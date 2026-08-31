"""hardware/sdr_device_arbiter.py must protect a device across OS PROCESSES,
not just threads inside one process -- that's the whole reason it exists
instead of reusing RealSpectrumStream's in-memory threading.Lock. These tests
persist real lock files under tmp_path and use a genuinely-dead PID (from a
subprocess we spawn and wait on) to exercise orphan cleanup deterministically,
rather than guessing at an unused PID number.
"""
from __future__ import annotations

import subprocess
import sys
import time

import pytest

from app.modules.ble_rffi_studio.hardware.sdr_device_arbiter import (
    ACQUIRED,
    AVAILABLE,
    SdrDeviceArbiter,
)


@pytest.fixture
def arbiter(tmp_path):
    return SdrDeviceArbiter(tmp_path / "locks")


@pytest.fixture
def dead_pid():
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def test_first_acquire_is_granted(arbiter):
    result = arbiter.acquire("usrp-b200-E3R04Z1B2", owner="ble_capture", operation_id="op-1")
    assert result.granted is True
    assert result.status == ACQUIRED


def test_second_acquire_by_different_owner_is_refused(arbiter):
    arbiter.acquire("usrp-b200-E3R04Z1B2", owner="ble_capture", operation_id="op-1")
    result = arbiter.acquire("usrp-b200-E3R04Z1B2", owner="live_spectrum_stream", operation_id="op-2")
    assert result.granted is False
    assert result.current_owner == "ble_capture"
    assert result.current_operation_id == "op-1"


def test_same_owner_and_operation_reacquire_is_idempotent(arbiter):
    first = arbiter.acquire("dev-1", owner="ble_capture", operation_id="op-1", lease_seconds=60)
    second = arbiter.acquire("dev-1", owner="ble_capture", operation_id="op-1", lease_seconds=60)
    assert second.granted is True
    assert second.lease_expires_at >= first.lease_expires_at


def test_release_by_the_holder_frees_the_device(arbiter):
    arbiter.acquire("dev-1", owner="ble_capture", operation_id="op-1")
    released = arbiter.release("dev-1", owner="ble_capture", operation_id="op-1")
    assert released is True
    assert arbiter.get_status("dev-1")["status"] == AVAILABLE


def test_release_by_a_non_holder_is_refused(arbiter):
    arbiter.acquire("dev-1", owner="ble_capture", operation_id="op-1")
    released = arbiter.release("dev-1", owner="live_spectrum_stream", operation_id="op-2")
    assert released is False
    assert arbiter.get_status("dev-1")["status"] == ACQUIRED


def test_get_status_on_unknown_device_is_available(arbiter):
    status = arbiter.get_status("never-acquired-device")
    assert status["status"] == AVAILABLE
    assert status["owner"] is None


def test_expired_lease_is_reclaimable_by_a_new_owner(arbiter):
    arbiter.acquire("dev-1", owner="ble_capture", operation_id="op-1", lease_seconds=0.01)
    time.sleep(0.05)
    result = arbiter.acquire("dev-1", owner="live_spectrum_stream", operation_id="op-2")
    assert result.granted is True
    assert result.current_owner == "live_spectrum_stream"


def test_orphaned_lock_from_a_dead_process_is_reclaimable(arbiter, dead_pid, tmp_path, monkeypatch):
    arbiter.acquire("dev-1", owner="ble_capture", operation_id="op-1", lease_seconds=3600)
    # Rewrite the just-written lock file so its pid points at a process that
    # has genuinely already exited -- simulating a worker crash without
    # waiting on a real lease timeout.
    import json
    lock_path = tmp_path / "locks" / "dev-1.json"
    record = json.loads(lock_path.read_text(encoding="utf-8"))
    record["pid"] = dead_pid
    lock_path.write_text(json.dumps(record), encoding="utf-8")

    status_before = arbiter.get_status("dev-1")
    assert status_before["status"] == AVAILABLE  # self-healed on read

    result = arbiter.acquire("dev-1", owner="live_spectrum_stream", operation_id="op-2")
    assert result.granted is True


def test_orphan_cleanup_does_not_free_a_lock_held_by_a_live_process(arbiter):
    # The current test process is alive by definition -- acquiring under our
    # own real PID must not be treated as orphaned by a competing acquire.
    arbiter.acquire("dev-1", owner="ble_capture", operation_id="op-1", lease_seconds=3600)
    result = arbiter.acquire("dev-1", owner="live_spectrum_stream", operation_id="op-2")
    assert result.granted is False


def test_different_devices_are_independent(arbiter):
    arbiter.acquire("dev-1", owner="ble_capture", operation_id="op-1")
    result = arbiter.acquire("dev-2", owner="live_spectrum_stream", operation_id="op-2")
    assert result.granted is True


@pytest.mark.parametrize("bad_id", ["../escape", "a/b", "a\\b"])
def test_path_traversal_in_device_id_is_rejected(arbiter, bad_id):
    with pytest.raises(ValueError):
        arbiter.acquire(bad_id, owner="ble_capture", operation_id="op-1")
