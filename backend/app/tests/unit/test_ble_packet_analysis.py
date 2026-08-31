from __future__ import annotations

import json
from pathlib import Path

from app.infrastructure.ble.capture.ble_offline_replay import sha256_file, write_json, write_jsonl
from app.infrastructure.ble.packet_analysis.ble_packet_analysis_service import BlePacketAnalysisService

CAPTURE_ID = "BLE-IQ-pktlabtest"
OLDER_CAPTURE_ID = "BLE-IQ-pktlabolder"
EXECUTION_ID = "BLE-HYBRID-pktlabtest"
TARGET_ADDRESS = "B0:B4:48:C0:36:06"
NON_TARGET_ADDRESS = "11:22:33:44:55:66"
REPLAY_RUN_ID = "BLE-RFFI-REPLAY-pktlabtest-0001"


def _write_capture(capture_root: Path, capture_id: str, samples: int = 8) -> tuple[Path, str]:
    capture_dir = capture_root / capture_id
    capture_dir.mkdir(parents=True)
    data = capture_dir / f"{capture_id}.sigmf-data"
    data.write_bytes(b"\x00" * (samples * 8))
    digest = sha256_file(data)
    write_json(capture_dir / "capture_manifest.json", {
        "capture_id": capture_id, "data_path": data.name, "data_sha256": digest,
        "actual_samples": samples, "actual_size_bytes": data.stat().st_size,
        "sample_format": "cf32_le", "sample_rate_sps": 4_000_000, "center_frequency_hz": 2_402_000_000,
        "bandwidth_hz": 2_000_000, "ble_channel": 37, "hash_status": "VERIFIED", "metadata_status": "COMPLETE",
        "overflow_count": 0, "discontinuity_count": 0, "short_read_count": 0, "write_error_count": 0,
        "created_at_utc": "2026-07-24T12:00:00Z",
        "b200_rf_started_at": "2026-07-24T12:00:00Z", "b200_rf_finished_at": "2026-07-24T12:00:10Z",
        "experimental_metadata": {"campaign_id": "TEST-CAMPAIGN", "condition_id": "C001", "session_id": "S001-POS"},
    })
    return capture_dir, digest


def _write_session(session_root: Path, capture_id: str, execution_id: str, native_scan_dir: Path) -> None:
    (session_root / execution_id).mkdir(parents=True, exist_ok=True)
    write_json(session_root / execution_id / "session_manifest.json", {
        "session_id": execution_id, "capture_id": capture_id, "target_address": TARGET_ADDRESS,
        "native_scan_path": str(native_scan_dir),
    })


