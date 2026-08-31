from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone

from app.config.settings import settings as app_settings
from app.infrastructure.sdr.real_spectrum_stream import real_spectrum_stream
from app.infrastructure.sdr.rf_safety import (
    safety_status,
    validate_center_frequency,
    validate_frequency_window,
    validate_gain,
    validate_sample_rate,
)


class DeviceController:
    def __init__(
        self,
        start_device_stream_use_case,
        stop_device_stream_use_case,
        set_center_frequency_use_case,
        set_sample_rate_use_case,
        set_gain_use_case,
        settings,
    ):
        self._start_device_stream_use_case = start_device_stream_use_case
        self._stop_device_stream_use_case = stop_device_stream_use_case
        self._set_center_frequency_use_case = set_center_frequency_use_case
        self._set_sample_rate_use_case = set_sample_rate_use_case
        self._set_gain_use_case = set_gain_use_case
        self._settings = settings
        self._is_streaming = False
        self._is_connected = False
        self._last_error: str | None = None
        self._device_info: dict = {}
        self._receiver_process = None

    def connect_device(self) -> dict:
        driver = self._driver_name()
        self._last_error = None
        try:
            validate_frequency_window(
                self._settings.frequency.center_frequency_hz,
                self._settings.frequency.sample_rate_hz,
            )
            validate_gain(self._settings.gain.gain_db)
        except ValueError as exc:
            self._is_connected = False
            self._last_error = str(exc)
            return self.get_device_status()

        python_exe = os.environ.get("RADIOCONDA_PYTHON", r"C:\Users\Usuario\radioconda\python.exe")
        backend_root = app_settings.storage.app_root.parent
        script_path = backend_root / "tools" / "capture_and_demodulate_fm.py"
        output_dir = app_settings.storage.temp_dir
        command = [
            python_exe,
            str(script_path),
            "--freq",
            f"{self._settings.frequency.center_frequency_hz / 1e6:.9f}",
            "--duration",
            "1",
            "--sample-rate",
            str(float(self._settings.frequency.sample_rate_hz)),
            "--gain",
            str(float(self._settings.gain.gain_db)),
            "--antenna",
            app_settings.default_device.antenna,
            "--device-addr",
            app_settings.default_device.device_args,
            "--output-dir",
            str(output_dir),
            "--base-name",
            "connect_probe",
        ]

        try:
            completed = subprocess.run(
                command,
                cwd=str(backend_root),
                capture_output=True,
                text=True,
                timeout=float(os.environ.get("REAL_SDR_CONNECT_TIMEOUT", "60")),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception as exc:
            self._is_connected = False
            self._last_error = str(exc)
            return self.get_device_status()

        if completed.returncode != 0:
            self._is_connected = False
            self._last_error = completed.stderr or completed.stdout or "UHD probe failed"
            return self.get_device_status()

        try:
            self._device_info = {
                "driver": "uhd_gnuradio",
                "probe": "capture_and_demodulate_fm",
                "stdout": completed.stdout[-4000:],
                "output_dir": str(output_dir),
            }
            self._is_connected = True
        except Exception as exc:
            self._is_connected = False
            self._last_error = f"{exc}: {completed.stdout}"

        return self.get_device_status()

    def disconnect_device(self) -> dict:
        self._is_streaming = False
        self._is_connected = False
        real_spectrum_stream.stop()
        return self.get_device_status()

    def open_wfm_receiver(self) -> dict:
        try:
            validate_center_frequency(self._settings.frequency.center_frequency_hz)
            validate_gain(self._settings.gain.gain_db)
        except ValueError as exc:
            self._last_error = str(exc)
            return self.get_device_status()

        python_exe = os.environ.get("RADIOCONDA_PYTHON", r"C:\Users\Usuario\radioconda\python.exe")
        backend_root = app_settings.storage.app_root.parent
        script_path = backend_root / "tools" / "wfm_receiver_qt.py"
        output_path = app_settings.storage.recordings_dir / "live_wfm_audio.wav"

        command = [
            python_exe,
            str(script_path),
            "--freq",
            f"{self._settings.frequency.center_frequency_hz / 1e6:.9f}",
            "--output",
            str(output_path),
        ]

        try:
            self._receiver_process = subprocess.Popen(
                command,
                cwd=str(backend_root),
                creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
            )
            self._is_connected = True
            self._is_streaming = True
            self._last_error = None
            return {
                **self.get_device_status(),
                "receiver_pid": self._receiver_process.pid,
                "audio_output_path": str(output_path),
            }
        except Exception as exc:
            self._last_error = str(exc)
            return self.get_device_status()

    def close_wfm_receiver(self) -> dict:
        if self._receiver_process and self._receiver_process.poll() is None:
            self._receiver_process.terminate()
        self._receiver_process = None
        self._is_streaming = False
        return self.get_device_status()

    def start_streaming(self) -> dict:
        try:
            validate_frequency_window(
                self._settings.frequency.center_frequency_hz,
                self._settings.frequency.sample_rate_hz,
            )
            validate_gain(self._settings.gain.gain_db)
        except ValueError as exc:
            self._is_streaming = False
            self._last_error = str(exc)
            return self.get_device_status()

        if not self._is_connected:
            self.connect_device()
        self._is_streaming = self._is_connected
        if self._is_streaming:
            real_spectrum_stream.ensure_started(self._settings)
        return self.get_device_status()

    def stop_streaming(self) -> dict:
        self._is_streaming = False
        real_spectrum_stream.stop()
        try:
            return self._stop_device_stream_use_case.execute()
        except Exception:
            return self.get_device_status()

    def set_frequency(self, frequency_hz: float) -> dict:
        validate_center_frequency(frequency_hz)
        validate_frequency_window(frequency_hz, self._settings.frequency.span_hz)
        self._settings.set_center_frequency(frequency_hz)
        if self._is_streaming:
            real_spectrum_stream.apply_settings(self._settings)
        try:
            return self._set_center_frequency_use_case.execute(frequency_hz)
        except Exception:
            return {"status": "ok", "center_frequency_hz": frequency_hz}

    def set_gain(self, gain_db: float) -> dict:
        validate_gain(gain_db)
        self._settings.set_gain(gain_db)
        if self._is_streaming:
            real_spectrum_stream.apply_settings(self._settings)
        try:
            return self._set_gain_use_case.execute(gain_db)
        except Exception:
            return {"status": "ok", "gain_db": gain_db}

    def set_sample_rate(self, sample_rate_hz: float) -> dict:
        # The real ADC/USRP acquisition rate -- independent of span_hz (the
        # displayed/analyzed window; see SpectrumController.set_span).
        # Lowering below the current span auto-narrows the span to match,
        # since a view can never be wider than what's actually sampled.
        validate_sample_rate(sample_rate_hz)
        validate_frequency_window(self._settings.frequency.center_frequency_hz, sample_rate_hz)
        self._settings.set_sample_rate(sample_rate_hz)
        if sample_rate_hz < self._settings.frequency.span_hz:
            self._settings.set_span(sample_rate_hz)
        if self._is_streaming:
            real_spectrum_stream.apply_settings(self._settings)
        result = {"status": "ok", "sample_rate_hz": sample_rate_hz, "span_hz": self._settings.frequency.span_hz}
        try:
            use_case_result = self._set_sample_rate_use_case.execute(sample_rate_hz)
            return {**result, **(use_case_result or {})}
        except Exception:
            return result

    def get_device_status(self) -> dict:
        return {
            "status": "streaming" if self._is_streaming else "ready",
            "driver": self._driver_name(),
            "is_connected": self._is_connected,
            "frequency_hz": self._settings.frequency.center_frequency_hz,
            "gain_db": self._settings.gain.gain_db,
            "sample_rate_hz": self._settings.frequency.sample_rate_hz,
            "is_streaming": self._is_streaming,
            "last_error": self._last_error,
            "device_info": self._device_info,
            "safety_limits": safety_status(),
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }

    def _driver_name(self) -> str:
        return "uhd_gnuradio"
