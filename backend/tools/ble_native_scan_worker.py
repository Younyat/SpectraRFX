"""Isolated WinRT/Bleak scanner for BLE native scans.

The Windows BLE stack can terminate the hosting Python process on some driver
failures. Running scanning out-of-process keeps the API server alive.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import traceback
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def device_id(address: str) -> str:
    return "ble-native-" + hashlib.sha256(address.upper().encode()).hexdigest()[:16]


def classify_advertisement(manufacturer_data: dict[str, str], service_data: dict[str, str]) -> dict[str, Any]:
    return {
        "data_mode": "UNKNOWN_FORMAT" if manufacturer_data or service_data else "GATT_READ",
        "parser_available": False,
        "measurements": [],
    }


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
    last_error: PermissionError | None = None
    for _ in range(30):
        try:
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, path)
            return
        except PermissionError as error:
            last_error = error
            time.sleep(0.05)
    path.write_text(payload, encoding="utf-8")
    if last_error is not None and temporary.exists():
        try:
            temporary.unlink()
        except PermissionError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan-dir", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--stop-file", required=True)
    args = parser.parse_args()

    scan_dir = Path(args.scan_dir)
    scan_dir.mkdir(parents=True, exist_ok=True)
    stop_file = Path(args.stop_file)
    return asyncio.run(scan(scan_dir, args.session_id, stop_file))


async def scan(scan_dir: Path, session_id: str, stop_file: Path) -> int:
    advertisements = scan_dir / "advertisements.jsonl"
    devices_path = scan_dir / "devices.json"
    status_path = scan_dir / "worker_status.json"
    devices: dict[str, dict[str, Any]] = {}

    def status(state: str, **extra: Any) -> None:
        atomic_json(status_path, {"state": state, "scan_session_id": session_id, "updated_at_utc": utc_now(), **extra})

    def callback(device: Any, advertisement: Any) -> None:
        now = utc_now()
        address = str(device.address)
        did = device_id(address)
        manufacturer = {f"0x{int(key):04X}": bytes(value).hex() for key, value in (advertisement.manufacturer_data or {}).items()}
        services = {str(key).lower(): bytes(value).hex() for key, value in (advertisement.service_data or {}).items()}
        parsed = classify_advertisement(manufacturer, services)
        previous = devices.get(did, {})
        record = {
            **previous,
            "device_id": did,
            "address": address,
            "address_type": "unknown",
            "local_name": advertisement.local_name or getattr(device, "name", None),
            "rssi_dbm": getattr(advertisement, "rssi", None),
            "tx_power_dbm": advertisement.tx_power,
            "manufacturer_data": manufacturer,
            "service_data": services,
            "service_uuids": [str(item).lower() for item in (advertisement.service_uuids or [])],
            "raw_advertising_bytes": None,
            "raw_advertising_pdu_available": False,
            "raw_advertising_unavailable_reason": "bleak_backend_exposes_normalized_fields_only",
            "first_seen_utc": previous.get("first_seen_utc", now),
            "last_seen_utc": now,
            "observation_count": int(previous.get("observation_count", 0)) + 1,
            "data_mode": parsed["data_mode"],
            "parser_available": parsed["parser_available"],
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
            "scan_session_id": session_id,
            "measurements": previous.get("measurements", []),
            "gatt_services": previous.get("gatt_services", []),
        }
        devices[did] = record
        observation = {
            "schema_version": "ble-native-observation-v1",
            "native_observation_id": "native-" + uuid.uuid4().hex,
            "scan_session_id": session_id,
            "timestamp_callback_utc": now,
            "timestamp_callback_monotonic_ns": time.monotonic_ns(),
            "address": address,
            "address_type": "unknown",
            "local_name": record["local_name"],
            "rssi_dbm": record["rssi_dbm"],
            "tx_power_dbm": record["tx_power_dbm"],
            "connectable": record["advertised_connectable"],
            "manufacturer_data": manufacturer,
            "service_data": services,
            "service_uuids": record["service_uuids"],
        }
        with advertisements.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(observation, sort_keys=True) + "\n")

    scanner = None
    try:
        status("starting", phase="importing_bleak")
        from bleak import BleakScanner
        try:
            from bleak.backends.winrt.util import assert_mta
            status("starting", phase="asserting_winrt_mta")
            await asyncio.wait_for(assert_mta(), timeout=10)
        except ImportError:
            status("starting", phase="winrt_mta_assert_unavailable")
        status("starting", phase="starting_scanner")
        scanner = BleakScanner(detection_callback=callback)
        await scanner.start()
        status("running", phase="scanner_started", started_at_utc=utc_now())
        while not stop_file.exists():
            await asyncio.sleep(0.1)
    except Exception as error:
        status("failed", error=f"{type(error).__name__}:{error}", traceback=traceback.format_exc())
        return 2
    finally:
        if scanner is not None:
            try:
                await scanner.stop()
            except Exception:
                pass
        atomic_json(devices_path, {"schema_version": "ble-native-devices-v1", "devices": list(devices.values())})
    status("completed", finished_at_utc=utc_now(), device_count=len(devices))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