def _write_replay(capture_dir: Path, replay_run_id: str) -> Path:
    replay_dir = capture_dir / "offline_replays" / replay_run_id
    (replay_dir / "decoded").mkdir(parents=True)

    candidates = [
        {"candidate_id": "cand-target", "candidate_index": 0, "start_sample": 0, "end_sample": 200, "processing_status": "PROCESSED"},
        {"candidate_id": "cand-other", "candidate_index": 1, "start_sample": 300, "end_sample": 500, "processing_status": "PROCESSED"},
        {"candidate_id": "cand-unsupported", "candidate_index": 2, "start_sample": 600, "end_sample": 800, "processing_status": "PROCESSED"},
    ]
    write_jsonl(replay_dir / "candidate_manifest.jsonl", candidates)
    write_json(replay_dir / "replay_state.json", {"checkpoint_sequence": 3, "total_candidate_segments": 3})

    decoded_packets = [
        {
            "packet_sha256": "sha-target-1", "iq_segment": "burst-000001.cf32", "address": TARGET_ADDRESS,
            "address_type": "public", "pdu_type_name": "ADV_IND", "tx_add": 0, "rx_add": 0, "crc_valid": True,
            "pdu_octets": "42250ADE4D9C0801", "payload_octets": "0ADE4D9C0801", "packet_start_bit": 57,
            "length_octets": 6, "power_dbfs": -40.0, "snr_db": 12.0, "frequency_hz": 2_402_000_000,
            "pdu_type_code": 2, "crc_received": 123, "crc_computed": 123,
        },
        {
            "packet_sha256": "sha-other-1", "iq_segment": "burst-000002.cf32", "address": NON_TARGET_ADDRESS,
            "address_type": "random", "pdu_type_name": "ADV_NONCONN_IND", "tx_add": 1, "rx_add": 0, "crc_valid": True,
            "pdu_octets": "42260BBBBBBB", "payload_octets": "0BBBBBBB", "packet_start_bit": 40,
            "length_octets": 4, "power_dbfs": -55.0, "snr_db": 6.0, "frequency_hz": 2_402_000_000,
            "pdu_type_code": 2, "crc_received": 456, "crc_computed": 456,
        },
        {
            # An unsupported PDU type -- the parser must say so honestly, not invent fields.
            "packet_sha256": "sha-unsupported-1", "iq_segment": "burst-000003.cf32", "address": None,
            "address_type": None, "pdu_type_name": "CONNECT_IND", "tx_add": 0, "rx_add": 0, "crc_valid": True,
            "pdu_octets": "4500", "payload_octets": "", "packet_start_bit": 10,
            "length_octets": 0, "power_dbfs": -60.0, "snr_db": 2.0, "frequency_hz": 2_402_000_000,
            "pdu_type_code": 5, "crc_received": 789, "crc_computed": 789,
        },
    ]
    write_jsonl(replay_dir / "decoded" / "decoded_packets.jsonl", decoded_packets)

    semantic_packets = [
        {
            "packet_id": "sha-target-1", "iq_segment": "burst-000001.cf32",
            "addresses": {"advertiser": {"address_raw_air_octets": "0ADE4D9C0801", "address_canonical": TARGET_ADDRESS, "address_type_from_header": "public"}},
            "advertising_data": {"structures": [
                {"structure_index": 0, "ad_type_raw": 255, "ad_type_name": "Manufacturer Specific Data", "length_raw": 4,
                 "ad_data_raw_hex": "0D000300", "decode_status": "decoded",
                 "decoded_value": {"company_identifier": 13, "company": {"name": None, "resolution_status": "resolved_in_pinned_registry", "value": 13}, "vendor_payload_hex": "0300", "vendor_decode_status": "raw_only"}},
                {"structure_index": 1, "ad_type_raw": 9, "ad_type_name": "Complete Local Name", "length_raw": 17,
                 "ad_data_raw_hex": "4343323635302053656E736F72546167", "decode_status": "decoded",
                 "decoded_value": {"text": "CC2650 SensorTag"}},
            ]},
            "pdu": {"type_name": "ADV_IND", "tx_add": 0, "rx_add": 0, "payload_raw_hex": "0ADE4D9C0801"},
        },
        {
            "packet_id": "sha-other-1", "iq_segment": "burst-000002.cf32",
            "addresses": {"advertiser": {"address_raw_air_octets": "665544332211", "address_canonical": NON_TARGET_ADDRESS, "address_type_from_header": "random"}},
            "advertising_data": {"structures": [
                {"structure_index": 0, "ad_type_raw": 7, "ad_type_name": "Unrecognized Reserved Type", "length_raw": 1,
                 "ad_data_raw_hex": "00", "decode_status": "preserved_unknown", "decoded_value": None},
            ]},
            "pdu": {"type_name": "ADV_NONCONN_IND", "tx_add": 1, "rx_add": 0, "payload_raw_hex": "0BBBBBBB"},
        },
        {
            "packet_id": "sha-unsupported-1", "iq_segment": "burst-000003.cf32",
            "addresses": {"advertiser": {}}, "advertising_data": {"structures": []},
            "pdu": {"type_name": "CONNECT_IND", "tx_add": 0, "rx_add": 0, "payload_raw_hex": ""},
        },
    ]
    write_jsonl(replay_dir / "decoded" / "semantic_packets.jsonl", semantic_packets)

    ledger = [
        {
            "packet_id": "pkt-target-1", "candidate_id": "cand-target", "packet_sha256": "sha-target-1",
            "packet_start_sample": 8, "rf_timestamp_utc": None,
            "pdu_type": "ADV_IND", "advertiser_address_raw": "0ADE4D9C0801", "advertiser_address_canonical": TARGET_ADDRESS,
            "address_type": "public", "tx_add": 0, "rx_add": 0, "payload_sha256": "deadbeef",
            "nearest_windows_callback_timestamp": "2026-07-24T12:00:00.100Z", "time_delta_ms": 12.0,
            "address_match_status": "MATCHED", "temporal_match_status": "MATCHED", "association_strength": "STRONG",
            "association_rejection_reason": None, "target_address_match": True,
        },
        {
            "packet_id": "pkt-other-1", "candidate_id": "cand-other", "packet_sha256": "sha-other-1",
            "packet_start_sample": 305, "rf_timestamp_utc": None,
            "pdu_type": "ADV_NONCONN_IND", "advertiser_address_raw": "665544332211", "advertiser_address_canonical": NON_TARGET_ADDRESS,
            "address_type": "random", "tx_add": 1, "rx_add": 0, "payload_sha256": "cafebabe",
            "nearest_windows_callback_timestamp": None, "time_delta_ms": None,
            "address_match_status": "NO_CANDIDATE_IN_WINDOW", "temporal_match_status": "NO_MATCH", "association_strength": "NONE",
            "association_rejection_reason": "TIME_DELTA_ABOVE_THRESHOLD", "target_address_match": False,
        },
        {
            "packet_id": "pkt-unsupported-1", "candidate_id": "cand-unsupported", "packet_sha256": "sha-unsupported-1",
            "packet_start_sample": 610, "rf_timestamp_utc": None,
            "pdu_type": "CONNECT_IND", "advertiser_address_raw": None, "advertiser_address_canonical": None,
            "address_type": None, "tx_add": 0, "rx_add": 0, "payload_sha256": None,
            "nearest_windows_callback_timestamp": None, "time_delta_ms": None,
            "address_match_status": "ADDRESS_NOT_PRESENT_IN_PDU", "temporal_match_status": "NO_MATCH", "association_strength": "NONE",
            "association_rejection_reason": "ADDRESS_NOT_PRESENT_IN_PDU", "target_address_match": False,
        },
    ]
    write_jsonl(replay_dir / "packet_association_ledger.jsonl", ledger)

    write_json(replay_dir / "replay_summary.json", {
        "execution_status": "FULLY_PROCESSED", "scientific_completion_status": "COMPLETE",
        "coverage": {"total_candidate_segments": 3, "processed_segments": 3, "failed_segments": 0, "pending_segments": 0},
        "decision": {"decision": "OFFLINE_REPLAY_NOT_ACCEPTED", "dataset_eligibility_status": "NOT_ELIGIBLE", "scientific_decision": "OFFLINE_REPLAY_NOT_ACCEPTED"},
        "candidate_funnel": {"crc_valid_packets": 3, "unique_crc_valid_packets": 3, "target_address_candidates": 1, "strong_target_matches": 1, "conflicting_matches": 0},
    })
    return replay_dir


