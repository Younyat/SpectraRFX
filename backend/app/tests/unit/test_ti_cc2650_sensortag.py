import struct

import pytest

from app.infrastructure.ble.native.ble_native_job_manager import BleNativeJobManager
from app.infrastructure.ble.parsers import BleParserRegistry
from app.infrastructure.ble.parsers.vendor_profiles.ti_cc2650_sensortag import (
    TI_HUMIDITY_CONFIG,
    TI_HUMIDITY_DATA,
    TI_HUMIDITY_PERIOD,
    TI_HUMIDITY_SERVICE,
    TI_IR_TEMPERATURE_CONFIG,
    TI_IR_TEMPERATURE_DATA,
    TI_IR_TEMPERATURE_PERIOD,
    TI_IR_TEMPERATURE_SERVICE,
    matches_ti_sensortag_advertising_fingerprint,
    matches_ti_sensortag_environment_profile,
    matches_ti_sensortag_ir_profile,
    parse_ti_cc2650_humidity,
    parse_ti_cc2650_ir_temperature,
)


# ── Parser: humidity/temperature (AA21) ──────────────────────────────────────

def test_humidity_payload_must_be_exactly_4_bytes_too_short():
    with pytest.raises(ValueError):
        parse_ti_cc2650_humidity(b"\x00\x00\x00")


def test_humidity_payload_must_be_exactly_4_bytes_too_long():
    with pytest.raises(ValueError):
        parse_ti_cc2650_humidity(b"\x00\x00\x00\x00\x00")


def test_humidity_endianness_is_little_endian():
    # 0x1234 little-endian bytes are 34 12 -- if this were read big-endian the
    # raw value (and therefore the converted temperature) would be different.
    payload = struct.pack("<HH", 0x1234, 0x0000)
    result = parse_ti_cc2650_humidity(payload)
    assert result.raw_temperature == 0x1234


def test_humidity_status_bits_are_cleared_before_conversion():
    # Same top 14 bits, differing only in the 2 status bits -- must convert identically.
    base_raw = 0b1100110011001100
    payload_a = struct.pack("<HH", 0, base_raw | 0b00)
    payload_b = struct.pack("<HH", 0, base_raw | 0b11)
    assert parse_ti_cc2650_humidity(payload_a).relative_humidity_percent == parse_ti_cc2650_humidity(payload_b).relative_humidity_percent


def test_humidity_temperature_conversion_matches_datasheet_endpoints():
    assert parse_ti_cc2650_humidity(struct.pack("<HH", 0, 0)).temperature_c == pytest.approx(-40.0)
    assert parse_ti_cc2650_humidity(struct.pack("<HH", 65535, 0)).temperature_c == pytest.approx(125.0, abs=0.01)


def test_humidity_conversion_matches_datasheet_endpoints():
    assert parse_ti_cc2650_humidity(struct.pack("<HH", 0, 0)).relative_humidity_percent == pytest.approx(0.0)
    assert parse_ti_cc2650_humidity(struct.pack("<HH", 0, 0xFFFC)).relative_humidity_percent == pytest.approx(100.0, abs=0.01)


def test_humidity_never_reinterprets_high_raw_temperature_as_negative():
    # raw_temperature above 0x8000 is a normal, valid unsigned reading (>25C
    # roughly) -- it must not be treated as a negative two's-complement value.
    result = parse_ti_cc2650_humidity(struct.pack("<HH", 0x9000, 0))
    assert result.temperature_c > 0


# ── Parser: IR temperature (AA01) ────────────────────────────────────────────

def test_ir_temperature_payload_length_enforced():
    with pytest.raises(ValueError):
        parse_ti_cc2650_ir_temperature(b"\x00\x00\x00")
    with pytest.raises(ValueError):
        parse_ti_cc2650_ir_temperature(b"\x00" * 5)


def test_ir_temperature_object_and_ambient_are_distinct_measurements():
    payload = struct.pack("<HH", 0x1000, 0x2000)
    result = parse_ti_cc2650_ir_temperature(payload)
    assert result.object_temperature_c != result.ambient_temperature_c
    assert result.object_temperature_c == pytest.approx((0x1000 >> 2) * 0.03125)
    assert result.ambient_temperature_c == pytest.approx((0x2000 >> 2) * 0.03125)


# ── Advertising 0x000D must never be interpreted as a measurement ───────────

def test_ti_manufacturer_id_advertising_bytes_are_not_a_measurement():
    parsers = BleParserRegistry()
    result = parsers.classify_advertisement({"0x000D": "030000"}, {})
    assert result == {"data_mode": "UNKNOWN_FORMAT", "parser_available": False, "measurements": []}


