from __future__ import annotations

import pytest

from app.modules.storage_management.service import StorageManagementError, StorageManagementService


class FakeCaptureManager:
    def __init__(self, manifests):
        self._manifests = manifests

    def list_captures(self):
        return self._manifests


def _write(path, size_bytes: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size_bytes)


def test_summary_reports_real_sizes_per_top_level_category(tmp_path):
    _write(tmp_path / "ble" / "iq_captures" / "BLE-IQ-a" / "BLE-IQ-a.sigmf-data", 100)
    _write(tmp_path / "scientific_reports" / "report.pdf", 50)

    service = StorageManagementService(tmp_path)
    summary = service.summary()

    assert summary["total_bytes"] == 150
    names = {category["name"] for category in summary["categories"]}
    assert names == {"ble", "scientific_reports"}
    ble_category = next(category for category in summary["categories"] if category["name"] == "ble")
    assert ble_category["total_bytes"] == 100
    assert ble_category["file_count"] == 1


def test_summary_on_missing_storage_root_returns_empty(tmp_path):
    service = StorageManagementService(tmp_path / "does-not-exist")
    summary = service.summary()
    assert summary["total_bytes"] == 0
    assert summary["categories"] == []


def test_list_items_marks_generic_directory_preserved_by_default(tmp_path):
    _write(tmp_path / "mlops" / "bundle-1" / "model.bin", 10)
    service = StorageManagementService(tmp_path)

    result = service.list_items("mlops")

    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["display_name"] == "bundle-1"
    assert item["size_bytes"] == 10
    assert item["preserved"] is True


def test_list_items_marks_known_cache_pattern_not_preserved(tmp_path):
    _write(tmp_path / "ble" / "iq_captures" / "BLE-IQ-a" / "offline_replays" / "r1" / "replay_summary.json", 5)
    service = StorageManagementService(tmp_path)

    result = service.list_items("ble/iq_captures/BLE-IQ-a")

    item = next(item for item in result["items"] if item["display_name"] == "offline_replays")
    assert item["preserved"] is False


def test_list_items_for_ble_iq_captures_uses_real_capture_manifests(tmp_path):
    _write(tmp_path / "ble" / "iq_captures" / "BLE-IQ-a" / "BLE-IQ-a.sigmf-data", 100)
    _write(tmp_path / "ble" / "iq_captures" / "BLE-IQ-b" / "BLE-IQ-b.sigmf-data", 300)
    manifests = [
        {"capture_id": "BLE-IQ-a", "created_at_utc": "2026-08-01T00:00:00Z", "ble_channel": 37, "dataset_eligible": True},
        {"capture_id": "BLE-IQ-b", "created_at_utc": "2026-08-02T00:00:00Z", "ble_channel": 38, "dataset_eligible": False},
    ]
    service = StorageManagementService(tmp_path, capture_manager=FakeCaptureManager(manifests))

    result = service.list_items("ble/iq_captures")

    assert [item["display_name"] for item in result["items"]] == ["BLE-IQ-b", "BLE-IQ-a"]
    newest = result["items"][0]
    assert newest["kind"] == "ble_capture"
    assert newest["size_bytes"] == 300
    assert newest["preserved"] is True
    assert newest["extra"]["ble_channel"] == 38


def test_list_items_for_ble_capture_without_manifest_is_still_shown_and_preserved(tmp_path):
    _write(tmp_path / "ble" / "iq_captures" / "BLE-IQ-orphan" / "partial.sigmf-data", 42)
    service = StorageManagementService(tmp_path, capture_manager=FakeCaptureManager([]))

    result = service.list_items("ble/iq_captures")

    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["kind"] == "ble_capture_incomplete"
    assert item["preserved"] is True
    assert item["size_bytes"] == 42


def test_list_items_raises_file_not_found_for_missing_path(tmp_path):
    service = StorageManagementService(tmp_path)
    with pytest.raises(FileNotFoundError):
        service.list_items("does-not-exist")


def test_delete_item_requires_confirm_true(tmp_path):
    _write(tmp_path / "mlops" / "bundle" / "model.bin", 10)
    service = StorageManagementService(tmp_path)
    with pytest.raises(StorageManagementError):
        service.delete_item("mlops/bundle", confirm=False)
    assert (tmp_path / "mlops" / "bundle").exists()


def test_delete_item_removes_a_real_directory_and_reports_freed_bytes(tmp_path):
    _write(tmp_path / "mlops" / "bundle" / "model.bin", 10)
    service = StorageManagementService(tmp_path)

    result = service.delete_item("mlops/bundle", confirm=True)

    assert result == {"deleted_item_id": "mlops/bundle", "freed_bytes": 10}
    assert not (tmp_path / "mlops" / "bundle").exists()


def test_delete_item_removes_a_real_file(tmp_path):
    _write(tmp_path / "scientific_reports" / "report.pdf", 25)
    service = StorageManagementService(tmp_path)

    result = service.delete_item("scientific_reports/report.pdf", confirm=True)

    assert result["freed_bytes"] == 25
    assert not (tmp_path / "scientific_reports" / "report.pdf").exists()


def test_delete_item_raises_file_not_found_for_missing_item(tmp_path):
    service = StorageManagementService(tmp_path)
    with pytest.raises(FileNotFoundError):
        service.delete_item("mlops/does-not-exist", confirm=True)


def test_delete_item_refuses_path_traversal_outside_storage_root(tmp_path):
    (tmp_path / "storage").mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    service = StorageManagementService(tmp_path / "storage")

    with pytest.raises(StorageManagementError):
        service.delete_item("../outside.txt", confirm=True)
    assert outside.exists()


def test_delete_item_refuses_to_delete_the_storage_root_itself(tmp_path):
    (tmp_path / "keep.txt").write_text("keep")
    service = StorageManagementService(tmp_path)
    with pytest.raises(StorageManagementError):
        service.delete_item("", confirm=True)
    assert (tmp_path / "keep.txt").exists()
