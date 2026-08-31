import importlib.util
import json
import struct
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "tools" / "ble_gate1b_replay_worker.py"
FROZEN = Path(r"C:\Users\Usuario\ble-worker-gate1b-frozen")


def load_worker():
    spec = importlib.util.spec_from_file_location("ble_gate1b_replay_worker", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_replay_bundle_and_independent_pcapng_reader(tmp_path):
    if not FROZEN.exists():
        return
    worker = load_worker()
    request = {
        "job_id": "BLE-JOB-TEST001",
        "contract_version": "ble-job-v1",
        "profile": "ble_le1m_primary_advertising",
        "input_mode": "validated_bitstream_replay",
        "source": {"type": "gate1b_fixture", "fixture_id": "gate1b-campaign-001", "source_commit": worker.WORKER_COMMIT},
        "passive_only": True,
        "expected_worker_commit": worker.WORKER_COMMIT,
    }
    request_path = tmp_path / "input.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    output = tmp_path / request["job_id"]
    assert worker.run(request_path, output, FROZEN) == 0
    confirmed = [json.loads(line) for line in (output / "confirmed_packets.jsonl").read_text().splitlines()]
    assert len(confirmed) == 9
    assert {item["pdu_type"] for item in confirmed} >= {"ADV_IND", "ADV_DIRECT_IND", "ADV_NONCONN_IND", "SCAN_REQ", "SCAN_RSP", "CONNECT_IND", "ADV_SCAN_IND", "ADV_EXT_IND"}
    assert all(item["crc_valid"] for item in confirmed)

    # Independent minimal PCAPNG block walk: proves structural readability,
    # link type, packet count, channel pseudo-header and advertising AA.
    raw = (output / "capture.pcapng").read_bytes()
    offset, packets, link_type = 0, [], None
    while offset < len(raw):
        block_type, length = struct.unpack_from("<II", raw, offset)
        assert length >= 12 and length % 4 == 0
        assert struct.unpack_from("<I", raw, offset + length - 4)[0] == length
        body = raw[offset + 8:offset + length - 4]
        if block_type == 1:
            link_type = struct.unpack_from("<H", body)[0]
        elif block_type == 6:
            captured = struct.unpack_from("<I", body, 12)[0]
            packet = body[20:20 + captured]
            packets.append(packet)
        offset += length
    assert offset == len(raw) and link_type == 256 and len(packets) == 9
    assert {packet[0] for packet in packets} == {37, 38, 39}
    assert all(packet[10:14] == bytes.fromhex("D6BE898E") for packet in packets)


def test_iq_mode_is_rejected_before_output(tmp_path):
    if not FROZEN.exists():
        return
    worker = load_worker()
    request = {"job_id": "BLE-JOB-IQ", "contract_version": "ble-job-v1", "input_mode": "iq_capture", "expected_worker_commit": worker.WORKER_COMMIT}
    path = tmp_path / "input.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    try:
        worker.run(path, tmp_path / "out", FROZEN)
    except RuntimeError as error:
        assert str(error) == "iq_recovery_not_available"
    else:
        raise AssertionError("IQ mode was accepted")
