from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.infrastructure.ble.ble_hybrid_campaign_manager import BleHybridCampaignManager
from app.infrastructure.ble.capture.ble_sdr_device_service import BleSdrDeviceService, SdrProbeConfig


def test_sdr_enumeration_is_shared_but_manual_refresh_is_physical(tmp_path):
    service = BleSdrDeviceService(SdrProbeConfig(tmp_path / "python", tmp_path / "probe"))
    calls = 0

    def probe():
        nonlocal calls
        calls += 1
        return {"available": True, "devices": [{"device_id": "sdr-b200", "available": True}]}

    service._probe_devices = probe  # type: ignore[method-assign]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service.list_devices(), range(4)))

    assert calls == 1
    assert all(result["devices"][0]["device_id"] == "sdr-b200" for result in results)
    results[0]["devices"][0]["device_id"] = "mutated-by-caller"
    assert service.list_devices()["devices"][0]["device_id"] == "sdr-b200"
    service.list_devices(force_probe=True)
    assert calls == 2


def test_internal_validation_session_is_not_operational_history(tmp_path):
    visible = tmp_path / "BLE-HYBRID-visible"
    internal = tmp_path / "BLE-HYBRID-internal"
    visible.mkdir()
    internal.mkdir()
    (visible / "session_manifest.json").write_text(
        '{"session_id":"visible","created_at_utc":"2026-07-19T01:00:00Z"}', encoding="utf-8"
    )
    (internal / "session_manifest.json").write_text(
        '{"session_id":"internal","created_at_utc":"2026-07-19T02:00:00Z",'
        '"operational_visibility":"internal_validation"}', encoding="utf-8"
    )
    manager = BleHybridCampaignManager(
        tmp_path, None, None, Path("python"), Path("decoder"), Path("correlator"), Path("worker")
    )
    assert [item["session_id"] for item in manager.list()] == ["visible"]
