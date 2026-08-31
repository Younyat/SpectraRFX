from __future__ import annotations

import base64
import json
import os
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from app.config.settings import settings as app_settings
from app.infrastructure.ble.capture.ble_live_burst_decoder import live_decode_burst, live_decode_enabled
from app.infrastructure.sdr.rf_safety import validate_frequency_window, validate_gain

# Same well-known BLE primary-advertising channel/frequency mapping
# duplicated (not imported) across this codebase wherever a small, frozen
# constant is cheaper than a cross-module dependency (see
# campaign_orchestrator.py's identical constant for the same reasoning).
_BLE_CHANNEL_FREQUENCIES_HZ = {37: 2_402_000_000, 38: 2_426_000_000, 39: 2_480_000_000}

# ble-worker-lab's ReceiverConfig.sample_rate_hz defaults to (and
# validate_receiver_config hard-rejects any other value than) 4,000,000 Hz --
# but live_decode_burst() never passes the burst's ACTUAL sample rate into
# ReceiverConfig, so that validation silently never triggers even when the
# live spectrum view is tuned to a different span (e.g. the general-purpose
# analyzer's default of 2 MHz). The receiver then applies 4 MSps timing math
# to samples that aren't actually at that rate, guaranteeing decode failure
# on every burst regardless of signal quality -- confirmed live: real BLE
# packets decode successfully the instant span is corrected to 4 MHz.
# Checked here, before ever calling live_decode_burst(), so a mismatch
# surfaces as an honest, actionable outcome instead of a misleading
# NO_BLE_PACKET_DECODED that looks identical to "no device nearby".
_BLE_LIVE_DECODE_REQUIRED_SAMPLE_RATE_HZ = 4_000_000


def _resolve_ble_channel_for_burst(center_frequency_hz: float) -> int:
    return min(_BLE_CHANNEL_FREQUENCIES_HZ, key=lambda ch: abs(_BLE_CHANNEL_FREQUENCIES_HZ[ch] - center_frequency_hz))


