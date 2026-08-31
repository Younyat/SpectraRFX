"""Authors a brand-new legacy-format capture (capture_manifest.json +
.sigmf-data/.sigmf-meta + a matching session_manifest.json) from an edited
IQ buffer produced by device_scrubber.py, so the result can be registered and
decoded through the EXISTING ingestion pipeline
(StudioRepository.build_capture -> replay-and-evidence job) completely
unchanged.

No change to CaptureRecord's schema anywhere: every provenance fact this
derivation needs lives inside experimental_metadata, a dict both
capture_stage.py and ble_offline_replay.py already read permissively (extra
keys are simply ignored by anything that doesn't know about them).

Reuses the original capture's OWN session_manifest.json (same native-scan
window, same RF timing) rather than inventing one -- the native BLE
observations recorded during that real acquisition remain valid evidence for
whatever ambient transmitters survive the excision; only the target
device's own footprint changes.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import numpy as np

from app.infrastructure.ble.capture.ble_capture_metadata import atomic_json, sha256_file
from app.infrastructure.ble.capture.ble_offline_replay import read_json

from .device_scrubber import ScrubReport, save_iq


class SourceSessionNotFoundError(Exception):
    pass


def find_source_session_manifest(legacy_session_root: Path, capture_id: str) -> tuple[Path, dict[str, Any]]:
    matches = []
    for manifest_path in legacy_session_root.glob("BLE-HYBRID-*/session_manifest.json"):
        try:
            manifest = read_json(manifest_path)
        except Exception:
            continue
        if manifest.get("capture_id") == capture_id:
            matches.append((manifest_path, manifest))
    if len(matches) != 1:
        raise SourceSessionNotFoundError(f"SOURCE_SESSION_NOT_UNAMBIGUOUS_FOR_CAPTURE:{capture_id}:{len(matches)}_matches")
    return matches[0]


def derive_scrubbed_capture(
    *,
    legacy_capture_root: Path,
    legacy_session_root: Path,
    source_capture_id: str,
    edited_iq: np.ndarray,
    sample_format: str,
    scrub_report: ScrubReport,
    excised_physical_unit_id: str,
) -> dict[str, Any]:
    """Returns {"capture_id", "session_id", "execution_id"} -- pass these
    straight into StudioRepository.build_capture(...) and then
    start_replay_and_evidence_job(...) to decode and evidence the result."""
    source_dir = legacy_capture_root / source_capture_id
    source_manifest = read_json(source_dir / "capture_manifest.json")
    _session_path, session_manifest = find_source_session_manifest(legacy_session_root, source_capture_id)

    new_capture_id = f"BLE-IQ-SCRUB-{uuid.uuid4().hex[:12]}"
    new_session_id = f"BLE-HYBRID-SCRUB-{uuid.uuid4().hex[:12]}"
    new_capture_dir = legacy_capture_root / new_capture_id
    new_capture_dir.mkdir(parents=True, exist_ok=False)

    data_filename = f"{new_capture_id}.sigmf-data"
    meta_filename = f"{new_capture_id}.sigmf-meta"
    data_path = new_capture_dir / data_filename
    save_iq(edited_iq, data_path, sample_format)
    data_sha256 = sha256_file(data_path)
    file_size = data_path.stat().st_size

    derivation_metadata = {
        "derived_from_capture_id": source_capture_id,
        "derivation_method": "DEVICE_PACKET_EXCISION_V1",
        "excised_physical_unit_id": excised_physical_unit_id,
        "windows_removed": scrub_report["windows_removed"],
        "windows_without_donor": scrub_report["windows_without_donor"],
        "samples_replaced": scrub_report["samples_replaced"],
    }

    new_manifest = dict(source_manifest)
    new_manifest.update({
        "capture_id": new_capture_id,
        "data_path": data_filename,
        "metadata_path": meta_filename,
        "data_sha256": data_sha256,
        "actual_file_size_bytes": file_size,
        "expected_file_size_bytes": file_size,
        "actual_size_bytes": file_size,
        "expected_size_bytes": file_size,
        "storage_target": str(new_capture_dir),
    })
    new_manifest["experimental_metadata"] = {**(source_manifest.get("experimental_metadata") or {}), **derivation_metadata}
    atomic_json(new_capture_dir / "capture_manifest.json", new_manifest)

    sigmf_meta_path = source_dir / str(source_manifest.get("metadata_path") or f"{source_capture_id}.sigmf-meta")
    if sigmf_meta_path.is_file():
        sigmf_meta = read_json(sigmf_meta_path)
        atomic_json(new_capture_dir / meta_filename, sigmf_meta)
        new_manifest["metadata_sha256"] = sha256_file(new_capture_dir / meta_filename)
        atomic_json(new_capture_dir / "capture_manifest.json", new_manifest)

    new_session_manifest = dict(session_manifest)
    new_session_manifest.pop("_session_manifest_path", None)
    new_session_manifest.update({
        "session_id": new_session_id,
        "capture_id": new_capture_id,
        "capture_manifest": str(new_capture_dir / "capture_manifest.json"),
    })
    new_session_manifest["experimental_metadata"] = {**(session_manifest.get("experimental_metadata") or {}), **derivation_metadata}
    new_session_dir = legacy_session_root / new_session_id
    new_session_dir.mkdir(parents=True, exist_ok=False)
    atomic_json(new_session_dir / "session_manifest.json", new_session_manifest)

    return {"capture_id": new_capture_id, "session_id": new_session_id, "execution_id": new_session_id}
