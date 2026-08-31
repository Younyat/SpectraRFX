"""Shared constants and small builders for the BLE Packet Analysis Lab.

This module owns no state and performs no I/O. It exists so every other file
in this package uses the exact same vocabulary -- provenance labels,
knowledge levels, transmitter classifications -- instead of each inventing
its own strings.
"""
from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "ble-packet-analysis-v1"

# ---------------------------------------------------------------------------
# Provenance: every field the dashboard shows must say where it came from.
# ---------------------------------------------------------------------------
PROVENANCE_B200 = "B200"
PROVENANCE_WINDOWS = "WINDOWS"
PROVENANCE_BOTH = "B200_AND_WINDOWS"
PROVENANCE_DERIVED = "DERIVED"
PROVENANCE_OPERATOR = "DECLARED_BY_OPERATOR"
PROVENANCE_VENDOR_DOC = "MANUFACTURER_DOCUMENTATION"
PROVENANCE_UNAVAILABLE = "NOT_AVAILABLE"

PROVENANCE_VALUES = {
    PROVENANCE_B200, PROVENANCE_WINDOWS, PROVENANCE_BOTH, PROVENANCE_DERIVED,
    PROVENANCE_OPERATOR, PROVENANCE_VENDOR_DOC, PROVENANCE_UNAVAILABLE,
}


def field(value: Any, source: str) -> dict[str, Any]:
    """Standard provenance-tagged field shape rendered by every table/detail
    view: {"value": ..., "source": "B200" | "WINDOWS" | ...}."""
    if source not in PROVENANCE_VALUES:
        raise ValueError(f"INVALID_PROVENANCE_SOURCE:{source}")
    return {"value": value, "source": source}


# ---------------------------------------------------------------------------
# Knowledge levels (sec. 22 / sec. 25): progressive, not a single verdict.
# PHYSICAL_UNIT_NOT_PROVEN is a standing caveat, not a terminal failure state
# -- it is attached alongside whatever level was actually reached.
# ---------------------------------------------------------------------------
LEVEL_1_BLE_PACKET_VALID = "LEVEL_1_BLE_PACKET_VALID"
LEVEL_2_ADDRESS_OBSERVED = "LEVEL_2_ADDRESS_OBSERVED"
LEVEL_3_VENDOR_COMPATIBLE = "LEVEL_3_VENDOR_COMPATIBLE"
LEVEL_4_LOGICAL_DEVICE_COMPATIBLE = "LEVEL_4_LOGICAL_DEVICE_COMPATIBLE"
LEVEL_5_WINDOWS_CORROBORATED = "LEVEL_5_WINDOWS_CORROBORATED"
PHYSICAL_UNIT_NOT_PROVEN = "PHYSICAL_UNIT_NOT_PROVEN"

KNOWLEDGE_LEVEL_ORDER = [
    LEVEL_1_BLE_PACKET_VALID,
    LEVEL_2_ADDRESS_OBSERVED,
    LEVEL_3_VENDOR_COMPATIBLE,
    LEVEL_4_LOGICAL_DEVICE_COMPATIBLE,
    LEVEL_5_WINDOWS_CORROBORATED,
]

# ---------------------------------------------------------------------------
# Transmitter classification (sec. 11): never invent "sensor" without cause.
# ---------------------------------------------------------------------------
KNOWN_CONTROLLED_SENSOR = "KNOWN_CONTROLLED_SENSOR"
KNOWN_CONTROLLED_DEVICE = "KNOWN_CONTROLLED_DEVICE"
WINDOWS_CORROBORATED_DEVICE = "WINDOWS_CORROBORATED_DEVICE"
VENDOR_COMPATIBLE_DEVICE = "VENDOR_COMPATIBLE_DEVICE"
UNKNOWN_BLE_TRANSMITTER = "UNKNOWN_BLE_TRANSMITTER"

