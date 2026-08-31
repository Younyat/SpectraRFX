from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class BleDeviceRegistry:
    def __init__(self, path: Path) -> None:
        self.path, self._lock, self._devices = path, threading.RLock(), {}
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            try: self._devices = json.loads(path.read_text(encoding="utf-8")).get("devices", {})
            except Exception: self._devices = {}

    @staticmethod
    def device_id(address: str) -> str:
        return "ble-native-" + hashlib.sha256(address.upper().encode()).hexdigest()[:16]

    def observe(self, device: Any, advertisement: Any, parsed: dict[str, Any], scan_session_id: str | None = None) -> dict[str, Any]:
        now, address = utc_now(), str(device.address)
        device_id = self.device_id(address)
        manufacturer = {f"0x{int(company):04X}": bytes(payload).hex() for company, payload in (advertisement.manufacturer_data or {}).items()}
        services = {str(key).lower(): bytes(value).hex() for key, value in (advertisement.service_data or {}).items()}
        with self._lock:
            previous = self._devices.get(device_id, {})
            value = {
                **previous, "device_id": device_id, "address": address, "address_type": "unknown",
                "local_name": advertisement.local_name or getattr(device, "name", None),
                "rssi_dbm": getattr(advertisement, "rssi", None), "tx_power_dbm": advertisement.tx_power,
                "manufacturer_data": manufacturer, "service_data": services,
                "service_uuids": [str(item).lower() for item in (advertisement.service_uuids or [])],
                # Bleak exposes normalized fields, not the complete HCI PDU.
                "raw_advertising_bytes": None,
                "raw_advertising_pdu_available": False,
                "raw_advertising_unavailable_reason": "bleak_backend_exposes_normalized_fields_only",
                "first_seen_utc": previous.get("first_seen_utc", now), "last_seen_utc": now,
                "observation_count": int(previous.get("observation_count", 0)) + 1,
                "data_mode": parsed["data_mode"], "parser_available": parsed["parser_available"],
                "connection": previous.get("connection", "disconnected"),
                "advertising_seen": True,
                "advertised_connectable": getattr(advertisement, "connectable", None),
                "windows_device_resolved": previous.get("windows_device_resolved", True),
                "connection_attempted": previous.get("connection_attempted", False),
                "connection_established": previous.get("connection_established", False),
                "gatt_discovery_attempted": previous.get("gatt_discovery_attempted", False),
                "gatt_discovery_succeeded": previous.get("gatt_discovery_succeeded", False),
                "profile_recognized": previous.get("profile_recognized", False),
                "sensor_parser_supported": previous.get("sensor_parser_supported", parsed["parser_available"]),
                "measurement_available": bool(previous.get("measurements")),
                "notification_supported": previous.get("notification_supported", False),
                "native_state": previous.get("native_state", "DISCOVERED"),
                "native_status": previous.get("native_status", "ADVERTISEMENT_ONLY"),
                "gatt_diagnostics": previous.get("gatt_diagnostics", []),
                "scan_session_id": scan_session_id or previous.get("scan_session_id"),
                "measurements": previous.get("measurements", []), "gatt_services": previous.get("gatt_services", []),
            }
            self._devices[device_id] = value
            self._save()
            return dict(value)

    def update(self, device_id: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            if device_id not in self._devices: raise KeyError(device_id)
            self._devices[device_id].update(fields); self._save(); return dict(self._devices[device_id])

    def merge_observed(self, observed: dict[str, Any]) -> dict[str, Any]:
        device_id = str(observed.get("device_id") or self.device_id(str(observed["address"])))
        with self._lock:
            previous = self._devices.get(device_id, {})
            count = int(previous.get("observation_count", 0)) + int(observed.get("observation_count", 1))
            preserved = {
                key: previous.get(key)
                for key in (
                    "connection", "connection_attempted", "connection_established",
                    "gatt_discovery_attempted", "gatt_discovery_succeeded", "profile_recognized",
                    "sensor_parser_supported", "measurement_available", "notification_supported",
                    "native_state", "native_status", "gatt_diagnostics", "measurements",
                    "gatt_services", "environmental_sensor", "ir_temperature_sensor",
                    "sensor_inventory", "profile_id", "profile_label", "profile_detection_source",
                    "profile_confidence", "probable_platform",
                )
                if key in previous
            }
            value = {
                **previous,
                **observed,
                **preserved,
                "device_id": device_id,
                "first_seen_utc": previous.get("first_seen_utc", observed.get("first_seen_utc")),
                "observation_count": count,
            }
            self._devices[device_id] = value
            self._save()
            return dict(value)

    def add_measurement(self, device_id: str, measurement: dict[str, Any]) -> None:
        with self._lock:
            values = self._devices[device_id].setdefault("measurements", [])
            values.append(measurement); del values[:-100]
            self._devices[device_id]["parser_available"] = True
            self._devices[device_id]["sensor_parser_supported"] = True
            valid=measurement.get("value") is not None and measurement.get("validation",{}).get("status","VALID")=="VALID"
            if valid:
                self._devices[device_id]["measurement_available"] = True
                self._devices[device_id]["native_state"] = "MEASUREMENT_AVAILABLE"
                warnings=any(item.get("value") is None for item in values)
                self._devices[device_id]["native_status"] = "MEASUREMENT_AVAILABLE_WITH_WARNINGS" if warnings else "MEASUREMENT_AVAILABLE"
            self._save()

    def add_diagnostic(self, device_id: str, diagnostic: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            values = self._devices[device_id].setdefault("gatt_diagnostics", [])
            values.append(diagnostic); del values[:-100]
            self._save()
            return dict(diagnostic)

    def get(self, device_id: str) -> dict[str, Any]:
        with self._lock:
            if device_id not in self._devices: raise KeyError(device_id)
            return dict(self._devices[device_id])

    def list(self) -> list[dict[str, Any]]:
        with self._lock: return sorted((dict(item) for item in self._devices.values()), key=lambda item: item.get("last_seen_utc", ""), reverse=True)

    def _save(self) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"schema_version": "1.0", "devices": self._devices}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.path)