def _build_service(tmp_path: Path, with_older_incomplete: bool = False):
    capture_root = tmp_path / "ble" / "iq_captures"
    session_root = tmp_path / "ble_lab" / "sessions"
    analysis_root = tmp_path / "ble_lab" / "packet_analysis"
    native_scan_dir = tmp_path / "ble" / "native" / "scans" / EXECUTION_ID
    native_scan_dir.mkdir(parents=True)
    write_jsonl(native_scan_dir / "advertisements.jsonl", [
        {"native_observation_id": "native-1", "address": TARGET_ADDRESS, "address_type": "public", "local_name": "CC2650 SensorTag",
         "rssi_dbm": -55, "tx_power_dbm": 0, "manufacturer_data": {}, "service_data": {}, "service_uuids": [],
         "connectable": True, "timestamp_callback_utc": "2026-07-24T12:00:00.100Z"},
        {"native_observation_id": "native-2", "address": "AA:BB:CC:DD:EE:FF", "address_type": "random", "local_name": None,
         "rssi_dbm": -70, "tx_power_dbm": None, "manufacturer_data": {}, "service_data": {}, "service_uuids": [],
         "connectable": False, "timestamp_callback_utc": "2026-07-24T12:00:05.000Z"},
    ])

    capture_dir, _ = _write_capture(capture_root, CAPTURE_ID)
    _write_session(session_root, CAPTURE_ID, EXECUTION_ID, native_scan_dir)
    replay_dir = _write_replay(capture_dir, REPLAY_RUN_ID)

    if with_older_incomplete:
        older_dir, _ = _write_capture(capture_root, OLDER_CAPTURE_ID)
        older_replay_dir = older_dir / "offline_replays" / "BLE-RFFI-REPLAY-pktlabolder-0001"
        (older_replay_dir / "decoded").mkdir(parents=True)
        write_jsonl(older_replay_dir / "candidate_manifest.jsonl", [{"candidate_id": "cand-a", "candidate_index": 0, "start_sample": 0, "end_sample": 10, "processing_status": "PENDING"}])
        write_json(older_replay_dir / "replay_state.json", {"checkpoint_sequence": 1})
        write_json(older_replay_dir / "replay_summary.json", {"execution_status": "PARTIAL", "scientific_completion_status": "INCOMPLETE", "coverage": {"total_candidate_segments": 1, "processed_segments": 0, "failed_segments": 0, "pending_segments": 1}, "decision": {"decision": "OFFLINE_REPLAY_NOT_ACCEPTED", "dataset_eligibility_status": "NOT_ELIGIBLE", "scientific_decision": "INCOMPLETE_REPLAY"}, "candidate_funnel": {"crc_valid_packets": 0, "unique_crc_valid_packets": 0, "target_address_candidates": 0, "strong_target_matches": 0, "conflicting_matches": 0}})
        write_jsonl(older_replay_dir / "packet_association_ledger.jsonl", [])
        write_jsonl(older_replay_dir / "decoded" / "decoded_packets.jsonl", [])
        write_jsonl(older_replay_dir / "decoded" / "semantic_packets.jsonl", [])

    service = BlePacketAnalysisService(capture_root, session_root, analysis_root)
    return service, capture_dir, replay_dir


