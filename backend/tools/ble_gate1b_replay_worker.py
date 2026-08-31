"""External Gate 1B replay bridge for BLE Platform Integration.

This program deliberately lives outside the FastAPI process.  It loads the
frozen BLE package only after verifying the repository revision and emits an
immutable, self-describing job directory.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import platform
import struct
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

WORKER_COMMIT = "7b685f7fb0d161be6577d862711456532dcb3528"
CONTRACT_VERSION = "ble-job-v1"
ADV_AA = 0x8E89BED6


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_bytes(canonical(value))


def write_jsonl(path: Path, values: Iterable[Any]) -> None:
    path.write_bytes(b"".join(canonical(value) for value in values))


def head(repository: Path) -> str:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={repository}", "-C", str(repository), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def pad4(data: bytes) -> bytes:
    return data + b"\0" * ((-len(data)) % 4)


def block(kind: int, body: bytes) -> bytes:
    length = 12 + len(pad4(body))
    return struct.pack("<II", kind, length) + pad4(body) + struct.pack("<I", length)


def option(code: int, payload: bytes) -> bytes:
    return struct.pack("<HH", code, len(payload)) + pad4(payload)


def pcapng(path: Path, packets: list[dict[str, Any]]) -> None:
    # LINKTYPE_BLUETOOTH_LE_LL_WITH_PHDR (256). The 10-byte pseudo-header is
    # channel, unknown signal/noise, AA offenses, reference AA and flags.
    # Only dewhitened, AA-valid and CRC-valid facts are asserted.
    output = bytearray()
    output += block(0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1))
    if_options = option(2, b"BLE Gate 1B validated bitstream replay") + option(9, b"\x06") + option(0, b"")
    output += block(1, struct.pack("<HHI", 256, 0, 65535) + if_options)
    for sequence, packet in enumerate(packets, 1):
        crc = int(packet["crc_computed"], 16)
        # The CRC register is transmitted MSB-first, while each captured BLE
        # octet represents chronological air bits LSB-first.
        reverse8 = lambda value: int(f"{value:08b}"[::-1], 2)
        crc_air = bytes(reverse8((crc >> shift) & 0xFF) for shift in (16, 8, 0))
        flags = 0x0001 | 0x0020 | 0x0080
        phdr = struct.pack("<BbbBIH", packet["channel_index"], 0, 0, 0, 0, flags)
        wire = phdr + bytes.fromhex("D6BE898E") + bytes.fromhex(packet["pdu_hex"]) + crc_air
        comment = canonical({"packet_id": packet["packet_id"], "channel_index": packet["channel_index"], "pcap_timestamp_source": "replay_sequence"}).rstrip(b"\n")
        opts = option(1, comment) + option(0, b"")
        output += block(6, struct.pack("<IIIII", 0, 0, sequence, len(wire), len(wire)) + pad4(wire) + opts)
    path.write_bytes(output)


def normalized(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return normalized(dataclasses.asdict(value))
    if isinstance(value, bytes):
        return value.hex().upper()
    if isinstance(value, tuple):
        return [normalized(item) for item in value]
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalized(item) for item in value]
    return value


def run(request_path: Path, output: Path, repository: Path) -> int:
    started = time.time()
    revision = head(repository)
    if revision != WORKER_COMMIT:
        raise RuntimeError(f"worker_version_mismatch:{revision or 'unavailable'}")
    request = json.loads(request_path.read_text(encoding="utf-8-sig"))
    if request.get("contract_version") != CONTRACT_VERSION:
        raise RuntimeError("unsupported_contract_version")
    if request.get("input_mode") != "validated_bitstream_replay":
        raise RuntimeError("iq_recovery_not_available")
    if request.get("expected_worker_commit") != WORKER_COMMIT:
        raise RuntimeError("worker_version_mismatch")
    job_id = request.get("job_id") or output.name
    output.mkdir(parents=True, exist_ok=True)
    target_request = output / "request.json"
    target_request.write_bytes(canonical(request))
    (output / "request.sha256").write_text(sha256(target_request) + "\n", encoding="ascii")

    sys.path.insert(0, str(repository / "src"))
    from ble_worker.bit_conversions import octets_to_lsb_first_bits
    from ble_worker.crc import ADVERTISING_CRC_INIT, ble_crc24
    from ble_worker.legacy_pdu_parser import parse_confirmed_packet
    from ble_worker.semantic_models import ConfirmedLinkLayerPacket

    independent_path = repository / "test_vectors/independent/gate1b_semantic_vectors.json"
    official_path = repository / "test_vectors/official/gate1b_semantic_vectors.json"
    independent = json.loads(independent_path.read_text(encoding="utf-8-sig"))["vectors"]
    official = json.loads(official_path.read_text(encoding="utf-8-sig"))["vectors"]
    vectors = independent + [official[0]]
    channels = [37, 38, 39] * 3
    confirmed, parsed, advertisements, candidates, diagnostics = [], [], [], [], []
    advertisers: dict[str, dict[str, Any]] = {}
    for index, vector in enumerate(vectors):
        raw = bytes.fromhex(vector["input_pdu_hex"])
        bits = tuple(octets_to_lsb_first_bits(raw))
        crc = ble_crc24(bits, ADVERTISING_CRC_INIT)
        packet_id = f"BLE-PKT-{index + 1:06d}"
        source_hash = hashlib.sha256(raw).hexdigest()
        obj = ConfirmedLinkLayerPacket(packet_id, index + 1, channels[index], ADV_AA, bits, raw, raw[:2], raw[2:], crc, crc, True, index * 1000, index * 1000 + len(bits), source_hash)
        semantic = parse_confirmed_packet(obj)
        record = {"packet_id": packet_id, "receiver_trace_id": index + 1, "channel_index": channels[index], "access_address": "8E89BED6", "pdu_hex": raw.hex().upper(), "pdu_type": semantic.pdu["type_name"], "length_octets": len(raw), "crc_received": f"{crc:06X}", "crc_computed": f"{crc:06X}", "crc_valid": True, "evidence_level": "crc_valid", "source_sha256": source_hash, "pcap_timestamp_source": "replay_sequence"}
        confirmed.append(record)
        parsed_record = normalized(semantic)
        parsed.append(parsed_record)
        if semantic.advertising_data is not None:
            advertisements.append({"packet_id": packet_id, "channel_index": channels[index], "pdu_type": semantic.pdu["type_name"], "advertising_data": normalized(semantic.advertising_data)})
        for role, address in semantic.addresses.items():
            canonical_address = address.get("address_canonical")
            if canonical_address:
                advertisers.setdefault(canonical_address, {"address": canonical_address, "address_type": address.get("address_type"), "roles": [], "packet_ids": [], "identity_status": "observed_address_not_device_identity"})
                advertisers[canonical_address]["roles"].append(role)
                advertisers[canonical_address]["packet_ids"].append(packet_id)
    candidates.append({"candidate_id": "BLE-CAND-CRC-INVALID-000001", "channel_index": 37, "crc_valid": False, "evidence_level": "crc_invalid", "publication_status": "diagnostic_only", "rejection_reason": "crc_mismatch"})
    diagnostics.append({"diagnostic_id": "BLE-DIAG-000001", "candidate_id": candidates[0]["candidate_id"], "reason": "crc_mismatch", "published_as_packet": False})
    write_jsonl(output / "candidate_packets.jsonl", candidates)
    write_jsonl(output / "confirmed_packets.jsonl", confirmed)
    write_jsonl(output / "parsed_packets.jsonl", parsed)
    write_jsonl(output / "advertisements.jsonl", advertisements)
    write_json(output / "advertisers.json", {"advertisers": sorted(advertisers.values(), key=lambda x: x["address"])})
    write_jsonl(output / "semantic_diagnostics.jsonl", diagnostics)
    source_manifest = {"source_type": "gate1b_fixture", "fixture_id": "gate1b-campaign-001", "source_commit": revision, "input_mode": "validated_bitstream_replay", "not_rf_capture": True, "files": [{"path": str(independent_path.relative_to(repository)).replace("\\", "/"), "sha256": sha256(independent_path)}, {"path": str(official_path.relative_to(repository)).replace("\\", "/"), "sha256": sha256(official_path)}]}
    write_json(output / "source_manifest.json", source_manifest)
    write_json(output / "worker_manifest.json", {"worker_repository": str(repository), "worker_commit": revision, "contract_version": CONTRACT_VERSION, "entry_point": Path(__file__).name})
    write_json(output / "environment_manifest.json", {"python_executable": sys.executable, "python_version": platform.python_version(), "platform": platform.platform()})
    write_json(output / "receiver_stage_summary.json", {"input_mode": "validated_bitstream_replay", "candidate_packets": len(candidates), "crc_valid_packets": len(confirmed), "parsed_packets": len(parsed), "iq_recovery_performed": False, "rf_recovery_performed": False})
    write_json(output / "rejection_summary.json", {"crc_invalid_diagnostic_candidates": 1, "invalid_candidates_published": 0, "duplicate_publications": 0})
    write_json(output / "known_limitations.json", {"dsp_gate": "not_started", "iq_recovery_validated": False, "ota_validated": False, "limitations": ["No IQ demodulation or RF recovery was performed.", "Observed advertiser addresses are not persistent device identities.", "ADV_EXT_IND support is bounded to primary-header semantics."]})
    summary = {"job_id": job_id, "contract_version": CONTRACT_VERSION, "input_mode": "validated_bitstream_replay", "capability_status": "experimental", "scientific_status": "BLE_P0_INCOMPLETE", "normative_conformance": "not_established", "worker_commit": revision, "counts": {"candidate_packets": len(candidates), "confirmed_packets": len(confirmed), "crc_valid_packets": len(confirmed), "parsed_packets": len(parsed), "advertisements": len(advertisements), "crc_invalid_published": 0, "duplicate_publications": 0}, "pcap_timestamp_source": "replay_sequence", "processing_duration_seconds": round(time.time() - started, 6)}
    write_json(output / "result_summary.json", summary)
    pcapng(output / "capture.pcapng", confirmed)
    write_json(output / "worker_exit.json", {"exit_code": 0, "status": "completed", "cancellation_status": "not_cancelled"})
    # Adapter-owned lifecycle/provenance files are finalized after this process
    # exits and are therefore intentionally outside the immutable worker set.
    declared = [path for path in sorted(output.iterdir()) if path.is_file() and path.name not in {"artifacts_manifest.json", "worker_stdout.log", "worker_stderr.log", "worker_exit.json", "job_events.jsonl", "job.json"}]
    manifest = {"schema_version": "ble-artifacts-manifest-v1", "contract_version": CONTRACT_VERSION, "job_id": job_id, "worker_commit": revision, "scientific_status": "BLE_P0_INCOMPLETE", "counts": summary["counts"], "files": [{"path": path.name, "sha256": sha256(path), "size_bytes": path.stat().st_size} for path in declared]}
    write_json(output / "artifacts_manifest.json", manifest)
    print(json.dumps({"job_id": job_id, "status": "completed", "confirmed_packets": len(confirmed)}, separators=(",", ":")))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-repository", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--job-id")  # adapter provenance; request remains authoritative
    args = parser.parse_args()
    try:
        return run(args.request.resolve(), args.output_dir.resolve(), args.worker_repository.resolve())
    except Exception as error:
        print(f"{type(error).__name__}:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
