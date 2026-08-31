from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path
from time import perf_counter

import numpy as np

from ..domain.models import WifiCaptureContract
from ..domain.support_matrix import SUPPORT_MATRIX
from ..infrastructure.capture_adapter import file_layout, iter_iq_chunks
from ..infrastructure.legacy_ofdm_decoder import find_stf_candidates
from ..infrastructure.metrics import StreamingIqMetrics
from ..infrastructure.gr_ieee80211_worker import GrIeee80211Worker
from ..infrastructure.mac_parser import RecoveredPsdu, parse_mpdu

PARTIAL_RECOVERY_NOTE = (
    "Recovery is partial: this receiver does not recover every transmitted frame, "
    "even on a clean channel. Every frame reported here passed FCS and is a "
    "confirmed, not candidate, frame. See receiver_internal_events.jsonl for the "
    "full per-stage diagnostic trace of the current, still-open loss."
)

# WIFI_GR_IEEE80211_WORKER lets an operator override the interpreter/script (e.g.
# a different machine's pinned GNU Radio environment), but with no override this
# resolves to the validated V3 worker so selecting the wifi_80211 pipeline always
# runs the real decoder without needing a per-session env var.
_DEFAULT_WIFI_WORKER_PYTHON = Path(r"C:\Users\Usuario\wifi-worker-lab\wifi-worker-env\python.exe")
_DEFAULT_WIFI_WORKER_SCRIPT = Path(__file__).resolve().parents[5] / "tools" / "wifi_80211_v3_worker.py"


def default_worker_command() -> str | None:
    """None if the pinned wifi-worker-lab environment isn't present on this
    machine (a different developer's machine, CI) -- callers then fall back to
    the existing scaffold instead of trying to spawn a missing interpreter.
    Unquoted: decode() splits this with shlex.split(..., posix=False) on
    Windows, which does not strip quote characters (it preserves them so
    Windows-style single-backslash paths survive un-mangled) -- quoting here
    would leave literal quote characters embedded in the resolved path."""
    if not _DEFAULT_WIFI_WORKER_PYTHON.is_file() or not _DEFAULT_WIFI_WORKER_SCRIPT.is_file():
        return None
    return f"{_DEFAULT_WIFI_WORKER_PYTHON} {_DEFAULT_WIFI_WORKER_SCRIPT}"


