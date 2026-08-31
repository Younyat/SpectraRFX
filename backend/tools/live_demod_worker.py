#!/usr/bin/env python3
"""Continuous live demodulation worker.

Captures IQ from USRP via a custom GNU Radio sink block, demodulates in
real-time chunks, and writes PCM audio as JSON lines to stdout.
Control commands (stop, set_gain, set_freq, set_bpf) are read from stdin
as JSON lines.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import queue
import sys
import threading
import time

import numpy as np
from gnuradio import gr, uhd
from scipy import signal


AUDIO_MODES = {"am", "fm", "wfm", "nfm"}
DEFAULT_AUDIO_RATE = 48_000

# FIR filter taps for IQ bandpass — 201 gives ~1% transition bandwidth at
# typical SDR sample rates without measurable latency on modern hardware.
_BPF_NUMTAPS = 201


# ---------------------------------------------------------------------------
# Custom GNU Radio sink block
# ---------------------------------------------------------------------------

class _IQChunkSink(gr.sync_block):
    """Accumulates IQ samples into fixed-size chunks and feeds a queue."""

    def __init__(self, chunk_size: int, iq_queue: "queue.Queue[np.ndarray]") -> None:
        gr.sync_block.__init__(self, name="IQChunkSink", in_sig=[np.complex64], out_sig=None)
        self._chunk_size = chunk_size
        self._queue = iq_queue
        self._buf = np.empty(chunk_size, dtype=np.complex64)
        self._pos = 0

    def work(self, input_items, output_items):  # type: ignore[override]
        samples: np.ndarray = input_items[0]
        n_in = len(samples)
        i = 0
        while i < n_in:
            to_copy = min(self._chunk_size - self._pos, n_in - i)
            self._buf[self._pos : self._pos + to_copy] = samples[i : i + to_copy]
            self._pos += to_copy
            i += to_copy
            if self._pos == self._chunk_size:
                try:
                    self._queue.put_nowait(self._buf.copy())
                except queue.Full:
                    pass
                self._pos = 0
        return n_in


# ---------------------------------------------------------------------------
# GNU Radio flowgraph
# ---------------------------------------------------------------------------

class _LiveIqCapture(gr.top_block):

    def __init__(
        self,
        center_freq_hz: float,
        sample_rate_hz: float,
        gain_db: float,
        antenna: str,
        device_addr: str,
        chunk_size: int,
        iq_queue: "queue.Queue[np.ndarray]",
    ) -> None:
        gr.top_block.__init__(self, "LiveIqCapture", catch_exceptions=True)

        self.usrp = uhd.usrp_source(
            str(device_addr).strip(),
            uhd.stream_args(cpu_format="fc32", args="", channels=[0]),
        )
        self.usrp.set_samp_rate(float(sample_rate_hz))
        self.usrp.set_time_unknown_pps(uhd.time_spec(0))
        self.usrp.set_center_freq(float(center_freq_hz), 0)
        self.usrp.set_antenna(str(antenna), 0)
        try:
            self.usrp.set_gain(float(gain_db), 0)
        except TypeError:
            self.usrp.set_gain(float(gain_db))

        self._sink = _IQChunkSink(chunk_size, iq_queue)
        self.connect(self.usrp, self._sink)

    def set_gain(self, gain_db: float) -> None:
        try:
            self.usrp.set_gain(float(gain_db), 0)
        except Exception:
            pass

    def set_center_freq(self, center_hz: float) -> None:
        try:
            self.usrp.set_center_freq(float(center_hz), 0)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# IQ Band-Pass Filter
# ---------------------------------------------------------------------------

def _apply_iq_bpf(
    iq: np.ndarray,
    low_hz: float,
    high_hz: float,
    fs: float,
) -> np.ndarray:
    """Band-pass filter complex baseband IQ data.

    low_hz / high_hz are signed offsets from the carrier (0 Hz in IQ space).
    Uses a linear-phase FIR (Hamming window) for flat passband and controlled
    roll-off.  For off-centre passbands the signal is frequency-shifted,
    low-pass filtered, then shifted back — equivalent to a complex BPF.
    """
    bw = (high_hz - low_hz) / 2.0          # half-bandwidth
    fc = (low_hz + high_hz) / 2.0          # passband centre offset

    if bw < 100.0 or bw >= fs / 2.0:       # degenerate range — bypass
        return iq

    nyq = fs / 2.0
    cutoff = min(max(bw / nyq, 1e-4), 0.499)
    numtaps = min(_BPF_NUMTAPS, max(11, len(iq) // 4 | 1))
    h = signal.firwin(numtaps, cutoff, window="hamming")

    if abs(fc) < 1.0:
        # Symmetric: apply real FIR to both I and Q channels independently
        re = signal.lfilter(h, 1.0, iq.real).astype(np.float32)
        im = signal.lfilter(h, 1.0, iq.imag).astype(np.float32)
        return (re + 1j * im).astype(np.complex64)
    else:
        # Asymmetric: frequency-shift to DC, low-pass, shift back
        t = np.arange(len(iq), dtype=np.float64) / fs
        mix_dn = np.exp(-2j * np.pi * fc * t).astype(np.complex64)
        shifted = iq * mix_dn
        re = signal.lfilter(h, 1.0, shifted.real).astype(np.float32)
        im = signal.lfilter(h, 1.0, shifted.imag).astype(np.float32)
        filtered = (re + 1j * im).astype(np.complex64)
        mix_up = np.exp(2j * np.pi * fc * t).astype(np.complex64)
        return (filtered * mix_up).astype(np.complex64)


# ---------------------------------------------------------------------------
# Demodulation
# ---------------------------------------------------------------------------

def _demodulate(
    iq: np.ndarray,
    mode: str,
    sample_rate_hz: float,
    audio_rate: int,
    bpf_low_hz: float | None = None,
    bpf_high_hz: float | None = None,
) -> np.ndarray:
    mode = mode.lower()

    # Pre-demodulation band-pass filter (channel selection / interference rejection)
    if bpf_low_hz is not None and bpf_high_hz is not None:
        iq = _apply_iq_bpf(iq, bpf_low_hz, bpf_high_hz, sample_rate_hz)

    if mode == "am":
        audio = np.abs(iq).astype(np.float32)
        sos = signal.butter(
            5, min(10_000.0, sample_rate_hz * 0.45),
            btype="lowpass", fs=sample_rate_hz, output="sos",
        )
        audio = signal.sosfilt(sos, audio).astype(np.float32)
    elif mode in {"fm", "wfm", "nfm"}:
        phase = np.unwrap(np.angle(iq))
        audio = np.diff(phase.astype(np.float64), prepend=phase[0]).astype(np.float32)
        cutoff = 15_000.0 if mode == "wfm" else 5_000.0
        sos = signal.butter(
            5, min(cutoff, sample_rate_hz * 0.45),
            btype="lowpass", fs=sample_rate_hz, output="sos",
        )
        audio = signal.sosfilt(sos, audio).astype(np.float32)
    else:
        return np.zeros(audio_rate, dtype=np.int16)

    # Resample to target audio rate
    gcd = math.gcd(int(round(sample_rate_hz)), int(audio_rate))
    up = int(audio_rate // gcd)
    down = int(round(sample_rate_hz) // gcd)
    audio = signal.resample_poly(audio, up, down).astype(np.float32)

    # Normalize and convert to int16
    audio -= float(np.mean(audio))
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak <= 1e-12:
        return np.zeros(len(audio), dtype=np.int16)
    audio = np.clip(audio / peak, -1.0, 1.0)
    return (audio * 32767.0).astype(np.int16)


def _rms_db(pcm: np.ndarray) -> float:
    if pcm.size == 0:
        return -96.0
    rms = float(np.sqrt(np.mean(pcm.astype(np.float64) ** 2))) / 32768.0
    return float(20.0 * np.log10(max(rms, 1e-10)))


# ---------------------------------------------------------------------------
# JSON I/O helpers
# ---------------------------------------------------------------------------

def _emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def _stdin_reader(stop_event: threading.Event, cmd_queue: "queue.Queue[dict]") -> None:
    try:
        for raw in sys.stdin:
            raw = raw.strip()
            if not raw:
                continue
            try:
                cmd = json.loads(raw)
            except Exception:
                continue
            if cmd.get("cmd") == "stop":
                stop_event.set()
                return
            cmd_queue.put(cmd)
    except Exception:
        stop_event.set()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Continuous live audio demodulation worker")
    parser.add_argument("--center-hz",      type=float, required=True)
    parser.add_argument("--mode",           type=str,   required=True)
    parser.add_argument("--sample-rate",    type=float, default=2_000_000.0)
    parser.add_argument("--gain",           type=float, default=30.0)
    parser.add_argument("--antenna",        type=str,   default="RX2")
    parser.add_argument("--device-addr",    type=str,   default="")
    parser.add_argument("--chunk-duration", type=float, default=0.5)
    parser.add_argument("--audio-rate",     type=int,   default=DEFAULT_AUDIO_RATE)
    parser.add_argument("--settle-ms",      type=int,   default=300)
    parser.add_argument("--bpf-low-hz",     type=float, default=None)
    parser.add_argument("--bpf-high-hz",    type=float, default=None)
    args = parser.parse_args()

    mode = args.mode.lower()
    if mode not in AUDIO_MODES:
        _emit({"type": "error", "message": f"Mode {mode!r} not supported. Use: {sorted(AUDIO_MODES)}"})
        sys.exit(1)

    chunk_size = max(1, int(round(args.sample_rate * args.chunk_duration)))
    iq_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=10)
    cmd_queue: queue.Queue[dict] = queue.Queue()
    stop_event = threading.Event()

    # Mutable BPF state — updated via set_bpf stdin command
    bpf: dict = {"low_hz": args.bpf_low_hz, "high_hz": args.bpf_high_hz}

    try:
        tb = _LiveIqCapture(
            center_freq_hz=args.center_hz,
            sample_rate_hz=args.sample_rate,
            gain_db=args.gain,
            antenna=args.antenna,
            device_addr=args.device_addr,
            chunk_size=chunk_size,
            iq_queue=iq_queue,
        )
    except Exception as exc:
        _emit({"type": "error", "message": f"SDR init failed: {exc}"})
        sys.exit(1)

    stdin_thread = threading.Thread(
        target=_stdin_reader, args=(stop_event, cmd_queue), daemon=True
    )
    stdin_thread.start()

    try:
        tb.start()
        time.sleep(args.settle_ms / 1000.0)
        _emit({
            "type": "status",
            "message": "streaming",
            "center_hz": args.center_hz,
            "mode": mode,
            "sample_rate": args.sample_rate,
            "gain": args.gain,
            "chunk_duration": args.chunk_duration,
            "bpf_low_hz": bpf["low_hz"],
            "bpf_high_hz": bpf["high_hz"],
        })

        chunk_index = 0
        while not stop_event.is_set():
            # Process pending control commands
            while not cmd_queue.empty():
                try:
                    cmd = cmd_queue.get_nowait()
                    if cmd.get("cmd") == "set_gain":
                        tb.set_gain(float(cmd["gain"]))
                    elif cmd.get("cmd") == "set_freq":
                        tb.set_center_freq(float(cmd["center_hz"]))
                    elif cmd.get("cmd") == "set_bpf":
                        bpf["low_hz"] = cmd.get("bpf_low_hz")   # None disables BPF
                        bpf["high_hz"] = cmd.get("bpf_high_hz")
                except Exception:
                    pass

            # Get next IQ chunk
            try:
                iq = iq_queue.get(timeout=1.0)
            except queue.Empty:
                if not stop_event.is_set():
                    _emit({"type": "heartbeat", "chunk": chunk_index})
                continue

            try:
                pcm = _demodulate(
                    iq, mode, args.sample_rate, args.audio_rate,
                    bpf_low_hz=bpf["low_hz"],
                    bpf_high_hz=bpf["high_hz"],
                )
                _emit({
                    "type": "audio_chunk",
                    "chunk": chunk_index,
                    "pcm_b64": base64.b64encode(pcm.tobytes()).decode(),
                    "sample_rate": args.audio_rate,
                    "samples": int(pcm.size),
                    "duration_s": float(pcm.size) / args.audio_rate,
                    "rms_db": _rms_db(pcm),
                })
                chunk_index += 1
            except Exception as exc:
                _emit({"type": "error", "message": f"Demodulation error: {exc}"})

    except KeyboardInterrupt:
        pass
    except Exception as exc:
        _emit({"type": "error", "message": f"Worker fatal error: {exc}"})
    finally:
        try:
            tb.stop()
            tb.wait()
        except Exception:
            pass
        _emit({"type": "status", "message": "stopped"})


if __name__ == "__main__":
    main()
