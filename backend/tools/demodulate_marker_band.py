#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from gnuradio import blocks
from gnuradio import gr
from gnuradio import uhd
from scipy import signal
from scipy.io import wavfile


ANALOG_MODES = {"am", "fm", "wfm", "nfm"}
DIGITAL_MODES = {"ask", "fsk", "psk", "ook"}


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]+', "_", name)
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("._")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_device_addr(device_addr: str) -> str:
    return str(device_addr).strip()


class FiniteIqCapture(gr.top_block):
    def __init__(
        self,
        center_freq_hz: float,
        iq_output_path: str,
        duration_s: float,
        sample_rate_hz: float,
        gain_db: float,
        antenna: str,
        device_addr: str,
    ):
        gr.top_block.__init__(self, "Finite Marker Band IQ Capture", catch_exceptions=True)
        sample_count = int(duration_s * sample_rate_hz)
        self.source = uhd.usrp_source(
            normalize_device_addr(device_addr),
            uhd.stream_args(cpu_format="fc32", args="", channels=[0]),
        )
        self.source.set_samp_rate(float(sample_rate_hz))
        self.source.set_time_unknown_pps(uhd.time_spec(0))
        self.source.set_center_freq(float(center_freq_hz), 0)
        self.source.set_antenna(str(antenna), 0)
        try:
            self.source.set_gain(float(gain_db), 0)
        except TypeError:
            self.source.set_gain(float(gain_db))

        self.head = blocks.head(gr.sizeof_gr_complex, sample_count)
        self.sink = blocks.file_sink(gr.sizeof_gr_complex, iq_output_path, False)
        self.sink.set_unbuffered(False)
        self.connect((self.source, 0), (self.head, 0))
        self.connect((self.head, 0), (self.sink, 0))


def normalize_audio(audio: np.ndarray) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float32)
    audio = audio - float(np.mean(audio))
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak <= 1e-12:
        return np.zeros(audio.shape, dtype=np.int16)
    audio = np.clip(audio / peak, -1.0, 1.0)
    return (audio * 32767.0).astype(np.int16)


