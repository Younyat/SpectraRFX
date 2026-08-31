from __future__ import annotations

import json
import os
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

import asyncio

from app.config.settings import settings as app_settings
from app.infrastructure.sdr.real_spectrum_stream import real_spectrum_stream
from app.infrastructure.sdr.rf_safety import validate_gain, validate_sample_rate

_AUDIO_MODES = {"am", "fm", "nfm", "wfm"}
_MAX_BUFFER_CHUNKS = 300  # ~2.5 min at 0.5 s chunks


class LiveDemodulationController:
    """Manages a continuous live audio demodulation worker subprocess.

    Completely independent from DemodulationController — shares only the
    exclusive SDR lock (real_spectrum_stream) to prevent device conflicts.
    """

    def __init__(self, settings) -> None:
        self._settings = settings
        self._worker: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._state: dict = {"status": "idle"}
        self._was_streaming = False
        self._chunks: list[dict] = []
        self._chunks_lock = threading.Lock()
        self._reader_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_status(self) -> dict:
        with self._lock:
            return dict(self._state)

    def start(
        self,
        center_hz: float,
        mode: str,
        sample_rate_hz: float,
        gain_db: float,
        chunk_duration: float = 0.5,
        bpf_low_hz: float | None = None,
        bpf_high_hz: float | None = None,
    ) -> dict:
        mode = mode.lower()
        if mode not in _AUDIO_MODES:
            raise ValueError(f"mode must be one of {sorted(_AUDIO_MODES)}")
        validate_gain(gain_db)
        validate_sample_rate(sample_rate_hz)
        if chunk_duration < 0.1 or chunk_duration > 5.0:
            raise ValueError("chunk_duration must be between 0.1 and 5.0 seconds")

        # Validate BPF range when provided
        if bpf_low_hz is not None and bpf_high_hz is not None:
            if bpf_high_hz <= bpf_low_hz:
                raise ValueError("bpf_high_hz must be greater than bpf_low_hz")

        with self._lock:
            self._stop_worker_locked()

            backend_root = app_settings.storage.app_root.parent
            script = backend_root / "tools" / "live_demod_worker.py"
            python_exe = os.environ.get("RADIOCONDA_PYTHON", r"C:\Users\Usuario\radioconda\python.exe")

            cmd = [
                python_exe, str(script),
                "--center-hz",      str(float(center_hz)),
                "--mode",           mode,
                "--sample-rate",    str(float(sample_rate_hz)),
                "--gain",           str(float(gain_db)),
                "--antenna",        app_settings.default_device.antenna,
                "--device-addr",    app_settings.default_device.device_args,
                "--chunk-duration", str(float(chunk_duration)),
            ]

            if bpf_low_hz is not None and bpf_high_hz is not None:
                cmd += ["--bpf-low-hz", str(float(bpf_low_hz)),
                        "--bpf-high-hz", str(float(bpf_high_hz))]

            self._was_streaming = real_spectrum_stream.is_running()
            real_spectrum_stream.begin_exclusive_operation("Live audio demodulation is using the USRP-B200")

            try:
                self._worker = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=str(backend_root),
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            except Exception as exc:
                real_spectrum_stream.end_exclusive_operation()
                if self._was_streaming:
                    real_spectrum_stream.ensure_started(self._settings)
                raise ValueError(f"Failed to start live demodulation worker: {exc}") from exc

            with self._chunks_lock:
                self._chunks.clear()

            self._state = {
                "status": "starting",
                "mode": mode,
                "center_hz": center_hz,
                "sample_rate_hz": sample_rate_hz,
                "gain_db": gain_db,
                "chunk_duration": chunk_duration,
                "bpf_low_hz": bpf_low_hz,
                "bpf_high_hz": bpf_high_hz,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "chunks_delivered": 0,
            }

            self._reader_thread = threading.Thread(
                target=self._read_worker_output, daemon=True, name="LiveDemodReader"
            )
            self._reader_thread.start()

        return self.get_status()

    def stop(self) -> dict:
        with self._lock:
            self._stop_worker_locked()
            self._state["status"] = "idle"
        return self.get_status()

    def update_gain(self, gain_db: float) -> dict:
        validate_gain(gain_db)
        with self._lock:
            if self._worker and self._worker.poll() is None:
                try:
                    self._worker.stdin.write(json.dumps({"cmd": "set_gain", "gain": gain_db}) + "\n")
                    self._worker.stdin.flush()
                    self._state["gain_db"] = gain_db
                except Exception:
                    pass
        return self.get_status()

    def update_freq(self, center_hz: float) -> dict:
        with self._lock:
            if self._worker and self._worker.poll() is None:
                try:
                    self._worker.stdin.write(json.dumps({"cmd": "set_freq", "center_hz": center_hz}) + "\n")
                    self._worker.stdin.flush()
                    self._state["center_hz"] = center_hz
                except Exception:
                    pass
        return self.get_status()

    def update_bpf(self, bpf_low_hz: float | None, bpf_high_hz: float | None) -> dict:
        """Enable or disable the pre-demodulation band-pass filter at runtime."""
        if bpf_low_hz is not None and bpf_high_hz is not None:
            if bpf_high_hz <= bpf_low_hz:
                raise ValueError("bpf_high_hz must be greater than bpf_low_hz")

        with self._lock:
            if self._worker and self._worker.poll() is None:
                try:
                    self._worker.stdin.write(
                        json.dumps({
                            "cmd": "set_bpf",
                            "bpf_low_hz": bpf_low_hz,
                            "bpf_high_hz": bpf_high_hz,
                        }) + "\n"
                    )
                    self._worker.stdin.flush()
                    self._state["bpf_low_hz"] = bpf_low_hz
                    self._state["bpf_high_hz"] = bpf_high_hz
                except Exception:
                    pass
        return self.get_status()

    def get_chunks_from(self, offset: int) -> tuple[list[dict], int]:
        with self._chunks_lock:
            new = self._chunks[offset:]
            return new, offset + len(new)

    async def sse_generator(self) -> AsyncIterator[str]:
        offset = 0
        yield f"data: {json.dumps({'type': 'connected', 'status': self._state.get('status', 'idle')})}\n\n"

        while True:
            chunks, offset = self.get_chunks_from(offset)
            for chunk in chunks:
                yield f"data: {json.dumps(chunk)}\n\n"

            status = self._state.get("status", "idle")
            if status in ("idle", "error") and not chunks:
                yield f"data: {json.dumps({'type': 'stream_end', 'status': status})}\n\n"
                break

            if not chunks:
                yield ": keepalive\n\n"
                await asyncio.sleep(0.04)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _read_worker_output(self) -> None:
        worker = self._worker
        if not worker:
            return
        try:
            for raw in worker.stdout:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue

                msg_type = msg.get("type", "")
                if msg_type == "status":
                    message = msg.get("message", "")
                    with self._lock:
                        if message == "streaming":
                            self._state["status"] = "streaming"
                        elif message == "stopped":
                            self._state["status"] = "idle"
                elif msg_type == "audio_chunk":
                    with self._chunks_lock:
                        self._chunks.append(msg)
                        if len(self._chunks) > _MAX_BUFFER_CHUNKS:
                            del self._chunks[: len(self._chunks) - _MAX_BUFFER_CHUNKS]
                    with self._lock:
                        self._state["chunks_delivered"] = self._state.get("chunks_delivered", 0) + 1
                        self._state["last_rms_db"] = msg.get("rms_db", -96.0)
                elif msg_type == "error":
                    with self._lock:
                        self._state["status"] = "error"
                        self._state["error"] = msg.get("message", "Unknown worker error")
        except Exception:
            pass
        finally:
            with self._lock:
                if self._state.get("status") not in ("idle",):
                    self._state["status"] = "idle"
            try:
                real_spectrum_stream.end_exclusive_operation()
            except Exception:
                pass
            if self._was_streaming:
                try:
                    real_spectrum_stream.ensure_started(self._settings)
                except Exception:
                    pass

    def _stop_worker_locked(self) -> None:
        if not self._worker:
            return
        if self._worker.poll() is None:
            try:
                self._worker.stdin.write(json.dumps({"cmd": "stop"}) + "\n")
                self._worker.stdin.flush()
                self._worker.wait(timeout=6.0)
            except Exception:
                try:
                    self._worker.kill()
                except Exception:
                    pass
        self._worker = None
