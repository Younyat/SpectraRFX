"""Read-only Windows evidence access.

Reads ONLY the native advertisements.jsonl already preserved by the original
hybrid session -- never starts a new Windows BLE scan, never opens a new GATT
connection. This mirrors ble_offline_replay.py's own _native_rows() but
returns the full window (not filtered to one target address), because the
dashboard's "SOLO WINDOWS" filter must show every preserved callback.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _epoch(value: Any) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def read_native_rows(native_scan_path: Path, window_start_utc: str | None, window_end_utc: str | None) -> list[dict[str, Any]]:
    if not native_scan_path.is_file():
        return []
    rows = [json.loads(line) for line in native_scan_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    start, end = _epoch(window_start_utc), _epoch(window_end_utc)
    if start is None or end is None:
        return rows
    return [row for row in rows if (ts := _epoch(row.get("timestamp_callback_utc"))) is not None and start <= ts <= end]


def windows_row_view(native_row: dict[str, Any]) -> dict[str, Any]:
    """Reshapes one preserved advertisements.jsonl row into the fields
    Microsoft's BluetoothLEAdvertisementReceivedEventArgs documents
    (address, address type, RSSI, timestamp, advertisement payload)."""
    return {
        "native_observation_id": native_row.get("native_observation_id"),
        "bluetooth_address": native_row.get("address"),
        "bluetooth_address_type": native_row.get("address_type"),
        "local_name": native_row.get("local_name"),
        "rssi_dbm": native_row.get("rssi_dbm"),
        "tx_power_dbm": native_row.get("tx_power_dbm"),
        "manufacturer_data": native_row.get("manufacturer_data") or {},
        "service_data": native_row.get("service_data") or {},
        "service_uuids": native_row.get("service_uuids") or [],
        "connectable": native_row.get("connectable"),
        "timestamp_callback_utc": native_row.get("timestamp_callback_utc"),
        "scanning_mode": "PASSIVE",  # native scan worker never issues SCAN_REQ; see BLE Lab native scanner
    }
