from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ANALYSIS_CONFIGURATION_ID = "ble-rffi-offline-detector-decoder-replay-v1"
REPLAY_SCHEMA_VERSION = "ble-rffi-offline-replay-v1"
# Acquisition profile (A0 baseline) that must stay frozen regardless of
# channel -- comparing across channels/devices with a different sample
# rate or bandwidth per capture would confound the comparison. center_
# frequency_hz and ble_channel are validated separately below (see
# _BLE_ADVERTISING_CHANNEL_FREQUENCIES_HZ): they are expected to vary
# together across the 3 primary BLE advertising channels, not to be fixed
# to channel 37. The decoder itself (ble_worker.whitening.ble_dewhiten)
# already parameterizes dewhitening on channel_index for any of 0-39; this
# gate used to hardcode channel 37 only, rejecting every real channel
# 38/39 capture before decode ever started even though nothing downstream
# actually required that -- confirmed by cross-referencing campaign_
# orchestrator.py's own _BLE_CHANNEL_FREQUENCIES_HZ, which already lists
# all 3.
REQUIRED_RF = {
    "sample_format": "cf32_le",
    "sample_rate_sps": 4_000_000,
    "bandwidth_hz": 2_000_000,
}
_BLE_ADVERTISING_CHANNEL_FREQUENCIES_HZ = {37: 2_402_000_000, 38: 2_426_000_000, 39: 2_480_000_000}
# Every processing_status a candidate can reach. PENDING is the only
# non-terminal value; a resumed run only ever re-attempts PENDING rows.
CANDIDATE_PENDING = "PENDING"
CANDIDATE_PROCESSED = "PROCESSED"
CANDIDATE_FAILED_TIMEOUT = "FAILED_TIMEOUT"
CANDIDATE_FAILED_DECODER_ERROR = "FAILED_DECODER_ERROR"
CANDIDATE_TERMINAL = {CANDIDATE_PROCESSED, CANDIDATE_FAILED_TIMEOUT, CANDIDATE_FAILED_DECODER_ERROR}
CANDIDATE_FAILED = {CANDIDATE_FAILED_TIMEOUT, CANDIDATE_FAILED_DECODER_ERROR}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_replace_with_retry(temporary: Path, path: Path) -> None:
    """os.replace() can raise a transient PermissionError ([WinError 5]) on
    Windows when something else (antivirus real-time scan, search indexer,
    OneDrive/backup sync) briefly has the destination open -- observed
    directly twice in real, otherwise-successful ~20-minute decode runs,
    each time failing in the last few checkpoints after >99% coverage. A
    short retry absorbs that without masking a genuine, persistent failure.
    """
    last_error: OSError | None = None
    for attempt in range(6):
        try:
            os.replace(temporary, path)
            return
        except PermissionError as error:
            last_error = error
            time.sleep(0.05 * (2 ** attempt))
    raise last_error  # persisted past every retry -- a real failure, not a blip


