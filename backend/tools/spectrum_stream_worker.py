#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time
from datetime import datetime, timezone

import numpy as np
from gnuradio import blocks
from gnuradio import gr
from gnuradio import uhd


def normalize_device_addr(device_addr: str) -> str:
    return str(device_addr).strip()


# LO-offset tuning: a real, measured B200/AD9361 hardware characteristic
# (direct-conversion/zero-IF front end), not a software bug -- see the
# README's "Center-frequency spectral artifact" section for the full
# investigation. Tuning the LO exactly to the frequency of interest (a bare
# float passed to set_center_freq) puts that residual LO-leakage/DC-offset
# spike right at the center of the displayed band. uhd.tune_request_t's
# (target_freq, lo_offset) form keeps the REPORTED/displayed center exactly
# at target_freq (UHD compensates with an internal digital mixer) while
# physically placing the LO -- and therefore the leakage -- lo_offset away
# from it, landing the artifact off to one side of the display instead of
# dead center. A quarter of the sample rate is a conventional, safe choice:
# far enough to clear the narrow (~20-25 kHz measured) artifact, not so far
# that the wanted band approaches the anti-aliasing filter's edge.
def _tune_request(center_freq_hz: float, sample_rate_hz: float):
    lo_offset_hz = sample_rate_hz * 0.25 if sample_rate_hz > 0 else 0.0
    return uhd.tune_request_t(center_freq_hz, lo_offset_hz)


class SpectrumStream(gr.top_block):
    def __init__(
        self,
        center_freq_hz: float,
        sample_rate_hz: float,
        gain_db: float,
        antenna: str,
        device_addr: str,
    ):
        gr.top_block.__init__(self, "Spectrum Stream", catch_exceptions=True)
        self.source = uhd.usrp_source(
            normalize_device_addr(device_addr),
            uhd.stream_args(cpu_format="fc32", args="", channels=[0]),
        )
        self.source.set_samp_rate(float(sample_rate_hz))
        self.source.set_time_unknown_pps(uhd.time_spec(0))
        self.source.set_center_freq(_tune_request(float(center_freq_hz), float(sample_rate_hz)), 0)
        self.source.set_antenna(str(antenna), 0)
        try:
            # Belt-and-suspenders alongside the LO-offset tune above (see
            # _tune_request docstring): UHD's own digital DC-offset
            # correction, tried first and confirmed NOT sufficient by itself
            # (2026-08-01 investigation, see README's "Center-frequency
            # spectral artifact" section) -- kept enabled anyway since it's
            # free and can only help with whatever residual remains.
            self.source.set_auto_dc_offset(True, 0)
        except Exception:
            pass
        try:
            self.source.set_gain(float(gain_db), 0)
        except TypeError:
            self.source.set_gain(float(gain_db))

        self.sink = blocks.vector_sink_c()
        self.connect((self.source, 0), (self.sink, 0))

    def set_center_frequency(self, center_freq_hz: float) -> None:
        self.source.set_center_freq(_tune_request(float(center_freq_hz), float(self.source.get_samp_rate())), 0)

    def set_sample_rate(self, sample_rate_hz: float) -> None:
        self.source.set_samp_rate(float(sample_rate_hz))

    def set_gain(self, gain_db: float) -> None:
        try:
            self.source.set_gain(float(gain_db), 0)
        except TypeError:
            self.source.set_gain(float(gain_db))


import base64

# BLE advertising band (channels 37/38/39 span roughly 2402-2480 MHz, with
# guard room to 2483.5 MHz for the full 2.4 GHz ISM band) -- burst detection
# below only ever runs when the CURRENT live tuning overlaps this range, so
# enabling "BLE live check" while looking at FM/WiFi/etc. never adds any
# per-frame cost at all (see _within_ble_band's call site in the main loop).
_BLE_BAND_START_HZ = 2_400_000_000.0
_BLE_BAND_STOP_HZ = 2_483_500_000.0


def _within_ble_band(center_freq_hz: float, sample_rate_hz: float) -> bool:
    tuned_start = center_freq_hz - sample_rate_hz / 2.0
    tuned_stop = center_freq_hz + sample_rate_hz / 2.0
    return tuned_start <= _BLE_BAND_STOP_HZ and tuned_stop >= _BLE_BAND_START_HZ


