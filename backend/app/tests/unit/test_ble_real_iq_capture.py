import json
import time
from pathlib import Path

import pytest

from app.infrastructure.ble.capture.ble_capture_job_manager import BleCaptureJobManager
from app.infrastructure.ble.capture.ble_capture_metadata import atomic_json, sha256_file
from app.modules.ble_lab.module import BLE_CAPTURE_AND_DECODE_ENABLED
from tools import ble_sdr_capture_worker


class FakeDevices:
    def __init__(self, available=True): self.available = available
    def list_devices(self):
        devices = [{"device_id":"sdr-test","driver":"fake-test-only","label":"Infrastructure fake",
                    "frequency_ranges_hz":[{"minimum":2_000_000_000,"maximum":3_000_000_000}],
                    "sample_rate_ranges_sps":[{"minimum":4_000_000,"maximum":20_000_000}],
                    "bandwidth_ranges_hz":[{"minimum":1_000_000,"maximum":10_000_000}]}] if self.available else []
        return {"available":self.available,"devices":devices,"reason_code":None if self.available else "NO_COMPATIBLE_SDR"}
    def private_args(self, device_id):
        if not self.available or device_id != "sdr-test": raise ValueError("UNKNOWN_SDR_DEVICE")
        return {"driver":"fake-test-only"}


class FakeCapture:
    def __init__(self, mode="complete"): self.mode = mode
    def capture(self, request_path: Path, output: Path, cancel):
        request=json.loads(request_path.read_text()); cid=request["capture_id"]
        if self.mode == "wait":
            for _ in range(100):
                if cancel(): return {"cancelled":True,"exit_code":-1}
                time.sleep(.005)
        data=output/f"{cid}.sigmf-data"; data.write_bytes(b"\x01\x02"*16)
        meta=output/f"{cid}.sigmf-meta"; atomic_json(meta,{"global":{"core:version":"1.2.6","core:datatype":"ci8","core:sample_rate":8_000_000,"core:hw":"Test fake","core:recorder":"Tests"},"captures":[{"core:sample_start":0,"core:frequency":2_402_000_000,"core:datetime":"2026-01-01T00:00:00Z"}],"annotations":[]})
        if self.mode == "timeout_after_iq":
            raise TimeoutError("CAPTURE_TIMEOUT")
        manifest={"schema_version":"1.0","capture_id":cid,"created_at_utc":"2026-01-01T00:00:00Z","data_path":data.name,"metadata_path":meta.name,"data_sha256":sha256_file(data),"metadata_sha256":sha256_file(meta),"capture_complete":True,"sample_rate_sps":8_000_000,"sample_format":"ci8","ble_channel":37}
        if self.mode == "bad_hash": manifest["data_sha256"]="0"*64
        atomic_json(output/"capture_manifest.json",manifest)
        return {"cancelled":False,"exit_code":0}


def payload(**changes):
    value={"device_id":"sdr-test","ble_channel":37,"center_frequency_hz":2_402_000_000,"sample_rate_sps":8_000_000,"bandwidth_hz":2_000_000,"gain_mode":"manual","gain_db":24,"duration_seconds":1,"sample_format":"ci8"}
    value.update(changes); return value


def manager(tmp_path, enabled=True, devices=True, mode="complete"):
    return BleCaptureJobManager(tmp_path,FakeDevices(devices),FakeCapture(mode),enabled,minimum_free_bytes=0)


def wait(manager, capture_id):
    for _ in range(200):
        job=manager.get(capture_id)
        if job["state"] in {"completed","failed","cancelled","timed_out"}: return job
        time.sleep(.01)
    raise AssertionError("job did not finish")


def test_no_sdr_detected_is_safe(tmp_path):
    caps=manager(tmp_path,devices=False).capabilities(); assert caps["available"] is False; assert caps["capture_and_decode_enabled"] is False


def test_stale_device_id_resolves_to_only_available_receiver(tmp_path):
    request=manager(tmp_path)._validate(payload(device_id="sdr-from-previous-probe"))
    assert request["device_id"] == "sdr-test"


