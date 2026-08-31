"""Real capture campaign: wraps the EXISTING, already-validated B200 +
native-scan session mechanism (BleHybridCampaignManager) and the EXISTING
resumable offline replay (BleCaptureJobManager.start_offline_replay,
Fase 1) -- it reuses their MECHANISM only, never their scientific
vocabulary or dataset decisions, exactly like CaptureStage/EvidenceStage do
for a legacy capture picked by hand.

Every session always launches with campaign_intent=exploratory_target_search
and target={"kind":"any"}: which physical unit (if any) a packet belongs to
is decided entirely downstream, by THIS module's own AddressBinding +
Evidence Stage -- never by what the legacy campaign manager was told its
"target" was. This also sidesteps the legacy POSITIVE_TARGET_VALIDATION
requirement that a device be freshly re-discovered by a live native scan
right before the session starts, which would otherwise force an extra,
separate discovery step with its own timing race.

The "condicion experimental" (target physically on/off/present/absent) is
whatever the operator declares and physically arranges before clicking
launch -- this code has no way to verify or change the physical setup
itself, and does not pretend otherwise.

CAPTURE vs. REPLAY+EVIDENCE are deliberately separable, not just internally
factored: run_capture_only() holds the B200 for only as long as the actual
RF acquisition needs (seconds), while OFFLINE_REPLAY (decode) is the slow
part (can take many minutes) and never touches the B200 at all. An operator
capturing several devices in a hurry can run run_capture_only() repeatedly
without ever blocking on decode, then later call
run_replay_and_evidence_for_capture() for each capture_id whenever there's
time -- run_session() (capture + replay + evidence in one call) still exists
for callers that want the old, simpler all-in-one behavior.
"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

import numpy as np

ProgressHook = Callable[[str, float, str], None]

_HYBRID_TERMINAL = {"completed", "failed", "cancelled", "timed_out"}
_JOB_TERMINAL = {"completed", "failed", "cancelled"}
# Same terminal-state set as BleCaptureJobManager.TERMINAL -- duplicated
# rather than imported to keep this module's only dependency on that class
# to its public create()/get() methods, never its internals.
_CAPTURE_TERMINAL = {"completed", "failed", "cancelled", "timed_out"}
_BLE_CHANNEL_FREQUENCIES_HZ = {37: 2_402_000_000, 38: 2_426_000_000, 39: 2_480_000_000}

# A single offline-replay invocation stops after this many seconds of actual
# decode work and reports exit_status=PARTIAL with a checkpoint, rather than
# ever silently treating a partially-decoded capture as fully analyzed (a
# real capture's candidate backlog can take far longer than one HTTP-request
# lifetime to fully decode). The orchestrator resumes from checkpoint until
# exit_status=FULLY_PROCESSED, up to _MAX_REPLAY_RESUMES chunks, so evidence
# is only ever built from a complete decode of the capture.
_REPLAY_CHUNK_BUDGET_SECONDS = 1800.0
_MAX_REPLAY_RESUMES = 12

# A real-time USB3 RF stream can drop samples if the host briefly can't keep
# up (this environment's measured historical rate: ~46% of B200 captures,
# even in isolation) -- the worker correctly refuses to treat a
# dropped-sample capture as valid (job state -> "failed", error contains
# "CAPTURE_FAILED"). That is not a misconfiguration an operator can fix by
# reading an error message; it is exactly the kind of transient condition a
# plain retry resolves. Retried automatically here rather than surfaced,
# up to this many real capture attempts, so a routine RF hiccup never shows
# up as an error the operator has to act on.
_MAX_CAPTURE_ATTEMPTS = 6


class CampaignSessionError(Exception):
    pass


_TARGET_STATE_BY_PURPOSE = {
    "TARGET_DEVICE_ON": "POWERED_ON",
    "BACKGROUND_TARGET_OFF": "OPERATOR_DECLARED_POWERED_OFF_OR_REMOVED",
    # BACKGROUND_GENERAL/UNKNOWN_DEVICE_COLLECTION have no specific target
    # unit in question at all -- target_state stays None (not applicable),
    # never a fabricated POWERED_ON/OFF value for a unit that was never named.
}
_DATASET_ROLE_BY_PURPOSE = {
    "TARGET_DEVICE_ON": "POSITIVE_CANDIDATE",
    "BACKGROUND_TARGET_OFF": "NEGATIVE_CANDIDATE",
    "BACKGROUND_GENERAL": "NEGATIVE_CANDIDATE",
    "UNKNOWN_DEVICE_COLLECTION": "UNKNOWN_CANDIDATE",
}
_BACKGROUND_KIND_BY_PURPOSE = {
    "BACKGROUND_TARGET_OFF": "TARGET_DECLARED_OFF_OR_REMOVED",
    "BACKGROUND_GENERAL": "GENERAL_AMBIENT",
}
_POWER_STATE_BY_PURPOSE = {
    "TARGET_DEVICE_ON": "powered_on",
    "BACKGROUND_TARGET_OFF": "operator_declared_powered_off_or_removed",
    "BACKGROUND_GENERAL": "not_applicable_general_ambient",
    "UNKNOWN_DEVICE_COLLECTION": "not_applicable_unknown_device_collection",
}


class CampaignOrchestrator:
    def __init__(self, *, hybrid_manager: Any, capture_manager: Any, arbiter: Any, repository: Any) -> None:
        self.hybrid_manager = hybrid_manager
        self.capture_manager = capture_manager
        self.arbiter = arbiter
        self.repository = repository

    def resolve_device_id(self, requested_device_id: str | None = None) -> str:
        return self.capture_manager.resolve_device_id(requested_device_id)

    def _hybrid_payload(
        self, *, device_id: str, ble_channel: int, duration_seconds: float, gain_db: float,
        condition_label: str, physical_unit_id: str | None, project_id: str, campaign_id: str, session_index: int,
        power_state: str,
    ) -> dict[str, Any]:
        metadata = {
            "distance": "0.50 m", "orientation": "0", "location": "LAB-A",
            "physical_unit_id": physical_unit_id or "AMBIENT_UNKNOWN",
            "power_state": power_state,
            "execution_purpose": "EXPLORATORY_TARGET_SEARCH",
            "condition_id": condition_label,
            "project_id": project_id, "campaign_id": campaign_id,
            "operator_notes": f"BLE-RFFI Studio guided campaign, session {session_index}",
        }
        return {
            "device_id": device_id, "channel": ble_channel, "duration_seconds": duration_seconds,
            "gain_db": gain_db, "target": {"kind": "any"}, "campaign_intent": "exploratory_target_search",
            "experimental_metadata": metadata,
        }

    def _validate_and_derive(
        self, *, capture_purpose: str, physical_unit_id: str | None,
        operator_confirmed_target_absent: bool, isolation_declared: bool,
    ) -> tuple[str, str | None, str, str | None, str | None, bool]:
        if capture_purpose not in _DATASET_ROLE_BY_PURPOSE:
            raise CampaignSessionError(f"UNKNOWN_CAPTURE_PURPOSE:{capture_purpose}")

        if capture_purpose == "TARGET_DEVICE_ON" and not physical_unit_id:
            raise CampaignSessionError(
                "TARGET_DEVICE_ON_REQUIRES_A_PHYSICAL_UNIT_ID:capturing the target device means selecting which physical unit it is"
            )
        if capture_purpose == "BACKGROUND_TARGET_OFF" and not operator_confirmed_target_absent:
            raise CampaignSessionError(
                "BACKGROUND_TARGET_OFF_REQUIRES_OPERATOR_CONFIRMATION:the operator must explicitly confirm the target device "
                "was powered off or removed for the whole capture -- this is never inferred from the absence of a signal"
            )
        # Physical isolation and a specific target unit are TARGET_DEVICE_ON-
        # only concepts: isolation asserts "only this unit was transmitting
        # nearby", precisely the opposite of what a BACKGROUND_* capture is
        # for, and BACKGROUND_GENERAL/UNKNOWN_DEVICE_COLLECTION have no
        # specific unit in question at all. Forced off/None here rather than
        # trusted from the caller so a stale/incorrect frontend request can
        # never smuggle a positive label onto a background/unknown-device
        # session. BACKGROUND_TARGET_OFF's target_reference_id stays
        # optional -- the operator may declare "the target is off" without
        # pinning it to one specific registered unit.
        if capture_purpose != "TARGET_DEVICE_ON":
            isolation_declared = False

        target_state = _TARGET_STATE_BY_PURPOSE.get(capture_purpose)
        dataset_role = _DATASET_ROLE_BY_PURPOSE[capture_purpose]
        background_kind = _BACKGROUND_KIND_BY_PURPOSE.get(capture_purpose)
        target_reference_id = physical_unit_id if capture_purpose in ("TARGET_DEVICE_ON", "BACKGROUND_TARGET_OFF") else None
        return capture_purpose, target_state, dataset_role, background_kind, target_reference_id, isolation_declared

    def _start_hybrid_session(self, payload: dict[str, Any], report: Callable[[str, float, str], None]) -> dict[str, Any]:
        """BleHybridCampaignManager.start() can raise
        HYBRID_CAMPAIGN_ALREADY_RUNNING even for a legitimately free device: a
        just-finished attempt's background thread (its own `_run`) writes the
        terminal state (e.g. "failed") and only clears its `_active` flag
        afterward, in a separate step -- not atomically. Retrying
        immediately after observing that terminal state (as the RF-overflow
        retry loop above does, with no delay) can race that cleanup and hit
        this window. This is a real, observed startup race, never a genuine
        second concurrent session, so it is absorbed here with a short
        backoff and never counted against _MAX_CAPTURE_ATTEMPTS (that budget
        is for real RF acquisition failures, not this manager-internal
        timing gap)."""
        deadline = time.time() + 10.0
        while True:
            try:
                return self.hybrid_manager.start(payload)
            except RuntimeError as error:
                if "HYBRID_CAMPAIGN_ALREADY_RUNNING" not in str(error):
                    raise
                if time.time() >= deadline:
                    raise CampaignSessionError(f"HYBRID_CAMPAIGN_ALREADY_RUNNING:the previous attempt's cleanup never finished within 10s") from error
                report("LAUNCH_SESSION", 0.0, "Esperando a que finalice la limpieza de la sesion anterior antes de reintentar...")
                time.sleep(0.5)

    def _acquire_capture(
        self, *, resolved_device_id: str, ble_channel: int, duration_seconds: float, gain_db: float,
        condition_label: str, physical_unit_id: str | None, project_id: str, campaign_id: str,
        session_index: int, capture_purpose: str, progress: ProgressHook | None,
        cancel_event: threading.Event | None = None,
    ) -> tuple[str, str]:
        """Runs the real B200+native-scan session (with transient-RF-overflow
        retry), returning (session_id, capture_id). Never touches the offline
        replay/evidence pipeline -- callers decide separately whether/when to
        run that (see run_capture_only vs. run_session).

        `cancel_event`, when set by the caller (an operator-requested stop --
        see ScientificResultsJobManager.cancel_job), stops the real B200
        session via hybrid_manager.stop() (the same mechanism the manager
        already uses internally) rather than abandoning it: the RF hardware
        is released properly instead of continuing to run unobserved."""
        def report(phase: str, fraction: float, message: str) -> None:
            if progress:
                progress(phase, fraction, message)

        if cancel_event is not None and cancel_event.is_set():
            raise CampaignSessionError("CANCELLED_BY_OPERATOR")

        payload = self._hybrid_payload(
            device_id=resolved_device_id, ble_channel=ble_channel, duration_seconds=duration_seconds, gain_db=gain_db,
            condition_label=condition_label, physical_unit_id=physical_unit_id,
            project_id=project_id, campaign_id=campaign_id, session_index=session_index,
            power_state=_POWER_STATE_BY_PURPOSE.get(capture_purpose, "unknown"),
        )

        session: dict[str, Any] | None = None
        for capture_attempt in range(1, _MAX_CAPTURE_ATTEMPTS + 1):
            report("LAUNCH_SESSION", 0.0, f"Iniciando sesion hibrida (B200 + escaneo nativo Windows), intento {capture_attempt}/{_MAX_CAPTURE_ATTEMPTS}")
            session = self._start_hybrid_session(payload, report)
            session_id = session["session_id"]

            while session.get("state") not in _HYBRID_TERMINAL:
                if cancel_event is not None and cancel_event.is_set():
                    self.hybrid_manager.stop(session_id)
                    deadline = time.time() + 15.0
                    while session.get("state") not in _HYBRID_TERMINAL and time.time() < deadline:
                        time.sleep(0.5)
                        session = self.hybrid_manager.get(session_id)
                    raise CampaignSessionError("CANCELLED_BY_OPERATOR")
                time.sleep(1.0)
                session = self.hybrid_manager.get(session_id)
                report("CAPTURING", 0.25, f"Sesion {session_id}: {session.get('state')} (intento {capture_attempt}/{_MAX_CAPTURE_ATTEMPTS})")

            if session.get("state") == "completed":
                break
            is_transient_rf_failure = "CAPTURE_FAILED" in str(session.get("error") or "")
            if not is_transient_rf_failure or capture_attempt == _MAX_CAPTURE_ATTEMPTS:
                raise CampaignSessionError(f"HYBRID_SESSION_{str(session.get('state', 'unknown')).upper()}:{session.get('error')}")
            report("CAPTURING", 0.1, f"Adquisicion RF interrumpida (overflow/discontinuidad transitoria de USB) -- reintentando automaticamente ({capture_attempt}/{_MAX_CAPTURE_ATTEMPTS})")

        return session["session_id"], session["capture_id"]

    # ------------------------------------------------------------------
    # Guided capture: probe with short, throwaway B200 captures BEFORE
    # committing to the real, saved capture -- see run_guided_capture_only()
    # below for the full rationale. Deliberately the "least costly, least
    # risky" option (short repeated probes) rather than a continuous stream:
    # every probe reuses the EXACT same capture_manager.create()/get() path
    # BleHybridCampaignManager itself already calls internally for its own
    # B200 acquisition (see ble_hybrid_campaign_manager.py's _run), so this
    # is not a new, separate hardware-access path -- just the same one, run
    # for 1 second at a time instead of the full requested duration.
    # ------------------------------------------------------------------

    _PROBE_BLOCK_MIN_SAMPLES = 4  # below this, treat as "insufficient data" rather than falsely reporting "quiet"

    def _probe_energy_power(self, iq_path: Path, sample_rate_sps: float) -> np.ndarray | None:
        values = np.fromfile(iq_path, dtype=np.complex64)
        block = max(64, int(sample_rate_sps / 100_000))
        count = len(values) // block
        if count < self._PROBE_BLOCK_MIN_SAMPLES:
            return None
        return np.mean(np.abs(values[: count * block].reshape(count, block)) ** 2, axis=1)

    def _probe_has_energy(self, iq_path: Path, sample_rate_sps: float) -> bool:
        """Same energy-threshold math as ble_sdr_capture_worker.detect_bursts()
        and spectrum_stream_worker.py's _detect_energy_bursts() -- a real BLE
        advertisement burst rising above the local noise floor. Used to wait
        for "the device I just turned on is really transmitting"."""
        power = self._probe_energy_power(iq_path, sample_rate_sps)
        if power is None:
            return False
        noise = float(np.median(power))
        mad = float(np.median(np.abs(power - noise)))
        threshold = max(noise * 4.0, noise + 8.0 * mad, 1e-12)
        return bool(np.any(power > threshold))

    def _probe_has_destructive_signal(self, iq_path: Path, sample_rate_sps: float) -> bool:
        """Deliberately a DIFFERENT, much higher bar than _probe_has_energy:
        ordinary BLE traffic (including ambient IoT the operator cannot turn
        off -- see the noisy-environment guidance elsewhere in this module's
        README) is expected and fine in a BACKGROUND capture; what actually
        ruins one is a signal strong enough to saturate/clip the receiver
        (the measured ~46% RF-overflow retry rate this module already works
        around). Checks raw sample magnitude against near-full-scale for
        cf32 (nominally [-1, 1]), not the burst-detection noise threshold."""
        values = np.fromfile(iq_path, dtype=np.complex64)
        if values.size < self._PROBE_BLOCK_MIN_SAMPLES:
            return False
        return bool(np.max(np.abs(values)) > 0.9)

    def _probe_for_signal(
        self, *, resolved_device_id: str, ble_channel: int, gain_db: float, project_id: str, campaign_id: str,
        check: Callable[[Path, float], bool], want: bool, probe_duration_seconds: float, max_probes: int,
        phase: str, progress: ProgressHook | None,
    ) -> bool:
        sample_rate_sps = 4_000_000.0
        for attempt in range(1, max_probes + 1):
            request = {
                "device_id": resolved_device_id, "ble_channel": ble_channel,
                "center_frequency_hz": _BLE_CHANNEL_FREQUENCIES_HZ[ble_channel],
                "sample_rate_sps": int(sample_rate_sps), "bandwidth_hz": 2_000_000,
                "gain_mode": "manual", "gain_db": float(gain_db), "antenna": "RX2",
                "duration_seconds": probe_duration_seconds, "sample_format": "cf32_le",
                "purpose": "BLE-RFFI Studio guided capture probe -- never kept, deleted immediately after check",
                "controlled_transmitter_state": "unknown", "operator_confirmed": False,
                "capture_role": "controlled_transmitter_active_B",
                "experimental_metadata": {"project_id": project_id, "campaign_id": campaign_id, "guided_capture_probe": True},
            }
            job = self.capture_manager.create(request)
            capture_id = job["capture_id"]
            while job.get("state") not in _CAPTURE_TERMINAL:
                time.sleep(0.2)
                job = self.capture_manager.get(capture_id)

            observed = False
            if job.get("state") == "completed":
                iq_path = self.capture_manager.root / capture_id / f"{capture_id}.sigmf-data"
                try:
                    observed = check(iq_path, sample_rate_sps)
                except Exception:
                    observed = False
            # Always cleaned up immediately -- a probe is never part of any
            # dataset and must never linger in the legacy capture list.
            try:
                self.repository.delete_legacy_capture(capture_id)
            except Exception:
                pass

            if progress:
                progress(phase, min(0.45, 0.05 + attempt / max_probes * 0.4), f"Sondeo {attempt}/{max_probes}: {'senal detectada' if observed else 'sin senal'}")
            if observed == want:
                return True
        return False

    def run_guided_capture_only(
        self,
        *,
        ble_channel: int,
        duration_seconds: float,
        gain_db: float,
        condition_label: str,
        physical_unit_id: str | None,
        project_id: str,
        campaign_id: str,
        session_index: int,
        device_id: str | None = None,
        isolation_declared: bool = False,
        capture_purpose: str = "TARGET_DEVICE_ON",
        operator_confirmed_target_absent: bool = False,
        probe_duration_seconds: float = 1.0,
        probe_timeout_seconds: float = 30.0,
        progress: ProgressHook | None = None,
    ) -> dict[str, Any]:
        """Guided capture: for TARGET_DEVICE_ON, waits (via short, throwaway
        probe captures -- see _probe_for_signal) until the B200 itself
        confirms a real energy burst before recording the real, saved
        capture -- catching "I forgot to turn it on" or "it's too far from
        the antenna" before spending the full capture duration on nothing.
        For BACKGROUND_TARGET_OFF/BACKGROUND_GENERAL, waits until no
        destructively strong signal is present (near-full-scale amplitude,
        i.e. real overflow/clipping risk) -- deliberately NOT a "totally
        quiet" requirement, since ordinary ambient BLE traffic the operator
        cannot silence is expected and fine for a background sample.
        UNKNOWN_DEVICE_COLLECTION has no probe defined yet and goes straight
        to the real capture, same as run_capture_only().
        """
        def report(phase: str, fraction: float, message: str) -> None:
            if progress:
                progress(phase, fraction, message)

        capture_purpose, target_state, dataset_role, background_kind, target_reference_id, isolation_declared = self._validate_and_derive(
            capture_purpose=capture_purpose, physical_unit_id=physical_unit_id,
            operator_confirmed_target_absent=operator_confirmed_target_absent, isolation_declared=isolation_declared,
        )

        resolved_device_id = self.resolve_device_id(device_id)
        operation_id = f"campaign-guided-{uuid.uuid4().hex[:10]}"
        max_probes = max(1, int(probe_timeout_seconds / max(0.1, probe_duration_seconds)))
        lease_seconds = max(600.0, duration_seconds * 6 + probe_timeout_seconds * 3)
        acquired = self.arbiter.acquire(resolved_device_id, owner="ble_rffi_studio_campaign", operation_id=operation_id, lease_seconds=lease_seconds)
        if not acquired.granted:
            raise CampaignSessionError(f"B200_BUSY:held_by={acquired.current_owner}:operation={acquired.current_operation_id}")

        try:
            if capture_purpose == "TARGET_DEVICE_ON":
                report("PROBE_BASELINE", 0.02, "Comprobando linea base antes de pedirte que enciendas el dispositivo...")
                # Best-effort only -- a noisy baseline is not fatal (ambient
                # BLE nearby is normal), this is purely informational context
                # for what follows, never a hard gate.
                self._probe_for_signal(
                    resolved_device_id=resolved_device_id, ble_channel=ble_channel, gain_db=gain_db,
                    project_id=project_id, campaign_id=campaign_id, check=self._probe_has_energy, want=False,
                    probe_duration_seconds=probe_duration_seconds, max_probes=max(1, max_probes // 5),
                    phase="PROBE_BASELINE", progress=progress,
                )
                report("WAITING_FOR_DEVICE", 0.1, "AHORA ENCIENDE EL DISPOSITIVO -- esperando que el B200 detecte una senal real...")
                detected = self._probe_for_signal(
                    resolved_device_id=resolved_device_id, ble_channel=ble_channel, gain_db=gain_db,
                    project_id=project_id, campaign_id=campaign_id, check=self._probe_has_energy, want=True,
                    probe_duration_seconds=probe_duration_seconds, max_probes=max_probes,
                    phase="WAITING_FOR_DEVICE", progress=progress,
                )
                if not detected:
                    raise CampaignSessionError(
                        f"GUIDED_CAPTURE_NO_SIGNAL_DETECTED:no se detecto ninguna senal real en {probe_timeout_seconds:.0f}s -- "
                        "verifica que el dispositivo este encendido, cerca de la antena, y en el canal correcto"
                    )
            elif capture_purpose in ("BACKGROUND_TARGET_OFF", "BACKGROUND_GENERAL"):
                report("PROBE_ENVIRONMENT", 0.1, "Comprobando que no haya ninguna senal demasiado potente antes de capturar el entorno...")
                clean = self._probe_for_signal(
                    resolved_device_id=resolved_device_id, ble_channel=ble_channel, gain_db=gain_db,
                    project_id=project_id, campaign_id=campaign_id, check=self._probe_has_destructive_signal, want=False,
                    probe_duration_seconds=probe_duration_seconds, max_probes=max_probes,
                    phase="PROBE_ENVIRONMENT", progress=progress,
                )
                if not clean:
                    raise CampaignSessionError(
                        f"GUIDED_CAPTURE_ENVIRONMENT_TOO_HOT:se sigue detectando una senal muy potente (riesgo de saturar la captura) tras "
                        f"{probe_timeout_seconds:.0f}s -- aleja o apaga lo que este transmitiendo tan cerca de la antena"
                    )

            report("REAL_CAPTURE", 0.5, "Confirmado -- lanzando la captura real que se va a guardar...")
            session_id, capture_id = self._acquire_capture(
                resolved_device_id=resolved_device_id, ble_channel=ble_channel, duration_seconds=duration_seconds,
                gain_db=gain_db, condition_label=condition_label, physical_unit_id=physical_unit_id,
                project_id=project_id, campaign_id=campaign_id, session_index=session_index,
                capture_purpose=capture_purpose, progress=progress,
            )
            report("CAPTURE_STAGE", 0.9, f"Construyendo CaptureRecord para {capture_id}")
            self.repository.build_capture(
                capture_id=capture_id, project_id=project_id, campaign_id=campaign_id, execution_id=session_id, session_id=session_id,
                isolation_declared_physical_unit_id=physical_unit_id if isolation_declared else None,
                capture_purpose=capture_purpose, target_state=target_state, background_kind=background_kind,
                target_reference_id=target_reference_id, dataset_role=dataset_role,
            )
            report("DONE", 1.0, "Captura guiada completada -- replay y evidencia pendientes (aplicar mas tarde)")
            return {
                "session_id": session_id, "capture_id": capture_id,
                "condition_label": condition_label, "physical_unit_id": physical_unit_id,
                "capture_purpose": capture_purpose, "target_state": target_state, "dataset_role": dataset_role,
            }
        finally:
            self.arbiter.release(resolved_device_id, owner="ble_rffi_studio_campaign", operation_id=operation_id)

    def _run_replay_and_evidence(
        self, *, capture: Any, capture_id: str, project_id: str, ble_channel: int, progress: ProgressHook | None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """The slow part: resumable OFFLINE_REPLAY (decode) until
        FULLY_PROCESSED, then Evidence Stage. Pure CPU work on an
        already-recorded IQ file -- never touches the B200, so callers never
        need to hold the device arbiter lease for this.

        `cancel_event`, when set, stops the in-flight replay job via
        capture_manager.cancel_offline_replay() -- same rationale as
        _acquire_capture's cancel_event: a real, acknowledged stop rather
        than an abandoned background job."""
        def report(phase: str, fraction: float, message: str) -> None:
            if progress:
                progress(phase, fraction, message)

        report("OFFLINE_REPLAY", 0.6, "Ejecutando replay resumible (puede tardar varios minutos)")
        replay_job = self.capture_manager.start_offline_replay(capture_id, {"job_time_budget_seconds": _REPLAY_CHUNK_BUDGET_SECONDS})
        replay_run_id = replay_job["replay_run_id"]
        replay_state = replay_job
        for resume_attempt in range(_MAX_REPLAY_RESUMES):
            while replay_state.get("state") not in _JOB_TERMINAL:
                if cancel_event is not None and cancel_event.is_set():
                    self.capture_manager.cancel_offline_replay(capture_id, replay_run_id)
                    deadline = time.time() + 15.0
                    while replay_state.get("state") not in _JOB_TERMINAL and time.time() < deadline:
                        time.sleep(0.5)
                        replay_state = self.capture_manager.offline_replay_job(capture_id, replay_run_id)
                    raise CampaignSessionError("CANCELLED_BY_OPERATOR")
                time.sleep(2.0)
                replay_state = self.capture_manager.offline_replay_job(capture_id, replay_run_id)
                coverage = ((replay_state.get("progress") or {}).get("coverage_percentage"))
                report("OFFLINE_REPLAY", 0.7, f"Replay {replay_run_id}: {replay_state.get('state')}" + (f" ({coverage:.1f}% procesado)" if coverage is not None else ""))
            if replay_state.get("state") != "completed":
                raise CampaignSessionError(f"OFFLINE_REPLAY_{str(replay_state.get('state', 'unknown')).upper()}:{replay_state.get('error')}")
            exit_status = (replay_state.get("result") or {}).get("exit_status")
            # Real-hardware bug fix (2026-08-13): COMPLETED_WITH_FAILED_SEGMENTS
            # is a real, documented terminal execution_status (see
            # ble_offline_replay.py / capture.py's own ReplayStatus / this
            # package's README) -- every segment was attempted (no
            # pending_segments), some individually failed decode/timeout,
            # which is an expected, normal outcome for real RF, never a
            # reason to abort the whole session. It was previously treated
            # as OFFLINE_REPLAY_UNEXPECTED_EXIT_STATUS, meaning any real
            # capture with even one failed segment could never reach
            # evidence-building at all. Dataset eligibility for the affected
            # segments is still correctly gated downstream by
            # scientific_completion_status/pending_segments, untouched here.
            if exit_status in ("FULLY_PROCESSED", "COMPLETED_WITH_FAILED_SEGMENTS"):
                break
            if exit_status != "PARTIAL":
                raise CampaignSessionError(f"OFFLINE_REPLAY_UNEXPECTED_EXIT_STATUS:{exit_status}")
            report("OFFLINE_REPLAY", 0.7, f"Replay {replay_run_id}: presupuesto de tiempo agotado, retomando desde el ultimo checkpoint (intento {resume_attempt + 2})")
            replay_state = self.capture_manager.start_offline_replay(capture_id, {"replay_run_id": replay_run_id, "job_time_budget_seconds": _REPLAY_CHUNK_BUDGET_SECONDS})
        else:
            raise CampaignSessionError(f"OFFLINE_REPLAY_DID_NOT_REACH_FULLY_PROCESSED_AFTER_{_MAX_REPLAY_RESUMES}_RESUMES:{replay_run_id}")

        report("EVIDENCE", 0.85, "Construyendo evidencia (ExampleRecord + ExampleAnnotation)")
        evidence_summary = self.repository.build_evidence(capture=capture, project_id=project_id, ble_channel=ble_channel, replay_run_id=replay_run_id)
        report("DONE", 1.0, "Replay y evidencia completados")
        return {"replay_run_id": replay_run_id, "evidence_summary": evidence_summary}

    def run_capture_only(
        self,
        *,
        ble_channel: int,
        duration_seconds: float,
        gain_db: float,
        condition_label: str,
        physical_unit_id: str | None,
        project_id: str,
        campaign_id: str,
        session_index: int,
        device_id: str | None = None,
        isolation_declared: bool = False,
        capture_purpose: str = "TARGET_DEVICE_ON",
        operator_confirmed_target_absent: bool = False,
        progress: ProgressHook | None = None,
    ) -> dict[str, Any]:
        """Real B200 acquisition only -- builds the CaptureRecord and stops.
        No OFFLINE_REPLAY, no evidence: those can be run later, for any
        number of captures, via run_replay_and_evidence_for_capture(), once
        there's time for the slow decode. Releases the B200 arbiter lease as
        soon as the RF acquisition itself is done, letting the operator
        capture another device right away instead of waiting on decode."""
        def report(phase: str, fraction: float, message: str) -> None:
            if progress:
                progress(phase, fraction, message)

        capture_purpose, target_state, dataset_role, background_kind, target_reference_id, isolation_declared = self._validate_and_derive(
            capture_purpose=capture_purpose, physical_unit_id=physical_unit_id,
            operator_confirmed_target_absent=operator_confirmed_target_absent, isolation_declared=isolation_declared,
        )

        resolved_device_id = self.resolve_device_id(device_id)
        operation_id = f"campaign-session-{uuid.uuid4().hex[:10]}"
        lease_seconds = max(300.0, duration_seconds * 6)
        acquired = self.arbiter.acquire(resolved_device_id, owner="ble_rffi_studio_campaign", operation_id=operation_id, lease_seconds=lease_seconds)
        if not acquired.granted:
            raise CampaignSessionError(f"B200_BUSY:held_by={acquired.current_owner}:operation={acquired.current_operation_id}")

        try:
            session_id, capture_id = self._acquire_capture(
                resolved_device_id=resolved_device_id, ble_channel=ble_channel, duration_seconds=duration_seconds,
                gain_db=gain_db, condition_label=condition_label, physical_unit_id=physical_unit_id,
                project_id=project_id, campaign_id=campaign_id, session_index=session_index,
                capture_purpose=capture_purpose, progress=progress,
            )
            report("CAPTURE_STAGE", 0.9, f"Construyendo CaptureRecord para {capture_id}")
            self.repository.build_capture(
                capture_id=capture_id, project_id=project_id, campaign_id=campaign_id, execution_id=session_id, session_id=session_id,
                isolation_declared_physical_unit_id=physical_unit_id if isolation_declared else None,
                capture_purpose=capture_purpose, target_state=target_state, background_kind=background_kind,
                target_reference_id=target_reference_id, dataset_role=dataset_role,
            )
            report("DONE", 1.0, "Captura completada -- replay y evidencia pendientes (aplicar mas tarde)")
            return {
                "session_id": session_id, "capture_id": capture_id,
                "condition_label": condition_label, "physical_unit_id": physical_unit_id,
                "capture_purpose": capture_purpose, "target_state": target_state, "dataset_role": dataset_role,
            }
        finally:
            self.arbiter.release(resolved_device_id, owner="ble_rffi_studio_campaign", operation_id=operation_id)

    def run_replay_and_evidence_for_capture(
        self, *, capture_id: str, project_id: str, ble_channel: int, progress: ProgressHook | None = None,
    ) -> dict[str, Any]:
        """Runs OFFLINE_REPLAY + Evidence Stage for a CaptureRecord that
        already exists (built earlier by run_capture_only, run_session, or a
        manually-selected legacy capture). Never touches the B200 or the
        device arbiter -- this is pure CPU decode work on an already-recorded
        file, so it can run at any time, independent of any live capture."""
        capture = self.repository.get_capture(capture_id)
        if capture is None:
            raise CampaignSessionError(f"CAPTURE_NOT_BUILT_YET:{capture_id}:build the CaptureRecord before requesting replay/evidence for it")
        tail = self._run_replay_and_evidence(capture=capture, capture_id=capture_id, project_id=project_id, ble_channel=ble_channel, progress=progress)
        return {"capture_id": capture_id, **tail}

    def run_session(
        self,
        *,
        ble_channel: int,
        duration_seconds: float,
        gain_db: float,
        condition_label: str,
        physical_unit_id: str | None,
        project_id: str,
        campaign_id: str,
        session_index: int,
        device_id: str | None = None,
        isolation_declared: bool = False,
        capture_purpose: str = "TARGET_DEVICE_ON",
        operator_confirmed_target_absent: bool = False,
        progress: ProgressHook | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Capture + OFFLINE_REPLAY + evidence in one call -- the original,
        all-in-one behavior. Prefer run_capture_only() + a later
        run_replay_and_evidence_for_capture() when capturing several devices
        in a hurry (this call holds the B200 arbiter lease for the ENTIRE
        decode, not just the RF acquisition).

        `cancel_event`: optional, operator-controlled stop signal checked
        during both the RF-acquisition and the replay/decode phases (see
        _acquire_capture/_run_replay_and_evidence). The arbiter lease is
        always released via the existing finally block below, cancelled or
        not, so a stopped session never leaves the B200 marked busy."""
        capture_purpose, target_state, dataset_role, background_kind, target_reference_id, isolation_declared = self._validate_and_derive(
            capture_purpose=capture_purpose, physical_unit_id=physical_unit_id,
            operator_confirmed_target_absent=operator_confirmed_target_absent, isolation_declared=isolation_declared,
        )

        resolved_device_id = self.resolve_device_id(device_id)
        operation_id = f"campaign-session-{uuid.uuid4().hex[:10]}"
        lease_seconds = max(300.0, duration_seconds * 6)
        acquired = self.arbiter.acquire(resolved_device_id, owner="ble_rffi_studio_campaign", operation_id=operation_id, lease_seconds=lease_seconds)
        if not acquired.granted:
            raise CampaignSessionError(f"B200_BUSY:held_by={acquired.current_owner}:operation={acquired.current_operation_id}")

        try:
            session_id, capture_id = self._acquire_capture(
                resolved_device_id=resolved_device_id, ble_channel=ble_channel, duration_seconds=duration_seconds,
                gain_db=gain_db, condition_label=condition_label, physical_unit_id=physical_unit_id,
                project_id=project_id, campaign_id=campaign_id, session_index=session_index,
                capture_purpose=capture_purpose, progress=progress, cancel_event=cancel_event,
            )
            if progress:
                progress("CAPTURE_STAGE", 0.5, f"Construyendo CaptureRecord para {capture_id}")
            # The hybrid session_id IS "which hybrid acquisition session
            # produced this capture" -- pass it explicitly as both
            # execution_id and session_id rather than relying on
            # CaptureStage's manifest/replay inference, since no offline
            # replay exists yet at this point (it runs next) and the raw
            # capture's own experimental_metadata never records a session_id
            # (the hybrid manager only generates one after this payload was
            # already sent).
            capture = self.repository.build_capture(
                capture_id=capture_id, project_id=project_id, campaign_id=campaign_id, execution_id=session_id, session_id=session_id,
                isolation_declared_physical_unit_id=physical_unit_id if isolation_declared else None,
                capture_purpose=capture_purpose, target_state=target_state, background_kind=background_kind,
                target_reference_id=target_reference_id, dataset_role=dataset_role,
            )

            tail = self._run_replay_and_evidence(capture=capture, capture_id=capture_id, project_id=project_id, ble_channel=ble_channel, progress=progress, cancel_event=cancel_event)

            return {
                "session_id": session_id, "capture_id": capture_id, "replay_run_id": tail["replay_run_id"],
                "condition_label": condition_label, "physical_unit_id": physical_unit_id,
                "capture_purpose": capture_purpose, "target_state": target_state, "dataset_role": dataset_role,
                "evidence_summary": tail["evidence_summary"],
            }
        finally:
            self.arbiter.release(resolved_device_id, owner="ble_rffi_studio_campaign", operation_id=operation_id)
