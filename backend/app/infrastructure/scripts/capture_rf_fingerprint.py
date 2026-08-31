#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#C:\Users\Usuario\radioconda\python.exe capture_rf_fingerprint.py --capture-root rf_dataset --emitter-device-id remote_001 --session-id 2026_04_21_lab_01 --receiver-id usrp_b200_01 --environment-id lab_a --freq 89.400000 --duration 5 --sample-rate 10000000 --gain 20
import argparse
import json
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from gnuradio import blocks
from gnuradio import gr
from gnuradio import uhd


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def sanitize_name(s: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in s).strip("_")


class RFCapture(gr.top_block):
    def __init__(
        self,
        center_freq_hz: float,
        output_path: str,
        duration_s: float,
        samp_rate: float,
        gain: float,
        antenna: str = "RX2",
        device_addr: str = "",
        use_agc: bool = False,
    ):
        gr.top_block.__init__(self, "RF Fingerprint Capture", catch_exceptions=True)

        self.center_freq_hz = float(center_freq_hz)
        self.output_path = str(output_path)
        self.duration_s = float(duration_s)
        self.samp_rate = float(samp_rate)
        self.gain = float(gain)
        self.antenna = str(antenna)
        self.device_addr = str(device_addr)
        self.use_agc = bool(use_agc)

        self.num_samples = int(self.duration_s * self.samp_rate)

        self.uhd_usrp_source_0 = uhd.usrp_source(
            ",".join((self.device_addr, "")),
            uhd.stream_args(
                cpu_format="fc32",
                args="",
                channels=list(range(0, 1)),
            ),
        )

        self.uhd_usrp_source_0.set_samp_rate(self.samp_rate)
        self.uhd_usrp_source_0.set_time_unknown_pps(uhd.time_spec(0))
        self.uhd_usrp_source_0.set_center_freq(self.center_freq_hz, 0)
        self.uhd_usrp_source_0.set_antenna(self.antenna, 0)

        if self.use_agc:
            try:
                self.uhd_usrp_source_0.set_rx_agc(True, 0)
                print("[INFO] RX AGC enabled")
            except Exception as exc:
                print("[WARN] Could not enable RX AGC: {}".format(exc))
        else:
            try:
                self.uhd_usrp_source_0.set_gain(self.gain, 0)
            except TypeError:
                self.uhd_usrp_source_0.set_gain(self.gain)

        self.blocks_head_0 = blocks.head(gr.sizeof_gr_complex, self.num_samples)
        self.blocks_file_sink_0 = blocks.file_sink(gr.sizeof_gr_complex, self.output_path, False)
        self.blocks_file_sink_0.set_unbuffered(False)

        self.connect((self.uhd_usrp_source_0, 0), (self.blocks_head_0, 0))
        self.connect((self.blocks_head_0, 0), (self.blocks_file_sink_0, 0))


