"""Texas Instruments CC2650 SensorTag vendor profile.

UUIDs, activation sequences, and conversion formulas are per TI's CC2650
SensorTag user guide (the environmental services are propietary GATT built on
the base F000xxxx-0451-4000-B000-000000000000 UUID; TI's reference firmware
and mobile app source document the byte layout and scale factors used here).

Detection is deliberately two-phase and the phases are NOT equivalent:

  Phase 1 (advertising fingerprint) -- local_name/manufacturer_data/advertised
  service UUIDs. This is a hint only. Some real SensorTag units advertise with
  empty manufacturer_data/service_data/service_uuids, so phase 1 alone must
  never be required and must never by itself enable the environmental sensor.

  Phase 2 (connected GATT fingerprint) -- the actual discovered services and
  characteristics after connecting. This is the only check that gates
  measurement activation: a single isolated UUID is not sufficient evidence,
  so each profile match requires the service UUID *and* all of the
  characteristic UUIDs it depends on to be present together.
"""
from __future__ import annotations

from dataclasses import dataclass

TI_MANUFACTURER_COMPANY_ID = "0x000D"  # Texas Instruments Inc.
TI_BASE_SUFFIX = "-0451-4000-b000-000000000000"

# IR temperature service (object + ambient/die temperature, TMP007-class thermopile).
TI_IR_TEMPERATURE_SERVICE = "f000aa00-0451-4000-b000-000000000000"
TI_IR_TEMPERATURE_DATA = "f000aa01-0451-4000-b000-000000000000"
TI_IR_TEMPERATURE_CONFIG = "f000aa02-0451-4000-b000-000000000000"
TI_IR_TEMPERATURE_PERIOD = "f000aa03-0451-4000-b000-000000000000"

# Humidity + ambient temperature service (HDC1000-class).
TI_HUMIDITY_SERVICE = "f000aa20-0451-4000-b000-000000000000"
TI_HUMIDITY_DATA = "f000aa21-0451-4000-b000-000000000000"
TI_HUMIDITY_CONFIG = "f000aa22-0451-4000-b000-000000000000"
TI_HUMIDITY_PERIOD = "f000aa23-0451-4000-b000-000000000000"

# Identified but not yet parsed -- service *identity* only. Do not add parsing
# for these until humidity+temperature and IR temperature are validated
# end to end (explicit scope decision, not an oversight).
TI_PRESSURE_SERVICE = "f000aa40-0451-4000-b000-000000000000"
TI_OPTICAL_SERVICE = "f000aa70-0451-4000-b000-000000000000"
TI_MOVEMENT_SERVICE = "f000aa80-0451-4000-b000-000000000000"

KNOWN_SERVICE_NAMES = {
    TI_IR_TEMPERATURE_SERVICE: "TI IR Temperature Service",
    TI_HUMIDITY_SERVICE: "TI Humidity Service",
    TI_PRESSURE_SERVICE: "TI Barometric Pressure Service",
    TI_OPTICAL_SERVICE: "TI Optical Sensor Service",
    TI_MOVEMENT_SERVICE: "TI Movement Service",
}

PROFILE_ID = "ti-sensortag-compatible-v1"
HUMIDITY_PARSER_ID = "ti-cc2650-hdc1000-v1"
IR_PARSER_ID = "ti-cc2650-tmp007-v1"


@dataclass(frozen=True)
class TiHumidityMeasurement:
    temperature_c: float
    relative_humidity_percent: float
    raw_temperature: int
    raw_humidity: int
    raw_hex: str


@dataclass(frozen=True)
class TiIrTemperatureMeasurement:
    object_temperature_c: float
    ambient_temperature_c: float
    raw_object: int
    raw_ambient: int
    raw_hex: str


