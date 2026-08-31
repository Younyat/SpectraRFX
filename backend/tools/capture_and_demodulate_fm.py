#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from gnuradio import analog
from gnuradio import blocks
from gnuradio import filter
from gnuradio import gr
from gnuradio import uhd


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]+', "_", name)
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("._")


def normalize_device_addr(device_addr: str) -> str:
    return str(device_addr).strip()


def describe_uhd_lookup_failure(device_addr: str, error: Exception) -> str:
    device_addr = normalize_device_addr(device_addr)
    requested = device_addr or "<empty/default>"
    return (
        "UHD did not find a USRP device.\n"
        f"Requested device address: {requested}\n"
        f"UHD error: {error}\n\n"
        "Checks:\n"
        "  1. Run `uhd_find_devices` and confirm the radio is listed.\n"
        "  2. Run `uhd_usrp_probe` to confirm UHD can open it.\n"
        "  3. If more than one device is present, pass `--device-addr \"serial=<serial>\"`.\n"
        "  4. For network USRPs, pass `--device-addr \"addr=<ip>\"` and verify the host can reach that IP.\n"
        "  5. For USB B2xx devices on Windows, verify the USB cable, power, and installed UHD/USB driver."
    )


class CaptureAndDemodulateFM(gr.top_block):
    def __init__(
        self,
        center_freq_hz: float,
        iq_output_path: str,
        wav_output_path: str,
        duration_s: float,
        samp_rate: float = 2e6,
        gain: float = 20.0,
        antenna: str = "RX2",
        device_addr: str = "",
        use_agc: bool = False,
    ):
        gr.top_block.__init__(self, "Capture And Demodulate FM", catch_exceptions=True)

        self.center_freq_hz = float(center_freq_hz)
        self.iq_output_path = str(iq_output_path)
        self.wav_output_path = str(wav_output_path)
        self.duration_s = float(duration_s)
        self.samp_rate = float(samp_rate)
        self.gain = float(gain)
        self.antenna = str(antenna)
        self.device_addr = str(device_addr)
        self.use_agc = bool(use_agc)

        self.audio_rate = 48000
        self.quad_rate = 192000

        self.num_iq_samples = int(self.duration_s * self.samp_rate)
        self.num_audio_samples = int(self.duration_s * self.audio_rate)

        self.uhd_usrp_source_0 = uhd.usrp_source(
            normalize_device_addr(self.device_addr),
            uhd.stream_args(cpu_format="fc32", args="", channels=[0]),
        )
        self.uhd_usrp_source_0.set_samp_rate(self.samp_rate)
        self.uhd_usrp_source_0.set_time_unknown_pps(uhd.time_spec(0))
        self.uhd_usrp_source_0.set_center_freq(self.center_freq_hz, 0)
        self.uhd_usrp_source_0.set_antenna(self.antenna, 0)

        if self.use_agc:
            self.uhd_usrp_source_0.set_rx_agc(True, 0)
        else:
            try:
                self.uhd_usrp_source_0.set_gain(self.gain, 0)
            except TypeError:
                self.uhd_usrp_source_0.set_gain(self.gain)

        self.blocks_head_iq_0 = blocks.head(gr.sizeof_gr_complex, self.num_iq_samples)
        self.blocks_head_audio_0 = blocks.head(gr.sizeof_float, self.num_audio_samples)
        self.blocks_file_sink_iq_0 = blocks.file_sink(gr.sizeof_gr_complex, self.iq_output_path, False)
        self.blocks_file_sink_iq_0.set_unbuffered(False)
        self.rational_resampler_xxx_0 = filter.rational_resampler_ccc(
            interpolation=12,
            decimation=125,
            taps=[],
            fractional_bw=0,
        )
        self.analog_wfm_rcv_0 = analog.wfm_rcv(quad_rate=self.quad_rate, audio_decimation=4)
        self.blocks_wavfile_sink_0 = blocks.wavfile_sink(
            self.wav_output_path,
            1,
            self.audio_rate,
            blocks.FORMAT_WAV,
            blocks.FORMAT_PCM_16,
            False,
        )

        self.connect((self.uhd_usrp_source_0, 0), (self.blocks_head_iq_0, 0))
        self.connect((self.blocks_head_iq_0, 0), (self.blocks_file_sink_iq_0, 0))
        self.connect((self.uhd_usrp_source_0, 0), (self.rational_resampler_xxx_0, 0))
        self.connect((self.rational_resampler_xxx_0, 0), (self.analog_wfm_rcv_0, 0))
        self.connect((self.analog_wfm_rcv_0, 0), (self.blocks_head_audio_0, 0))
        self.connect((self.blocks_head_audio_0, 0), (self.blocks_wavfile_sink_0, 0))


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture IQ and WFM audio from UHD.")
    parser.add_argument("--freq", type=float, required=True, help="Frequency in MHz, for example 89.4")
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--sample-rate", type=float, default=2e6)
    parser.add_argument("--gain", type=float, default=20.0)
    parser.add_argument("--antenna", type=str, default="RX2")
    parser.add_argument("--device-addr", type=str, default="")
    parser.add_argument("--output-dir", type=str, default="captures")
    parser.add_argument("--base-name", type=str, default=None)
    parser.add_argument("--use-agc", action="store_true")
    parser.add_argument("--settle-ms", type=int, default=300)
    args = parser.parse_args()

    center_freq_hz = args.freq * 1e6
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    base_name = safe_filename(args.base_name or f"fm_{args.freq:.6f}MHz_{int(args.duration)}s")
    iq_path = output_dir / f"{base_name}.cfile"
    wav_path = output_dir / f"{base_name}.wav"
    meta_path = output_dir / f"{base_name}.json"

    try:
        tb = CaptureAndDemodulateFM(
            center_freq_hz=center_freq_hz,
            iq_output_path=str(iq_path),
            wav_output_path=str(wav_path),
            duration_s=args.duration,
            samp_rate=args.sample_rate,
            gain=args.gain,
            antenna=args.antenna,
            device_addr=args.device_addr,
            use_agc=args.use_agc,
        )
    except RuntimeError as exc:
        message = str(exc)
        if "No devices found" in message or "LookupError" in message:
            raise SystemExit(describe_uhd_lookup_failure(args.device_addr, exc)) from exc
        raise

    time.sleep(args.settle_ms / 1000.0)
    tb.start()
    tb.wait()
    tb.stop()

    metadata = {
        "generated_at_utc": utc_now_iso(),
        "capture_type": "simultaneous_iq_and_fm_audio",
        "center_freq_hz": center_freq_hz,
        "center_freq_mhz": args.freq,
        "duration_seconds": args.duration,
        "sample_rate_hz": args.sample_rate,
        "audio_rate_hz": 48000,
        "gain_db": None if args.use_agc else args.gain,
        "agc_enabled": bool(args.use_agc),
        "antenna": args.antenna,
        "device_addr": args.device_addr,
        "iq_file": str(iq_path),
        "iq_format": "complex64_fc32_interleaved",
        "wav_file": str(wav_path),
    }

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
