"""Test double for backend/tools/ble_decode_burst_directory.py.

Mirrors the real tool's CLI contract exactly (--segments-dir, --output-dir,
--worker-repository, --channel, --start-index, --end-index) plus the same
progress.json / batch_summary.json / decoded_packets.jsonl /
semantic_packets.jsonl incremental-write behavior, so the resumable replay
engine in ble_offline_replay.py can be exercised without the real
ble-worker-lab DSP dependency.

Per-segment behavior (sleep, crash, confirmed packet count) is driven by a
JSON control file whose path comes from the FAKE_DECODER_CONTROL_PATH
environment variable, keyed by segment filename. This lets tests deterministically
force a timeout, a decoder crash, or a given number of confirmed packets for
one specific candidate without touching real DSP code.
"""
from __future__ import annotations  # noqa: F404 -- must stay first; enables list[dict] etc under the pinned Python 3.8 worker runtime

import argparse
import json
import os
import time
from pathlib import Path


def append_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--segments-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--worker-repository", type=Path, required=True)
    parser.add_argument("--channel", type=int, default=37)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--end-index", type=int)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    control_path = os.environ.get("FAKE_DECODER_CONTROL_PATH")
    control = json.loads(Path(control_path).read_text(encoding="utf-8")) if control_path and Path(control_path).is_file() else {}

    all_segments = sorted(args.segments_dir.glob("*.cf32"))
    selected = all_segments[args.start_index:args.end_index]
    decoded_path = args.output_dir / "decoded_packets.jsonl"
    semantic_path = args.output_dir / "semantic_packets.jsonl"
    if args.start_index == 0:
        decoded_path.write_text("", encoding="utf-8")
        semantic_path.write_text("", encoding="utf-8")

    attempts: list[dict] = []
    write_json(args.output_dir / "progress.json", {"processed_segments": 0, "total_segments": len(selected), "crc_valid_packets": 0})
    for index, segment in enumerate(selected, start=1):
        spec = control.get(segment.name, {})
        if spec.get("crash"):
            raise RuntimeError("SIMULATED_DECODER_CRASH:" + segment.name)
        time.sleep(float(spec.get("sleep_seconds", 0.0)))
        confirmed_count = int(spec.get("confirmed_packets", 0))
        packets, semantic = [], []
        # Mirrors the real decoded_packets.jsonl/semantic_packets.jsonl field
        # names and join key exactly (semantic row's top-level "packet_id" ==
        # confirmed packet's "packet_sha256" -- NOT "source_packet_sha256"),
        # including a distinct packet_start_bit per packet within one segment,
        # so tests can catch a regression of the real bug where two packets
        # confirmed from the same merged candidate collapsed onto the same
        # packet_id because payload/position fields were silently empty.
        for packet_index in range(confirmed_count):
            packet_sha = f"{segment.stem}-pkt{packet_index}"
            pdu_octets = spec.get("payload_hex") or f"AA{packet_index:02X}"
            packets.append({
                "packet_sha256": packet_sha,
                "iq_segment": segment.name,
                "address": spec.get("address", "00:00:00:00:00:00"),
                "address_type": "random",
                "pdu_type_name": spec.get("pdu_type_name", "ADV_NONCONN_IND"),
                "tx_add": 0,
                "rx_add": 0,
                "pdu_octets": pdu_octets,
                "payload_octets": pdu_octets,
                "packet_start_bit": packet_index * 400,
            })
            semantic.append({
                "packet_id": packet_sha,
                "source_packet_sha256": f"unrelated-hash-{packet_sha}",
                "iq_segment": segment.name,
                "addresses": {"advertiser": {"address_raw_air_octets": spec.get("address_raw_air_octets", "AABBCCDDEEFF")}},
            })
        append_jsonl(decoded_path, packets)
        append_jsonl(semantic_path, semantic)
        attempts.append({"iq_segment": segment.name, "confirmed_packets": len(packets), "semantic_packets": len(semantic)})
        write_json(args.output_dir / "batch_summary.json", {"segments": index, "start_index": args.start_index, "end_index": args.end_index, "attempts": attempts, "partial": True})
        write_json(args.output_dir / "progress.json", {"processed_segments": index, "total_segments": len(selected), "current_segment": segment.name})
    write_json(args.output_dir / "batch_summary.json", {"segments": len(attempts), "start_index": args.start_index, "end_index": args.end_index, "attempts": attempts, "partial": False})
    print(json.dumps({"segments": len(attempts)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