def write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    _atomic_replace_with_retry(temporary, path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("".join(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n" for row in rows), encoding="utf-8")
    _atomic_replace_with_retry(temporary, path)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_id(value: str, prefix: str) -> str:
    if not value.startswith(prefix) or any(part in value for part in ("/", "\\", "..")):
        raise ValueError(f"INVALID_{prefix.rstrip('-')}_ID")
    return value


def candidate_id_for(source_iq_sha256: str, start_sample: int, end_sample: int, analysis_configuration_id: str) -> str:
    """Deterministic identity: same source I/Q + same interval + same detector
    configuration always yields the same candidate_id, independent of list
    order. Re-running the detector never renumbers an already-checkpointed
    candidate out from under a resumed replay."""
    digest = hashlib.sha256(f"{source_iq_sha256}:{start_sample}:{end_sample}:{analysis_configuration_id}".encode("utf-8")).hexdigest()
    return "cand-" + digest[:24]


def packet_identity_for(candidate_id: str, packet_start_sample: Any, decoded_pdu_hex: str) -> str:
    digest = hashlib.sha256(f"{candidate_id}:{packet_start_sample}:{decoded_pdu_hex}".encode("utf-8")).hexdigest()
    return "pkt-" + digest[:24]


def candidate_status_counts(candidates: list[dict[str, Any]]) -> dict[str, int]:
    total = len(candidates)
    processed = sum(1 for row in candidates if row.get("processing_status") == CANDIDATE_PROCESSED)
    failed_timeout = sum(1 for row in candidates if row.get("processing_status") == CANDIDATE_FAILED_TIMEOUT)
    failed_decoder_error = sum(1 for row in candidates if row.get("processing_status") == CANDIDATE_FAILED_DECODER_ERROR)
    failed = failed_timeout + failed_decoder_error
    return {
        "total": total, "processed": processed, "failed": failed,
        "failed_timeout": failed_timeout, "failed_decoder_error": failed_decoder_error,
        "pending": total - processed - failed,
    }


def coverage_snapshot(counts: dict[str, int], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Shared shape for a coverage report, from either a live in-memory
    candidate list or the checkpointed ledger on disk. Distinguishes having
    ATTEMPTED every candidate from having successfully DECODED every
    candidate -- a segment that hit a timeout or decoder error was attempted,
    not successfully processed."""
    total = max(1, counts["total"])
    return {
        "total_candidate_segments": counts["total"],
        "successfully_processed_segments": counts["processed"],
        "failed_timeout_segments": counts["failed_timeout"],
        "failed_decoder_error_segments": counts["failed_decoder_error"],
        "pending_segments": counts["pending"],
        "attempted_coverage": round((counts["processed"] + counts["failed"]) / total, 5),
        "successful_coverage": round(counts["processed"] / total, 5),
        # Backward-compatible aliases already consumed by the dashboard/tests.
        "processed_segments": counts["processed"],
        "failed_segments": counts["failed"],
        "coverage_percentage": round(100.0 * (counts["processed"] + counts["failed"]) / total, 3),
        **(extra or {}),
    }


def read_replay_progress(replay_dir: Path) -> dict[str, Any] | None:
    """Live coverage snapshot read straight off the checkpointed candidate
    ledger, usable while a replay job is still running in another thread.
    Reads/writes to these files are atomic (os.replace), so this never sees
    a torn write from a concurrent checkpoint."""
    manifest_path = replay_dir / "candidate_manifest.jsonl"
    state_path = replay_dir / "replay_state.json"
    if not manifest_path.is_file() or not state_path.is_file():
        return None
    candidates = read_jsonl(manifest_path)
    state = read_json(state_path)
    counts = candidate_status_counts(candidates)
    return coverage_snapshot(counts, {
        "checkpoint_sequence": state.get("checkpoint_sequence", 0),
        "last_checkpoint_at": state.get("last_checkpoint_at"),
        "decoder_timeout_count": state.get("decoder_timeout_count", 0),
        "decoder_internal_error_count": state.get("decoder_internal_error_count", 0),
        "worker_restart_count": state.get("worker_restart_count", 0),
        "resume_available": counts["pending"] > 0,
    })


class BleOfflineReplayService:
    def __init__(
        self,
        capture_root: Path,
        session_root: Path | None = None,
        backend_root: Path | None = None,
        worker_repository: Path | None = None,
        python_executable: Path | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.capture_root = capture_root
        self.session_root = session_root or capture_root.parent.parent / "ble_lab" / "sessions"
        self.backend_root = backend_root or Path(__file__).resolve().parents[4]
        self.worker_repository = worker_repository or Path(os.environ.get("BLE_GATE2A2_REPOSITORY", r"C:\Users\Usuario\ble-worker-lab"))
        default_worker_python = Path(os.environ.get("RADIOCONDA_PYTHON", r"C:\Users\Usuario\radioconda\python.exe"))
        self.python_executable = python_executable or Path(os.environ.get("BLE_GATE2A2_WORKER_PYTHON", str(default_worker_python if default_worker_python.is_file() else Path(sys.executable))))
        # job_time_budget default: how long a single start/continue call is allowed to
        # run before it must checkpoint and hand control back to the operator.
        self.job_time_budget_seconds = float(timeout_seconds or os.environ.get("BLE_RFFI_OFFLINE_REPLAY_TIMEOUT_SECONDS", "480"))
        self.batch_size = int(os.environ.get("BLE_RFFI_REPLAY_BATCH_SIZE", "200"))
        self.batch_timeout_seconds = float(os.environ.get("BLE_RFFI_REPLAY_BATCH_TIMEOUT_SECONDS", "240"))
        self.per_candidate_timeout_seconds = float(os.environ.get("BLE_RFFI_REPLAY_PER_CANDIDATE_TIMEOUT_SECONDS", "30"))
        self.capture_tool = self.backend_root / "tools" / "ble_sdr_capture_worker.py"
        # Each burst segment decodes fully independently of every other one
        # (no shared state), so the parallel script is a drop-in replacement
        # -- same CLI, byte-identical output, ~4-5x faster on this machine's
        # 16 logical cores (validated against real captured segments). Kept
        # switchable via env var in case a future environment needs the
        # sequential fallback (e.g. constrained CPU/memory).
        use_sequential_decode = os.environ.get("BLE_RFFI_REPLAY_SEQUENTIAL_DECODE", "").strip().lower() in {"1", "true", "yes"}
        decode_tool_name = "ble_decode_burst_directory.py" if use_sequential_decode else "ble_decode_burst_directory_parallel.py"
        self.decode_tool = self.backend_root / "tools" / decode_tool_name

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def create(
        self,
        capture_id: str,
        payload: dict[str, Any] | None = None,
        cancel_requested: Callable[[], bool] | None = None,
        checkpoint_hook: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Run (or resume) one bounded replay attempt. Bounded by
        job_time_budget_seconds: if the candidate backlog is not exhausted
        within that budget, the attempt checkpoints and returns with
        resume_available=true instead of blocking indefinitely."""
        return self._run(capture_id, payload or {}, cancel_requested, checkpoint_hook)

    def latest(self, capture_id: str) -> dict[str, Any]:
        capture_dir = self._capture_dir(safe_id(capture_id, "BLE-IQ-"))
        replay_root = capture_dir / "offline_replays"
        if not replay_root.is_dir():
            raise FileNotFoundError("REPLAY_NOT_FOUND")
        summaries = sorted(replay_root.glob("*/replay_summary.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not summaries:
            raise FileNotFoundError("REPLAY_NOT_FOUND")
        return read_json(summaries[0])

    # ------------------------------------------------------------------
    # Source resolution / validation (unchanged contract)
    # ------------------------------------------------------------------

    def _capture_dir(self, capture_id: str) -> Path:
        path = (self.capture_root / capture_id).resolve()
        if path.parent != self.capture_root.resolve() or not path.is_dir():
            raise FileNotFoundError(capture_id)
        return path

    def _source_session(self, capture_id: str, execution_id: Any = None) -> dict[str, Any]:
        matches: list[dict[str, Any]] = []
        for manifest_path in self.session_root.glob("BLE-HYBRID-*/session_manifest.json"):
            try:
                session = read_json(manifest_path)
            except Exception:
                continue
            if session.get("capture_id") == capture_id:
                session["_session_manifest_path"] = str(manifest_path)
                matches.append(session)
        if execution_id:
            matches = [session for session in matches if session.get("session_id") == execution_id]
            if not matches:
                raise ValueError("CAPTURE_ID_DOES_NOT_BELONG_TO_EXECUTION_ID")
        if len(matches) != 1:
            raise ValueError("SOURCE_SESSION_NOT_UNAMBIGUOUS")
        return matches[0]

    def quick_native_presence_check(self, capture_id: str, execution_id: Any = None, target_addresses: list[str] | None = None) -> dict[str, Any]:
        """Fast (sub-second, no IQ decode) triage: was any of target_addresses
        seen at all by the native Windows BLE scan during this capture's RF
        window? Reads only capture_manifest.json + the already-preserved
        advertisements.jsonl -- never touches the (large, slow to decode) IQ
        file itself.

        target_addresses is the caller's resolved set of known addresses for
        the physical unit in question (e.g. from a Physical Device Registry
        binding) -- callers whose session actually declares a single
        target_address up front (the older hybrid-campaign flow) may omit
        this and let it fall back to that field instead.

        This is a NECESSARY-but-not-sufficient predictor of the real,
        decode-dependent verdict _associate() computes later: a target never
        seen natively in the window WILL end up REPETITION_NEEDED (no B200
        decode can invent a native corroboration that never happened), so
        target_observed=False is a reliable early rejection. target_observed
        =True does not guarantee ELIGIBLE_AS_POSITIVE -- MULTIPLE_NATIVE_
        CALLBACKS ambiguity can still occur and is only resolved by full
        packet-level association, which this check deliberately skips.
        """
        capture_dir = self._capture_dir(capture_id)
        capture_manifest = read_json(capture_dir / "capture_manifest.json")
        try:
            session = self._source_session(capture_id, execution_id)
        except ValueError:
            return {"applicable": False, "reason": "SOURCE_SESSION_NOT_FOUND"}
        candidates = {str(addr).upper() for addr in (target_addresses or []) if addr}
        if not candidates and session.get("target_address"):
            candidates = {str(session["target_address"]).upper()}
        if not candidates:
            return {"applicable": False, "reason": "NO_TARGET_ADDRESS_AVAILABLE"}
        window_start = capture_manifest.get("b200_rf_started_at")
        window_end = capture_manifest.get("b200_rf_finished_at")
        native_rows = self._native_rows(session, capture_manifest)
        target_rows = [row for row in native_rows if str(row.get("address", "")).upper() in candidates]
        other_addresses = {str(row.get("address", "")).upper() for row in native_rows} - candidates
        return {
            "applicable": True,
            "target_addresses": sorted(candidates),
            "window_start_utc": window_start,
            "window_end_utc": window_end,
            "target_observed": bool(target_rows),
            "target_observation_count": len(target_rows),
            "other_addresses_observed_count": len(other_addresses),
            "total_native_observations": len(native_rows),
        }

    def _validate_source(self, capture_id: str, capture: dict[str, Any], session: dict[str, Any], iq_sha: str) -> None:
        if session.get("capture_id") != capture_id:
            raise ValueError("CAPTURE_ID_DOES_NOT_BELONG_TO_EXECUTION_ID")
        if capture.get("data_sha256") != iq_sha:
            raise ValueError("REPLAY_SOURCE_IQ_SHA256_MISMATCH")
        missing = [key for key in ("capture_id", "data_path", "data_sha256", "sample_rate_sps", "center_frequency_hz", "bandwidth_hz", "sample_format", "ble_channel") if capture.get(key) in {None, ""}]
        if missing:
            raise ValueError("REPLAY_SOURCE_METADATA_MISSING:" + ",".join(missing))
        for key, expected in REQUIRED_RF.items():
            observed = capture.get(key)
            if key != "sample_format":
                observed = int(observed)
            if observed != expected:
                raise ValueError(f"REPLAY_RF_CONFIGURATION_MISMATCH:{key}")
        observed_channel = int(capture["ble_channel"])
        expected_frequency = _BLE_ADVERTISING_CHANNEL_FREQUENCIES_HZ.get(observed_channel)
        if expected_frequency is None:
            raise ValueError(f"REPLAY_RF_CONFIGURATION_MISMATCH:ble_channel")
        if int(capture["center_frequency_hz"]) != expected_frequency:
            raise ValueError("REPLAY_RF_CONFIGURATION_MISMATCH:center_frequency_hz")
        if not (Path(str(session.get("_session_manifest_path"))).is_file()):
            raise ValueError("SOURCE_SESSION_MANIFEST_MISSING")

    def _configuration(self, capture: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        sample_rate = int(capture["sample_rate_sps"])
        return {
            "schema_version": "ble-rffi-offline-replay-configuration-v1",
            "analysis_configuration_id": ANALYSIS_CONFIGURATION_ID,
            "sample_format": "cf32_le",
            "sample_rate_sps": sample_rate,
            "center_frequency_hz": int(capture["center_frequency_hz"]),
            "bandwidth_hz": int(capture["bandwidth_hz"]),
            "ble_channel": int(capture["ble_channel"]),
            "noise_estimator": "median_block_power",
            "minimum_active_blocks": 1,
            "minimum_burst_duration_samples": 80,
            "maximum_burst_duration_samples": 4096,
            "candidate_merge_gap_samples": max(64, int(sample_rate / 100_000)) * 2,
            "frequency_offset_search_range_hz": "worker_default",
            "frequency_offset_step_hz": "worker_default",
            "symbol_rate": 1_000_000,
            "samples_per_symbol": sample_rate / 1_000_000,
            "timing_phase_search": "worker_default",
            "preamble_policy": "worker_default_ble_le1m",
            "access_address": "8E89BED6",
            "whitening_channel_index": int(capture["ble_channel"]),
            "crc_init": "0x555555",
            "maximum_payload_length": 255,
            "worker_version": self._git_revision(self.worker_repository),
            "decoder_version": self._git_revision(self.backend_root.parent),
            "source_session_manifest": session.get("_session_manifest_path"),
        }

    def _provenance(self, capture: dict[str, Any], session: dict[str, Any], iq_sha: str, replay_run_id: str, started_at: str) -> dict[str, Any]:
        metadata = dict(capture.get("experimental_metadata") or session.get("experimental_metadata") or {})
        return {
            "campaign_id": metadata.get("campaign_id"),
            "condition_id": metadata.get("condition_id"),
            "session_role": metadata.get("session_id") or metadata.get("operator_session_id"),
            "execution_id": session.get("session_id"),
            "source_execution_id": session.get("session_id"),
            "capture_id": capture.get("capture_id"),
            "source_capture_id": capture.get("capture_id"),
            "iq_sha256": iq_sha,
            "source_iq_sha256": iq_sha,
            "capture_window_start": capture.get("b200_rf_started_at") or capture.get("created_at_utc"),
            "capture_window_end": capture.get("b200_rf_finished_at"),
            "diagnostic_run_id": "RF-DIAGNOSTIC-" + str(capture.get("capture_id")),
            "replay_run_id": replay_run_id,
            "worker_version": self._git_revision(self.worker_repository),
            "decoder_version": self._git_revision(self.backend_root.parent),
            "analysis_configuration_id": ANALYSIS_CONFIGURATION_ID,
            "started_at": started_at,
        }

    # ------------------------------------------------------------------
    # Resumable execution engine
    # ------------------------------------------------------------------

    def _run(
        self,
        capture_id: str,
        payload: dict[str, Any],
        cancel_requested: Callable[[], bool] | None,
        checkpoint_hook: Callable[[dict[str, Any]], None] | None,
    ) -> dict[str, Any]:
        payload = dict(payload)
        capture_id = safe_id(capture_id, "BLE-IQ-")
        started_at = utc_now()
        capture_dir = self._capture_dir(capture_id)
        capture_manifest = read_json(capture_dir / "capture_manifest.json")
        source_session = self._source_session(capture_id, payload.get("execution_id"))
        expected_sha = str(payload.get("expected_iq_sha256") or capture_manifest.get("data_sha256") or "")
        iq_path = capture_dir / str(capture_manifest.get("data_path") or f"{capture_id}.sigmf-data")
        actual_sha = sha256_file(iq_path)
        if expected_sha and actual_sha != expected_sha:
            raise ValueError("REPLAY_SOURCE_IQ_SHA256_MISMATCH")
        self._validate_source(capture_id, capture_manifest, source_session, actual_sha)
        configuration = self._configuration(capture_manifest, source_session)
        worker_version, decoder_version = configuration["worker_version"], configuration["decoder_version"]

        batch_size = int(payload.get("batch_size") or self.batch_size)
        per_candidate_timeout = float(payload.get("per_candidate_timeout_seconds") or self.per_candidate_timeout_seconds)
        batch_timeout = float(payload.get("batch_timeout_seconds") or self.batch_timeout_seconds)
        job_time_budget = float(payload.get("job_time_budget_seconds") or self.job_time_budget_seconds)

        # Whether this call resumes existing work is decided by whether the
        # target directory already has real prior progress on disk -- NOT by
        # whether the caller happened to pass replay_run_id. Callers such as
        # BleCaptureJobManager always pass a replay_run_id (self-minted for a
        # brand-new run, or operator-supplied for a genuine resume) so they
        # can pre-create job.json before launching the background thread;
        # treating "replay_run_id present" as "must resume" would make every
        # fresh run through that caller incorrectly look for checkpoint state
        # that was never written yet.
        requested_run_id = str(payload.get("replay_run_id") or "")
        if requested_run_id:
            replay_run_id = safe_id(requested_run_id, "BLE-RFFI-REPLAY-")
            candidate_dir = capture_dir / "offline_replays" / replay_run_id
            has_prior_progress = (candidate_dir / "replay_state.json").is_file() or (candidate_dir / "burst_candidates.jsonl").is_file()
        else:
            replay_run_id = "BLE-RFFI-REPLAY-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
            has_prior_progress = False

        if has_prior_progress:
            replay_run_id, replay_dir, candidates, state = self._resume(
                capture_dir, replay_run_id, actual_sha, worker_version, decoder_version,
            )
        else:
            replay_dir, candidates, state = self._start_fresh(
                capture_dir, replay_run_id, capture_manifest, configuration, actual_sha, worker_version, decoder_version,
            )
        state.update(batch_size=batch_size, per_candidate_timeout_seconds=per_candidate_timeout, batch_timeout_seconds=batch_timeout)
        write_json(replay_dir / "replay_configuration.json", configuration)
        (replay_dir / "input_iq_sha256.txt").write_text(actual_sha + "  " + iq_path.name + "\n", encoding="ascii")
        provenance = self._provenance(capture_manifest, source_session, actual_sha, replay_run_id, started_at)

        decoded_dir = replay_dir / "decoded"
        decoded_dir.mkdir(exist_ok=True)
        segments_dir = replay_dir / "iq_bursts"
        job_deadline = time.monotonic() + max(0.05, job_time_budget)

        worker_error = None
        try:
            outcome = self._process_batches(
                candidates, replay_dir, segments_dir, decoded_dir, int(capture_manifest["ble_channel"]),
                state, job_deadline, cancel_requested, checkpoint_hook,
            )
        except Exception as error:
            worker_error = f"{type(error).__name__}:{error}"
            outcome = "failed"

        state["checkpoint_sequence"] = int(state.get("checkpoint_sequence", 0)) + 1
        state["last_checkpoint_at"] = utc_now()
        write_jsonl(replay_dir / "candidate_manifest.jsonl", candidates)
        write_json(replay_dir / "replay_state.json", state)

        completed_at = utc_now()
        decoded_packets = read_jsonl(decoded_dir / "decoded_packets.jsonl")
        semantic_packets = read_jsonl(decoded_dir / "semantic_packets.jsonl")
        native_rows = self._native_rows(source_session, capture_manifest)
        association = self._associate(decoded_packets, semantic_packets, candidates, native_rows, capture_manifest, source_session)
        completion = self._completion_status(candidates, outcome, state)
        funnel = self._funnel(capture_manifest, candidates, decoded_packets, semantic_packets, association, completion, state)
        rejection = self._rejection_summary(candidates, funnel)
        decision = self._decision(capture_manifest, source_session, funnel, association, completion)
        exit_status = self._exit_status(completion, worker_error)
        final_report = self._final_report(capture_manifest, completion, funnel, association, rejection, decision)

        result = {
            **provenance,
            "schema_version": REPLAY_SCHEMA_VERSION,
            "analysis_configuration_id": ANALYSIS_CONFIGURATION_ID,
            "started_at": started_at,
            "completed_at": completed_at,
            "exit_status": exit_status,
            "execution_status": completion["execution_status"],
            "termination_reason": completion["termination_reason"],
            "scientific_completion_status": completion["scientific_completion_status"],
            "decision_scope": completion["decision_scope"],
            "resume_available": completion["resume_available"],
            "coverage": completion["coverage"],
            "candidate_funnel": funnel,
            "candidate_rejection_summary": rejection,
            "target_association_results": association,
            "decision": decision,
            "final_report": final_report,
            "worker_error": worker_error,
            "artifacts": self._write_artifacts(replay_dir, provenance, configuration, funnel, rejection, association, candidates, decision, completion, final_report, started_at, completed_at, exit_status, worker_error),
        }
        write_json(replay_dir / "replay_summary.json", result)
        return result

    def _final_report(
        self,
        capture: dict[str, Any],
        completion: dict[str, Any],
        funnel: dict[str, Any],
        association: dict[str, Any],
        rejection: dict[str, Any],
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        """The mandatory closing report (BLE-RFFI Stage 1 Phase 1 sec. 6).
        Meaningful as a CLOSED result only once scientific_completion_status
        == COMPLETE; while INCOMPLETE this reflects the processed-subset-only
        state honestly rather than pretending coverage is final."""
        coverage = completion["coverage"]
        rejection_reason_counts: dict[str, int] = {}
        for row in association.get("packet_association_ledger", []):
            reason = row.get("association_rejection_reason")
            if reason:
                rejection_reason_counts[reason] = rejection_reason_counts.get(reason, 0) + 1
        return {
            "schema_version": "ble-rffi-replay-final-report-v1",
            "total_candidate_segments": coverage["total_candidate_segments"],
            "successfully_processed_segments": coverage["successfully_processed_segments"],
            "failed_timeout_segments": coverage["failed_timeout_segments"],
            "failed_decoder_error_segments": coverage["failed_decoder_error_segments"],
            "pending_segments": coverage["pending_segments"],
            "attempted_coverage": coverage["attempted_coverage"],
            "successful_coverage": coverage["successful_coverage"],
            "crc_valid_packets": funnel["crc_valid_packets"],
            "unique_crc_valid_packets": funnel["unique_crc_valid_packets"],
            "target_address_candidates": funnel["target_address_candidates"],
            "strong_target_matches": funnel["strong_target_matches"],
            "conflicting_matches": funnel["conflicting_matches"],
            "association_rejection_summary": rejection_reason_counts,
            "source_acquisition_quality": {
                "overflow_count": capture.get("overflow_count"),
                "discontinuity_count": capture.get("discontinuity_count"),
                "short_read_count": capture.get("short_read_count"),
                "write_error_count": capture.get("write_error_count"),
                "hash_status": capture.get("hash_status"),
                "metadata_status": capture.get("metadata_status"),
                "acquisition_status": decision["source_quality_gate"]["acquisition_status"],
            },
            "scientific_decision": decision["scientific_decision"],
            "dataset_eligibility_status": decision["dataset_eligibility_status"],
            "scope_note": (
                "pending_segments == 0: this report covers the complete capture."
                if coverage["pending_segments"] == 0 else
                f"pending_segments == {coverage['pending_segments']}: this report covers the processed subset only, "
                "not the complete capture. strong_target_matches == 0 here means the target was not corroborated in "
                "the processed subset, not that it is absent from the full capture."
            ),
        }

    def _start_fresh(
        self,
        capture_dir: Path,
        replay_run_id: str,
        capture_manifest: dict[str, Any],
        configuration: dict[str, Any],
        actual_sha: str,
        worker_version: str,
        decoder_version: str,
    ) -> tuple[Path, list[dict[str, Any]], dict[str, Any]]:
        replay_dir = capture_dir / "offline_replays" / replay_run_id
        # exist_ok=True: BleCaptureJobManager pre-creates this directory
        # (job.json only) before launching the background thread. _run()
        # only reaches here when there is no burst_candidates.jsonl/
        # replay_state.json yet, so there is no real prior progress to clobber.
        replay_dir.mkdir(parents=True, exist_ok=True)
        bursts = self._detect(capture_dir, replay_dir, capture_manifest)
        candidates = self._build_candidate_manifest(bursts, actual_sha)
        write_jsonl(replay_dir / "burst_candidates.jsonl", bursts)
        write_jsonl(replay_dir / "candidate_manifest.jsonl", candidates)
        manifest_hash = self._candidate_manifest_hash(candidates)
        state = {
            "schema_version": "ble-rffi-offline-replay-state-v1",
            "replay_run_id": replay_run_id,
            "source_iq_sha256": actual_sha,
            "analysis_configuration_id": ANALYSIS_CONFIGURATION_ID,
            "worker_version": worker_version,
            "decoder_version": decoder_version,
            "candidate_manifest_sha256": manifest_hash,
            "total_candidate_segments": len(candidates),
            "checkpoint_sequence": 0,
            "last_checkpoint_at": None,
            "decoder_timeout_count": 0,
            "decoder_internal_error_count": 0,
            "worker_restart_count": 0,
            "cancelled_with_checkpoint": False,
        }
        write_json(replay_dir / "replay_state.json", state)
        return replay_dir, candidates, state

    def _resume(
        self,
        capture_dir: Path,
        replay_run_id: str,
        actual_sha: str,
        worker_version: str,
        decoder_version: str,
    ) -> tuple[str, Path, list[dict[str, Any]], dict[str, Any]]:
        replay_dir = capture_dir / "offline_replays" / replay_run_id
        state_path = replay_dir / "replay_state.json"
        if not replay_dir.is_dir():
            raise FileNotFoundError("REPLAY_RUN_NOT_FOUND")
        if not state_path.is_file():
            # Pre-existing single-shot runs (started before the resumable
            # engine existed) have no checkpoint state. Bootstrap one in
            # place from their already-preserved burst_candidates.jsonl +
            # decoded/batch_summary.json instead of discarding that work and
            # redecoding from candidate 0.
            self._migrate_legacy_run(replay_dir, actual_sha, worker_version, decoder_version)
        state = read_json(state_path)
        candidates = read_jsonl(replay_dir / "candidate_manifest.jsonl")
        current_manifest_hash = self._candidate_manifest_hash(candidates)
        checks = (
            ("source_iq_sha256", actual_sha),
            ("analysis_configuration_id", ANALYSIS_CONFIGURATION_ID),
            ("worker_version", worker_version),
            ("decoder_version", decoder_version),
            ("candidate_manifest_sha256", current_manifest_hash),
        )
        for field, current_value in checks:
            if state.get(field) != current_value:
                raise ValueError(f"REPLAY_RESUME_CONFIGURATION_CHANGED:{field}")
        return replay_run_id, replay_dir, candidates, state

    def _migrate_legacy_run(self, replay_dir: Path, actual_sha: str, worker_version: str, decoder_version: str) -> None:
        bursts_path = replay_dir / "burst_candidates.jsonl"
        if not bursts_path.is_file():
            raise FileNotFoundError("REPLAY_RUN_NOT_FOUND")
        candidates = self._build_candidate_manifest(read_jsonl(bursts_path), actual_sha)
        batch_summary_path = replay_dir / "decoded" / "batch_summary.json"
        attempts = read_json(batch_summary_path).get("attempts", []) if batch_summary_path.is_file() else []
        # The old single-shot decoder always decoded segments contiguously
        # from index 0 (see ble_decode_burst_directory.py's default
        # --start-index 0) -- batch_summary.json's attempts therefore cover
        # exactly candidates [0, len(attempts)) in order.
        if attempts:
            self._apply_slice_results(candidates, 0, len(attempts), {"attempts": attempts, "elapsed_seconds": 0.0}, timed_out=False)
        write_jsonl(replay_dir / "candidate_manifest.jsonl", candidates)
        write_json(replay_dir / "replay_state.json", {
            "schema_version": "ble-rffi-offline-replay-state-v1",
            "replay_run_id": replay_dir.name,
            "source_iq_sha256": actual_sha,
            "analysis_configuration_id": ANALYSIS_CONFIGURATION_ID,
            "worker_version": worker_version,
            "decoder_version": decoder_version,
            "candidate_manifest_sha256": self._candidate_manifest_hash(candidates),
            "total_candidate_segments": len(candidates),
            "checkpoint_sequence": 0,
            "last_checkpoint_at": None,
            "decoder_timeout_count": 0,
            "decoder_internal_error_count": 0,
            "worker_restart_count": 0,
            "cancelled_with_checkpoint": False,
            "migrated_from_legacy_single_shot_run": True,
            "migrated_at_utc": utc_now(),
            "legacy_processed_segments_at_migration": len(attempts),
        })

    def _build_candidate_manifest(self, bursts: list[dict[str, Any]], source_iq_sha256: str) -> list[dict[str, Any]]:
        rows = []
        for index, burst in enumerate(bursts):
            start_sample, end_sample = int(burst.get("sample_start", 0)), int(burst.get("sample_end", 0))
            candidate_id = candidate_id_for(source_iq_sha256, start_sample, end_sample, ANALYSIS_CONFIGURATION_ID)
            rows.append({
                "candidate_id": candidate_id,
                "candidate_index": index,
                "burst_id": burst.get("burst_id"),
                "start_sample": start_sample,
                "end_sample": end_sample,
                "duration_samples": int(burst.get("sample_count", end_sample - start_sample)),
                "start_time_relative_seconds": None,
                "mean_power_dbfs": burst.get("power_dbfs"),
                "peak_power_dbfs": burst.get("power_dbfs"),
                "iq_segment_path": burst.get("iq_segment_path"),
                "iq_segment_sha256": burst.get("iq_segment_sha256"),
                "processing_status": CANDIDATE_PENDING,
                "attempt_count": 0,
                "processing_duration_ms": None,
                "decoder_result": None,
                "rejection_reason": None,
                "crc_status": "NOT_EVALUATED",
            })
        return rows

    def _candidate_manifest_hash(self, candidates: list[dict[str, Any]]) -> str:
        digest = hashlib.sha256()
        for row in sorted(candidates, key=lambda item: item["candidate_index"]):
            digest.update(f"{row['candidate_id']}:{row['start_sample']}:{row['end_sample']}\n".encode("utf-8"))
        return digest.hexdigest()

    def _detect(self, capture_dir: Path, replay_dir: Path, capture: dict[str, Any]) -> list[dict[str, Any]]:
        spec = importlib.util.spec_from_file_location("ble_sdr_capture_worker_replay", self.capture_tool)
        if spec is None or spec.loader is None:
            raise RuntimeError("CAPTURE_WORKER_IMPORT_FAILED")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        data_path = capture_dir / str(capture["data_path"])
        return module.detect_bursts(data_path, str(capture["sample_format"]), float(capture["sample_rate_sps"]), replay_dir)

    # ------------------------------------------------------------------
    # Batch-first, isolate-on-stall decode loop
    # ------------------------------------------------------------------

    def _process_batches(
        self,
        candidates: list[dict[str, Any]],
        replay_dir: Path,
        segments_dir: Path,
        decoded_dir: Path,
        channel: int,
        state: dict[str, Any],
        job_deadline: float,
        cancel_requested: Callable[[], bool] | None,
        checkpoint_hook: Callable[[dict[str, Any]], None] | None,
    ) -> str:
        total = len(candidates)
        if total == 0:
            write_json(decoded_dir / "progress.json", {"processed_segments": 0, "total_segments": 0, "crc_valid_packets": 0})
            write_jsonl(decoded_dir / "decoded_packets.jsonl", [])
            write_jsonl(decoded_dir / "semantic_packets.jsonl", [])
            return "fully_processed"
        stdout_path, stderr_path = replay_dir / "worker_stdout.log", replay_dir / "worker_stderr.log"
        batch_size = int(state["batch_size"])
        index = 0
        while index < total:
            if cancel_requested and cancel_requested():
                state["cancelled_with_checkpoint"] = True
                return "cancelled"
            if time.monotonic() >= job_deadline:
                return "budget_exhausted"
            if candidates[index]["processing_status"] != CANDIDATE_PENDING:
                index += 1
                continue
            end = index
            while end < total and end - index < batch_size and candidates[end]["processing_status"] == CANDIDATE_PENDING:
                end += 1
            remaining_budget = max(1.0, job_deadline - time.monotonic())
            batch_bound = min(float(state["batch_timeout_seconds"]), remaining_budget)
            outcome = self._run_decode_slice(segments_dir, decoded_dir, channel, index, end, batch_bound, stdout_path, stderr_path, cancel_requested)
            self._apply_slice_results(candidates, index, index + outcome["processed_in_batch"], outcome, timed_out=False)
            self._checkpoint(replay_dir, candidates, state, checkpoint_hook)
            if outcome["completed"]:
                index = end
                continue
            if outcome["cancelled"]:
                state["cancelled_with_checkpoint"] = True
                return "cancelled"
            # The batch stalled or crashed before reaching `end`. Isolate the
            # single candidate it was working on so one bad segment cannot
            # block the thousands behind it.
            stalled_index = index + outcome["processed_in_batch"]
            if stalled_index >= end:
                index = end
                continue
            if time.monotonic() >= job_deadline:
                return "budget_exhausted"
            state["worker_restart_count"] = int(state.get("worker_restart_count", 0)) + 1
            isolated_bound = min(float(state["per_candidate_timeout_seconds"]), max(1.0, job_deadline - time.monotonic()))
            isolated = self._run_decode_slice(segments_dir, decoded_dir, channel, stalled_index, stalled_index + 1, isolated_bound, stdout_path, stderr_path, cancel_requested)
            if isolated["processed_in_batch"] >= 1 and isolated["completed"]:
                self._apply_slice_results(candidates, stalled_index, stalled_index + 1, isolated, timed_out=False)
            else:
                candidates[stalled_index]["attempt_count"] = int(candidates[stalled_index].get("attempt_count", 0)) + 1
                if isolated["cancelled"]:
                    state["cancelled_with_checkpoint"] = True
                    self._checkpoint(replay_dir, candidates, state, checkpoint_hook)
                    return "cancelled"
                if isolated["crashed"]:
                    candidates[stalled_index].update(processing_status=CANDIDATE_FAILED_DECODER_ERROR, rejection_reason="DECODER_INTERNAL_ERROR", crc_status="NOT_EVALUATED", processing_duration_ms=round(isolated["elapsed_seconds"] * 1000, 3))
                    state["decoder_internal_error_count"] = int(state.get("decoder_internal_error_count", 0)) + 1
                else:
                    candidates[stalled_index].update(processing_status=CANDIDATE_FAILED_TIMEOUT, rejection_reason="DECODER_TIMEOUT", crc_status="NOT_EVALUATED", processing_duration_ms=round(isolated["elapsed_seconds"] * 1000, 3))
                    state["decoder_timeout_count"] = int(state.get("decoder_timeout_count", 0)) + 1
            self._checkpoint(replay_dir, candidates, state, checkpoint_hook)
            index = stalled_index + 1
        return "fully_processed"

    def _checkpoint(self, replay_dir: Path, candidates: list[dict[str, Any]], state: dict[str, Any], checkpoint_hook: Callable[[dict[str, Any]], None] | None) -> None:
        state["checkpoint_sequence"] = int(state.get("checkpoint_sequence", 0)) + 1
        state["last_checkpoint_at"] = utc_now()
        write_jsonl(replay_dir / "candidate_manifest.jsonl", candidates)
        write_json(replay_dir / "replay_state.json", state)
        if checkpoint_hook:
            checkpoint_hook(self._coverage(candidates, state))

    def _run_decode_slice(
        self,
        segments_dir: Path,
        decoded_dir: Path,
        channel: int,
        start_index: int,
        end_index: int,
        timeout: float,
        stdout_path: Path,
        stderr_path: Path,
        cancel_requested: Callable[[], bool] | None,
    ) -> dict[str, Any]:
        if not any(segments_dir.glob("*.cf32")):
            return {"completed": True, "cancelled": False, "crashed": False, "processed_in_batch": 0, "attempts": [], "elapsed_seconds": 0.0}
        command = [
            str(self.python_executable), str(self.decode_tool),
            "--segments-dir", str(segments_dir),
            "--output-dir", str(decoded_dir),
            "--worker-repository", str(self.worker_repository),
            "--channel", str(channel),
            "--start-index", str(start_index),
            "--end-index", str(end_index),
        ]
        started = time.monotonic()
        with stdout_path.open("ab") as out, stderr_path.open("ab") as err:
            process = subprocess.Popen(command, cwd=self.decode_tool.parent, stdout=out, stderr=err)
            return_code = None
            cancelled = False
            while True:
                return_code = process.poll()
                if return_code is not None:
                    break
                cancelled = bool(cancel_requested and cancel_requested())
                timed_out = time.monotonic() - started > timeout
                if cancelled or timed_out:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    break
                time.sleep(0.1)
        elapsed = time.monotonic() - started
        batch_summary_path = decoded_dir / "batch_summary.json"
        attempts = read_json(batch_summary_path).get("attempts", []) if batch_summary_path.is_file() else []
        expected = end_index - start_index
        processed_in_batch = min(len(attempts), expected)
        completed = return_code == 0 and processed_in_batch == expected and not cancelled
        return {
            "completed": completed,
            "cancelled": cancelled,
            "crashed": (return_code is not None and return_code != 0 and not cancelled),
            "processed_in_batch": processed_in_batch,
            "attempts": attempts[:processed_in_batch],
            "elapsed_seconds": elapsed,
        }

    def _apply_slice_results(self, candidates: list[dict[str, Any]], start_index: int, applied_end: int, outcome: dict[str, Any], timed_out: bool) -> None:
        attempts = outcome["attempts"]
        per_segment_ms = round((outcome["elapsed_seconds"] * 1000.0) / max(1, len(attempts)), 3) if attempts and outcome["elapsed_seconds"] > 0 else None
        for offset, attempt in enumerate(attempts):
            row = candidates[start_index + offset]
            confirmed = int(attempt.get("confirmed_packets", 0))
            row.update(
                processing_status=CANDIDATE_PROCESSED,
                attempt_count=int(row.get("attempt_count", 0)) + 1,
                processing_duration_ms=per_segment_ms,
                decoder_result={"confirmed_packets": confirmed, "semantic_packets": int(attempt.get("semantic_packets", 0)), "iq_segment": attempt.get("iq_segment")},
                crc_status="VALID" if confirmed > 0 else "NOT_RECOVERED",
                rejection_reason=None if confirmed > 0 else "CRC_NOT_RECOVERED",
            )

    def _coverage(self, candidates: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
        counts = candidate_status_counts(candidates)
        return coverage_snapshot(counts, {
            "checkpoint_sequence": state.get("checkpoint_sequence", 0),
            "last_checkpoint_at": state.get("last_checkpoint_at"),
        })

    def _completion_status(self, candidates: list[dict[str, Any]], outcome: str, state: dict[str, Any]) -> dict[str, Any]:
        coverage = self._coverage(candidates, state)
        pending = coverage["pending_segments"]
        failed = coverage["failed_segments"]
        if outcome == "cancelled":
            execution_status, termination_reason = "CANCELLED_WITH_CHECKPOINT", "OPERATOR_CANCELLED"
        elif outcome == "failed":
            execution_status, termination_reason = "FAILED", "SOURCE_OR_WORKER_ERROR"
        elif pending > 0:
            execution_status, termination_reason = "PARTIAL", "JOB_TIME_BUDGET_EXCEEDED"
        elif failed > 0:
            execution_status, termination_reason = "COMPLETED_WITH_FAILED_SEGMENTS", "NONE"
        else:
            execution_status, termination_reason = "FULLY_PROCESSED", "NONE"
        scientific_complete = pending == 0 and outcome not in {"cancelled", "failed"}
        return {
            "execution_status": execution_status,
            "termination_reason": termination_reason,
            "scientific_completion_status": "COMPLETE" if scientific_complete else "INCOMPLETE",
            "decision_scope": "FULL_CAPTURE" if scientific_complete else "PROCESSED_SUBSET_ONLY",
            "resume_available": pending > 0 and outcome != "failed",
            "coverage": coverage,
        }

    def _exit_status(self, completion: dict[str, Any], worker_error: str | None) -> str:
        if worker_error:
            return "FAILED"
        return completion["execution_status"]

    # ------------------------------------------------------------------
    # Association, funnel, decision
    # ------------------------------------------------------------------

    def _native_rows(self, session: dict[str, Any], capture: dict[str, Any]) -> list[dict[str, Any]]:
        native_path = Path(str(session.get("native_scan_path") or self.session_root.parent.parent / "ble" / "native" / "scans" / session["session_id"])) / "advertisements.jsonl"
        rows = read_jsonl(native_path)
        start, end = self._epoch(capture.get("b200_rf_started_at")), self._epoch(capture.get("b200_rf_finished_at"))
        if start is None or end is None:
            return rows
        filtered = []
        for row in rows:
            ts = self._epoch(row.get("timestamp_callback_utc"))
            if ts is not None and start <= ts <= end:
                filtered.append(row)
        return filtered

    def _associate(
        self,
        packets: list[dict[str, Any]],
        semantic_packets: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
        natives: list[dict[str, Any]],
        capture: dict[str, Any],
        session: dict[str, Any],
    ) -> dict[str, Any]:
        candidate_by_segment = {Path(str(row.get("iq_segment_path"))).name: row for row in candidates}
        # Only used for the raw on-air address bytes, which decoded_packets.jsonl
        # does not carry directly (semantic_packets.jsonl's addresses.advertiser.
        # address_raw_air_octets does). Never used to compute packet_id or any
        # disambiguating field -- see the packet_start_bit comment below for why.
        # Join key: a semantic row's own top-level "packet_id" equals the
        # confirmed packet's "packet_sha256" (matches ble_decode_burst_directory.py's
        # own semantic_by_id[item["packet_sha256"]] join) -- NOT "source_packet_sha256",
        # which is a different, unrelated hash and never matches packet_sha256.
        semantic_by_sha = {row.get("packet_id"): row for row in semantic_packets if row.get("packet_id")}
        target = str(session.get("target_address") or "").upper()
        start = self._epoch(capture.get("created_at_utc")) or self._epoch(capture.get("b200_rf_started_at")) or 0.0
        rate = float(capture["sample_rate_sps"])
        symbol_rate_hz = 1_000_000.0  # BLE LE 1M PHY
        target_callbacks = [row for row in natives if str(row.get("address", "")).upper() == target]
        ledger, used = [], set()
        for packet in packets:
            segment_name = str(packet.get("iq_segment") or "")
            candidate = candidate_by_segment.get(segment_name, {})
            candidate_id = candidate.get("candidate_id")
            segment_start_sample = int(candidate.get("start_sample", 0))
            # decoded_packets.jsonl already carries a bit-accurate offset
            # within the segment (packet_start_bit); use it so two packets
            # decoded from the SAME merged candidate never collapse onto the
            # same packet_start_sample/packet_id just because both lack a
            # payload hash.
            packet_start_bit = packet.get("packet_start_bit")
            start_sample = segment_start_sample + (round(int(packet_start_bit) * rate / symbol_rate_hz) if packet_start_bit is not None else 0)
            packet_time = start + float(start_sample) / rate
            # decoded_packets.jsonl (backend/tools/ble_decode_burst_directory.py)
            # already carries pdu_type_name/tx_add/rx_add/pdu_octets directly on
            # the confirmed-packet row, so packet_id/pdu fields no longer depend
            # on the semantic join succeeding (it only supplies the raw on-air
            # address bytes below, which decoded_packets.jsonl lacks).
            payload_hex = str(packet.get("pdu_octets") or packet.get("payload_octets") or "")
            packet_id = packet_identity_for(candidate_id or segment_name, start_sample, payload_hex)
            packet_address = str(packet.get("address") or "").upper()
            semantic = semantic_by_sha.get(packet.get("packet_sha256"), {})
            advertiser_address_raw = ((semantic.get("addresses") or {}).get("advertiser") or {}).get("address_raw_air_octets")
            address_present = bool(packet_address)

            candidates_in_window = []
            for native in natives:
                native_id = native.get("native_observation_id")
                if native_id in used:
                    continue
                ts = self._epoch(native.get("timestamp_callback_utc"))
                if ts is None:
                    continue
                delta_ms = (ts - packet_time) * 1000.0
                if abs(delta_ms) > 250.0:
                    continue
                candidates_in_window.append((native, delta_ms))

            address_matches = [item for item in candidates_in_window if str(item[0].get("address", "")).upper() == packet_address] if address_present else []
            selected = address_matches[0] if len(address_matches) == 1 else None

            if not address_present:
                address_match_status, rejection = "ADDRESS_NOT_PRESENT_IN_PDU", "ADDRESS_NOT_PRESENT_IN_PDU"
            elif selected:
                address_match_status, rejection = ("MATCHED" if packet_address == target else "MATCHED_NON_TARGET"), None
            elif len(address_matches) > 1:
                address_match_status, rejection = "AMBIGUOUS", "MULTIPLE_NATIVE_CALLBACKS"
            elif candidates_in_window:
                address_match_status, rejection = "MISMATCH", "ADDRESS_MISMATCH"
            else:
                address_match_status, rejection = "NO_CANDIDATE_IN_WINDOW", ("WINDOWS_TIMESTAMP_UNAVAILABLE" if not natives else "TIME_DELTA_ABOVE_THRESHOLD")

            temporal_match_status = "MATCHED" if selected else ("AMBIGUOUS" if len(candidates_in_window) > 1 else "NO_MATCH")
            is_target = bool(selected) and packet_address == target
            association_strength = "STRONG" if (selected and is_target and address_match_status == "MATCHED") else ("WEAK" if selected else "NONE")

            row = {
                "packet_id": packet_id,
                "candidate_id": candidate_id,
                # Explicit join key back to decoded/decoded_packets.jsonl and
                # decoded/semantic_packets.jsonl for downstream read-only
                # consumers (BLE Packet Analysis Lab) -- avoids relying on
                # positional alignment between separate JSONL files.
                "packet_sha256": packet.get("packet_sha256"),
                "packet_start_sample": start_sample,
                "rf_timestamp_utc": None,
                "pdu_type": packet.get("pdu_type_name"),
                "advertiser_address_raw": advertiser_address_raw,
                "advertiser_address_canonical": packet.get("address"),
                "address_type": packet.get("address_type"),
                "tx_add": packet.get("tx_add"),
                "rx_add": packet.get("rx_add"),
                "payload_sha256": hashlib.sha256(payload_hex.encode("ascii")).hexdigest() if payload_hex else None,
                "nearest_windows_callback_timestamp": selected[0].get("timestamp_callback_utc") if selected else None,
                "time_delta_ms": round(selected[1], 3) if selected else None,
                "address_match_status": address_match_status,
                "temporal_match_status": temporal_match_status,
                "association_strength": association_strength,
                "association_rejection_reason": rejection,
                "target_address_match": is_target,
                # Copied straight from decoded_packets.jsonl (see
                # ble_decode_burst_directory.py), which in turn copies them
                # from RecoveredBitstreamCandidate -- already computed
                # inside ble-worker-lab's dsp_receiver() during decode, not
                # re-derived here. None when the source row predates this
                # field (old real replays decoded before this change).
                "synchronization_score": packet.get("synchronization_score"),
                "symbol_phase": packet.get("symbol_phase"),
                "frequency_offset_hz": packet.get("frequency_offset_hz"),
                "frequency_fit_quality": packet.get("frequency_fit_quality"),
            }
            if selected:
                used.add(selected[0].get("native_observation_id"))
            ledger.append(row)

        strong_target = [row for row in ledger if row["association_strength"] == "STRONG"]
        conflicting = [row for row in ledger if row["address_match_status"] == "AMBIGUOUS"]
        temporally_matched = [row for row in ledger if row["temporal_match_status"] == "MATCHED"]
        return {
            "schema_version": "ble-rffi-replay-association-v2",
            "source_native_window_only": True,
            "target_address": target,
            "windows_target_callbacks_inside_window": len(target_callbacks),
            "first_target_callback_inside_window": min((row.get("timestamp_callback_utc") for row in target_callbacks), default=None),
            "last_target_callback_inside_window": max((row.get("timestamp_callback_utc") for row in target_callbacks), default=None),
            "packet_association_ledger": ledger,
            "strong_target_matches": len(strong_target),
            "conflicting_matches": len(conflicting),
            "native_temporal_matches": len(temporally_matched),
        }

    def _funnel(
        self,
        capture: dict[str, Any],
        candidates: list[dict[str, Any]],
        decoded: list[dict[str, Any]],
        semantic: list[dict[str, Any]],
        association: dict[str, Any],
        completion: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        min_duration, max_duration = 80, 4096
        duration_ok = [row for row in candidates if min_duration <= int(row.get("duration_samples", 0)) <= max_duration]
        unique_crc = {row.get("packet_sha256") for row in decoded if row.get("packet_sha256")}
        crc_valid = [row for row in decoded if row.get("crc_valid") is True or row.get("packet_sha256")]
        coverage = completion["coverage"]
        return {
            "schema_version": "ble-rffi-candidate-funnel-v2",
            "samples_examined": int(capture.get("actual_samples") or 0),
            "energy_excursion_groups": len(candidates),
            "pre_decoder_candidate_regions": len(candidates),
            "duration_filtered_candidates": len(duration_ok),
            "merged_candidate_regions": len(candidates),
            "frequency_plausible_candidates": len(duration_ok),
            "gfsk_demodulation_attempts": coverage["processed_segments"] + coverage["failed_segments"],
            "total_candidate_segments": coverage["total_candidate_segments"],
            "successfully_processed_segments": coverage["successfully_processed_segments"],
            "failed_timeout_segments": coverage["failed_timeout_segments"],
            "failed_decoder_error_segments": coverage["failed_decoder_error_segments"],
            "pending_segments": coverage["pending_segments"],
            "attempted_coverage": coverage["attempted_coverage"],
            "successful_coverage": coverage["successful_coverage"],
            "processed_segments": coverage["processed_segments"],
            "failed_segments": coverage["failed_segments"],
            "coverage_percentage": coverage["coverage_percentage"],
            "decoder_timeout_count": state.get("decoder_timeout_count", 0),
            "decoder_internal_error_count": state.get("decoder_internal_error_count", 0),
            "worker_restart_count": state.get("worker_restart_count", 0),
            "symbol_timing_candidates": None,
            "preamble_candidates": None,
            "advertising_access_address_hits": None,
            "header_valid_candidates": None,
            "length_valid_candidates": None,
            "dewhitening_completed": None,
            "crc_checked_packets": len(decoded),
            "crc_valid_packets": len(crc_valid),
            "unique_crc_valid_packets": len(unique_crc),
            "target_address_candidates": sum(1 for row in decoded if str(row.get("address", "")).upper() == association.get("target_address")),
            "native_temporal_matches": int(association.get("native_temporal_matches") or 0),
            "strong_target_matches": int(association.get("strong_target_matches") or 0),
            "conflicting_matches": int(association.get("conflicting_matches") or 0),
            "instrumentation_status": {
                "symbol_timing_candidates": "NOT_INSTRUMENTED_BY_CURRENT_DECODER",
                "preamble_candidates": "NOT_INSTRUMENTED_BY_CURRENT_DECODER",
                "advertising_access_address_hits": "NOT_INSTRUMENTED_BY_CURRENT_DECODER",
                "header_valid_candidates": "NOT_INSTRUMENTED_BY_CURRENT_DECODER",
                "length_valid_candidates": "NOT_INSTRUMENTED_BY_CURRENT_DECODER",
                "dewhitening_completed": "NOT_INSTRUMENTED_BY_CURRENT_DECODER",
            },
        }

    def _rejection_summary(self, candidates: list[dict[str, Any]], funnel: dict[str, Any]) -> dict[str, Any]:
        min_duration, max_duration = 80, 4096
        rejected_duration = [row for row in candidates if not (min_duration <= int(row.get("duration_samples", 0)) <= max_duration)]
        timeout_rows = [row for row in candidates if row["processing_status"] == CANDIDATE_FAILED_TIMEOUT]
        error_rows = [row for row in candidates if row["processing_status"] == CANDIDATE_FAILED_DECODER_ERROR]
        crc_not_recovered = [row for row in candidates if row.get("crc_status") == "NOT_RECOVERED"]
        return {
            "schema_version": "ble-rffi-candidate-rejection-summary-v2",
            "rejected_duration": len(rejected_duration),
            "rejected_gap_or_grouping": 0,
            "rejected_frequency_offset": None,
            "rejected_symbol_timing": None,
            "rejected_gfsk_demodulation": None,
            "rejected_preamble": None,
            "rejected_access_address": None,
            "rejected_header": None,
            "rejected_length": None,
            "rejected_dewhitening": None,
            "rejected_crc": len(crc_not_recovered),
            "decoder_timeout": len(timeout_rows),
            "decoder_internal_error": len(error_rows),
            "rejected_temporal_association": max(0, int(funnel.get("crc_valid_packets") or 0) - int(funnel.get("native_temporal_matches") or 0)),
            "rejected_target_conflict": int(funnel.get("conflicting_matches") or 0),
            "limited_samples_by_reason": {
                "rejected_duration": [
                    {"candidate_id": row.get("candidate_id"), "start_sample": row.get("start_sample"), "duration_samples": row.get("duration_samples")}
                    for row in rejected_duration[:25]
                ],
                "decoder_timeout": [
                    {"candidate_id": row.get("candidate_id"), "candidate_index": row.get("candidate_index"), "attempt_count": row.get("attempt_count")}
                    for row in timeout_rows[:25]
                ],
                "decoder_internal_error": [
                    {"candidate_id": row.get("candidate_id"), "candidate_index": row.get("candidate_index"), "attempt_count": row.get("attempt_count")}
                    for row in error_rows[:25]
                ],
            },
        }

    def _decision(self, capture: dict[str, Any], session: dict[str, Any], funnel: dict[str, Any], association: dict[str, Any], completion: dict[str, Any]) -> dict[str, Any]:
        quality_ok = all(int(capture.get(key) or 0) == 0 for key in ("overflow_count", "discontinuity_count", "short_read_count", "write_error_count"))
        quality_ok = quality_ok and capture.get("hash_status") == "VERIFIED" and capture.get("metadata_status") == "COMPLETE"
        source_policy_ok = (capture.get("experimental_metadata") or {}).get("source_working_tree_status") == "CLEAN"
        preflight_ok = bool((capture.get("experimental_metadata") or {}).get("preflight_valid_at_capture_start"))
        crc = int(funnel.get("crc_valid_packets") or 0)
        strong = int(funnel.get("strong_target_matches") or 0)
        conflicts = int(funnel.get("conflicting_matches") or 0)
        scientific_complete = completion["scientific_completion_status"] == "COMPLETE"

        if int(funnel.get("energy_excursion_groups") or 0) > 0 and crc == 0:
            decision = "BLE_STRUCTURE_OR_CRC_NOT_RECOVERED"
            reason = ["BLE_STRUCTURE_OBSERVED_CRC_NOT_RECOVERED" if funnel.get("gfsk_demodulation_attempts") else "ENERGY_PRESENT_BLE_STRUCTURE_NOT_ESTABLISHED"]
        elif crc > 0 and strong == 0:
            decision = "BLE_PACKETS_RECOVERED_TARGET_NOT_CORROBORATED"
            reason = ["BLE_PACKETS_RECOVERED_TARGET_NOT_CORROBORATED"]
            if association.get("windows_target_callbacks_inside_window", 0) <= 0:
                reason.append("TARGET_ASSOCIATION_NOT_EVALUABLE_FROM_PRESERVED_NATIVE_EVIDENCE")
        elif 1 <= strong <= 2:
            decision = "E4_MINIMAL_OBSERVED_BELOW_DATASET_ACCEPTANCE"
            reason = ["INSUFFICIENT_UNIQUE_TARGET_PACKETS"]
        elif strong >= 3 and conflicts == 0 and quality_ok and source_policy_ok and preflight_ok:
            decision = "E4_ACCEPTED_FOR_DATASET_CANDIDATE"
            reason = []
        else:
            decision = "OFFLINE_REPLAY_NOT_ACCEPTED"
            reason = ["REPLAY_GATE_NOT_SATISFIED"]

        if not scientific_complete:
            reason.append("DECODER_REPLAY_INCOMPLETE")
            if completion["termination_reason"] == "OPERATOR_CANCELLED":
                reason.append("DECODER_REPLAY_CANCELLED_BY_OPERATOR")
            if completion["termination_reason"] == "JOB_TIME_BUDGET_EXCEEDED":
                reason.append("DECODER_REPLAY_TIMEOUT")
            if decision == "E4_ACCEPTED_FOR_DATASET_CANDIDATE":
                decision = "E4_CANDIDATE_REQUIRES_COMPLETE_REPLAY"

        eligible = decision == "E4_ACCEPTED_FOR_DATASET_CANDIDATE" and scientific_complete
        if not quality_ok:
            reason.append("SOURCE_SESSION_QUALITY_NOT_ELIGIBLE")
        if not source_policy_ok:
            reason.append("SOURCE_WORKING_TREE_POLICY_NOT_PASSED")
        if not preflight_ok:
            reason.append("PREFLIGHT_NOT_VALID_AT_CAPTURE_START")

        return {
            "decision": decision,
            "scientific_decision": "INCOMPLETE_REPLAY" if not scientific_complete else decision,
            "partial_observation": "BLE_CRC_VALID_PACKETS_RECOVERED" if crc > 0 else "NO_CRC_VALID_PACKETS_YET",
            "target_corroboration_in_processed_subset": "ESTABLISHED" if strong > 0 else "NOT_ESTABLISHED",
            "maximum_observed_evidence_level": "E4" if strong > 0 else "E2" if association.get("windows_target_callbacks_inside_window") else "E1",
            "association_evidence_status": "ACCEPTED" if eligible else "MINIMAL_OBSERVATION" if strong else "NOT_CORROBORATED",
            "ground_truth_status": "PASSED_E4" if eligible else "INSUFFICIENT_FOR_ACCEPTED_E4",
            "dataset_eligibility_status": "ELIGIBLE" if eligible else "NOT_ELIGIBLE",
            "source_quality_gate": {
                "acquisition_status": "PASSED" if quality_ok else "FAILED",
                "source_working_tree_policy": "PASSED" if source_policy_ok else "FAILED",
                "preflight_valid_at_capture_start": preflight_ok,
            },
            "reason_codes": sorted(set(reason)),
            "next_operator_action": "REVIEW_REPLAY_RESULT_BEFORE_ANY_HARDWARE" if scientific_complete else "CONTINUE_REPLAY_FROM_CHECKPOINT",
        }

    def _write_artifacts(
        self,
        replay_dir: Path,
        provenance: dict[str, Any],
        configuration: dict[str, Any],
        funnel: dict[str, Any],
        rejection: dict[str, Any],
        association: dict[str, Any],
        candidates: list[dict[str, Any]],
        decision: dict[str, Any],
        completion: dict[str, Any],
        final_report: dict[str, Any],
        started_at: str,
        completed_at: str,
        exit_status: str,
        worker_error: str | None,
    ) -> dict[str, Any]:
        common = {**provenance, "started_at": started_at, "completed_at": completed_at, "exit_status": exit_status}
        manifest = {
            "schema_version": REPLAY_SCHEMA_VERSION,
            **common,
            "configuration": configuration,
            "decision": decision,
            "completion": completion,
            "worker_error": worker_error,
            "original_iq_modified": False,
            "read_only_source_iq": True,
        }
        write_json(replay_dir / "replay_manifest.json", manifest)
        write_json(replay_dir / "candidate_funnel.json", {**common, **funnel})
        write_json(replay_dir / "candidate_rejection_summary.json", {**common, **rejection})
        write_json(replay_dir / "target_association_results.json", {**common, **{k: v for k, v in association.items() if k != "packet_association_ledger"}})
        write_jsonl(replay_dir / "packet_association_ledger.jsonl", association.get("packet_association_ledger", []))
        write_jsonl(replay_dir / "crc_valid_packets.jsonl", [row for row in candidates if row.get("crc_status") == "VALID"])
        write_json(replay_dir / "replay_final_report.json", {**common, **final_report})
        return {
            name: {"path": str(replay_dir / name), "sha256": sha256_file(replay_dir / name), "size_bytes": (replay_dir / name).stat().st_size}
            for name in (
                "replay_manifest.json",
                "replay_configuration.json",
                "replay_state.json",
                "candidate_manifest.jsonl",
                "candidate_funnel.json",
                "candidate_rejection_summary.json",
                "crc_valid_packets.jsonl",
                "packet_association_ledger.jsonl",
                "target_association_results.json",
                "replay_final_report.json",
                "worker_stdout.log",
                "worker_stderr.log",
                "input_iq_sha256.txt",
            )
            if (replay_dir / name).exists()
        }

    def _git_revision(self, repo: Path) -> str:
        try:
            return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5, check=True).stdout.strip()
        except Exception:
            return "UNKNOWN"

    def _epoch(self, value: Any) -> float | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
        except Exception:
            return None