def main():
    parser = argparse.ArgumentParser(description="Capture RF IQ to .cfile and save metadata for RF fingerprint training")
    parser.add_argument("--capture-root", type=str, default="rf_dataset", help="Root dataset directory")
    parser.add_argument("--emitter-device-id", type=str, required=True, help="Emitter identifier, for example remote_001")
    parser.add_argument("--session-id", type=str, required=True, help="Session identifier, for example 2026_04_21_lab_01")
    parser.add_argument("--receiver-id", type=str, default="usrp_b200_01", help="Receiver identifier")
    parser.add_argument("--environment-id", type=str, default="default_lab", help="Environment identifier")
    parser.add_argument("--label", type=str, default="", help="Optional label text")
    parser.add_argument("--modulation-hint", type=str, default="unknown", help="Optional modulation hint")
    parser.add_argument("--notes", type=str, default="", help="Optional notes")
    parser.add_argument("--freq", type=float, required=True, help="Center frequency in MHz")
    parser.add_argument("--duration", type=float, default=5.0, help="Capture duration in seconds")
    parser.add_argument("--sample-rate", type=float, default=2e6, help="Sample rate in Hz")
    parser.add_argument("--gain", type=float, default=20.0, help="Manual RX gain in dB")
    parser.add_argument("--antenna", type=str, default="RX2", help="RX antenna")
    parser.add_argument("--device-addr", type=str, default="", help="UHD device args")
    parser.add_argument("--use-agc", action="store_true", help="Enable AGC instead of fixed gain")
    parser.add_argument("--settle-ms", type=int, default=300, help="Delay before starting capture in ms")
    parser.add_argument("--capture-type", type=str, default="fingerprint_iq", help="Capture type tag")
    args = parser.parse_args()

    capture_root = Path(args.capture_root).resolve()
    device_dir = capture_root / sanitize_name(args.emitter_device_id) / sanitize_name(args.session_id)
    device_dir.mkdir(parents=True, exist_ok=True)

    capture_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    center_freq_hz = float(args.freq) * 1e6

    base_name = "iq_{}_{}_{}MHz_{}s".format(
        sanitize_name(args.emitter_device_id),
        sanitize_name(capture_id),
        "{:.6f}".format(args.freq),
        str(args.duration).replace(".", "_")
    )

    cfile_path = device_dir / (base_name + ".cfile")
    json_path = device_dir / (base_name + ".json")

    print("[INFO] Capture root: {}".format(capture_root))
    print("[INFO] Emitter device id: {}".format(args.emitter_device_id))
    print("[INFO] Session id: {}".format(args.session_id))
    print("[INFO] Frequency MHz: {:.6f}".format(args.freq))
    print("[INFO] Duration s: {}".format(args.duration))
    print("[INFO] Sample rate Hz: {}".format(args.sample_rate))
    print("[INFO] Output cfile: {}".format(cfile_path))

    tb = RFCapture(
        center_freq_hz=center_freq_hz,
        output_path=str(cfile_path),
        duration_s=args.duration,
        samp_rate=args.sample_rate,
        gain=args.gain,
        antenna=args.antenna,
        device_addr=args.device_addr,
        use_agc=args.use_agc,
    )

    time.sleep(args.settle_ms / 1000.0)

    tb.start()
    tb.wait()
    tb.stop()

    if not cfile_path.exists():
        raise RuntimeError("Capture failed, output file was not created")

    file_size_bytes = cfile_path.stat().st_size
    sample_count = int(file_size_bytes // 8)
    sha256 = sha256_file(cfile_path)

    metadata = {
        "id": capture_id,
        "generated_at_utc": utc_now_iso(),
        "capture_type": args.capture_type,
        "source_device": args.receiver_id,
        "receiver_id": args.receiver_id,
        "emitter_device_id": args.emitter_device_id,
        "session_id": args.session_id,
        "environment_id": args.environment_id,
        "label": args.label,
        "modulation_hint": args.modulation_hint,
        "notes": args.notes,
        "center_frequency_hz": center_freq_hz,
        "bandwidth_hz": args.sample_rate,
        "duration_seconds": float(args.duration),
        "sample_rate_hz": float(args.sample_rate),
        "sample_count": sample_count,
        "gain_db": None if args.use_agc else float(args.gain),
        "agc_enabled": bool(args.use_agc),
        "antenna": args.antenna,
        "device_addr": args.device_addr,
        "channel_index": 0,
        "iq_file": str(cfile_path),
        "metadata_file": str(json_path),
        "iq_format": "complex64_fc32_interleaved",
        "iq_dtype": "complex64",
        "byte_order": "native",
        "file_size_bytes": file_size_bytes,
        "sha256": sha256,
        "replay_parameters": {
            "center_frequency_hz": center_freq_hz,
            "sample_rate_hz": float(args.sample_rate),
            "gain_db": None if args.use_agc else float(args.gain),
            "antenna": args.antenna,
            "iq_format": "complex64_fc32_interleaved"
        },
        "ai_dataset_fields": [
            "emitter_device_id",
            "session_id",
            "receiver_id",
            "environment_id",
            "label",
            "modulation_hint",
            "center_frequency_hz",
            "bandwidth_hz",
            "sample_rate_hz",
            "duration_seconds",
            "iq_file",
            "sha256"
        ]
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print("[OK] CFILE saved: {}".format(cfile_path))
    print("[OK] JSON saved:  {}".format(json_path))
    print("[OK] SHA256:      {}".format(sha256))


if __name__ == "__main__":
    main()