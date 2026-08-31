from app.infrastructure.ble.parsers import BleParserRegistry


def uuid(short: str) -> str:
    return f"f000aa{short}-0451-4000-b000-000000000000"


def test_complete_legacy_topology_is_cc2541_and_has_no_light() -> None:
    parser=BleParserRegistry()
    services={uuid(value) for value in ("00","10","20","30","40","50","60")}
    characteristics={uuid(value) for value in ("01","02","03","21","22","23")}
    profile=parser.detect_connected_vendor_profile(services,characteristics)
    assert profile is not None
    assert profile["profile_id"] == "ti-sensortag-cc2541-legacy-v1"
    assert profile["probable_platform"] == "CC2541"
    assert profile["sensor_inventory"]["accelerometer"]["present"] is True
    assert profile["sensor_inventory"]["ambient_light"]["status"] == "not_present_in_detected_hardware_profile"


def test_cc2650_topology_uses_movement_and_optical_discriminants() -> None:
    parser=BleParserRegistry()
    services={uuid(value) for value in ("00","20","40","70","80")}
    characteristics={uuid(value) for value in ("01","02","03","21","22","23")}
    profile=parser.detect_connected_vendor_profile(services,characteristics)
    assert profile is not None
    assert profile["profile_id"] == "ti-sensortag-cc2650-v1"
    assert profile["sensor_inventory"]["ambient_light"]["present"] is True


def test_tmp006_object_value_is_never_promoted_as_temperature() -> None:
    measurements=BleParserRegistry().parse_ti_ir_temperature_notification("device",bytes.fromhex("eafd3c0e"))
    by_type={item["measurement_type"]:item for item in measurements}
    assert by_type["object_temperature"]["value"] is None
    assert by_type["object_temperature"]["validation"]["status"] == "RAW_ONLY"
    assert by_type["ambient_temperature"]["value"] == 28.469
    assert by_type["ambient_temperature"]["validation"]["status"] == "VALID"


def test_legacy_accelerometer_signed_axes() -> None:
    values=BleParserRegistry().parse_ti_legacy_sensor("device","accelerometer",uuid("11"),bytes([64,192,32]))
    assert [item["value"] for item in values] == [1.0,-1.0,0.5]
    assert all(item["validation"]["status"] == "VALID" for item in values)


def test_legacy_barometer_is_calibration_gated() -> None:
    value=BleParserRegistry().parse_ti_legacy_sensor("device","barometer",uuid("41"),b"\x00\x01\x02\x03")[0]
    assert value["value"] is None
    assert value["validation"]["status"] == "CALIBRATION_REQUIRED"


def test_cc2650_optical_and_movement_payloads() -> None:
    parser=BleParserRegistry()
    light=parser.parse_ti_legacy_sensor("device","ambient_light",uuid("71"),(100).to_bytes(2,"little"))[0]
    assert light["value"] == 1.0
    movement=parser.parse_ti_legacy_sensor("device","movement",uuid("81"),b"\x00\x00"*9)
    assert len(movement) == 9
    assert {item["measurement_type"] for item in movement} >= {"angular_velocity_x","acceleration_x","magnetic_field_x"}


def test_cc2650_barometer_is_directly_scaled() -> None:
    raw=(2500).to_bytes(3,"little")+(101325).to_bytes(3,"little")
    values=BleParserRegistry().parse_ti_legacy_sensor("device","barometer",uuid("41"),raw)
    assert values[0]["value"] == 25.0
    assert values[1]["value"] == 1013.25
