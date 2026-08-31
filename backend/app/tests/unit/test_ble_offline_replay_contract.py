import json
from pathlib import Path

import pytest

from app.infrastructure.ble.capture.ble_offline_replay import BleOfflineReplayService, sha256_file


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def source_tree(tmp_path: Path):
    capture_root = tmp_path / "ble" / "iq_captures"
    session_root = tmp_path / "ble_lab" / "sessions"
    capture_id = "BLE-IQ-test000001"
    execution_id = "BLE-HYBRID-test000001"
    capture_dir = capture_root / capture_id
    capture_dir.mkdir(parents=True)
    data = capture_dir / f"{capture_id}.sigmf-data"
    data.write_bytes(b"\x00" * 64)
    digest = sha256_file(data)
    manifest = {
        "capture_id": capture_id,
        "data_path": data.name,
        "data_sha256": digest,
        "actual_samples": 8,
        "actual_size_bytes": 64,
        "sample_format": "cf32_le",
        "sample_rate_sps": 4_000_000,
        "center_frequency_hz": 2_402_000_000,
        "bandwidth_hz": 2_000_000,
        "ble_channel": 37,
        "hash_status": "VERIFIED",
        "metadata_status": "COMPLETE",
        "overflow_count": 0,
        "discontinuity_count": 0,
        "short_read_count": 0,
        "write_error_count": 0,
        "experimental_metadata": {
            "campaign_id": "BLE-RFFI-CC2650-UNIT-01-CH37-v1",
            "condition_id": "C001",
            "session_id": "S001-POS",
            "execution_purpose": "POSITIVE_PILOT",
            "source_working_tree_status": "CLEAN",
            "preflight_valid_at_capture_start": True,
        },
    }
    write_json(capture_dir / "capture_manifest.json", manifest)
    write_json(session_root / execution_id / "session_manifest.json", {
        "session_id": execution_id,
        "capture_id": capture_id,
        "target_address": "B0:B4:48:C0:36:06",
        "native_scan_path": str(tmp_path / "ble" / "native" / "scans" / execution_id),
        "experimental_metadata": manifest["experimental_metadata"],
    })
    return BleOfflineReplayService(capture_root, session_root=session_root, backend_root=Path("backend")), capture_id, execution_id, digest


def test_replay_rejects_capture_from_other_execution(tmp_path):
    service, capture_id, _, digest = source_tree(tmp_path)
    with pytest.raises(ValueError, match="CAPTURE_ID_DOES_NOT_BELONG_TO_EXECUTION_ID"):
        service.create(capture_id, {"execution_id": "BLE-HYBRID-other", "expected_iq_sha256": digest})


def test_replay_rejects_sha_mismatch_before_detector(tmp_path):
    service, capture_id, execution_id, _ = source_tree(tmp_path)
    with pytest.raises(ValueError, match="REPLAY_SOURCE_IQ_SHA256_MISMATCH"):
        service.create(capture_id, {"execution_id": execution_id, "expected_iq_sha256": "0" * 64})


def test_replay_rejects_rf_configuration_mismatch(tmp_path):
    service, capture_id, execution_id, digest = source_tree(tmp_path)
    manifest = service._capture_dir(capture_id) / "capture_manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["sample_rate_sps"] = 8_000_000
    write_json(manifest, data)
    with pytest.raises(ValueError, match="REPLAY_RF_CONFIGURATION_MISMATCH:sample_rate_sps"):
        service.create(capture_id, {"execution_id": execution_id, "expected_iq_sha256": digest})


# Real bug found and fixed: REQUIRED_RF used to hardcode ble_channel=37 /
# center_frequency_hz=2_402_000_000 as the ONLY accepted combination,
# rejecting every real channel 38/39 capture before OFFLINE_REPLAY ever
# started -- even though the decoder itself (ble_worker.whitening.
# ble_dewhiten) already parameterizes dewhitening on channel_index for any
# BLE channel. _validate_source is exercised directly here (not through
# create()) since a full create() run would go on to invoke the real
# decoder on fake placeholder IQ bytes, which is a different, unrelated
# failure mode from what these tests check.
@pytest.mark.parametrize("channel,frequency_hz", [(37, 2_402_000_000), (38, 2_426_000_000), (39, 2_480_000_000)])
def test_validate_source_accepts_every_primary_advertising_channel(tmp_path, channel, frequency_hz):
    service, capture_id, execution_id, digest = source_tree(tmp_path)
    capture = json.loads((service._capture_dir(capture_id) / "capture_manifest.json").read_text(encoding="utf-8"))
    capture["ble_channel"] = channel
    capture["center_frequency_hz"] = frequency_hz
    session = {"capture_id": capture_id, "_session_manifest_path": str(service._capture_dir(capture_id) / "capture_manifest.json")}
    service._validate_source(capture_id, capture, session, digest)  # must not raise


def test_validate_source_rejects_channel_frequency_mismatch(tmp_path):
    service, capture_id, execution_id, digest = source_tree(tmp_path)
    capture = json.loads((service._capture_dir(capture_id) / "capture_manifest.json").read_text(encoding="utf-8"))
    capture["ble_channel"] = 38
    # center_frequency_hz left at the channel-37 value from the fixture --
    # a real, physically inconsistent combination that must still be caught.
    session = {"capture_id": capture_id, "_session_manifest_path": str(service._capture_dir(capture_id) / "capture_manifest.json")}
    with pytest.raises(ValueError, match="REPLAY_RF_CONFIGURATION_MISMATCH:center_frequency_hz"):
        service._validate_source(capture_id, capture, session, digest)


def test_validate_source_rejects_unknown_channel(tmp_path):
    service, capture_id, execution_id, digest = source_tree(tmp_path)
    capture = json.loads((service._capture_dir(capture_id) / "capture_manifest.json").read_text(encoding="utf-8"))
    capture["ble_channel"] = 12  # a real general-purpose channel, but not yet supported by this pipeline
    session = {"capture_id": capture_id, "_session_manifest_path": str(service._capture_dir(capture_id) / "capture_manifest.json")}
    with pytest.raises(ValueError, match="REPLAY_RF_CONFIGURATION_MISMATCH:ble_channel"):
        service._validate_source(capture_id, capture, session, digest)