def _detect_energy_bursts(iq: np.ndarray, sample_rate_hz: float) -> list[tuple[int, int, float]]:
    """Lightweight, in-memory adaptation of ble_sdr_capture_worker.py's own
    detect_bursts() energy-threshold algorithm (median/MAD noise floor,
    block-power grouping) -- deliberately re-implemented here rather than
    imported, since that function is file(np.memmap)-oriented and used by the
    disk-based OFFLINE_REPLAY pipeline; duplicating ~10 lines of simple,
    stable math is lower-risk than forcing a shared dependency between a
    live-streaming worker and a disk-batch decode tool. Returns
    (start_sample, end_sample, peak_power_dbfs) tuples, strongest last.
    """
    block = max(64, int(sample_rate_hz / 100_000))
    count = len(iq) // block
    if count < 4:
        return []
    power = np.mean(np.abs(iq[: count * block].reshape(count, block)) ** 2, axis=1)
    noise = float(np.median(power))
    mad = float(np.median(np.abs(power - noise)))
    threshold = max(noise * 4.0, noise + 8.0 * mad, 1e-12)
    active = np.flatnonzero(power > threshold)
    if not active.size:
        return []
    groups = np.split(active, np.where(np.diff(active) > 2)[0] + 1)
    bursts = []
    for group in groups:
        if not len(group):
            continue
        start = max(0, (int(group[0]) - 2) * block)
        end = min(len(iq), (int(group[-1]) + 3) * block)
        peak_dbfs = float(10.0 * np.log10(max(float(np.max(power[group])), 1e-12)))
        bursts.append((start, end, peak_dbfs))
    bursts.sort(key=lambda item: item[2])
    return bursts


def next_power_of_two(value: int) -> int:
    return 1 << max(1, int(value - 1).bit_length())


def effective_fft_size(
    sample_rate_hz: float,
    requested_rbw_hz: float,
    fallback_fft_size: int,
    min_fft_size: int,
    max_fft_size: int,
) -> int:
    if requested_rbw_hz <= 0:
        return max(min_fft_size, min(fallback_fft_size, max_fft_size))
    hann_enbw_bins = 1.5
    target_size = math.ceil(sample_rate_hz * hann_enbw_bins / requested_rbw_hz)
    return max(min_fft_size, min(next_power_of_two(target_size), max_fft_size))


def smooth_video_bandwidth(
    levels_db: np.ndarray,
    previous_power: np.ndarray | None,
    vbw_hz: float,
    frame_interval_s: float,
) -> tuple[np.ndarray, np.ndarray]:
    current_power = np.power(10.0, levels_db / 10.0)
    if previous_power is None or previous_power.shape != current_power.shape or vbw_hz <= 0:
        return levels_db, current_power

    alpha = 1.0 - math.exp(-2.0 * math.pi * vbw_hz * frame_interval_s)
    alpha = min(max(alpha, 0.0), 1.0)
    smoothed_power = previous_power + alpha * (current_power - previous_power)
    smoothed_db = 10.0 * np.log10(smoothed_power + 1e-24)
    return smoothed_db, smoothed_power


def build_frame(
    samples: np.ndarray,
    center_freq_hz: float,
    sample_rate_hz: float,
    span_hz: float,
    fft_size: int,
    requested_rbw_hz: float,
    effective_rbw_hz: float,
    requested_vbw_hz: float,
    frame_interval_s: float,
    previous_video_power: np.ndarray | None,
    device_serial: str | None,
) -> tuple[dict, np.ndarray]:
    samples = samples[-fft_size:]
    window = np.hanning(fft_size).astype(np.float32)
    spectrum = np.fft.fftshift(np.fft.fft(samples * window, n=fft_size))
    magnitudes = np.abs(spectrum) / max(float(np.sum(window)), 1.0)
    levels_db = 20.0 * np.log10(magnitudes + 1e-12)
    # Smoothing operates on the full acquisition bandwidth (fft_size bins,
    # matching sample_rate_hz) so its shape stays stable across frames
    # regardless of the display span -- cropping to span_hz happens only
    # below, after smoothing, and never touches acquisition itself.
    levels_db, video_power = smooth_video_bandwidth(
        levels_db,
        previous_video_power,
        requested_vbw_hz,
        frame_interval_s,
    )
    freqs = center_freq_hz + np.fft.fftshift(np.fft.fftfreq(fft_size, d=1.0 / sample_rate_hz))
    # span_hz is a VIEW window into the real acquisition bandwidth
    # (sample_rate_hz) -- independent of it by design (see
    # RuntimeConfig/real_spectrum_stream.py's separate sample-rate control).
    # Never wider than what was actually sampled.
    display_span_hz = min(float(span_hz), float(sample_rate_hz))
    if display_span_hz < sample_rate_hz:
        keep = np.abs(freqs - center_freq_hz) <= display_span_hz / 2.0
        freqs = freqs[keep]
        levels_db = levels_db[keep]
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "center_frequency_hz": center_freq_hz,
        "span_hz": display_span_hz,
        "start_frequency_hz": float(freqs[0]),
        "stop_frequency_hz": float(freqs[-1]),
        "sample_rate_hz": sample_rate_hz,
        "frequencies_hz": freqs.astype(float).tolist(),
        "levels_db": levels_db.astype(float).tolist(),
        "points": int(freqs.size),
        "fft_size": fft_size,
        "requested_rbw_hz": requested_rbw_hz,
        "effective_rbw_hz": effective_rbw_hz,
        "requested_vbw_hz": requested_vbw_hz,
        "effective_vbw_hz": min(requested_vbw_hz, 0.5 / frame_interval_s),
        "source": "uhd_gnuradio_live",
        "power_unit": "dBFS",
        "calibration_id": None,
        "device_serial": device_serial,
    }, video_power