class RealSpectrumStream:
    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._latest_frame: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._config_key: tuple | None = None
        self._runtime_key: tuple | None = None
        self._exclusive_reason: str | None = None
        self._lock = threading.Lock()

        # BLE-RFFI Studio "Live Monitor model check" (see spectrum_stream_worker.py's
        # ble_live_check_enabled) -- entirely additive, off by default, never
        # touched by any existing spectrum/demodulation code path.
        # _ble_live_check_enabled lives HERE (not just in the worker
        # subprocess) so a later, unrelated settings change that respawns the
        # worker (which always starts with it back off) can transparently
        # re-send the toggle instead of silently losing it.
        # Multiple bundles can be watched at once (real request: several
        # already-good per-device detectors running side by side so the
        # operator sees WHICH device, if any, is on right now, instead of
        # forcing a single multi-class model to always guess one of N known
        # devices even when none are actually present -- see backend/README.md's
        # device-scrubbing section for why a single combined classifier
        # cannot represent "none of these"). Every burst is scored against
        # every currently-enabled bundle_id.
        self._ble_live_check_enabled = False
        self._live_check_bundle_ids: set[str] = set()
        self._live_check_repository: Any | None = None
        self._pending_burst: dict[str, Any] | None = None
        self._latest_live_check_results: dict[str, dict[str, Any]] = {}
        self._burst_event = threading.Event()
        threading.Thread(target=self._live_check_worker_loop, daemon=True).start()

        # AI Research Plugin LIVE inference (additive, opt-in): on-demand raw
        # I/Q snapshots, keyed by request_id (not a single slot like
        # _pending_burst) since a caller is synchronously waiting for THIS
        # specific request's answer, not just "whatever the worker most
        # recently emitted" -- see capture_live_iq_snapshot() below.
        self._pending_iq_snapshots: dict[str, dict[str, Any]] = {}
        self._iq_snapshot_event = threading.Event()

    def get_latest(self, analyzer_settings) -> dict:
        self.ensure_started(analyzer_settings)
        with self._lock:
            if self._latest_frame is not None:
                return dict(self._latest_frame)
            return {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "center_frequency_hz": analyzer_settings.frequency.center_frequency_hz,
                "span_hz": analyzer_settings.frequency.sample_rate_hz,
                "frequencies_hz": [],
                "levels_db": [],
                "source": "real_sdr_pending",
                "error": self._last_error or "Waiting for first real SDR frame",
            }

    def ensure_started(self, analyzer_settings) -> None:
        with self._lock:
            if self._exclusive_reason is not None:
                self._last_error = self._exclusive_reason
                return

        config_key = self._make_config_key(analyzer_settings)
        runtime_key = self._make_runtime_key(analyzer_settings)
        if self._process is not None and self._process.poll() is None:
            if self._config_key == config_key:
                if self._runtime_key != runtime_key:
                    if self._send_update(analyzer_settings):
                        self._runtime_key = runtime_key
                        self._latest_frame = None
                        self._last_error = None
                        return
                    self.stop()
                else:
                    return

        self.stop()
        self._config_key = config_key
        self._runtime_key = runtime_key
        self._latest_frame = None
        self._last_error = None

        try:
            validate_frequency_window(
                analyzer_settings.frequency.center_frequency_hz,
                analyzer_settings.frequency.sample_rate_hz,
            )
            validate_gain(analyzer_settings.gain.gain_db)
        except ValueError as exc:
            self._last_error = str(exc)
            return

        python_exe = os.environ.get("RADIOCONDA_PYTHON", r"C:\Users\Usuario\radioconda\python.exe")
        backend_root = app_settings.storage.app_root.parent
        script_path = backend_root / "tools" / "spectrum_stream_worker.py"

        if not Path(python_exe).exists():
            self._last_error = f"RadioConda Python not found: {python_exe}"
            return
        if not script_path.exists():
            self._last_error = f"Spectrum stream worker not found: {script_path}"
            return

        command = [
            python_exe,
            "-u",
            str(script_path),
            "--freq",
            f"{analyzer_settings.frequency.center_frequency_hz / 1e6:.9f}",
            "--sample-rate",
            str(float(analyzer_settings.frequency.sample_rate_hz)),
            "--span-hz",
            str(float(analyzer_settings.frequency.span_hz)),
            "--gain",
            str(float(analyzer_settings.gain.gain_db)),
            "--antenna",
            app_settings.default_device.antenna,
            "--device-addr",
            app_settings.default_device.device_args,
            "--fft-size",
            str(int(analyzer_settings.resolution.fft_size)),
            "--max-fft-size",
            os.environ.get("REAL_SDR_MAX_FFT_SIZE", "65536"),
            "--rbw",
            str(float(analyzer_settings.resolution.rbw_hz)),
            "--vbw",
            str(float(analyzer_settings.resolution.vbw_hz)),
            "--fps",
            os.environ.get("REAL_SDR_FPS", "10"),
        ]

        try:
            self._process = subprocess.Popen(
                command,
                cwd=str(backend_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                text=True,
                bufsize=1,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception as exc:
            self._last_error = str(exc)
            self._process = None
            return

        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        # A brand-new worker subprocess always starts with
        # ble_live_check_enabled=False (see spectrum_stream_worker.py's
        # RuntimeConfig.__init__) -- if the feature was already active before
        # some unrelated settings change forced a respawn here, re-assert it
        # instead of silently losing the toggle.
        if self._ble_live_check_enabled:
            self._send_raw_command({"command": "update", "ble_live_check_enabled": True})

    def stop(self) -> None:
        if self._process is not None and self._process.poll() is None:
            if self._process.stdin is not None:
                try:
                    self._process.stdin.close()
                except Exception:
                    pass
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None

    def apply_settings(self, analyzer_settings) -> None:
        self.ensure_started(analyzer_settings)

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def begin_exclusive_operation(self, reason: str) -> None:
        self.stop()
        with self._lock:
            self._exclusive_reason = reason
            self._latest_frame = None
            self._last_error = reason

    def end_exclusive_operation(self) -> None:
        with self._lock:
            self._exclusive_reason = None

    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                frame = json.loads(line)
            except json.JSONDecodeError:
                continue
            with self._lock:
                if frame.get("source") == "real_sdr_error":
                    self._last_error = frame.get("error", "Unknown SDR error")
                elif frame.get("source") == "ble_rffi_iq_burst":
                    # Single pending slot, by design (see class docstring
                    # note above): a newer burst overwrites an older one that
                    # the inference worker hasn't gotten to yet, instead of
                    # queueing up staleness. Never touches _latest_frame /
                    # _last_error -- the normal spectrum trace is completely
                    # unaffected by this branch.
                    self._pending_burst = frame
                    self._burst_event.set()
                elif frame.get("source") == "ble_rffi_burst_detection_error":
                    # Non-fatal by design: a failure in the opt-in BLE burst
                    # detector must never surface as a spectrum-stream error
                    # (_last_error) or interrupt the live trace.
                    pass
                elif frame.get("source") == "iq_snapshot":
                    # Keyed by request_id (not a single overwriting slot) --
                    # never touches _latest_frame/_last_error, so the normal
                    # spectrum trace is completely unaffected.
                    request_id = frame.get("request_id")
                    if isinstance(request_id, str):
                        self._pending_iq_snapshots[request_id] = frame
                        self._iq_snapshot_event.set()
                else:
                    self._latest_frame = frame
                    self._last_error = None

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            line = line.strip()
            if line:
                with self._lock:
                    self._last_error = line

    def _make_config_key(self, analyzer_settings) -> tuple:
        return (
            app_settings.default_device.antenna,
            app_settings.default_device.device_args,
        )

    def _make_runtime_key(self, analyzer_settings) -> tuple:
        return (
            float(analyzer_settings.frequency.center_frequency_hz),
            float(analyzer_settings.frequency.sample_rate_hz),
            float(analyzer_settings.frequency.span_hz),
            float(analyzer_settings.gain.gain_db),
            int(analyzer_settings.resolution.fft_size),
            float(analyzer_settings.resolution.rbw_hz),
            float(analyzer_settings.resolution.vbw_hz),
        )

    def _send_update(self, analyzer_settings) -> bool:
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            return False

        command = {
            "command": "update",
            "center_freq_hz": float(analyzer_settings.frequency.center_frequency_hz),
            "sample_rate_hz": float(analyzer_settings.frequency.sample_rate_hz),
            "span_hz": float(analyzer_settings.frequency.span_hz),
            "gain_db": float(analyzer_settings.gain.gain_db),
            "fft_size": int(analyzer_settings.resolution.fft_size),
            "rbw_hz": float(analyzer_settings.resolution.rbw_hz),
            "vbw_hz": float(analyzer_settings.resolution.vbw_hz),
        }

        try:
            process.stdin.write(json.dumps(command) + "\n")
            process.stdin.flush()
            return True
        except Exception as exc:
            self._last_error = str(exc)
            return False

    def _send_raw_command(self, command: dict[str, Any]) -> bool:
        process = self._process
        if process is None or process.poll() is not None or process.stdin is None:
            return False
        try:
            process.stdin.write(json.dumps(command) + "\n")
            process.stdin.flush()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # AI Research Plugin LIVE inference -- entirely additive on top of the
    # spectrum stream above. Requests a bounded, one-shot raw I/Q snapshot
    # from the SAME live worker subprocess already streaming spectrum
    # frames (see spectrum_stream_worker.py's iq_snapshot_request) --
    # never opens a second SDR session, following the exact precedent of
    # the BLE live-check burst mechanism just above.
    # ------------------------------------------------------------------

    def capture_live_iq_snapshot(self, analyzer_settings, sample_count: int, timeout_seconds: float = 5.0) -> dict[str, Any] | None:
        """Blocks the calling thread until the requested snapshot arrives
        or timeout_seconds elapses (mirrors this class's existing
        synchronous design -- callers on the async side run this via an
        executor). Returns the worker's raw "iq_snapshot" frame dict
        (base64-encoded I/Q still undecoded), or None if the worker isn't
        available or the request times out."""
        self.ensure_started(analyzer_settings)
        request_id = uuid.uuid4().hex
        sent = self._send_raw_command({
            "command": "update",
            "iq_snapshot_request": {"request_id": request_id, "sample_count": int(sample_count)},
        })
        if not sent:
            return None

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            self._iq_snapshot_event.wait(timeout=0.2)
            self._iq_snapshot_event.clear()
            with self._lock:
                frame = self._pending_iq_snapshots.pop(request_id, None)
            if frame is not None:
                return frame
        with self._lock:
            self._pending_iq_snapshots.pop(request_id, None)
        return None

    # ------------------------------------------------------------------
    # BLE-RFFI Studio "Live Monitor model check" -- entirely additive on top
    # of the spectrum stream above. See spectrum_stream_worker.py's
    # ble_live_check_enabled / _detect_energy_bursts for where the burst
    # itself comes from (same B200 session, no second SDR open).
    # ------------------------------------------------------------------

    def enable_ble_live_check(self, bundle_id: str, repository: Any) -> None:
        """Additive: adds bundle_id to the set of currently-watched bundles
        without disturbing any others already enabled. Callers that want
        "only this one" (e.g. the single-model health check) must explicitly
        disable_ble_live_check() the previous bundle_id themselves first --
        see BleRffiLiveModelPanel.tsx's toggle()."""
        with self._lock:
            self._ble_live_check_enabled = True
            self._live_check_bundle_ids.add(bundle_id)
            self._live_check_repository = repository
            self._latest_live_check_results.pop(bundle_id, None)
            self._pending_burst = None
        self._send_raw_command({"command": "update", "ble_live_check_enabled": True})

    def disable_ble_live_check(self, bundle_id: str | None = None) -> None:
        """bundle_id given: stop watching just that one. bundle_id=None:
        full teardown (every watched bundle) -- reserved for the panel's own
        unmount cleanup, never for a single row's own toggle-off (that would
        silently stop every OTHER bundle a different row had going)."""
        with self._lock:
            if bundle_id is None:
                self._live_check_bundle_ids.clear()
                self._latest_live_check_results.clear()
            else:
                self._live_check_bundle_ids.discard(bundle_id)
                self._latest_live_check_results.pop(bundle_id, None)
            still_watching = bool(self._live_check_bundle_ids)
            self._ble_live_check_enabled = still_watching
            if not still_watching:
                self._live_check_repository = None
            self._pending_burst = None
        self._send_raw_command({"command": "update", "ble_live_check_enabled": still_watching})

    def get_latest_live_check_results(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {bundle_id: dict(result) for bundle_id, result in self._latest_live_check_results.items()}

    def _live_check_worker_loop(self) -> None:
        """Runs in its own thread, entirely separate from the SDR-reading
        thread above, so a slow/failing inference call can never delay or
        block spectrum frames. Single-pending-window by design: if a newer
        burst overwrites self._pending_burst before this loop gets to it
        (see _read_stdout), the older one is simply never processed --
        exactly the "keep up or drop" behavior requested, never a growing
        backlog."""
        while True:
            self._burst_event.wait(timeout=0.5)
            self._burst_event.clear()
            with self._lock:
                burst = self._pending_burst
                self._pending_burst = None
                enabled = self._ble_live_check_enabled
                bundle_ids = set(self._live_check_bundle_ids)
                repository = self._live_check_repository
            if not (enabled and burst and bundle_ids and repository is not None):
                continue
            try:
                iq_bytes = base64.b64decode(burst["iq_window_base64"])
                iq_window = np.frombuffer(iq_bytes, dtype=np.complex64)
                # Real, decoded-packet-aligned window instead of the raw
                # energy-threshold burst -- matches how every training
                # ExampleRecord's window was built (see BLE-RFFI Studio
                # README's "Why live detection fails despite a good TEST
                # score"). live_decode_burst() is best-effort and additive:
                # BLE_LIVE_DECODE_ENABLED=false (or any internal failure)
                # makes it a no-op returning None, in which case behavior is
                # UNCHANGED from before this fix (classify the raw burst
                # window) -- this preserves the existing, working fallback
                # rather than ever blocking on the new code path. Decoded
                # ONCE per burst, shared across every watched bundle below --
                # only the classify step is genuinely per-bundle (a
                # different model, possibly a different acquisition
                # reference/compatibility check).
                decoded = None
                decode_attempted = live_decode_enabled()
                sample_rate_mismatch = decode_attempted and float(burst["sample_rate_hz"]) != _BLE_LIVE_DECODE_REQUIRED_SAMPLE_RATE_HZ
                if decode_attempted and not sample_rate_mismatch:
                    channel = _resolve_ble_channel_for_burst(float(burst["center_frequency_hz"]))
                    decoded = live_decode_burst(iq_window, channel=channel)
                    if decoded is not None and decoded["packet_start_sample"] >= decoded["packet_end_sample"]:
                        decoded = None  # degenerate slice -- treat exactly like "no packet decoded"

                shared_outcome: dict[str, Any] | None = None
                if sample_rate_mismatch:
                    shared_outcome = {
                        "error": None, "predicted_class": None, "identified_device": None,
                        "class_probability": None, "acceptance_threshold": None,
                        "final_decision": "SAMPLE_RATE_MISMATCH", "decoded_address": None,
                        "timestamp_utc": burst.get("timestamp_utc"), "peak_power_dbfs": burst.get("peak_power_dbfs"),
                        "message": (
                            f"Live decode requires {_BLE_LIVE_DECODE_REQUIRED_SAMPLE_RATE_HZ / 1e6:.0f} MSps; "
                            f"the spectrum view is currently tuned to {float(burst['sample_rate_hz']) / 1e6:.3f} MSps. "
                            "Set the span to 4 MHz before enabling the live check."
                        ),
                    }
                elif decode_attempted and decoded is None:
                    # A real BLE packet could not be decoded from this
                    # energy burst (common: non-BLE 2.4 GHz activity, a
                    # packet collision, or a marginal SNR case) -- never
                    # feed the classifier a window shape it was never
                    # trained on. This is a real, informative outcome in its
                    # own right, not an error.
                    shared_outcome = {
                        "error": None, "predicted_class": None, "identified_device": None,
                        "class_probability": None, "acceptance_threshold": None,
                        "final_decision": "NO_BLE_PACKET_DECODED", "decoded_address": None,
                        "timestamp_utc": burst.get("timestamp_utc"), "peak_power_dbfs": burst.get("peak_power_dbfs"),
                    }

                results: dict[str, dict[str, Any]] = {}
                if shared_outcome is not None:
                    results = {bundle_id: dict(shared_outcome) for bundle_id in bundle_ids}
                else:
                    classify_window = iq_window
                    if decoded is not None:
                        classify_window = iq_window[decoded["packet_start_sample"]:decoded["packet_end_sample"]]
                    for bundle_id in bundle_ids:
                        try:
                            result = repository.live_check(
                                bundle_id=bundle_id, iq_window=classify_window,
                                sample_rate_sps=float(burst["sample_rate_hz"]), center_frequency_hz=float(burst["center_frequency_hz"]),
                                bandwidth_hz=float(burst.get("bandwidth_hz") or burst["sample_rate_hz"]), sample_format=str(burst.get("sample_format", "cf32_le")),
                            )
                            results[bundle_id] = {
                                **result, "timestamp_utc": burst.get("timestamp_utc"), "peak_power_dbfs": burst.get("peak_power_dbfs"),
                                "error": None, "decoded_address": decoded.get("address") if decoded else None,
                            }
                        except Exception as exc:
                            # One bundle's own failure (e.g. a channel
                            # mismatch specific to ITS acquisition reference)
                            # must never block scoring every OTHER
                            # simultaneously-watched bundle against this
                            # same burst.
                            results[bundle_id] = {"error": str(exc), "timestamp_utc": burst.get("timestamp_utc")}
            except Exception as exc:
                results = {bundle_id: {"error": str(exc), "timestamp_utc": burst.get("timestamp_utc")} for bundle_id in bundle_ids}
            with self._lock:
                for bundle_id, outcome in results.items():
                    # Never store a result for a bundle that was disabled
                    # while this burst was being scored.
                    if self._ble_live_check_enabled and bundle_id in self._live_check_bundle_ids:
                        self._latest_live_check_results[bundle_id] = outcome


real_spectrum_stream = RealSpectrumStream()