class WifiDecodeService:
    """V2 orchestrator. Full frame recovery is delegated to a pinned external worker."""

    def decode(self, contract: WifiCaptureContract, output_dir: Path) -> dict:
        output_dir.mkdir(parents=True, exist_ok=True)
        missing = contract.validate()
        if missing:
            return self._write_report(output_dir, contract, {"status": "non_reproducible_input", "missing_metadata": missing, "analysis_truncated": False})
        started = perf_counter(); metrics = StreamingIqMetrics(); candidate_map = {}; overlap = np.zeros(0, np.complex64); samples_read = 0; overlap_reprocessed = 0
        for offset, chunk in iter_iq_chunks(Path(contract.input_file), contract.datatype):
            metrics.update(chunk)
            search = np.concatenate((overlap, chunk))
            search_offset = offset - overlap.size
            overlap_reprocessed += int(overlap.size)
            for candidate in find_stf_candidates(search, search_offset):
                candidate["timestamp_seconds"] = candidate["sample_start"] / contract.sample_rate_hz
                candidate["capture_sha256"] = contract.input_iq_sha256
                key = f"{contract.input_iq_sha256}:{candidate['sample_start']}"
                previous = candidate_map.get(key)
                if previous is None or candidate["plateau_length"] > previous["plateau_length"]:
                    candidate_map[key] = candidate
            overlap = search[-256:].copy()
            samples_read += chunk.size
        candidates = sorted(candidate_map.values(), key=lambda item: item["sample_start"])
        layout = file_layout(Path(contract.input_file), contract.datatype)
        external = os.environ.get("WIFI_GR_IEEE80211_WORKER", "").strip() or (default_worker_command() or "")
        evidence = {"channel_profile_match": True, "rf_activity": metrics.result(contract.sample_rate_hz)["rms_magnitude"] > 1e-8, "stf_candidate": bool(candidates), "synchronized_candidate": False, "valid_l_sig": False, "psdu_recovered": False, "fcs_valid_frame": False, "mac_parsed": False}
        worker_state = {"configured": bool(external), "path": external or None, "status": "not_configured"}
        confirmed_frames: list[dict] = []
        extra_notes: list[str] = []
        extra_outputs: dict[str, str] = {}
        diagnostics_summary: dict | None = None
        if external:
            if contract.sample_rate_hz != 20_000_000.0 or contract.hardware_center_frequency_hz != contract.channel_center_frequency_hz:
                worker_state["status"] = "channelized_20msps_input_required"
                worker_state["fallback_to_current_scaffold"] = True
            else:
                worker_manifest = {**contract.to_dict(), "decoder_sample_rate_hz": 20_000_000.0, "input_kind": "channelized_complex_iq"}
                worker_manifest_path = output_dir / "worker_input_manifest.json"
                worker_manifest_path.write_text(json.dumps(worker_manifest, indent=2), encoding="utf-8")
                command = shlex.split(external, posix=os.name != "nt")
                if len(command) == 1 and command[0].lower().endswith(".py"):
                    command.insert(0, sys.executable)
                worker_output_dir = output_dir / "worker"
                process_result = GrIeee80211Worker(command).run(worker_manifest_path, worker_output_dir)
                worker_state.update(process_result.__dict__)
                worker_state["fallback_to_current_scaffold"] = process_result.status != "complete"
                if process_result.status == "complete":
                    confirmed_frames, evidence, extra_notes, extra_outputs, diagnostics_summary = self._merge_worker_result(worker_output_dir, output_dir, evidence)
                    worker_state["frames_confirmed"] = len(confirmed_frames)
        analysis_status = "preamble_candidates_only" if candidates else "no_valid_preamble"
        if confirmed_frames:
            analysis_status = "frames_confirmed_partial_recovery"
        result = {"status": analysis_status, "final_status": "not_decoded" if not confirmed_frames else "frames_confirmed", "valid_demodulation": bool(confirmed_frames), "analysis_truncated": samples_read < contract.sample_count, **layout, "samples_read_from_file": samples_read, "unique_samples_processed": samples_read, "overlap_samples_reprocessed": overlap_reprocessed, "samples_discarded": max(0, layout["samples_total_in_file"] - samples_read), "rf_activity": metrics.result(contract.sample_rate_hz), "evidence": evidence, "preamble_candidates": candidates, "frames_decoded": len(confirmed_frames), "frames_crc_valid": len(confirmed_frames), "receiver_diagnostics_summary": diagnostics_summary, "support_matrix": SUPPORT_MATRIX, "external_worker": worker_state, "failures_by_reason": {"unsupported_phy": len(candidates)}, "processing_duration_seconds": perf_counter() - started, "notes": ["STF correlation candidates are not decoded IEEE 802.11 frames.", "MAC parsing accepts only complete PSDUs returned by the validated PHY worker.", "P0 frame recovery requires a pinned and validated gr-ieee802-11 worker.", "No noiseFloorOffset was applied.", *extra_notes]}
        (output_dir / "failed_frame_candidates.json").write_text(json.dumps({"candidates": candidates}, indent=2), encoding="utf-8")
        (output_dir / "decoded_frames.json").write_text(json.dumps({"frames": confirmed_frames}, indent=2), encoding="utf-8")
        return self._write_report(output_dir, contract, result, extra_outputs)

    def _merge_worker_result(self, worker_output_dir: Path, output_dir: Path, evidence: dict) -> tuple[list[dict], dict, list[str], dict[str, str], dict | None]:
        """Reads the real worker's confirmed frames and turns them into MAC-parsed
        results via the existing, fail-closed mac_parser -- reused unchanged. Also
        promotes the worker's diagnostic evidence (receiver_internal_events.jsonl,
        software_versions.json) up to the top-level output_dir so the existing
        outputs/{filename} download endpoint serves them with no new code."""
        result_path = worker_output_dir / "worker_result.json"
        extra_outputs: dict[str, str] = {}
        notes: list[str] = []
        if not result_path.is_file():
            return [], evidence, notes, extra_outputs, None
        try:
            worker_result = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception:
            return [], evidence, ["Worker result could not be parsed."], extra_outputs, None

        confirmed_frames = []
        for raw_frame in worker_result.get("frames", []):
            try:
                mpdu = bytes.fromhex(raw_frame["mpdu_hex"])
                # decode_mac already verified FCS internally and does not
                # retransmit the trailing FCS bytes in the published PDU.
                parsed = parse_mpdu(RecoveredPsdu(data=mpdu, complete=True, source="validated_phy_worker", fcs_included=False))
                confirmed_frames.append({"arrival_order": raw_frame.get("arrival_order"), **parsed})
            except Exception as exc:
                notes.append(f"A worker-reported frame failed MAC parsing and was excluded: {exc}")

        if confirmed_frames:
            evidence = {**evidence, "synchronized_candidate": True, "valid_l_sig": True, "psdu_recovered": True, "fcs_valid_frame": True, "mac_parsed": True}
            notes.append(PARTIAL_RECOVERY_NOTE)

        diagnostics_summary = worker_result.get("receiver_diagnostics_summary")
        if diagnostics_summary:
            notes.append(f"Receiver diagnostics: {json.dumps(diagnostics_summary)}")

        for filename in ("receiver_internal_events.jsonl", "software_versions.json"):
            source = worker_output_dir / filename
            if source.is_file():
                destination = output_dir / filename
                destination.write_bytes(source.read_bytes())
                extra_outputs[filename.rsplit(".", 1)[0]] = str(destination)

        return confirmed_frames, evidence, notes, extra_outputs, diagnostics_summary

    def _write_report(self, output_dir: Path, contract: WifiCaptureContract, result: dict, extra_outputs: dict[str, str] | None = None) -> dict:
        manifest = contract.to_dict(); (output_dir / "capture_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        outputs = {"report": str(output_dir / "demodulation_report.json"), "capture_manifest": str(output_dir / "capture_manifest.json"), "decoded_frames": str(output_dir / "decoded_frames.json"), "failed_frame_candidates": str(output_dir / "failed_frame_candidates.json"), **(extra_outputs or {})}
        report = {"decoder": "wifi_80211_v2", "version": "0.1-foundation", "protocol": "wifi_80211", "pipeline": "wifi_80211", **result, "outputs": outputs}
        (output_dir / "demodulation_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report
