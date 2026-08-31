"""Separates what a device's documentation says it can sense from what this
capture actually observed (sec. 10, sec. 17). This offline replay never
opens a GATT connection (advertising-only capture), so GATT-sourced values
are always NOT_AVAILABLE here -- that is reported explicitly, not hidden.
"""
from __future__ import annotations

from typing import Any

from .models import (
    NOT_AVAILABLE,
    NOT_TRANSMITTED,
    PROVENANCE_B200,
    PROVENANCE_VENDOR_DOC,
    TI_CC2650_DOCUMENTED_SENSORS,
    TI_COMPANY_ID,
    field,
)


def sensor_view_for_transmitter(transmitter: dict[str, Any], enriched_packets: list[dict[str, Any]]) -> dict[str, Any]:
    is_ti_compatible = TI_COMPANY_ID in transmitter.get("company_ids", [])
    is_named_sensortag = any("sensortag" in name.lower() for name in transmitter.get("local_names", []))
    documented = TI_CC2650_DOCUMENTED_SENSORS if (is_ti_compatible or is_named_sensortag) else {}

    rows = []
    for sensor_key, description in documented.items():
        rows.append({
            "measurement_name": sensor_key,
            "documented_by": field(description, PROVENANCE_VENDOR_DOC),
            "value_in_advertising": field(None, PROVENANCE_B200),
            "value_via_gatt": field(None, "NOT_AVAILABLE"),
            "status": NOT_TRANSMITTED,
            "note": "Known from TI CC2650STK documentation; this offline replay is advertising-only and never opened a GATT connection, so no live reading exists for this capture.",
        })
    if not documented:
        rows.append({
            "measurement_name": None,
            "documented_by": field(None, "NOT_AVAILABLE"),
            "value_in_advertising": field(None, "NOT_AVAILABLE"),
            "value_via_gatt": field(None, "NOT_AVAILABLE"),
            "status": NOT_AVAILABLE,
            "note": "No manufacturer/name evidence ties this transmitter to a documented sensor profile.",
        })
    return {"transmitter_id": transmitter["logical_transmitter_id"], "sensor_profile_source": "TI_CC2650STK_DOCUMENTATION" if documented else None, "observations": rows}