def test_advertising_fingerprint_is_a_hint_not_a_measurement_source():
    # It should recognize the hint, but that recognition itself must never
    # produce a temperature/humidity/battery value.
    assert matches_ti_sensortag_advertising_fingerprint(None, {"0x000D": "030000"}, []) is True


# ── Two-phase detection: the second SensorTag (empty advertising) case ─────

def test_gatt_fingerprint_matches_when_all_four_humidity_uuids_present():
    matched = matches_ti_sensortag_environment_profile(
        {TI_HUMIDITY_SERVICE}, {TI_HUMIDITY_DATA, TI_HUMIDITY_CONFIG, TI_HUMIDITY_PERIOD},
    )
    assert matched is True


def test_gatt_fingerprint_does_not_match_on_partial_evidence():
    # Service present but the config/period characteristics are missing --
    # a single isolated UUID must not be enough.
    matched = matches_ti_sensortag_environment_profile({TI_HUMIDITY_SERVICE}, {TI_HUMIDITY_DATA})
    assert matched is False


def test_ir_gatt_fingerprint_matches_independently_of_humidity_profile():
    assert matches_ti_sensortag_ir_profile(
        {TI_IR_TEMPERATURE_SERVICE}, {TI_IR_TEMPERATURE_DATA, TI_IR_TEMPERATURE_CONFIG, TI_IR_TEMPERATURE_PERIOD},
    ) is True
    assert matches_ti_sensortag_ir_profile({TI_HUMIDITY_SERVICE}, {TI_HUMIDITY_DATA}) is False


def test_registry_detects_second_sensortag_with_empty_advertising_via_gatt_only():
    parsers = BleParserRegistry()
    profile = parsers.detect_connected_vendor_profile(
        {TI_IR_TEMPERATURE_SERVICE, TI_HUMIDITY_SERVICE, "f000aa40-0451-4000-b000-000000000000",
         "f000aa70-0451-4000-b000-000000000000", "f000aa80-0451-4000-b000-000000000000"},
        {TI_HUMIDITY_DATA, TI_HUMIDITY_CONFIG, TI_HUMIDITY_PERIOD, TI_IR_TEMPERATURE_DATA, TI_IR_TEMPERATURE_CONFIG, TI_IR_TEMPERATURE_PERIOD},
    )
    assert profile is not None
    assert profile["profile_detection_source"] == "gatt_fingerprint"
    assert profile["environmental_available"] is True
    assert profile["ir_temperature_available"] is True


def test_registry_reports_no_profile_when_gatt_evidence_is_insufficient():
    parsers = BleParserRegistry()
    profile = parsers.detect_connected_vendor_profile({TI_HUMIDITY_SERVICE}, {TI_HUMIDITY_DATA})
    assert profile is None


# ── Job manager: GATT sequence, lifecycle, staleness ────────────────────────

class FakeGattClient:
    """Stands in for bleak.BleakClient. auto_emit lets a test simulate the
    device sending its first notification as soon as it is subscribed;
    leaving it None lets a test exercise the no-notification timeout path."""

    def __init__(self, auto_emit: bytes | None = None):
        self.is_connected = True
        self.calls: list[tuple] = []
        self._notify_callback = None
        self.auto_emit = auto_emit

    async def start_notify(self, uuid, callback):
        self.calls.append(("start_notify", uuid))
        self._notify_callback = callback
        if self.auto_emit is not None:
            callback(None, bytearray(self.auto_emit))

    async def write_gatt_char(self, uuid, data, response=True):
        self.calls.append(("write", uuid, bytes(data)))

    async def stop_notify(self, uuid):
        self.calls.append(("stop_notify", uuid))

    async def disconnect(self):
        self.calls.append(("disconnect",))
        self.is_connected = False

    def emit(self, data: bytes):
        assert self._notify_callback is not None, "device is not subscribed"
        self._notify_callback(None, bytearray(data))


def _seed_device(manager: BleNativeJobManager, device_id: str, *, environmental_available=True, ir_available=False):
    manager.registry._devices[device_id] = {
        "device_id": device_id, "address": "AA:BB:CC:DD:EE:01", "address_type": "unknown",
        "local_name": "SensorTag", "rssi_dbm": -50, "tx_power_dbm": None,
        "manufacturer_data": {}, "service_data": {}, "service_uuids": [],
        "raw_advertising_bytes": None, "raw_advertising_pdu_available": False,
        "raw_advertising_unavailable_reason": "test",
        "first_seen_utc": "2026-01-01T00:00:00Z", "last_seen_utc": "2026-01-01T00:00:00Z",
        "observation_count": 1, "data_mode": "GATT_NOTIFY", "parser_available": False,
        "connection": "connected", "measurements": [], "gatt_services": [],
        "environmental_sensor": {
            "available": environmental_available, "active": False,
            "data_uuid": TI_HUMIDITY_DATA, "config_uuid": TI_HUMIDITY_CONFIG, "period_uuid": TI_HUMIDITY_PERIOD,
        },
        "ir_temperature_sensor": {
            "available": ir_available, "active": False,
            "data_uuid": TI_IR_TEMPERATURE_DATA, "config_uuid": TI_IR_TEMPERATURE_CONFIG, "period_uuid": TI_IR_TEMPERATURE_PERIOD,
        },
    }


