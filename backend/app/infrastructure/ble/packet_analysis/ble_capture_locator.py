"""Locates BLE captures and their replay lineage, read-only.

Never writes into iq_captures/ or ble_lab/sessions/. Joins
campaign_id -> condition_id -> session_role -> execution_id -> capture_id ->
iq_sha256 -> replay_run_id purely by reading existing manifests.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import (
    LAST_ACCEPTED_CAPTURE,
    LAST_COMPLETED_CAPTURE,
    LAST_CREATED_CAPTURE,
    LAST_FULLY_ANALYZED_CAPTURE,
)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


class BleCaptureLocator:
    def __init__(self, capture_root: Path, session_root: Path) -> None:
        self.capture_root = capture_root
        self.session_root = session_root

    def _sessions_by_capture_id(self) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for manifest_path in self.session_root.glob("BLE-HYBRID-*/session_manifest.json"):
            session = _read_json(manifest_path)
            if not session or not session.get("capture_id"):
                continue
            session["_session_manifest_path"] = str(manifest_path)
            index.setdefault(session["capture_id"], session)
        return index

    def _latest_replay(self, capture_dir: Path) -> dict[str, Any] | None:
        replay_root = capture_dir / "offline_replays"
        if not replay_root.is_dir():
            return None
        candidates = []
        for run_dir in replay_root.iterdir():
            if not run_dir.is_dir():
                continue
            summary = _read_json(run_dir / "replay_summary.json")
            state = _read_json(run_dir / "replay_state.json")
            if summary is None and state is None:
                continue
            candidates.append((run_dir, summary, state))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0].stat().st_mtime, reverse=True)
        run_dir, summary, state = candidates[0]
        if summary is not None:
            return {
                "replay_run_id": run_dir.name,
                "execution_status": summary.get("execution_status"),
                "scientific_completion_status": summary.get("scientific_completion_status"),
                "coverage": summary.get("coverage"),
                "decision": (summary.get("decision") or {}).get("decision"),
                "dataset_eligibility_status": (summary.get("decision") or {}).get("dataset_eligibility_status"),
                "crc_valid_packets": (summary.get("candidate_funnel") or {}).get("crc_valid_packets"),
                "unique_crc_valid_packets": (summary.get("candidate_funnel") or {}).get("unique_crc_valid_packets"),
                "strong_target_matches": (summary.get("candidate_funnel") or {}).get("strong_target_matches"),
                "conflicting_matches": (summary.get("candidate_funnel") or {}).get("conflicting_matches"),
            }
        return {
            "replay_run_id": run_dir.name,
            "execution_status": "IN_PROGRESS" if (state or {}).get("checkpoint_sequence") is not None else None,
            "scientific_completion_status": None,
            "coverage": None,
            "decision": None,
            "dataset_eligibility_status": None,
            "crc_valid_packets": None,
            "unique_crc_valid_packets": None,
            "strong_target_matches": None,
            "conflicting_matches": None,
        }

    def list_captures(self) -> list[dict[str, Any]]:
        sessions = self._sessions_by_capture_id()
        rows = []
        if not self.capture_root.is_dir():
            return rows
        for capture_dir in sorted(self.capture_root.iterdir()):
            if not capture_dir.is_dir():
                continue
            manifest = _read_json(capture_dir / "capture_manifest.json")
            if not manifest:
                continue
            capture_id = manifest.get("capture_id") or capture_dir.name
            session = sessions.get(capture_id, {})
            metadata = manifest.get("experimental_metadata") or {}
            replay = self._latest_replay(capture_dir)
            quality_ok = all(int(manifest.get(key) or 0) == 0 for key in ("overflow_count", "discontinuity_count", "short_read_count", "write_error_count"))
            quality_ok = quality_ok and manifest.get("hash_status") == "VERIFIED" and manifest.get("metadata_status") == "COMPLETE"
            rows.append({
                "capture_id": capture_id,
                "execution_id": session.get("session_id"),
                "campaign_id": metadata.get("campaign_id"),
                "condition_id": metadata.get("condition_id"),
                "session_role": metadata.get("session_id") or metadata.get("operator_session_id"),
                "iq_sha256": manifest.get("data_sha256"),
                "created_at_utc": manifest.get("created_at_utc"),
                "duration_seconds": (
                    round(int(manifest.get("actual_samples") or 0) / float(manifest.get("sample_rate_sps") or 1), 3)
                    if manifest.get("actual_samples") else None
                ),
                "ble_channel": manifest.get("ble_channel"),
                "center_frequency_hz": manifest.get("center_frequency_hz"),
                "sample_rate_sps": manifest.get("sample_rate_sps"),
                "receiver": "USRP_B200",
                "actual_samples": manifest.get("actual_samples"),
                "actual_size_bytes": manifest.get("actual_size_bytes"),
                "hash_status": manifest.get("hash_status"),
                "acquisition_quality": "PASSED" if quality_ok else "FAILED",
                "replay": replay,
                "target_address": session.get("target_address"),
                "_mtime": capture_dir.stat().st_mtime,
            })
        return rows

    def classify(self, rows: list[dict[str, Any]]) -> dict[str, str | None]:
        """Returns capture_id for each named classification (sec. 5); never
        conflates "most recently created" with "fully analyzed"."""
        if not rows:
            return {LAST_CREATED_CAPTURE: None, LAST_COMPLETED_CAPTURE: None, LAST_FULLY_ANALYZED_CAPTURE: None, LAST_ACCEPTED_CAPTURE: None}
        by_created = sorted(rows, key=lambda row: row["_mtime"], reverse=True)
        by_completed = [row for row in by_created if (row["replay"] or {}).get("execution_status") is not None]
        by_fully_analyzed = [row for row in by_created if (row["replay"] or {}).get("scientific_completion_status") == "COMPLETE"]
        by_accepted = [row for row in by_fully_analyzed if (row["replay"] or {}).get("dataset_eligibility_status") == "ELIGIBLE"]
        return {
            LAST_CREATED_CAPTURE: by_created[0]["capture_id"] if by_created else None,
            LAST_COMPLETED_CAPTURE: by_completed[0]["capture_id"] if by_completed else None,
            LAST_FULLY_ANALYZED_CAPTURE: by_fully_analyzed[0]["capture_id"] if by_fully_analyzed else None,
            LAST_ACCEPTED_CAPTURE: by_accepted[0]["capture_id"] if by_accepted else None,
        }

    def get_capture(self, capture_id: str) -> dict[str, Any] | None:
        for row in self.list_captures():
            if row["capture_id"] == capture_id:
                return row
        return None

    def resolve_replay_dir(self, capture_id: str, replay_run_id: str | None = None) -> Path:
        capture_dir = self.capture_root / capture_id
        if not capture_dir.is_dir():
            raise FileNotFoundError(f"CAPTURE_NOT_FOUND:{capture_id}")
        if replay_run_id:
            replay_dir = capture_dir / "offline_replays" / replay_run_id
            if not replay_dir.is_dir():
                raise FileNotFoundError(f"REPLAY_RUN_NOT_FOUND:{replay_run_id}")
            return replay_dir
        replay_root = capture_dir / "offline_replays"
        if not replay_root.is_dir():
            raise FileNotFoundError(f"NO_REPLAY_FOR_CAPTURE:{capture_id}")
        candidates = [p for p in replay_root.iterdir() if p.is_dir() and (p / "replay_summary.json").is_file()]
        if not candidates:
            raise FileNotFoundError(f"NO_COMPLETED_REPLAY_FOR_CAPTURE:{capture_id}")
        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return candidates[0]