def test_recent_verified_probe_is_reused_without_second_usb_enumeration(tmp_path):
    class CachedDevices(FakeDevices):
        def cached_device(self, device_id):
            assert device_id == "sdr-test"
            return {"device_id":"sdr-test","driver":"fake-test-only","frequency_ranges_hz":[{"minimum":2_000_000_000,"maximum":3_000_000_000}],"sample_rate_ranges_sps":[{"minimum":4_000_000,"maximum":20_000_000}],"bandwidth_ranges_hz":[{"minimum":1_000_000,"maximum":10_000_000}]}
        def list_devices(self):
            raise AssertionError("a recent verified B200 must not be probed twice")
    service=BleCaptureJobManager(tmp_path,CachedDevices(),FakeCapture(),True,minimum_free_bytes=0)
    assert service._validate(payload())["device_id"] == "sdr-test"


def test_feature_flag_disabled(tmp_path):
    with pytest.raises(PermissionError): manager(tmp_path,enabled=False).create(payload())


@pytest.mark.parametrize(("change","code"), [
    ({"center_frequency_hz":1},"INVALID_FREQUENCY"),({"sample_rate_sps":2_000_000},"UNSUPPORTED_SAMPLE_RATE"),
    ({"bandwidth_hz":20_000_000},"UNSUPPORTED_BANDWIDTH"),({"gain_db":1000},"INVALID_GAIN"),
    ({"duration_seconds":61},"INVALID_CAPTURE_DURATION"),({"sample_format":"bad"},"UNSUPPORTED_SAMPLE_FORMAT")])
def test_invalid_capture_parameters(tmp_path, change, code):
    with pytest.raises(ValueError,match=code): manager(tmp_path).create(payload(**change))


def test_real_capture_contract_preserves_sigmf_and_reopens(tmp_path):
    service=manager(tmp_path); created=service.create(payload()); finished=wait(service,created["capture_id"])
    assert finished["state"]=="completed"; assert service.verify(created["capture_id"])=={"data_valid":True,"metadata_valid":True}
    assert service.list_captures()[0]["capture_id"]==created["capture_id"]


def test_hash_mismatch_fails_job(tmp_path):
    service=manager(tmp_path,mode="bad_hash"); created=service.create(payload()); finished=wait(service,created["capture_id"])
    assert finished["state"]=="failed"; assert "HASH_MISMATCH" in finished["error"]


def test_timeout_after_complete_iq_is_recovered(tmp_path):
    service=manager(tmp_path,mode="timeout_after_iq"); created=service.create(payload(sample_rate_sps=8_000_000,duration_seconds=0.000002))
    finished=wait(service,created["capture_id"])
    assert finished["state"]=="completed"
    assert finished["capture_complete"] is True
    assert finished["completion_diagnostic"]=="CAPTURE_TIMEOUT_AFTER_IQ_COMPLETE_RECOVERED"
    assert service.verify(created["capture_id"])=={"data_valid":True,"metadata_valid":True}


def test_concurrent_capture_and_cancellation(tmp_path):
    service=manager(tmp_path,mode="wait"); first=service.create(payload())
    with pytest.raises(RuntimeError,match="CAPTURE_ALREADY_RUNNING"): service.create(payload())
    service.cancel(first["capture_id"]); assert wait(service,first["capture_id"])["state"]=="cancelled"


def test_cross_job_path_traversal_rejected(tmp_path):
    with pytest.raises(ValueError,match="INVALID_CAPTURE_ID"): manager(tmp_path).get("../other")


def test_capture_and_decode_is_hardcoded_disabled():
    assert BLE_CAPTURE_AND_DECODE_ENABLED is False


def test_worker_atomic_live_json_retries_windows_reader_lock(tmp_path, monkeypatch):
    target = tmp_path / "live.json"
    real_replace = ble_sdr_capture_worker.os.replace
    attempts = 0

    def transient_lock(source, destination):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError(5, "file held by API reader")
        return real_replace(source, destination)

    monkeypatch.setattr(ble_sdr_capture_worker.os, "replace", transient_lock)
    monkeypatch.setattr(ble_sdr_capture_worker.time, "sleep", lambda _: None)
    ble_sdr_capture_worker.atomic_json(target, {"available": True})
    assert attempts == 3
    assert json.loads(target.read_text(encoding="utf-8")) == {"available": True}