@pytest.fixture
def manager(tmp_path):
    instance = BleNativeJobManager(tmp_path / "native")
    yield instance


def test_start_environmental_refuses_when_profile_not_available(manager):
    _seed_device(manager, "dev-1", environmental_available=False)
    manager._clients["dev-1"] = FakeGattClient(auto_emit=struct.pack("<HH", 25000, 33000))
    with pytest.raises(PermissionError):
        manager.start_environmental_measurements("dev-1")


def test_start_environmental_subscribes_before_writing_period_and_config(manager):
    _seed_device(manager, "dev-1")
    client = FakeGattClient(auto_emit=struct.pack("<HH", 25261, 33420))
    manager._clients["dev-1"] = client
    result = manager.start_environmental_measurements("dev-1")
    assert client.calls[0] == ("start_notify", TI_HUMIDITY_DATA)
    assert client.calls[1] == ("write", TI_HUMIDITY_PERIOD, b"\x64")
    assert client.calls[2] == ("write", TI_HUMIDITY_CONFIG, b"\x01")
    assert result["environmental_sensor"]["active"] is True
    assert result["environmental_sensor"]["status"] == "active"
    reading = result["environmental_sensor"]["last_reading"]
    assert reading["stale"] is False
    assert reading["temperature_c"] == pytest.approx(23.6, abs=0.1)


def test_start_environmental_is_idempotent_when_already_active(manager):
    _seed_device(manager, "dev-1")
    client = FakeGattClient(auto_emit=struct.pack("<HH", 25261, 33420))
    manager._clients["dev-1"] = client
    manager.start_environmental_measurements("dev-1")
    calls_after_first_start = len(client.calls)
    manager.start_environmental_measurements("dev-1")
    assert len(client.calls) == calls_after_first_start  # no second subscription/write sequence


def test_start_environmental_times_out_gracefully_without_a_notification(manager):
    _seed_device(manager, "dev-1")
    client = FakeGattClient(auto_emit=None)  # device never sends a notification
    manager._clients["dev-1"] = client
    result = manager._submit(manager._start_environmental("dev-1", first_notification_timeout=0.05), 5)
    assert result["environmental_sensor"]["status"] == "starting_no_data_yet"
    assert result["environmental_sensor"]["active"] is True  # subscription is live; just no data yet


def test_stop_environmental_disables_sensor_then_stops_notifications(manager):
    _seed_device(manager, "dev-1")
    client = FakeGattClient(auto_emit=struct.pack("<HH", 25261, 33420))
    manager._clients["dev-1"] = client
    manager.start_environmental_measurements("dev-1")
    result = manager.stop_environmental_measurements("dev-1")
    assert client.calls[-2] == ("write", TI_HUMIDITY_CONFIG, b"\x00")
    assert client.calls[-1] == ("stop_notify", TI_HUMIDITY_DATA)
    assert result["environmental_sensor"]["active"] is False
    assert result["environmental_sensor"]["last_reading"]["stale"] is True


def test_disconnect_marks_last_reading_stale_without_deleting_it(manager):
    _seed_device(manager, "dev-1")
    client = FakeGattClient(auto_emit=struct.pack("<HH", 25261, 33420))
    manager._clients["dev-1"] = client
    manager.start_environmental_measurements("dev-1")
    before = manager.registry.get("dev-1")["environmental_sensor"]["last_reading"]
    manager.disconnect("dev-1")
    after = manager.registry.get("dev-1")["environmental_sensor"]["last_reading"]
    assert after["stale"] is True
    assert after["temperature_c"] == before["temperature_c"]  # preserved, not discarded
    assert manager.registry.get("dev-1")["connection"] == "disconnected"


def test_late_notification_after_start_updates_reading_again(manager):
    _seed_device(manager, "dev-1")
    client = FakeGattClient(auto_emit=struct.pack("<HH", 25261, 33420))
    manager._clients["dev-1"] = client
    manager.start_environmental_measurements("dev-1")
    client.emit(struct.pack("<HH", 26000, 34000))
    reading = manager.registry.get("dev-1")["environmental_sensor"]["last_reading"]
    assert reading["stale"] is False
    assert reading["temperature_c"] != pytest.approx(23.6, abs=0.01)
