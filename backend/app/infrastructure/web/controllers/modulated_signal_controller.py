from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

from app.config.settings import settings as app_settings
from app.infrastructure.sdr.real_spectrum_stream import real_spectrum_stream
from app.infrastructure.sdr.rf_safety import (
    DEFAULT_USRP_B200_LIMITS,
    validate_gain,
    validate_sample_rate,
    validate_start_stop,
)


class ModulatedSignalController:
    _capture_oversample_factor = 1.25
    _max_capture_sample_rate_hz = 12_500_000.0
    _max_capture_file_size_bytes = 768 * 1024 * 1024

    def __init__(self, settings) -> None:
        self._settings = settings
        self._cfile_output_dir = app_settings.storage.recordings_dir / "modulated_signal_captures"
        self._iq_output_dir = app_settings.storage.recordings_dir / "modulated_signal_iq_captures"
        self._cfile_output_dir.mkdir(parents=True, exist_ok=True)
        self._iq_output_dir.mkdir(parents=True, exist_ok=True)

    def capture_marker_band(
        self,
        start_frequency_hz: float,
        stop_frequency_hz: float,
        duration_seconds: float = 5.0,
        label: str = "",
        modulation_hint: str = "unknown",
        notes: str = "",
        dataset_split: str = "train",
        session_id: str = "",
        transmitter_id: str = "",
        transmitter_class: str = "",
        operator: str = "",
        environment: str = "",
        file_format: str = "cfile",
        live_preview_snr_db: float | None = None,
        live_preview_noise_floor_db: float | None = None,
        live_preview_peak_level_db: float | None = None,
        live_preview_peak_frequency_hz: float | None = None,
        capture_mode: str = "immediate",
        trigger_strategy: str = "adaptive_energy_trigger",
        trigger_threshold_db: float = 6.0,
        pre_trigger_ms: float = 50.0,
        post_trigger_ms: float = 100.0,
        min_event_duration_ms: float = 10.0,
        max_event_duration_ms: float = 2000.0,
        cooldown_ms: float = 500.0,
        trigger_max_wait_s: float = 10.0,
        capture_repetitions: int = 1,
        min_valid_events: int = 1,
        smart_persistence_ms: float = 10.0,
        auto_qc_enabled: bool = True,
        target_task: str = "device_fingerprinting",
        signal_type: str = "",
        apply_bandpass_filter: bool = False,
        filter_stopband_attenuation_db: float = 60.0,
        filter_transition_width_hz: float | None = None,
    ) -> dict:
        file_format = file_format.lower()
        if file_format not in {"cfile", "iq"}:
            raise ValueError("file_format must be cfile or iq")
        if capture_mode not in {"immediate", "triggered_burst"}:
            raise ValueError("capture_mode must be immediate or triggered_burst")
        if capture_mode == "immediate":
            if duration_seconds <= 0 or duration_seconds > 120:
                raise ValueError("duration_seconds must be between 0 and 120")
            if filter_stopband_attenuation_db < 1 or filter_stopband_attenuation_db > 60:
                raise ValueError("filter_stopband_attenuation_db must be between 1 and 60 dB")
        if capture_mode == "triggered_burst":
            if trigger_strategy not in {"adaptive_energy_trigger", "smart_burst_trigger"}:
                raise ValueError("trigger_strategy must be adaptive_energy_trigger or smart_burst_trigger")
            if trigger_threshold_db <= 0 or trigger_threshold_db > 40:
                raise ValueError("trigger_threshold_db must be between 0 and 40 dB")
            if pre_trigger_ms < 0 or post_trigger_ms < 0:
                raise ValueError("pre_trigger_ms and post_trigger_ms must be non-negative")
            if trigger_max_wait_s <= 0 or trigger_max_wait_s > 120:
                raise ValueError("trigger_max_wait_s must be between 0 and 120")
            if capture_repetitions < 1 or capture_repetitions > 20:
                raise ValueError("capture_repetitions must be between 1 and 20")
            if target_task not in {"device_fingerprinting", "signal_recognition"}:
                raise ValueError("target_task must be device_fingerprinting or signal_recognition")

        center_frequency_hz, bandwidth_hz = validate_start_stop(start_frequency_hz, stop_frequency_hz)
        validate_gain(self._settings.gain.gain_db)
        requested_sample_rate_hz = max(
            bandwidth_hz * self._capture_oversample_factor,
            DEFAULT_USRP_B200_LIMITS.min_sample_rate_hz,
        )
        if requested_sample_rate_hz > self._max_capture_sample_rate_hz:
            max_bandwidth_hz = self._max_capture_sample_rate_hz / self._capture_oversample_factor
            raise ValueError(
                "Capture Lab bandwidth is too large for reliable acquisition in this workflow. "
                f"Requested bandwidth: {bandwidth_hz / 1e6:.2f} MHz. "
                f"Safe limit: {max_bandwidth_hz / 1e6:.2f} MHz. "
                "Reduce bandwidth or capture a narrower window."
            )

        sample_rate_hz = min(
            max(
                float(self._settings.frequency.sample_rate_hz),
                requested_sample_rate_hz,
                DEFAULT_USRP_B200_LIMITS.min_sample_rate_hz,
            ),
            min(DEFAULT_USRP_B200_LIMITS.max_sample_rate_hz, self._max_capture_sample_rate_hz),
        )
        validate_sample_rate(sample_rate_hz)
        # For immediate mode only: check that the single recording fits within the file-size limit.
        # Triggered mode writes per-event files (each event is typically short), so the limit
        # is not applied there.
        if capture_mode == "immediate":
            estimated_file_size_bytes = int(float(duration_seconds) * sample_rate_hz * 8)
            if estimated_file_size_bytes > self._max_capture_file_size_bytes:
                raise ValueError(
                    "Capture would generate an excessively large IQ file for Capture Lab. "
                    f"Estimated size: {estimated_file_size_bytes / (1024 * 1024):.1f} MiB. "
                    f"Limit: {self._max_capture_file_size_bytes / (1024 * 1024):.1f} MiB. "
                    "Reduce duration or bandwidth."
                )
        # effective_capture_horizon_s is only needed for the immediate script timeout
        effective_capture_horizon_s = float(duration_seconds)

        capture_id = str(uuid.uuid4())[:8]
        backend_root = app_settings.storage.app_root.parent
        python_exe = os.environ.get("RADIOCONDA_PYTHON", r"C:\Users\Usuario\radioconda\python.exe")
        output_dir = self._iq_output_dir if file_format == "iq" else self._cfile_output_dir
        base_name = f"{file_format}_{capture_id}_{center_frequency_hz / 1e6:.6f}MHz_{bandwidth_hz / 1e3:.1f}kHz"

        # Route to the appropriate backend script based on capture mode.
        # "immediate"       → capture_marker_band_iq.py  (GNU Radio flowgraph, one shot)
        # "triggered_burst" → triggered_burst_capture.py (GNU Radio sync_block, circular buffer, multi-event)
        if capture_mode == "triggered_burst":
            script_path = backend_root / "tools" / "triggered_burst_capture.py"
            command = [
                python_exe, str(script_path),
                "--capture-id", capture_id,
                "--start-hz", str(float(start_frequency_hz)),
                "--stop-hz", str(float(stop_frequency_hz)),
                "--sample-rate", str(sample_rate_hz),
                "--gain", str(float(self._settings.gain.gain_db)),
                "--antenna", app_settings.default_device.antenna,
                "--device-addr", app_settings.default_device.device_args,
                "--output-dir", str(output_dir),
                "--base-name", base_name,
                "--file-format", file_format,
                "--label", label,
                "--modulation-hint", modulation_hint,
                "--notes", notes,
                "--dataset-split", dataset_split,
                "--session-id", session_id,
                "--transmitter-id", transmitter_id,
                "--transmitter-class", transmitter_class,
                "--operator", operator,
                "--environment", environment,
                "--target-task", target_task,
                "--signal-type", signal_type,
                "--trigger-strategy", trigger_strategy,
                "--trigger-threshold-db", str(float(trigger_threshold_db)),
                "--pre-trigger-ms", str(float(pre_trigger_ms)),
                "--post-trigger-ms", str(float(post_trigger_ms)),
                "--min-event-duration-ms", str(float(min_event_duration_ms)),
                "--max-event-duration-ms", str(float(max_event_duration_ms)),
                "--cooldown-ms", str(float(cooldown_ms)),
                "--max-wait-seconds", str(float(trigger_max_wait_s)),
                "--capture-repetitions", str(int(capture_repetitions)),
                "--min-valid-events", str(int(min_valid_events)),
                "--smart-persistence-ms", str(float(smart_persistence_ms)),
            ]
            if not auto_qc_enabled:
                command.append("--no-auto-qc")
            # Session timeout: wait time × repetitions + cooldown × repetitions + margin
            session_timeout = (
                float(trigger_max_wait_s) * int(capture_repetitions)
                + float(cooldown_ms) / 1000.0 * max(int(capture_repetitions) - 1, 0)
                + 60.0
            )
        else:
            script_path = backend_root / "tools" / "capture_marker_band_iq.py"
            command = [
                python_exe, str(script_path),
                "--capture-id", capture_id,
                "--start-hz", str(float(start_frequency_hz)),
                "--stop-hz", str(float(stop_frequency_hz)),
                "--duration", str(float(duration_seconds)),
                "--sample-rate", str(sample_rate_hz),
                "--gain", str(float(self._settings.gain.gain_db)),
                "--antenna", app_settings.default_device.antenna,
                "--device-addr", app_settings.default_device.device_args,
                "--output-dir", str(output_dir),
                "--base-name", base_name,
                "--file-format", file_format,
                "--label", label,
                "--modulation-hint", modulation_hint,
                "--notes", notes,
                "--dataset-split", dataset_split,
                "--session-id", session_id,
                "--transmitter-id", transmitter_id,
                "--transmitter-class", transmitter_class,
                "--operator", operator,
                "--environment", environment,
                "--capture-mode", capture_mode,
            ]
            if apply_bandpass_filter:
                command.append("--apply-bandpass-filter")
                command.extend(["--filter-stopband-attenuation-db", str(float(filter_stopband_attenuation_db))])
                if filter_transition_width_hz is not None:
                    command.extend(["--filter-transition-width-hz", str(float(filter_transition_width_hz))])
            session_timeout = max(effective_capture_horizon_s + 30.0, 45.0)

        # Live preview metrics apply to both scripts
        if live_preview_snr_db is not None:
            command.extend(["--live-preview-snr-db", str(float(live_preview_snr_db))])
        if live_preview_noise_floor_db is not None:
            command.extend(["--live-preview-noise-floor-db", str(float(live_preview_noise_floor_db))])
        if live_preview_peak_level_db is not None:
            command.extend(["--live-preview-peak-level-db", str(float(live_preview_peak_level_db))])
        if live_preview_peak_frequency_hz is not None:
            command.extend(["--live-preview-peak-frequency-hz", str(float(live_preview_peak_frequency_hz))])

        was_streaming = real_spectrum_stream.is_running()
        real_spectrum_stream.begin_exclusive_operation(
            "Marker-band IQ capture is using the USRP-B200 exclusively"
        )
        try:
            completed = subprocess.run(
                command,
                cwd=str(backend_root),
                capture_output=True,
                text=True,
                timeout=session_timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except Exception as exc:
            raise ValueError(str(exc)) from exc
        finally:
            real_spectrum_stream.end_exclusive_operation()
            if was_streaming:
                real_spectrum_stream.ensure_started(self._settings)

        if completed.returncode != 0:
            error_output = completed.stderr or completed.stdout or "IQ capture failed"
            if "No devices found" in error_output or "No devices found" in (completed.stdout or ""):
                error_output = (
                    "UHD did not find the USRP-B200. Check the USB connection and make sure no other "
                    "GNU Radio/UHD process is using the device."
                )
            raise ValueError(error_output)

        stdout_lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if not stdout_lines:
            raise ValueError("IQ capture worker did not return metadata")
        return self._with_urls(json.loads(stdout_lines[-1]))

    def list_captures(self) -> list[dict]:
        captures = []
        metadata_paths = list(self._cfile_output_dir.glob("*.json")) + list(self._iq_output_dir.glob("*.json"))
        for path in sorted(metadata_paths, key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                with path.open("r", encoding="utf-8") as file:
                    capture = json.load(file)
                capture["metadata_file"] = str(path.resolve())
                capture["metadata_path_repaired"] = True
                iq_path = Path(str(capture.get("iq_file") or ""))
                capture["external_iq_file"] = bool(capture.get("iq_file")) and not self._is_safe_capture_artifact(iq_path)
                captures.append(self._with_urls(capture))
            except Exception:
                continue
        return captures

    def get_capture(self, capture_id: str) -> dict:
        for capture in self.list_captures():
            if capture.get("id") == capture_id:
                return capture
        raise ValueError(f"Modulated signal capture not found: {capture_id}")

    def get_iq_file(self, capture_id: str) -> Path:
        capture = self.get_capture(capture_id)
        return self._existing_file(capture.get("iq_file"), "IQ file")

    def get_metadata_file(self, capture_id: str) -> Path:
        capture = self.get_capture(capture_id)
        return self._existing_file(capture.get("metadata_file"), "metadata file")

    def delete_capture(self, capture_id: str) -> dict:
        capture = self.get_capture(capture_id)
        removed_registry_records = self._delete_linked_fingerprinting_records(capture)
        removed_registry_records.extend(self._delete_linked_rf_signal_understanding_records(capture))
        candidate_values = [capture.get("iq_file"), capture.get("metadata_file")]
        removed_files: list[str] = []
        skipped_external_files: list[str] = []
        for value in candidate_values:
            if not value:
                continue
            path = Path(str(value))
            if not path.exists() or not path.is_file():
                continue
            if not self._is_safe_capture_artifact(path):
                skipped_external_files.append(str(path))
                continue
            try:
                path.unlink()
                removed_files.append(str(path.resolve()))
            except OSError:
                skipped_external_files.append(str(path))

        return {
            "capture_id": capture_id,
            "deleted": True,
            "deleted_files": removed_files,
            "skipped_external_files": skipped_external_files,
            "deleted_registry_records": removed_registry_records,
        }

    def _is_safe_capture_artifact(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
            recordings_root = app_settings.storage.recordings_dir.resolve()
            resolved.relative_to(recordings_root)
            return resolved.suffix.lower() in {".json", ".iq", ".cfile"}
        except (OSError, ValueError):
            return False

    def _delete_linked_fingerprinting_records(self, capture: dict) -> list[str]:
        captures_dir = app_settings.storage.fingerprinting_dir / "captures"
        if not captures_dir.exists():
            return []
        linked_paths = set()
        for value in [capture.get("iq_file"), capture.get("metadata_file")]:
            if not value:
                continue
            try:
                linked_paths.add(str(Path(str(value)).resolve()))
            except OSError:
                continue
        removed: list[str] = []
        for record_path in captures_dir.glob("*.json"):
            try:
                with record_path.open("r", encoding="utf-8") as handle:
                    record = json.load(handle)
            except Exception:
                continue
            references = [
                ((record.get("artifacts") or {}).get("iq_file")),
                ((record.get("artifacts") or {}).get("metadata_file")),
                ((record.get("capture_config") or {}).get("output_path")),
            ]
            normalized_refs = set()
            for reference in references:
                if not reference:
                    continue
                try:
                    normalized_refs.add(str(Path(str(reference)).resolve()))
                except OSError:
                    continue
            if linked_paths.intersection(normalized_refs):
                try:
                    record_path.unlink()
                    removed.append(record_path.stem)
                except OSError:
                    pass
        return removed

    def _delete_linked_rf_signal_understanding_records(self, capture: dict) -> list[str]:
        registry_path = app_settings.storage.storage_root / "rf_signal_understanding" / "capture_registry" / "captures.json"
        if not registry_path.exists():
            return []
        capture_id = capture.get("id")
        if not capture_id:
            return []
        try:
            with registry_path.open("r", encoding="utf-8") as handle:
                records = json.load(handle)
        except Exception:
            return []
        if not isinstance(records, list):
            return []
        original_count = len(records)
        filtered_records = [r for r in records if str(r.get("capture_id")) != str(capture_id)]
        if len(filtered_records) < original_count:
            with registry_path.open("w", encoding="utf-8") as handle:
                json.dump(filtered_records, handle, indent=2, ensure_ascii=False)
            return [str(capture_id)]
        return []

    def _existing_file(self, value: str | None, label: str) -> Path:
        if not value:
            raise ValueError(f"{label} is not available")
        path = Path(value)
        if not path.exists():
            raise ValueError(f"{label} not found: {path}")
        return path

    def _with_urls(self, capture: dict) -> dict:
        capture_id = capture.get("id")
        if capture_id:
            capture["iq_url"] = f"/api/modulated-signals/captures/{capture_id}/iq"
            capture["metadata_url"] = f"/api/modulated-signals/captures/{capture_id}/metadata"
        return capture