# ---------------------------------------------------------------------------
# Packet-level scientific states (sec. 28). Never "FAILED" for a merely
# unknown/unsupported field -- that is a different, honest state.
# ---------------------------------------------------------------------------
BLE_PACKET_VALID = "BLE_PACKET_VALID"
BLE_PACKET_CONTENT_PARSED = "BLE_PACKET_CONTENT_PARSED"
BLE_PACKET_PARTIALLY_PARSED = "BLE_PACKET_PARTIALLY_PARSED"
BLE_PACKET_UNSUPPORTED_PDU = "BLE_PACKET_UNSUPPORTED_PDU"
BLE_PACKET_MALFORMED_PAYLOAD = "BLE_PACKET_MALFORMED_PAYLOAD"
MANUFACTURER_IDENTIFIED = "MANUFACTURER_IDENTIFIED"
MANUFACTURER_PAYLOAD_RAW_ONLY = "MANUFACTURER_PAYLOAD_RAW_ONLY"
WINDOWS_MATCHED = "WINDOWS_MATCHED"
WINDOWS_NOT_MATCHED = "WINDOWS_NOT_MATCHED"
WINDOWS_EVIDENCE_UNAVAILABLE = "WINDOWS_EVIDENCE_UNAVAILABLE"

# ---------------------------------------------------------------------------
# Sensor-value provenance states (sec. 10 / sec. 17): a device can HAVE a
# sensor by documentation without that sensor's value ever appearing in this
# specific packet, capture, or advertising channel at all.
# ---------------------------------------------------------------------------
NOT_TRANSMITTED = "NOT_TRANSMITTED"     # known sensor, not sent in advertising (may need GATT)
NOT_PARSED = "NOT_PARSED"               # bytes present, no parser/documentation to interpret them
NOT_AVAILABLE = "NOT_AVAILABLE"         # no evidence at all (neither B200 nor Windows nor GATT)

# ---------------------------------------------------------------------------
# Capture classification (sec. 5): never say "last capture" unqualified.
# ---------------------------------------------------------------------------
LAST_CREATED_CAPTURE = "LAST_CREATED_CAPTURE"
LAST_COMPLETED_CAPTURE = "LAST_COMPLETED_CAPTURE"
LAST_FULLY_ANALYZED_CAPTURE = "LAST_FULLY_ANALYZED_CAPTURE"
LAST_ACCEPTED_CAPTURE = "LAST_ACCEPTED_CAPTURE"

# ---------------------------------------------------------------------------
# Job phases (sec. 20) -- weights sum to 1.0, used for overall_progress.
# ---------------------------------------------------------------------------
JOB_PHASES: list[tuple[str, float]] = [
    ("LOAD_CAPTURE_METADATA", 0.05),
    ("VERIFY_SOURCE_INTEGRITY", 0.05),
    ("LOAD_REPLAY_LEDGER", 0.10),
    ("LOAD_PACKETS", 0.15),
    ("PARSE_LINK_LAYER", 0.10),
    ("PARSE_AD_STRUCTURES", 0.15),
    ("GROUP_TRANSMITTERS", 0.10),
    ("LOAD_WINDOWS_EVIDENCE", 0.10),
    ("CORRELATE_SOURCES", 0.10),
    ("BUILD_SENSOR_VIEWS", 0.05),
    ("WRITE_ARTIFACTS", 0.05),
]
JOB_PHASE_NAMES = [name for name, _ in JOB_PHASES]

# ---------------------------------------------------------------------------
# TI CC2650 SensorTag documented sensor profile (sec. 10 / sec. 26). This is
# vendor documentation, not a claim about what any specific packet contains.
# Source: TI CC2650STK ("SimpleLink SensorTag") design/support documentation.
# ---------------------------------------------------------------------------
TI_CC2650_DOCUMENTED_SENSORS = {
    "temperature": "IR/ambient temperature (TMP007)",
    "humidity": "Humidity (HDC1000)",
    "barometric_pressure": "Barometric pressure (BMP280)",
    "accelerometer_gyroscope_magnetometer": "9-axis motion (MPU9250)",
    "ambient_light": "Optical/ambient light (OPT3001)",
    "battery": "Battery voltage/level",
}
TI_COMPANY_ID = 0x000D
TI_COMPANY_NAME = "Texas Instruments Inc."
