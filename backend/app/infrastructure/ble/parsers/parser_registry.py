from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from .vendor_profiles import (
    PROFILE_ID as TI_PROFILE_ID,
    TI_HUMIDITY_DATA,
    TI_IR_TEMPERATURE_DATA,
    matches_ti_sensortag_environment_profile,
    matches_ti_sensortag_ir_profile,
    parse_ti_cc2650_humidity,
    parse_ti_cc2650_ir_temperature,
)

TI_HUMIDITY_PARSER_ID = "ti-cc2650-hdc1000-v1"
TI_IR_PARSER_ID = "ti-cc2650-tmp007-v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class BleParserRegistry:
    """Strict registry: unmatched payloads never become measurements."""

    STANDARD_GATT: dict[str, dict[str, Any]] = {
        "00002a19-0000-1000-8000-00805f9b34fb": {
            "parser_id": "bluetooth-sig-battery-level-v1", "measurement_type": "battery",
            "unit": "%", "length": 1, "signed": False, "scale": 1.0,
        },
        "00002a6e-0000-1000-8000-00805f9b34fb": {
            "parser_id": "bluetooth-sig-temperature-v1", "measurement_type": "temperature",
            "unit": "degC", "length": 2, "signed": True, "scale": 0.01,
        },
        "00002a6f-0000-1000-8000-00805f9b34fb": {
            "parser_id": "bluetooth-sig-humidity-v1", "measurement_type": "humidity",
            "unit": "%", "length": 2, "signed": False, "scale": 0.01,
        },
    }

    def __init__(self) -> None:
        self._vendor_parsers: list[Callable[..., dict[str, Any] | None]] = []

    def describe(self, characteristic_uuid: str) -> dict[str, Any] | None:
        profile = self.STANDARD_GATT.get(characteristic_uuid.lower())
        return None if profile is None else {**profile, "parser_version": "1.0", "source_type": "gatt", "characteristic_uuid": characteristic_uuid.lower(), "endianness": "little", "minimum_payload_length": profile["length"], "supported_measurements": [profile["measurement_type"]]}

    def parse_gatt(self, device_id: str, characteristic_uuid: str, raw: bytes, acquisition_mode: str) -> dict[str, Any] | None:
        profile = self.STANDARD_GATT.get(characteristic_uuid.lower())
        if profile is None or len(raw) != profile["length"]:
            return None
        integer = int.from_bytes(raw, "little", signed=profile["signed"])
        return {
            "measurement_id": "ble-measurement-" + uuid.uuid4().hex[:16],
            "device_id": device_id,
            "measurement_type": profile["measurement_type"],
            "value": integer * profile["scale"],
            "unit": profile["unit"],
            "observed_at_utc": utc_now(),
            "acquisition_mode": acquisition_mode,
            "source_uuid": characteristic_uuid.lower(),
            "source_raw_hex": raw.hex(),
            "parser_id": profile["parser_id"],
            "parser_version": "1.0",
            "conversion": {"endianness": "little", "signed": profile["signed"], "scale": profile["scale"], "offset": 0},
            "quality": {"parsed": True, "crc_available": False},
        }

    def classify_advertisement(self, manufacturer_data: dict[str, str], service_data: dict[str, str]) -> dict[str, Any]:
        # Vendor formats require an explicit registered parser. Raw bytes are
        # intentionally returned without guessing offsets or engineering units.
        # In particular: manufacturer_data["0x000D"] (TI's company ID) is never
        # interpreted as a measurement here -- it is only ever a phase-1 hint,
        # handled separately by matches_ti_sensortag_advertising_fingerprint().
        return {"data_mode": "UNKNOWN_FORMAT" if manufacturer_data or service_data else "GATT_READ", "parser_available": False, "measurements": []}

    def detect_connected_vendor_profile(self, service_uuids: set[str] | list[str], characteristic_uuids: set[str] | list[str]) -> dict[str, Any] | None:
        """Phase 2 -- only ever called with the device's own discovered GATT
        services/characteristics after connecting. Returns None (no vendor
        profile) unless at least one sub-profile's full UUID set matches."""
        has_environmental = matches_ti_sensortag_environment_profile(service_uuids, characteristic_uuids)
        has_ir = matches_ti_sensortag_ir_profile(service_uuids, characteristic_uuids)
        if not has_environmental and not has_ir:
            return None
        services={str(value).lower() for value in service_uuids}
        legacy={f"f000aa{x}-0451-4000-b000-000000000000" for x in ("00","10","20","30","40","50")}
        cc2650={f"f000aa{x}-0451-4000-b000-000000000000" for x in ("00","20","40","70","80")}
        is_legacy=legacy.issubset(services) or bool({f"f000aa{x}-0451-4000-b000-000000000000" for x in ("10","30","50")} & services)
        is_cc2650=cc2650.issubset(services) and not is_legacy
        profile_id="ti-sensortag-cc2541-legacy-v1" if is_legacy else "ti-sensortag-cc2650-v1" if is_cc2650 else TI_PROFILE_ID
        profile_label="TI SensorTag — probable CC2541 generation" if is_legacy else "TI SensorTag CC2650" if is_cc2650 else "TI SensorTag profile (generation unresolved)"
        sensor_services={
            "accelerometer":"f000aa10-0451-4000-b000-000000000000", "magnetometer":"f000aa30-0451-4000-b000-000000000000",
            "barometer":"f000aa40-0451-4000-b000-000000000000", "gyroscope":"f000aa50-0451-4000-b000-000000000000",
            "ambient_light":"f000aa70-0451-4000-b000-000000000000", "movement":"f000aa80-0451-4000-b000-000000000000",
            "simple_keys":"0000ffe0-0000-1000-8000-00805f9b34fb", "test_service":"f000aa60-0451-4000-b000-000000000000",
        }
        inventory={name:{"present":uuid in services,"status":"available_inactive" if uuid in services else "not_present_in_detected_hardware_profile"} for name,uuid in sensor_services.items()}
        if inventory["barometer"]["present"]: inventory["barometer"]["status"]="available_inactive" if is_cc2650 else "calibration_required"
        return {
            "profile_id": profile_id,
            "profile_label": profile_label,
            "profile_detection_source": "gatt_fingerprint",
            "profile_confidence": "high" if is_legacy or is_cc2650 else "medium",
            "probable_platform": "CC2541" if is_legacy else "CC2650" if is_cc2650 else None,
            "sensor_inventory": inventory,
            "environmental_available": has_environmental,
            "ir_temperature_available": has_ir,
        }

    def parse_ti_humidity_notification(self, device_id: str, raw: bytes) -> list[dict[str, Any]]:
        try:
            parsed = parse_ti_cc2650_humidity(raw)
        except ValueError:
            return []
        base = {
            "parser_id": TI_HUMIDITY_PARSER_ID, "parser_version": "1.0", "device_id": device_id,
            "source_uuid": TI_HUMIDITY_DATA, "source_raw_hex": raw.hex(), "observed_at_utc": utc_now(),
            "acquisition_mode": "gatt_notify", "quality": {"parsed": True, "crc_available": False},
        }
        return [
            {**base, "measurement_id": "ble-measurement-" + uuid.uuid4().hex[:16], "measurement_type": "temperature",
             "value": round(parsed.temperature_c, 2), "unit": "degC",
             "conversion": {"endianness": "little", "signed": False, "scale": 165.0 / 65536.0, "offset": -40.0}},
            {**base, "measurement_id": "ble-measurement-" + uuid.uuid4().hex[:16], "measurement_type": "relative_humidity",
             "value": round(parsed.relative_humidity_percent, 2), "unit": "%RH",
             "conversion": {"endianness": "little", "signed": False, "scale": 100.0 / 65536.0, "offset": 0.0}},
        ]

    def parse_ti_ir_temperature_notification(self, device_id: str, raw: bytes) -> list[dict[str, Any]]:
        try:
            parsed = parse_ti_cc2650_ir_temperature(raw)
        except ValueError:
            return []
        base = {
            "parser_id": TI_IR_PARSER_ID, "parser_version": "1.0", "device_id": device_id,
            "source_uuid": TI_IR_TEMPERATURE_DATA, "source_raw_hex": raw.hex(), "observed_at_utc": utc_now(),
            "acquisition_mode": "gatt_notify", "quality": {"parsed": True, "crc_available": False},
        }
        return [
            {**base, "measurement_id": "ble-measurement-" + uuid.uuid4().hex[:16], "measurement_type": "object_temperature",
             "value": None, "unit": "degC", "validation":{"status":"RAW_ONLY","finite":False,"range_check":"not_run"},
             "quality":{"parsed":False,"crc_available":False,"status":"INVALID_PARSER_RESULT","reason":"TMP006 object temperature conversion requires thermopile calibration coefficients"},
             "conversion": {"endianness": "little", "signed": True, "scale": None, "offset": None}},
            {**base, "measurement_id": "ble-measurement-" + uuid.uuid4().hex[:16], "measurement_type": "ambient_temperature",
             "value": round(parsed.ambient_temperature_c, 3), "unit": "degC",
             "validation":{"status":"VALID","finite":True,"range_check":"passed"},
             "conversion": {"endianness": "little", "signed": True, "scale": 1/128, "offset": 0.0}},
        ]

    def parse_ti_legacy_sensor(self, device_id: str, sensor: str, source_uuid: str, raw: bytes) -> list[dict[str, Any]]:
        """Strict CC2541 SensorTag parsers. Pressure remains calibration-gated."""
        now=utc_now(); base={"device_id":device_id,"source_uuid":source_uuid,"source_raw_hex":raw.hex(),"observed_at_utc":now,
            "acquisition_mode":"gatt_notify","parser_version":"1.0","quality":{"parsed":True,"crc_available":False},
            "validation":{"status":"VALID","finite":True,"range_check":"passed"}}
        def measurement(kind:str,value:float|int|None,unit:str,parser_id:str,conversion:dict[str,Any],status:str="VALID"):
            return {**base,"measurement_id":"ble-measurement-"+uuid.uuid4().hex[:16],"measurement_type":kind,"value":value,"unit":unit,
                "parser_id":parser_id,"conversion":conversion,"validation":{"status":status,"finite":value is not None,"range_check":"passed" if value is not None else "not_run"},
                "quality":{**base["quality"],"parsed":value is not None}}
        if sensor=="accelerometer" and len(raw)==3:
            axes=[int.from_bytes(raw[i:i+1],"little",signed=True)/64.0 for i in range(3)]
            return [measurement(f"acceleration_{axis}",round(value,5),"g","ti-cc2541-kxtj9-v1",{"endianness":"one-byte","signed":True,"scale":1/64,"offset":0}) for axis,value in zip("xyz",axes)]
        if sensor in {"magnetometer","gyroscope"} and len(raw)==6:
            values=[int.from_bytes(raw[i:i+2],"little",signed=True) for i in range(0,6,2)]
            scale=2000/65536 if sensor=="magnetometer" else 500/65536
            unit="uT" if sensor=="magnetometer" else "deg/s"; parser_id="ti-cc2541-mag3110-v1" if sensor=="magnetometer" else "ti-cc2541-imu3000-v1"
            prefix="magnetic_field" if sensor=="magnetometer" else "angular_velocity"
            return [measurement(f"{prefix}_{axis}",round(value*scale,5),unit,parser_id,{"endianness":"little","signed":True,"scale":scale,"offset":0}) for axis,value in zip("xyz",values)]
        if sensor=="simple_keys" and len(raw)==1:
            return [measurement("simple_keys",raw[0],"bitmask","ti-cc2541-simple-keys-v1",{"left_button_mask":1,"right_button_mask":2})]
        if sensor=="ambient_light" and len(raw)==2:
            value=int.from_bytes(raw,"little"); mantissa=value&0x0fff; exponent=(value>>12)&0x0f; lux=mantissa*(0.01*(2**exponent))
            return [measurement("ambient_light",round(lux,3),"lux","ti-cc2650-opt3001-v1",{"endianness":"little","mantissa_bits":12,"exponent_bits":4})]
        if sensor=="movement" and len(raw)>=18:
            words=[int.from_bytes(raw[i:i+2],"little",signed=True) for i in range(0,18,2)]
            output=[]
            for axis,value in zip("xyz",words[0:3]): output.append(measurement(f"angular_velocity_{axis}",round(value*500/65536,5),"deg/s","ti-cc2650-mpu9250-v1",{"endianness":"little","signed":True,"scale":500/65536}))
            for axis,value in zip("xyz",words[3:6]): output.append(measurement(f"acceleration_{axis}",round(value/4096,5),"g","ti-cc2650-mpu9250-v1",{"endianness":"little","signed":True,"scale":1/4096}))
            for axis,value in zip("xyz",words[6:9]): output.append(measurement(f"magnetic_field_{axis}",value,"raw_count","ti-cc2650-mpu9250-v1",{"endianness":"little","signed":True,"scale":1}))
            return output
        if sensor=="barometer" and len(raw)==6:
            temperature=int.from_bytes(raw[0:3],"little",signed=False)/100.0; pressure=int.from_bytes(raw[3:6],"little",signed=False)/100.0
            return [measurement("barometer_temperature",round(temperature,2),"degC","ti-cc2650-bmp280-v1",{"endianness":"little","signed":False,"scale":0.01}),measurement("barometric_pressure",round(pressure,2),"hPa","ti-cc2650-bmp280-v1",{"endianness":"little","signed":False,"scale":0.01})]
        if sensor=="barometer":
            return [measurement("barometric_pressure",None,"hPa","ti-cc2541-t5400-v1",{"endianness":"little","calibration":"AA43_REQUIRED"},"CALIBRATION_REQUIRED")]
        return [measurement(sensor,None,"raw","ti-cc2541-raw-v1",{},"INVALID_LENGTH")]
