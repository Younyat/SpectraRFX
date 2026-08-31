"""Real SoapySDR probe/capture worker for BLE Lab.

This process never synthesizes IQ. Test fakes live in backend tests and do not
invoke this entry point.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import queue
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

try:
    import psutil
except Exception:
    psutil = None


FORMAT_PROFILE = {
    "cf32_le": {"cpu_format": "cf32_le", "otw_format": "CF32", "file_format": "cf32_le",
                "bytes_per_cpu_sample": 8, "bytes_per_wire_sample": 8, "bytes_per_file_sample": 8,
                "conversion_enabled": False},
    "ci16_le": {"cpu_format": "ci16_le", "otw_format": "CS16", "file_format": "ci16_le",
                "bytes_per_cpu_sample": 4, "bytes_per_wire_sample": 4, "bytes_per_file_sample": 4,
                "conversion_enabled": False},
    "ci8": {"cpu_format": "ci8", "otw_format": "CS8", "file_format": "ci8",
            "bytes_per_cpu_sample": 2, "bytes_per_wire_sample": 2, "bytes_per_file_sample": 2,
            "conversion_enabled": False},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True); handle.write("\n"); handle.flush(); os.fsync(handle.fileno())
    # On Windows a browser/API reader can briefly hold live.json without
    # delete sharing. Retry the atomic swap instead of aborting the RF stream.
    for attempt in range(40):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(0.01)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def backend_commit() -> str | None:
    try:
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repository_root(),
                                capture_output=True, text=True, timeout=5, check=True)
        return result.stdout.strip() or None
    except Exception:
        return None


def storage_free_bytes(path: Path) -> int | None:
    try:
        return int(shutil.disk_usage(path).free)
    except Exception:
        return None


def observed_usb_mode(output: Path) -> str | None:
    log_path = output / "capture.stderr.log"
    if not log_path.exists():
        return None
    text = log_path.read_text(errors="ignore")
    if "USB 3" in text:
        return "USB 3"
    if "USB 2" in text:
        return "USB 2"
    return None


class CpuSampler:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.system_values: list[float] = []
        self.process_values: list[float] = []
        self.memory_values: list[int] = []
        self.started = time.monotonic()
        self.process_time_started = time.process_time()

    def start(self) -> None:
        if psutil is None:
            return
        process = psutil.Process(os.getpid())
        psutil.cpu_percent(interval=None)
        process.cpu_percent(interval=None)

        def run() -> None:
            while not self._stop.wait(0.25):
                try:
                    self.system_values.append(float(psutil.cpu_percent(interval=None)))
                    self.process_values.append(float(process.cpu_percent(interval=None)))
                    self.memory_values.append(int(process.memory_info().rss))
                except Exception:
                    pass

        self._thread = threading.Thread(target=run, name="cpu-metrics-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> dict:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        elapsed = max(time.monotonic() - self.started, 1e-9)
        fallback_process_cpu = 100.0 * (time.process_time() - self.process_time_started) / elapsed
        return {
            "cpu_usage_mean": float(sum(self.system_values) / len(self.system_values)) if self.system_values else None,
            "cpu_usage_max": float(max(self.system_values)) if self.system_values else None,
            "process_cpu_usage_mean": float(sum(self.process_values) / len(self.process_values)) if self.process_values else fallback_process_cpu,
            "memory_usage_max": int(max(self.memory_values)) if self.memory_values else None,
        }


class DedicatedWriter:
    def __init__(self, path: Path, capacity_bytes: int, block_size_bytes: int, fsync_on_close: bool = True) -> None:
        self.path = path
        self.capacity_bytes = int(capacity_bytes)
        self.block_size_bytes = max(1, int(block_size_bytes))
        self.max_blocks = max(1, self.capacity_bytes // self.block_size_bytes)
        self.queue: queue.Queue[bytes | None] = queue.Queue(maxsize=self.max_blocks)
        self.high_watermark_bytes = 0
        self.queue_overrun_count = 0
        self.write_call_count = 0
        self.latencies_ms: list[float] = []
        self.bytes_written = 0
        self.error: str | None = None
        self._fsync_on_close = fsync_on_close
        self._thread = threading.Thread(target=self._run, name="ble-iq-dedicated-writer", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def submit(self, payload: bytes) -> bool:
        try:
            self.queue.put_nowait(payload)
            self.high_watermark_bytes = max(self.high_watermark_bytes, self.queue.qsize() * self.block_size_bytes)
            return True
        except queue.Full:
            self.queue_overrun_count += 1
            self.high_watermark_bytes = max(self.high_watermark_bytes, self.capacity_bytes)
            return False

    def close(self) -> None:
        self.queue.put(None)
        self._thread.join()
        if self.error:
            raise RuntimeError(self.error)

    def _run(self) -> None:
        try:
            with self.path.open("wb") as handle:
                while True:
                    item = self.queue.get()
                    try:
                        if item is None:
                            break
                        t0 = time.perf_counter()
                        handle.write(item)
                        self.latencies_ms.append((time.perf_counter() - t0) * 1000.0)
                        self.write_call_count += 1
                        self.bytes_written += len(item)
                    finally:
                        self.queue.task_done()
                handle.flush()
                if self._fsync_on_close:
                    os.fsync(handle.fileno())
        except Exception as error:
            self.error = f"WRITER_ERROR:{type(error).__name__}:{error}"

    def metrics(self, elapsed_seconds: float) -> dict:
        return {
            "writer_thread_mode": "dedicated_thread",
            "writer_queue_capacity_bytes": self.capacity_bytes,
            "writer_queue_high_watermark_bytes": self.high_watermark_bytes,
            "writer_queue_overrun_count": self.queue_overrun_count,
            "maximum_buffer_occupancy": self.high_watermark_bytes,
            "write_block_size_bytes": self.block_size_bytes,
            "write_call_count": self.write_call_count,
            "mean_write_latency_ms": float(sum(self.latencies_ms) / len(self.latencies_ms)) if self.latencies_ms else None,
            "maximum_write_latency_ms": float(max(self.latencies_ms)) if self.latencies_ms else None,
            "measured_write_throughput_bytes_s": float(self.bytes_written) / max(elapsed_seconds, 1e-9),
            "memory_copy_count_per_block": 1,
            "writer_error": self.error,
        }


class LiveTelemetryPublisher:
    """Writes live.json (the UI preview snapshot) on its own background
    thread, off the real-time RX loop.

    Root cause found by tracing a real, intermittent SOAPY_SDR_OVERFLOW: the
    RX loop used to call atomic_json() -- which does an os.fsync() -- directly,
    roughly every 250ms for the whole capture. fsync latency is unpredictable
    (disk/OS scheduling), and the RX loop must call device.readStream() again
    within one ~50ms block period or the USRP's internal ring buffer overruns.
    Any slow fsync call directly caused a lost-samples overflow.

    Only ever keeps the LATEST snapshot (maxsize=1, drop-oldest-on-full) --
    submit() never blocks, so a slow or stalled disk write can delay how
    fresh the UI preview is, but can never delay the RX loop itself.
    """
    def __init__(self, path: Path) -> None:
        self.path = path
        self._queue: queue.Queue[dict | None] = queue.Queue(maxsize=1)
        self._thread = threading.Thread(target=self._run, name="ble-live-telemetry-writer", daemon=True)
        self.publish_failures = 0

    def start(self) -> None:
        self._thread.start()

    def submit(self, payload: dict) -> None:
        try:
            self._queue.put_nowait(payload)
            return
        except queue.Full:
            pass
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            pass

    def close(self) -> None:
        self._queue.put(None)
        self._thread.join()

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            try:
                atomic_json(self.path, item)
            except Exception:
                self.publish_failures += 1


def write_jsonl(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows: handle.write(json.dumps(row, sort_keys=True) + "\n")


def detect_bursts(data_path: Path, sample_format: str, sample_rate: float, output: Path) -> list[dict]:
    dtype = {"cf32_le": "<c8", "ci16_le": "<i2", "ci8": "i1"}[sample_format]
    raw = np.memmap(data_path, dtype=dtype, mode="r")
    if sample_format == "cf32_le": values = raw
    else:
        scale = 32768.0 if sample_format == "ci16_le" else 128.0
        values = (raw[0::2].astype(np.float32) + 1j * raw[1::2].astype(np.float32)) / scale
    block = max(64, int(sample_rate / 100_000))
    count = len(values) // block
    if count < 4: return []
    power = np.mean(np.abs(np.asarray(values[:count * block]).reshape(count, block)) ** 2, axis=1)
    noise = float(np.median(power)); mad = float(np.median(np.abs(power - noise)))
    threshold = max(noise * 4.0, noise + 8.0 * mad, 1e-12)
    active = np.flatnonzero(power > threshold)
    groups = np.split(active, np.where(np.diff(active) > 2)[0] + 1) if active.size else []
    segment_dir = output / "iq_bursts"; segment_dir.mkdir(exist_ok=True)
    bursts = []
    bytes_per_sample = {"cf32_le": 8, "ci16_le": 4, "ci8": 2}[sample_format]
    with data_path.open("rb") as source:
        for index, group in enumerate(groups, 1):
            if not len(group): continue
            start = max(0, (int(group[0]) - 2) * block); end = min(len(values), (int(group[-1]) + 3) * block)
            source.seek(start * bytes_per_sample); payload = source.read((end - start) * bytes_per_sample)
            segment = segment_dir / f"burst-{index:06d}.cf32" if sample_format == "cf32_le" else segment_dir / f"burst-{index:06d}.iq"
            segment.write_bytes(payload)
            bursts.append({"burst_id": f"burst-{index:06d}", "sample_start": start, "sample_end": end,
                           "sample_count": end-start, "power_dbfs": float(10*np.log10(max(float(np.max(power[group])), 1e-12))),
                           "noise_power_dbfs": float(10*np.log10(max(noise, 1e-12))), "threshold_dbfs": float(10*np.log10(threshold)),
                           "iq_segment_path": str(segment.relative_to(output)), "iq_segment_sha256": sha256(segment),
                           "classification": "energy_burst_candidate", "ble_packet_confirmed": False})
    return bursts


def ranges(values):
    result = []
    for value in values:
        minimum = float(value.minimum()); maximum = float(value.maximum())
        result.append({"minimum": minimum, "maximum": maximum})
    return result


def uhd_version() -> str | None:
    try:
        result = subprocess.run(["uhd_config_info", "--version"], capture_output=True, text=True, timeout=10, check=True)
        return result.stdout.strip().splitlines()[-1] or None
    except Exception:
        return None


def probe() -> int:
    import SoapySDR
    devices = []
    for args in SoapySDR.Device.enumerate():
        private = {str(k): str(v) for k, v in dict(args).items()}
        device = None
        try:
            device = SoapySDR.Device(args)
            info = device.getHardwareInfo()
            driver = str(private.get("driver") or device.getDriverKey())
            devices.append({
                "device_args": private,
                "driver": driver,
                "label": str(private.get("label") or info.get("hardware") or device.getHardwareKey() or driver),
                "serial": str(private.get("serial") or info.get("serial") or ""),
                "rx_channels": int(device.getNumChannels(SoapySDR.SOAPY_SDR_RX)),
                "frequency_ranges_hz": ranges(device.getFrequencyRange(SoapySDR.SOAPY_SDR_RX, 0)),
                "sample_rate_ranges_sps": ranges(device.getSampleRateRange(SoapySDR.SOAPY_SDR_RX, 0)),
                "bandwidth_ranges_hz": ranges(device.getBandwidthRange(SoapySDR.SOAPY_SDR_RX, 0)),
                "gain_elements": list(device.listGains(SoapySDR.SOAPY_SDR_RX, 0)),
                "antenna_options": list(device.listAntennas(SoapySDR.SOAPY_SDR_RX, 0)),
                "stream_formats": list(device.getStreamFormats(SoapySDR.SOAPY_SDR_RX, 0)),
                "clock_sources": list(device.listClockSources()),
                "time_sources": list(device.listTimeSources()),
            })
        except Exception:
            continue
        finally:
            if device is not None:
                try: device = None
                except Exception: pass
    runtime = {"sdr_runtime":"radioconda-or-configured-runtime",
               "soapysdr_library_version":getattr(SoapySDR,"getLibVersion",lambda:"unknown")(),
               "soapysdr_api_version":getattr(SoapySDR,"getAPIVersion",lambda:"unknown")(),
               "soapysdr_abi_version":getattr(SoapySDR,"getABIVersion",lambda:"unknown")(),
               "device_probe_succeeded":bool(devices)}
    print(json.dumps({"devices": devices,"runtime":runtime}, separators=(",", ":")))
    return 0


def output_buffer(sample_format: str, count: int):
    if sample_format == "ci8": return np.empty(count * 2, dtype=np.int8), "CS8"
    if sample_format == "ci16_le": return np.empty(count * 2, dtype="<i2"), "CS16"
    if sample_format == "cf32_le": return np.empty(count, dtype="<c8"), "CF32"
    raise ValueError("UNSUPPORTED_SAMPLE_FORMAT")


def complex_view(buffer, sample_format: str, samples: int):
    if sample_format == "cf32_le": return buffer[:samples].astype(np.complex64, copy=False)
    raw = buffer[:samples * 2].reshape(-1, 2).astype(np.float32)
    scale = 128.0 if sample_format == "ci8" else 32768.0
    return (raw[:, 0] + 1j * raw[:, 1]) / scale


def live_metrics(values, request, received, written, overflows, discontinuities):
    if len(values) == 0: return {"available": False}
    subset = values[-min(len(values), 8192):]
    power = np.abs(subset) ** 2
    if request.get("frontend_preview_enabled") is False:
        return {"available": True, "timestamp_utc": utc_now(), "samples_received": received, "bytes_written": written,
                "stream_overflows": overflows, "input_discontinuities": discontinuities,
                "average_power_dbfs": float(10 * np.log10(max(float(np.mean(power)), 1e-12))),
                "peak_power_dbfs": float(20 * np.log10(max(float(np.max(np.abs(subset))), 1e-12))),
                "clipping_percentage": float(100 * np.mean(np.abs(subset) >= 0.999)),
                "preview_disabled": True}
    nfft = min(2048, len(subset)); windowed = subset[-nfft:] * np.hanning(nfft)
    spectrum = 20 * np.log10(np.maximum(np.abs(np.fft.fftshift(np.fft.fft(windowed))) / max(1, nfft), 1e-12))
    frequencies = np.linspace(request["center_frequency_hz"] - request["sample_rate_sps"] / 2,
                              request["center_frequency_hz"] + request["sample_rate_sps"] / 2, nfft, endpoint=False)
    stride = max(1, nfft // 256)
    return {"available": True, "timestamp_utc": utc_now(), "samples_received": received, "bytes_written": written,
            "stream_overflows": overflows, "input_discontinuities": discontinuities,
            "average_power_dbfs": float(10 * np.log10(max(float(np.mean(power)), 1e-12))),
            "peak_power_dbfs": float(20 * np.log10(max(float(np.max(np.abs(subset))), 1e-12))),
            "clipping_percentage": float(100 * np.mean(np.abs(subset) >= 0.999)),
            "frequencies_hz": frequencies[::stride].tolist(), "spectrum_dbfs": spectrum[::stride].tolist(),
            "i_preview": subset.real[::max(1, len(subset)//512)].tolist(),
            "q_preview": subset.imag[::max(1, len(subset)//512)].tolist()}


def capture(request_path: Path, output: Path) -> int:
    import SoapySDR

    request = json.loads(request_path.read_text(encoding="utf-8-sig"))
    output.mkdir(parents=True, exist_ok=True)
    capture_id, fmt = request["capture_id"], request["sample_format"]
    profile = FORMAT_PROFILE[fmt]
    partial = output / f"{capture_id}.partial"
    final = output / f"{capture_id}.sigmf-data"
    meta_path = output / f"{capture_id}.sigmf-meta"
    persist_iq = bool(request.get("disk_persistence_enabled", True))
    target_samples = int(request["sample_rate_sps"] * request["duration_seconds"])
    expected_request_size = int(request.get("expected_size_bytes") or 0)
    received = overflows = discontinuities = telemetry_publish_failures = chunks = 0
    receiver_events: list[dict] = []
    failure_reason_codes: list[str] = []
    loss_correlation = "unknown"
    writer: DedicatedWriter | None = None
    telemetry_publisher: LiveTelemetryPublisher | None = None
    writer_metrics = {
        "writer_thread_mode": "disabled",
        "writer_queue_capacity_bytes": 0,
        "writer_queue_high_watermark_bytes": 0,
        "writer_queue_overrun_count": 0,
        "maximum_buffer_occupancy": 0,
        "write_block_size_bytes": 0,
        "write_call_count": 0,
        "mean_write_latency_ms": None,
        "maximum_write_latency_ms": None,
        "measured_write_throughput_bytes_s": None,
        "memory_copy_count_per_block": 0,
        "writer_error": None,
    }
    started_at = utc_now()
    b200_rf_started_at: str | None = None
    b200_rf_finished_at: str | None = None
    capture_started_monotonic = time.monotonic()
    sampler = CpuSampler()
    sampler.start()
    stream = None
    device = None
    hw = "unknown"
    hw_info: dict[str, str] = {}
    manifest_status = "COMPLETE"

    def publish_terminal(capture_complete: bool, diagnostic_status: str, error: str | None = None) -> None:
        nonlocal writer_metrics
        cpu_metrics = sampler.stop()
        actual_size = final.stat().st_size if final.exists() else partial.stat().st_size if partial.exists() else 0
        expected_size = received * profile["bytes_per_file_sample"] if persist_iq else 0
        size_status = "PASSED" if actual_size == expected_size else "FAILED"
        continuity_status = "PASSED" if overflows == 0 and discontinuities == 0 else "FAILED"
        if persist_iq and size_status != "PASSED" and "CAPTURE_SIZE_MISMATCH" not in failure_reason_codes:
            failure_reason_codes.append("CAPTURE_SIZE_MISMATCH")
        if overflows and "ACQUISITION_OVERFLOW" not in failure_reason_codes:
            failure_reason_codes.append("ACQUISITION_OVERFLOW")
        if discontinuities and "ACQUISITION_DISCONTINUITY" not in failure_reason_codes:
            failure_reason_codes.append("ACQUISITION_DISCONTINUITY")
        data_sha = sha256(final) if persist_iq and final.exists() else None
        metadata_sha = sha256(meta_path) if persist_iq and meta_path.exists() else None
        hash_status = "VERIFIED" if persist_iq and data_sha and metadata_sha else "NOT_APPLICABLE" if not persist_iq else "NOT_AVAILABLE"
        metadata_status = "COMPLETE" if (not persist_iq or meta_path.exists()) else "INCOMPLETE"
        writer_metrics = dict(writer_metrics)
        writer_metrics.update({
            "storage_target": str(output),
            "storage_free_bytes": storage_free_bytes(output),
            "hash_during_capture": False,
            "manifest_during_capture": False,
            "fsync_during_capture": False,
        })
        quality = {
            "schema_version": "ble-sdr-quality-v1",
            "capture_id": capture_id,
            "capture_complete": capture_complete,
            "diagnostic_status": diagnostic_status,
            "overflow_count": overflows,
            "discontinuity_count": discontinuities,
            "silent_sample_loss_detected": discontinuities > 0,
            "fingerprinting_eligible": False,
            "disk_persistence_enabled": persist_iq,
            "writer_metrics": writer_metrics,
            **writer_metrics,
            **cpu_metrics,
            "storage_target": str(output),
            "storage_free_bytes": storage_free_bytes(output),
            "loss_correlation": loss_correlation,
            "failure_reason_codes": failure_reason_codes,
            "limitations": ["Diagnostic capture only; not eligible for dataset or training."],
        }
        atomic_json(output / "quality_report.json", quality)
        write_jsonl(output / "receiver_events.jsonl", receiver_events)
        manifest = {
            "schema_version": "ble-sdr-capture-manifest-v2",
            "capture_id": capture_id,
            "created_at_utc": started_at,
            "b200_job_started_at": started_at,
            "b200_job_finished_at": utc_now(),
            "b200_rf_started_at": b200_rf_started_at,
            "b200_rf_finished_at": b200_rf_finished_at,
            "b200_rf_duration_seconds": received / request["sample_rate_sps"],
            "diagnostic_status": diagnostic_status,
            "manifest_status": manifest_status,
            "device_driver": request["device_args"].get("driver", "unknown"),
            "device_serial": hw_info.get("serial") or request["device_args"].get("serial"),
            "device_serial_masked": request.get("device_serial_masked"),
            "hardware": hw,
            "usb_mode": observed_usb_mode(output),
            "uhd_version": hw_info.get("uhd_version") or hw_info.get("version") or uhd_version(),
            "backend_commit": backend_commit(),
            "host_id": platform.node(),
            "capture_software_version": "ble-sdr-capture-v3",
            "center_frequency_hz": request["center_frequency_hz"],
            "ble_channel": request.get("ble_channel"),
            "sample_rate_sps": request["sample_rate_sps"],
            "bandwidth_hz": request["bandwidth_hz"],
            "sample_format": fmt,
            **profile,
            "gain_configuration": {"mode": request.get("gain_mode"), "gain_db": request.get("gain_db")},
            "antenna": request.get("antenna"),
            "requested_duration_seconds": request["duration_seconds"],
            "actual_samples": received,
            "sample_count": received,
            "actual_duration_seconds": received / request["sample_rate_sps"],
            "expected_size_bytes": expected_request_size,
            "expected_file_size_bytes": expected_request_size,
            "actual_size_bytes": actual_size,
            "file_size": actual_size,
            "size_status": size_status,
            "dropped_samples": None,
            "overflow_count": overflows,
            "input_discontinuities": discontinuities,
            "discontinuity_count": discontinuities,
            "telemetry_publish_failures": telemetry_publish_failures,
            "data_path": final.name if persist_iq and final.exists() else None,
            "metadata_path": meta_path.name if persist_iq and meta_path.exists() else None,
            "data_sha256": data_sha,
            "metadata_sha256": metadata_sha,
            "capture_complete": capture_complete,
            "disk_persistence_enabled": persist_iq,
            "frontend_preview_enabled": bool(request.get("frontend_preview_enabled", True)),
            "ui_polling_mode": request.get("ui_polling_mode", "normal"),
            "diagnostic_step": request.get("diagnostic_step"),
            "writer_metrics": writer_metrics,
            **writer_metrics,
            **cpu_metrics,
            "hash_status": hash_status,
            "metadata_status": metadata_status,
            "hash_during_capture": False,
            "manifest_during_capture": False,
            "fsync_during_capture": False,
            "gap_handling_policy": "overflow_counter_only_no_local_gap_reconstruction",
            "samples_lost_estimated": None,
            "samples_inserted_or_repeated": 0,
            "continuity_status": continuity_status,
            "loss_correlation": loss_correlation,
            "failure_reason_codes": failure_reason_codes,
            "scientific_corpus_membership": "none",
            "eligible_for_holdout": False,
            "dataset_eligible": False,
            "qualification_only": True,
            "purpose": request["purpose"],
            "controlled_transmitter_state": request.get("controlled_transmitter_state", "unknown"),
            "operator_confirmed": bool(request.get("operator_confirmed", False)),
            "confirmation_method": request.get("confirmation_method"),
            "capture_role": request.get("capture_role"),
            "analysis_status": "not_requested",
            "iq_recovery_validated": False,
            "ota_validated": False,
            "error": error,
            # Paper-campaign metadata: copied straight from the caller's
            # request when declared (e.g. by paper_campaign_runner.py before
            # capture) -- never fabricated here. Absent from `request` on
            # every capture not run through the runner, which leaves these
            # None on the manifest and, downstream, on CaptureRecord too.
            "day_id": request.get("day_id"), "campaign_period": request.get("campaign_period"),
            "pre_or_post": request.get("pre_or_post"), "intervention_arm": request.get("intervention_arm"),
            "packet_condition": request.get("packet_condition"), "receiver_epoch": request.get("receiver_epoch"),
            "receiver_session_id": request.get("receiver_session_id"),
            "firmware_hash": request.get("firmware_hash"), "configuration_hash": request.get("configuration_hash"),
            "time_since_power_on_s": request.get("time_since_power_on_s"),
            "time_since_intervention_s": request.get("time_since_intervention_s"),
            "capture_order": request.get("capture_order"), "review_status": request.get("review_status"),
            "ambient_temperature_c": request.get("ambient_temperature_c"), "battery_id": request.get("battery_id"),
            "battery_voltage_pre_v": request.get("battery_voltage_pre_v"), "battery_voltage_post_v": request.get("battery_voltage_post_v"),
            "operator_id": request.get("operator_id"), "planned_capture_id": request.get("planned_capture_id"),
        }
        atomic_json(output / "capture_manifest.json", manifest)
        if persist_iq and data_sha and metadata_sha:
            (output / "capture.sha256").write_text(f"{data_sha}  {final.name}\n{metadata_sha}  {meta_path.name}\n", encoding="ascii")

    try:
        matches = list(SoapySDR.Device.enumerate(request["device_args"]))
        if not matches:
            failure_reason_codes.append("SDR_DEVICE_NOT_FOUND_DURING_CAPTURE")
            publish_terminal(False, "FAILED", "SDR_DEVICE_NOT_FOUND_DURING_CAPTURE")
            return 2
        device = SoapySDR.Device(matches[0])
        device.setSampleRate(SoapySDR.SOAPY_SDR_RX, 0, request["sample_rate_sps"])
        device.setFrequency(SoapySDR.SOAPY_SDR_RX, 0, request["center_frequency_hz"])
        device.setBandwidth(SoapySDR.SOAPY_SDR_RX, 0, request["bandwidth_hz"])
        if request.get("antenna"):
            device.setAntenna(SoapySDR.SOAPY_SDR_RX, 0, request["antenna"])
        if request.get("gain_mode") == "automatic":
            device.setGainMode(SoapySDR.SOAPY_SDR_RX, 0, True)
        else:
            device.setGainMode(SoapySDR.SOAPY_SDR_RX, 0, False)
            device.setGain(SoapySDR.SOAPY_SDR_RX, 0, request["gain_db"])
        buffer, wire_format = output_buffer(fmt, min(262144, max(16384, int(request["sample_rate_sps"] // 20))))
        block_samples = len(buffer) if fmt == "cf32_le" else len(buffer) // 2
        write_block_size = block_samples * profile["bytes_per_file_sample"]
        if persist_iq:
            capacity = int(request.get("writer_queue_capacity_bytes") or 64 * 1024 * 1024)
            writer = DedicatedWriter(partial, capacity, write_block_size, fsync_on_close=True)
            writer.start()
            writer_metrics = writer.metrics(1e-9)
        telemetry_enabled = request.get("ui_polling_mode", "normal") != "disabled"
        if telemetry_enabled:
            telemetry_publisher = LiveTelemetryPublisher(output / "live.json")
            telemetry_publisher.start()
        hw = str(device.getHardwareKey())
        hw_info = {str(k): str(v) for k, v in dict(device.getHardwareInfo()).items()}
        stream = device.setupStream(SoapySDR.SOAPY_SDR_RX, wire_format, [0])
        b200_rf_started_at = utc_now()
        receiver_events.append({"event_type": "capture_started", "event": "capture_started", "timestamp_utc": b200_rf_started_at, "sample_index": 0})
        device.activateStream(stream)
        while received < target_samples:
            wanted = min(block_samples, target_samples - received)
            result = device.readStream(stream, [buffer], wanted, timeoutUs=1_000_000)
            if result.ret == SoapySDR.SOAPY_SDR_OVERFLOW:
                overflows += 1
                discontinuities += 1
                receiver_events.append({"event_type": "host_receive_overrun", "event": "stream_overflow",
                                        "timestamp_utc": utc_now(), "sample_index_start": received,
                                        "sample_index_end": None, "estimated_samples_lost": None})
                loss_correlation = "host_receive_overrun"
                continue
            if result.ret <= 0:
                failure_reason_codes.append(f"SDR_STREAM_READ_ERROR:{result.ret}")
                raise RuntimeError(f"SDR_STREAM_READ_ERROR:{result.ret}")
            samples = int(result.ret)
            payload = buffer[:samples if fmt == "cf32_le" else samples * 2].tobytes(order="C")
            received += samples
            if writer is not None and not writer.submit(payload):
                failure_reason_codes.append("WRITER_QUEUE_FULL")
                receiver_events.append({"event_type": "writer_queue_full", "event": "writer_queue_full",
                                        "timestamp_utc": utc_now(), "sample_index_start": received - samples,
                                        "sample_index_end": received, "estimated_samples_lost": samples})
                loss_correlation = "writer_queue_full"
                break
            chunks += 1
            written = writer.bytes_written if writer is not None else 0
            if telemetry_enabled and (chunks % 5 == 0 or received == target_samples):
                # live_metrics() reads `buffer` synchronously, before the next
                # readStream() can overwrite it -- safe on this thread. Only
                # the disk write (atomic_json's fsync) is handed off, since
                # THAT was the real source of RX-loop stalls -> overflows.
                live = live_metrics(complex_view(buffer, fmt, samples), request, received, written, overflows, discontinuities)
                if writer is not None:
                    live["writer_queue_high_watermark_bytes"] = writer.high_watermark_bytes
                    live["writer_queue_overrun_count"] = writer.queue_overrun_count
                telemetry_publisher.submit(live)
        b200_rf_finished_at = utc_now()
        receiver_events.append({"event_type": "capture_rf_finished", "event": "capture_rf_finished",
                                "timestamp_utc": b200_rf_finished_at, "sample_index": received,
                                "overflow_count": overflows, "discontinuity_count": discontinuities})
        if stream is not None:
            device.deactivateStream(stream)
            device.closeStream(stream)
            stream = None
        write_elapsed = max(time.monotonic() - capture_started_monotonic, 1e-9)
        if writer is not None:
            writer.close()
            writer_metrics = writer.metrics(write_elapsed)
        if telemetry_publisher is not None:
            telemetry_publisher.close()
            telemetry_publish_failures = telemetry_publisher.publish_failures
        if persist_iq:
            actual_partial = partial.stat().st_size if partial.exists() else 0
            expected = received * profile["bytes_per_file_sample"]
            if actual_partial != expected:
                failure_reason_codes.append("CAPTURE_SIZE_MISMATCH")
            else:
                os.replace(partial, final)
            metadata = {"global": {"core:version": "1.2.6", "core:datatype": fmt, "core:sample_rate": request["sample_rate_sps"],
                        "core:hw": hw, "core:recorder": "SpectraRFX BLE Capture", "core:description": request.get("description", "Experimental BLE-channel IQ capture")},
                        "captures": [{"core:sample_start": 0, "core:frequency": request["center_frequency_hz"], "core:datetime": b200_rf_started_at or started_at}], "annotations": []}
            atomic_json(meta_path, metadata)
        analysis_enabled = bool(request.get("analysis_enabled", False))
        bursts = detect_bursts(final, fmt, request["sample_rate_sps"], output) if persist_iq and final.exists() and analysis_enabled else []
        write_jsonl(output / "burst_candidates.jsonl", bursts)
        receiver_events.append({"event_type": "capture_finished", "event": "capture_finished",
                                "timestamp_utc": utc_now(), "sample_index": received,
                                "overflow_count": overflows, "discontinuity_count": discontinuities})
        passed = received == target_samples and overflows == 0 and discontinuities == 0 and not failure_reason_codes
        publish_terminal(passed, "PASSED" if passed else "FAILED")
        return 0 if passed else 2
    except Exception as error:
        if not failure_reason_codes:
            failure_reason_codes.append(type(error).__name__)
        try:
            if writer is not None:
                writer.close()
                writer_metrics = writer.metrics(max(time.monotonic() - capture_started_monotonic, 1e-9))
        except Exception as writer_error:
            failure_reason_codes.append("WRITER_ERROR")
            writer_metrics = writer.metrics(max(time.monotonic() - capture_started_monotonic, 1e-9)) if writer is not None else writer_metrics
            writer_metrics["writer_error"] = str(writer_error)
        if telemetry_publisher is not None:
            telemetry_publisher.close()
            telemetry_publish_failures = telemetry_publisher.publish_failures
        publish_terminal(False, "FAILED", f"{type(error).__name__}:{error}")
        return 2
    finally:
        if stream is not None and device is not None:
            try:
                device.deactivateStream(stream)
                device.closeStream(stream)
            except Exception:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("devices")
    capture_parser = sub.add_parser("capture"); capture_parser.add_argument("--request", type=Path, required=True); capture_parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try: return probe() if args.action == "devices" else capture(args.request, args.output_dir)
    except Exception as error: print(f"{type(error).__name__}:{error}", file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