def resample_audio(audio: np.ndarray, sample_rate_hz: float, audio_rate_hz: int) -> np.ndarray:
    gcd = math.gcd(int(round(sample_rate_hz)), int(audio_rate_hz))
    up = int(audio_rate_hz // gcd)
    down = int(round(sample_rate_hz) // gcd)
    return signal.resample_poly(audio, up, down)


def demodulate_audio(iq: np.ndarray, mode: str, sample_rate_hz: float, audio_rate_hz: int) -> np.ndarray:
    mode = mode.lower()
    if mode == "am":
        audio = np.abs(iq)
        sos = signal.butter(5, min(12_000.0, sample_rate_hz * 0.45), btype="lowpass", fs=sample_rate_hz, output="sos")
        audio = signal.sosfilt(sos, audio)
    elif mode in {"fm", "wfm", "nfm"}:
        phase = np.unwrap(np.angle(iq))
        audio = np.diff(phase, prepend=phase[0])
        cutoff = 15_000.0 if mode == "wfm" else 5_000.0
        sos = signal.butter(5, min(cutoff, sample_rate_hz * 0.45), btype="lowpass", fs=sample_rate_hz, output="sos")
        audio = signal.sosfilt(sos, audio)
    else:
        raise ValueError(f"Mode {mode} does not produce audio")

    return normalize_audio(resample_audio(audio, sample_rate_hz, audio_rate_hz))


def apply_marker_band_fir_filter(
    samples: np.ndarray,
    sample_rate_hz: float,
    selected_bandwidth_hz: float,
    stopband_attenuation_db: float,
    transition_width_hz: float | None = None,
) -> tuple[np.ndarray, dict]:
    if samples.size == 0:
        raise ValueError("Cannot filter an empty IQ capture")
    nyquist_hz = float(sample_rate_hz) / 2.0
    passband_edge_hz = float(selected_bandwidth_hz) / 2.0
    guard_hz = nyquist_hz - passband_edge_hz
    if guard_hz <= 0:
        raise ValueError("Cannot apply FIR filter: marker bandwidth reaches Nyquist. Increase sample rate or narrow M1-M2.")

    if transition_width_hz is None or transition_width_hz <= 0:
        transition_width_hz = max(guard_hz * 0.8, min(2_000.0, guard_hz))
    transition_hz = min(float(transition_width_hz), guard_hz * 0.95)
    transition_hz = max(transition_hz, max(sample_rate_hz / 100_000.0, 1.0))
    cutoff_hz = min(passband_edge_hz + transition_hz / 2.0, nyquist_hz * 0.999)
    numtaps, beta = signal.kaiserord(float(stopband_attenuation_db), max(transition_hz / nyquist_hz, 1e-6))
    numtaps = max(int(numtaps), 31)
    if numtaps % 2 == 0:
        numtaps += 1
    taps = signal.firwin(numtaps, cutoff_hz, window=("kaiser", beta), pass_zero="lowpass", fs=sample_rate_hz)
    filtered = signal.fftconvolve(samples.astype(np.complex64), taps.astype(np.float32), mode="same").astype(np.complex64)
    return filtered, {
        "enabled": True,
        "filter_type": "fir_kaiser_complex_baseband_lowpass",
        "reason": "Demodulation worker tunes the USRP to M1-M2 center; marker band maps to complex-baseband low-pass.",
        "sample_rate_hz": float(sample_rate_hz),
        "passband_width_hz": float(selected_bandwidth_hz),
        "passband_edge_hz": float(passband_edge_hz),
        "cutoff_hz": float(cutoff_hz),
        "transition_width_hz": float(transition_hz),
        "requested_stopband_attenuation_db": float(stopband_attenuation_db),
        "num_taps": int(numtaps),
        "window": "kaiser",
        "kaiser_beta": float(beta),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture and demodulate an RF marker band from UHD.")
    parser.add_argument("--start-hz", type=float, required=True)
    parser.add_argument("--stop-hz", type=float, required=True)
    parser.add_argument("--mode", type=str, required=True)
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--sample-rate", type=float, default=2e6)
    parser.add_argument("--gain", type=float, default=20.0)
    parser.add_argument("--antenna", type=str, default="RX2")
    parser.add_argument("--device-addr", type=str, default="")
    parser.add_argument("--output-dir", type=str, required=True)
    parser.add_argument("--base-name", type=str, default=None)
    parser.add_argument("--audio-rate", type=int, default=48_000)
    parser.add_argument("--settle-ms", type=int, default=300)
    parser.add_argument("--apply-bandpass-filter", action="store_true")
    parser.add_argument("--filter-stopband-attenuation-db", type=float, default=60.0)
    parser.add_argument("--filter-transition-width-hz", type=float, default=None)
    args = parser.parse_args()

    mode = args.mode.lower()
    if mode not in ANALOG_MODES | DIGITAL_MODES:
        raise ValueError(f"Unsupported demodulation mode: {args.mode}")
    if args.stop_hz <= args.start_hz:
        raise ValueError("stop-hz must be greater than start-hz")

    bandwidth_hz = args.stop_hz - args.start_hz
    center_freq_hz = args.start_hz + bandwidth_hz / 2.0
    sample_rate_hz = float(args.sample_rate)

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    base_name = safe_filename(args.base_name or f"demod_{mode}_{center_freq_hz / 1e6:.6f}MHz")
    iq_path = output_dir / f"{base_name}.cfile"
    wav_path = output_dir / f"{base_name}.wav"
    meta_path = output_dir / f"{base_name}.json"

    tb = FiniteIqCapture(
        center_freq_hz=center_freq_hz,
        iq_output_path=str(iq_path),
        duration_s=float(args.duration),
        sample_rate_hz=sample_rate_hz,
        gain_db=float(args.gain),
        antenna=args.antenna,
        device_addr=args.device_addr,
    )

    time.sleep(args.settle_ms / 1000.0)
    tb.start()
    tb.wait()
    tb.stop()

    iq = np.fromfile(iq_path, dtype=np.complex64)
    filter_metadata = {"enabled": False, "filter_type": None, "note": "No FIR marker-band filter was applied."}
    if args.apply_bandpass_filter:
        if args.filter_stopband_attenuation_db < 1 or args.filter_stopband_attenuation_db > 60:
            raise ValueError("filter-stopband-attenuation-db must be between 1 and 60 dB")
        iq, filter_metadata = apply_marker_band_fir_filter(
            iq,
            sample_rate_hz,
            bandwidth_hz,
            float(args.filter_stopband_attenuation_db),
            args.filter_transition_width_hz,
        )
        iq.astype(np.complex64).tofile(iq_path)
    audio_file = None
    audio_supported = mode in ANALOG_MODES
    if audio_supported:
        audio = demodulate_audio(iq, mode, sample_rate_hz, int(args.audio_rate))
        wavfile.write(wav_path, int(args.audio_rate), audio)
        audio_file = str(wav_path)

    metadata = {
        "generated_at_utc": utc_now_iso(),
        "mode": mode,
        "start_frequency_hz": args.start_hz,
        "stop_frequency_hz": args.stop_hz,
        "center_frequency_hz": center_freq_hz,
        "bandwidth_hz": bandwidth_hz,
        "duration_seconds": args.duration,
        "sample_rate_hz": sample_rate_hz,
        "gain_db": args.gain,
        "antenna": args.antenna,
        "device_addr": args.device_addr,
        "iq_file": str(iq_path),
        "audio_file": audio_file,
        "audio_supported": audio_supported,
        "audio_rate_hz": args.audio_rate if audio_supported else None,
        "marker_band_filter": filter_metadata,
        "notes": [
            "AM/FM/WFM/NFM generate WAV audio.",
            "ASK/FSK/PSK/OOK currently capture IQ and metadata for digital analysis/export.",
        ],
    }

    with open(meta_path, "w", encoding="utf-8") as file:
        json.dump(metadata, file, indent=2, ensure_ascii=False)

    print(json.dumps({**metadata, "metadata_file": str(meta_path)}), flush=True)


if __name__ == "__main__":
    main()
