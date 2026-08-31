#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from gnuradio import blocks
from gnuradio import gr
from gnuradio import uhd


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]+', "_", name)
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("._")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_device_addr(device_addr: str) -> str:
    return str(device_addr).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def db10(value: float) -> float:
    return 10.0 * np.log10(max(float(value), 1e-20))


def apply_marker_band_fir_filter(
    samples: np.ndarray,
    sample_rate_hz: float,
    selected_bandwidth_hz: float,
    stopband_attenuation_db: float,
    transition_width_hz: float | None = None,
) -> tuple[np.ndarray, dict]:
    """Apply a real FIR low-pass filter to complex baseband marker-band IQ.

    The USRP is tuned to the marker-band center frequency, therefore the RF
    marker interval maps to a complex-baseband low-pass passband.
    """
    if samples.size == 0:
        raise ValueError("Cannot filter an empty IQ capture")
    if sample_rate_hz <= 0 or selected_bandwidth_hz <= 0:
        raise ValueError("sample_rate_hz and selected_bandwidth_hz must be positive")

    nyquist_hz = float(sample_rate_hz) / 2.0
    passband_edge_hz = float(selected_bandwidth_hz) / 2.0
    guard_hz = nyquist_hz - passband_edge_hz
    if guard_hz <= 0:
        raise ValueError(
            "Cannot apply marker-band FIR filter: selected bandwidth reaches or exceeds Nyquist. "
            "Increase sample rate or reduce Marker 1-2 bandwidth."
        )

    try:
        from scipy import signal
    except Exception as exc:  # pragma: no cover - depends on runtime env
        raise RuntimeError("SciPy is required for real FIR marker-band filtering") from exc

    requested_transition_hz = transition_width_hz
    if requested_transition_hz is None or requested_transition_hz <= 0:
        requested_transition_hz = max(guard_hz * 0.8, min(2_000.0, guard_hz))
    transition_hz = min(float(requested_transition_hz), guard_hz * 0.95)
    transition_hz = max(transition_hz, max(sample_rate_hz / 100_000.0, 1.0))
    cutoff_hz = min(passband_edge_hz + transition_hz / 2.0, nyquist_hz * 0.999)
    normalized_transition = max(transition_hz / nyquist_hz, 1e-6)
    numtaps, beta = signal.kaiserord(float(stopband_attenuation_db), normalized_transition)
    numtaps = max(int(numtaps), 31)
    if numtaps % 2 == 0:
        numtaps += 1
    taps = signal.firwin(
        numtaps,
        cutoff_hz,
        window=("kaiser", beta),
        pass_zero="lowpass",
        fs=float(sample_rate_hz),
    )
    filtered = signal.fftconvolve(samples.astype(np.complex64), taps.astype(np.float32), mode="same").astype(np.complex64)
    stopband_start_hz = min(passband_edge_hz + transition_hz, nyquist_hz)
    metadata = {
        "enabled": True,
        "filter_type": "fir_kaiser_complex_baseband_lowpass",
        "reason": "USRP is tuned to marker-band center; Marker 1-2 maps to baseband low-pass.",
        "sample_rate_hz": float(sample_rate_hz),
        "passband_width_hz": float(selected_bandwidth_hz),
        "passband_edge_hz": float(passband_edge_hz),
        "cutoff_hz": float(cutoff_hz),
        "transition_width_hz": float(transition_hz),
        "stopband_start_hz": float(stopband_start_hz),
        "requested_stopband_attenuation_db": float(stopband_attenuation_db),
        "num_taps": int(numtaps),
        "window": "kaiser",
        "kaiser_beta": float(beta),
        "implementation": "scipy.signal.firwin + scipy.signal.fftconvolve(mode='same')",
    }
    return filtered, metadata


def find_first_burst(
    samples: np.ndarray,
    sample_rate_hz: float,
    threshold_db: float,
    pre_trigger_ms: float,
    post_trigger_ms: float,
) -> tuple[int, int] | None:
    if samples.size == 0 or sample_rate_hz <= 0:
        return None

    power = np.abs(samples) ** 2
    noise_power = float(np.percentile(power, 20))
    threshold_power = max(noise_power * (10.0 ** (threshold_db / 10.0)), 1e-20)
    window = int(min(max(sample_rate_hz * 0.0005, 64), 4096))
    kernel = np.ones(window, dtype=np.float64) / window
    smoothed = np.convolve(power.astype(np.float64), kernel, mode="same")
    mask = smoothed > threshold_power
    if not np.any(mask):
      return None

    indices = np.flatnonzero(mask)
    trigger_index = int(indices[0])
    release_index = int(indices[-1])
    pre_samples = max(0, int((pre_trigger_ms / 1000.0) * sample_rate_hz))
    post_samples = max(0, int((post_trigger_ms / 1000.0) * sample_rate_hz))
    start_index = max(0, trigger_index - pre_samples)
    end_index = min(samples.size - 1, release_index + post_samples)
    return start_index, end_index


