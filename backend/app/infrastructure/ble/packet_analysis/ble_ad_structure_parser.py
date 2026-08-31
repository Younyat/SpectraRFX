"""Read-only advertising-data (AD) structure view builder.

The Length-Type-Data structures inside a BLE advertising payload are already
parsed and resolved against Bluetooth Assigned Numbers by the existing
decoder (ble-worker-lab's semantic parser, via
decoded/semantic_packets.jsonl -> advertising_data.structures[]). This module
does not re-parse AD structures from raw bytes; it reshapes what the decoder
already produced into the provenance-tagged view the dashboard renders, and
adds the one additional check the decoder does not already make explicit:
whether a resolved company_identifier matches Texas Instruments.
"""
from __future__ import annotations

from typing import Any

from .models import PROVENANCE_B200, PROVENANCE_VENDOR_DOC, TI_COMPANY_ID, TI_COMPANY_NAME, field


def ad_structures_view(semantic_packet: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not semantic_packet:
        return []
    advertising = semantic_packet.get("advertising_data") or {}
    structures = advertising.get("structures") or []
    view = []
    for structure in structures:
        ad_type_name = structure.get("ad_type_name")
        decode_status = structure.get("decode_status")
        row = {
            "structure_index": structure.get("structure_index"),
            "ad_type_hex": f"0x{int(structure.get('ad_type_raw')):02X}" if structure.get("ad_type_raw") is not None else None,
            "ad_type_name": ad_type_name or "UNKNOWN_AD_TYPE",
            "length": structure.get("length_raw"),
            "raw_data_hex": field(structure.get("ad_data_raw_hex"), PROVENANCE_B200),
            "parser_status": "DECODED" if decode_status == "decoded" else "RAW_ONLY" if ad_type_name else "UNKNOWN_AD_TYPE",
            "interpreted_value": None,
            "manufacturer": None,
        }
        decoded_value = structure.get("decoded_value") or {}
        if ad_type_name == "Manufacturer Specific Data" and decoded_value:
            company_id = decoded_value.get("company_identifier")
            company = decoded_value.get("company") or {}
            is_ti = company_id == TI_COMPANY_ID
            row["manufacturer"] = {
                "company_id_raw": field(f"0x{company_id:04X}" if company_id is not None else None, PROVENANCE_B200),
                "company_id": field(company_id, PROVENANCE_B200),
                "company_name": field(company.get("name"), PROVENANCE_VENDOR_DOC if company.get("name") else PROVENANCE_B200),
                "manufacturer_payload_hex": field(decoded_value.get("vendor_payload_hex"), PROVENANCE_B200),
                "manufacturer_parser_status": "RAW_ONLY" if decoded_value.get("vendor_decode_status") == "raw_only" else (decoded_value.get("vendor_decode_status") or "RAW_ONLY"),
                # This is an identifier-compatibility check only. It is NEVER
                # upgraded to a specific device/model claim -- that requires
                # additional corroborating evidence handled by the
                # transmitter catalog, not this parser.
                "compatibility_note": "MANUFACTURER_ID_COMPATIBLE_WITH_TEXAS_INSTRUMENTS" if is_ti else None,
            }
            if is_ti:
                row["manufacturer"]["company_name"] = field(TI_COMPANY_NAME, PROVENANCE_VENDOR_DOC)
        elif decoded_value:
            row["interpreted_value"] = field(decoded_value, PROVENANCE_B200)
        view.append(row)
    return view


def local_name_from_structures(structures_view: list[dict[str, Any]]) -> str | None:
    # decoded_value shape confirmed against a real capture: {"text": "..."}.
    for row in structures_view:
        if row["ad_type_name"] in {"Complete Local Name", "Shortened Local Name"}:
            value = row.get("interpreted_value")
            if isinstance(value, dict) and isinstance(value.get("value"), dict):
                text = value["value"].get("text")
                if text:
                    return text
    return None


def manufacturer_summary(structures_view: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in structures_view:
        if row.get("manufacturer"):
            return row["manufacturer"]
    return None


def service_uuids_from_structures(structures_view: list[dict[str, Any]]) -> list[str]:
    # decoded_value shape confirmed against a real capture: a LIST of
    # {"uuid": "AA80", "assigned": {"name":..., "value":..., "resolution_status":...}}
    # for 16/32/128-bit service UUID AD types, not a flat list of strings.
    uuid_types = {
        "Incomplete List of 16-bit Service or Service Class UUIDs", "Complete List of 16-bit Service or Service Class UUIDs",
        "Incomplete 16-bit Service UUIDs", "Complete 16-bit Service UUIDs",
        "Incomplete 32-bit Service UUIDs", "Complete 32-bit Service UUIDs",
        "Incomplete 128-bit Service UUIDs", "Complete 128-bit Service UUIDs",
        "Incomplete List of 128-bit Service or Service Class UUIDs", "Complete List of 128-bit Service or Service Class UUIDs",
    }
    uuids: list[str] = []
    for row in structures_view:
        if row["ad_type_name"] in uuid_types:
            value = row.get("interpreted_value")
            payload = value.get("value") if isinstance(value, dict) else None
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict) and item.get("uuid"):
                        uuids.append(str(item["uuid"]))
                    else:
                        uuids.append(str(item))
    return uuids