class RuntimeConfig:
    def __init__(
        self,
        center_freq_hz: float,
        sample_rate_hz: float,
        gain_db: float,
        fft_size: int,
        requested_rbw_hz: float,
        requested_vbw_hz: float,
        span_hz: float | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self.center_freq_hz = center_freq_hz
        self.sample_rate_hz = sample_rate_hz
        # Independent from sample_rate_hz by design: sample_rate_hz is the
        # real ADC/USRP acquisition rate (what a downstream decoder like
        # BLE's Gate 2A.2 actually needs correct); span_hz is only how much
        # of that acquired bandwidth gets displayed/analyzed (see
        # build_frame's display_span_hz cropping). Defaults to the full
        # acquisition bandwidth so behavior is unchanged unless a caller
        # deliberately requests a narrower view.
        self.span_hz = float(span_hz) if span_hz is not None else sample_rate_hz
        self.gain_db = gain_db
        self.fft_size = fft_size
        self.requested_rbw_hz = requested_rbw_hz
        self.requested_vbw_hz = requested_vbw_hz
        # Opt-in only (see BLE-RFFI Studio's "Live Monitor model check"
        # feature) -- off by default, so every existing use of this worker
        # (FM/WiFi/anything else) behaves exactly as before this field
        # existed. Toggled via the same "update" stdin command as every
        # other runtime setting, never a separate code path.
        self.ble_live_check_enabled = False
        # On-demand raw I/Q snapshot request (AI Research Plugin LIVE
        # inference, additive/opt-in): normally None. Set via the same
        # "update" command; consumed exactly once by take_pending_iq_snapshot_request()
        # so the main loop only starts accumulating a given request one time.
        self.iq_snapshot_request: dict | None = None

    def snapshot(self) -> tuple[float, float, float, float, int, float, float, bool]:
        with self._lock:
            return (
                self.center_freq_hz,
                self.sample_rate_hz,
                self.span_hz,
                self.gain_db,
                self.fft_size,
                self.requested_rbw_hz,
                self.requested_vbw_hz,
                self.ble_live_check_enabled,
            )

    def apply(self, update: dict) -> tuple[bool, str | None]:
        changed = False
        with self._lock:
            if "center_freq_hz" in update:
                value = float(update["center_freq_hz"])
                if value != self.center_freq_hz:
                    self.center_freq_hz = value
                    changed = True
            if "sample_rate_hz" in update:
                value = float(update["sample_rate_hz"])
                if value != self.sample_rate_hz:
                    self.sample_rate_hz = value
                    changed = True
            if "span_hz" in update:
                value = float(update["span_hz"])
                if value != self.span_hz:
                    self.span_hz = value
                    changed = True
            if "gain_db" in update:
                value = float(update["gain_db"])
                if value != self.gain_db:
                    self.gain_db = value
                    changed = True
            if "fft_size" in update:
                value = int(update["fft_size"])
                if value != self.fft_size:
                    self.fft_size = value
                    changed = True
            if "rbw_hz" in update:
                value = float(update["rbw_hz"])
                if value != self.requested_rbw_hz:
                    self.requested_rbw_hz = value
                    changed = True
            if "vbw_hz" in update:
                value = float(update["vbw_hz"])
                if value != self.requested_vbw_hz:
                    self.requested_vbw_hz = value
                    changed = True
            if "ble_live_check_enabled" in update:
                value = bool(update["ble_live_check_enabled"])
                if value != self.ble_live_check_enabled:
                    self.ble_live_check_enabled = value
                    changed = True
            if "iq_snapshot_request" in update:
                requested = update["iq_snapshot_request"]
                if requested is None:
                    self.iq_snapshot_request = None
                else:
                    # Hard cap independent of whatever the caller asked for
                    # -- this is raw complex64 held in memory and shipped
                    # over a JSON/base64 pipe; 2,000,000 samples is already
                    # generous (~16 MB raw) and far above any real model
                    # input size, just a defensive ceiling.
                    sample_count = max(1, min(int(requested["sample_count"]), 2_000_000))
                    self.iq_snapshot_request = {
                        "request_id": str(requested["request_id"]),
                        "sample_count": sample_count,
                    }
                changed = True
        return changed, None

    def take_pending_iq_snapshot_request(self) -> dict | None:
        """Atomically reads and clears a pending snapshot request so the
        main loop only ever starts accumulating a given request once, even
        though it polls this every cycle."""
        with self._lock:
            pending = self.iq_snapshot_request
            self.iq_snapshot_request = None
            return pending


def stdin_control_loop(config: RuntimeConfig) -> None:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue

        if message.get("command") != "update":
            continue

        _, error = config.apply(message)
        if error:
            print(json.dumps({"source": "real_sdr_error", "error": error}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Persistent UHD spectrum stream worker.")
    parser.add_argument("--freq", type=float, required=True, help="Center frequency in MHz")
    parser.add_argument("--sample-rate", type=float, default=2e6)
    parser.add_argument("--span-hz", type=float, default=None, help="Display span; defaults to --sample-rate (full acquisition bandwidth)")
    parser.add_argument("--gain", type=float, default=20.0)
    parser.add_argument("--antenna", type=str, default="RX2")
    parser.add_argument("--device-addr", type=str, default="")
    parser.add_argument("--fft-size", type=int, default=4096)
    parser.add_argument("--min-fft-size", type=int, default=256)
    parser.add_argument("--max-fft-size", type=int, default=65536)
    parser.add_argument("--rbw", type=float, default=10_000.0)
    parser.add_argument("--vbw", type=float, default=3_000.0)
    parser.add_argument("--fps", type=float, default=5.0)
    args = parser.parse_args()

    center_freq_hz = float(args.freq) * 1e6
    sample_rate_hz = float(args.sample_rate)
    interval = 1.0 / max(float(args.fps), 0.1)
    fft_size = effective_fft_size(
        sample_rate_hz=sample_rate_hz,
        requested_rbw_hz=float(args.rbw),
        fallback_fft_size=int(args.fft_size),
        min_fft_size=int(args.min_fft_size),
        max_fft_size=int(args.max_fft_size),
    )
    effective_rbw_hz = sample_rate_hz * 1.5 / float(fft_size)
    previous_video_power: np.ndarray | None = None
    runtime = RuntimeConfig(
        center_freq_hz=center_freq_hz,
        sample_rate_hz=sample_rate_hz,
        gain_db=float(args.gain),
        fft_size=fft_size,
        requested_rbw_hz=float(args.rbw),
        requested_vbw_hz=float(args.vbw),
        span_hz=float(args.span_hz) if args.span_hz is not None else None,
    )

    tb = SpectrumStream(
        center_freq_hz=center_freq_hz,
        sample_rate_hz=sample_rate_hz,
        gain_db=float(args.gain),
        antenna=args.antenna,
        device_addr=args.device_addr,
    )
    try:
        usrp_info = dict(tb.source.get_usrp_info(0))
        device_serial = str(usrp_info.get("mboard_serial") or usrp_info.get("serial") or "").strip() or None
    except Exception:
        device_serial = None

    tb.start()
    threading.Thread(target=stdin_control_loop, args=(runtime,), daemon=True).start()
    # Small 2-slot rolling window of raw IQ (this interval + the previous one)
    # purely for BLE burst detection below -- never touches the FFT path
    # above. Two slots (rather than just the current interval) so a burst
    # straddling an interval boundary is still fully contained in at least
    # one detection pass. Bounded by construction: at most 2x one interval's
    # worth of samples, the same data this loop already holds in memory for
    # the FFT every cycle.
    previous_iq_for_ble: np.ndarray | None = None
    # On-demand raw I/Q snapshot accumulator (AI Research Plugin LIVE
    # inference, additive/opt-in): None whenever no snapshot is in
    # progress -- every other code path in this loop is unaffected. Sized
    # to a real model's declared input, requested from the backend side
    # (see real_spectrum_stream.py's capture_live_iq_snapshot), never an
    # arbitrary open-ended capture.
    iq_snapshot_state: dict | None = None
    try:
        while True:
            time.sleep(interval)
            (
                center_freq_hz,
                sample_rate_hz,
                span_hz,
                gain_db,
                fft_size,
                requested_rbw_hz,
                requested_vbw_hz,
                ble_live_check_enabled,
            ) = runtime.snapshot()

            # Sample rate first: set_center_frequency() reads the CURRENT
            # sample rate off the source to size its LO offset (see
            # _tune_request), so it must see this cycle's rate, not last
            # cycle's.
            tb.set_sample_rate(sample_rate_hz)
            tb.set_center_frequency(center_freq_hz)
            tb.set_gain(gain_db)

            fft_size = effective_fft_size(
                sample_rate_hz=sample_rate_hz,
                requested_rbw_hz=requested_rbw_hz,
                fallback_fft_size=fft_size,
                min_fft_size=int(args.min_fft_size),
                max_fft_size=int(args.max_fft_size),
            )
            effective_rbw_hz = sample_rate_hz * 1.5 / float(fft_size)
            samples = np.asarray(tb.sink.data(), dtype=np.complex64)
            if samples.size < fft_size:
                continue

            frame, previous_video_power = build_frame(
                samples,
                center_freq_hz,
                sample_rate_hz,
                span_hz,
                fft_size,
                requested_rbw_hz,
                effective_rbw_hz,
                requested_vbw_hz,
                interval,
                previous_video_power,
                device_serial,
            )
            print(json.dumps(frame), flush=True)

            # Additive, opt-in only (AI Research Plugin LIVE inference):
            # skipped entirely (one cheap dict-is-None check) unless a
            # snapshot was actually requested from the backend side.
            # Accumulates this interval's real raw I/Q into the pending
            # request until enough samples exist, then emits exactly one
            # "iq_snapshot" frame and stops -- never a continuous stream.
            new_snapshot_request = runtime.take_pending_iq_snapshot_request()
            if new_snapshot_request is not None:
                iq_snapshot_state = {**new_snapshot_request, "chunks": [], "collected": 0}
            if iq_snapshot_state is not None:
                iq_snapshot_state["chunks"].append(samples)
                iq_snapshot_state["collected"] += int(samples.size)
                if iq_snapshot_state["collected"] >= iq_snapshot_state["sample_count"]:
                    snapshot_iq = np.concatenate(iq_snapshot_state["chunks"])[: iq_snapshot_state["sample_count"]]
                    print(json.dumps({
                        "source": "iq_snapshot",
                        "request_id": iq_snapshot_state["request_id"],
                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                        "center_frequency_hz": center_freq_hz,
                        "sample_rate_hz": sample_rate_hz,
                        "bandwidth_hz": sample_rate_hz,
                        "sample_format": "cf32_le",
                        "sample_count": int(snapshot_iq.size),
                        "iq_window_base64": base64.b64encode(snapshot_iq.astype(np.complex64).tobytes()).decode("ascii"),
                    }), flush=True)
                    iq_snapshot_state = None

            # Additive, opt-in only: skipped entirely (zero extra cost) unless
            # BLE live check is enabled AND the current tuning overlaps the
            # BLE band -- never runs while looking at FM/WiFi/anything else.
            if ble_live_check_enabled and _within_ble_band(center_freq_hz, sample_rate_hz):
                try:
                    ring = samples if previous_iq_for_ble is None else np.concatenate([previous_iq_for_ble, samples])
                    bursts = _detect_energy_bursts(ring, sample_rate_hz)
                    if bursts:
                        start, end, peak_dbfs = bursts[-1]
                        burst_iq = ring[start:end]
                        print(json.dumps({
                            "source": "ble_rffi_iq_burst",
                            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                            "center_frequency_hz": center_freq_hz,
                            "sample_rate_hz": sample_rate_hz,
                            "bandwidth_hz": sample_rate_hz,
                            "sample_format": "cf32_le",
                            "peak_power_dbfs": peak_dbfs,
                            "sample_count": int(end - start),
                            "iq_window_base64": base64.b64encode(burst_iq.astype(np.complex64).tobytes()).decode("ascii"),
                        }), flush=True)
                except Exception as exc:
                    print(json.dumps({"source": "ble_rffi_burst_detection_error", "error": str(exc)}), flush=True)
            previous_iq_for_ble = samples

            reset = getattr(tb.sink, "reset", None)
            if callable(reset):
                reset()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(json.dumps({"source": "real_sdr_error", "error": str(exc)}), flush=True)
        raise
    finally:
        tb.stop()
        tb.wait()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"spectrum_stream_worker failed: {exc}", file=sys.stderr, flush=True)
        raise