def parse_ti_cc2650_humidity(payload: bytes) -> TiHumidityMeasurement:
    """AA21: 4 bytes, little-endian -- [0:2) raw temperature, [2:4) raw
    humidity. The sensor's raw temperature output is a plain unsigned 16-bit
    linear ADC code spanning its full -40C..+125C range (HDC1000-class
    conversion) -- it is intentionally NOT reinterpreted as two's-complement
    signed; doing so would corrupt every reading above roughly +25C, where
    raw_temperature already exceeds 0x8000 as a normal, valid unsigned value.
    """
    if len(payload) != 4:
        raise ValueError(f"TI humidity payload must contain 4 bytes; received {len(payload)}")
    raw_temperature = int.from_bytes(payload[0:2], byteorder="little", signed=False)
    raw_humidity = int.from_bytes(payload[2:4], byteorder="little", signed=False)
    temperature_c = (raw_temperature / 65536.0) * 165.0 - 40.0
    # The two least-significant bits of the humidity field are status bits,
    # not part of the measurement, and must be cleared before conversion.
    humidity_clean = raw_humidity & 0xFFFC
    humidity_percent = (humidity_clean / 65536.0) * 100.0
    return TiHumidityMeasurement(temperature_c, humidity_percent, raw_temperature, raw_humidity, payload.hex())


def parse_ti_cc2650_ir_temperature(payload: bytes) -> TiIrTemperatureMeasurement:
    """AA01: 4 bytes, little-endian -- [0:2) object (IR/thermopile) temperature,
    [2:4) ambient (die) temperature. Each 16-bit field is a 14-bit value
    left-justified with 2 reserved/status LSBs, scaled 0.03125 degC/LSB after
    shifting them out -- per TI's TMP007-based SensorTag conversion. This is a
    different physical measurement from the humidity service's ambient
    temperature above and must not be merged with it.
    """
    if len(payload) != 4:
        raise ValueError(f"TI IR temperature payload must contain 4 bytes; received {len(payload)}")
    raw_object = int.from_bytes(payload[0:2], byteorder="little", signed=True)
    raw_ambient = int.from_bytes(payload[2:4], byteorder="little", signed=True)
    # On legacy TMP006 SensorTags the first word is thermopile voltage, not a
    # temperature. It is retained only for provenance; the parser registry
    # marks object temperature RAW_ONLY until calibrated nonlinear conversion.
    object_temperature_c = float("nan")
    ambient_temperature_c = raw_ambient / 128.0
    return TiIrTemperatureMeasurement(object_temperature_c, ambient_temperature_c, raw_object, raw_ambient, payload.hex())


def matches_ti_sensortag_advertising_fingerprint(local_name: str | None, manufacturer_data: dict[str, str], service_uuids: list[str]) -> bool:
    """Phase 1 -- a hint only. Never treat this as sufficient to enable
    measurements; some real units advertise with none of these fields
    populated, and the reverse (matching by name/manufacturer alone) is not
    proof of the real GATT profile either."""
    if local_name and "sensortag" in local_name.lower():
        return True
    if TI_MANUFACTURER_COMPANY_ID in manufacturer_data:
        return True
    return any(str(item).lower().endswith(TI_BASE_SUFFIX) for item in service_uuids)


def matches_ti_sensortag_environment_profile(service_uuids: set[str] | list[str], characteristic_uuids: set[str] | list[str]) -> bool:
    """Phase 2 -- the only check that actually enables the humidity/
    temperature sensor: the service UUID and all three of its dependent
    characteristic UUIDs must be present together in the connected device's
    own discovered GATT profile."""
    services = {str(item).lower() for item in service_uuids}
    characteristics = {str(item).lower() for item in characteristic_uuids}
    return (
        TI_HUMIDITY_SERVICE in services
        and TI_HUMIDITY_DATA in characteristics
        and TI_HUMIDITY_CONFIG in characteristics
        and TI_HUMIDITY_PERIOD in characteristics
    )


def matches_ti_sensortag_ir_profile(service_uuids: set[str] | list[str], characteristic_uuids: set[str] | list[str]) -> bool:
    """Phase 2 equivalent for the IR temperature service."""
    services = {str(item).lower() for item in service_uuids}
    characteristics = {str(item).lower() for item in characteristic_uuids}
    return (
        TI_IR_TEMPERATURE_SERVICE in services
        and TI_IR_TEMPERATURE_DATA in characteristics
        and TI_IR_TEMPERATURE_CONFIG in characteristics
        and TI_IR_TEMPERATURE_PERIOD in characteristics
    )