def test_latest_completed_prefers_fully_analyzed_over_more_recently_created(tmp_path):
    service, _, _ = _build_service(tmp_path, with_older_incomplete=True)
    listing = service.list_captures()
    assert listing["classification"]["LAST_FULLY_ANALYZED_CAPTURE"] == CAPTURE_ID
    # The "older" capture is a decoy that must NOT be reported as fully analyzed
    # just because a directory with that name exists.
    assert listing["classification"]["LAST_CREATED_CAPTURE"] in {CAPTURE_ID, OLDER_CAPTURE_ID}


def test_packet_ids_unique_and_every_field_carries_provenance(tmp_path):
    service, _, _ = _build_service(tmp_path)
    result = service.analyze(CAPTURE_ID)
    packet_ids = [p["packet_id"] for p in result["packets"]]
    assert len(packet_ids) == len(set(packet_ids)) == 3
    for packet in result["packets"]:
        assert packet["pdu_type"]["source"] in {"B200", "NOT_AVAILABLE"}
        assert packet["advertiser_address_canonical"]["source"] == "B200"
        assert packet["crc_valid"]["source"] == "B200"


def test_target_packet_reaches_windows_corroborated_level(tmp_path):
    service, _, _ = _build_service(tmp_path)
    result = service.analyze(CAPTURE_ID)
    target = next(p for p in result["packets"] if p["is_target"])
    assert target["knowledge_level"] == "LEVEL_5_WINDOWS_CORROBORATED"
    assert target["windows_match"]["value"] == "WINDOWS_MATCHED"
    assert target["physical_unit_caveat"] == "PHYSICAL_UNIT_NOT_PROVEN"


