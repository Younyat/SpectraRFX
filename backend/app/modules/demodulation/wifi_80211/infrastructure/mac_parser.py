from __future__ import annotations

import binascii
from dataclasses import dataclass

from ..domain.frame_types import CONTROL_SUBTYPES, DATA_SUBTYPES, MANAGEMENT_SUBTYPES


def _mac(raw: bytes) -> str:
    return ":".join(f"{value:02x}" for value in raw)


# Beacon/probe_response frame bodies start with 12 fixed bytes (8-byte timestamp
# + 2-byte beacon interval + 2-byte capability info) before tagged parameters;
# probe_request bodies have no fixed fields and start directly with tagged
# parameters. In both cases the SSID element (tag number 0) comes first when
# present. Malformed/truncated payloads are expected on a lossy receiver, so
# this never raises -- it just omits the ssid field.
_SSID_FIXED_FIELDS_LENGTH = {"beacon": 12, "probe_response": 12, "probe_request": 0}


def _extract_ssid(subtype_name: str, payload: bytes) -> str | None:
    offset = _SSID_FIXED_FIELDS_LENGTH.get(subtype_name)
    if offset is None or len(payload) < offset + 2:
        return None
    tag_number, tag_length = payload[offset], payload[offset + 1]
    if tag_number != 0 or len(payload) < offset + 2 + tag_length:
        return None
    return payload[offset + 2:offset + 2 + tag_length].decode("utf-8", errors="replace")


@dataclass(frozen=True)
class RecoveredPsdu:
    data: bytes
    complete: bool
    source: str = "validated_phy_worker"
    # gr-ieee802-11's decode_mac verifies FCS internally (via the standard CRC-32
    # residue check) and only publishes a message after that check passes, but it
    # does not retransmit the trailing FCS bytes in the published PDU -- so a real
    # worker-recovered PSDU has no FCS trailer left to re-slice or recompute here.
    # Default True keeps the original contract for any future/legacy source that
    # does hand back a full frame+FCS blob.
    fcs_included: bool = True


def parse_mpdu(psdu: RecoveredPsdu) -> dict:
    """Parse visible IEEE 802.11 MAC fields; protected payload remains ciphertext."""
    if not isinstance(psdu, RecoveredPsdu) or not psdu.complete or psdu.source != "validated_phy_worker":
        raise ValueError("MAC parser requires a complete PSDU from the validated PHY worker")
    if psdu.fcs_included:
        if len(psdu.data) < 14:
            raise ValueError("MPDU is too short")
        body, received = psdu.data[:-4], psdu.data[-4:]
        computed_int = binascii.crc32(body) & 0xFFFFFFFF
        received_int = int.from_bytes(received, "little")
        fcs_fields = {"fcs_received": f"{received_int:08x}", "fcs_computed": f"{computed_int:08x}", "fcs_valid": received_int == computed_int}
    else:
        if len(psdu.data) < 10:
            raise ValueError("MPDU is too short")
        body = psdu.data
        fcs_fields = {"fcs_valid": True, "fcs_verified_by": "phy_worker_upstream_crc32_residue_check"}
    fc = int.from_bytes(body[:2], "little"); frame_type = (fc >> 2) & 0x3; subtype = (fc >> 4) & 0xF
    flags = {"to_ds": bool(fc & 0x0100), "from_ds": bool(fc & 0x0200), "more_fragments": bool(fc & 0x0400), "retry": bool(fc & 0x0800), "power_management": bool(fc & 0x1000), "more_data": bool(fc & 0x2000), "protected": bool(fc & 0x4000), "order": bool(fc & 0x8000)}
    type_name = {0: "management", 1: "control", 2: "data"}.get(frame_type, "extension")
    subtype_name = ({0: MANAGEMENT_SUBTYPES, 1: CONTROL_SUBTYPES, 2: DATA_SUBTYPES}.get(frame_type, {})).get(subtype, f"subtype_{subtype}")
    result = {"protocol_version": fc & 0x3, "frame_type": type_name, "subtype": subtype_name, **flags, "duration_id": int.from_bytes(body[2:4], "little"), "address_1": _mac(body[4:10]), **fcs_fields}
    if frame_type != 1 and len(body) >= 24:
        result.update({"address_2": _mac(body[10:16]), "address_3": _mac(body[16:22])})
        sequence = int.from_bytes(body[22:24], "little"); result.update({"sequence_number": sequence >> 4, "fragment_number": sequence & 0xF})
        header_length = 24
        if flags["to_ds"] and flags["from_ds"] and len(body) >= 30:
            result["address_4"] = _mac(body[24:30]); header_length = 30
        payload = body[header_length:]
        result["payload_length"] = len(payload)
        if flags["protected"]:
            result.update({"payload_state": "protected_ciphertext", "ciphertext_length": len(payload)})
        else:
            result.update({"payload_state": "clear", "payload_hex": payload.hex()})
            ssid = _extract_ssid(subtype_name, payload)
            if ssid is not None:
                result["ssid"] = ssid
    return result
