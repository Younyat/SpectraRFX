#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from gnuradio import uhd


def normalize_device_addr(device_addr: str) -> str:
    return str(device_addr).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe a UHD/USRP device.")
    parser.add_argument("--device-addr", type=str, default="")
    parser.add_argument("--antenna", type=str, default="RX2")
    parser.add_argument("--sample-rate", type=float, default=2e6)
    parser.add_argument("--freq", type=float, default=89.4, help="Frequency in MHz")
    parser.add_argument("--gain", type=float, default=20.0)
    args = parser.parse_args()

    device_args = normalize_device_addr(args.device_addr)
    source = uhd.usrp_source(
        device_args,
        uhd.stream_args(cpu_format="fc32", args="", channels=[0]),
    )

    center_freq_hz = float(args.freq) * 1e6
    source.set_samp_rate(float(args.sample_rate))
    source.set_time_unknown_pps(uhd.time_spec(0))
    source.set_center_freq(center_freq_hz, 0)
    source.set_antenna(args.antenna, 0)
    try:
        source.set_gain(float(args.gain), 0)
    except TypeError:
        source.set_gain(float(args.gain))

    antennas = []
    try:
        antennas = list(source.get_antennas(0))
    except Exception:
        pass

    result = {
        "ok": True,
        "driver": "uhd_gnuradio",
        "device_args": args.device_addr,
        "antenna": args.antenna,
        "antennas": antennas,
        "center_frequency_hz": center_freq_hz,
        "sample_rate_hz": float(args.sample_rate),
        "gain_db": float(args.gain),
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