def test_ti_company_id_resolves_but_does_not_claim_specific_model(tmp_path):
    service, _, _ = _build_service(tmp_path)
    result = service.analyze(CAPTURE_ID)
    target = next(p for p in result["packets"] if p["is_target"])
    manufacturer = target["ad_structures"][0]["manufacturer"]
    assert manufacturer["company_id"]["value"] == 13
    assert manufacturer["company_name"]["value"] == "Texas Instruments Inc."
    assert manufacturer["company_name"]["source"] == "MANUFACTURER_DOCUMENTATION"
    assert manufacturer["compatibility_note"] == "MANUFACTURER_ID_COMPATIBLE_WITH_TEXAS_INSTRUMENTS"
    # The parser must never upgrade "TI-compatible" into "this is a CC2650" on its own.
    assert "CC2650" not in json.dumps(manufacturer)


def test_unknown_ad_type_and_unsupported_pdu_are_not_invented(tmp_path):
    service, _, _ = _build_service(tmp_path)
    result = service.analyze(CAPTURE_ID)
    other = next(p for p in result["packets"] if p["advertiser_address_canonical"]["value"] == NON_TARGET_ADDRESS)
    assert other["ad_structures"][0]["parser_status"] in {"RAW_ONLY", "UNKNOWN_AD_TYPE"}
    unsupported = next(p for p in result["packets"] if p["pdu_type"]["value"] == "CONNECT_IND")
    assert unsupported["link_layer"]["parser_status"] == "PDU_VALID_BUT_PARSER_NOT_IMPLEMENTED"


def test_windows_only_observations_available_without_rf_packet(tmp_path):
    service, _, _ = _build_service(tmp_path)
    result = service.analyze(CAPTURE_ID)
    addresses = {row["bluetooth_address"] for row in result["windows_only_observations"]}
    assert "AA:BB:CC:DD:EE:FF" in addresses  # never appears in any decoded packet


def test_analysis_is_marked_diagnostic_only_and_never_dataset_eligible(tmp_path):
    service, _, _ = _build_service(tmp_path)
    result = service.analyze(CAPTURE_ID)
    assert result["purpose"] == "BLE_PACKET_ANALYSIS"
    assert result["diagnostic_only"] is True
    assert result["scientific_campaign_member"] is False
    assert result["dataset_eligible"] is False
    assert result["training_eligible"] is False


def test_analysis_never_modifies_phase1_replay_artifacts(tmp_path):
    service, _, replay_dir = _build_service(tmp_path)
    ledger_path = replay_dir / "packet_association_ledger.jsonl"
    summary_path = replay_dir / "replay_summary.json"
    before_ledger, before_summary = ledger_path.read_bytes(), summary_path.read_bytes()
    before_mtime_ledger, before_mtime_summary = ledger_path.stat().st_mtime, summary_path.stat().st_mtime
    service.analyze(CAPTURE_ID)
    assert ledger_path.read_bytes() == before_ledger
    assert summary_path.read_bytes() == before_summary
    assert ledger_path.stat().st_mtime == before_mtime_ledger
    assert summary_path.stat().st_mtime == before_mtime_summary


def test_transmitter_catalog_never_labels_target_a_confirmed_sensor_without_corroboration(tmp_path):
    service, _, _ = _build_service(tmp_path)
    result = service.analyze(CAPTURE_ID)
    other = next(tx for tx in result["transmitters"] if not tx["is_target"])
    assert other["classification"] == "UNKNOWN_BLE_TRANSMITTER"
    target = next(tx for tx in result["transmitters"] if tx["is_target"])
    assert target["classification"] == "KNOWN_CONTROLLED_SENSOR"  # corroborated in this fixture


def test_gatt_sensor_values_never_shown_as_observed_in_this_offline_capture(tmp_path):
    service, _, _ = _build_service(tmp_path)
    result = service.analyze(CAPTURE_ID)
    target_view = next(v for v in result["sensor_views"] if any(tx["logical_transmitter_id"] == v["transmitter_id"] and tx["is_target"] for tx in result["transmitters"]))
    for observation in target_view["observations"]:
        assert observation["value_via_gatt"]["source"] == "NOT_AVAILABLE"
        assert observation["status"] == "NOT_TRANSMITTED"
