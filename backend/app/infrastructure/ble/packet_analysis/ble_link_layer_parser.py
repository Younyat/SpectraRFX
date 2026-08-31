"""Read-only link-layer view builder.

Does NOT re-decode IQ or re-run GFSK/CRC. It reads the already-decoded rows
that backend/tools/ble_decode_burst_directory.py wrote during the replay
(decoded/decoded_packets.jsonl) plus the enriched association row from
packet_association_ledger.jsonl, and reshapes them into the
PREAMBLE | ACCESS ADDRESS | HEADER | PAYLOAD | CRC breakdown the dashboard
shows. All of it is B200-sourced (this file never touches Windows evidence).
"""
from __future__ import annotations

from typing import Any

from .models import (
    BLE_PACKET_CONTENT_PARSED,
    BLE_PACKET_MALFORMED_PAYLOAD,
    BLE_PACKET_UNSUPPORTED_PDU,
    BLE_PACKET_VALID,
    PROVENANCE_B200,
    field,
)

# Legacy advertising PDU types the existing decoder
# (ble-worker-lab/src/ble_worker/legacy_pdu_parser.py) can confirm and
# semantically parse today.
SUPPORTED_PDU_TYPES = {"ADV_IND", "ADV_NONCONN_IND", "ADV_SCAN_IND", "ADV_DIRECT_IND", "SCAN_RSP"}
ACCESS_ADDRESS_ADVERTISING = "8E89BED6"


def link_layer_view(decoded_packet: dict[str, Any]) -> dict[str, Any]:
    pdu_type = decoded_packet.get("pdu_type_name")
    crc_valid = bool(decoded_packet.get("crc_valid"))
    if not crc_valid:
        status = BLE_PACKET_MALFORMED_PAYLOAD
    elif pdu_type not in SUPPORTED_PDU_TYPES:
        status = BLE_PACKET_UNSUPPORTED_PDU
    else:
        status = BLE_PACKET_CONTENT_PARSED

    header_hex = decoded_packet.get("pdu_octets", "")
    payload_hex = decoded_packet.get("payload_octets", "") or decoded_packet.get("advertising_data_hex", "")
    return {
        "parser_status": status if status != BLE_PACKET_UNSUPPORTED_PDU else "PDU_VALID_BUT_PARSER_NOT_IMPLEMENTED",
        "base_status": BLE_PACKET_VALID if crc_valid else BLE_PACKET_MALFORMED_PAYLOAD,
        "preamble_bits": field("01010101" if pdu_type else None, PROVENANCE_B200),
        "access_address_hex": field(ACCESS_ADDRESS_ADVERTISING, PROVENANCE_B200),
        "pdu_header_hex": field(header_hex[:4] if header_hex else None, PROVENANCE_B200),
        "pdu_payload_hex": field(payload_hex, PROVENANCE_B200),
        "crc_received_hex": field(decoded_packet.get("crc_received"), PROVENANCE_B200),
        "crc_calculated_hex": field(decoded_packet.get("crc_computed"), PROVENANCE_B200),
        "crc_valid": field(crc_valid, PROVENANCE_B200),
        "header": {
            "pdu_type_raw": field(decoded_packet.get("pdu_type_code"), PROVENANCE_B200),
            "pdu_type_name": field(pdu_type, PROVENANCE_B200),
            "tx_add": field(decoded_packet.get("tx_add"), PROVENANCE_B200),
            "rx_add": field(decoded_packet.get("rx_add"), PROVENANCE_B200),
            "payload_length": field(decoded_packet.get("length_octets"), PROVENANCE_B200),
            "header_valid": field(pdu_type in SUPPORTED_PDU_TYPES, PROVENANCE_B200),
        },
        "rf": {
            "candidate_id": None,  # filled in by the caller, which has the ledger row
            "start_sample": None,
            "packet_start_sample": None,
            "power_dbfs": field(decoded_packet.get("power_dbfs"), PROVENANCE_B200),
            "snr_db": field(decoded_packet.get("snr_db"), PROVENANCE_B200),
            "frequency_hz": field(decoded_packet.get("frequency_hz"), PROVENANCE_B200),
        },
    }
