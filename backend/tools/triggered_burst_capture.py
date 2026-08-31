#!/usr/bin/env python3
"""
triggered_burst_capture.py — Circular-buffer triggered IQ capture via GNU Radio.

Uses a GNU Radio uhd.usrp_source feeding a custom gr.sync_block that maintains a
pre-trigger ring buffer in memory.  When the trigger condition fires, the pre-trigger
IQ is already buffered — no burst start is ever missed.

Supports:
  * adaptive_energy_trigger  – rolling-percentile noise floor, fire on energy spike
  * smart_burst_trigger      – adds persistence check and saturation rejection
  * Multiple capture repetitions with cooldown between events
  * Per-event .iq/.cfile + .json metadata files with Auto-QC

Output (stdout, last line): JSON of the first QC-valid event (primary capture).
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

try:
    from gnuradio import gr, uhd
except Exception as _exc:
    sys.exit(
        f"GNU Radio / UHD not importable: {_exc}\n"
        "Run this script from the RadioConda environment."
    )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db10(linear: float) -> float:
    return 10.0 * float(np.log10(max(float(linear), 1e-20)))


def _safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]+', "_", name)
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name.strip("._") or "capture"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _log(msg: str) -> None:
    print(f"[TRIGGER] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Circular IQ block buffer
# ---------------------------------------------------------------------------

class _CircularBlockBuffer:
    """Keeps at most *max_samples* IQ samples across a deque of numpy blocks."""

    def __init__(self, max_samples: int) -> None:
        self._max = max(max_samples, 1)
        self._blocks: collections.deque[np.ndarray] = collections.deque()
        self._held = 0

    def push(self, block: np.ndarray) -> None:
        b = block.astype(np.complex64)
        self._blocks.append(b)
        self._held += b.size
        while self._held > self._max:
            excess = self._held - self._max
            oldest = self._blocks[0]
            if oldest.size <= excess and len(self._blocks) > 1:
                self._blocks.popleft()
                self._held -= oldest.size
                continue
            self._blocks[0] = oldest[excess:].astype(np.complex64, copy=False)
            self._held -= excess
            break

    def snapshot(self) -> np.ndarray:
        if not self._blocks:
            return np.zeros(0, dtype=np.complex64)
        raw = np.concatenate(list(self._blocks))
        return raw[-self._max:].astype(np.complex64)

    def reset(self, max_samples: int | None = None) -> None:
        self._blocks.clear()
        self._held = 0
        if max_samples is not None:
            self._max = max(max_samples, 1)


# ---------------------------------------------------------------------------
# Trigger strategies
# ---------------------------------------------------------------------------

class _AdaptiveEnergyTrigger:
    def __init__(self, threshold_db: float, sample_rate_hz: float,
                 noise_window_s: float = 1.0, noise_percentile: float = 20.0,
                 block_size: int = 1024) -> None:
        self._threshold_linear = 10.0 ** (threshold_db / 10.0)
        self._noise_percentile = noise_percentile
        window_blocks = max(int(noise_window_s * sample_rate_hz / block_size), 20)
        self._energy_hist: collections.deque[float] = collections.deque(maxlen=window_blocks)

    def update(self, block: np.ndarray) -> tuple[bool, float, float]:
        energy = float(np.mean(np.abs(block.astype(np.complex64)) ** 2))
        self._energy_hist.append(energy)
        if len(self._energy_hist) < 5:
            return False, _db10(energy), -999.0
        noise = float(np.percentile(list(self._energy_hist), self._noise_percentile))
        noise_db = _db10(max(noise, 1e-20))
        energy_db = _db10(max(energy, 1e-20))
        fired = energy > max(noise * self._threshold_linear, 1e-20)
        return fired, energy_db, noise_db

    def reset(self) -> None:
        self._energy_hist.clear()


class _SmartBurstTrigger(_AdaptiveEnergyTrigger):
    def __init__(self, threshold_db: float, sample_rate_hz: float,
                 min_persistence_ms: float = 10.0, saturation_level_db: float = -0.5,
                 **kwargs: object) -> None:
        super().__init__(threshold_db, sample_rate_hz, **kwargs)
        self._min_persistence_s = max(min_persistence_ms / 1000.0, 0.0)
        self._sat_power = 10.0 ** (saturation_level_db / 10.0)
        self._above_since: float | None = None

    def update(self, block: np.ndarray) -> tuple[bool, float, float]:
        b = block.astype(np.complex64)
        basic_fired, energy_db, noise_db = super().update(b)
        peak_power = float(np.max(np.abs(b) ** 2))
        if peak_power >= self._sat_power:
            self._above_since = None
            return False, energy_db, noise_db
        now = time.monotonic()
        if basic_fired:
            if self._above_since is None:
                self._above_since = now
            if (now - self._above_since) >= self._min_persistence_s:
                return True, energy_db, noise_db
        else:
            self._above_since = None
        return False, energy_db, noise_db

    def reset(self) -> None:
        super().reset()
        self._above_since = None


# ---------------------------------------------------------------------------
# Auto-QC
# ---------------------------------------------------------------------------

def _auto_qc(samples: np.ndarray, sample_rate_hz: float, snr_db: float,
              min_duration_s: float, max_duration_s: float,
              min_snr_db: float = 3.0, saturation_max_abs: float = 0.99,
              clipping_ratio_threshold: float = 0.40) -> dict:
    issues: list[str] = []
    s = samples.astype(np.complex64)
    duration_s = s.size / max(sample_rate_hz, 1.0)
    if duration_s < min_duration_s:
        issues.append(f"duration {duration_s:.4f}s < min {min_duration_s:.4f}s")
    if max_duration_s > 0 and duration_s > max_duration_s:
        issues.append(f"duration {duration_s:.4f}s > max {max_duration_s:.4f}s")
    if snr_db < min_snr_db:
        issues.append(f"SNR {snr_db:.1f} dB < min {min_snr_db:.1f} dB")
    max_abs = float(np.max(np.abs(s))) if s.size else 0.0
    if max_abs > saturation_max_abs:
        issues.append(f"possible saturation (max_abs={max_abs:.4f})")
    if s.size > 2:
        real_clip = float(np.mean(np.diff(s.real) == 0))
        imag_clip = float(np.mean(np.diff(s.imag) == 0))
        if max(real_clip, imag_clip) > clipping_ratio_threshold:
            issues.append(f"possible clipping (real={real_clip:.2f} imag={imag_clip:.2f})")
    if max_abs < 1e-12:
        issues.append("samples are near-zero")
    return {"passed": len(issues) == 0, "issues": issues,
            "duration_s": float(duration_s), "max_abs": float(max_abs), "snr_db": float(snr_db)}


# ---------------------------------------------------------------------------
# Per-event file writer
# ---------------------------------------------------------------------------

def _write_event(event_samples: np.ndarray, event_id: str, event_index: int,
                 output_dir: Path, base_name: str, file_format: str,
                 args: argparse.Namespace, center_freq_hz: float,
                 bandwidth_hz: float, sample_rate_hz: float,
                 trigger_info: dict, qc_result: dict, session_meta: dict) -> dict:
    ext = ".iq" if file_format == "iq" else ".cfile"
    iq_path = output_dir / f"{base_name}_ev{event_index:02d}{ext}"
    meta_path = output_dir / f"{base_name}_ev{event_index:02d}.json"
    event_samples.astype(np.complex64).tofile(iq_path)
    sha = _sha256(iq_path)
    label = (args.signal_type if (args.target_task == "signal_recognition" and args.signal_type)
             else args.label)
    metadata = {
        "id": event_id,
        "session_capture_id": args.capture_id,
        "event_index": event_index,
        "generated_at_utc": _utc_now(),
        "capture_type": "triggered_burst_event",
        "file_format": file_format,
        "source_device": "USRP-B200 from Ettus Research",
        "driver": "uhd_gnuradio",
        "label": label,
        "modulation_hint": args.modulation_hint,
        "notes": args.notes,
        "dataset_split": args.dataset_split,
        "session_id": args.session_id,
        "transmitter_id": args.transmitter_id,
        "transmitter_class": args.transmitter_class,
        "operator": args.operator,
        "environment": args.environment,
        "target_task": args.target_task,
        "signal_type": args.signal_type,
        "start_frequency_hz": float(args.start_hz),
        "stop_frequency_hz": float(args.stop_hz),
        "center_frequency_hz": float(center_freq_hz),
        "bandwidth_hz": float(bandwidth_hz),
        "duration_seconds": float(event_samples.size / sample_rate_hz),
        "requested_duration_seconds": None,
        "sample_rate_hz": float(sample_rate_hz),
        "sample_count": int(event_samples.size),
        "gain_db": float(args.gain),
        "antenna": args.antenna,
        "device_addr": args.device_addr,
        "channel_index": 0,
        "iq_file": str(iq_path),
        "metadata_file": str(meta_path),
        "iq_format": "complex64_fc32_interleaved",
        "file_extension": ext,
        "iq_dtype": "complex64",
        "byte_order": "native",
        "file_size_bytes": iq_path.stat().st_size,
        "sha256": sha,
        "marker_band_filter": {"enabled": False, "filter_type": None},
        "unfiltered_iq_file": None,
        "replay_parameters": {
            "center_frequency_hz": float(center_freq_hz),
            "sample_rate_hz": float(sample_rate_hz),
            "gain_db": float(args.gain),
            "antenna": args.antenna,
            "iq_format": "complex64_fc32_interleaved",
        },
        "ai_dataset_fields": ["label", "modulation_hint", "center_frequency_hz",
                              "bandwidth_hz", "sample_rate_hz", "duration_seconds",
                              "iq_file", "sha256"],
        "preview_metrics": {
            "live_preview_snr_db": args.live_preview_snr_db,
            "live_preview_noise_floor_db": args.live_preview_noise_floor_db,
            "live_preview_peak_level_db": args.live_preview_peak_level_db,
            "live_preview_peak_frequency_hz": args.live_preview_peak_frequency_hz,
        },
        "trigger_capture": {
            "mode": "triggered_burst",
            "strategy": args.trigger_strategy,
            "threshold_db": float(args.trigger_threshold_db),
            "pre_trigger_ms": float(args.pre_trigger_ms),
            "post_trigger_ms": float(args.post_trigger_ms),
            "trigger_max_wait_s": float(args.max_wait_seconds),
            "trigger_detected": True,
            "event_index": event_index,
            "session_events_requested": args.capture_repetitions,
            "session_events_captured": session_meta.get("events_captured", 1),
            "session_events_qc_passed": session_meta.get("events_qc_passed", 1),
            **trigger_info,
        },
        "auto_qc": qc_result,
    }
    with meta_path.open("w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=2, ensure_ascii=False)
    return metadata


# ---------------------------------------------------------------------------
# GNU Radio custom sink block — circular buffer + trigger + event saving
# ---------------------------------------------------------------------------

class _TriggerCaptureBlock(gr.sync_block):
    """
    GNU Radio sink block that maintains a pre-trigger circular buffer and runs
    trigger detection on each batch of samples delivered by the scheduler.
    All event saving happens inside work() on the GR scheduler thread.
    """

    def __init__(self, args: argparse.Namespace, sample_rate_hz: float,
                 center_freq_hz: float, bandwidth_hz: float,
                 output_dir: Path, base_name: str) -> None:
        gr.sync_block.__init__(self, name="trigger_capture",
                               in_sig=[np.complex64], out_sig=[])

        self._args = args
        self._sr = sample_rate_hz
        self._center = center_freq_hz
        self._bw = bandwidth_hz
        self._output_dir = output_dir
        self._base = base_name

        pre_samples = max(int(args.pre_trigger_ms / 1000.0 * sample_rate_hz), 0)
        self._post_target = max(int(args.post_trigger_ms / 1000.0 * sample_rate_hz), 1)
        self._min_event_s = max(args.min_event_duration_ms / 1000.0, 0.001)
        self._max_event_s = max(args.max_event_duration_ms / 1000.0,
                                self._min_event_s + 0.001)
        self._cooldown_s = max(args.cooldown_ms / 1000.0, 0.0)
        self._max_wait_s = float(args.max_wait_seconds)

        self._circ = _CircularBlockBuffer(max(pre_samples, 1024))

        trig_kwargs: dict = dict(
            threshold_db=float(args.trigger_threshold_db),
            sample_rate_hz=sample_rate_hz,
        )
        if args.trigger_strategy == "smart_burst_trigger":
            self._trigger: _AdaptiveEnergyTrigger = _SmartBurstTrigger(
                min_persistence_ms=float(args.smart_persistence_ms),
                **trig_kwargs,
            )
        else:
            self._trigger = _AdaptiveEnergyTrigger(**trig_kwargs)

        # Warmup: 1 second of noise history before arming
        self._warmup_target = int(sample_rate_hz * 1.0)
        self._warmup_count = 0

        self._state = "warmup"
        self._pre_snapshot: np.ndarray | None = None
        self._post_buffer: list[np.ndarray] = []
        self._post_collected = 0
        self._trigger_info: dict = {}
        self._wait_start = 0.0
        self._cooldown_end = 0.0
        self._event_index = 0
        self._captured_events: list[dict] = []

        self.done_event = threading.Event()

    # ------------------------------------------------------------------ work
    def work(self, input_items, output_items):  # type: ignore[override]
        block = input_items[0].copy()

        if self._state == "warmup":
            self._circ.push(block)
            self._trigger.update(block)
            self._warmup_count += block.size
            if self._warmup_count >= self._warmup_target:
                _log(f"Warmup done. Arming trigger (strategy={self._args.trigger_strategy}, "
                     f"threshold={self._args.trigger_threshold_db}dB, "
                     f"max_wait={self._max_wait_s}s).")
                self._state = "waiting"
                self._wait_start = time.monotonic()
                self._trigger.reset()

        elif self._state == "waiting":
            self._circ.push(block)
            elapsed = time.monotonic() - self._wait_start
            if elapsed > self._max_wait_s:
                _log(f"Event {self._event_index + 1}: timeout after {elapsed:.1f}s.")
                self._advance_or_done()
            else:
                fired, e_db, n_db = self._trigger.update(block)
                if fired:
                    snr = e_db - n_db
                    _log(f"Event {self._event_index + 1}: TRIGGER at +{elapsed:.3f}s "
                         f"energy={e_db:.1f}dB noise={n_db:.1f}dB SNR={snr:.1f}dB")
                    self._pre_snapshot = self._circ.snapshot()
                    self._trigger_info = {
                        "trigger_energy_db": float(e_db),
                        "noise_floor_db": float(n_db),
                        "snr_db": float(snr),
                        "trigger_timestamp_utc": _utc_now(),
                        "pre_trigger_samples": int(self._pre_snapshot.size),
                    }
                    self._post_buffer = []
                    self._post_collected = 0
                    self._state = "collecting"

        elif self._state == "collecting":
            self._post_buffer.append(block)
            self._post_collected += block.size
            if self._post_collected >= self._post_target:
                self._finalize_event()

        elif self._state == "cooldown":
            if time.monotonic() >= self._cooldown_end:
                _log(f"Cooldown done. Waiting for event {self._event_index + 1}.")
                self._state = "waiting"
                self._wait_start = time.monotonic()
                self._trigger.reset()
                self._circ.reset()

        # "done" — keep consuming so the GR scheduler doesn't stall
        return len(block)

    # ---------------------------------------------------------------- helpers
    def _finalize_event(self) -> None:
        post = (np.concatenate(self._post_buffer)[:self._post_target]
                .astype(np.complex64))
        pre = self._pre_snapshot if self._pre_snapshot is not None else np.zeros(0, np.complex64)
        event_samples = np.concatenate([pre, post]).astype(np.complex64)
        self._trigger_info["post_trigger_samples"] = int(post.size)

        snr_db = self._trigger_info.get("snr_db", 0.0)
        qc = _auto_qc(event_samples, self._sr, snr_db,
                      self._min_event_s, self._max_event_s)

        save_this = (not self._args.auto_qc_enabled) or qc["passed"]
        if not save_this:
            _log(f"Event {self._event_index + 1}: QC FAILED — {'; '.join(qc['issues'])}")
        else:
            n_captured = len(self._captured_events) + 1
            n_qc = n_captured  # all saved events passed (or qc disabled)
            session_meta = {"events_captured": n_captured, "events_qc_passed": n_qc}
            event_id = f"{self._args.capture_id}_ev{self._event_index:02d}"
            meta = _write_event(
                event_samples, event_id, self._event_index,
                self._output_dir, self._base, self._args.file_format,
                self._args, self._center, self._bw, self._sr,
                self._trigger_info, qc, session_meta,
            )
            self._captured_events.append(meta)
            _log(f"Event {self._event_index + 1}: saved → {meta['iq_file']}  "
                 f"dur={meta['duration_seconds']:.3f}s QC={'PASS' if qc['passed'] else 'SKIP'}")

        self._event_index += 1
        if self._event_index >= self._args.capture_repetitions:
            self._state = "done"
            self.done_event.set()
        else:
            self._cooldown_end = time.monotonic() + self._cooldown_s
            self._state = "cooldown"

    def _advance_or_done(self) -> None:
        self._event_index += 1
        if self._event_index >= self._args.capture_repetitions:
            self._state = "done"
            self.done_event.set()
        else:
            self._state = "waiting"
            self._wait_start = time.monotonic()
            self._trigger.reset()
            self._circ.reset()


# ---------------------------------------------------------------------------
# GNU Radio flowgraph
# ---------------------------------------------------------------------------

def _normalize_device_addr(device_addr: str) -> str:
    return str(device_addr).strip()


class _TriggerCaptureFlowgraph(gr.top_block):
    def __init__(self, args: argparse.Namespace, sample_rate_hz: float,
                 center_freq_hz: float, bandwidth_hz: float,
                 capture_block: _TriggerCaptureBlock) -> None:
        gr.top_block.__init__(self, "TriggerCapture", catch_exceptions=True)
        self.source = uhd.usrp_source(
            _normalize_device_addr(args.device_addr),
            uhd.stream_args(cpu_format="fc32", args="", channels=[0]),
        )
        self.source.set_samp_rate(float(sample_rate_hz))
        self.source.set_center_freq(float(center_freq_hz), 0)
        self.source.set_antenna(str(args.antenna), 0)
        try:
            self.source.set_gain(float(args.gain), 0)
        except TypeError:
            self.source.set_gain(float(args.gain))
        self.connect((self.source, 0), (capture_block, 0))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description="Circular-buffer triggered IQ capture via GNU Radio.")
    p.add_argument("--capture-id", required=True)
    p.add_argument("--start-hz", type=float, required=True)
    p.add_argument("--stop-hz", type=float, required=True)
    p.add_argument("--sample-rate", type=float, default=2e6)
    p.add_argument("--gain", type=float, default=20.0)
    p.add_argument("--antenna", type=str, default="RX2")
    p.add_argument("--device-addr", type=str, default="")
    p.add_argument("--output-dir", required=True)
    p.add_argument("--base-name", type=str, default=None)
    p.add_argument("--file-format", type=str, default="cfile", choices=["cfile", "iq"])
    p.add_argument("--label", type=str, default="")
    p.add_argument("--modulation-hint", type=str, default="unknown")
    p.add_argument("--notes", type=str, default="")
    p.add_argument("--dataset-split", type=str, default="train")
    p.add_argument("--session-id", type=str, default="")
    p.add_argument("--transmitter-id", type=str, default="")
    p.add_argument("--transmitter-class", type=str, default="")
    p.add_argument("--operator", type=str, default="")
    p.add_argument("--environment", type=str, default="")
    p.add_argument("--target-task", type=str, default="device_fingerprinting",
                   choices=["device_fingerprinting", "signal_recognition"])
    p.add_argument("--signal-type", type=str, default="")
    p.add_argument("--trigger-strategy", type=str, default="adaptive_energy_trigger",
                   choices=["adaptive_energy_trigger", "smart_burst_trigger"])
    p.add_argument("--trigger-threshold-db", type=float, default=6.0)
    p.add_argument("--pre-trigger-ms", type=float, default=50.0)
    p.add_argument("--post-trigger-ms", type=float, default=100.0)
    p.add_argument("--min-event-duration-ms", type=float, default=10.0)
    p.add_argument("--max-event-duration-ms", type=float, default=2000.0)
    p.add_argument("--cooldown-ms", type=float, default=500.0)
    p.add_argument("--max-wait-seconds", type=float, default=10.0)
    p.add_argument("--capture-repetitions", type=int, default=1)
    p.add_argument("--min-valid-events", type=int, default=1)
    p.add_argument("--smart-persistence-ms", type=float, default=10.0)
    p.add_argument("--auto-qc-enabled", action="store_true", default=True)
    p.add_argument("--no-auto-qc", dest="auto_qc_enabled", action="store_false")
    p.add_argument("--settle-ms", type=int, default=400)
    p.add_argument("--live-preview-snr-db", type=float, default=None)
    p.add_argument("--live-preview-noise-floor-db", type=float, default=None)
    p.add_argument("--live-preview-peak-level-db", type=float, default=None)
    p.add_argument("--live-preview-peak-frequency-hz", type=float, default=None)
    args = p.parse_args()

    if args.stop_hz <= args.start_hz:
        sys.exit("ERROR: stop-hz must be greater than start-hz")
    if args.capture_repetitions < 1:
        sys.exit("ERROR: capture-repetitions must be >= 1")

    bandwidth_hz = args.stop_hz - args.start_hz
    center_freq_hz = args.start_hz + bandwidth_hz / 2.0
    sample_rate_hz = float(args.sample_rate)

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    base = _safe_filename(
        args.base_name or f"triggered_{args.capture_id}_{center_freq_hz / 1e6:.4f}MHz"
    )

    _log(f"Initializing: fc={center_freq_hz/1e6:.4f}MHz fs={sample_rate_hz/1e6:.3f}Msps "
         f"gain={args.gain}dB ant={args.antenna} reps={args.capture_repetitions}")

    capture_block = _TriggerCaptureBlock(
        args, sample_rate_hz, center_freq_hz, bandwidth_hz, output_dir, base
    )
    tb = _TriggerCaptureFlowgraph(args, sample_rate_hz, center_freq_hz, bandwidth_hz, capture_block)

    _log(f"Settling {args.settle_ms}ms...")
    time.sleep(args.settle_ms / 1000.0)

    tb.start()
    _log("Flowgraph running.")

    # Total session timeout: max_wait * reps + cooldown * (reps-1) + 30s margin
    total_timeout = (
        args.max_wait_seconds * args.capture_repetitions
        + (args.cooldown_ms / 1000.0) * max(args.capture_repetitions - 1, 0)
        + 30.0
    )
    completed = capture_block.done_event.wait(timeout=total_timeout)

    tb.stop()
    tb.wait()

    if not completed:
        _log("Session timed out globally.")

    events = capture_block._captured_events
    valid_events = [e for e in events if e.get("auto_qc", {}).get("passed", True)]
    n_valid = len(valid_events)
    _log(f"Session done: {len(events)} event(s) captured, {n_valid} QC-valid.")

    if len(events) < args.min_valid_events:
        sys.exit(
            f"ERROR: Triggered capture produced {len(events)} event(s) but "
            f"min_valid_events={args.min_valid_events}. "
            "Increase max_wait_seconds, lower threshold_db, or verify signal presence."
        )

    primary = (valid_events or events)[0]
    primary["trigger_capture"]["session_events_captured"] = len(events)
    primary["trigger_capture"]["session_events_qc_passed"] = n_valid

    print(json.dumps(primary), flush=True)


if __name__ == "__main__":
    main()
