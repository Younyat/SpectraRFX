"""Experimental Gate 2A.2 offline IQ analysis bridge for BLE Lab.

This program deliberately lives outside the FastAPI process, mirroring
ble_gate1b_replay_worker.py's subprocess boundary. Unlike that worker, this one
does NOT hard-pin an expected git commit and fail on mismatch: ble-worker-lab's
Gate 2A.2 DSP work is explicitly NOT frozen (dsp_gate=in_progress, Receiver
Candidate B not frozen), so there is no single "the" commit to demand -- it
moves as the campaign continues. Instead, the actual commit in use is recorded
truthfully in every output artifact as provenance.

This is a REAL analysis, not a simulation: it calls ble-worker-lab's own
iq_contract.validate_iq_job() and dsp_receiver.run_offline_receiver(), which
hands confirmed candidates to the SAME frozen Gate 1A decoder + Gate 1B
semantic parser the replay pipeline trusts -- so any confirmed_packets this
produces really did pass a real CRC check. The DSP front end that feeds it
(burst detection, GFSK discriminator, CFO estimate, 16-phase timing
interpolator) is the unvalidated, in-development part.

Every artifact this worker writes must carry the same honest labels:
dsp_gate=in_progress, iq_recovery_validated=false, ota_validated=false,
scientific_status=BLE_P0_INCOMPLETE. Never omit them, never let a caller
override them.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

CONTRACT_VERSION = "ble-gate2a2-offline-job-v1"


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


def head(repository: Path) -> str | None:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={repository}", "-C", str(repository), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def normalized(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return normalized(dataclasses.asdict(value))
    if isinstance(value, bytes):
        return value.hex().upper()
    if isinstance(value, complex):
        return {"real": value.real, "imag": value.imag}
    if isinstance(value, (tuple, list)):
        return [normalized(item) for item in value]
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()}
    return value


KNOWN_LIMITATIONS = {
    "dsp_gate": "in_progress",
    "iq_recovery_validated": False,
    "ota_validated": False,
    "scientific_status": "BLE_P0_INCOMPLETE",
    "receiver_candidate": "B",
    "candidate_frozen": False,
    "limitations": [
        "This is experimental, in-development DSP/IQ recovery -- Gate 2A.2, not Gate 1B.",
        "Receiver Candidate B is not frozen; results may contain decoding errors.",
        "Not validated for OTA reception. Normative conformance is not established.",
        "Only the frozen Gate 1A/1B decoder+parser boundary downstream of DSP recovery is trusted; "
        "the DSP front end (burst detection, CFO, timing recovery) feeding it is not.",
    ],
}


def run(request_path: Path, output: Path, repository: Path) -> int:
    started = time.time()
    revision = head(repository)
    request = json.loads(request_path.read_text(encoding="utf-8-sig"))
    if request.get("contract_version") != CONTRACT_VERSION:
        raise RuntimeError("unsupported_contract_version")

    job_id = request.get("job_id") or output.name
    output.mkdir(parents=True, exist_ok=True)
    target_request = output / "request.json"
    target_request.write_bytes(canonical(request))
    (output / "request.sha256").write_text(sha256(target_request) + "\n", encoding="ascii")

    sys.path.insert(0, str(repository / "src"))
    from ble_worker.dsp_models import INTERNAL_SAMPLE_RATE_HZ, IQ_CONTRACT_VERSION, IQ_PROFILE, PRIMARY_CHANNEL_FREQUENCIES
    from ble_worker.iq_contract import validate_iq_job
    from ble_worker.iq_reader import IqReaderConfig, read_iq_file
    from ble_worker.dsp_receiver import run_offline_receiver

    iq_path = Path(request["iq_file_path"])
    if not iq_path.is_file():
        raise RuntimeError("iq_file_not_found")
    channel_index = int(request["channel_index"])
    if channel_index not in PRIMARY_CHANNEL_FREQUENCIES:
        raise RuntimeError("unsupported_channel_index")

    chunk_samples = int(request.get("chunk_samples", 262_144))
    # iq_contract.validate_iq_job() requires the caller to have already
    # inspected the file (declared size/sample_count must match exactly) --
    # this is a deliberate anti-surprise check in ble-worker-lab's own
    # contract, so this worker reads the file's real size first rather than
    # trusting whatever the platform's job request happened to say.
    preread = read_iq_file(iq_path, IqReaderConfig("cf32_le", chunk_samples))
    contract_payload = {
        "contract_version": IQ_CONTRACT_VERSION,
        "profile": IQ_PROFILE,
        "passive_only": True,
        "source": {
            "type": "iq_file",
            "path": str(iq_path),
            "size_bytes": preread.accounting.bytes_total,
            "sha256": preread.input_iq_sha256,
        },
        "iq": {
            "format": "cf32_le",
            "sample_rate_hz": INTERNAL_SAMPLE_RATE_HZ,
            "channel_index": channel_index,
            "center_frequency_hz": PRIMARY_CHANNEL_FREQUENCIES[channel_index],
            "sample_count": preread.accounting.samples_total_in_file,
        },
        "receiver": {
            "chunk_samples": chunk_samples,
            "overlap_samples": int(request.get("overlap_samples", 8_192)),
            "dc_removal": bool(request.get("dc_removal", True)),
            "channel_filter": bool(request.get("channel_filter", True)),
            "cfo_correction": bool(request.get("cfo_correction", True)),
            "timing_recovery": bool(request.get("timing_recovery", True)),
        },
    }
    validated = validate_iq_job(contract_payload)

    # Real OTA bursts may include detector margins and exceed the synthetic
    # campaign's conservative 1,800-sample ceiling. Keep the existing decoder
    # and make only its already-defined burst limits explicit and bounded.
    minimum_burst_samples = int(request.get("minimum_burst_samples", validated.receiver_config.minimum_burst_samples))
    maximum_burst_samples = int(request.get("maximum_burst_samples", validated.receiver_config.maximum_burst_samples))
    if not 80 <= minimum_burst_samples <= maximum_burst_samples <= 8_192:
        raise RuntimeError("invalid_burst_sample_limits")
    receiver_config = dataclasses.replace(validated.receiver_config,
        minimum_burst_samples=minimum_burst_samples, maximum_burst_samples=maximum_burst_samples)

    result = run_offline_receiver(preread.samples, receiver_config, source_iq_sha256=validated.source_sha256)

    candidate_rows = [normalized(c) for c in result.candidates]
    semantic_rows = [normalized(p) for p in result.semantic_packets]
    semantic_by_id = {item.get("packet_id"): item for item in semantic_rows}
    confirmed_rows = []
    for decoded in result.decoded_results:
        for packet in decoded.confirmed_packets:
            item = normalized(packet); semantic = semantic_by_id.get(item.get("packet_sha256"), {})
            advertiser = (semantic.get("addresses") or {}).get("advertiser") or {}
            advertising = semantic.get("advertising_data") or {}
            item.update({"source": "usrp_b200", "frequency_hz": PRIMARY_CHANNEL_FREQUENCIES[channel_index],
                "address": advertiser.get("address_canonical"), "address_type": advertiser.get("address_type_from_header"),
                "advertising_data_hex": advertising.get("raw_hex"), "ad_structures": advertising.get("structures", []),
                "local_name": None, "power_dbfs": None, "snr_db": None})
            confirmed_rows.append(item)
    write_jsonl(output / "candidates.jsonl", candidate_rows)
    write_jsonl(output / "confirmed_packets.jsonl", confirmed_rows)
    write_jsonl(output / "semantic_packets.jsonl", semantic_rows)
    write_jsonl(output / "dsp_stage_events.jsonl", [normalized(e) for e in result.events])
    write_jsonl(output / "rejections.jsonl", [{"reason": r} for r in result.rejection_reasons])
    write_json(output / "hashes.json", result.derived_stream_sha256)
    write_json(output / "known_limitations.json", KNOWN_LIMITATIONS)
    write_json(output / "worker_manifest.json", {
        "worker_repository": str(repository),
        "worker_repository_commit": revision,
        "contract_version": CONTRACT_VERSION,
        "entry_point": Path(__file__).name,
        "note": "ble-worker-lab is under active development (Gate 2A.2, not frozen); "
                "this commit reflects the state at run time, it is not a fixed pin.",
    })
    write_json(output / "environment_manifest.json", {"python_executable": sys.executable, "python_version": platform.python_version(), "platform": platform.platform()})

    confirmed_count = sum(len(d.confirmed_packets) for d in result.decoded_results)
    summary = {
        "job_id": job_id,
        "contract_version": CONTRACT_VERSION,
        **KNOWN_LIMITATIONS,
        "worker_repository_commit": revision,
        "counts": {
            "candidates": len(result.candidates),
            "confirmed_packets": confirmed_count,
            "semantic_packets": len(result.semantic_packets),
            "rejections": len(result.rejection_reasons),
        },
        "processing_duration_seconds": round(time.time() - started, 6),
    }
    write_json(output / "result_summary.json", summary)
    write_json(output / "worker_exit.json", {"exit_code": 0, "status": "completed"})
    print(json.dumps({"job_id": job_id, "status": "completed", "confirmed_packets": confirmed_count}, separators=(",", ":")))
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
        output = args.output_dir.resolve()
        output.mkdir(parents=True, exist_ok=True)
        write_json(output / "worker_exit.json", {"exit_code": 2, "status": "failed", "error": f"{type(error).__name__}:{error}"})
        print(f"{type(error).__name__}:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
