from __future__ import annotations
import os
import subprocess
import uuid
from pathlib import Path

from app.config.settings import settings as app_settings
from app.application.dto.recording_dto import RecordingDTO

class StartRFRecordingUseCase:
    def __init__(self, recording_provider=None):
        self.recording_provider = recording_provider

    def execute(self, duration_seconds: float = 10.0, analyzer_settings=None, recording_type: str = "iq") -> RecordingDTO:
        recording_id = str(uuid.uuid4())[:8]
        center_frequency_hz = getattr(getattr(analyzer_settings, "frequency", None), "center_frequency_hz", 100_000_000.0)
        sample_rate_hz = getattr(getattr(analyzer_settings, "frequency", None), "sample_rate_hz", 2_000_000.0)
        gain_db = getattr(getattr(analyzer_settings, "gain", None), "gain_db", 20.0)

        output_dir = app_settings.storage.recordings_dir
        base_name = f"capture_{recording_id}_{center_frequency_hz / 1e6:.6f}MHz"
        iq_path = output_dir / f"{base_name}.cfile"
        wav_path = output_dir / f"{base_name}.wav"
        log_path = output_dir / f"{base_name}.log"

        python_exe = os.environ.get("RADIOCONDA_PYTHON", r"C:\Users\Usuario\radioconda\python.exe")
        backend_root = app_settings.storage.app_root.parent
        script_path = backend_root / "tools" / "capture_and_demodulate_fm.py"

        error_message = None
        if Path(python_exe).exists() and script_path.exists():
            command = [
                python_exe,
                str(script_path),
                "--freq",
                f"{center_frequency_hz / 1e6:.9f}",
                "--duration",
                str(float(duration_seconds)),
                "--sample-rate",
                str(float(sample_rate_hz)),
                "--gain",
                str(float(gain_db)),
                "--antenna",
                app_settings.default_device.antenna,
                "--device-addr",
                app_settings.default_device.device_args,
                "--output-dir",
                str(output_dir),
                "--base-name",
                base_name,
            ]
            try:
                log_file = open(log_path, "w", encoding="utf-8")
                subprocess.Popen(
                    command,
                    cwd=str(backend_root),
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            except Exception as exc:
                error_message = str(exc)

        return RecordingDTO(
            recording_id=recording_id,
            filename=str(wav_path if recording_type == "audio" else iq_path),
            duration_seconds=duration_seconds,
            format=recording_type,
            status="recording",
            error_message=error_message,
        )
