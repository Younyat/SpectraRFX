from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import numpy as np

from app.config.settings import settings as app_settings
from app.infrastructure.jobs import job_tracker
from app.infrastructure.sdr.real_spectrum_stream import real_spectrum_stream
from app.infrastructure.sdr.rf_safety import (
    DEFAULT_USRP_B200_LIMITS,
    validate_gain,
    validate_sample_rate,
    validate_start_stop,
)
from app.modules.demodulation.wifi_80211 import WifiDecodeService, default_worker_command
from app.modules.demodulation.wifi_80211.domain.models import WifiCaptureContract
from app.modules.demodulation.wifi_80211.infrastructure.capture_adapter import sample_count, sha256_file


class DemodulationController:
    IOT_PIPELINES = {
        "ble_advertising",
        "wifi_80211",
        "generic_gfsk_iot",
        "ook_ask_iot_sensor",
        "generic_fsk_iot",
        "zigbee_ieee802154",
        "lora_css",
        "ook_433_remote",
        "fsk_remote_decoder",
    }

    def __init__(
        self,
        start_demodulation_use_case,
        stop_demodulation_use_case,
        get_audio_status_use_case,
        settings,
    ):
        self._start_demodulation_use_case = start_demodulation_use_case
        self._stop_demodulation_use_case = stop_demodulation_use_case
        self._get_audio_status_use_case = get_audio_status_use_case
        self._settings = settings
        self._mode = "off"
        self._results: dict[str, dict] = {}
        self._output_dir = app_settings.storage.recordings_dir / "demodulations"
        self._dataset_output_dir = app_settings.storage.storage_root / "demodulation_outputs"
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._dataset_output_dir.mkdir(parents=True, exist_ok=True)

    def list_pipelines(self) -> list[dict]:
        return [
            {
                "id": "wfm_broadcast",
                "category": "Basic analog demodulation",
                "family": "audio_analog",
                "label": "WFM broadcast",
                "status": "implemented_basic",
                "outputs": ["recovered_audio.wav", "demodulation_report.json"],
            },
            {
                "id": "nfm",
                "category": "Basic analog demodulation",
                "family": "audio_analog",
                "label": "NFM",
                "status": "implemented_basic",
                "outputs": ["recovered_audio.wav", "demodulation_report.json"],
            },
            {
                "id": "am",
                "category": "Basic analog demodulation",
                "family": "audio_analog",
                "label": "AM",
                "status": "implemented_basic",
                "outputs": ["recovered_audio.wav", "demodulation_report.json"],
            },
            {
                "id": "ble_advertising",
                "category": "Wireless LAN decoders",
                "family": "bluetooth_low_energy",
                "label": "BLE advertising channels 37/38/39",
                "status": "rf_activity_and_sync_scaffold",
                "outputs": ["decoded_packets.json", "demodulation_report.json"],
            },
            {
                "id": "wifi_80211",
                "category": "IoT Demodulation Pipelines",
                "family": "wifi_80211",
                "label": "Wi-Fi 802.11 2.4 / 5 GHz",
                "status": "v2_foundation_flagged" if self._wifi_demod_v2_enabled() else "current_scaffold",
                "support": {
                    "legacy_ofdm_80211ag": "external_worker_required",
                    "dsss_cck_80211b": "not_implemented",
                    "ht_vht_he": "identification_not_implemented",
                },
                "outputs": (["decoded_frames.json", "failed_frame_candidates.json", "capture_manifest.json", "demodulation_report.json"] if self._wifi_demod_v2_enabled() else ["decoded_packets.json", "demodulation_report.json"]),
            },
            {
                "id": "generic_gfsk_iot",
                "category": "IoT Demodulation Pipelines",
                "family": "generic_iot",
                "label": "Generic GFSK IoT Telemetry",
                "status": "physical_bitstream_estimator",
                "outputs": ["bitstream.bin", "decoded_payload.json", "demodulation_report.json"],
            },
            {
                "id": "ook_ask_iot_sensor",
                "category": "IoT Demodulation Pipelines",
                "family": "generic_iot_sensor",
                "label": "Generic OOK/ASK IoT Sensor",
                "status": "physical_bitstream_estimator",
                "outputs": ["bitstream.bin", "decoded_payload.json", "demodulation_report.json"],
            },
            {
                "id": "generic_fsk_iot",
                "category": "IoT Demodulation Pipelines",
                "family": "generic_iot",
                "label": "Generic FSK IoT Telemetry",
                "status": "physical_bitstream_estimator",
                "outputs": ["bitstream.bin", "decoded_payload.json", "demodulation_report.json"],
            },
            {
                "id": "zigbee_ieee802154",
                "category": "IoT Demodulation Pipelines",
                "family": "ieee802154",
                "label": "Zigbee / IEEE 802.15.4 O-QPSK DSSS 2.4 GHz (CH11-CH26)",
                "status": "implemented",
                "outputs": ["decoded_frames.json", "demodulation_report.json"],
            },
            {
                "id": "ieee802154_oqpsk",
                "category": "Protocol/system decoders",
                "family": "ieee802154",
                "label": "IEEE 802.15.4 O-QPSK DSSS 2.4 GHz",
                "status": "rf_activity_and_sync_scaffold",
                "outputs": ["decoded_packets.json", "demodulation_report.json"],
            },
            {
                "id": "dvbt",
                "category": "Protocol/system decoders",
                "family": "terrestrial_tv",
                "label": "DVB-T",
                "status": "external_chain_required",
                "outputs": ["demodulation_report.json"],
            },
            {
                "id": "adsb_1090",
                "category": "Protocol/system decoders",
                "family": "adsb",
                "label": "ADS-B 1090 MHz",
                "status": "rf_activity_and_sync_scaffold",
                "outputs": ["decoded_packets.json", "demodulation_report.json"],
            },
            {
                "id": "ook_fsk_generic",
                "category": "Physical-layer demodulation",
                "family": "simple_digital",
                "label": "OOK / FSK / GFSK generic",
                "status": "symbol_estimation_scaffold",
                "outputs": ["bitstream.bin", "decoded_payload.json", "demodulation_report.json"],
            },
            {
                "id": "lora_css",
                "category": "IoT Demodulation Pipelines",
                "family": "lora",
                "label": "LoRa CSS",
                "status": "experimental_scaffold",
                "outputs": ["decoded_payload.json", "demodulation_report.json"],
            },
            {
                "id": "dvbs_s2",
                "category": "Protocol/system decoders",
                "family": "satellite_tv",
                "label": "DVB-S / DVB-S2",
                "status": "experimental_requires_external_rf_front_end",
                "outputs": ["demodulation_report.json"],
            },
            {
                "id": "ook_433_remote",
                "category": "IoT Demodulation Pipelines",
                "family": "ook_remote_control",
                "label": "OOK 433 / 315 / 868 MHz Remote Control (EV1527, PT2262)",
                "status": "implemented",
                "outputs": ["decoded_frames.json", "recovered_bitstream.bin", "demodulation_report.json"],
                "description": (
                    "Decodes OOK/ASK remote control transmitters on the 433.92 MHz (EU/AS), "
                    "315 MHz (NA) and 868 MHz (EU SRD) ISM bands. Supports EV1527/SC1527 "
                    "(20-bit address + 4-bit button) and PT2262/SC2262 (12 tri-state) families. "
                    "Performs adaptive envelope detection, histogram-based T-unit estimation, "
                    "burst segmentation and protocol matching with repetition analysis."
                ),
            },
            {
                "id": "fsk_remote_decoder",
                "category": "IoT Demodulation Pipelines",
                "family": "fsk_remote_control",
                "label": "FSK 315 / 433 / 868 MHz Remote Control",
                "status": "fsk_bitstream_candidate_decoder",
                "outputs": [
                    "fsk_burst_diagnostics.json",
                    "fsk_candidate_decodings.json",
                    "selected_fsk_decoding.json",
                    "demodulation_report.json",
                ],
                "description": (
                    "Remote-control oriented 2-FSK detector for ISM remotes. "
                    "Segments bursts, estimates two-tone deviation, extracts candidate bitstreams "
                    "and reports repetition similarity. Protocol-level validation is still marked "
                    "candidate unless a known frame format is matched."
                ),
            },
        ]

    def start_demodulation(self, mode: str) -> dict:
        self._mode = mode
        try:
            return self._start_demodulation_use_case.execute(mode)
        except Exception:
            return {"status": "ok", "demodulation_mode": mode}

    def stop_demodulation(self) -> dict:
        self._mode = "off"
        try:
            return self._stop_demodulation_use_case.execute()
        except Exception:
            return {"status": "ok", "demodulation_stopped": True}

    def get_audio_status(self) -> dict:
        try:
            status = self._get_audio_status_use_case.execute()
        except Exception:
            status = {"status": "stopped", "is_playing": False}
        status["demodulation_mode"] = self._mode
        return status

    def demodulate_marker_band(
        self,
        start_frequency_hz: float,
        stop_frequency_hz: float,
        mode: str,
        duration_seconds: float = 5.0,
        apply_bandpass_filter: bool = False,
        filter_stopband_attenuation_db: float = 60.0,
        filter_transition_width_hz: float | None = None,
    ) -> dict:
        mode = mode.lower()
        if mode not in {"am", "fm", "nfm", "wfm", "ask", "fsk", "psk", "ook"} | self.IOT_PIPELINES:
            raise ValueError("mode must be one of am, fm, nfm, wfm, ask, fsk, psk, ook, or a registered IoT pipeline")
        if duration_seconds <= 0 or duration_seconds > 60:
            raise ValueError("duration_seconds must be between 0 and 60")
        if filter_stopband_attenuation_db < 1 or filter_stopband_attenuation_db > 60:
            raise ValueError("filter_stopband_attenuation_db must be between 1 and 60 dB")

        center_frequency_hz, bandwidth_hz = validate_start_stop(start_frequency_hz, stop_frequency_hz)
        validate_gain(self._settings.gain.gain_db)
        sample_rate_hz = self._live_capture_sample_rate_hz(mode, bandwidth_hz)
        validate_sample_rate(sample_rate_hz)

        demodulation_id = str(uuid.uuid4())[:8]
        backend_root = app_settings.storage.app_root.parent
        script_path = backend_root / "tools" / "demodulate_marker_band.py"
        python_exe = os.environ.get("RADIOCONDA_PYTHON", r"C:\Users\Usuario\radioconda\python.exe")
        worker_mode = self._live_worker_mode_for_pipeline(mode)
        base_name = f"marker_{demodulation_id}_{mode}_{center_frequency_hz / 1e6:.6f}MHz"

        command = [
            python_exe,
            str(script_path),
            "--start-hz",
            str(float(start_frequency_hz)),
            "--stop-hz",
            str(float(stop_frequency_hz)),
            "--mode",
            worker_mode,
            "--duration",
            str(float(duration_seconds)),
            "--sample-rate",
            str(sample_rate_hz),
            "--gain",
            str(float(self._settings.gain.gain_db)),
            "--antenna",
            app_settings.default_device.antenna,
            "--device-addr",
            app_settings.default_device.device_args,
            "--output-dir",
            str(self._output_dir),
            "--base-name",
            base_name,
        ]
        if apply_bandpass_filter:
            command.append("--apply-bandpass-filter")
            command.extend(["--filter-stopband-attenuation-db", str(float(filter_stopband_attenuation_db))])
            if filter_transition_width_hz is not None:
                command.extend(["--filter-transition-width-hz", str(float(filter_transition_width_hz))])

        was_streaming = real_spectrum_stream.is_running()
        real_spectrum_stream.begin_exclusive_operation(
            "Marker-band demodulation is using the USRP-B200 exclusively"
        )
        try:
            completed = subprocess.run(
                command,
                cwd=str(backend_root),
                capture_output=True,
                text=True,
                timeout=self._live_capture_timeout_seconds(duration_seconds, sample_rate_hz),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError(
                "Live demodulation timed out before the SDR worker returned metadata. "
                f"mode={mode}, sample_rate={sample_rate_hz / 1e6:.2f} MS/s, "
                f"duration={float(duration_seconds):.1f}s"
            ) from exc
        except Exception as exc:
            raise ValueError(str(exc)) from exc
        finally:
            real_spectrum_stream.end_exclusive_operation()
            if was_streaming:
                real_spectrum_stream.ensure_started(self._settings)

        if completed.returncode != 0:
            error_output = completed.stderr or completed.stdout or "marker band demodulation failed"
            if "No devices found" in error_output:
                error_output = (
                    "UHD did not find the USRP-B200. Check the USB connection and make sure no other "
                    "GNU Radio/UHD process is using the device."
                )
            raise ValueError(error_output)

        stdout_lines = [line for line in completed.stdout.splitlines() if line.strip()]
        if not stdout_lines:
            raise ValueError("demodulation worker did not return metadata")
        metadata = json.loads(stdout_lines[-1])
        result = {
            **metadata,
            "id": demodulation_id,
            "status": "complete",
            "final_status": "media_recovered" if metadata.get("audio_file") else "rf_activity_only",
            "mode": "live_demodulation",
            "source": "live_sdr",
            "marker_left_hz": float(start_frequency_hz),
            "marker_right_hz": float(stop_frequency_hz),
            "pipeline": mode,
            "demodulation_pipeline": mode,
            "rf_analysis_source": "computed_from_live_iq",
            "demodulation_source": "computed_from_live_iq",
            "audio_url": f"/api/demodulation/audio/{demodulation_id}" if metadata.get("audio_file") else None,
            "metadata_url": f"/api/demodulation/results/{demodulation_id}",
        }
        if mode == "wifi_80211" and metadata.get("iq_file") and self._wifi_demod_v2_enabled() and self._wifi_worker_available():
            # Live captures are a single contiguous, temporally-ordered recording
            # (same rationale as Capture Lab), and _live_capture_sample_rate_hz
            # already forced sample_rate_hz to exactly 20 MS/s above when the
            # worker is available, so this can feed the same real V3 decoder
            # dataset captures use -- reusing _run_wifi_v2 keeps it one path.
            live_payload = {
                "sample_id": demodulation_id,
                "dataset_id": "live_sdr",
                "file_path": metadata["iq_file"],
                "file_format": "cfile",
                "datatype": "cf32_le",
                "sample_rate_hz": sample_rate_hz,
                "center_frequency_hz": center_frequency_hz,
                "hardware_center_frequency_hz": center_frequency_hz,
                "channel_center_frequency_hz": center_frequency_hz,
                "channel_width_hz": 20_000_000.0,
                "bandwidth_hz": bandwidth_hz,
                "capture_duration": duration_seconds,
                "source_dataset": "live_sdr",
                "source": "live_sdr",
                "signal_type": mode,
                "pipeline": mode,
                "temporal_order_known": True,
            }
            output_dir = self._output_dir / demodulation_id
            output_dir.mkdir(parents=True, exist_ok=True)
            wifi_v2 = self._run_wifi_v2(live_payload, Path(str(metadata["iq_file"])), output_dir)
            if (wifi_v2.get("external_worker") or {}).get("fallback_to_current_scaffold"):
                requested_iq_samples = max(1, int(float(sample_rate_hz) * float(duration_seconds)))
                iq = self._read_complex_iq(Path(str(metadata["iq_file"])), "cf32_le", max_samples=requested_iq_samples)
                wifi_report = self._run_iot_pipeline(iq, live_payload, mode, output_dir)
                wifi_report["wifi_v2_worker_failure"] = wifi_v2.get("external_worker")
                wifi_report["notes"] = [*(wifi_report.get("notes") or []), "Wi-Fi V2 worker failed or rejected its input; the current scaffold was used without affecting other pipelines."]
            else:
                wifi_report = wifi_v2
            result.update(
                {
                    **wifi_report,
                    "id": demodulation_id,
                    "mode": "live_demodulation",
                    "source": "live_sdr",
                    "marker_left_hz": float(start_frequency_hz),
                    "marker_right_hz": float(stop_frequency_hz),
                    "center_frequency_hz": center_frequency_hz,
                    "bandwidth_hz": bandwidth_hz,
                    "sample_rate_hz": sample_rate_hz,
                    "duration_seconds": duration_seconds,
                    "iq_file": metadata["iq_file"],
                    "output_dir": str(output_dir),
                    "metadata_file": str(output_dir / "demodulation_report.json"),
                    "metadata_url": f"/api/demodulation/results/{demodulation_id}",
                    "rf_analysis_source": "computed_from_live_iq",
                    "demodulation_source": "computed_from_live_iq",
                }
            )
            result.setdefault("outputs", {})
            result["outputs"]["report"] = str(output_dir / "demodulation_report.json")
            Path(str(output_dir / "demodulation_report.json")).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        elif mode in self.IOT_PIPELINES and metadata.get("iq_file"):
            live_payload = {
                "sample_id": demodulation_id,
                "dataset_id": "live_sdr",
                "file_path": metadata["iq_file"],
                "file_format": "cfile",
                "datatype": "cf32_le",
                "sample_rate_hz": sample_rate_hz,
                "center_frequency_hz": center_frequency_hz,
                "bandwidth_hz": bandwidth_hz,
                "capture_duration": duration_seconds,
                "source_dataset": "live_sdr",
                "signal_type": mode,
                "pipeline": mode,
            }
            requested_iq_samples = max(1, int(float(sample_rate_hz) * float(duration_seconds)))
            iq = self._read_complex_iq(Path(str(metadata["iq_file"])), "cf32_le", max_samples=requested_iq_samples)
            output_dir = self._output_dir / demodulation_id
            output_dir.mkdir(parents=True, exist_ok=True)
            iot_report = self._run_iot_pipeline(iq, live_payload, mode, output_dir)
            result.update(
                {
                    **iot_report,
                    "id": demodulation_id,
                    "mode": "live_demodulation",
                    "source": "live_sdr",
                    "marker_left_hz": float(start_frequency_hz),
                    "marker_right_hz": float(stop_frequency_hz),
                    "center_frequency_hz": center_frequency_hz,
                    "bandwidth_hz": bandwidth_hz,
                    "sample_rate_hz": sample_rate_hz,
                    "duration_seconds": duration_seconds,
                    "iq_file": metadata["iq_file"],
                    "output_dir": str(output_dir),
                    "metadata_file": str(output_dir / "demodulation_report.json"),
                    "metadata_url": f"/api/demodulation/results/{demodulation_id}",
                    "rf_analysis_source": "computed_from_live_iq",
                    "demodulation_source": "computed_from_live_iq",
                }
            )
            result.setdefault("outputs", {})
            result["outputs"]["report"] = str(output_dir / "demodulation_report.json")
            Path(str(output_dir / "demodulation_report.json")).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        self._results[demodulation_id] = result
        self._persist_result_metadata(result)
        self._mode = mode
        return result

    def demodulate_dataset_capture(self, payload: dict) -> dict:
        normalized = self._normalize_dataset_input(payload)
        sample_id = normalized["sample_id"]
        demodulation_id = f"dataset_{sample_id}_{str(uuid.uuid4())[:8]}"
        output_dir = self._dataset_output_dir / sample_id
        output_dir.mkdir(parents=True, exist_ok=True)

        missing = self._missing_demodulation_metadata(normalized)
        pipeline = normalized.get("pipeline") or self._infer_pipeline(normalized)
        report = self._base_dataset_report(demodulation_id, normalized, pipeline, output_dir)

        if missing:
            report.update(
                {
                    "status": "missing_metadata",
                    "missing_metadata": missing,
                    "notes": [
                        "Demodulation was not attempted because critical metadata is missing.",
                        "Required fields include file_path, sample_rate_hz, center_frequency_hz and datatype.",
                    ],
                }
            )
            return self._finalize_dataset_result(report, output_dir)

        path = Path(str(normalized["file_path"])).expanduser()
        if not path.exists():
            report.update({"status": "missing_metadata", "notes": [f"RF input file not found: {path}"]})
            return self._finalize_dataset_result(report, output_dir)

        if not self._is_supported_rf_input(path, normalized.get("file_format")):
            report.update(
                {
                    "status": "unsupported_signal_type",
                    "notes": [f"Unsupported RF input format: {path.suffix or normalized.get('file_format')}"],
                }
            )
            return self._finalize_dataset_result(report, output_dir)

        if pipeline == "wifi_80211" and self._wifi_demod_v2_enabled() and self._wifi_worker_available():
            wifi_v2 = self._run_wifi_v2(normalized, path, output_dir)
            if (wifi_v2.get("external_worker") or {}).get("fallback_to_current_scaffold"):
                iq = self._read_complex_iq(path, str(normalized["datatype"]))
                fallback = self._run_iot_pipeline(iq, normalized, pipeline, output_dir)
                fallback["wifi_v2_worker_failure"] = wifi_v2.get("external_worker")
                fallback["notes"] = [*(fallback.get("notes") or []), "Wi-Fi V2 worker failed or rejected its input; the current scaffold was used without affecting other pipelines."]
                report.update(fallback)
            else:
                report.update(wifi_v2)
            return self._finalize_dataset_result(report, output_dir)

        iq = self._read_complex_iq(path, str(normalized["datatype"]))
        if iq.size == 0:
            report.update({"status": "rf_activity_only", "notes": ["RF file contained no readable complex samples."]})
            return self._finalize_dataset_result(report, output_dir)

        report["rf_activity"] = self._summarize_iq_activity(iq, float(normalized["sample_rate_hz"]))
        signal_detected = bool(report["rf_activity"]["signal_detected"])
        if pipeline in {"wfm_broadcast", "nfm", "am"}:
            audio_path = self._demodulate_audio_iq(iq, float(normalized["sample_rate_hz"]), pipeline, output_dir)
            report.update(
                {
                    "status": "media_recovered" if audio_path else ("rf_activity_only" if signal_detected else "sync_failed"),
                    "outputs": {
                        "audio": str(audio_path) if audio_path else None,
                        "report": str(output_dir / "demodulation_report.json"),
                    },
                    "audio_file": str(audio_path) if audio_path else None,
                    "audio_url": f"/api/demodulation/audio/{demodulation_id}" if audio_path else None,
                    "notes": [
                        "Analog audio was demodulated from stored IQ using a basic post-capture DSP path."
                        if audio_path
                        else "Audio demodulation did not produce a usable WAV file."
                    ],
                }
            )
            return self._finalize_dataset_result(report, output_dir)

        if pipeline in self.IOT_PIPELINES or pipeline in {"ieee802154_oqpsk", "ook_fsk_generic"}:
            decoded = self._run_iot_pipeline(iq, normalized, pipeline, output_dir)
            report.update(decoded)
            return self._finalize_dataset_result(report, output_dir)

        if pipeline == "adsb_1090":
            decoded = self._packet_scaffold("adsb", iq, normalized, output_dir)
            report.update(decoded)
            return self._finalize_dataset_result(report, output_dir)

        if pipeline == "ook_fsk_generic":
            decoded = self._simple_digital_scaffold(iq, normalized, output_dir)
            report.update(decoded)
            return self._finalize_dataset_result(report, output_dir)

        if pipeline in {"dvbt", "dvbs_s2", "lora_css"}:
            report.update(
                {
                    "status": "unsupported_signal_type" if pipeline == "dvbs_s2" else "sync_failed",
                    "outputs": {"report": str(output_dir / "demodulation_report.json")},
                    "notes": [
                        "This pipeline is registered for traceability, but a full protocol demodulator is not implemented in this build.",
                        "RF activity is reported separately and is not treated as successful demodulation.",
                    ],
                }
            )
            return self._finalize_dataset_result(report, output_dir)

        report.update(
            {
                "status": "unsupported_signal_type",
                "outputs": {"report": str(output_dir / "demodulation_report.json")},
                "notes": [f"No compatible demodulation pipeline for signal_type={normalized.get('signal_type')!r}."],
            }
        )
        return self._finalize_dataset_result(report, output_dir)

    def test_ble_advertising_channels(
        self,
        duration_seconds: float = 1.0,
        sample_rate_hz: float = 8_000_000.0,
        bandwidth_hz: float = 2_000_000.0,
    ) -> dict:
        if duration_seconds <= 0 or duration_seconds > 10:
            raise ValueError("duration_seconds must be between 0 and 10")
        channels = [
            {"channel": 37, "frequency_hz": 2_402_000_000.0},
            {"channel": 38, "frequency_hz": 2_426_000_000.0},
            {"channel": 39, "frequency_hz": 2_480_000_000.0},
        ]
        rows = []
        for item in channels:
            center = item["frequency_hz"]
            try:
                result = self.demodulate_marker_band(
                    start_frequency_hz=center - bandwidth_hz / 2.0,
                    stop_frequency_hz=center + bandwidth_hz / 2.0,
                    mode="ble_advertising",
                    duration_seconds=duration_seconds,
                    apply_bandpass_filter=False,
                )
                diagnostics = result.get("stage_diagnostics", {})
                rows.append(
                    {
                        "channel": item["channel"],
                        "frequency_hz": center,
                        "rf_activity": bool(result.get("rf_activity_detected")),
                        "bursts": int(result.get("burst_count") or diagnostics.get("burst_count") or 0),
                        "bitstream": bool(diagnostics.get("bitstream_recovered")),
                        "access_address": bool(result.get("access_address_detected")),
                        "packets": int(result.get("packets_decoded") or 0),
                        "candidates": int(result.get("packet_candidates") or diagnostics.get("packet_candidates") or 0),
                        "crc_valid": int(result.get("packets_crc_valid") or 0),
                        "status": result.get("final_status") or result.get("status"),
                        "result_id": result.get("id"),
                    }
                )
            except Exception as exc:
                rows.append(
                    {
                        "channel": item["channel"],
                        "frequency_hz": center,
                        "rf_activity": False,
                        "bursts": 0,
                        "bitstream": False,
                        "access_address": False,
                        "packets": 0,
                        "candidates": 0,
                        "crc_valid": 0,
                        "status": "error",
                        "error": str(exc),
                    }
                )
        return {
            "mode": "live_demodulation",
            "pipeline": "ble_advertising",
            "test": "ble_advertising_channels",
            "duration_seconds": duration_seconds,
            "sample_rate_hz": sample_rate_hz,
            "rows": rows,
        }

    def test_wifi_5ghz_channels(
        self,
        duration_seconds: float = 0.5,
        bandwidth_hz: float = 20_000_000.0,
    ) -> dict:
        if duration_seconds <= 0 or duration_seconds > 5:
            raise ValueError("duration_seconds must be between 0 and 5")
        if bandwidth_hz <= 0 or bandwidth_hz > 40_000_000:
            raise ValueError("bandwidth_hz must be between 0 and 40 MHz")

        channels = self._wifi_5ghz_channels()
        rows = []
        for item in channels:
            center = item["frequency_hz"]
            try:
                result = self.demodulate_marker_band(
                    start_frequency_hz=center - bandwidth_hz / 2.0,
                    stop_frequency_hz=center + bandwidth_hz / 2.0,
                    mode="wifi_80211",
                    duration_seconds=duration_seconds,
                    apply_bandpass_filter=False,
                )
                packets = result.get("decoded_packets", {})
                rows.append(
                    {
                        "channel": item["channel"],
                        "frequency_hz": center,
                        "rf_activity": bool(
                            result.get("rf_activity_detected")
                            or result.get("rf_activity", {}).get("signal_detected")
                            or result.get("rf_metrics", {}).get("rf_activity_detected")
                        ),
                        "frames": int(packets.get("frames_decoded") or 0),
                        "crc_valid": int(packets.get("frames_crc_valid") or 0),
                        "status": result.get("final_status") or result.get("status"),
                        "result_id": result.get("id"),
                    }
                )
            except Exception as exc:
                rows.append(
                    {
                        "channel": item["channel"],
                        "frequency_hz": center,
                        "rf_activity": False,
                        "frames": 0,
                        "crc_valid": 0,
                        "status": "error",
                        "error": str(exc),
                    }
                )
        return {
            "mode": "live_demodulation",
            "pipeline": "wifi_80211",
            "test": "wifi_5ghz_channels",
            "duration_seconds": duration_seconds,
            "bandwidth_hz": bandwidth_hz,
            "rows": rows,
        }

    def list_results(self) -> list[dict]:
        results = self._load_persisted_results()
        for result_id, result in self._results.items():
            results[result_id] = result
        return sorted(results.values(), key=lambda item: str(item.get("generated_at_utc", "")), reverse=True)

    def get_result(self, demodulation_id: str) -> dict:
        result = self._results.get(demodulation_id) or self._load_persisted_results().get(demodulation_id)
        if result is None:
            raise ValueError(f"Demodulation result not found: {demodulation_id}")
        return result

    def get_audio_file(self, demodulation_id: str) -> Path:
        result = self.get_result(demodulation_id)
        audio_file = result.get("audio_file")
        if not audio_file:
            raise ValueError(f"No audio available for demodulation result: {demodulation_id}")
        path = Path(audio_file)
        if not path.exists():
            raise ValueError(f"Audio file not found: {path}")
        return path

    def get_output_file(self, demodulation_id: str, filename: str) -> Path:
        result = self.get_result(demodulation_id)
        output_dir_value = result.get("output_dir")
        if output_dir_value:
            output_dir = Path(str(output_dir_value)).resolve()
            path = (output_dir / filename).resolve()
            try:
                path.relative_to(output_dir)
            except ValueError as exc:
                raise ValueError("Invalid output path") from exc
        else:
            path = self._legacy_output_path_from_result(result, filename)
        if not path.exists() or not path.is_file():
            raise ValueError(f"Output file not found: {filename}")
        return path

    def delete_result(self, demodulation_id: str) -> dict:
        result = self.get_result(demodulation_id)
        candidate_values = [
            result.get("metadata_file"),
            result.get("audio_file"),
            result.get("iq_file"),
        ]
        outputs = result.get("outputs")
        if isinstance(outputs, dict):
            candidate_values.extend(value for value in outputs.values() if value)
        removed_files: list[str] = []
        skipped_files: list[str] = []
        seen: set[str] = set()
        for value in candidate_values:
            if not value:
                continue
            try:
                path = Path(str(value)).resolve()
            except OSError:
                skipped_files.append(str(value))
                continue
            if str(path) in seen:
                continue
            seen.add(str(path))
            if not path.exists() or not path.is_file():
                continue
            if not self._is_safe_demodulation_file(path):
                skipped_files.append(str(path))
                continue
            path.unlink()
            removed_files.append(str(path))
        self._results.pop(demodulation_id, None)
        return {
            "id": demodulation_id,
            "deleted": True,
            "deleted_files": removed_files,
            "skipped_files": skipped_files,
        }

    def _persist_result_metadata(self, result: dict) -> None:
        metadata_file = result.get("metadata_file")
        if not metadata_file:
            return
        path = Path(str(metadata_file))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as file:
                json.dump(result, file, indent=2, ensure_ascii=False)
        except Exception:
            return

    def _load_persisted_results(self) -> dict[str, dict]:
        results: dict[str, dict] = {}
        if not self._output_dir.exists():
            paths: list[Path] = []
        else:
            # Flat root JSONs: plain marker-band captures (non-IoT) written by the
            # worker script.  Loaded first so that enriched nested reports overwrite
            # them when both exist for the same demodulation id.
            paths = list(self._output_dir.glob("*.json"))
            # Nested demodulation_report.json: live IoT pipeline results (BLE, Zigbee,
            # OOK-433, etc.) written by _run_iot_pipeline into a per-id subdirectory.
            paths.extend(self._output_dir.glob("*/demodulation_report.json"))
        if self._dataset_output_dir.exists():
            paths.extend(self._dataset_output_dir.glob("*/demodulation_report.json"))
        for path in paths:
            try:
                with path.open("r", encoding="utf-8") as file:
                    metadata = json.load(file)
                result = self._result_from_metadata(path, metadata)
                results[result["id"]] = result
            except Exception:
                continue
        return results

    def _is_safe_demodulation_file(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
            allowed_roots = (self._output_dir.resolve(), self._dataset_output_dir.resolve())
            if not any(self._path_is_relative_to(resolved, root) for root in allowed_roots):
                return False
            return resolved.suffix.lower() in {".json", ".wav", ".cfile", ".iq", ".bin", ".csv", ".ts", ".log", ".txt"}
        except (OSError, ValueError):
            return False

    def _legacy_output_path_from_result(self, result: dict, filename: str) -> Path:
        outputs = result.get("outputs")
        if isinstance(outputs, dict):
            for value in outputs.values():
                if not value:
                    continue
                candidate = Path(str(value)).resolve()
                if candidate.name == filename and self._is_safe_demodulation_file(candidate):
                    return candidate
        metadata_file = result.get("metadata_file")
        if metadata_file:
            candidate = (Path(str(metadata_file)).resolve().parent / filename).resolve()
            if self._is_safe_demodulation_file(candidate):
                return candidate
        raise ValueError(f"Output file not found: {filename}")

    def _path_is_relative_to(self, path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def _result_from_metadata(self, path: Path, metadata: dict) -> dict:
        demodulation_id = str(metadata.get("id") or "").strip()
        if not demodulation_id:
            stem = path.stem
            parts = stem.split("_")
            if len(parts) >= 2 and parts[0] == "marker":
                demodulation_id = parts[1]
            else:
                demodulation_id = stem
        audio_file = metadata.get("audio_file")
        result = {
            **metadata,
            "id": demodulation_id,
            "status": metadata.get("status") or "complete",
            "metadata_file": str(path.resolve()),
            "metadata_url": f"/api/demodulation/results/{demodulation_id}",
            "audio_url": f"/api/demodulation/audio/{demodulation_id}" if audio_file else None,
        }
        return result

    def start_wifi_dataset_job(self, payload: dict) -> dict:
        """Runs demodulate_dataset_capture (unchanged) off the request thread so a
        real V3 worker invocation -- which can take tens of seconds -- doesn't block
        the HTTP handler. Capture Lab is the intended caller for wifi_80211 payloads,
        but this wraps the same dataset-capture path any pipeline already uses."""
        job_id = job_tracker.create_job("wifi_80211_decode", description=str(payload.get("sample_id", "")))

        def _run() -> None:
            job_tracker.update_job(job_id, 10, "Running worker...")
            try:
                result = self.demodulate_dataset_capture(payload)
            except Exception as exc:  # noqa: BLE001 - report to the job, don't crash the thread
                job_tracker.fail_job(job_id, str(exc))
                return
            job_tracker.complete_job(job_id, result)

        threading.Thread(target=_run, daemon=True).start()
        return {"job_id": job_id}

    def get_wifi_dataset_job(self, job_id: str) -> dict:
        job = job_tracker.get_job(job_id)
        if job is None:
            raise ValueError(f"Unknown job_id: {job_id}")
        return job

    def _normalize_dataset_input(self, payload: dict) -> dict:
        normalized = dict(payload)
        path = self._resolve_sigmf_path(Path(str(normalized.get("file_path") or "")))
        normalized["file_path"] = str(path) if str(path) else ""
        if not normalized.get("file_format") and path.suffix:
            normalized["file_format"] = path.suffix.lower().lstrip(".")
        sigmf_meta = self._load_sigmf_metadata(path)
        if sigmf_meta:
            global_meta = sigmf_meta.get("global", {})
            captures = sigmf_meta.get("captures", [])
            first_capture = captures[0] if captures else {}
            normalized["sample_rate_hz"] = normalized.get("sample_rate_hz") or global_meta.get("core:sample_rate")
            normalized["center_frequency_hz"] = normalized.get("center_frequency_hz") or first_capture.get("core:frequency")
            normalized["datatype"] = normalized.get("datatype") or global_meta.get("core:datatype")
            normalized["source_dataset"] = normalized.get("source_dataset") or "sigmf"
        normalized["datatype"] = self._normalize_iq_datatype(normalized.get("datatype") or normalized.get("sample_dtype"))
        normalized["signal_type"] = (
            normalized.get("manual_signal_type")
            or normalized.get("signal_type")
            or normalized.get("modulation_class")
            or "unknown"
        )
        normalized["sample_id"] = str(normalized.get("sample_id") or Path(str(normalized.get("file_path"))).stem)
        return normalized

    def _missing_demodulation_metadata(self, data: dict) -> list[str]:
        missing = []
        for key in ("file_path", "sample_rate_hz", "center_frequency_hz", "datatype"):
            if data.get(key) in {None, ""}:
                missing.append(key)
        return missing

    def _resolve_sigmf_path(self, path: Path) -> Path:
        if path.suffix.lower() == ".sigmf-meta":
            data_path = Path(str(path)[:-11] + ".sigmf-data")
            return data_path if data_path.exists() else path
        return path

    def _load_sigmf_metadata(self, path: Path) -> dict | None:
        candidates = []
        if path.suffix.lower() == ".sigmf-meta":
            candidates.append(path)
        elif str(path).endswith(".sigmf-data"):
            candidates.append(Path(str(path)[:-11] + ".sigmf-meta"))
        else:
            candidates.append(path.with_suffix(".sigmf-meta"))
        for candidate in candidates:
            if candidate.exists():
                try:
                    return json.loads(candidate.read_text(encoding="utf-8"))
                except Exception:
                    return None
        return None

    def _normalize_iq_datatype(self, value: object) -> str:
        text = str(value or "").strip().lower()
        aliases = {
            "complex64": "cf32_le",
            "complex64_fc32_interleaved": "cf32_le",
            "fc32": "cf32_le",
            "cf32": "cf32_le",
            "cf32_le": "cf32_le",
            "ci16": "ci16_le",
            "ci16_le": "ci16_le",
            "int16": "ci16_le",
            "cu8": "cu8",
            "uint8": "cu8",
        }
        return aliases.get(text, text)

    def _is_supported_rf_input(self, path: Path, file_format: object = None) -> bool:
        suffix = path.suffix.lower()
        fmt = str(file_format or "").lower()
        return suffix in {".cfile", ".iq", ".bin", ".dat", ".sigmf-data"} or fmt in {
            "cfile",
            "iq",
            "bin",
            "dat",
            "sigmf-data",
            "sigmf",
        }

    def _read_complex_iq(self, path: Path, datatype: str, max_samples: int | None = 2_000_000) -> np.ndarray:
        dtype = self._normalize_iq_datatype(datatype)
        if dtype == "cf32_le":
            raw = np.fromfile(path, dtype="<f4", count=-1 if max_samples is None else max_samples * 2)
            raw = raw[: raw.size - (raw.size % 2)]
            return raw[0::2].astype(np.float32) + 1j * raw[1::2].astype(np.float32)
        if dtype == "ci16_le":
            raw = np.fromfile(path, dtype="<i2", count=-1 if max_samples is None else max_samples * 2).astype(np.float32)
            raw = raw[: raw.size - (raw.size % 2)] / 32768.0
            return raw[0::2] + 1j * raw[1::2]
        if dtype == "cu8":
            raw = np.fromfile(path, dtype=np.uint8, count=-1 if max_samples is None else max_samples * 2).astype(np.float32)
            raw = raw[: raw.size - (raw.size % 2)]
            raw = (raw - 127.5) / 127.5
            return raw[0::2] + 1j * raw[1::2]
        return np.array([], dtype=np.complex64)

    @staticmethod
    def _wifi_demod_v2_enabled() -> bool:
        # Selecting the wifi_80211 pipeline should use the real (validated V3)
        # decoder by default -- WIFI_DEMOD_V2 is now an opt-out, not an opt-in.
        return os.environ.get("WIFI_DEMOD_V2", "true").strip().lower() not in {"0", "false", "no", "off"}

    @staticmethod
    def _wifi_worker_available() -> bool:
        """WIFI_GR_IEEE80211_WORKER may be a single script path, or a full command
        ("<interpreter> <script>") when the worker needs a pinned interpreter other
        than this backend's own -- mirror WifiDecodeService.decode()'s shlex parsing
        here instead of treating the whole value as one file path. With no override,
        this resolves to the same validated V3 worker default decode() itself falls
        back to, so the two checks never disagree about whether a worker is set."""
        configured = os.environ.get("WIFI_GR_IEEE80211_WORKER", "").strip() or (default_worker_command() or "")
        if not configured:
            return False
        try:
            command = shlex.split(configured, posix=os.name != "nt")
        except ValueError:
            return False
        if not command:
            return False
        if len(command) == 1:
            return Path(command[0]).is_file()
        return all(Path(token).is_file() for token in command if token.lower().endswith((".exe", ".py")))

    def _run_wifi_v2(self, data: dict, path: Path, output_dir: Path) -> dict:
        datatype = str(data.get("datatype") or "")
        hardware_center = float(data.get("hardware_center_frequency_hz") or data.get("center_frequency_hz") or 0.0)
        channel_center = float(data.get("channel_center_frequency_hz") or data.get("center_frequency_hz") or 0.0)
        known_order = bool(data.get("temporal_order_known", False))
        contract = WifiCaptureContract(
            input_file=str(path), datatype=datatype,
            sample_rate_hz=float(data.get("sample_rate_hz") or 0.0),
            hardware_center_frequency_hz=hardware_center,
            channel_center_frequency_hz=channel_center,
            channel_width_hz=float(data.get("channel_width_hz") or data.get("bandwidth_hz") or 20_000_000.0),
            capture_start_utc=data.get("capture_start_utc") or data.get("timestamp_utc"),
            sample_count=sample_count(path, datatype),
            gain_db=float(data["gain_db"]) if data.get("gain_db") is not None else None,
            antenna=data.get("antenna") or data.get("antenna_port"),
            device_model=data.get("device_model") or data.get("sdr_model"),
            device_serial=data.get("device_serial") or data.get("sdr_serial"),
            source=str(data.get("source") or "dataset"), input_iq_sha256=sha256_file(path),
            overflow_count=int(data["overflow_count"]) if data.get("overflow_count") is not None else None,
            gaps_detected=bool(data["gaps_detected"]) if data.get("gaps_detected") is not None else None,
            dc_correction_applied=bool(data.get("dc_correction_applied", False)),
            iq_correction_applied=bool(data.get("iq_correction_applied", False)),
            filter_definition=dict(data.get("filter_definition") or {"applied": False, "stage": "raw_iq"}),
            decoder_mode=str(data.get("decoder_mode") or "auto"), temporal_order_known=known_order,
            metadata_evidence={
                "sample_rate_hz": "known" if data.get("sample_rate_hz") else "unknown",
                "datatype": "known" if data.get("datatype") else "unknown",
                "hardware_center_frequency_hz": "inferred" if not data.get("hardware_center_frequency_hz") else "known",
                "channel_center_frequency_hz": "inferred" if not data.get("channel_center_frequency_hz") else "known",
                "overflow_count": "known" if data.get("overflow_count") is not None else "unknown",
                "gaps_detected": "known" if data.get("gaps_detected") is not None else "unknown",
                "capture_start_utc": "known" if data.get("capture_start_utc") or data.get("timestamp_utc") else "unknown",
                "temporal_order_known": "known" if data.get("temporal_order_known") is not None else "unknown",
            },
        )
        return WifiDecodeService().decode(contract, output_dir)

    def _summarize_iq_activity(self, iq: np.ndarray, sample_rate_hz: float) -> dict:
        power = np.abs(iq) ** 2
        mean_power = float(np.mean(power)) if power.size else 0.0
        peak_power = float(np.max(power)) if power.size else 0.0
        rms = float(np.sqrt(mean_power))
        near_zero_ratio = float(np.mean(np.abs(iq) < 1e-6)) if iq.size else 1.0
        clipping_ratio = float(np.mean(np.abs(iq) > 0.98)) if iq.size else 0.0
        dynamic_db = 10.0 * np.log10(max(peak_power, 1e-20) / max(mean_power, 1e-20))
        return {
            "samples_analyzed": int(iq.size),
            "duration_seconds_analyzed": float(iq.size / max(sample_rate_hz, 1.0)),
            "mean_power_db": float(10.0 * np.log10(max(mean_power, 1e-20))),
            "peak_power_db": float(10.0 * np.log10(max(peak_power, 1e-20))),
            "rms_amplitude": rms,
            "near_zero_ratio": near_zero_ratio,
            "clipping_ratio": clipping_ratio,
            "dynamic_range_proxy_db": float(dynamic_db),
            "signal_detected": bool(iq.size > 0 and near_zero_ratio < 0.95 and peak_power > 1e-10),
        }

    def _infer_pipeline(self, data: dict) -> str:
        signal = str(data.get("signal_type") or "").lower()
        label = str(data.get("transmitter_label") or "").lower()
        joined = f"{signal} {label}"
        if "ble" in joined or "bluetooth" in joined:
            return "ble_advertising"
        if "wifi" in joined or "wi-fi" in joined or "802.11" in joined:
            return "wifi_80211"
        if "zigbee" in joined or "802.15.4" in joined or "ieee802154" in joined:
            return "zigbee_ieee802154"
        if "dvbt" in joined or "dvb-t" in joined:
            return "dvbt"
        if "ads-b" in joined or "adsb" in joined:
            return "adsb_1090"
        if "lora" in joined:
            return "lora_css"
        if "ook" in joined or "fsk" in joined or "gfsk" in joined:
            if "gfsk" in joined:
                return "generic_gfsk_iot"
            if "ook" in joined or "ask" in joined:
                return "ook_ask_iot_sensor"
            return "generic_fsk_iot"
        if signal in {"am", "fm", "wfm", "nfm"}:
            return "wfm_broadcast" if signal == "wfm" else signal
        return "ook_fsk_generic"

    def _live_capture_sample_rate_hz(self, mode: str, bandwidth_hz: float) -> float:
        configured_rate = float(self._settings.frequency.sample_rate_hz)
        if mode == "wifi_80211":
            if self._wifi_demod_v2_enabled() and self._wifi_worker_available():
                # The validated V3 worker requires an exact 20 MS/s channelized
                # capture (legacy 802.11a/g channels are always 20 MHz wide) --
                # capture at that fixed rate directly instead of deriving one
                # from the marker span, so live captures can feed the real
                # decoder the same way dataset/Capture Lab captures do.
                return 20_000_000.0
            required_rate = max(
                bandwidth_hz * 1.25,
                DEFAULT_USRP_B200_LIMITS.min_sample_rate_hz,
            )
            sample_rate_hz = min(
                max(configured_rate, required_rate),
                30_720_000.0,
                DEFAULT_USRP_B200_LIMITS.max_sample_rate_hz,
            )
        else:
            sample_rate_hz = min(
                max(
                    configured_rate,
                    bandwidth_hz * 4.0,
                    DEFAULT_USRP_B200_LIMITS.min_sample_rate_hz,
                ),
                DEFAULT_USRP_B200_LIMITS.max_sample_rate_hz,
            )
        validate_sample_rate(sample_rate_hz)
        return sample_rate_hz

    def _live_capture_timeout_seconds(self, duration_seconds: float, sample_rate_hz: float) -> float:
        sample_rate_msps = sample_rate_hz / 1_000_000.0
        if sample_rate_msps >= 20.0:
            return max(float(duration_seconds) + 90.0, 120.0)
        return max(float(duration_seconds) + 30.0, 45.0)

    def _live_worker_mode_for_pipeline(self, pipeline: str) -> str:
        if pipeline in {"ble_advertising", "generic_gfsk_iot", "generic_fsk_iot", "zigbee_ieee802154", "lora_css"}:
            return "fsk"
        if pipeline == "wifi_80211":
            return "psk"
        if pipeline in {"ook_ask_iot_sensor", "ook_433_remote"}:
            return "ook"
        if pipeline == "fsk_remote_decoder":
            return "fsk"
        return pipeline

    def _wifi_5ghz_channels(self) -> list[dict]:
        channels = [
            36, 40, 44, 48,
            52, 56, 60, 64,
            100, 104, 108, 112, 116, 120, 124, 128,
            132, 136, 140, 144,
            149, 153, 157, 161, 165,
        ]
        return [
            {"channel": channel, "frequency_hz": float((5000 + channel * 5) * 1_000_000)}
            for channel in channels
        ]

    def _wifi_24ghz_channels(self) -> list[dict]:
        return [
            {"channel": channel, "frequency_hz": float((2407 + channel * 5) * 1_000_000)}
            for channel in range(1, 14)
        ]

    def list_wifi_channels(self) -> dict:
        return {"channels_24ghz": self._wifi_24ghz_channels(), "channels_5ghz": self._wifi_5ghz_channels()}

    def _base_dataset_report(self, demodulation_id: str, data: dict, pipeline: str, output_dir: Path) -> dict:
        return {
            "id": demodulation_id,
            "sample_id": data.get("sample_id"),
            "dataset_id": data.get("dataset_id"),
            "source_dataset": data.get("source_dataset") or data.get("dataset_id") or "dataset_builder",
            "input_file": data.get("file_path"),
            "file_format": data.get("file_format"),
            "datatype": data.get("datatype"),
            "sample_rate_hz": data.get("sample_rate_hz"),
            "center_frequency_hz": data.get("center_frequency_hz"),
            "bandwidth_hz": data.get("bandwidth_hz"),
            "duration_seconds": data.get("capture_duration"),
            "signal_type": data.get("signal_type"),
            "device_profile": data.get("device_profile"),
            "demodulation_pipeline": pipeline,
            "pipeline": pipeline,
            "mode": "dataset_demodulation",
            "source": "dataset_builder",
            "rf_analysis_source": "computed_from_file_iq",
            "demodulation_source": "computed_from_file_iq",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "output_dir": str(output_dir),
            "status": "not_attempted",
            "final_status": "not_attempted",
            "outputs": {},
        }

    def _demodulate_audio_iq(self, iq: np.ndarray, sample_rate_hz: float, pipeline: str, output_dir: Path) -> Path | None:
        if iq.size < 16:
            return None
        if pipeline == "am":
            audio = np.abs(iq)
            audio = audio - np.mean(audio)
        else:
            phase = np.unwrap(np.angle(iq))
            audio = np.diff(phase, prepend=phase[0])
        audio_rate = 48_000
        step = max(1, int(round(sample_rate_hz / audio_rate)))
        audio = audio[::step]
        if audio.size < 16:
            return None
        if pipeline == "nfm":
            actual_rate = sample_rate_hz / step
            cutoff_norm = min(5000.0 / (actual_rate / 2.0), 0.95)
            n = 63
            t = np.arange(n) - (n - 1) / 2.0
            h = np.sinc(2.0 * cutoff_norm * t) * np.hamming(n)
            h = (h / h.sum()).astype(np.float32)
            audio = np.convolve(audio, h, mode="same")
        audio = audio - np.mean(audio)
        peak = float(np.max(np.abs(audio)))
        if not np.isfinite(peak) or peak <= 1e-12:
            return None
        audio_i16 = np.clip(audio / peak * 0.85, -1.0, 1.0)
        audio_i16 = (audio_i16 * 32767).astype("<i2")
        path = output_dir / "recovered_audio.wav"
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(int(sample_rate_hz / step))
            wav.writeframes(audio_i16.tobytes())
        return path

    def _ble_scaffold(self, iq: np.ndarray, data: dict, output_dir: Path) -> dict:
        receiver_chain_version = "ble_receiver_chain_diagnostics_v2"
        center = float(data.get("center_frequency_hz") or 0.0)
        sample_rate = float(data.get("sample_rate_hz") or 1.0)
        capture_bandwidth_hz = float(data.get("bandwidth_hz") or sample_rate)
        min_burst_duration_ms = float(data.get("min_burst_duration_ms") or 2.0)
        max_burst_duration_ms = float(data.get("max_burst_duration_ms") or 150.0)
        min_gap_duration_ms = float(data.get("min_gap_duration_ms") or 2.5)
        channel, channel_frequency_hz = self._ble_channel_from_frequency(center)
        profile_channel = self._extract_profile_ble_channel(data)
        channel_consistency = profile_channel is None or profile_channel == channel
        activity = self._summarize_iq_activity(iq, sample_rate)
        filtered_iq = iq.astype(np.complex64, copy=True)
        channel_filter_applied = False
        # Shift IQ so the BLE channel sits at DC before GFSK discrimination.
        # Without this, a 1 MHz offset (e.g. SDR at 2425 MHz for BLE CH38 at
        # 2426 MHz) biases the instantaneous-frequency estimate and, more
        # importantly, means the hardware receive filter is not centred on the
        # BLE channel â€” clipping one sideband and causing bit errors.
        freq_offset_hz = channel_frequency_hz - center
        freq_correction_applied = abs(freq_offset_hz) > 1000.0
        if freq_correction_applied:
            t = np.arange(len(filtered_iq), dtype=np.float64) / sample_rate
            filtered_iq *= np.exp(-2j * np.pi * float(freq_offset_hz) * t).astype(np.complex64)
        filtered_path = output_dir / "filtered_iq.cfile"
        filtered_iq.tofile(filtered_path)
        bursts = self._ble_burst_candidates(filtered_iq, sample_rate)
        burst_count = len(bursts)
        burst_metrics = self._ble_burst_metrics(bursts, sample_rate, activity, data)

        # --- Real GFSK demodulation + packet search ---
        raw_bits = self._ble_gfsk_demod(filtered_iq, sample_rate)
        bitstream_path = output_dir / "recovered_bitstream.bin"
        bitstream_path.write_bytes(np.packbits(raw_bits).tobytes() if raw_bits.size else b"")

        decoded_pkts = self._ble_decode_burst_packets(filtered_iq, sample_rate, bursts, channel)
        if not decoded_pkts:
            decoded_pkts = self._ble_search_packets(raw_bits, channel)
        candidate_pkts = decoded_pkts
        valid_pkts = [p for p in candidate_pkts if p.get("crc_valid", False)]
        n_candidates = len(candidate_pkts)
        n_decoded = len(valid_pkts)
        n_crc_valid = len(valid_pkts)
        aa_detected = n_candidates > 0

        # Legacy AA correlation search (kept for diagnostics)
        aa_search = self._search_ble_access_address(raw_bits)
        aa_detected = bool(aa_search.get("access_address_detected"))

        # Build output packet list for the frontend
        def _packet_view(packet: dict, index: int) -> dict:
            return {
                "index": index,
                "bit_offset": packet.get("bit_offset", 0),
                "timestamp_seconds": packet.get("bit_offset", 0) / 1_000_000.0,
                "channel": channel,
                "pdu_type": packet.get("pdu_type"),
                "advertiser_address": packet.get("advertiser_address"),
                "payload_hex": packet.get("payload_hex"),
                "payload_fields": packet.get("payload_fields"),
                "crc_valid": packet.get("crc_valid", False),
                "crc_computed": packet.get("crc_computed"),
                "crc_received": packet.get("crc_received"),
                "polarity": packet.get("polarity", "normal"),
                "sync_source": packet.get("sync_source"),
                "phase_adjust_bits": packet.get("phase_adjust_bits"),
                "burst_index": packet.get("burst_index"),
                "symbol_phase_samples": packet.get("symbol_phase_samples"),
                "symbol_phase_selected": packet.get("symbol_phase_selected", packet.get("symbol_phase_samples")),
                "access_address_match_score": packet.get("access_address_match_score"),
                "pdu_start_bit": packet.get("pdu_start_bit", packet.get("bit_offset", 0)),
                "pdu_start_adjustment": packet.get("pdu_start_adjustment", packet.get("phase_adjust_bits")),
                "dewhitening_channel": packet.get("dewhitening_channel", channel),
                "computed_crc": packet.get("computed_crc", packet.get("crc_computed")),
                "received_crc": packet.get("received_crc", packet.get("crc_received")),
                "crc_match": packet.get("crc_match", packet.get("crc_valid", False)),
                "crc_diagnostic_variants": packet.get("crc_diagnostic_variants"),
                "rejection_reason": packet.get("rejection_reason"),
                "trust_level": "crc_valid" if packet.get("crc_valid", False) else "candidate_unvalidated",
            }

        pkt_list = [
            _packet_view(p, i)
            for i, p in enumerate(valid_pkts)
        ]
        candidate_list = [
            _packet_view(p, i)
            for i, p in enumerate(candidate_pkts)
        ]
        advertiser_addresses = list({p["advertiser_address"] for p in pkt_list if p.get("advertiser_address")})
        pdu_types = list({p["pdu_type"] for p in pkt_list if p.get("pdu_type")})

        packets_out = {
            "receiver_chain_version": receiver_chain_version,
            "protocol": "bluetooth_low_energy",
            "pipeline": "ble_advertising",
            "channel": channel,
            "channel_frequency_mhz": channel_frequency_hz / 1e6,
            "access_address_detected": aa_detected,
            "access_address": "0x8E89BED6",
            "packets_decoded": n_decoded,
            "packet_candidates": n_candidates,
            "packets_crc_valid": n_crc_valid,
            "advertiser_addresses": advertiser_addresses,
            "pdu_types": pdu_types,
            "payload_extractable": n_crc_valid > 0,
            "packets": pkt_list,
            "candidate_packets": candidate_list,
        }

        burst_path = output_dir / "burst_candidates.json"
        burst_path.write_text(
            json.dumps(
                {
                    "burst_count": burst_count,
                    "bursts": [
                        {
                            "burst_index": index,
                            "start_sample": start,
                            "stop_sample": stop,
                            "start_seconds": start / sample_rate,
                            "duration_us": (stop - start) / sample_rate * 1_000_000.0,
                        }
                        for index, (start, stop) in enumerate(bursts)
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        aa_path = output_dir / "access_address_search.json"
        aa_path.write_text(json.dumps(aa_search, indent=2), encoding="utf-8")
        packet_path = output_dir / "decoded_packets.json"
        packet_path.write_text(json.dumps(packets_out, indent=2), encoding="utf-8")
        diagnostics_path = output_dir / "candidate_diagnostics.json"
        diagnostics_path.write_text(
            json.dumps(
                {
                    "receiver_chain_version": receiver_chain_version,
                    "receiver_chain": [
                        "iq_input",
                        "frequency_correction",
                        "channel_filtering",
                        "burst_detection",
                        "symbol_timing_recovery",
                        "gfsk_demodulation",
                        "preamble_detection",
                        "access_address_validation",
                        "pdu_boundary_estimation",
                        "dewhitening",
                        "crc24_validation",
                        "pdu_parsing",
                        "report_generation",
                    ],
                    "candidate_count": n_candidates,
                    "crc_valid_count": n_crc_valid,
                    "candidates": candidate_list,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        logs_path = output_dir / "logs.txt"
        warning = None if channel_consistency else "Selected BLE channel does not match tuned center frequency"
        log_lines = [
            "BLE advertising demodulation run",
            f"receiver_chain_version={receiver_chain_version}",
            f"center_frequency_hz={center}",
            f"computed_ble_channel={channel}",
            f"channel_frequency_hz={channel_frequency_hz}",
            f"frequency_correction_applied={freq_correction_applied}",
            f"frequency_correction_hz={freq_offset_hz if freq_correction_applied else 0.0}",
            f"profile_ble_channel={profile_channel}",
            f"iq_samples_analyzed={int(iq.size)}",
            f"iq_duration_analyzed_seconds={float(iq.size / max(sample_rate, 1.0))}",
            f"rf_activity_detected={bool(activity.get('signal_detected'))}",
            f"burst_count={burst_count}",
            f"gfsk_bits_extracted={int(raw_bits.size)}",
            f"access_address_detected={aa_detected}",
            f"packet_candidates={n_candidates}",
            f"packets_decoded={n_decoded}",
            f"packets_crc_valid={n_crc_valid}",
        ]
        logs_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
        stage_diagnostics = {
            "receiver_chain_version": receiver_chain_version,
            "iq_loaded": bool(iq.size > 0),
            "iq_samples_analyzed": int(iq.size),
            "iq_duration_analyzed_seconds": float(iq.size / max(sample_rate, 1.0)),
            "channel_filter_applied": channel_filter_applied,
            "channel_filter_note": "No additional BLE FIR channel filter was applied; IQ came from the selected marker capture bandwidth.",
            "frequency_correction_applied": freq_correction_applied,
            "frequency_correction_hz": float(freq_offset_hz) if freq_correction_applied else 0.0,
            "rf_activity_detected": bool(activity.get("signal_detected")),
            "burst_detection_attempted": True,
            "burst_count": burst_count,
            "gfsk_demodulation_attempted": True,
            "gfsk_bits_extracted": int(raw_bits.size),
            "bitstream_recovered": bool(raw_bits.size > 0),
            "access_address_search_attempted": True,
            "access_address_detected": aa_detected,
            "ble_packet_reconstruction_attempted": True,
            "pdu_boundary_adjustments_tested": [-4, -3, -2, -1, 0, 1, 2, 3, 4],
            "dewhitening_attempted": n_candidates > 0,
            "dewhitening_channel": channel,
            "packet_candidates": n_candidates,
            "packets_decoded": n_decoded,
            "crc_validation_attempted": True,
            "packets_crc_valid": n_crc_valid,
            "candidate_diagnostics_written": True,
        }
        warnings = [warning] if warning else []
        if freq_correction_applied:
            hw_bw_hz = float(data.get("bandwidth_hz") or sample_rate)
            hw_margin = hw_bw_hz / 2.0 - abs(freq_offset_hz)
            if hw_margin < 500_000:
                warnings.append(
                    f"SDR center ({center/1e6:.3f} MHz) is {abs(freq_offset_hz)/1e3:.0f} kHz from BLE "
                    f"CH{channel} ({channel_frequency_hz/1e6:.0f} MHz). The hardware receive filter "
                    f"(Â±{hw_bw_hz/2/1e6:.1f} MHz) may have clipped one sideband â€” re-tune the SDR to "
                    f"{channel_frequency_hz/1e6:.0f} MHz for best results. "
                    f"Software frequency correction ({freq_offset_hz/1e3:+.0f} kHz) has been applied."
                )
            else:
                warnings.append(
                    f"SDR center offset {freq_offset_hz/1e3:+.0f} kHz from BLE CH{channel}; "
                    f"software frequency correction applied."
                )
        if activity.get("signal_detected") and not aa_detected:
            warnings.append("RF activity detected but no valid BLE advertising packet was recovered. "
                            "The signal may not be BLE, or the frequency/gain may need adjustment.")
        if aa_detected and n_candidates == 0:
            warnings.append("BLE Access Address was detected, but packet reconstruction did not recover a valid advertising PDU.")
        if n_candidates > 0 and n_crc_valid == 0:
            warnings.append("BLE packet candidates were reconstructed, but none passed CRC validation. Treat addresses, PDU types and payload fields as unvalidated candidates.")
        final_status = (
            "decoded_with_valid_crc" if aa_detected and n_decoded >= 1 and n_crc_valid >= 1
            else "ble_candidate_not_decoded" if activity.get("signal_detected")
            else "rf_activity_only"
        )
        return {
            "ble_receiver_chain_version": receiver_chain_version,
            "status": "complete" if final_status == "decoded_with_valid_crc" else "rf_activity_only",
            "final_status": final_status,
            "valid_demodulation": final_status == "decoded_with_valid_crc",
            "protocol": "bluetooth_low_energy",
            "pipeline": "ble_advertising",
            "computed_ble_channel": channel,
            "profile_ble_channel": profile_channel,
            "channel_consistency": channel_consistency,
            "warning": warning,
            "warnings": [w for w in warnings if w],
            "channel": channel,
            "channel_frequency_mhz": channel_frequency_hz / 1e6,
            "frequency_correction_applied": freq_correction_applied,
            "frequency_correction_hz": float(freq_offset_hz) if freq_correction_applied else 0.0,
            "rf_activity_detected": bool(activity.get("signal_detected")),
            "burst_count": burst_count,
            "access_address_detected": aa_detected,
            "access_address": "0x8E89BED6",
            "packet_candidates": n_candidates,
            "packets_decoded": n_decoded,
            "packets_crc_valid": n_crc_valid,
            "confidence_score": min(1.0, n_crc_valid / 3.0) if n_crc_valid > 0 else None,
            "stage_diagnostics": stage_diagnostics,
            "burst_metrics": burst_metrics,
            "access_address_search": aa_search,
            "outputs": {
                "filtered_iq": str(filtered_path),
                "burst_candidates": str(burst_path),
                "bitstream": str(bitstream_path),
                "access_address_search": str(aa_path),
                "candidate_diagnostics": str(diagnostics_path),
                "decoded_packets": str(packet_path),
                "report": str(output_dir / "demodulation_report.json"),
                "logs": str(logs_path),
            },
            "decoded_packets": packets_out,
            "notes": (
                [f"Decoded {n_decoded} BLE advertising packet(s), {n_crc_valid} CRC-valid."]
                if n_crc_valid > 0
                else ["Signal is compatible with the BLE advertising pipeline, but no CRC-valid packet was recovered."]
            ),
            "warnings": warnings,
        }

    def _run_iot_pipeline(self, iq: np.ndarray, data: dict, pipeline: str, output_dir: Path) -> dict:
        started = perf_counter()
        if pipeline == "ble_advertising":
            result = self._ble_scaffold(iq, data, output_dir)
            result.update(self._iot_common_envelope(iq, data, pipeline, "bluetooth_low_energy", "gfsk", "ble_advertising_decoder"))
        elif pipeline == "generic_gfsk_iot":
            result = self._generic_gfsk_iot(iq, data, output_dir)
        elif pipeline == "wifi_80211":
            result = self._wifi_80211_scaffold(iq, data, output_dir)
            result.update(self._iot_common_envelope(iq, data, "wifi_80211", "wifi_80211", "ofdm_dsss", "ieee80211_frame_parser"))
        elif pipeline == "ook_ask_iot_sensor":
            result = self._ook_ask_iot_sensor(iq, data, output_dir)
        elif pipeline == "generic_fsk_iot":
            result = self._generic_fsk_iot(iq, data, output_dir)
        elif pipeline in {"zigbee_ieee802154", "ieee802154_oqpsk"}:
            result = self._zigbee_ieee802154(iq, data, output_dir)
            result.update(self._iot_common_envelope(iq, data, "zigbee_ieee802154", "ieee802154", "oqpsk_dsss", "ieee802154_frame_decoder"))
        elif pipeline == "lora_css":
            result = self._packet_scaffold("lora", iq, data, output_dir)
            result.update(self._iot_common_envelope(iq, data, "lora_css", "lora", "css", "lora_packet_decoder"))
            result["demodulation_level_reached"] = "rf_activity_only"
        elif pipeline == "ook_433_remote":
            result = self._ook_433_remote(iq, data, output_dir)
            result.update(self._iot_common_envelope(iq, data, "ook_433_remote", "ook_remote_control", "ook_ask", "ev1527_pt2262_decoder"))
        elif pipeline == "fsk_remote_decoder":
            result = self._fsk_remote_decoder(iq, data, output_dir)
            result.update(self._iot_common_envelope(iq, data, "fsk_remote_decoder", "fsk_remote_control", "2fsk", "fsk_remote_candidate_decoder"))
        else:
            result = self._simple_digital_scaffold(iq, data, output_dir)
            result.update(self._iot_common_envelope(iq, data, pipeline, "generic_iot", "unknown", None))
        result["processing_time_ms"] = int((perf_counter() - started) * 1000)
        result["version"] = "1.0"
        result.setdefault("warnings", [])
        result.setdefault("fingerprint_data", self._fingerprint_data_from_iq(iq, data))
        result.setdefault("final_status", result.get("status", "not_attempted"))
        return result

    def _iot_common_envelope(
        self,
        iq: np.ndarray,
        data: dict,
        pipeline: str,
        iot_family: str,
        physical_demodulator: str,
        protocol_decoder: str | None,
    ) -> dict:
        rf_metrics = self._rf_metrics_from_iq(iq, data)
        return {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "pipeline_name": pipeline,
            "iot_family": iot_family,
            "physical_demodulator": physical_demodulator,
            "protocol_decoder": protocol_decoder,
            "input": {
                "source": data.get("source_dataset") or data.get("source") or "dataset",
                "center_frequency_hz": data.get("center_frequency_hz"),
                "sample_rate_sps": data.get("sample_rate_hz"),
                "duration_seconds": data.get("capture_duration"),
                "file_path": data.get("file_path"),
            },
            "rf_metrics": rf_metrics,
            "signal_quality": {
                "snr_estimated_db": rf_metrics["snr_estimated_db"],
                "frequency_offset_hz": rf_metrics["frequency_offset_hz"],
                "peak_power_dbm": rf_metrics["peak_power_dbm"],
            },
        }

    def _rf_metrics_from_iq(self, iq: np.ndarray, data: dict) -> dict:
        activity = self._summarize_iq_activity(iq, float(data.get("sample_rate_hz") or 1.0))
        magnitude = np.abs(iq) if iq.size else np.array([], dtype=np.float32)
        snr = float(max(0.0, activity.get("dynamic_range_proxy_db", 0.0) - 3.0))
        iq_i = np.real(iq)
        iq_q = np.imag(iq)
        i_power = float(np.mean(iq_i * iq_i)) if iq.size else 0.0
        q_power = float(np.mean(iq_q * iq_q)) if iq.size else 0.0
        imbalance = float(10.0 * np.log10(max(i_power, 1e-20) / max(q_power, 1e-20)))
        return {
            "snr_estimated_db": snr,
            "frequency_offset_hz": 0.0,
            "timing_offset_samples": 0,
            "peak_power_dbm": float(activity.get("peak_power_db", -200.0)),
            "iq_imbalance_db": imbalance,
            "rf_activity_detected": bool(activity.get("signal_detected")),
            "estimated_bandwidth_hz": data.get("bandwidth_hz"),
        }

    def _fingerprint_data_from_iq(self, iq: np.ndarray, data: dict) -> dict:
        activity = self._summarize_iq_activity(iq, float(data.get("sample_rate_hz") or 1.0))
        return {
            "sample_count": int(iq.size),
            "mean_power_db": activity.get("mean_power_db"),
            "peak_power_db": activity.get("peak_power_db"),
            "near_zero_ratio": activity.get("near_zero_ratio"),
            "clipping_ratio": activity.get("clipping_ratio"),
            "confidence_source": "computed_from_iq",
        }

    def _generic_gfsk_iot(self, iq: np.ndarray, data: dict, output_dir: Path) -> dict:
        bits, hex_text = self._frequency_discriminator_bits(iq)
        payload_path, bitstream_path = self._write_bitstream_outputs(bits, hex_text, output_dir)
        bitstream_recovered = bits.size >= 64
        warnings = [] if bitstream_recovered else ["SNR too low or capture too short for bit recovery"]
        if bits.size and bits.size < 512:
            warnings.append("Short bitstream; symbol rate confidence below 80%")
        common = self._iot_common_envelope(iq, data, "generic_gfsk_iot", "generic_iot", "gfsk", None)
        return {
            **common,
            "estimation_results": {
                "symbol_rate_estimated_baud": self._estimate_symbol_rate(iq, data),
                "symbol_rate_confidence": 0.65 if bitstream_recovered else 0.0,
                "symbol_rate_range": [],
                "frequency_deviation_hz": self._estimate_frequency_deviation(iq, data),
                "clock_recovery_locked": bool(bitstream_recovered),
            },
            "demodulation_results": {
                "bitstream_recovered": bool(bitstream_recovered),
                "bits_count": int(bits.size),
                "bytes_count": int(bits.size // 8),
                "preamble_detected": "55" in hex_text[:32] or "aa" in hex_text[:32].lower(),
                "preamble_pattern": "0x55" if "55" in hex_text[:32] else ("0xAA" if "aa" in hex_text[:32].lower() else None),
            },
            "extracted_data": {"bitstream_hex": hex_text[:4096], "payloads_hex": [hex_text[:512]] if hex_text else [], "payload_extractable": False},
            "demodulation_level_reached": "physical_demodulation_recovered_bitstream" if bitstream_recovered else "rf_activity_only",
            "final_status": "bitstream_recovered" if bitstream_recovered else "rf_activity_only",
            "status": "bitstream_recovered" if bitstream_recovered else "rf_activity_only",
            "valid_demodulation": False,
            "confidence_score": None,
            "outputs": {"bitstream": str(bitstream_path), "decoded_payload": str(payload_path), "report": str(output_dir / "demodulation_report.json")},
            "warnings": warnings or ["No known protocol decoder available"],
        }

    def _generic_fsk_iot(self, iq: np.ndarray, data: dict, output_dir: Path) -> dict:
        result = self._generic_gfsk_iot(iq, data, output_dir)
        result.update(self._iot_common_envelope(iq, data, "generic_fsk_iot", "generic_iot", "fsk", None))
        deviation = self._estimate_frequency_deviation(iq, data)
        result["estimation_results"].update(
            {
                "frequency_deviation_hz": deviation,
                "frequency_deviation_confidence": 0.72 if result["demodulation_results"]["bitstream_recovered"] else 0.0,
                "mark_frequency_offset_hz": deviation / 2.0,
                "space_frequency_offset_hz": -deviation / 2.0,
            }
        )
        result["pipeline_name"] = "generic_fsk_iot"
        return result

    def _ook_ask_iot_sensor(self, iq: np.ndarray, data: dict, output_dir: Path) -> dict:
        sample_rate = float(data.get("sample_rate_hz") or 1.0)
        envelope = np.abs(iq)
        if envelope.size == 0:
            bits = np.array([], dtype=np.uint8)
            active = np.array([], dtype=bool)
        else:
            threshold = float(np.median(envelope) + 0.75 * np.std(envelope))
            active = envelope > threshold
            stride = max(1, int(sample_rate / 20_000.0))
            bits = active[::stride].astype(np.uint8)
        hex_text = np.packbits(bits).tobytes().hex() if bits.size else ""
        payload_path, bitstream_path = self._write_bitstream_outputs(bits, hex_text, output_dir)
        bursts = self._detect_boolean_runs(active, sample_rate)
        burst_durations = [round((stop - start) / sample_rate * 1000.0, 3) for start, stop in bursts]
        gaps = [round((bursts[i][0] - bursts[i - 1][1]) / sample_rate * 1000.0, 3) for i in range(1, len(bursts))]
        bitstream_recovered = bits.size >= 64 and len(bursts) > 0
        common = self._iot_common_envelope(iq, data, "ook_ask_iot_sensor", "generic_iot_sensor", "ook_ask", None)
        return {
            **common,
            "burst_analysis": {
                "burst_count": len(bursts),
                "burst_durations_ms": burst_durations,
                "inter_burst_gaps_ms": gaps,
                "repetition_interval_ms": float(np.median(gaps)) if gaps else None,
                "repetition_confidence": 0.8 if len(gaps) >= 2 else 0.0,
            },
            "symbol_rate_analysis": {
                "symbol_rates_estimated": [int(sample_rate / max(1, int(sample_rate / 20_000.0)))] if bitstream_recovered else [],
                "symbol_rate_mean_baud": int(sample_rate / max(1, int(sample_rate / 20_000.0))) if bitstream_recovered else None,
                "symbol_rate_std_dev": 0.0,
                "consistency": 0.65 if bitstream_recovered else 0.0,
            },
            "pulse_timing": self._pulse_timing(active, sample_rate),
            "demodulation_results": {
                "bitstream_recovered": bool(bitstream_recovered),
                "bits_per_burst": [int(duration / 1000.0 * 20_000.0) for duration in burst_durations],
                "total_bits": int(bits.size),
                "alignment_confidence": 0.55 if bitstream_recovered else 0.0,
            },
            "extracted_data": {
                "payloads_hex": [hex_text[:512]] if hex_text else [],
                "payload_pattern_detected": False,
                "payload_pattern_hex": None,
            },
            "demodulation_level_reached": "physical_demodulation_recovered_bitstream" if bitstream_recovered else "rf_activity_only",
            "final_status": "bitstream_recovered" if bitstream_recovered else "rf_activity_only",
            "status": "bitstream_recovered" if bitstream_recovered else "rf_activity_only",
            "valid_demodulation": False,
            "confidence_score": None,
            "fingerprint_usable": bool(bitstream_recovered and len(bursts) > 0),
            "outputs": {"bitstream": str(bitstream_path), "decoded_payload": str(payload_path), "report": str(output_dir / "demodulation_report.json")},
            "warnings": [] if bitstream_recovered else ["No stable OOK/ASK burst bitstream recovered"],
        }

    def _frequency_discriminator_bits(self, iq: np.ndarray) -> tuple[np.ndarray, str]:
        if iq.size < 4:
            return np.array([], dtype=np.uint8), ""
        phase_delta = np.angle(iq[1:] * np.conj(iq[:-1]))
        phase_delta = phase_delta - np.median(phase_delta)
        stride = max(1, int(phase_delta.size / 8192))
        soft = phase_delta[::stride]
        bits = (soft > 0).astype(np.uint8)
        return bits, np.packbits(bits).tobytes().hex()

    def _write_bitstream_outputs(self, bits: np.ndarray, hex_text: str, output_dir: Path) -> tuple[Path, Path]:
        bitstream_path = output_dir / "bitstream.bin"
        payload_path = output_dir / "decoded_payload.json"
        bitstream_path.write_bytes(np.packbits(bits).tobytes() if bits.size else b"")
        payload_path.write_text(
            json.dumps(
                {
                    "bit_count": int(bits.size),
                    "bytes_count": int(bits.size // 8),
                    "bitstream_hex": hex_text[:4096],
                    "payload_extractable": False,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return payload_path, bitstream_path

    def _estimate_symbol_rate(self, iq: np.ndarray, data: dict) -> int | None:
        sample_rate = float(data.get("sample_rate_hz") or 0.0)
        if iq.size < 32 or sample_rate <= 0:
            return None
        return int(min(max(sample_rate / max(1, iq.size / 4096.0), 1_000.0), 2_000_000.0))

    def _estimate_frequency_deviation(self, iq: np.ndarray, data: dict) -> float | None:
        sample_rate = float(data.get("sample_rate_hz") or 0.0)
        if iq.size < 4 or sample_rate <= 0:
            return None
        phase_delta = np.angle(iq[1:] * np.conj(iq[:-1]))
        freq = phase_delta * sample_rate / (2.0 * np.pi)
        return float(np.percentile(freq, 90) - np.percentile(freq, 10))

    def _detect_boolean_runs(self, active: np.ndarray, sample_rate: float) -> list[tuple[int, int]]:
        if active.size == 0:
            return []
        padded = np.concatenate([[False], active.astype(bool), [False]])
        edges = np.flatnonzero(padded[1:] != padded[:-1])
        runs = list(zip(edges[0::2], edges[1::2]))
        min_len = max(1, int(sample_rate * 0.0001))
        return [(int(start), int(stop)) for start, stop in runs if stop - start >= min_len]

    def _estimate_burst_count(self, iq: np.ndarray, sample_rate: float) -> int:
        if iq.size == 0:
            return 0
        envelope = np.abs(iq)
        threshold = float(np.median(envelope) + 1.5 * np.std(envelope))
        active = envelope > threshold
        return len(self._detect_boolean_runs(active, sample_rate))

    def _ble_channel_from_frequency(self, center_frequency_hz: float) -> tuple[int, float]:
        channels = {
            37: 2_402_000_000.0,
            38: 2_426_000_000.0,
            39: 2_480_000_000.0,
        }
        channel = min(channels, key=lambda item: abs(channels[item] - center_frequency_hz))
        return channel, channels[channel]

    def _extract_profile_ble_channel(self, data: dict) -> int | None:
        for key in ("profile_ble_channel", "ble_channel", "channel"):
            value = data.get(key)
            try:
                if value is not None and str(value) != "":
                    parsed = int(value)
                    if parsed in {37, 38, 39}:
                        return parsed
            except (TypeError, ValueError):
                pass
        text = " ".join(str(data.get(key) or "") for key in ("signal_type", "device_profile", "pipeline", "sample_id"))
        for channel in (37, 38, 39):
            if f"ch{channel}" in text.lower() or f"_{channel}" in text.lower():
                return channel
        return None

    def _ble_burst_candidates(self, iq: np.ndarray, sample_rate: float) -> list[tuple[int, int]]:
        if iq.size == 0:
            return []
        envelope = np.abs(iq)
        threshold = float(np.median(envelope) + 2.0 * np.std(envelope))
        active = envelope > threshold
        runs = self._detect_boolean_runs(active, sample_rate)
        min_samples = max(1, int(sample_rate * 80e-6))
        max_samples = max(min_samples, int(sample_rate * 2.5e-3))
        return [(start, stop) for start, stop in runs if min_samples <= stop - start <= max_samples]

    def _ble_burst_metrics(self, bursts: list[tuple[int, int]], sample_rate: float, activity: dict, data: dict) -> dict:
        durations = np.array([(stop - start) / sample_rate * 1_000_000.0 for start, stop in bursts], dtype=float)
        return {
            "burst_count": len(bursts),
            "average_burst_duration_us": float(np.mean(durations)) if durations.size else None,
            "min_burst_duration_us": float(np.min(durations)) if durations.size else None,
            "max_burst_duration_us": float(np.max(durations)) if durations.size else None,
            "expected_ble_burst_window_us": [80, 600],
            "estimated_bandwidth_hz": data.get("bandwidth_hz"),
            "snr_estimate_db": activity.get("dynamic_range_proxy_db"),
        }

    def _search_ble_access_address(self, bits: np.ndarray) -> dict:
        target_hex = "8E89BED6"
        target = np.array([int(bit) for bit in f"{int(target_hex, 16):032b}"], dtype=np.uint8)
        variants = []
        variants.append(("normal", "normal", target))
        variants.append(("reversed", "normal", target[::-1]))
        variants.append(("normal", "inverted", 1 - target))
        variants.append(("reversed", "inverted", 1 - target[::-1]))
        max_score = 0
        exact_matches = 0
        near_matches = 0
        best: dict | None = None
        top_matches: list[dict] = []
        if bits.size >= 32:
            for bit_order, polarity, pattern in variants:
                for offset in range(0, bits.size - 31):
                    score = int(np.sum(bits[offset : offset + 32] == pattern))
                    if score > max_score:
                        max_score = score
                        best = {"bit_offset": offset, "bit_order": bit_order, "polarity": polarity}
                    if score >= 24:
                        top_matches.append({
                            "bit_offset": int(offset),
                            "bit_order": bit_order,
                            "polarity": polarity,
                            "score": score,
                        })
                    if score == 32:
                        exact_matches += 1
                    if score >= 28:
                        near_matches += 1
        top_matches = sorted(top_matches, key=lambda item: item["score"], reverse=True)[:50]
        return {
            "target": "0x8E89BED6",
            "exact_matches": exact_matches,
            "near_matches": near_matches,
            "max_correlation_score": float(max_score),
            "bit_order_tested": ["normal", "reversed"],
            "polarity_tested": ["normal", "inverted"],
            "access_address_detected": exact_matches > 0 or max_score >= 28,
            "best_match": best,
            "top_matches": top_matches,
        }

    # ------------------------------------------------------------------
    # BLE GFSK demodulation helpers
    # ------------------------------------------------------------------

    def _ble_int_from_bits(self, bits: np.ndarray, n: int, offset: int = 0) -> int:
        """Integer from n LSB-first bits starting at offset."""
        if offset + n > bits.size:
            return 0
        val = 0
        for i in range(n):
            val |= (int(bits[offset + i]) << i)
        return val

    def _ble_dewhiten_bits(self, bits: np.ndarray, channel: int) -> np.ndarray:
        """BLE data whitening/de-whitening: 7-bit LFSR x^7+x^4+1, init = 1||ch[5:0]."""
        ch = int(channel) & 0x3F
        lfsr = 0x40 | ch
        result = bits.copy()
        for i in range(len(bits)):
            out = (lfsr >> 6) & 1
            result[i] = bits[i] ^ out
            fb = ((lfsr >> 6) ^ (lfsr >> 3)) & 1
            lfsr = ((lfsr << 1) & 0x7F) | fb
        return result

    def _ble_crc24_bits(self, bits: np.ndarray, init: int = 0x555555) -> int:
        """BLE CRC-24 over individual bits in transmission order. Poly = x^24+x^10+x^9+x^6+x^4+x^3+x+1."""
        crc = init & 0xFFFFFF
        for bit in bits:
            d = (int(bit) ^ ((crc >> 23) & 1)) & 1
            crc = (crc << 1) & 0xFFFFFF
            if d:
                crc ^= 0x00065B
        return crc

    def _ble_crc24_bits_reflected(self, bits: np.ndarray, init: int = 0x555555) -> int:
        """Diagnostic reflected CRC-24 variant for checking BLE bit-order mistakes."""
        crc = init & 0xFFFFFF
        for bit in bits:
            d = (int(bit) ^ (crc & 1)) & 1
            crc >>= 1
            if d:
                crc ^= 0xDA6000
        return crc & 0xFFFFFF

    def _ble_gfsk_demod(self, iq: np.ndarray, sample_rate: float, symbol_offset_samples: int | None = None) -> np.ndarray:
        """
        GFSK frequency discriminator for BLE at 1 Mbit/s.
        Returns bit array with one bit per symbol period.

        Uses integrate-and-dump over each full symbol period rather than
        convolve+center-sample, which avoids even-kernel boundary ambiguity
        and edge artifacts that were causing scattered bit errors.
        """
        SYMBOL_RATE = 1_000_000.0
        if iq.size < 16:
            return np.array([], dtype=np.uint8)
        q = iq.astype(np.complex64)
        phase_delta = np.angle(q[1:] * np.conj(q[:-1])).astype(np.float32)
        sps = max(1.0, sample_rate / SYMBOL_RATE)
        sps_int = max(1, int(round(sps)))

        offset = (sps_int // 2) if symbol_offset_samples is None else int(symbol_offset_samples)
        offset = max(0, min(offset, sps_int - 1))

        avail = phase_delta.size - offset
        n_syms = avail // sps_int
        if n_syms < 10:
            return np.array([], dtype=np.uint8)

        # Integrate instantaneous frequency over each non-overlapping symbol window.
        # This is the optimal linear receiver for GFSK: sum(phase) over one period
        # equals the total phase advance, directly proportional to frequency deviation.
        # Unlike convolve+sample, this uses exactly sps_int samples per symbol with
        # no boundary overlap or zero-padding artifacts.
        seg = phase_delta[offset: offset + n_syms * sps_int]
        symbol_integrals = seg.reshape(n_syms, sps_int).sum(axis=1)

        dc = float(np.median(symbol_integrals))
        return (symbol_integrals > dc).astype(np.uint8)

    def _ble_decode_burst_packets(
        self,
        iq: np.ndarray,
        sample_rate: float,
        bursts: list[tuple[int, int]],
        channel: int,
    ) -> list[dict]:
        """Decode BLE packets per burst while sweeping symbol phase inside each burst."""
        SYMBOL_RATE = 1_000_000.0
        sps_int = max(1, int(round(max(1.0, sample_rate / SYMBOL_RATE))))
        pad = int(max(4 * sps_int, round(40e-6 * sample_rate)))
        decoded: list[dict] = []
        used_offsets: list[int] = []
        # BLE advertising preamble + AA template (40 bits, Â±1 encoding)
        ble_sync_tmpl = np.array([
            1,0,1,0,1,0,1,0, 0,1,1,0,1,0,1,1,
            0,1,1,1,1,1,0,1, 1,0,0,1,0,0,0,1,
            0,1,1,1,0,0,0,1,
        ], dtype=np.float32) * 2 - 1
        for burst_index, (start_sample, stop_sample) in enumerate(bursts):
            seg_start = max(0, int(start_sample) - pad)
            seg_stop = min(iq.size, int(stop_sample) + pad)
            segment = iq[seg_start:seg_stop]
            best_packets: list[dict] = []
            best_score = -1
            best_phase = 0
            best_sync_across_phases = 0.0
            for phase in range(sps_int):
                burst_bits = self._ble_gfsk_demod(segment, sample_rate, symbol_offset_samples=phase)
                if burst_bits.size >= 40:
                    bits_f = burst_bits.astype(np.float32) * 2 - 1
                    phase_sync = float(np.max(np.abs(np.correlate(bits_f, ble_sync_tmpl, mode='valid'))))
                else:
                    phase_sync = 0.0
                best_sync_across_phases = max(best_sync_across_phases, phase_sync)
                packets = self._ble_search_packets(burst_bits, channel)
                if not packets:
                    continue
                crc_valid = sum(1 for pkt in packets if pkt.get("crc_valid"))
                has_preamble = int(any(p.get("sync_source") == "preamble_access_address" for p in packets))
                score = crc_valid * 1_000_000 + int(phase_sync) * 1000 + has_preamble * 100 + len(packets)
                if score > best_score:
                    best_score = score
                    best_packets = packets
                    best_phase = phase
            # Reject bursts that don't match the BLE sync word at any phase â€” these are
            # non-BLE 2.4 GHz interference that happen to partially match the AA pattern.
            if best_sync_across_phases < 28.0:
                continue
            for pkt in best_packets:
                local_bit_offset = int(pkt.get("bit_offset", 0))
                global_bit_offset = int(round(seg_start / sample_rate * SYMBOL_RATE)) + local_bit_offset
                if any(abs(global_bit_offset - seen) < 24 for seen in used_offsets):
                    continue
                used_offsets.append(global_bit_offset)
                pkt["bit_offset"] = global_bit_offset
                pkt["pdu_start_bit"] = global_bit_offset
                pkt["burst_index"] = burst_index
                pkt["symbol_phase_samples"] = best_phase
                pkt["symbol_phase_selected"] = best_phase
                pkt["burst_start_sample"] = int(start_sample)
                pkt["burst_stop_sample"] = int(stop_sample)
                decoded.append(pkt)
        return decoded

    def _ble_decode_adv_packet(self, bits_from_pdu: np.ndarray, channel: int) -> dict | None:
        """
        Decode one BLE advertising PDU (bits start immediately after the Access Address).
        De-whitens, validates CRC-24, and extracts header + payload fields.
        Returns a packet dict for a plausible PDU; CRC validity is reported separately.
        """
        MAX_PAYLOAD = 37
        if bits_from_pdu.size < (2 + 6 + 3) * 8:  # min: header + AdvA + CRC
            return None
        # De-whiten from the start of the PDU
        available = min((2 + MAX_PAYLOAD + 3) * 8, bits_from_pdu.size)
        dw = self._ble_dewhiten_bits(bits_from_pdu[:available], channel)
        # Parse PDU header (16 bits)
        pdu_type = self._ble_int_from_bits(dw, 4, 0)
        tx_add = int(dw[4]) if dw.size > 4 else 0
        rx_add = int(dw[5]) if dw.size > 5 else 0
        length = self._ble_int_from_bits(dw, 6, 8)  # bits [13:8] of header
        if pdu_type > 6 or length < 6 or length > MAX_PAYLOAD:
            return None
        total_bits = (2 + length + 3) * 8
        if dw.size < total_bits:
            return None
        # CRC check over header + payload
        crc_data = dw[:(2 + length) * 8]
        computed = self._ble_crc24_bits(crc_data, init=0x555555)
        computed_reflected = self._ble_crc24_bits_reflected(crc_data, init=0x555555)
        received = self._ble_int_from_bits(dw, 24, (2 + length) * 8)
        crc_valid = (computed == received)
        crc_variant_matches = []
        if computed_reflected == received:
            crc_variant_matches.append("reflected_crc24")
        # Decode advertiser address (6 bytes, LSB first â†’ reverse for display)
        adv_bytes = [self._ble_int_from_bits(dw, 8, 16 + i * 8) for i in range(6)]
        adv_addr = ":".join(f"{b:02X}" for b in reversed(adv_bytes))
        # AdvData / payload hex
        adv_data_len = max(0, length - 6)
        payload_bytes = [self._ble_int_from_bits(dw, 8, 64 + i * 8) for i in range(adv_data_len)]
        pdu_names = {0: "ADV_IND", 1: "ADV_DIRECT_IND", 2: "ADV_NONCONN_IND",
                     3: "SCAN_REQ", 4: "SCAN_RSP", 5: "CONNECT_IND", 6: "ADV_SCAN_IND"}
        return {
            "pdu_type": pdu_names.get(pdu_type, f"UNKNOWN_0x{pdu_type:X}"),
            "length": length,
            "tx_add": bool(tx_add),
            "rx_add": bool(rx_add),
            "advertiser_address": adv_addr,
            "payload_hex": bytes(payload_bytes).hex(),
            "payload_fields": self._ble_parse_adv_data(bytes(payload_bytes)),
            "crc_valid": bool(crc_valid),
            "crc_computed": f"0x{computed:06X}",
            "crc_received": f"0x{received:06X}",
            "computed_crc": f"0x{computed:06X}",
            "received_crc": f"0x{received:06X}",
            "crc_match": bool(crc_valid),
            "crc_diagnostic_variants": {
                "msb_first_poly_0x00065B": f"0x{computed:06X}",
                "lsb_reflected_poly_0xDA6000": f"0x{computed_reflected:06X}",
                "received": f"0x{received:06X}",
                "variant_matches": crc_variant_matches,
            },
            "dewhitening_channel": int(channel),
            "rejection_reason": None if crc_valid else "crc_mismatch",
            "_total_bits": total_bits,
        }

    def _ble_parse_adv_data(self, adv_data: bytes) -> list[dict]:
        """Parse BLE AdvData TLV structures into a list of AD records."""
        records = []
        i = 0
        while i < len(adv_data):
            if i + 1 > len(adv_data):
                break
            length = adv_data[i]
            if length == 0 or i + 1 + length > len(adv_data):
                break
            ad_type = adv_data[i + 1]
            ad_data = adv_data[i + 2: i + 1 + length]
            ad_type_names = {
                0x01: "Flags", 0x02: "16b_UUID_incomplete", 0x03: "16b_UUID_complete",
                0x08: "Short_Local_Name", 0x09: "Complete_Local_Name",
                0x0A: "TX_Power_Level", 0xFF: "Manufacturer_Specific",
            }
            record = {
                "ad_type": f"0x{ad_type:02X}",
                "ad_type_name": ad_type_names.get(ad_type, "Unknown"),
                "data_hex": ad_data.hex(),
            }
            if ad_type == 0x09 or ad_type == 0x08:
                try:
                    record["name"] = ad_data.decode("utf-8", errors="replace")
                except Exception:
                    pass
            records.append(record)
            i += 1 + length
        return records

    def _ble_search_packets(self, bits: np.ndarray, channel: int) -> list[dict]:
        """
        Search for BLE advertising packets using NumPy correlation.
        Handles both normal and inverted GFSK polarity.
        """
        if bits.size < 50:
            return []
        # Advertising sync word: preamble + AA (0x8E89BED6), each byte LSB-first
        # AA first bit on air = LSB of 0xD6 = 0 â†’ preamble = 0x55 (01010101b), LSB-first = [1,0,1,0,1,0,1,0]
        # 0x55 â†’ [1,0,1,0,1,0,1,0]
        # 0xD6 = 11010110 â†’ [0,1,1,0,1,0,1,1]
        # 0xBE = 10111110 â†’ [0,1,1,1,1,1,0,1]
        # 0x89 = 10001001 â†’ [1,0,0,1,0,0,0,1]
        # 0x8E = 10001110 â†’ [0,1,1,1,0,0,0,1]
        SYNC = np.array([1,0,1,0,1,0,1,0,
                         0,1,1,0,1,0,1,1,
                         0,1,1,1,1,1,0,1,
                         1,0,0,1,0,0,0,1,
                         0,1,1,1,0,0,0,1], dtype=np.float32) * 2 - 1  # +1/-1
        bits_f = bits.astype(np.float32) * 2 - 1
        corr = np.correlate(bits_f, SYNC, mode='valid')
        # threshold = 32/40 bits correct (allows 4 bit errors in 40-bit sync word)
        candidates: list[tuple[int, int, str, int]] = []
        for pos in np.where(np.abs(corr) >= 32)[0]:
            polarity = 1 if corr[pos] < 0 else 0
            candidates.append((int(pos) + 40, polarity, "preamble_access_address", int(abs(corr[pos]))))

        aa = np.array([0,1,1,0,1,0,1,1,
                       0,1,1,1,1,1,0,1,
                       1,0,0,1,0,0,0,1,
                       0,1,1,1,0,0,0,1], dtype=np.float32) * 2 - 1
        aa_corr = np.correlate(bits_f, aa, mode='valid')
        for pos in np.where(np.abs(aa_corr) >= 28)[0]:
            polarity = 1 if aa_corr[pos] < 0 else 0
            candidates.append((int(pos) + 32, polarity, "access_address", int(abs(aa_corr[pos]))))
        packets = []
        skip_until = -1
        boundary_adjustments = sorted(range(-4, 5), key=lambda value: (abs(value), value))
        for pdu_start, polarity, source, aa_score in sorted(candidates, key=lambda item: item[0]):
            if int(pdu_start) < skip_until:
                continue
            # Polarity is derived from the candidate correlation above.
            pdu_start = int(pdu_start)
            if pdu_start >= bits.size:
                break
            # Try all PDU boundary offsets; prefer CRC-valid over first structural match.
            # Without this, the first plausible offset (-2) is always taken, which
            # reads 2 bits into the AA tail and produces a structurally valid but
            # CRC-invalid PDU while the true PDU at offset 0 is never tried.
            phase_candidates: list[tuple[int, int, dict]] = []
            for pdu_start_adjustment in boundary_adjustments:
                start = pdu_start + pdu_start_adjustment
                if start < 0 or start >= bits.size:
                    continue
                pdu_bits = bits[start:]
                if polarity:
                    pdu_bits = pdu_bits ^ 1
                pkt = self._ble_decode_adv_packet(pdu_bits, channel)
                if pkt is not None:
                    phase_candidates.append((pdu_start_adjustment, start, pkt))
            if not phase_candidates:
                continue
            valid_candidates = [(adj, st, p) for adj, st, p in phase_candidates if p.get("crc_valid")]
            chosen_adjust, chosen_start, chosen_pkt = (
                valid_candidates[0] if valid_candidates else phase_candidates[0]
            )
            chosen_pkt['bit_offset'] = int(chosen_start)
            chosen_pkt['pdu_start_bit'] = int(chosen_start)
            chosen_pkt['sync_source'] = source
            chosen_pkt['phase_adjust_bits'] = chosen_adjust
            chosen_pkt['pdu_start_adjustment'] = chosen_adjust
            chosen_pkt['access_address_match_score'] = int(aa_score)
            chosen_pkt['polarity'] = 'inverted' if polarity else 'normal'
            skip_until = chosen_start + chosen_pkt.pop('_total_bits', 64)
            packets.append(chosen_pkt)
        return packets

    # ------------------------------------------------------------------
    # Zigbee / IEEE 802.15.4 O-QPSK DSSS helpers
    # ------------------------------------------------------------------

    # IEEE 802.15.4-2006 Table 69: 32-chip PN spreading sequences (c0..c31)
    _ZIGBEE_PN = [
        [1,1,0,1,1,0,0,1,1,1,0,0,0,0,1,1,0,1,0,1,0,0,1,0,0,0,1,0,1,1,1,0],  # 0
        [1,1,1,0,1,1,0,1,1,0,0,1,1,1,0,0,0,0,1,1,0,1,0,1,0,0,1,0,0,0,1,0],  # 1
        [0,0,1,0,1,1,1,0,1,1,0,1,1,0,0,1,1,1,0,0,0,0,1,1,0,1,0,1,0,0,1,0],  # 2
        [0,0,1,0,0,0,1,0,1,1,1,0,1,1,0,1,1,0,0,1,1,1,0,0,0,0,1,1,0,1,0,1],  # 3
        [0,1,0,1,0,0,1,0,0,0,1,0,1,1,1,0,1,1,0,1,1,0,0,1,1,1,0,0,0,0,1,1],  # 4
        [0,0,1,1,0,1,0,1,0,0,1,0,0,0,1,0,1,1,1,0,1,1,0,1,1,0,0,1,1,1,0,0],  # 5
        [1,1,0,0,0,0,1,1,0,1,0,1,0,0,1,0,0,0,1,0,1,1,1,0,1,1,0,1,1,0,0,1],  # 6
        [1,0,0,1,1,1,0,0,0,0,1,1,0,1,0,1,0,0,1,0,0,0,1,0,1,1,1,0,1,1,0,1],  # 7
        [1,0,0,0,1,1,0,0,0,1,0,0,1,1,1,0,1,0,1,1,1,1,1,0,0,0,1,1,0,1,1,0],  # 8
        [0,1,1,0,1,0,0,0,1,1,0,0,0,1,0,0,1,1,1,0,1,0,1,1,1,1,1,0,0,0,1,1],  # 9
        [0,0,1,1,0,1,1,0,1,0,0,0,1,1,0,0,0,1,0,0,1,1,1,0,1,0,1,1,1,1,1,0],  # 10
        [1,1,1,0,0,0,1,1,0,1,1,0,1,0,0,0,1,1,0,0,0,1,0,0,1,1,1,0,1,0,1,1],  # 11
        [1,0,1,1,1,1,1,0,0,0,1,1,0,1,1,0,1,0,0,0,1,1,0,0,0,1,0,0,1,1,1,0],  # 12
        [1,1,1,0,1,0,1,1,1,1,1,0,0,0,1,1,0,1,1,0,1,0,0,0,1,1,0,0,0,1,0,0],  # 13
        [0,1,0,0,1,1,1,0,1,0,1,1,1,1,1,0,0,0,1,1,0,1,1,0,1,0,0,0,1,1,0,0],  # 14
        [1,1,0,0,0,1,0,0,1,1,1,0,1,0,1,1,1,1,1,0,0,0,1,1,0,1,1,0,1,0,0,0],  # 15
    ]

    def _zigbee_channel_from_frequency(self, center_hz: float) -> tuple[int, float]:
        """Return (channel_number, channel_center_hz) for the nearest IEEE 802.15.4 channel (CH11-CH26)."""
        best_ch, best_dist = 11, float("inf")
        for k in range(11, 27):
            ch_hz = (2405.0 + 5.0 * (k - 11)) * 1e6
            dist = abs(center_hz - ch_hz)
            if dist < best_dist:
                best_dist = dist
                best_ch = k
        return best_ch, (2405.0 + 5.0 * (best_ch - 11)) * 1e6

    def _zigbee_crc16(self, data: bytes) -> int:
        """CRC-16/KERMIT used by IEEE 802.15.4 FCS. Poly 0x1021, init 0x0000, LSB-first."""
        crc = 0x0000
        for byte in data:
            crc ^= byte
            for _ in range(8):
                crc = (crc >> 1) ^ 0x8408 if (crc & 1) else (crc >> 1)
        return crc & 0xFFFF

    def _zigbee_oqpsk_dechip(self, iq: np.ndarray, sample_rate: float) -> np.ndarray:
        """Recover IEEE 802.15.4 O-QPSK chips at 2 Mchip/s. Returns 0/1 chip array."""
        CHIP_RATE = 2_000_000.0
        spc = sample_rate / CHIP_RATE
        spc_int = max(1, int(round(spc)))
        if iq.size < 64:
            return np.array([], dtype=np.uint8)
        q = iq.astype(np.complex64)
        if spc_int >= 2:
            kernel = np.ones(spc_int, dtype=np.float32) / spc_int
            iq_i = np.convolve(np.real(q), kernel, "same")
            iq_q = np.convolve(np.imag(q), kernel, "same")
        else:
            iq_i = np.real(q).astype(np.float32)
            iq_q = np.imag(q).astype(np.float32)
        n_chips = iq.size // spc_int
        offset = spc_int // 2
        idx = np.arange(n_chips) * spc_int + offset
        idx = idx[idx < iq_i.size]
        n = idx.size
        half = max(1, spc_int // 2)
        idx_q = np.clip(idx + half, 0, iq_q.size - 1)
        chips = np.zeros(n, dtype=np.uint8)
        chips[0::2] = (iq_i[idx[0::2]] > 0).astype(np.uint8)
        chips[1::2] = (iq_q[idx_q[1::2]] > 0).astype(np.uint8)
        return chips

    def _zigbee_try_decode_frame(self, chips_b: np.ndarray, PN_b: np.ndarray, start: int) -> dict | None:
        """Attempt IEEE 802.15.4 frame decode from chip position start using PN correlation."""
        MAX_SYMS = 270  # preamble(8)+SFD(2)+PHR(2)+PSDU(127*2)=266
        n_avail = (chips_b.size - start) // 32
        n_decode = min(MAX_SYMS, n_avail)
        if n_decode < 12:
            return None
        end = start + n_decode * 32
        segment = chips_b[start:end].astype(np.float32).reshape(n_decode, 32)
        corrs = segment @ PN_b.T.astype(np.float32)  # (n_decode, 16)
        symbols = np.argmax(corrs, axis=1).astype(np.int16)
        # Check preamble: at least 7 of 8 leading symbols must be 0
        if int(np.sum(symbols[:8] == 0)) < 7:
            return None
        # Check SFD: symbols[8]=7 (low nibble 0xA7), symbols[9]=10 (high nibble)
        if symbols[8] != 7 or symbols[9] != 10:
            return None
        phr = int(symbols[10]) | (int(symbols[11]) << 4)
        length = phr & 0x7F
        if length < 2 or length > 127:
            return None
        needed = 12 + length * 2
        if needed > n_decode:
            return None
        psdu_syms = symbols[12:12 + length * 2]
        lo = psdu_syms[0::2].astype(np.uint8)
        hi = psdu_syms[1::2].astype(np.uint8)
        psdu_bytes = bytes(int(l) | (int(h) << 4) for l, h in zip(lo, hi))
        payload = psdu_bytes[:-2]
        fcs_recv = psdu_bytes[-2] | (psdu_bytes[-1] << 8)
        fcs_calc = self._zigbee_crc16(payload)
        return {
            "phr": phr,
            "length": length,
            "payload_hex": payload.hex(),
            "fcs_received": f"0x{fcs_recv:04X}",
            "fcs_computed": f"0x{fcs_calc:04X}",
            "crc_valid": fcs_calc == fcs_recv,
            "_total_chips": needed * 32,
        }

    def _zigbee_search_frames(self, chips: np.ndarray) -> list[dict]:
        """Search chip stream for IEEE 802.15.4 preamble+SFD+frame; returns decoded frame dicts."""
        if chips.size < 12 * 32:
            return []
        PN_b = (np.array(self._ZIGBEE_PN, dtype=np.float32) * 2.0 - 1.0)  # (16,32) bipolar
        pn0 = PN_b[0]
        all_frames: list[dict] = []
        seen: set[int] = set()
        for polarity in (0, 1):
            c = (chips ^ polarity).astype(np.float32) * 2.0 - 1.0
            # Sliding window correlation with PN[0] using stride tricks
            if c.size < 32:
                continue
            windows = np.lib.stride_tricks.sliding_window_view(c, 32)  # (n-31, 32)
            corr = windows @ pn0  # (n-31,)
            candidates = np.where(corr >= 24.0)[0]
            skip_until = -1
            c_int8 = c.astype(np.int8)
            for pos in candidates:
                pos = int(pos)
                if pos < skip_until or pos in seen:
                    continue
                frame = self._zigbee_try_decode_frame(c_int8, PN_b.astype(np.int8), pos)
                if frame is not None:
                    total = frame.pop("_total_chips", 12 * 32)
                    frame["chip_offset"] = pos
                    all_frames.append(frame)
                    seen.add(pos)
                    skip_until = pos + total
        return all_frames

    def _zigbee_ieee802154(self, iq: np.ndarray, data: dict, output_dir: Path) -> dict:
        """Full IEEE 802.15.4 O-QPSK DSSS pipeline: chip recovery â†’ PN despreading â†’ SFD â†’ FCS."""
        center = float(data.get("center_frequency_hz") or 0.0)
        sample_rate = float(data.get("sample_rate_hz") or 1.0)
        channel, ch_hz = self._zigbee_channel_from_frequency(center)
        activity = self._summarize_iq_activity(iq, sample_rate)

        chips = self._zigbee_oqpsk_dechip(iq, sample_rate)
        chip_path = output_dir / "chips.bin"
        chip_path.write_bytes(np.packbits(chips).tobytes() if chips.size else b"")

        frames = self._zigbee_search_frames(chips) if chips.size >= 12 * 32 else []
        n_frames = len(frames)
        n_crc_valid = sum(1 for f in frames if f.get("crc_valid"))

        decoded = {
            "protocol": "ieee802154",
            "pipeline": "zigbee_ieee802154",
            "channel": channel,
            "channel_frequency_mhz": ch_hz / 1e6,
            "frames_decoded": n_frames,
            "frames_crc_valid": n_crc_valid,
            "payload_extractable": n_crc_valid > 0,
            "frames": [
                {
                    "index": i,
                    "chip_offset": f.get("chip_offset", 0),
                    "channel": channel,
                    "length": f.get("length"),
                    "payload_hex": f.get("payload_hex"),
                    "fcs_received": f.get("fcs_received"),
                    "fcs_computed": f.get("fcs_computed"),
                    "crc_valid": f.get("crc_valid", False),
                }
                for i, f in enumerate(frames)
            ],
        }
        decoded_path = output_dir / "decoded_frames.json"
        decoded_path.write_text(json.dumps(decoded, indent=2), encoding="utf-8")
        logs_path = output_dir / "logs.txt"
        logs_path.write_text(
            "\n".join([
                "Zigbee/IEEE 802.15.4 O-QPSK DSSS pipeline",
                f"center_frequency_hz={center}",
                f"computed_channel=CH{channel} ({ch_hz/1e6:.1f} MHz)",
                f"chips_extracted={chips.size}",
                f"rf_activity_detected={bool(activity.get('signal_detected'))}",
                f"frames_decoded={n_frames}",
                f"frames_crc_valid={n_crc_valid}",
            ]) + "\n",
            encoding="utf-8",
        )
        final_status = (
            "decoded_with_valid_crc" if n_crc_valid > 0
            else "zigbee_candidate_not_decoded" if activity.get("signal_detected")
            else "rf_activity_only"
        )
        return {
            "status": "complete" if n_crc_valid > 0 else "rf_activity_only",
            "final_status": final_status,
            "valid_demodulation": n_crc_valid > 0,
            "protocol": "ieee802154",
            "pipeline": "zigbee_ieee802154",
            "computed_zigbee_channel": channel,
            "channel_frequency_mhz": ch_hz / 1e6,
            "rf_activity_detected": bool(activity.get("signal_detected")),
            "chips_extracted": int(chips.size),
            "frames_decoded": n_frames,
            "frames_crc_valid": n_crc_valid,
            "confidence_score": min(1.0, n_crc_valid / 3.0) if n_crc_valid > 0 else None,
            "stage_diagnostics": {
                "iq_loaded": bool(iq.size > 0),
                "rf_activity_detected": bool(activity.get("signal_detected")),
                "oqpsk_dechip_attempted": True,
                "chips_extracted": int(chips.size),
                "pn_despreading_attempted": chips.size >= 12 * 32,
                "frames_decoded": n_frames,
                "crc_validation_attempted": n_frames > 0,
                "frames_crc_valid": n_crc_valid,
            },
            "outputs": {
                "chips": str(chip_path),
                "decoded_frames": str(decoded_path),
                "report": str(output_dir / "demodulation_report.json"),
                "logs": str(logs_path),
            },
            "decoded_frames": decoded,
            "notes": (
                [f"Decoded {n_frames} IEEE 802.15.4 frame(s), {n_crc_valid} CRC-valid."]
                if n_crc_valid > 0
                else ["RF activity detected; no CRC-valid IEEE 802.15.4 frame recovered."]
                if activity.get("signal_detected")
                else ["No Zigbee/IEEE 802.15.4 frames found in the capture."]
            ),
            "warnings": (
                ["Low SNR or wrong channel â€” chip recovery may be unreliable."]
                if not n_crc_valid and activity.get("signal_detected")
                else []
            ),
        }

    def _pulse_timing(self, active: np.ndarray, sample_rate: float) -> dict:
        runs_on = self._detect_boolean_runs(active, sample_rate)
        runs_off = self._detect_boolean_runs(~active.astype(bool), sample_rate) if active.size else []
        on_ms = np.array([(stop - start) / sample_rate * 1000.0 for start, stop in runs_on], dtype=float)
        off_ms = np.array([(stop - start) / sample_rate * 1000.0 for start, stop in runs_off], dtype=float)
        duty = float(np.mean(active) * 100.0) if active.size else 0.0
        return {
            "on_time_min_ms": float(np.min(on_ms)) if on_ms.size else None,
            "on_time_max_ms": float(np.max(on_ms)) if on_ms.size else None,
            "on_time_mean_ms": float(np.mean(on_ms)) if on_ms.size else None,
            "off_time_min_ms": float(np.min(off_ms)) if off_ms.size else None,
            "off_time_max_ms": float(np.max(off_ms)) if off_ms.size else None,
            "off_time_mean_ms": float(np.mean(off_ms)) if off_ms.size else None,
            "duty_cycle_percent": duty,
        }

    # ------------------------------------------------------------------
    # OOK 433/315/868 MHz remote control helpers
    # ------------------------------------------------------------------

    def _ook433_pulse_sequence(
        self, binary: np.ndarray, sample_rate: float
    ) -> list[tuple[int, float]]:
        """Time-ordered (level: 0/1, duration_Âµs) for every run in binary signal."""
        if binary.size == 0:
            return []
        edges = np.flatnonzero(np.diff(binary.astype(np.int8)))
        seg_starts = np.concatenate([[0], edges + 1])
        seg_ends = np.concatenate([edges + 1, [binary.size]])
        pulses: list[tuple[int, float]] = []
        for s, e in zip(seg_starts, seg_ends):
            dur_us = (e - s) / sample_rate * 1e6
            if dur_us >= 50.0:  # ignore sub-50 Âµs glitches
                pulses.append((int(binary[s]), dur_us))
        return pulses

    def _ook433_pulse_sequence_indexed(
        self, binary: np.ndarray, sample_rate: float
    ) -> list[dict]:
        """Time-ordered pulse runs with sample positions for per-burst diagnostics."""
        if binary.size == 0:
            return []
        edges = np.flatnonzero(np.diff(binary.astype(np.int8)))
        seg_starts = np.concatenate([[0], edges + 1])
        seg_ends = np.concatenate([edges + 1, [binary.size]])
        pulses: list[dict] = []
        for s, e in zip(seg_starts, seg_ends):
            dur_us = (e - s) / sample_rate * 1e6
            if dur_us >= 50.0:
                pulses.append(
                    {
                        "level": int(binary[s]),
                        "duration_us": float(dur_us),
                        "start_sample": int(s),
                        "end_sample": int(e),
                    }
                )
        return pulses

    def _ook433_merge_short_glitches(
        self,
        pulses: list[dict],
        min_duration_us: float = 100.0,
    ) -> list[dict]:
        """Remove sub-symbol glitches and fuse adjacent runs with the same level."""
        if not pulses:
            return []
        merged: list[dict] = []
        for pulse in pulses:
            item = dict(pulse)
            if item["duration_us"] < min_duration_us and merged:
                merged[-1]["end_sample"] = int(item["end_sample"])
                merged[-1]["duration_us"] += float(item["duration_us"])
                continue
            if merged and merged[-1]["level"] == item["level"]:
                merged[-1]["end_sample"] = int(item["end_sample"])
                merged[-1]["duration_us"] += float(item["duration_us"])
            else:
                merged.append(item)
        if len(merged) >= 2 and merged[-1]["duration_us"] < min_duration_us:
            tail = merged.pop()
            merged[-1]["end_sample"] = int(tail["end_sample"])
            merged[-1]["duration_us"] += float(tail["duration_us"])
        fused: list[dict] = []
        for pulse in merged:
            if fused and fused[-1]["level"] == pulse["level"]:
                fused[-1]["end_sample"] = int(pulse["end_sample"])
                fused[-1]["duration_us"] += float(pulse["duration_us"])
            else:
                fused.append(pulse)
        return fused

    def _ook433_internal_pulses_for_burst(
        self,
        envelope: np.ndarray,
        start_sample: int,
        end_sample: int,
        sample_rate: float,
        min_glitch_us: float = 100.0,
    ) -> tuple[list[dict], float | None]:
        """Extract symbol-level ON/OFF transitions inside one carrier burst."""
        if envelope.size == 0 or end_sample <= start_sample or sample_rate <= 0:
            return [], None
        start = max(0, int(start_sample))
        stop = min(int(end_sample), int(envelope.size))
        segment = envelope[start:stop].astype(np.float32, copy=False)
        if segment.size < max(8, int(sample_rate * min_glitch_us * 1e-6)):
            return [], None
        smooth_len = max(1, int(round(sample_rate * 25e-6)))
        if smooth_len > 1 and segment.size > smooth_len:
            kernel = np.ones(smooth_len, dtype=np.float32) / float(smooth_len)
            smooth = np.convolve(segment, kernel, mode="same")
        else:
            smooth = segment
        p10 = float(np.percentile(smooth, 10))
        p90 = float(np.percentile(smooth, 90))
        if p90 <= p10 * 1.05:
            return [
                {
                    "level": 1,
                    "duration_us": float((stop - start) / sample_rate * 1e6),
                    "start_sample": start,
                    "end_sample": stop,
                }
            ], None
        threshold = (p10 + p90) / 2.0
        local_binary = (smooth > threshold).astype(np.uint8)
        local_pulses = self._ook433_pulse_sequence_indexed(local_binary, sample_rate)
        absolute_pulses = []
        for pulse in local_pulses:
            absolute_pulses.append(
                {
                    "level": int(pulse["level"]),
                    "duration_us": float(pulse["duration_us"]),
                    "start_sample": int(start + pulse["start_sample"]),
                    "end_sample": int(start + pulse["end_sample"]),
                }
            )
        return self._ook433_merge_short_glitches(absolute_pulses, min_glitch_us), threshold

    def _ook433_internal_pulse_metrics(self, internal_pulses: list[dict], burst_duration_s: float | None) -> dict:
        marks = [float(p["duration_us"]) for p in internal_pulses if p["level"] == 1]
        spaces = [float(p["duration_us"]) for p in internal_pulses if p["level"] == 0]
        transitions = max(0, len(internal_pulses) - 1)
        duration_s = float(burst_duration_s or 0.0)
        transition_rate = transitions / duration_s if duration_s > 0 else 0.0

        def stats(values: list[float], name: str) -> dict:
            if not values:
                return {
                    f"min_{name}_us": None,
                    f"max_{name}_us": None,
                    f"median_{name}_us": None,
                    f"short_{name}_us": None,
                    f"long_{name}_us": None,
                }
            arr = np.array(values, dtype=np.float32)
            return {
                f"min_{name}_us": round(float(np.min(arr)), 3),
                f"max_{name}_us": round(float(np.max(arr)), 3),
                f"median_{name}_us": round(float(np.median(arr)), 3),
                f"short_{name}_us": round(float(np.percentile(arr, 25)), 3),
                f"long_{name}_us": round(float(np.percentile(arr, 75)), 3),
            }

        symbol_level_detected = transitions >= 10 and bool(marks) and bool(spaces)
        return {
            "internal_transition_count": transitions,
            "average_transition_rate": round(float(transition_rate), 3),
            "mark_count": len(marks),
            "space_count": len(spaces),
            **stats(marks, "mark"),
            **stats(spaces, "space"),
            "symbol_level_detected": symbol_level_detected,
            "transition_rejection_reason": None if symbol_level_detected else "no_symbol_level_ook_transitions_detected",
        }

    def _ook433_instantaneous_frequency_metrics(
        self,
        iq: np.ndarray,
        start_sample: int,
        end_sample: int,
        sample_rate: float,
    ) -> dict:
        if iq.size == 0 or end_sample <= start_sample or sample_rate <= 0:
            return {"possible_modulation": "unknown"}
        segment = iq[max(0, start_sample):min(iq.size, end_sample)]
        if segment.size < 32:
            return {"possible_modulation": "unknown"}
        inst = np.diff(np.unwrap(np.angle(segment))).astype(np.float32) * (sample_rate / (2.0 * np.pi))
        if inst.size < 16:
            return {"possible_modulation": "unknown"}
        lo = float(np.percentile(inst, 5))
        hi = float(np.percentile(inst, 95))
        clipped = inst[(inst >= lo) & (inst <= hi)]
        if clipped.size < 16:
            clipped = inst
        median = float(np.median(clipped))
        low_cluster = clipped[clipped <= median]
        high_cluster = clipped[clipped > median]
        if low_cluster.size < 8 or high_cluster.size < 8:
            return {
                "possible_modulation": "ook_or_ask_candidate",
                "instantaneous_frequency_std_hz": round(float(np.std(clipped)), 3),
            }
        low_center = float(np.median(low_cluster))
        high_center = float(np.median(high_cluster))
        separation = abs(high_center - low_center)
        deviation = separation / 2.0
        balance = min(low_cluster.size, high_cluster.size) / max(low_cluster.size, high_cluster.size)
        two_tone = separation >= 2_000.0 and balance >= 0.15
        return {
            "possible_modulation": "fsk_candidate" if two_tone else "ook_or_ask_candidate",
            "instantaneous_frequency_low_hz": round(low_center, 3),
            "instantaneous_frequency_high_hz": round(high_center, 3),
            "frequency_deviation_hz": round(float(deviation), 3),
            "frequency_cluster_balance": round(float(balance), 4),
            "instantaneous_frequency_std_hz": round(float(np.std(clipped)), 3),
        }

    def _fsk_bits_to_hex(self, bits: list[int]) -> str:
        return self._ook433_bits_to_hex(bits)

    def _estimate_fsk_symbol_rate(self, tone_bits: np.ndarray, sample_rate: float) -> tuple[float | None, float]:
        if tone_bits.size < 4 or sample_rate <= 0:
            return None, 0.0
        transitions = np.flatnonzero(np.diff(tone_bits.astype(np.int8)) != 0)
        if transitions.size < 2:
            return None, 0.0
        runs = np.diff(np.concatenate([[0], transitions + 1, [tone_bits.size]]))
        runs = runs[(runs > 0) & (runs < np.percentile(runs, 95))]
        if runs.size == 0:
            return None, 0.0
        samples_per_symbol = float(np.percentile(runs, 25))
        if samples_per_symbol <= 0:
            return None, 0.0
        symbol_rate = sample_rate / samples_per_symbol
        consistency = 1.0 - min(1.0, float(np.std(runs)) / max(float(np.mean(runs)), 1.0))
        return float(symbol_rate), float(max(0.0, min(1.0, consistency)))

    def _fsk_decode_burst(
        self,
        iq: np.ndarray,
        start_sample: int,
        end_sample: int,
        sample_rate: float,
        burst_index: int,
    ) -> dict:
        segment = iq[max(0, start_sample):min(iq.size, end_sample)]
        duration_s = (end_sample - start_sample) / sample_rate if sample_rate > 0 else 0.0
        base = {
            "burst_index": burst_index,
            "burst_start_time": start_sample / sample_rate if sample_rate > 0 else None,
            "burst_duration": duration_s,
            "fsk_detected": False,
            "rejection_reason": None,
        }
        if segment.size < 64 or sample_rate <= 0:
            base["rejection_reason"] = "burst_too_short_for_fsk"
            return base
        analysis_sample_rate = float(sample_rate)
        decimation = 1
        max_analysis_samples = 300_000
        if segment.size > max_analysis_samples:
            decimation = int(np.ceil(segment.size / max_analysis_samples))
            segment = segment[::decimation]
            analysis_sample_rate = sample_rate / decimation
            base["analysis_decimation"] = decimation
            base["analysis_sample_rate_hz"] = round(float(analysis_sample_rate), 3)
        inst = np.diff(np.unwrap(np.angle(segment))).astype(np.float32) * (analysis_sample_rate / (2.0 * np.pi))
        if inst.size < 32:
            base["rejection_reason"] = "insufficient_instantaneous_frequency_samples"
            return base
        inst = inst - float(np.median(inst))
        lo = float(np.percentile(inst, 2))
        hi = float(np.percentile(inst, 98))
        inst = inst[(inst >= lo) & (inst <= hi)]
        if inst.size < 32:
            base["rejection_reason"] = "frequency_samples_clipped_empty"
            return base
        median = float(np.median(inst))
        low_cluster = inst[inst <= median]
        high_cluster = inst[inst > median]
        if low_cluster.size < 8 or high_cluster.size < 8:
            base["rejection_reason"] = "two_tone_clusters_not_found"
            return base
        fsk_low = float(np.median(low_cluster))
        fsk_high = float(np.median(high_cluster))
        tone_separation = abs(fsk_high - fsk_low)
        deviation = tone_separation / 2.0
        threshold = (fsk_low + fsk_high) / 2.0
        balance = min(low_cluster.size, high_cluster.size) / max(low_cluster.size, high_cluster.size)
        if tone_separation < 2_000.0 or balance < 0.10:
            base.update({
                "fsk_low_hz": round(fsk_low, 3),
                "fsk_high_hz": round(fsk_high, 3),
                "tone_separation_hz": round(float(tone_separation), 3),
                "frequency_deviation_hz": round(float(deviation), 3),
                "frequency_cluster_balance": round(float(balance), 4),
                "rejection_reason": "weak_or_unbalanced_fsk_tones",
            })
            return base
        tone_bits = (inst > threshold).astype(np.uint8)
        symbol_rate, symbol_confidence = self._estimate_fsk_symbol_rate(tone_bits, analysis_sample_rate)
        if symbol_rate is None:
            symbol_rate = max(1_000.0, min(20_000.0, 1.0 / max(duration_s / 64.0, 1e-6)))
            symbol_confidence = 0.15
        symbol_rate = max(250.0, min(50_000.0, float(symbol_rate)))
        candidate_rates = sorted({
            float(symbol_rate),
            float(max(250.0, symbol_rate * 0.5)),
            float(min(50_000.0, symbol_rate * 2.0)),
            1_000.0,
            2_000.0,
            4_800.0,
            9_600.0,
            19_200.0,
        })
        decodings = []
        for rate in candidate_rates:
            samples_per_symbol = max(4, int(round(analysis_sample_rate / rate)))
            bits = []
            for offset in range(0, tone_bits.size, samples_per_symbol):
                window = tone_bits[offset:offset + samples_per_symbol]
                if window.size:
                    bits.append(1 if float(np.mean(window)) >= 0.5 else 0)
            if len(bits) < 8:
                continue
            for polarity in ("normal", "inverted"):
                candidate_bits = bits if polarity == "normal" else [1 - bit for bit in bits]
                entropy = self._ook433_binary_entropy(candidate_bits)
                decodings.append({
                    "symbol_rate_estimate": round(float(rate), 3),
                    "polarity": polarity,
                    "bit_length": len(candidate_bits),
                    "bitstring": "".join(str(bit) for bit in candidate_bits[:2048]),
                    "hex_candidate": self._fsk_bits_to_hex(candidate_bits),
                    "entropy": round(float(entropy), 4),
                    "confidence": round(float(max(0.0, min(1.0, 0.45 * symbol_confidence + 0.35 * min(1.0, tone_separation / 50_000.0) + 0.20 * min(1.0, entropy)))), 4),
                })
        selected = max(decodings, key=lambda item: (item["confidence"], item["bit_length"]), default=None)
        fsk_noise = float(np.std(inst - np.where(tone_bits > 0, fsk_high, fsk_low))) if inst.size == tone_bits.size else float(np.std(inst))
        fsk_snr = 20.0 * np.log10(max(tone_separation, 1e-9) / max(fsk_noise, 1e-9))
        base.update({
            "fsk_detected": True,
            "fsk_low_hz": round(fsk_low, 3),
            "fsk_high_hz": round(fsk_high, 3),
            "frequency_deviation_hz": round(float(deviation), 3),
            "tone_separation_hz": round(float(tone_separation), 3),
            "symbol_rate_estimate": round(float(symbol_rate), 3),
            "symbol_rate_confidence": round(float(symbol_confidence), 4),
            "frequency_cluster_balance": round(float(balance), 4),
            "fsk_snr": round(float(fsk_snr), 3),
            "candidate_decodings": decodings[:20],
            "selected_decoding": selected,
        })
        return base

    def _fsk_remote_candidates(
        self,
        iq: np.ndarray,
        bursts_indexed: list[list[dict]],
        sample_rate: float,
    ) -> tuple[list[dict], list[dict], dict]:
        diagnostics: list[dict] = []
        candidates: list[dict] = []
        for index, burst in enumerate(bursts_indexed):
            if not burst:
                continue
            decoded = self._fsk_decode_burst(
                iq,
                int(burst[0]["start_sample"]),
                int(burst[-1]["end_sample"]),
                sample_rate,
                index,
            )
            diagnostics.append(decoded)
            selected = decoded.get("selected_decoding")
            if decoded.get("fsk_detected") and isinstance(selected, dict):
                item = dict(selected)
                item["burst_index"] = index
                item["fsk_low_hz"] = decoded.get("fsk_low_hz")
                item["fsk_high_hz"] = decoded.get("fsk_high_hz")
                item["frequency_deviation_hz"] = decoded.get("frequency_deviation_hz")
                item["tone_separation_hz"] = decoded.get("tone_separation_hz")
                candidates.append(item)
        bitsets = [
            [int(ch) for ch in str(candidate.get("bitstring") or "") if ch in "01"]
            for candidate in candidates
        ]
        similarities = [
            self._ook433_bit_similarity(bitsets[i], bitsets[j])
            for i in range(len(bitsets))
            for j in range(i + 1, len(bitsets))
            if bitsets[i] and bitsets[j]
        ]
        selected = max(candidates, key=lambda item: (item.get("confidence") or 0.0, item.get("bit_length") or 0), default={})
        if selected:
            selected = dict(selected)
            selected["repetition_similarity"] = round(float(np.mean(similarities)), 4) if similarities else 0.0
            selected["final_status"] = "fsk_bitstream_candidate"
            selected["valid_protocol"] = False
        return diagnostics, candidates, selected

    def _fsk_remote_candidates_from_ranges(
        self,
        iq: np.ndarray,
        burst_ranges: list[tuple[int, int]],
        sample_rate: float,
    ) -> tuple[list[dict], list[dict], dict]:
        diagnostics: list[dict] = []
        candidates: list[dict] = []
        for index, (start_sample, end_sample) in enumerate(burst_ranges):
            decoded = self._fsk_decode_burst(iq, start_sample, end_sample, sample_rate, index)
            diagnostics.append(decoded)
            selected = decoded.get("selected_decoding")
            if decoded.get("fsk_detected") and isinstance(selected, dict):
                item = dict(selected)
                item["burst_index"] = index
                item["fsk_low_hz"] = decoded.get("fsk_low_hz")
                item["fsk_high_hz"] = decoded.get("fsk_high_hz")
                item["frequency_deviation_hz"] = decoded.get("frequency_deviation_hz")
                item["tone_separation_hz"] = decoded.get("tone_separation_hz")
                candidates.append(item)
        bitsets = [
            [int(ch) for ch in str(candidate.get("bitstring") or "") if ch in "01"]
            for candidate in candidates
        ]
        similarities = [
            self._ook433_bit_similarity(bitsets[i], bitsets[j])
            for i in range(len(bitsets))
            for j in range(i + 1, len(bitsets))
            if bitsets[i] and bitsets[j]
        ]
        selected = max(candidates, key=lambda item: (item.get("confidence") or 0.0, item.get("bit_length") or 0), default={})
        if selected:
            selected = dict(selected)
            selected["repetition_similarity"] = round(float(np.mean(similarities)), 4) if similarities else 0.0
            selected["final_status"] = "fsk_bitstream_candidate"
            selected["valid_protocol"] = False
        return diagnostics, candidates, selected

    @staticmethod
    def _burst_ranges_from_ook_report(result: dict) -> list[tuple[int, int]]:
        decoded_frames = result.get("decoded_frames")
        diagnostics = decoded_frames.get("burst_diagnostics") if isinstance(decoded_frames, dict) else None
        if not isinstance(diagnostics, list):
            return []
        ranges: list[tuple[int, int]] = []
        for item in diagnostics:
            if not isinstance(item, dict):
                continue
            start = item.get("burst_start_sample")
            stop = item.get("burst_end_sample")
            try:
                start_i = int(start)
                stop_i = int(stop)
            except (TypeError, ValueError):
                continue
            if stop_i > start_i:
                ranges.append((start_i, stop_i))
        return ranges

    @staticmethod
    def _compact_fsk_decoding_for_response(decoding: Any) -> dict:
        if not isinstance(decoding, dict):
            return {}
        compact = {
            key: value
            for key, value in decoding.items()
            if key not in {"bitstring", "hex_candidate", "samples", "symbols"}
        }
        bitstring = decoding.get("bitstring")
        if bitstring is not None:
            text = str(bitstring)
            compact["bit_preview"] = text[:256]
            compact["bit_length_inline"] = len(text)
            compact["bitstring_truncated"] = len(text) > 256
        hex_candidate = decoding.get("hex_candidate")
        if hex_candidate is not None:
            text = str(hex_candidate)
            compact["hex_preview"] = text[:256]
            compact["hex_length_inline"] = len(text)
            compact["hex_candidate_truncated"] = len(text) > 256
        return compact

    def _compact_fsk_remote_response(self, result: dict) -> dict:
        selected = self._compact_fsk_decoding_for_response(result.get("selected_fsk_decoding"))
        result["selected_fsk_decoding"] = selected

        decoded_frames = result.get("decoded_frames")
        if isinstance(decoded_frames, dict):
            adaptive = decoded_frames.get("adaptive_decoding")
            if isinstance(adaptive, dict):
                adaptive = dict(adaptive)
                adaptive["selected_fsk_decoding"] = selected
                selected_hex = adaptive.get("selected_hex_candidate")
                if selected_hex is not None:
                    text = str(selected_hex)
                    adaptive["selected_hex_preview"] = text[:256]
                    adaptive["selected_hex_length_inline"] = len(text)
                    adaptive["selected_hex_candidate_truncated"] = len(text) > 256
                    adaptive.pop("selected_hex_candidate", None)
            result["decoded_frames"] = {
                "protocol": decoded_frames.get("protocol"),
                "pipeline": decoded_frames.get("pipeline"),
                "center_frequency_hz": decoded_frames.get("center_frequency_hz"),
                "bursts_detected": decoded_frames.get("bursts_detected"),
                "symbol_level_bursts": decoded_frames.get("symbol_level_bursts"),
                "no_symbol_level_bursts": decoded_frames.get("no_symbol_level_bursts"),
                "possible_modulation_counts": decoded_frames.get("possible_modulation_counts"),
                "recommended_pipeline": decoded_frames.get("recommended_pipeline"),
                "fsk_majority_detected": decoded_frames.get("fsk_majority_detected"),
                "selected_fsk_decoding": selected,
                "repeat_analysis": decoded_frames.get("repeat_analysis"),
                "burst_comparison": decoded_frames.get("burst_comparison"),
                "adaptive_decoding": adaptive,
            }

        adaptive = result.get("adaptive_decoding")
        if isinstance(adaptive, dict):
            adaptive = dict(adaptive)
            adaptive["selected_fsk_decoding"] = selected
            selected_hex = adaptive.get("selected_hex_candidate")
            if selected_hex is not None:
                text = str(selected_hex)
                adaptive["selected_hex_preview"] = text[:256]
                adaptive["selected_hex_length_inline"] = len(text)
                adaptive["selected_hex_candidate_truncated"] = len(text) > 256
                adaptive.pop("selected_hex_candidate", None)
            result["adaptive_decoding"] = adaptive
        return result

    def _fsk_remote_decoder(self, iq: np.ndarray, data: dict, output_dir: Path) -> dict:
        base = self._ook_433_remote(iq, data, output_dir)
        candidates = base.get("fsk_candidate_decodings")
        if not isinstance(candidates, list):
            selected = base.get("selected_fsk_decoding")
            candidates = [selected] if isinstance(selected, dict) and selected else []

        selected = base.get("selected_fsk_decoding")
        if not candidates:
            sample_rate = float(data.get("sample_rate_hz") or base.get("sample_rate_hz") or 1.0)
            forced_ranges = self._burst_ranges_from_ook_report(base)
            if forced_ranges:
                forced_diagnostics, forced_candidates, forced_selected = self._fsk_remote_candidates_from_ranges(
                    iq,
                    forced_ranges,
                    sample_rate,
                )
                (output_dir / "fsk_burst_diagnostics.json").write_text(
                    json.dumps({"bursts": forced_diagnostics}, indent=2),
                    encoding="utf-8",
                )
                (output_dir / "fsk_candidate_decodings.json").write_text(
                    json.dumps({"candidate_count": len(forced_candidates), "candidates": forced_candidates}, indent=2),
                    encoding="utf-8",
                )
                (output_dir / "selected_fsk_decoding.json").write_text(
                    json.dumps(forced_selected, indent=2),
                    encoding="utf-8",
                )
                candidates = forced_candidates
                selected = forced_selected

        selected_ok = isinstance(selected, dict) and bool(selected)
        bitstream_candidate = selected_ok and int(selected.get("bit_length") or 0) > 0
        final_status = "fsk_bitstream_candidate" if bitstream_candidate else (
            "fsk_activity_detected_no_bitstream" if base.get("rf_activity_detected") else "no_signal_detected"
        )

        base.update(
            {
                "status": "partial_decode" if bitstream_candidate else "rf_activity_only",
                "final_status": final_status,
                "valid_demodulation": False,
                "protocol": "fsk_remote_control",
                "pipeline": "fsk_remote_decoder",
                "demodulation_pipeline": "fsk_remote_decoder",
                "recommended_pipeline": None,
                "fsk_candidates": len(candidates),
                "selected_fsk_decoding": selected if isinstance(selected, dict) else {},
                "notes": [
                    "FSK remote-control pipeline selected.",
                    "A candidate FSK bitstream was recovered, but no known remote-control frame format was validated."
                    if bitstream_candidate
                    else "RF activity was detected, but no stable FSK bitstream candidate was recovered.",
                ],
                "warnings": [
                    "candidate_only_no_protocol_crc",
                    "use repeated captures and compare selected_fsk_decoding for stable frame fields",
                ],
            }
        )
        base.setdefault("stage_diagnostics", {})
        base["stage_diagnostics"].update(
            {
                "pipeline": "fsk_remote_decoder",
                "fsk_candidates": len(candidates),
                "selected_fsk_bit_length": int(selected.get("bit_length") or 0) if isinstance(selected, dict) else 0,
                "selected_frequency_deviation_hz": selected.get("frequency_deviation_hz") if isinstance(selected, dict) else None,
                "selected_tone_separation_hz": selected.get("tone_separation_hz") if isinstance(selected, dict) else None,
                "selected_repetition_similarity": selected.get("repetition_similarity") if isinstance(selected, dict) else None,
                "demodulation_level_reached": "fsk_candidate_bitstream" if bitstream_candidate else "rf_activity_only",
            }
        )
        base = self._compact_fsk_remote_response(base)

        report_path = output_dir / "demodulation_report.json"
        base.setdefault("outputs", {})["report"] = str(report_path)
        report_path.write_text(json.dumps(base, indent=2, ensure_ascii=False), encoding="utf-8")
        return base

    def _ook433_estimate_t_unit(
        self, pulses: list[tuple[int, float]]
    ) -> tuple[float, float]:
        """
        Estimate the basic time quantum T (Âµs) via histogram peak detection on
        HIGH-pulse widths.  Returns (t_unit_Âµs, confidence 0â€“1).

        Most 433 MHz OOK protocols use two pulse lengths in a 1:3 ratio (EV1527,
        PT2262).  T is the shorter of the two dominant peaks.
        """
        if len(pulses) < 4:
            return 350.0, 0.0
        highs = np.array(
            [d for lv, d in pulses if lv == 1 and 80.0 <= d <= 8000.0],
            dtype=np.float32,
        )
        if highs.size < 2:
            return 350.0, 0.0
        # 20 Âµs bins over [80, 8000] Âµs
        bins = np.arange(80, 8001, 20, dtype=np.float32)
        hist, _ = np.histogram(highs, bins=bins)
        # Local maxima with count â‰¥ 2
        peak_centers: list[float] = []
        for i in range(1, len(hist) - 1):
            if hist[i] >= 2 and hist[i] > hist[i - 1] and hist[i] > hist[i + 1]:
                peak_centers.append(float(bins[i] + 10))
        if not peak_centers:
            t_unit = float(np.percentile(highs, 10))
            return max(t_unit, 80.0), 0.25
        peak_centers.sort()
        t_unit = peak_centers[0]
        confidence = 0.5
        if len(peak_centers) >= 2:
            ratio = peak_centers[1] / t_unit if t_unit > 0 else 0.0
            if 2.5 <= ratio <= 3.5:   # 1:3 â†’ EV1527, PT2262
                confidence = 0.90
            elif 1.8 <= ratio <= 2.2:  # 1:2 ratio
                confidence = 0.75
            elif 3.5 < ratio <= 4.5:  # 1:4 ratio
                confidence = 0.70
            else:
                confidence = 0.40
        return float(t_unit), confidence

    def _ook433_find_bursts(
        self,
        pulses: list[tuple[int, float]],
        t_unit_us: float,
    ) -> list[list[tuple[int, float]]]:
        """
        Segment pulse sequence into bursts separated by long LOW gaps (sync/inter-
        frame silence).  A gap delimiter is a LOW duration â‰¥ max(8Â·T, 2 ms).
        """
        if not pulses:
            return []
        gap_threshold_us = max(8.0 * t_unit_us, 2000.0)
        bursts: list[list[tuple[int, float]]] = []
        current: list[tuple[int, float]] = []
        for lv, dur_us in pulses:
            if lv == 0 and dur_us >= gap_threshold_us:
                if len(current) >= 6:  # minimum ~3 bit-pairs
                    bursts.append(current)
                current = []
            else:
                current.append((lv, dur_us))
        if len(current) >= 6:
            bursts.append(current)
        return bursts

    def _ook433_find_bursts_indexed(
        self,
        pulses: list[dict],
        t_unit_us: float,
        min_burst_duration_ms: float = 2.0,
        max_burst_duration_ms: float = 150.0,
        min_gap_duration_ms: float = 2.0,
    ) -> list[list[dict]]:
        """Segment indexed OOK pulses into bursts separated by long LOW gaps."""
        if not pulses:
            return []
        gap_threshold_us = max(8.0 * t_unit_us, min_gap_duration_ms * 1000.0)
        min_burst_us = min_burst_duration_ms * 1000.0
        max_burst_us = max_burst_duration_ms * 1000.0
        bursts: list[list[dict]] = []
        current: list[dict] = []
        def _append_valid(candidate: list[dict]) -> None:
            if len(candidate) < 2:
                return
            duration_us = float(candidate[-1]["end_sample"] - candidate[0]["start_sample"])
            # Convert samples to microseconds using pulse durations, avoiding a
            # sample-rate parameter in this low-level segmenter.
            duration_us = sum(float(p["duration_us"]) for p in candidate)
            if min_burst_us <= duration_us <= max_burst_us:
                bursts.append(candidate)
        for pulse in pulses:
            if pulse["level"] == 0 and pulse["duration_us"] >= gap_threshold_us:
                _append_valid(current)
                current = []
            else:
                current.append(pulse)
        _append_valid(current)
        return bursts

    def _ook433_invalid_continuous_runs(
        self,
        pulses: list[dict],
        t_unit_us: float,
        max_burst_duration_ms: float,
        min_gap_duration_ms: float,
    ) -> list[dict]:
        """Return pulse groups that look like an invalid continuous envelope."""
        if not pulses:
            return []
        gap_threshold_us = max(8.0 * t_unit_us, min_gap_duration_ms * 1000.0)
        max_burst_us = max_burst_duration_ms * 1000.0
        invalid: list[dict] = []
        current: list[dict] = []
        for pulse in pulses:
            if pulse["level"] == 0 and pulse["duration_us"] >= gap_threshold_us:
                if current:
                    duration_us = sum(float(p["duration_us"]) for p in current)
                    if duration_us > max_burst_us:
                        invalid.append({
                            "start_sample": int(current[0]["start_sample"]),
                            "end_sample": int(current[-1]["end_sample"]),
                            "duration_ms": duration_us / 1000.0,
                            "reason": "invalid_continuous_envelope",
                        })
                current = []
            else:
                current.append(pulse)
        if current:
            duration_us = sum(float(p["duration_us"]) for p in current)
            if duration_us > max_burst_us:
                invalid.append({
                    "start_sample": int(current[0]["start_sample"]),
                    "end_sample": int(current[-1]["end_sample"]),
                    "duration_ms": duration_us / 1000.0,
                    "reason": "invalid_continuous_envelope",
                })
        return invalid

    def _ook433_decode_pwm_bits(
        self, pulses: list[tuple[int, float]], t_unit_us: float
    ) -> list[int]:
        """
        Decode PWM bit-stream from consecutive HIGH+LOW pulse pairs.
        Convention (EV1527 / SC1527 / HX2262):
          bit 0 â†’ 1T HIGH + 3T LOW
          bit 1 â†’ 3T HIGH + 1T LOW
        Tolerance: Â±60 % of T to handle crystal tolerance and propagation jitter.
        """
        bits: list[int] = []
        tol = 0.6 * t_unit_us
        short = t_unit_us
        long_ = 3.0 * t_unit_us
        i = 0
        while i + 1 < len(pulses):
            lv_h, dur_h = pulses[i]
            lv_l, dur_l = pulses[i + 1]
            if lv_h != 1 or lv_l != 0:
                i += 1
                continue
            is_sh = abs(dur_h - short) <= tol
            is_lh = abs(dur_h - long_) <= tol
            is_sl = abs(dur_l - short) <= tol
            is_ll = abs(dur_l - long_) <= tol
            if is_sh and is_ll:
                bits.append(0)
                i += 2
            elif is_lh and is_sl:
                bits.append(1)
                i += 2
            else:
                i += 1
        return bits

    def _ook433_raw_bits_from_burst(
        self,
        binary: np.ndarray,
        start_sample: int,
        end_sample: int,
        sample_rate: float,
        t_unit_us: float,
    ) -> list[int]:
        """Protocol-agnostic OOK bit estimate by sampling the envelope in T-sized windows."""
        if binary.size == 0 or end_sample <= start_sample or sample_rate <= 0:
            return []
        samples_per_symbol = max(1, int(round(sample_rate * max(t_unit_us, 50.0) * 1e-6)))
        start = max(0, start_sample)
        stop = min(binary.size, end_sample)
        bits: list[int] = []
        for offset in range(start, stop, samples_per_symbol):
            window = binary[offset:min(stop, offset + samples_per_symbol)]
            if window.size == 0:
                continue
            bits.append(1 if float(np.mean(window)) >= 0.25 else 0)
        # Trim leading/trailing zeros from inter-symbol silence inside the segmented burst.
        while bits and bits[0] == 0:
            bits.pop(0)
        while bits and bits[-1] == 0:
            bits.pop()
        return bits

    def _ook433_bits_to_hex(self, bits: list[int]) -> str:
        if not bits:
            return ""
        arr = np.array(bits, dtype=np.uint8)
        pad_len = (len(arr) + 7) // 8 * 8
        padded = np.zeros(pad_len, dtype=np.uint8)
        padded[: len(arr)] = arr
        return np.packbits(padded).tobytes().hex().upper()

    def _ook433_match_ev1527(self, bits: list[int]) -> dict | None:
        """
        Match an EV1527 / SC1527 / HX2262 24-bit OOK frame.
        Frame structure: [20-bit device address][4-bit button code].
        Bit order: MSB first (as transmitted on-air after sync pulse).
        No CRC â€” receiver relies on repetition for reliability.
        """
        if len(bits) < 24:
            return None
        addr_bits = bits[:20]
        btn_bits = bits[20:24]
        address = sum(b << (19 - i) for i, b in enumerate(addr_bits))
        button = sum(b << (3 - i) for i, b in enumerate(btn_bits))
        # Degenerate addresses (all-0 or all-1) indicate floating encoder pins
        if address == 0 or address == (1 << 20) - 1:
            return None
        return {
            "protocol": "EV1527",
            "address": f"0x{address:05X}",
            "address_int": address,
            "button_code": f"0x{button:X}",
            "button_int": button,
            "button_bits": "".join(str(b) for b in btn_bits),
            "raw_bits": "".join(str(b) for b in bits[:24]),
            "extra_bits": len(bits) - 24,
        }

    def _ook433_match_pt2262(
        self, pulses: list[tuple[int, float]], t_unit_us: float
    ) -> dict | None:
        """
        Match a PT2262 / SC2262 / HT6P20B 12-tri-state OOK frame.
        Each tri-state is two consecutive PWM pulse-pairs (4 pulses total):
          tri 0 â†’ (1T H + 3T L) + (1T H + 3T L)  [D0 D0]
          tri 1 â†’ (3T H + 1T L) + (3T H + 1T L)  [D1 D1]
          tri F â†’ (1T H + 3T L) + (3T H + 1T L)  [D0 D1]  (floating pin)
        12 tri-states â†’ 8 address + 4 data.
        """
        if len(pulses) < 48:
            return None
        tol = 0.6 * t_unit_us
        short = t_unit_us
        long_ = 3.0 * t_unit_us

        def _pair_type(lv_h: int, dur_h: float, lv_l: int, dur_l: float) -> str | None:
            if lv_h != 1 or lv_l != 0:
                return None
            if abs(dur_h - short) <= tol and abs(dur_l - long_) <= tol:
                return "S"
            if abs(dur_h - long_) <= tol and abs(dur_l - short) <= tol:
                return "L"
            return None

        tristate: list[str] = []
        i = 0
        while i + 3 < len(pulses) and len(tristate) < 12:
            p1 = _pair_type(pulses[i][0], pulses[i][1], pulses[i + 1][0], pulses[i + 1][1])
            p2 = _pair_type(pulses[i + 2][0], pulses[i + 2][1], pulses[i + 3][0], pulses[i + 3][1])
            if p1 is None or p2 is None:
                return None
            if p1 == "S" and p2 == "S":
                tristate.append("0")
            elif p1 == "L" and p2 == "L":
                tristate.append("1")
            elif p1 == "S" and p2 == "L":
                tristate.append("F")
            else:
                return None
            i += 4
        if len(tristate) < 12:
            return None
        ts_str = "".join(tristate)
        return {
            "protocol": "PT2262",
            "tristate_code": ts_str,
            "address_tristates": ts_str[:8],
            "data_tristates": ts_str[8:],
        }

    def _ook433_repeat_analysis(self, all_bits: list[list[int]]) -> dict:
        """Detect identical repeated burst patterns (typical for OOK remotes)."""
        if not all_bits:
            return {"repetition_detected": False, "burst_count": 0}
        patterns = [
            "".join(str(b) for b in bits[: min(24, len(bits))])
            for bits in all_bits
            if len(bits) >= 8
        ]
        if not patterns:
            return {"repetition_detected": False, "burst_count": len(all_bits)}
        most_common = max(set(patterns), key=patterns.count)
        count = patterns.count(most_common)
        return {
            "repetition_detected": count >= 2,
            "burst_count": len(all_bits),
            "most_repeated_pattern": most_common if count >= 2 else None,
            "repetition_count": count,
            "unique_patterns": len(set(patterns)),
        }

    def _ook433_bit_similarity(self, left: list[int], right: list[int]) -> float:
        """Return 0-1 similarity over the overlapping portion of two bitstrings."""
        n = min(len(left), len(right))
        if n == 0:
            return 0.0
        matches = sum(1 for i in range(n) if left[i] == right[i])
        length_penalty = n / max(len(left), len(right), 1)
        return float((matches / n) * length_penalty)

    def _ook433_cluster_bits(self, all_bits: list[list[int]], threshold: float = 0.85) -> list[int | None]:
        """Assign simple similarity clusters for repeated/rolling-code inspection."""
        clusters: list[list[int]] = []
        assignments: list[int | None] = []
        for bits in all_bits:
            if not bits:
                assignments.append(None)
                continue
            assigned = None
            for cluster_index, representative in enumerate(clusters):
                if self._ook433_bit_similarity(bits, representative) >= threshold:
                    assigned = cluster_index
                    break
            if assigned is None:
                clusters.append(bits)
                assigned = len(clusters) - 1
            assignments.append(assigned)
        return assignments

    def _ook433_binary_entropy(self, bits: list[int]) -> float:
        if not bits:
            return 0.0
        ones = sum(1 for bit in bits if bit == 1)
        p1 = ones / len(bits)
        p0 = 1.0 - p1
        entropy = 0.0
        for p in (p0, p1):
            if p > 0:
                entropy -= p * float(np.log2(p))
        return float(entropy)

    def _ook433_duration_histogram(self, durations_us: list[float], bin_us: float = 50.0) -> list[dict]:
        values = np.array([d for d in durations_us if d >= 0], dtype=np.float32)
        if values.size == 0:
            return []
        max_value = max(float(np.max(values)), bin_us)
        bins = np.arange(0.0, max_value + bin_us * 2.0, bin_us, dtype=np.float32)
        hist, edges = np.histogram(values, bins=bins)
        return [
            {
                "start_us": round(float(edges[i]), 3),
                "end_us": round(float(edges[i + 1]), 3),
                "count": int(count),
            }
            for i, count in enumerate(hist)
            if count > 0
        ]

    def _ook433_classify_duration(self, duration_us: float, classes: dict) -> str:
        if duration_us >= float(classes["sync_threshold_us"]):
            return "sync"
        return "long" if self._ook433_is_long(duration_us, classes) else "short"

    def _ook433_mostly_trivial_hex(self, hex_text: str) -> bool:
        cleaned = "".join(ch for ch in (hex_text or "").upper() if ch in "0123456789ABCDEF")
        if len(cleaned) < 8:
            return False
        dominant = max(cleaned.count("F"), cleaned.count("0"))
        return dominant / max(len(cleaned), 1) >= 0.85

    def _ook433_mostly_trivial_bits(self, bitstring: str) -> bool:
        bits = "".join(ch for ch in (bitstring or "") if ch in "01")
        if len(bits) < 32:
            return False
        dominant = max(bits.count("1"), bits.count("0"))
        return dominant / max(len(bits), 1) >= 0.85

    def _ook433_duration_classes(self, durations_us: list[float], unit_us: float) -> dict:
        valid = np.array([d for d in durations_us if d >= 40.0], dtype=np.float32)
        if valid.size == 0:
            return {"short_us": unit_us, "long_us": 3.0 * unit_us, "sync_threshold_us": 8.0 * unit_us}
        short_us = float(np.percentile(valid, 25))
        long_us = float(np.percentile(valid, 75))
        if long_us < short_us * 1.5:
            long_us = max(3.0 * max(short_us, unit_us), long_us)
        return {
            "short_us": max(40.0, short_us),
            "long_us": max(long_us, short_us),
            "sync_threshold_us": max(8.0 * max(unit_us, short_us), 2000.0),
        }

    def _ook433_is_long(self, duration_us: float, classes: dict) -> bool:
        return duration_us >= (float(classes["short_us"]) + float(classes["long_us"])) / 2.0

    def _ook433_fixed_period_bits(
        self,
        binary: np.ndarray,
        start_sample: int,
        end_sample: int,
        sample_rate: float,
        symbol_unit_us: float,
        threshold: float = 0.25,
    ) -> list[int]:
        if binary.size == 0 or end_sample <= start_sample or sample_rate <= 0:
            return []
        samples_per_symbol = max(1, int(round(sample_rate * max(symbol_unit_us, 50.0) * 1e-6)))
        bits: list[int] = []
        start = max(0, start_sample)
        stop = min(binary.size, end_sample)
        for offset in range(start, stop, samples_per_symbol):
            window = binary[offset:min(stop, offset + samples_per_symbol)]
            if window.size:
                bits.append(1 if float(np.mean(window)) >= threshold else 0)
        while bits and bits[0] == 0:
            bits.pop(0)
        while bits and bits[-1] == 0:
            bits.pop()
        return bits

    def _ook433_bits_from_internal_pulses(
        self,
        pulses: list[tuple[int, float]],
        symbol_unit_us: float,
    ) -> list[int]:
        """Convert symbol-level pulse runs to a raw NRZ projection."""
        if not pulses:
            return []
        unit = max(float(symbol_unit_us or 0.0), 50.0)
        bits: list[int] = []
        for level, duration_us in pulses:
            repeat = max(1, int(round(float(duration_us) / unit)))
            bits.extend([int(level)] * repeat)
        while bits and bits[0] == 0:
            bits.pop(0)
        while bits and bits[-1] == 0:
            bits.pop()
        return bits

    def _ook433_decode_hypothesis(
        self,
        encoding_type: str,
        pulses: list[tuple[int, float]],
        binary: np.ndarray,
        start_sample: int,
        end_sample: int,
        sample_rate: float,
        unit_us: float,
        classes: dict,
    ) -> list[int]:
        bits: list[int] = []
        if encoding_type in {"raw_ook_nrz", "fixed_symbol_period"}:
            if pulses:
                return self._ook433_bits_from_internal_pulses(pulses, unit_us)
            return self._ook433_fixed_period_bits(binary, start_sample, end_sample, sample_rate, unit_us)
        if encoding_type == "pulse_width":
            return [1 if self._ook433_is_long(dur, classes) else 0 for level, dur in pulses if level == 1]
        if encoding_type in {"pulse_distance", "ppm"}:
            for i in range(len(pulses) - 1):
                level, _dur = pulses[i]
                next_level, gap = pulses[i + 1]
                if level == 1 and next_level == 0 and gap < classes["sync_threshold_us"]:
                    bits.append(1 if self._ook433_is_long(gap, classes) else 0)
            return bits
        if encoding_type == "pwm":
            i = 0
            while i + 1 < len(pulses):
                lv_h, dur_h = pulses[i]
                lv_l, dur_l = pulses[i + 1]
                if lv_h == 1 and lv_l == 0:
                    high_long = self._ook433_is_long(dur_h, classes)
                    low_long = self._ook433_is_long(dur_l, classes)
                    if not high_long and low_long:
                        bits.append(0)
                    elif high_long and not low_long:
                        bits.append(1)
                    elif high_long != low_long:
                        bits.append(1 if high_long else 0)
                    i += 2
                else:
                    i += 1
            return bits
        if encoding_type == "manchester":
            raw = self._ook433_fixed_period_bits(binary, start_sample, end_sample, sample_rate, max(50.0, unit_us / 2.0))
            for i in range(0, len(raw) - 1, 2):
                pair = (raw[i], raw[i + 1])
                if pair == (0, 1):
                    bits.append(0)
                elif pair == (1, 0):
                    bits.append(1)
            return bits
        if encoding_type in {"differential_manchester", "bi_phase"}:
            raw = self._ook433_fixed_period_bits(binary, start_sample, end_sample, sample_rate, max(50.0, unit_us / 2.0))
            previous = 1
            for i in range(0, len(raw) - 1, 2):
                first, second = raw[i], raw[i + 1]
                if first == second:
                    continue
                transition_at_start = first != previous
                bits.append(0 if transition_at_start else 1)
                previous = second
            return bits
        if encoding_type == "tri_state":
            pwm_bits = self._ook433_decode_hypothesis("pwm", pulses, binary, start_sample, end_sample, sample_rate, unit_us, classes)
            # Keep tri-state as a binary projection so common/variable positions remain comparable.
            for i in range(0, len(pwm_bits) - 1, 2):
                pair = (pwm_bits[i], pwm_bits[i + 1])
                if pair == (0, 0):
                    bits.extend([0, 0])
                elif pair == (1, 1):
                    bits.extend([1, 1])
                elif pair in {(0, 1), (1, 0)}:
                    bits.extend([0, 1])
            return bits
        return []

    def _ook433_adaptive_decodings(
        self,
        binary: np.ndarray,
        bursts_indexed: list[list[dict]],
        sample_rate: float,
        t_unit_us: float,
        repetition_detected: bool = False,
        known_protocol_matched: bool = False,
        invalid_continuous_count: int = 0,
    ) -> tuple[list[dict], dict]:
        encoding_types = [
            "raw_ook_nrz",
            "pulse_width",
            "pulse_distance",
            "pwm",
            "ppm",
            "manchester",
            "differential_manchester",
            "bi_phase",
            "tri_state",
            "fixed_symbol_period",
        ]
        all_candidates: list[dict] = []
        all_pulse_durations = [float(p["duration_us"]) for burst in bursts_indexed for p in burst]
        classes = self._ook433_duration_classes(all_pulse_durations, t_unit_us)
        for encoding_type in encoding_types:
            per_burst: list[dict] = []
            bitsets: list[list[int]] = []
            for burst_index, burst in enumerate(bursts_indexed):
                if not burst:
                    bits: list[int] = []
                    start_sample = end_sample = 0
                else:
                    start_sample = int(burst[0]["start_sample"])
                    end_sample = int(burst[-1]["end_sample"])
                    pulses = [(int(p["level"]), float(p["duration_us"])) for p in burst]
                    bits = self._ook433_decode_hypothesis(
                        encoding_type,
                        pulses,
                        binary,
                        start_sample,
                        end_sample,
                        sample_rate,
                        t_unit_us,
                        classes,
                    )
                bitsets.append(bits)
                per_burst.append(
                    {
                        "burst_index": burst_index,
                        "bitstring": "".join(str(bit) for bit in bits),
                        "hex_candidate": self._ook433_bits_to_hex(bits),
                        "bit_length": len(bits),
                    }
                )
            non_empty = [bits for bits in bitsets if bits]
            lengths = np.array([len(bits) for bits in non_empty], dtype=np.float32)
            if lengths.size:
                median_len = int(np.median(lengths))
                representative = max(non_empty, key=lambda bits: (len(bits), non_empty.count(bits)))
                length_consistency = float(max(0.0, 1.0 - (np.std(lengths) / max(float(np.mean(lengths)), 1.0))))
            else:
                median_len = 0
                representative = []
                length_consistency = 0.0
            similarities = []
            for i in range(len(non_empty)):
                for j in range(i + 1, len(non_empty)):
                    similarities.append(self._ook433_bit_similarity(non_empty[i], non_empty[j]))
            repetition_similarity = float(np.mean(similarities)) if similarities else (1.0 if len(non_empty) == 1 else 0.0)
            entropy = self._ook433_binary_entropy(representative)
            entropy_score = 1.0 - min(1.0, abs(entropy - 0.65) / 0.65)
            min_len = min((len(bits) for bits in non_empty), default=0)
            common_positions = []
            variable_bit_positions = []
            if min_len > 0:
                for pos in range(min(min_len, 512)):
                    values = [bits[pos] for bits in non_empty if len(bits) > pos]
                    if values and all(value == values[0] for value in values):
                        common_positions.append({"position": pos, "bit": values[0]})
                    else:
                        variable_bit_positions.append(pos)
            trivial = entropy < 0.08 or median_len < 8
            penalties = {
                "single_burst_penalty": 0.55 if len(non_empty) <= 1 else 1.0,
                "no_repetition_penalty": 0.45 if not repetition_detected else 1.0,
                "excessive_duration_penalty": 0.45 if invalid_continuous_count > 0 else 1.0,
                "trivial_hex_penalty": 0.20 if entropy < 0.08 else 1.0,
                "no_protocol_match_penalty": 0.85 if not known_protocol_matched else 1.0,
            }
            confidence = (
                0.35 * repetition_similarity
                + 0.25 * length_consistency
                + 0.20 * entropy_score
                + 0.20 * (0.0 if trivial else 1.0)
            )
            for penalty in penalties.values():
                confidence *= penalty
            rejection_reason = None
            if not non_empty:
                rejection_reason = "no_bits_recovered"
            elif median_len < 8:
                rejection_reason = "too_short"
            elif entropy < 0.08:
                rejection_reason = "trivial_all_zeros_or_ones"
            elif len(non_empty) <= 1:
                rejection_reason = "single_burst_no_repetition"
            elif repetition_similarity < 0.55:
                rejection_reason = "unstable_between_repeated_bursts"
            candidate = {
                "encoding_type": encoding_type,
                "bitstring": "".join(str(bit) for bit in representative),
                "hex_candidate": self._ook433_bits_to_hex(representative),
                "bit_length": len(representative),
                "sync_pattern": {
                    "short_us": round(float(classes["short_us"]), 3),
                    "long_us": round(float(classes["long_us"]), 3),
                    "sync_threshold_us": round(float(classes["sync_threshold_us"]), 3),
                },
                "preamble_length": self._ook433_preamble_length(representative),
                "symbol_unit_us": round(float(t_unit_us), 3),
                "repetition_similarity": round(repetition_similarity, 4),
                "length_consistency": round(length_consistency, 4),
                "entropy": round(entropy, 4),
                "variable_bit_positions": variable_bit_positions[:256],
                "common_bit_positions": common_positions[:256],
                "confidence": round(float(max(0.0, min(1.0, confidence))), 4),
                "penalties": penalties,
                "selected_reason": (
                    f"{encoding_type} produced repetition_similarity={repetition_similarity:.3f}, "
                    f"length_consistency={length_consistency:.3f}, entropy={entropy:.3f}; "
                    f"penalties={{{', '.join(f'{k}:{v:.2f}' for k, v in penalties.items())}}}"
                ),
                "rejection_reason": rejection_reason,
                "per_burst": per_burst,
            }
            all_candidates.append(candidate)
        selected = max(
            all_candidates,
            key=lambda item: (item["rejection_reason"] is None, item["confidence"], item["bit_length"]),
            default={},
        )
        return all_candidates, selected

    def _ook433_preamble_length(self, bits: list[int]) -> int:
        if not bits:
            return 0
        first = bits[0]
        count = 0
        for bit in bits:
            if bit != first:
                break
            count += 1
        return count

    def _ook433_burst_rf_metrics(
        self,
        iq: np.ndarray,
        start_sample: int,
        end_sample: int,
        center_hz: float,
        sample_rate: float,
        noise_floor_power: float,
        capture_bandwidth_hz: float | None = None,
    ) -> dict:
        """Estimate RF peak, occupied bandwidth and burst-local SNR from IQ."""
        if iq.size == 0 or end_sample <= start_sample:
            return {"peak_frequency_hz": None, "estimated_bandwidth_hz": None, "snr_db": None}
        segment = iq[max(0, start_sample): min(iq.size, end_sample)]
        if segment.size < 16:
            return {"peak_frequency_hz": None, "estimated_bandwidth_hz": None, "snr_db": None}
        nfft = int(2 ** np.ceil(np.log2(min(max(segment.size, 256), 16384))))
        window = np.hanning(segment.size).astype(np.float32)
        if window.size != segment.size:
            window = np.ones(segment.size, dtype=np.float32)
        spectrum = np.fft.fftshift(np.fft.fft(segment * window, n=nfft))
        power = np.abs(spectrum) ** 2
        freqs = np.fft.fftshift(np.fft.fftfreq(nfft, d=1.0 / sample_rate))
        if capture_bandwidth_hz and capture_bandwidth_hz > 0:
            band_mask = np.abs(freqs) <= (float(capture_bandwidth_hz) / 2.0)
            if not np.any(band_mask):
                band_mask = np.ones_like(freqs, dtype=bool)
        else:
            band_mask = np.ones_like(freqs, dtype=bool)
        band_power = power[band_mask]
        band_freqs = freqs[band_mask]
        peak_idx = int(np.argmax(band_power))
        peak_frequency_hz = float(center_hz + band_freqs[peak_idx])
        total = float(np.sum(power))
        bandwidth_hz = None
        if total > 0 and band_power.size:
            band_total = float(np.sum(band_power))
            cdf = np.cumsum(band_power) / max(band_total, 1e-20)
            lo = int(np.searchsorted(cdf, 0.005))
            hi = int(np.searchsorted(cdf, 0.995))
            lo = max(0, min(lo, band_freqs.size - 1))
            hi = max(0, min(hi, band_freqs.size - 1))
            bandwidth_hz = float(abs(band_freqs[hi] - band_freqs[lo]))
        if capture_bandwidth_hz and capture_bandwidth_hz > 0:
            low = center_hz - float(capture_bandwidth_hz) / 2.0
            high = center_hz + float(capture_bandwidth_hz) / 2.0
            peak_frequency_hz = float(min(max(peak_frequency_hz, low), high))
            if bandwidth_hz is not None:
                bandwidth_hz = float(min(bandwidth_hz, float(capture_bandwidth_hz)))
        burst_power = float(np.mean(np.abs(segment) ** 2))
        snr_db = float(10.0 * np.log10(max(burst_power, 1e-20) / max(noise_floor_power, 1e-20)))
        return {
            "peak_frequency_hz": peak_frequency_hz,
            "estimated_bandwidth_hz": bandwidth_hz,
            "snr_db": snr_db,
        }

    def _ook_433_remote(self, iq: np.ndarray, data: dict, output_dir: Path) -> dict:
        """
        Full OOK remote-control decoder for the 433.92 MHz (EU/AS), 315 MHz (NA)
        and 868 MHz (EU SRD) ISM bands.

        Pipeline stages:
          1. Adaptive envelope thresholding (IQR-based, robust to ISM noise floor).
          2. Binary pulse-sequence extraction with 50 Âµs glitch rejection.
          3. T-unit estimation via histogram peak detection on HIGH-pulse widths.
          4. Burst segmentation by sync-gap detection (LOW â‰¥ 8Â·T or 2 ms).
          5. Per-burst PWM decoding (1T/3T convention) + protocol matching:
               â€¢ EV1527 / SC1527 / HX2262  (20-bit address + 4-bit button, no CRC)
               â€¢ PT2262 / SC2262 / HT6P20B (12 tri-states: 8-addr + 4-data)
          6. Repetition analysis: most remotes repeat the frame 3â€“10 times per press.
        """
        center = float(data.get("center_frequency_hz") or 0.0)
        sample_rate = float(data.get("sample_rate_hz") or 1.0)
        capture_bandwidth_hz = float(data.get("bandwidth_hz") or sample_rate)
        min_burst_duration_ms = float(data.get("min_burst_duration_ms") or 2.0)
        max_burst_duration_ms = float(data.get("max_burst_duration_ms") or 150.0)
        min_gap_duration_ms = float(data.get("min_gap_duration_ms") or 2.5)

        # ISM sub-band identification
        in_433_band = 433_050_000 <= center <= 434_790_000
        in_315_band = 314_000_000 <= center <= 316_000_000
        in_868_band = 868_000_000 <= center <= 868_600_000
        in_band = in_433_band or in_315_band or in_868_band

        activity = self._summarize_iq_activity(iq, sample_rate)

        threshold_candidates: list[float] = []
        if iq.size == 0:
            envelope = np.array([], dtype=np.float32)
            binary = np.array([], dtype=np.uint8)
            threshold = 0.0
        else:
            envelope = np.abs(iq).astype(np.float32)
            # IQR-based adaptive threshold: more robust than median+std for
            # impulsive ISM interference.  Falls back to mean*1.5 if IQR is
            # near-zero (continuous carrier or flat noise).
            p25 = float(np.percentile(envelope, 25))
            p75 = float(np.percentile(envelope, 75))
            iqr = p75 - p25
            if iqr > 0:
                threshold = p75 + 1.5 * iqr
            else:
                threshold = float(np.mean(envelope)) * 1.5 + 1e-12
            threshold = max(threshold, float(np.mean(envelope)) * 1.2)
            threshold_candidates = [
                threshold,
                float(np.percentile(envelope, 85)),
                float(np.percentile(envelope, 90)),
                float(np.percentile(envelope, 95)),
                float(np.percentile(envelope, 97.5)),
                float(np.percentile(envelope, 99)),
            ]
            # Preserve order but remove duplicate thresholds.
            seen_thresholds: set[float] = set()
            threshold_candidates = [
                value for value in threshold_candidates
                if not (round(value, 12) in seen_thresholds or seen_thresholds.add(round(value, 12)))
            ]
            binary = (envelope > threshold).astype(np.uint8)

        best_segmentation: dict | None = None
        all_invalid_continuous_runs: list[dict] = []
        for candidate_threshold in (threshold_candidates or [threshold]):
            candidate_binary = (envelope > candidate_threshold).astype(np.uint8) if envelope.size else binary
            candidate_pulses = self._ook433_pulse_sequence_indexed(candidate_binary, sample_rate)
            candidate_tuple_pulses = [(pulse["level"], pulse["duration_us"]) for pulse in candidate_pulses]
            candidate_t_unit_us, candidate_t_confidence = self._ook433_estimate_t_unit(candidate_tuple_pulses)
            candidate_bursts = self._ook433_find_bursts_indexed(
                candidate_pulses,
                candidate_t_unit_us,
                min_burst_duration_ms=min_burst_duration_ms,
                max_burst_duration_ms=max_burst_duration_ms,
                min_gap_duration_ms=min_gap_duration_ms,
            )
            candidate_invalid = self._ook433_invalid_continuous_runs(
                candidate_pulses,
                candidate_t_unit_us,
                max_burst_duration_ms=max_burst_duration_ms,
                min_gap_duration_ms=min_gap_duration_ms,
            )
            all_invalid_continuous_runs.extend(candidate_invalid)
            burst_count = len(candidate_bursts)
            invalid_count = len(candidate_invalid)
            burst_durations_ms = [
                sum(float(p["duration_us"]) for p in burst) / 1000.0
                for burst in candidate_bursts
            ]
            good_duration_count = sum(20.0 <= duration <= 80.0 for duration in burst_durations_ms)
            short_fragment_count = sum(duration < 10.0 for duration in burst_durations_ms)
            median_duration_ms = float(np.median(burst_durations_ms)) if burst_durations_ms else 0.0
            # Prefer repeated remote-control frames (tens of ms), not the
            # largest number of tiny fragments produced by an over-strict threshold.
            score = (
                good_duration_count * 150
                + min(burst_count, 25) * 10
                + candidate_t_confidence * 10
                - short_fragment_count * 25
                - abs(median_duration_ms - 35.0) * 2
                - invalid_count * 200
            )
            if burst_count == 1:
                score -= 50
            if burst_count == 0:
                score -= 100
            if burst_count > 40:
                score -= (burst_count - 40) * 20
            if best_segmentation is None or score > best_segmentation["score"]:
                best_segmentation = {
                    "score": score,
                    "threshold": candidate_threshold,
                    "good_duration_count": good_duration_count,
                    "short_fragment_count": short_fragment_count,
                    "median_duration_ms": median_duration_ms,
                    "binary": candidate_binary,
                    "indexed_pulses": candidate_pulses,
                    "pulses": candidate_tuple_pulses,
                    "t_unit_us": candidate_t_unit_us,
                    "t_confidence": candidate_t_confidence,
                    "bursts_indexed": candidate_bursts,
                    "invalid_continuous_runs": candidate_invalid,
                }

        if best_segmentation:
            threshold = float(best_segmentation["threshold"])
            binary = best_segmentation["binary"]
            indexed_pulses = best_segmentation["indexed_pulses"]
            pulses = best_segmentation["pulses"]
            t_unit_us = float(best_segmentation["t_unit_us"])
            t_confidence = float(best_segmentation["t_confidence"])
            bursts_indexed = best_segmentation["bursts_indexed"]
            invalid_continuous_runs = best_segmentation["invalid_continuous_runs"]
            if not bursts_indexed and not invalid_continuous_runs and all_invalid_continuous_runs:
                invalid_continuous_runs = all_invalid_continuous_runs[:10]
        else:
            indexed_pulses = []
            pulses = []
            t_unit_us, t_confidence = 350.0, 0.0
            bursts_indexed = []
            invalid_continuous_runs = []

        symbol_rate_baud = int(round(1e6 / t_unit_us)) if t_unit_us > 0 else 0

        decoded_bursts: list[dict] = []
        all_decoded_bits: list[list[int]] = []
        noise_floor_power = float(np.median(np.abs(iq) ** 2)) if iq.size else 0.0
        preliminary_diagnostics: list[dict] = []
        all_mark_us: list[float] = []
        all_space_us: list[float] = []
        symbol_bursts_indexed: list[list[dict]] = []
        raw_pulse_bursts: list[dict] = []
        for i, indexed_burst in enumerate(bursts_indexed):
            start_sample = int(indexed_burst[0]["start_sample"]) if indexed_burst else 0
            end_sample = int(indexed_burst[-1]["end_sample"]) if indexed_burst else start_sample
            burst_duration_s = (end_sample - start_sample) / sample_rate if sample_rate > 0 else None
            internal_pulses, internal_threshold = self._ook433_internal_pulses_for_burst(
                envelope,
                start_sample,
                end_sample,
                sample_rate,
                min_glitch_us=100.0,
            )
            internal_metrics = self._ook433_internal_pulse_metrics(internal_pulses, burst_duration_s)
            frequency_metrics = self._ook433_instantaneous_frequency_metrics(iq, start_sample, end_sample, sample_rate)
            symbol_burst = internal_pulses if internal_metrics["symbol_level_detected"] else []
            symbol_bursts_indexed.append(symbol_burst)
            burst = [(pulse["level"], pulse["duration_us"]) for pulse in symbol_burst]
            protocol_bits = self._ook433_decode_pwm_bits(burst, t_unit_us) if symbol_burst else []
            raw_bits = (
                self._ook433_bits_from_internal_pulses(burst, t_unit_us)
                if internal_metrics["symbol_level_detected"]
                else []
            )
            bits = protocol_bits if protocol_bits else raw_bits
            all_decoded_bits.append(bits)
            ev1527 = self._ook433_match_ev1527(protocol_bits) if len(protocol_bits) >= 24 else None
            pt2262 = self._ook433_match_pt2262(burst, t_unit_us) if len(burst) >= 48 else None
            pulse_widths_us = [round(float(p["duration_us"]), 3) for p in internal_pulses if p["level"] == 1]
            gap_widths_us = [round(float(p["duration_us"]), 3) for p in internal_pulses if p["level"] == 0]
            all_mark_us.extend(float(value) for value in pulse_widths_us)
            all_space_us.extend(float(value) for value in gap_widths_us)
            burst_t_unit = float(np.median(pulse_widths_us)) if pulse_widths_us else t_unit_us
            burst_symbol_rate = int(round(1e6 / burst_t_unit)) if burst_t_unit > 0 else None
            raw_bitstring = "".join(str(bit) for bit in bits)
            rf_metrics = self._ook433_burst_rf_metrics(
                iq,
                start_sample,
                end_sample,
                center,
                sample_rate,
                noise_floor_power,
                capture_bandwidth_hz,
            )
            decoded_bursts.append(
                {
                    "burst_index": i,
                    "pulse_count": len(burst),
                    "bit_count": len(bits),
                    "protocol_bit_count": len(protocol_bits),
                    "raw_bit_count": len(raw_bits),
                    "raw_bitstring": raw_bitstring,
                    "bits_hex": self._ook433_bits_to_hex(bits),
                    "ev1527": ev1527,
                    "pt2262": pt2262,
                    "protocol_detected": (
                        "EV1527" if ev1527 else "PT2262" if pt2262 else "unknown_ook"
                    ),
                }
            )
            raw_pulse_bursts.append(
                {
                    "burst_id": i,
                    "burst_start_us": round(float(start_sample / sample_rate * 1e6), 3) if sample_rate > 0 else None,
                    "burst_duration_us": round(float((end_sample - start_sample) / sample_rate * 1e6), 3) if sample_rate > 0 else None,
                    "internal_threshold": internal_threshold,
                    "internal_transition_count": internal_metrics["internal_transition_count"],
                    "symbol_level_detected": internal_metrics["symbol_level_detected"],
                    "possible_modulation": frequency_metrics.get("possible_modulation"),
                    "internal_pulses": [
                        {
                            "level": int(pulse["level"]),
                            "duration_us": round(float(pulse["duration_us"]), 3),
                        }
                        for pulse in internal_pulses
                    ],
                }
            )
            preliminary_diagnostics.append(
                {
                    "burst_index": i,
                    "burst_start_time": start_sample / sample_rate if sample_rate > 0 else None,
                    "burst_end_time": end_sample / sample_rate if sample_rate > 0 else None,
                    "burst_duration": (end_sample - start_sample) / sample_rate if sample_rate > 0 else None,
                    "burst_start_sample": start_sample,
                    "burst_end_sample": end_sample,
                    "peak_frequency_hz": rf_metrics["peak_frequency_hz"],
                    "estimated_bandwidth_hz": rf_metrics["estimated_bandwidth_hz"],
                    "snr_db": rf_metrics["snr_db"],
                    "symbol_rate_estimate": burst_symbol_rate,
                    "pulse_widths_us": pulse_widths_us,
                    "gap_widths_us": gap_widths_us,
                    "mark_us": pulse_widths_us,
                    "space_us": gap_widths_us,
                    **internal_metrics,
                    **frequency_metrics,
                    "bit_count": len(bits),
                    "protocol_bit_count": len(protocol_bits),
                    "raw_bit_count": len(raw_bits),
                    "bit_recovery_method": (
                        "protocol_pwm" if protocol_bits
                        else "raw_envelope_sampling" if raw_bits
                        else "not_attempted_no_symbol_level_transitions"
                    ),
                    "raw_bitstring": raw_bitstring,
                    "hex_candidate": self._ook433_bits_to_hex(bits),
                    "protocol_detected": "EV1527" if ev1527 else "PT2262" if pt2262 else "unknown_ook",
                }
            )

        repeat_analysis = self._ook433_repeat_analysis(all_decoded_bits)
        cluster_ids = self._ook433_cluster_bits(all_decoded_bits)
        similarity_matrix: list[list[float]] = []
        for left in all_decoded_bits:
            similarity_matrix.append([
                round(self._ook433_bit_similarity(left, right), 4)
                for right in all_decoded_bits
            ])
        for i, diag in enumerate(preliminary_diagnostics):
            row = similarity_matrix[i] if i < len(similarity_matrix) else []
            other_scores = [score for j, score in enumerate(row) if j != i]
            diag["repetition_score"] = round(max(other_scores), 4) if other_scores else 0.0
            diag["similarity_between_bursts"] = row
            diag["clustering_id"] = cluster_ids[i] if i < len(cluster_ids) else None
        cluster_counts: dict[str, int] = {}
        for cluster_id in cluster_ids:
            key = "unclustered" if cluster_id is None else str(cluster_id)
            cluster_counts[key] = cluster_counts.get(key, 0) + 1
        rolling_code_candidates = []
        for i, bits in enumerate(all_decoded_bits):
            for j in range(i + 1, len(all_decoded_bits)):
                similarity = self._ook433_bit_similarity(bits, all_decoded_bits[j])
                if 0.35 <= similarity < 0.85 and min(len(bits), len(all_decoded_bits[j])) >= 16:
                    rolling_code_candidates.append(
                        {"left_burst": i, "right_burst": j, "similarity": round(similarity, 4)}
                    )
        duration_classes = self._ook433_duration_classes(all_mark_us + all_space_us, t_unit_us)
        for diag in preliminary_diagnostics:
            diag["mark_classes"] = [
                self._ook433_classify_duration(float(value), duration_classes)
                for value in diag.get("mark_us", [])
            ]
            diag["space_classes"] = [
                self._ook433_classify_duration(float(value), duration_classes)
                for value in diag.get("space_us", [])
            ]

        n_bursts = len(decoded_bursts)
        n_ev1527 = sum(1 for b in decoded_bursts if b["ev1527"])
        n_pt2262 = sum(1 for b in decoded_bursts if b["pt2262"])
        possible_modulation_counts: dict[str, int] = {}
        for diag in preliminary_diagnostics:
            modulation = str(diag.get("possible_modulation") or "unknown")
            possible_modulation_counts[modulation] = possible_modulation_counts.get(modulation, 0) + 1

        # Select the best frame: most frequently repeated address wins
        best_frame: dict | None = None
        if n_ev1527 > 0:
            addrs = [b["ev1527"]["address"] for b in decoded_bursts if b["ev1527"]]
            best_addr = max(set(addrs), key=addrs.count)
            best_frame = next(
                b["ev1527"] for b in decoded_bursts
                if b.get("ev1527") and b["ev1527"]["address"] == best_addr
            )
            best_frame = dict(best_frame)
            best_frame["address_repetitions"] = addrs.count(best_addr)
        elif n_pt2262 > 0:
            tristates = [b["pt2262"]["tristate_code"] for b in decoded_bursts if b["pt2262"]]
            best_ts = max(set(tristates), key=tristates.count)
            best_frame = next(
                (b["pt2262"] for b in decoded_bursts
                 if b.get("pt2262") and b["pt2262"]["tristate_code"] == best_ts),
                None,
            )
            if best_frame:
                best_frame = dict(best_frame)
                best_frame["tristate_repetitions"] = tristates.count(best_ts)

        all_protocols = [b["protocol_detected"] for b in decoded_bursts]
        dominant_protocol = (
            max(set(all_protocols), key=all_protocols.count) if all_protocols else "unknown"
        )
        adaptive_candidates, selected_decoding = self._ook433_adaptive_decodings(
            binary,
            symbol_bursts_indexed,
            sample_rate,
            t_unit_us,
            repetition_detected=bool(repeat_analysis.get("repetition_detected")),
            known_protocol_matched=(n_ev1527 > 0 or n_pt2262 > 0),
            invalid_continuous_count=len(invalid_continuous_runs),
        )
        symbol_level_burst_count = sum(
            1 for diag in preliminary_diagnostics if diag.get("symbol_level_detected")
        )
        no_symbol_level_count = n_bursts - symbol_level_burst_count
        fsk_majority = (
            n_bursts > 0
            and possible_modulation_counts.get("fsk_candidate", 0) >= max(1, int(np.ceil(n_bursts * 0.6)))
            and no_symbol_level_count >= max(1, int(np.ceil(n_bursts * 0.6)))
        )
        fsk_burst_diagnostics, fsk_candidate_decodings, selected_fsk_decoding = (
            self._fsk_remote_candidates(iq, bursts_indexed, sample_rate) if fsk_majority else ([], [], {})
        )
        cluster0_indices = [
            index for index, cluster_id in enumerate(cluster_ids)
            if cluster_id == 0 and index < len(all_decoded_bits)
        ]
        cluster0_bits = [all_decoded_bits[index] for index in cluster0_indices if all_decoded_bits[index]]
        cluster0_similarities = [
            self._ook433_bit_similarity(cluster0_bits[i], cluster0_bits[j])
            for i in range(len(cluster0_bits))
            for j in range(i + 1, len(cluster0_bits))
        ]
        cluster0_same_sequence = bool(cluster0_bits) and all(
            bits == cluster0_bits[0] for bits in cluster0_bits
        )
        burst_stability_confidence = (
            float(np.mean(cluster0_similarities)) if cluster0_similarities
            else (1.0 if len(cluster0_bits) == 1 else 0.0)
        )
        if not repeat_analysis.get("repetition_detected"):
            burst_stability_confidence *= 0.35
        if n_bursts and symbol_level_burst_count == 0:
            burst_stability_confidence = min(burst_stability_confidence, 0.25)
        protocol_decoding_confidence = min(1.0, (n_ev1527 + n_pt2262) / max(n_bursts, 1)) if n_bursts else 0.0
        selected_encoding_confidence = float(selected_decoding.get("confidence") or 0.0)
        if fsk_majority:
            selected_encoding_confidence = 0.0
            selected_decoding = {
                "encoding_type": None,
                "bitstring": "",
                "hex_candidate": "",
                "bit_length": 0,
                "confidence": 0.0,
                "recommended_pipeline": "fsk_remote_decoder",
                "rejection_reason": "not_symbol_level_ook_possible_fsk",
                "selected_reason": (
                    "Most bursts are FSK candidates and do not expose symbol-level OOK amplitude transitions. "
                    "OOK adaptive encoding is disabled; run the FSK remote decoder."
                ),
            }
        elif n_bursts and symbol_level_burst_count == 0:
            selected_encoding_confidence = min(selected_encoding_confidence, 0.10)
            selected_decoding["confidence"] = round(float(selected_encoding_confidence), 4)
            selected_decoding["rejection_reason"] = "no_symbol_level_ook_transitions_detected"
        selected_hex_warning = (
            "selected_hex_candidate_is_mostly_F_or_0"
            if (
                self._ook433_mostly_trivial_hex(str(selected_decoding.get("hex_candidate") or ""))
                or self._ook433_mostly_trivial_bits(str(selected_decoding.get("bitstring") or ""))
            )
            else None
        )
        selected_reason = (
            str(selected_decoding.get("selected_reason"))
            if fsk_majority and selected_decoding.get("selected_reason")
            else (
                f"Selected {selected_decoding.get('encoding_type')} as the most stable non-rejected hypothesis. "
                f"This is an encoding hypothesis, not a decoded remote-control protocol. "
                f"Protocol decoder confidence is {protocol_decoding_confidence:.3f}. "
                f"Symbol-level OOK transitions were detected in {symbol_level_burst_count}/{n_bursts} burst(s)."
            )
        )

        decoded_out = {
            "protocol": "ook_433_remote",
            "pipeline": "ook_433_remote",
            "center_frequency_hz": center,
            "in_433_band": in_433_band,
            "in_315_band": in_315_band,
            "in_868_band": in_868_band,
            "t_unit_us": round(t_unit_us, 1),
            "t_unit_confidence": round(t_confidence, 2),
            "symbol_rate_baud": symbol_rate_baud,
            "bursts_detected": n_bursts,
            "symbol_level_bursts": symbol_level_burst_count,
            "no_symbol_level_bursts": no_symbol_level_count,
            "possible_modulation_counts": possible_modulation_counts,
            "dominant_protocol": dominant_protocol,
            "recommended_pipeline": "fsk_remote_decoder" if fsk_majority else None,
            "fsk_majority_detected": fsk_majority,
            "selected_fsk_decoding": selected_fsk_decoding,
            "ev1527_frames": n_ev1527,
            "pt2262_frames": n_pt2262,
            "best_decoded_frame": best_frame,
            "repeat_analysis": repeat_analysis,
            "burst_comparison": {
                "similarity_matrix": similarity_matrix,
                "cluster_counts": cluster_counts,
                "cluster0_same_sequence": cluster0_same_sequence,
                "cluster0_repetition_similarity": round(burst_stability_confidence, 4),
                "rolling_code_candidates": rolling_code_candidates[:50],
                "interpretation": (
                    "repeated_code" if repeat_analysis.get("repetition_detected") else
                    "possible_rolling_code_or_bit_errors" if rolling_code_candidates else
                    "no_stable_repetition_detected"
                ),
            },
            "adaptive_decoding": {
                "selected_encoding_type": selected_decoding.get("encoding_type"),
                "selected_confidence": selected_decoding.get("confidence"),
                "burst_stability_confidence": round(float(burst_stability_confidence), 4),
                "protocol_decoding_confidence": round(float(protocol_decoding_confidence), 4),
                "selected_encoding_confidence": round(float(selected_encoding_confidence), 4),
                "selected_rejection_reason": selected_decoding.get("rejection_reason"),
                "selected_reason": selected_reason,
                "selected_warning": selected_hex_warning,
                "recommended_pipeline": selected_decoding.get("recommended_pipeline"),
                "fsk_majority_detected": fsk_majority,
                "selected_fsk_decoding": selected_fsk_decoding,
                "selected_hex_candidate": selected_decoding.get("hex_candidate"),
                "selected_bit_length": selected_decoding.get("bit_length"),
            },
            "burst_diagnostics": preliminary_diagnostics,
            "bursts": decoded_bursts,
        }
        decoded_path = output_dir / "decoded_frames.json"
        decoded_path.write_text(json.dumps(decoded_out, indent=2), encoding="utf-8")
        raw_pulses_path = output_dir / "raw_pulses.json"
        raw_pulses_path.write_text(
            json.dumps(
                {
                    "sample_rate_hz": sample_rate,
                    "threshold": threshold,
                    "threshold_selection_score": best_segmentation.get("score") if best_segmentation else None,
                    "threshold_selection_metrics": {
                        "good_duration_count": best_segmentation.get("good_duration_count") if best_segmentation else None,
                        "short_fragment_count": best_segmentation.get("short_fragment_count") if best_segmentation else None,
                        "median_duration_ms": best_segmentation.get("median_duration_ms") if best_segmentation else None,
                    },
                    "pulse_count": len(indexed_pulses),
                    "duration_classes": {
                        "short_us": round(float(duration_classes["short_us"]), 3),
                        "long_us": round(float(duration_classes["long_us"]), 3),
                        "sync_threshold_us": round(float(duration_classes["sync_threshold_us"]), 3),
                    },
                    "mark_histogram": self._ook433_duration_histogram(all_mark_us),
                    "space_histogram": self._ook433_duration_histogram(all_space_us),
                    "global_carrier_pulses": indexed_pulses,
                    "bursts": raw_pulse_bursts,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        burst_features_path = output_dir / "burst_features.json"
        burst_features_path.write_text(
            json.dumps(
                {
                    "burst_count": n_bursts,
                    "symbol_level_bursts": symbol_level_burst_count,
                    "no_symbol_level_bursts": no_symbol_level_count,
                    "possible_modulation_counts": possible_modulation_counts,
                    "segmentation_limits": {
                        "min_burst_duration_ms": min_burst_duration_ms,
                        "max_burst_duration_ms": max_burst_duration_ms,
                        "min_gap_duration_ms": min_gap_duration_ms,
                    },
                    "invalid_continuous_runs": invalid_continuous_runs,
                    "duration_classes": {
                        "short_us": round(float(duration_classes["short_us"]), 3),
                        "long_us": round(float(duration_classes["long_us"]), 3),
                        "sync_threshold_us": round(float(duration_classes["sync_threshold_us"]), 3),
                    },
                    "mark_histogram": self._ook433_duration_histogram(all_mark_us),
                    "space_histogram": self._ook433_duration_histogram(all_space_us),
                    "features": preliminary_diagnostics,
                    "cluster_counts": cluster_counts,
                    "repeat_analysis": repeat_analysis,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        candidate_decodings_path = output_dir / "candidate_decodings.json"
        candidate_decodings_path.write_text(
            json.dumps(
                {
                    "candidate_count": len(adaptive_candidates),
                    "selected_encoding_type": selected_decoding.get("encoding_type"),
                    "candidates": adaptive_candidates,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        selected_decoding_path = output_dir / "selected_decoding.json"
        selected_decoding_path.write_text(json.dumps(selected_decoding, indent=2), encoding="utf-8")
        fsk_burst_diagnostics_path = output_dir / "fsk_burst_diagnostics.json"
        fsk_burst_diagnostics_path.write_text(json.dumps({"bursts": fsk_burst_diagnostics}, indent=2), encoding="utf-8")
        fsk_candidate_decodings_path = output_dir / "fsk_candidate_decodings.json"
        fsk_candidate_decodings_path.write_text(json.dumps({"candidate_count": len(fsk_candidate_decodings), "candidates": fsk_candidate_decodings}, indent=2), encoding="utf-8")
        selected_fsk_decoding_path = output_dir / "selected_fsk_decoding.json"
        selected_fsk_decoding_path.write_text(json.dumps(selected_fsk_decoding, indent=2), encoding="utf-8")
        diagnostics_out = {
            "protocol": "ook_433_remote",
            "pipeline": "ook_433_remote",
            "center_frequency_hz": center,
            "sample_rate_hz": sample_rate,
            "threshold": threshold,
            "t_unit_us": round(t_unit_us, 1),
            "t_unit_confidence": round(t_confidence, 2),
            "symbol_rate_baud": symbol_rate_baud,
            "burst_count": n_bursts,
            "symbol_level_bursts": symbol_level_burst_count,
            "no_symbol_level_bursts": no_symbol_level_count,
            "possible_modulation_counts": possible_modulation_counts,
            "segmentation_limits": {
                "min_burst_duration_ms": min_burst_duration_ms,
                "max_burst_duration_ms": max_burst_duration_ms,
                "min_gap_duration_ms": min_gap_duration_ms,
            },
            "invalid_continuous_runs": invalid_continuous_runs,
            "duration_classes": {
                "short_us": round(float(duration_classes["short_us"]), 3),
                "long_us": round(float(duration_classes["long_us"]), 3),
                "sync_threshold_us": round(float(duration_classes["sync_threshold_us"]), 3),
            },
            "mark_histogram": self._ook433_duration_histogram(all_mark_us),
            "space_histogram": self._ook433_duration_histogram(all_space_us),
            "repeat_analysis": repeat_analysis,
            "burst_comparison": decoded_out["burst_comparison"],
            "adaptive_decoding": decoded_out["adaptive_decoding"],
            "bursts": preliminary_diagnostics,
        }
        diagnostics_path = output_dir / "ook_burst_diagnostics.json"
        diagnostics_path.write_text(json.dumps(diagnostics_out, indent=2), encoding="utf-8")

        raw_bits = np.array(
            all_decoded_bits[0] if all_decoded_bits else [], dtype=np.uint8
        )
        bitstream_path = output_dir / "recovered_bitstream.bin"
        bitstream_path.write_bytes(
            np.packbits(raw_bits).tobytes() if raw_bits.size else b""
        )

        pulse_timing = self._pulse_timing(binary, sample_rate)

        logs_path = output_dir / "logs.txt"
        logs_path.write_text(
            "\n".join([
                "OOK 433/315/868 MHz remote control decoder",
                f"center_frequency_hz={center}",
                f"in_433_band={in_433_band}  in_315_band={in_315_band}  in_868_band={in_868_band}",
                f"t_unit_us={t_unit_us:.1f}  t_unit_confidence={t_confidence:.2f}",
                f"symbol_rate_baud={symbol_rate_baud}",
                f"pulses_extracted={len(pulses)}",
                f"bursts_detected={n_bursts}",
                f"symbol_level_bursts={symbol_level_burst_count}",
                f"no_symbol_level_bursts={no_symbol_level_count}",
                f"possible_modulation_counts={possible_modulation_counts}",
                f"invalid_continuous_runs={len(invalid_continuous_runs)}",
                f"clusters={cluster_counts}",
                f"repeat_interpretation={decoded_out['burst_comparison']['interpretation']}",
                f"selected_adaptive_encoding={selected_decoding.get('encoding_type')}",
                f"selected_adaptive_confidence={selected_decoding.get('confidence')}",
                f"burst_stability_confidence={burst_stability_confidence:.4f}",
                f"protocol_decoding_confidence={protocol_decoding_confidence:.4f}",
                f"selected_adaptive_rejection_reason={selected_decoding.get('rejection_reason')}",
                f"ev1527_frames={n_ev1527}  pt2262_frames={n_pt2262}",
                f"dominant_protocol={dominant_protocol}",
                f"rf_activity_detected={bool(activity.get('signal_detected'))}",
            ]) + "\n",
            encoding="utf-8",
        )

        decoded_ok = n_ev1527 > 0 or n_pt2262 > 0
        ook_warnings = []
        if not in_band and center > 0:
            ook_warnings.append(f"Center {center / 1e6:.3f} MHz is outside 433/315/868 MHz ISM bands - results may be unreliable.")
        if selected_hex_warning:
            ook_warnings.append(selected_hex_warning)
        if n_bursts and symbol_level_burst_count == 0:
            ook_warnings.append("no_symbol_level_ook_transitions_detected")
        if possible_modulation_counts.get("fsk_candidate", 0) > 0:
            ook_warnings.append("instantaneous_frequency_two_tone_candidate_consider_fsk_decoder")
        if fsk_majority:
            ook_warnings.append("not_symbol_level_ook_possible_fsk")
        final_status = (
            "decoded_with_protocol" if decoded_ok
            else "fsk_candidate_detected" if fsk_majority
            else "ook_burst_detected_no_symbol_transitions" if n_bursts > 0 and symbol_level_burst_count == 0
            else "bitstream_recovered" if n_bursts > 0
            else "segmentation_failed" if invalid_continuous_runs
            else "rf_activity_only" if activity.get("signal_detected")
            else "no_signal_detected"
        )

        return {
            "status": "complete" if decoded_ok else "rf_activity_only",
            "final_status": final_status,
            "valid_demodulation": decoded_ok,
            "protocol": "ook_433_remote",
            "pipeline": "ook_433_remote",
            "center_frequency_hz": center,
            "in_433_ism_band": in_band,
            "in_433_band": in_433_band,
            "in_315_band": in_315_band,
            "in_868_band": in_868_band,
            "rf_activity_detected": bool(activity.get("signal_detected")),
            "t_unit_us": round(t_unit_us, 1),
            "t_unit_confidence": round(t_confidence, 2),
            "symbol_rate_baud": symbol_rate_baud,
            "bursts_detected": n_bursts,
            "symbol_level_bursts": symbol_level_burst_count,
            "no_symbol_level_bursts": no_symbol_level_count,
            "possible_modulation_counts": possible_modulation_counts,
            "dominant_protocol": dominant_protocol,
            "recommended_pipeline": "fsk_remote_decoder" if fsk_majority else None,
            "fsk_majority_detected": fsk_majority,
            "selected_fsk_decoding": selected_fsk_decoding,
            "ev1527_frames": n_ev1527,
            "pt2262_frames": n_pt2262,
            "best_frame": best_frame,
            "confidence_score": min(1.0, (n_ev1527 + n_pt2262) / 5.0) if decoded_ok else None,
            "stage_diagnostics": {
                "iq_loaded": bool(iq.size > 0),
                "rf_activity_detected": bool(activity.get("signal_detected")),
                "in_433_ism_band": in_band,
                "pulses_extracted": len(pulses),
                "symbol_level_bursts": symbol_level_burst_count,
                "no_symbol_level_bursts": no_symbol_level_count,
                "possible_modulation_counts": possible_modulation_counts,
                "t_unit_us": round(t_unit_us, 1),
                "t_unit_confidence": round(t_confidence, 2),
                "segmentation_limits": {
                    "min_burst_duration_ms": min_burst_duration_ms,
                    "max_burst_duration_ms": max_burst_duration_ms,
                    "min_gap_duration_ms": min_gap_duration_ms,
                },
                "invalid_continuous_runs": invalid_continuous_runs,
                "bursts_found": n_bursts,
                "burst_diagnostics_written": True,
                "cluster_counts": cluster_counts,
                "repeat_interpretation": decoded_out["burst_comparison"]["interpretation"],
                "adaptive_decoder_attempted": True,
                "selected_encoding_type": selected_decoding.get("encoding_type"),
                "selected_encoding_confidence": selected_decoding.get("confidence"),
                "burst_stability_confidence": round(float(burst_stability_confidence), 4),
                "protocol_decoding_confidence": round(float(protocol_decoding_confidence), 4),
                "selected_encoding_rejection_reason": selected_decoding.get("rejection_reason"),
                "selected_encoding_warning": selected_hex_warning,
                "recommended_pipeline": "fsk_remote_decoder" if fsk_majority else None,
                "fsk_majority_detected": fsk_majority,
                "ev1527_decoded": n_ev1527,
                "pt2262_decoded": n_pt2262,
            },
            "pulse_timing": pulse_timing,
            "analysis_interpretation": (
                "decoded_remote_frame" if decoded_ok else
                "fsk_candidate_detected; ook_not_symbol_level; run_fsk_remote_decoder"
                if fsk_majority else
                "ook_burst_detected; no_symbol_level_ook_transitions_detected; check_fsk_or_ask"
                if n_bursts > 0 and symbol_level_burst_count == 0 else
                "stable_repeated_ook_burst_detected; protocol_unknown; pulse_level_decoding_required"
                if repeat_analysis.get("repetition_detected") else
                "ook_activity_detected; protocol_unknown; no_stable_repetition_detected"
            ),
            "burst_stability_confidence": round(float(burst_stability_confidence), 4),
            "protocol_decoding_confidence": round(float(protocol_decoding_confidence), 4),
            "selected_encoding_confidence": round(float(selected_encoding_confidence), 4),
            "repeat_analysis": repeat_analysis,
            "burst_comparison": decoded_out["burst_comparison"],
            "adaptive_decoding": decoded_out["adaptive_decoding"],
            "decoded_frames": decoded_out,
            "outputs": {
                "decoded_frames": str(decoded_path),
                "burst_diagnostics": str(diagnostics_path),
                "raw_pulses": str(raw_pulses_path),
                "burst_features": str(burst_features_path),
                "candidate_decodings": str(candidate_decodings_path),
                "selected_decoding": str(selected_decoding_path),
                "fsk_burst_diagnostics": str(fsk_burst_diagnostics_path),
                "fsk_candidate_decodings": str(fsk_candidate_decodings_path),
                "selected_fsk_decoding": str(selected_fsk_decoding_path),
                "bitstream": str(bitstream_path),
                "logs": str(logs_path),
                "report": str(output_dir / "demodulation_report.json"),
            },
            "notes": (
                [
                    f"Decoded {n_ev1527 + n_pt2262} OOK frame(s) from {n_bursts} burst(s). "
                    f"Protocol: {dominant_protocol}.  "
                    f"Repetition count: {repeat_analysis.get('repetition_count', 0)}."
                ]
                if decoded_ok
                else [f"OOK burst activity detected ({n_bursts} burst(s)) but no known protocol matched."]
                if n_bursts > 0
                else ["OOK envelope looked continuous or poorly segmented; no valid remote-control burst was accepted."]
                if invalid_continuous_runs
                else [
                    "No OOK signal detected. "
                    "Verify center frequency (433.92 / 315 / 868 MHz) and capture bandwidth."
                ]
            ),
            "warnings": ook_warnings,
        }

    def _packet_scaffold(self, protocol: str, iq: np.ndarray, data: dict, output_dir: Path) -> dict:
        packets = {
            "protocol": protocol,
            "frames_decoded": 0,
            "frames_crc_valid": 0,
            "payload_extractable": False,
            "frames": [],
        }
        packet_path = output_dir / "decoded_packets.json"
        packet_path.write_text(json.dumps(packets, indent=2), encoding="utf-8")
        return {
            "status": "rf_activity_only",
            "protocol": protocol,
            "outputs": {"decoded_packets": str(packet_path), "report": str(output_dir / "demodulation_report.json")},
            "decoded_packets": packets,
            "valid_demodulation": False,
            "confidence_score": None,
            "notes": [
                f"{protocol} pipeline selected, but this build has not reconstructed CRC-valid protocol frames.",
                "RF activity is not reported as successful protocol demodulation.",
            ],
        }

    def _wifi_80211_scaffold(self, iq: np.ndarray, data: dict, output_dir: Path) -> dict:
        sample_rate = float(data.get("sample_rate_hz") or 1.0)
        center = float(data.get("center_frequency_hz") or 0.0)
        bandwidth = float(data.get("bandwidth_hz") or 0.0)
        activity = self._summarize_iq_activity(iq, sample_rate)
        channel = self._wifi_channel_from_frequency(center)

        magnitude = np.abs(iq).astype(np.float32) if iq.size else np.array([], dtype=np.float32)
        candidates: list[dict] = []
        if magnitude.size and activity.get("signal_detected"):
            smooth_window = max(1, int(sample_rate * 20e-6))
            if smooth_window > 1:
                kernel = np.ones(smooth_window, dtype=np.float32) / float(smooth_window)
                envelope = np.convolve(magnitude, kernel, mode="same")
            else:
                envelope = magnitude
            threshold = float(np.median(envelope) + 3.0 * np.std(envelope))
            active = envelope > threshold
            edges = np.flatnonzero(np.diff(active.astype(np.int8)) != 0)
            starts = []
            stops = []
            if active.size:
                if active[0]:
                    starts.append(0)
                starts.extend((edges[active[edges + 1]] + 1).tolist())
                stops.extend((edges[active[edges]] + 1).tolist())
                if active[-1]:
                    stops.append(active.size)
            min_samples = max(1, int(sample_rate * 16e-6))
            max_candidates = 200
            for index, (start, stop) in enumerate(zip(starts, stops)):
                if stop <= start or (stop - start) < min_samples:
                    continue
                segment = iq[start:stop]
                if segment.size == 0:
                    continue
                power = np.abs(segment) ** 2
                peak_power = float(np.max(power)) if power.size else 0.0
                mean_power = float(np.mean(power)) if power.size else 0.0
                candidates.append(
                    {
                        "candidate_index": len(candidates),
                        "start_time_seconds": float(start / sample_rate),
                        "duration_seconds": float((stop - start) / sample_rate),
                        "sample_count": int(stop - start),
                        "peak_power_db": float(10.0 * np.log10(max(peak_power, 1e-20))),
                        "mean_power_db": float(10.0 * np.log10(max(mean_power, 1e-20))),
                        "ofdm_activity_candidate": True,
                        "crc_valid": False,
                        "note": "Energy burst candidate only; no IEEE 802.11 PHY synchronization or FCS validation was performed.",
                    }
                )
                if len(candidates) >= max_candidates:
                    break

        frames = []
        packets = {
            "protocol": "wifi_80211",
            "channel": channel.get("channel"),
            "band": channel.get("band"),
            "center_frequency_hz": center,
            "bandwidth_hz": bandwidth,
            "frames_decoded": 0,
            "frames_crc_valid": 0,
            "packet_candidates": len(candidates),
            "payload_extractable": False,
            "frames": frames,
            "candidate_packets": candidates,
        }
        packet_path = output_dir / "decoded_packets.json"
        packet_path.write_text(json.dumps(packets, indent=2), encoding="utf-8")

        detected = bool(activity.get("signal_detected"))
        final_status = "wifi_activity_detected_no_valid_frames" if detected else "no_signal_detected"
        return {
            "status": "rf_activity_only" if detected else "sync_failed",
            "final_status": final_status,
            "protocol": "wifi_80211",
            "pipeline": "wifi_80211",
            "valid_demodulation": False,
            "rf_activity_detected": detected,
            "wifi_band": channel.get("band"),
            "wifi_channel": channel.get("channel"),
            "wifi_channel_frequency_hz": channel.get("center_frequency_hz"),
            "frames_decoded": 0,
            "frames_crc_valid": 0,
            "packet_candidates": len(candidates),
            "confidence_score": None,
            "outputs": {"decoded_packets": str(packet_path), "report": str(output_dir / "demodulation_report.json")},
            "decoded_packets": packets,
            "stage_diagnostics": {
                "iq_loaded": bool(iq.size > 0),
                "rf_activity_detected": detected,
                "candidate_bursts": len(candidates),
                "channel_inferred": channel,
                "demodulation_level_reached": "energy_burst_detection",
                "limitations": [
                    "No 802.11 preamble synchronization",
                    "No OFDM equalization",
                    "No MAC header parse",
                    "No FCS/CRC validation",
                ],
            },
            "notes": [
                f"Wi-Fi activity candidate(s): {len(candidates)} on {channel.get('band') or 'unknown band'} channel {channel.get('channel') or 'n/a'}.",
                "This build detects Wi-Fi-band RF burst candidates, but does not reconstruct CRC-valid IEEE 802.11 frames.",
            ],
        }

    def _wifi_channel_from_frequency(self, frequency_hz: float) -> dict:
        mhz = frequency_hz / 1_000_000.0
        if 2401.0 <= mhz <= 2495.0:
            channel = int(round((mhz - 2407.0) / 5.0))
            if channel == 14 or 1 <= channel <= 13:
                center_mhz = 2484.0 if channel == 14 else 2407.0 + channel * 5.0
                return {"band": "2.4GHz", "channel": channel, "center_frequency_hz": center_mhz * 1_000_000}
        if 5000.0 <= mhz <= 5900.0:
            channel = int(round((mhz - 5000.0) / 5.0))
            return {"band": "5GHz", "channel": channel, "center_frequency_hz": (5000.0 + channel * 5.0) * 1_000_000}
        return {"band": None, "channel": None, "center_frequency_hz": None}

    def _simple_digital_scaffold(self, iq: np.ndarray, data: dict, output_dir: Path) -> dict:
        magnitude = np.abs(iq)
        threshold = float(np.median(magnitude) + np.std(magnitude))
        bits = (magnitude[:: max(1, int(len(magnitude) / 4096))] > threshold).astype(np.uint8)
        bitstream_path = output_dir / "bitstream.bin"
        bitstream_path.write_bytes(np.packbits(bits).tobytes())
        payload = {
            "bit_count": int(bits.size),
            "baud_rate_estimated": None,
            "payload_hex": "",
            "confidence_score": None,
            "note": "Raw thresholded activity only; not a validated symbol clock or decoded protocol payload.",
        }
        payload_path = output_dir / "decoded_payload.json"
        payload_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {
            "status": "partial_decode" if bits.size else "sync_failed",
            "outputs": {
                "bitstream": str(bitstream_path),
                "decoded_payload": str(payload_path),
                "report": str(output_dir / "demodulation_report.json"),
            },
            "decoded_payload": payload,
            "valid_demodulation": False,
            "confidence_score": None,
            "notes": ["A provisional bitstream was extracted, but no protocol-level CRC or payload validation was performed."],
        }

    def _finalize_dataset_result(self, report: dict, output_dir: Path) -> dict:
        report_path = output_dir / "demodulation_report.json"
        report["metadata_file"] = str(report_path)
        report["metadata_url"] = f"/api/demodulation/results/{report['id']}"
        report["final_status"] = report.get("final_status") or report.get("status") or "not_attempted"
        report.setdefault("outputs", {})["report"] = str(report_path)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        self._results[report["id"]] = report
        return report