class FiniteMarkerBandCapture(gr.top_block):
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture marker-limited IQ from UHD for modulation analysis.")
    parser.add_argument("--capture-id", type=str, required=True)
    parser.add_argument("--start-hz", type=float, required=True)
    parser.add_argument("--stop-hz", type=float, required=True)
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--sample-rate", type=float, default=2e6)
    parser.add_argument("--gain", type=float, default=20.0)
    parser.add_argument("--antenna", type=str, default="RX2")
    parser.add_argument("--device-addr", type=str, default="")
    parser.add_argument("--output-dir", type=str, required=True)
    parser.add_argument("--base-name", type=str, default=None)
    parser.add_argument("--file-format", type=str, default="cfile", choices=["cfile", "iq"])
    parser.add_argument("--label", type=str, default="")
    parser.add_argument("--modulation-hint", type=str, default="unknown")
    parser.add_argument("--notes", type=str, default="")
    parser.add_argument("--dataset-split", type=str, default="train")
    parser.add_argument("--session-id", type=str, default="")
    parser.add_argument("--transmitter-id", type=str, default="")
    parser.add_argument("--transmitter-class", type=str, default="")
    parser.add_argument("--operator", type=str, default="")
    parser.add_argument("--environment", type=str, default="")
    parser.add_argument("--live-preview-snr-db", type=float, default=None)
    parser.add_argument("--live-preview-noise-floor-db", type=float, default=None)
    parser.add_argument("--live-preview-peak-level-db", type=float, default=None)
    parser.add_argument("--live-preview-peak-frequency-hz", type=float, default=None)
    parser.add_argument("--capture-mode", type=str, default="immediate", choices=["immediate", "triggered_burst"])
    parser.add_argument("--trigger-threshold-db", type=float, default=6.0)
    parser.add_argument("--pre-trigger-ms", type=float, default=0.0)
    parser.add_argument("--post-trigger-ms", type=float, default=50.0)
    parser.add_argument("--trigger-max-wait-s", type=float, default=5.0)
    parser.add_argument("--settle-ms", type=int, default=300)
    parser.add_argument("--apply-bandpass-filter", action="store_true")
    parser.add_argument("--filter-stopband-attenuation-db", type=float, default=60.0)
    parser.add_argument("--filter-transition-width-hz", type=float, default=None)
    parser.add_argument("--keep-unfiltered-copy", action="store_true")
    args = parser.parse_args()

    if args.stop_hz <= args.start_hz:
        raise ValueError("stop-hz must be greater than start-hz")
    if args.duration <= 0:
        raise ValueError("duration must be greater than zero")

    bandwidth_hz = args.stop_hz - args.start_hz
    center_freq_hz = args.start_hz + bandwidth_hz / 2.0
    sample_rate_hz = float(args.sample_rate)
    requested_duration_s = float(args.duration)
    capture_horizon_s = requested_duration_s
    if args.capture_mode == "triggered_burst":
        capture_horizon_s = max(
            requested_duration_s,
            float(args.trigger_max_wait_s) + (float(args.pre_trigger_ms) + float(args.post_trigger_ms)) / 1000.0 + 0.25,
        )

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    base_name = safe_filename(args.base_name or f"iq_{args.capture_id}_{center_freq_hz / 1e6:.6f}MHz")
    extension = ".iq" if args.file_format == "iq" else ".cfile"
    iq_path = output_dir / f"{base_name}{extension}"
    meta_path = output_dir / f"{base_name}.json"

    tb = FiniteMarkerBandCapture(
        center_freq_hz=center_freq_hz,
        iq_output_path=str(iq_path),
        duration_s=capture_horizon_s,
        sample_rate_hz=sample_rate_hz,
        gain_db=float(args.gain),
        antenna=args.antenna,
        device_addr=args.device_addr,
    )

    time.sleep(args.settle_ms / 1000.0)
    tb.start()
    tb.wait()
    tb.stop()

    raw_samples = np.fromfile(iq_path, dtype=np.complex64)
    actual_duration_s = capture_horizon_s
    trigger_result = {
        "mode": args.capture_mode,
        "threshold_db": float(args.trigger_threshold_db),
        "pre_trigger_ms": float(args.pre_trigger_ms),
        "post_trigger_ms": float(args.post_trigger_ms),
        "trigger_max_wait_s": float(args.trigger_max_wait_s),
        "trigger_detected": False,
    }

    if args.capture_mode == "triggered_burst":
        bounds = find_first_burst(
            raw_samples,
            sample_rate_hz,
            float(args.trigger_threshold_db),
            float(args.pre_trigger_ms),
            float(args.post_trigger_ms),
        )
        if bounds is None:
            raise RuntimeError(
                "Triggered burst capture did not detect activity above threshold. "
                "Increase trigger_max_wait_s, reduce threshold_db, or verify the signal is present."
            )
        burst_start, burst_end = bounds
        cropped = raw_samples[burst_start:burst_end + 1]
        cropped.astype(np.complex64).tofile(iq_path)
        raw_samples = cropped
        actual_duration_s = raw_samples.size / sample_rate_hz
        trigger_result.update(
            {
                "trigger_detected": True,
                "burst_start_sample": int(burst_start),
                "burst_end_sample": int(burst_end),
                "captured_duration_s": float(actual_duration_s),
            }
        )

    filter_metadata = {
        "enabled": False,
        "filter_type": None,
        "note": "No post-capture FIR marker-band filter was applied.",
    }
    unfiltered_iq_path = None
    if args.apply_bandpass_filter:
        if args.filter_stopband_attenuation_db < 1 or args.filter_stopband_attenuation_db > 60:
            raise ValueError("filter-stopband-attenuation-db must be between 1 and 60 dB")
        if args.keep_unfiltered_copy:
            unfiltered_iq_path = iq_path.with_name(f"{iq_path.stem}.unfiltered{iq_path.suffix}")
            raw_samples.astype(np.complex64).tofile(unfiltered_iq_path)
        raw_samples, filter_metadata = apply_marker_band_fir_filter(
            raw_samples,
            sample_rate_hz,
            bandwidth_hz,
            float(args.filter_stopband_attenuation_db),
            args.filter_transition_width_hz,
        )
        raw_samples.astype(np.complex64).tofile(iq_path)
        sample_count = int(raw_samples.size)

    sample_count = int(raw_samples.size)
    metadata = {
        "id": args.capture_id,
        "generated_at_utc": utc_now_iso(),
        "capture_type": "marker_band_iq",
        "file_format": args.file_format,
        "source_device": "USRP-B200 from Ettus Research",
        "driver": "uhd_gnuradio",
        "label": args.label,
        "modulation_hint": args.modulation_hint,
        "notes": args.notes,
        "dataset_split": args.dataset_split,
        "session_id": args.session_id,
        "transmitter_id": args.transmitter_id,
        "transmitter_class": args.transmitter_class,
        "operator": args.operator,
        "environment": args.environment,
        "start_frequency_hz": args.start_hz,
        "stop_frequency_hz": args.stop_hz,
        "center_frequency_hz": center_freq_hz,
        "bandwidth_hz": bandwidth_hz,
        "duration_seconds": actual_duration_s,
        "requested_duration_seconds": requested_duration_s,
        "sample_rate_hz": sample_rate_hz,
        "sample_count": sample_count,
        "gain_db": args.gain,
        "antenna": args.antenna,
        "device_addr": args.device_addr,
        "channel_index": 0,
        "iq_file": str(iq_path),
        "metadata_file": str(meta_path),
        "iq_format": "complex64_fc32_interleaved",
        "file_extension": extension,
        "iq_dtype": "complex64",
        "byte_order": "native",
        "file_size_bytes": iq_path.stat().st_size,
        "sha256": sha256_file(iq_path),
        "marker_band_filter": filter_metadata,
        "unfiltered_iq_file": str(unfiltered_iq_path) if unfiltered_iq_path else None,
        "replay_parameters": {
            "center_frequency_hz": center_freq_hz,
            "sample_rate_hz": sample_rate_hz,
            "gain_db": args.gain,
            "antenna": args.antenna,
            "iq_format": "complex64_fc32_interleaved",
        },
        "ai_dataset_fields": [
            "label",
            "modulation_hint",
            "center_frequency_hz",
            "bandwidth_hz",
            "sample_rate_hz",
            "duration_seconds",
            "iq_file",
            "sha256",
        ],
        "preview_metrics": {
            "live_preview_snr_db": args.live_preview_snr_db,
            "live_preview_noise_floor_db": args.live_preview_noise_floor_db,
            "live_preview_peak_level_db": args.live_preview_peak_level_db,
            "live_preview_peak_frequency_hz": args.live_preview_peak_frequency_hz,
        },
        "trigger_capture": trigger_result,
    }

    with meta_path.open("w", encoding="utf-8") as file:
        json.dump(metadata, file, indent=2, ensure_ascii=False)

    print(json.dumps(metadata), flush=True)


if __name__ == "__main__":
    main()
