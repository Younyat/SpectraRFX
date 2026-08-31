from types import SimpleNamespace

from app.infrastructure.ble.native.ble_device_registry import BleDeviceRegistry
from app.infrastructure.ble.parsers import BleParserRegistry


def test_standard_gatt_measurements_preserve_raw_and_conversion():
    parsers = BleParserRegistry()
    temperature = parsers.parse_gatt("device-1", "00002a6e-0000-1000-8000-00805f9b34fb", bytes.fromhex("3c09"), "gatt_read")
    humidity = parsers.parse_gatt("device-1", "00002a6f-0000-1000-8000-00805f9b34fb", bytes.fromhex("0014"), "gatt_notify")
    battery = parsers.parse_gatt("device-1", "00002a19-0000-1000-8000-00805f9b34fb", bytes([87]), "gatt_read")
    assert temperature["value"] == 23.64 and temperature["source_raw_hex"] == "3c09"
    assert humidity["value"] == 51.2 and humidity["acquisition_mode"] == "gatt_notify"
    assert battery["value"] == 87 and battery["unit"] == "%"


def test_unknown_gatt_and_vendor_payloads_are_never_guessed():
    parsers = BleParserRegistry()
    assert parsers.parse_gatt("device-1", "ffffffff-ffff-ffff-ffff-ffffffffffff", b"\x01\x02", "gatt_read") is None
    result = parsers.classify_advertisement({"0x1234": "0102"}, {})
    assert result == {"data_mode": "UNKNOWN_FORMAT", "parser_available": False, "measurements": []}


def test_registry_preserves_real_advertisement_bytes(tmp_path):
    registry = BleDeviceRegistry(tmp_path / "registry.json")
    device = SimpleNamespace(address="AA:BB:CC:DD:EE:FF", name="Sensor")
    advertisement = SimpleNamespace(local_name="Sensor", rssi=-62, tx_power=None,
                                    manufacturer_data={0x1234: b"\x01\x02"},
                                    service_data={"180f": b"\x57"}, service_uuids=["180f"])
    value = registry.observe(device, advertisement, {"data_mode": "UNKNOWN_FORMAT", "parser_available": False})
    assert value["manufacturer_data"] == {"0x1234": "0102"}
    assert value["service_data"] == {"180f": "57"}
    assert value["observation_count"] == 1 and value["address_type"] == "unknown"
