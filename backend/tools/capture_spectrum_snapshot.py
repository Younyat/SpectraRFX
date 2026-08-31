#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

import numpy as np
from gnuradio import blocks
from gnuradio import gr
from gnuradio import uhd


def normalize_device_addr(device_addr: str) -> str:
    return str(device_addr).strip()


class SpectrumSnapshot(gr.top_block):
    def __init__(
        self,
        center_freq_hz: float,
        sample_rate_hz: float,
        gain_db: float,
        antenna: str,
        device_addr: str,
        sample_count: int,
        use_agc: bool,
    ):
        gr.top_block.__init__(self, "Spectrum Snapshot", catch_exceptions=True)

        self.source = uhd.usrp_source(
            normalize_device_addr(device_addr),
            uhd.stream_args(cpu_format="fc32", args="", channels=[0]),
        )
        self.source.set_samp_rate(float(sample_rate_hz))
        self.source.set_time_unknown_pps(uhd.time_spec(0))
        self.source.set_center_freq(float(center_freq_hz), 0)
        self.source.set_antenna(str(antenna), 0)

        if use_agc:
            try:
                self.source.set_rx_agc(True, 0)
            except Exception:
                pass
        else:
            try:
                self.source.set_gain(float(gain_db), 0)
            except TypeError:
                self.source.set_gain(float(gain_db))

        self.head = blocks.head(gr.sizeof_gr_complex, int(sample_count))
        self.sink = blocks.vector_sink_c()

        self.connect((self.source, 0), (self.head, 0))
        self.connect((self.head, 0), (self.sink, 0))


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture one real UHD spectrum snapshot as JSON.")
    parser.add_argument("--freq", type=float, required=True, help="Center frequency in MHz")
    parser.add_argument("--sample-rate", type=float, default=2e6)
    parser.add_argument("--gain", type=float, default=20.0)
    parser.add_argument("--antenna", type=str, default="RX2")
    parser.add_argument("--device-addr", type=str, default="")
    parser.add_argument("--fft-size", type=int, default=4096)
    parser.add_argument("--sample-count", type=int, default=65536)
    parser.add_argument("--use-agc", action="store_true")
    args = parser.parse_args()

    center_freq_hz = float(args.freq) * 1e6
    sample_rate_hz = float(args.sample_rate)
    fft_size = int(args.fft_size)

    tb = SpectrumSnapshot(
        center_freq_hz=center_freq_hz,
        sample_rate_hz=sample_rate_hz,
        gain_db=float(args.gain),
        antenna=args.antenna,
        device_addr=args.device_addr,
        sample_count=int(args.sample_count),
        use_agc=bool(args.use_agc),
    )
    tb.start()
    tb.wait()
    tb.stop()

    samples = np.asarray(tb.sink.data(), dtype=np.complex64)
    if samples.size < fft_size:
        raise RuntimeError(f"Not enough samples captured: {samples.size} < {fft_size}")

    samples = samples[-fft_size:]
    window = np.hanning(fft_size).astype(np.float32)
    spectrum = np.fft.fftshift(np.fft.fft(samples * window, n=fft_size))
    magnitudes = np.abs(spectrum) / max(float(np.sum(window)), 1.0)
    levels_db = 20.0 * np.log10(magnitudes + 1e-12)
    freqs = center_freq_hz + np.fft.fftshift(np.fft.fftfreq(fft_size, d=1.0 / sample_rate_hz))

    result = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "center_frequency_hz": center_freq_hz,
        "span_hz": sample_rate_hz,
        "start_frequency_hz": float(freqs[0]),
        "stop_frequency_hz": float(freqs[-1]),
        "sample_rate_hz": sample_rate_hz,
        "frequencies_hz": freqs.astype(float).tolist(),
        "levels_db": levels_db.astype(float).tolist(),
        "points": fft_size,
        "source": "uhd_gnuradio",
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
