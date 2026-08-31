"""Groups analyzed packets into logical transmitters.

A "transmitter" here means an observed BLE advertiser, not a claimed
device model. Classification never asserts identity beyond what the
evidence supports (sec. 11-12).
"""
from __future__ import annotations

from typing import Any

from .ble_ad_structure_parser import local_name_from_structures, manufacturer_summary, service_uuids_from_structures
from .models import (
    KNOWN_CONTROLLED_DEVICE,
    KNOWN_CONTROLLED_SENSOR,
    LEVEL_2_ADDRESS_OBSERVED,
    LEVEL_3_VENDOR_COMPATIBLE,
    LEVEL_4_LOGICAL_DEVICE_COMPATIBLE,
    LEVEL_5_WINDOWS_CORROBORATED,
    TI_COMPANY_ID,
    UNKNOWN_BLE_TRANSMITTER,
    VENDOR_COMPATIBLE_DEVICE,
    WINDOWS_CORROBORATED_DEVICE,
    WINDOWS_MATCHED,
)


def build_transmitter_catalog(enriched_packets: list[dict[str, Any]], target_address: str) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for packet in enriched_packets:
        address = (packet.get("advertiser_address_canonical") or {}).get("value") or "UNKNOWN"
        group = groups.setdefault(address, {
            "logical_transmitter_id": f"TX-{address.replace(':', '')}",
            "addresses_observed": set(),
            "address_types": set(),
            "local_names": set(),
            "company_ids": set(),
            "service_uuids": set(),
            "packet_count": 0,
            "unique_packet_count": 0,
            "b200_observations": 0,
            "windows_observations": 0,
            "corroborated_observations": 0,
            "first_seen": None,
            "last_seen": None,
            "_unique_pdu_hex": set(),
            "is_target": address == target_address,
        })
        group["addresses_observed"].add(address)
        address_type = (packet.get("address_type") or {}).get("value")
        if address_type:
            group["address_types"].add(address_type)
        structures = packet.get("ad_structures") or []
        name = local_name_from_structures(structures)
        if name:
            group["local_names"].add(name)
        manufacturer = manufacturer_summary(structures)
        if manufacturer and manufacturer.get("company_id", {}).get("value") is not None:
            group["company_ids"].add(manufacturer["company_id"]["value"])
        for uuid in service_uuids_from_structures(structures):
            group["service_uuids"].add(uuid)
        group["packet_count"] += 1
        pdu_hex = (packet.get("pdu_payload_hex") or {}).get("value")
        if pdu_hex:
            group["_unique_pdu_hex"].add(pdu_hex)
        group["b200_observations"] += 1
        if packet.get("windows_match", {}).get("value") == WINDOWS_MATCHED:
            group["windows_observations"] += 1
            group["corroborated_observations"] += 1
        rf_time = packet.get("rf_timestamp_utc")
        if rf_time:
            group["first_seen"] = min(group["first_seen"] or rf_time, rf_time)
            group["last_seen"] = max(group["last_seen"] or rf_time, rf_time)

    catalog = []
    for address, group in groups.items():
        group["unique_packet_count"] = len(group["_unique_pdu_hex"]) or group["packet_count"]
        del group["_unique_pdu_hex"]
        group["addresses_observed"] = sorted(group["addresses_observed"])
        group["address_types"] = sorted(group["address_types"])
        group["local_names"] = sorted(group["local_names"])
        group["company_ids"] = sorted(group["company_ids"])
        group["service_uuids"] = sorted(group["service_uuids"])
        group["classification"], group["knowledge_level"] = _classify(group)
        catalog.append(group)
    catalog.sort(key=lambda item: (not item["is_target"], -item["packet_count"]))
    return catalog


def _classify(group: dict[str, Any]) -> tuple[str, str]:
    is_ti = TI_COMPANY_ID in group["company_ids"]
    corroborated = group["corroborated_observations"] > 0
    if group["is_target"] and corroborated:
        return KNOWN_CONTROLLED_SENSOR, LEVEL_5_WINDOWS_CORROBORATED
    if group["is_target"]:
        return KNOWN_CONTROLLED_DEVICE, LEVEL_4_LOGICAL_DEVICE_COMPATIBLE
    if corroborated:
        return WINDOWS_CORROBORATED_DEVICE, LEVEL_5_WINDOWS_CORROBORATED
    if is_ti or group["local_names"]:
        return VENDOR_COMPATIBLE_DEVICE, LEVEL_3_VENDOR_COMPATIBLE
    if group["addresses_observed"]:
        return UNKNOWN_BLE_TRANSMITTER, LEVEL_2_ADDRESS_OBSERVED
    return UNKNOWN_BLE_TRANSMITTER, LEVEL_2_ADDRESS_OBSERVED
