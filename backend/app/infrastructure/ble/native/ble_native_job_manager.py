from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError as FutureTimeoutError
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..parsers import BleParserRegistry
from ..parsers.vendor_profiles import (
    KNOWN_SERVICE_NAMES,
    TI_HUMIDITY_CONFIG,
    TI_HUMIDITY_DATA,
    TI_HUMIDITY_PERIOD,
    TI_IR_TEMPERATURE_CONFIG,
    TI_IR_TEMPERATURE_DATA,
    TI_IR_TEMPERATURE_PERIOD,
)
from .ble_device_registry import BleDeviceRegistry


class BleNativeJobManager:
    LEGACY_SENSORS={
        "accelerometer":{"data":"f000aa11-0451-4000-b000-000000000000","config":"f000aa12-0451-4000-b000-000000000000","period":"f000aa13-0451-4000-b000-000000000000","enable":b"\x01"},
        "magnetometer":{"data":"f000aa31-0451-4000-b000-000000000000","config":"f000aa32-0451-4000-b000-000000000000","period":"f000aa33-0451-4000-b000-000000000000","enable":b"\x01"},
        "barometer":{"data":"f000aa41-0451-4000-b000-000000000000","config":"f000aa42-0451-4000-b000-000000000000","calibration":"f000aa43-0451-4000-b000-000000000000","enable":b"\x01"},
        "gyroscope":{"data":"f000aa51-0451-4000-b000-000000000000","config":"f000aa52-0451-4000-b000-000000000000","enable":b"\x07"},
        "simple_keys":{"data":"0000ffe1-0000-1000-8000-00805f9b34fb"},
        "ambient_light":{"data":"f000aa71-0451-4000-b000-000000000000","config":"f000aa72-0451-4000-b000-000000000000","period":"f000aa73-0451-4000-b000-000000000000","enable":b"\x01"},
        "movement":{"data":"f000aa81-0451-4000-b000-000000000000","config":"f000aa82-0451-4000-b000-000000000000","period":"f000aa83-0451-4000-b000-000000000000","enable":b"\x7f\x00"},
    }
    def __init__(self, root: Path) -> None:
        self.root = root; root.mkdir(parents=True, exist_ok=True)
        self.registry = BleDeviceRegistry(root / "device_registry.json")
        self.parsers = BleParserRegistry()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="ble-native-winrt")
        self._thread.start()
        self._scanner = None; self._clients: dict[str, Any] = {}; self._scanning = False
        self._discovered_devices: dict[str, Any] = {}
        self._connection_jobs: dict[str, dict[str, Any]] = {}
        self._connection_futures: dict[str, Any] = {}
        self._connection_by_device: dict[str, str] = {}
        self._connection_lock = threading.RLock()
        self._last_error: str | None = None
        self._scan_session_id: str | None = None
        self._scan_session_dir: Path | None = None
        self._scan_process: subprocess.Popen | None = None
        self._scan_stop_file: Path | None = None
        self._scan_file_lock = threading.Lock()
        self._gatt_semaphore = None
        self.gatt_policy = {"max_concurrent_gatt_connections": 1, "max_retries_per_device": 3,
                            "connection_timeout_s": 12.0, "service_discovery_timeout_s": 15.0,
                            "read_timeout_s": 10.0, "notification_timeout_s": 5.0, "retry_backoff_s": 0.75}

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop); self._loop.run_forever()

    def _submit(self, coroutine, timeout: float = 30):
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            future.cancel()
            raise

    async def _adapter_status(self) -> dict[str, Any]:
        try:
            from bleak.backends.winrt.util import assert_mta
            await assert_mta()
            from winrt.windows.devices.bluetooth import BluetoothAdapter
            adapter = await BluetoothAdapter.get_default_async()
            if adapter is None: raise RuntimeError("NO_DEFAULT_BLUETOOTH_ADAPTER")
            return {"available": True, "adapter_type": "native_ble", "backend": "winrt", "scan_supported": True, "gatt_supported": True}
        except Exception as error:
            self._last_error = f"{type(error).__name__}:{error}"
            return {"available": False, "adapter_type": "native_ble", "backend": "winrt", "scan_supported": False, "gatt_supported": False, "reason_code": "NO_NATIVE_BLE_ADAPTER", "message": "A conventional BLE adapter is required for device scanning and GATT access.", "diagnostic": self._last_error}

    def status(self) -> dict[str, Any]:
        try: result = self._submit(self._adapter_status(), 10)
        except Exception as error: result = {"available": False, "adapter_type": "native_ble", "backend": "winrt", "scan_supported": False, "gatt_supported": False, "reason_code": "NO_NATIVE_BLE_ADAPTER", "message": "A conventional BLE adapter is required for device scanning and GATT access.", "diagnostic": f"{type(error).__name__}:{error}"}
        return {**result, "scanning": self._scanning, "scan_session_id": self._scan_session_id,
                "device_count": len(self.registry.list()), "last_error": self._last_error,
                "native_gate_status": "NATIVE-1_IMPLEMENTED_PENDING_RUNTIME_VALIDATION", "gatt_policy": self.gatt_policy}

    async def _start_scan(self, session_id: str | None = None) -> None:
        if self._scanning: return
        self._scan_session_id = session_id or ("ble-scan-" + uuid.uuid4().hex)
        if any(token in self._scan_session_id for token in ("/", "\\", "..")): raise ValueError("INVALID_SCAN_SESSION_ID")
        self._scan_session_dir = self.root / "scans" / self._scan_session_id
        self._scan_session_dir.mkdir(parents=True, exist_ok=True)
        self._scan_stop_file = self._scan_session_dir / "stop.requested"
        if self._scan_stop_file.exists(): self._scan_stop_file.unlink()
        started_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        (self._scan_session_dir / "scan_manifest.json").write_text(json.dumps({"schema_version":"ble-native-scan-v1",
            "scan_session_id":self._scan_session_id,"started_at_utc":started_utc,"started_monotonic_ns":time.monotonic_ns(),
            "backend_version":"ble-native-v1","bleak_version":"0.22.3","deduplication":False}, indent=2)+"\n", encoding="utf-8")
        backend_root = Path(__file__).resolve().parents[4]
        worker = Path(os.environ.get("BLE_NATIVE_SCAN_WORKER", backend_root / "tools" / "ble_native_scan_worker.py"))
        stdout = (self._scan_session_dir / "worker.stdout.log").open("ab")
        stderr = (self._scan_session_dir / "worker.stderr.log").open("ab")
        self._scan_process = subprocess.Popen(
            [sys.executable, str(worker), "--scan-dir", str(self._scan_session_dir),
             "--session-id", self._scan_session_id, "--stop-file", str(self._scan_stop_file)],
            cwd=str(backend_root), stdout=stdout, stderr=stderr, shell=False, env=dict(os.environ),
        )
        status_path = self._scan_session_dir / "worker_status.json"
        deadline = time.monotonic() + float(os.environ.get("BLE_NATIVE_WORKER_READY_TIMEOUT_SECONDS", "60"))
        last_worker_status: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            if status_path.exists():
                status = json.loads(status_path.read_text(encoding="utf-8"))
                last_worker_status = status
                if status.get("state") == "running":
                    self._scanning = True; self._last_error = None; return
                if status.get("state") == "failed":
                    raise RuntimeError(status.get("error") or "NATIVE_BLE_WORKER_FAILED")
            if self._scan_process.poll() is not None:
                raise RuntimeError(f"NATIVE_BLE_WORKER_EXITED:{self._scan_process.returncode}")
            await asyncio.sleep(0.1)
        detail = ""
        if last_worker_status:
            detail = ":" + json.dumps({k: last_worker_status.get(k) for k in ("state", "phase", "error", "updated_at_utc")}, sort_keys=True)
        raise TimeoutError(f"NATIVE_BLE_WORKER_READY_TIMEOUT{detail}")

    def start_scan(self, session_id: str | None = None) -> dict[str, Any]:
        timeout = float(os.environ.get("BLE_NATIVE_SCAN_START_TIMEOUT_SECONDS", "45"))
        try: self._submit(self._start_scan(session_id), timeout)
        except Exception as error:
            self._last_error = f"{type(error).__name__}:{error}"
            if self._scan_process is not None and self._scan_process.poll() is None:
                self._scan_process.terminate()
            self._scanner = None; self._scanning = False
            raise RuntimeError(f"NATIVE_BLE_SCAN_FAILED:{self._last_error}") from error
        return {"state": "scanning", "started": True, "scan_session_id": self._scan_session_id}

    def _write_scan_devices_snapshot(self) -> None:
        if not self._scan_session_dir: return
        worker_snapshot = self._scan_session_dir / "devices.json"
        if worker_snapshot.exists():
            try:
                for item in json.loads(worker_snapshot.read_text(encoding="utf-8")).get("devices", []):
                    self.registry.merge_observed(item)
            except Exception as error:
                self._last_error = f"{type(error).__name__}:{error}"
        devices=[item for item in self.registry.list() if item.get("scan_session_id")==self._scan_session_id]
        (self._scan_session_dir/"devices.json").write_text(json.dumps({"schema_version":"ble-native-devices-v1","devices":devices},indent=2)+"\n",encoding="utf-8")

    async def _stop_scan(self) -> None:
        try:
            if self._scan_stop_file is not None:
                self._scan_stop_file.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
            if self._scan_process is not None:
                deadline = time.monotonic() + 10
                while self._scan_process.poll() is None and time.monotonic() < deadline:
                    await asyncio.sleep(0.1)
                if self._scan_process.poll() is None:
                    self._scan_process.terminate()
                    await asyncio.sleep(1)
                if self._scan_process.poll() is None:
                    self._scan_process.kill()
        finally:
            self._write_scan_devices_snapshot()
            self._scanner = None; self._scan_process = None; self._scan_stop_file = None; self._scanning = False

    def stop_scan(self) -> dict[str, Any]:
        if not self._scanning and self._scanner is None and self._scan_process is None:
            self._write_scan_devices_snapshot()
            return {"state": "idle", "stopped": False, "already_idle": True, "device_count": len(self.registry.list())}
        try:
            self._submit(self._stop_scan(), 15)
        except Exception as error:
            self._last_error = f"{type(error).__name__}:{error}"
            self._scanner = None; self._scanning = False
            return {"state": "idle", "stopped": False, "stop_error": self._last_error, "device_count": len(self.registry.list())}
        return {"state": "idle", "stopped": True, "device_count": len(self.registry.list())}

    def devices(self) -> list[dict[str, Any]]: return self.registry.list()
    def device(self, device_id: str) -> dict[str, Any]: return self.registry.get(device_id)
    def diagnostics(self, device_id: str) -> list[dict[str, Any]]: return self.registry.get(device_id).get("gatt_diagnostics", [])

    @staticmethod
    def _error_status(error: Exception) -> str:
        value = f"{type(error).__name__}:{error}".lower()
        if "timeout" in value: return "CONNECTION_TIMEOUT"
        if "access" in value or "denied" in value: return "ACCESS_DENIED"
        if "pair" in value: return "PAIRING_REQUIRED"
        if "not discoverable" in value or "not found" in value: return "DEVICE_OBJECT_UNRESOLVED"
        if "unreachable" in value: return "CONNECTION_UNREACHABLE"
        return "GATT_DISCOVERY_FAILED"

    def _diagnostic(self, device_id: str, operation: str, attempt: int, started: float,
                    *, status: str, error: Exception | None = None, cache_mode: str = "cached") -> None:
        finished = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.registry.add_diagnostic(device_id, {
            "attempt_id": "gatt-attempt-" + uuid.uuid4().hex,
            "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "started_at": finished, "finished_at": finished,
            "started_monotonic_ns": int(started * 1_000_000_000), "finished_monotonic_ns": time.monotonic_ns(),
            "scan_session_id": self.registry.get(device_id).get("scan_session_id"),
            "bleak_version": "0.22.3", "backend_version": "ble-native-v1",
            "operation": operation, "attempt": attempt,
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
            "cache_mode": cache_mode, "status": status,
            "exception_class": type(error).__name__ if error else None,
            "exception_message": str(error) if error else None,
            "winrt_code": getattr(error, "winerror", None) if error else None,
            "gatt_communication_status": getattr(error, "status", None) if error else None,
            "protocol_error": getattr(error, "protocol_error", None) if error else None,
        })

    def diagnostic_report(self, device_id: str) -> dict[str, Any]:
        record = self.registry.get(device_id)
        attempts = []
        for item in record.get("gatt_diagnostics", []):
            status = str(item.get("status", ""))
            attempts.append({
                "attempt_id": item.get("attempt_id"), "operation": item.get("operation"),
                "started_at": item.get("started_at") or item.get("timestamp_utc"),
                "finished_at": item.get("finished_at") or item.get("timestamp_utc"),
                "started_monotonic_ns": item.get("started_monotonic_ns"),
                "finished_monotonic_ns": item.get("finished_monotonic_ns"),
                "duration_ms": item.get("duration_ms"), "queue_duration_ms": item.get("queue_duration_ms"),
                "cache_mode": item.get("cache_mode", "not_applicable"),
                "result": "success" if status in {"CONNECTED", "SERVICES_DISCOVERED", "MEASUREMENT_AVAILABLE"} else ("timeout" if "TIMEOUT" in status else "failure"),
                "failure_classification": None if status in {"CONNECTED", "SERVICES_DISCOVERED", "MEASUREMENT_AVAILABLE"} else status,
                "gatt_communication_status": item.get("gatt_communication_status"),
                "protocol_error": item.get("protocol_error"),
                "exception_type": item.get("exception_class"), "exception_message": item.get("exception_message"),
                "winrt_error_code": item.get("winrt_code"), "scan_session_id": item.get("scan_session_id"),
                "bleak_version": item.get("bleak_version"), "backend_version": item.get("backend_version"),
            })
        return {
            "schema_version": "ble-gatt-diagnostics-v1", "device_id": device_id,
            "advertising_state": "ADVERTISEMENT_SEEN" if record.get("advertising_seen") else "NOT_SEEN",
            "connection_state": "CONNECTED" if record.get("connection_established") else (record.get("native_status") if record.get("connection_attempted") else "NOT_ATTEMPTED"),
            "gatt_discovery_state": "GATT_DISCOVERED" if record.get("gatt_discovery_succeeded") else ("GATT_DISCOVERY_FAILED" if record.get("gatt_discovery_attempted") else "NOT_ATTEMPTED"),
            "profile_state": "PROFILE_CLASSIFIED" if record.get("profile_recognized") else "NOT_EVALUATED",
            "parser_state": "SUPPORTED" if record.get("sensor_parser_supported") else ("PARSER_UNSUPPORTED" if record.get("profile_recognized") else "NOT_EVALUATED"),
            "measurement_state": "MEASUREMENT_AVAILABLE" if record.get("measurement_available") else "UNAVAILABLE",
            "attempts": attempts,
        }

    def _connection_stage(self, job_id: str | None, stage: str, step: int, attempt: int = 0) -> None:
        if not job_id: return
        with self._connection_lock:
            job=self._connection_jobs[job_id]
            job.update(current_stage=stage, step=step, attempt=attempt,
                       elapsed_seconds=round(time.monotonic()-job["started_monotonic"], 3), updated_at_utc=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))

    async def _connect(self, device_id: str, job_id: str | None = None) -> dict[str, Any]:
        self._connection_stage(job_id, "WAITING_FOR_GATT_SLOT", 1)
        if self._gatt_semaphore is None: self._gatt_semaphore = asyncio.Semaphore(self.gatt_policy["max_concurrent_gatt_connections"])
        queued = time.monotonic()
        async with self._gatt_semaphore:
            queue_duration_ms = round((time.monotonic() - queued) * 1000, 3)
            if queue_duration_ms > 1:
                self.registry.add_diagnostic(device_id, {"attempt_id": "gatt-attempt-" + uuid.uuid4().hex,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "operation": "queue_wait",
                    "attempt": 0, "duration_ms": 0, "queue_duration_ms": queue_duration_ms, "cache_mode": "not_applicable",
                    "status": "QUEUED", "exception_class": None, "exception_message": None, "winrt_code": None,
                    "gatt_communication_status": None, "protocol_error": None})
            return await self._connect_serialized(device_id, job_id)

    async def _connect_serialized(self, device_id: str, job_id: str | None = None) -> dict[str, Any]:
        from bleak import BleakClient, BleakScanner
        # Most BLE USB adapters only support one active native GATT
        # connection at a time -- connecting to a second device while a
        # first is still held open fails at the WinRT/Bleak level. Drop any
        # other connected device first so "Connect" always succeeds from a
        # clean slate rather than requiring the user to disconnect manually.
        for other_id, other_client in list(self._clients.items()):
            if other_id != device_id and other_client.is_connected:
                await self._disconnect(other_id)
        record = self.registry.get(device_id)
        self._connection_stage(job_id, "RESOLVING_DEVICE", 2)
        self.registry.update(device_id, connection_attempted=True, native_state="CONNECT_REQUESTED", native_status="ADVERTISEMENT_ONLY")
        client = self._clients.get(device_id)
        if client is None or not client.is_connected:
            # Connecting a bare BleakClient(address) is flaky on the WinRT
            # backend -- Windows' own BLE device cache entry for an address
            # can lag behind what a passive scan already sees, so the first
            # attempt sometimes raises BleakDeviceNotFoundError for a device
            # that is genuinely in range and advertising right now. Retry a
            # couple of times before falling back to an explicit fresh
            # discovery (which is slower but resolves a stale cache).
            last_error: Exception | None = None
            for attempt in range(3):
                started = time.monotonic()
                try:
                    self._connection_stage(job_id, "CONNECTING", 3, attempt + 1)
                    discovered = self._discovered_devices.get(device_id)
                    if discovered is None:
                        discovered = await BleakScanner.find_device_by_address(record["address"], timeout=10.0)
                    if discovered is None: raise RuntimeError(f"BLE_DEVICE_NOT_DISCOVERABLE:{record['address']}")
                    client = BleakClient(discovered)
                    await asyncio.wait_for(client.connect(), timeout=12.0)
                    self._diagnostic(device_id, "connect", attempt + 1, started, status="CONNECTED")
                    last_error = None
                    break
                except Exception as error:  # noqa: BLE001 - deliberately broad, this is a hardware-flakiness retry
                    last_error = error
                    status = self._error_status(error)
                    self._diagnostic(device_id, "connect", attempt + 1, started, status=status, error=error)
                    self.registry.update(device_id, connection="failed", connection_established=False, native_status=status)
                    await asyncio.sleep(0.75)
            if last_error is not None:
                discovered = await BleakScanner.find_device_by_address(record["address"], timeout=10.0)
                if discovered is None:
                    self.registry.update(device_id, windows_device_resolved=False, native_status="DEVICE_OBJECT_UNRESOLVED")
                    raise RuntimeError(f"BLE_DEVICE_NOT_DISCOVERABLE:{record['address']}") from last_error
                self.registry.update(device_id, windows_device_resolved=True, native_state="CACHE_RESOLVED")
                client = BleakClient(discovered)
                await asyncio.wait_for(client.connect(), timeout=12.0)
        self._clients[device_id] = client
        self._connection_stage(job_id, "DISCOVERING_SERVICES", 4)
        services = self._serialize_services(client.services)
        self._connection_stage(job_id, "DISCOVERING_CHARACTERISTICS", 5)
        updates: dict[str, Any] = {"connection": "connected", "connection_established": True, "gatt_discovery_attempted": True, "gatt_discovery_succeeded": True, "native_state": "CHARACTERISTICS_DISCOVERED", "native_status": "NO_SENSOR_SERVICES", "data_mode": self._classify_services(services), "gatt_services": services, "notification_supported": any("notify" in char["properties"] or "indicate" in char["properties"] for service in services for char in service["characteristics"])}

        # Phase 2 detection: the connected device's OWN discovered GATT
        # services/characteristics are the only thing that can enable a
        # vendor profile's measurements -- phase 1 (advertising fingerprint,
        # applied earlier by the caller/registry.observe) is a hint only and
        # is deliberately not sufficient by itself (some real SensorTag units
        # advertise with empty manufacturer_data/service_data/service_uuids).
        service_uuids = {item["service_uuid"] for item in services}
        characteristic_uuids = {char["uuid"] for item in services for char in item["characteristics"]}
        profile = self.parsers.detect_connected_vendor_profile(service_uuids, characteristic_uuids)
        self._connection_stage(job_id, "CLASSIFYING_PROFILE", 6)
        previous_environmental = record.get("environmental_sensor") or {}
        previous_ir = record.get("ir_temperature_sensor") or {}
        if profile:
            updates["profile_recognized"] = True
            updates["native_state"] = "PROFILE_CLASSIFIED"
            updates["native_status"] = "PROFILE_CLASSIFIED"
            updates["profile_id"] = profile["profile_id"]
            updates["profile_label"] = profile["profile_label"]
            updates["profile_detection_source"] = profile["profile_detection_source"]
            updates["profile_confidence"] = profile["profile_confidence"]
            updates["probable_platform"] = profile["probable_platform"]
            updates["sensor_inventory"] = profile["sensor_inventory"]
            updates["environmental_sensor"] = {
                **previous_environmental, "available": profile["environmental_available"], "active": False,
                "status": "available" if profile["environmental_available"] else "unavailable",
                "data_uuid": TI_HUMIDITY_DATA, "config_uuid": TI_HUMIDITY_CONFIG, "period_uuid": TI_HUMIDITY_PERIOD,
            }
            updates["ir_temperature_sensor"] = {
                **previous_ir, "available": profile["ir_temperature_available"], "active": False,
                "status": "available" if profile["ir_temperature_available"] else "unavailable",
                "data_uuid": TI_IR_TEMPERATURE_DATA, "config_uuid": TI_IR_TEMPERATURE_CONFIG, "period_uuid": TI_IR_TEMPERATURE_PERIOD,
            }
        self.registry.update(device_id, **updates)
        self._connection_stage(job_id, "CONNECTED", 7)
        return self.registry.get(device_id)

    def connect(self, device_id: str) -> dict[str, Any]: return self._submit(self._connect(device_id), 75)

    def start_connection(self, device_id: str) -> dict[str, Any]:
        self.registry.get(device_id)
        with self._connection_lock:
            existing_id=self._connection_by_device.get(device_id)
            if existing_id and self._connection_jobs[existing_id]["status"] not in {"CONNECTED","FAILED","TIMED_OUT","CANCELLED_BY_USER","CANCELLED_BY_WINDOWS","OPERATION_ABORTED"}:
                return {**self.connection_job(existing_id), "status": "already_in_progress"}
            job_id="ble-connect-"+uuid.uuid4().hex
            now=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            self._connection_jobs[job_id]={"connection_job_id":job_id,"device_id":device_id,"status":"RUNNING","current_stage":"WAITING_FOR_GATT_SLOT","step":1,"total_steps":7,"attempt":0,"max_attempts":3,"created_at_utc":now,"updated_at_utc":now,"started_monotonic":time.monotonic(),"elapsed_seconds":0.0,"error":None}
            self._connection_by_device[device_id]=job_id
            future=asyncio.run_coroutine_threadsafe(self._connect(device_id,job_id),self._loop); self._connection_futures[job_id]=future
            def done(completed):
                with self._connection_lock:
                    job=self._connection_jobs[job_id]; job["elapsed_seconds"]=round(time.monotonic()-job["started_monotonic"],3); job["updated_at_utc"]=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    if completed.cancelled(): job.update(status="CANCELLED_BY_USER",current_stage="CANCELLED_BY_USER")
                    else:
                        error=completed.exception()
                        if error: job.update(status="TIMED_OUT" if "timeout" in f"{type(error).__name__}:{error}".lower() else "FAILED",current_stage="FAILED",error=f"{type(error).__name__}:{error}")
                        else: job.update(status="CONNECTED",current_stage="CONNECTED",result=completed.result())
            future.add_done_callback(done)
            return self.connection_job(job_id)

    def connection_job(self, job_id: str) -> dict[str, Any]:
        with self._connection_lock:
            if job_id not in self._connection_jobs: raise KeyError(job_id)
            job=dict(self._connection_jobs[job_id]); job["elapsed_seconds"]=round(time.monotonic()-job["started_monotonic"],3) if job["status"] in {"RUNNING","already_in_progress"} else job["elapsed_seconds"]
            job.pop("started_monotonic",None); return job

    def cancel_connection(self, job_id: str) -> dict[str, Any]:
        with self._connection_lock:
            if job_id not in self._connection_jobs: raise KeyError(job_id)
            future=self._connection_futures.get(job_id)
            if future and not future.done(): future.cancel()
        return self.connection_job(job_id)

    @staticmethod
    def _mark_stale(sensor: dict[str, Any] | None) -> dict[str, Any] | None:
        if not sensor:
            return sensor
        reading = sensor.get("last_reading")
        return {**sensor, "active": False, "status": "disconnected", "last_reading": {**reading, "stale": True} if reading else None}

    async def _disconnect(self, device_id: str) -> None:
        client = self._clients.pop(device_id, None)
        if client and client.is_connected: await client.disconnect()
        record = self.registry.get(device_id)
        # A lost/closed connection must never keep showing the last reading
        # as current -- preserve it for history, but mark it stale.
        self.registry.update(
            device_id, connection="disconnected",
            connection_established=False, native_status="ADVERTISEMENT_ONLY",
            environmental_sensor=self._mark_stale(record.get("environmental_sensor")),
            ir_temperature_sensor=self._mark_stale(record.get("ir_temperature_sensor")),
        )

    def disconnect(self, device_id: str) -> dict[str, Any]: self._submit(self._disconnect(device_id), 20); return self.registry.get(device_id)

    def services(self, device_id: str) -> list[dict[str, Any]]:
        record = self.registry.get(device_id)
        if record.get("connection") != "connected": self.connect(device_id); record = self.registry.get(device_id)
        return record.get("gatt_services", [])

    @staticmethod
    def _serialize_services(services) -> list[dict[str, Any]]:
        return [{"service_uuid": service.uuid.lower(), "description": service.description, "known_name": KNOWN_SERVICE_NAMES.get(service.uuid.lower()), "characteristics": [{"uuid": char.uuid.lower(), "description": char.description, "properties": list(char.properties), "descriptors": [{"handle": desc.handle, "uuid": desc.uuid.lower(), "description": desc.description} for desc in char.descriptors]} for char in service.characteristics]} for service in services]

    def _classify_services(self, services: list[dict[str, Any]]) -> str:
        properties = {prop for service in services for char in service["characteristics"] for prop in char["properties"]}
        return "GATT_NOTIFY" if properties & {"notify", "indicate"} else "GATT_READ" if "read" in properties else "UNKNOWN_FORMAT"

    def _characteristic(self, device_id: str, characteristic_uuid: str) -> dict[str, Any]:
        for service in self.registry.get(device_id).get("gatt_services", []):
            for characteristic in service["characteristics"]:
                if characteristic["uuid"].lower() == characteristic_uuid.lower(): return characteristic
        raise KeyError(characteristic_uuid)

    async def _read(self, device_id: str, characteristic_uuid: str) -> dict[str, Any]:
        if device_id not in self._clients or not self._clients[device_id].is_connected: await self._connect(device_id)
        characteristic = self._characteristic(device_id, characteristic_uuid)
        if "read" not in characteristic["properties"]: raise PermissionError("CHARACTERISTIC_NOT_READABLE")
        raw = bytes(await self._clients[device_id].read_gatt_char(characteristic_uuid))
        measurement = self.parsers.parse_gatt(device_id, characteristic_uuid, raw, "gatt_read")
        if measurement: self.registry.add_measurement(device_id, measurement)
        return {"device_id": device_id, "characteristic_uuid": characteristic_uuid.lower(), "raw_hex": raw.hex(), "measurement": measurement, "parser_supported": measurement is not None}

    def read(self, device_id: str, characteristic_uuid: str) -> dict[str, Any]: return self._submit(self._read(device_id, characteristic_uuid), 30)

    async def _subscribe(self, device_id: str, characteristic_uuid: str) -> dict[str, Any]:
        if device_id not in self._clients or not self._clients[device_id].is_connected: await self._connect(device_id)
        characteristic = self._characteristic(device_id, characteristic_uuid)
        if not ({"notify", "indicate"} & set(characteristic["properties"])): raise PermissionError("CHARACTERISTIC_NOT_NOTIFIABLE")
        def callback(_, data: bytearray):
            measurement = self.parsers.parse_gatt(device_id, characteristic_uuid, bytes(data), "gatt_notify")
            if measurement: self.registry.add_measurement(device_id, measurement)
        await self._clients[device_id].start_notify(characteristic_uuid, callback)
        self.registry.update(device_id, connection="receiving_notifications", data_mode="GATT_NOTIFY")
        return {"subscribed": True, "characteristic_uuid": characteristic_uuid.lower(), "parser": self.parsers.describe(characteristic_uuid)}

    def subscribe(self, device_id: str, characteristic_uuid: str) -> dict[str, Any]: return self._submit(self._subscribe(device_id, characteristic_uuid), 30)

    async def _unsubscribe(self, device_id: str, characteristic_uuid: str) -> None:
        await self._clients[device_id].stop_notify(characteristic_uuid)
        self.registry.update(device_id, connection="connected")

    def unsubscribe(self, device_id: str, characteristic_uuid: str) -> dict[str, Any]: self._submit(self._unsubscribe(device_id, characteristic_uuid), 20); return {"subscribed": False, "characteristic_uuid": characteristic_uuid.lower()}

    # ── TI CC2650 SensorTag: humidity/ambient temperature service (AA20) ────
    # Sequence per TI's SensorTag user guide: subscribe AA21, write the
    # sampling period to AA23, then write 0x01 to AA22 to enable the sensor.
    # Stopping is the mirror image: write 0x00 to AA22 (best-effort -- the
    # notification is always torn down even if this write fails), then stop
    # the AA21 subscription.
    def _update_environmental_reading(self, device_id: str, measurements: list[dict[str, Any]]) -> None:
        if not measurements: return
        by_type = {item["measurement_type"]: item for item in measurements}
        sensor = self.registry.get(device_id).get("environmental_sensor") or {}
        reading = {
            "temperature_c": by_type.get("temperature", {}).get("value"),
            "relative_humidity_percent": by_type.get("relative_humidity", {}).get("value"),
            "observed_at_utc": measurements[0]["observed_at_utc"],
            "source_raw_hex": measurements[0]["source_raw_hex"],
            "stale": False,
        }
        self.registry.update(device_id, environmental_sensor={**sensor, "active": True, "status": "active", "last_reading": reading})

    async def _start_environmental(self, device_id: str, period_hex: bytes = b"\x64", first_notification_timeout: float = 5.0) -> dict[str, Any]:
        if device_id not in self._clients or not self._clients[device_id].is_connected: await self._connect(device_id)
        record = self.registry.get(device_id)
        sensor = record.get("environmental_sensor") or {}
        if not sensor.get("available"): raise PermissionError("TI_ENVIRONMENTAL_SENSOR_NOT_AVAILABLE")
        if sensor.get("active"): return record  # already running -- idempotent, not a second subscription
        client = self._clients[device_id]
        first_notification = asyncio.Event()

        def callback(_, data: bytearray):
            measurements = self.parsers.parse_ti_humidity_notification(device_id, bytes(data))
            for measurement in measurements: self.registry.add_measurement(device_id, measurement)
            self._update_environmental_reading(device_id, measurements)
            first_notification.set()

        # Set "starting" BEFORE subscribing, not after writing period/config --
        # a fast device (or, as in tests, a mock) can deliver its first
        # notification before those two writes even return, and updating the
        # registry afterward with this pre-subscribe snapshot would clobber
        # the reading the callback already stored.
        self.registry.update(device_id, environmental_sensor={**sensor, "active": True, "status": "starting"})
        await client.start_notify(TI_HUMIDITY_DATA, callback)
        await client.write_gatt_char(TI_HUMIDITY_PERIOD, period_hex, response=True)
        await client.write_gatt_char(TI_HUMIDITY_CONFIG, b"\x01", response=True)
        try:
            await asyncio.wait_for(first_notification.wait(), timeout=first_notification_timeout)
        except asyncio.TimeoutError:
            current = self.registry.get(device_id).get("environmental_sensor") or {}
            self.registry.update(device_id, environmental_sensor={**current, "status": "starting_no_data_yet"})
        return self.registry.get(device_id)

    def start_environmental_measurements(self, device_id: str) -> dict[str, Any]:
        return self._submit(self._start_environmental(device_id), 30)

    async def _stop_environmental(self, device_id: str) -> dict[str, Any]:
        record = self.registry.get(device_id)
        sensor = record.get("environmental_sensor") or {}
        client = self._clients.get(device_id)
        if client and client.is_connected:
            try:
                await client.write_gatt_char(TI_HUMIDITY_CONFIG, b"\x00", response=True)
            finally:
                await client.stop_notify(TI_HUMIDITY_DATA)
        reading = sensor.get("last_reading")
        self.registry.update(device_id, environmental_sensor={**sensor, "active": False, "status": "disabled", "last_reading": {**reading, "stale": True} if reading else None})
        return self.registry.get(device_id)

    def stop_environmental_measurements(self, device_id: str) -> dict[str, Any]:
        return self._submit(self._stop_environmental(device_id), 20)

    # ── TI CC2650 SensorTag: IR temperature service (AA00) ──────────────────
    def _update_ir_reading(self, device_id: str, measurements: list[dict[str, Any]]) -> None:
        if not measurements: return
        by_type = {item["measurement_type"]: item for item in measurements}
        sensor = self.registry.get(device_id).get("ir_temperature_sensor") or {}
        reading = {
            "object_temperature_c": by_type.get("object_temperature", {}).get("value"),
            "ambient_temperature_c": by_type.get("ambient_temperature", {}).get("value"),
            "observed_at_utc": measurements[0]["observed_at_utc"],
            "source_raw_hex": measurements[0]["source_raw_hex"],
            "stale": False,
        }
        self.registry.update(device_id, ir_temperature_sensor={**sensor, "active": True, "status": "active", "last_reading": reading})

    async def _start_ir_temperature(self, device_id: str, period_hex: bytes = b"\x64", first_notification_timeout: float = 5.0) -> dict[str, Any]:
        if device_id not in self._clients or not self._clients[device_id].is_connected: await self._connect(device_id)
        record = self.registry.get(device_id)
        sensor = record.get("ir_temperature_sensor") or {}
        if not sensor.get("available"): raise PermissionError("TI_IR_TEMPERATURE_SENSOR_NOT_AVAILABLE")
        if sensor.get("active"): return record
        client = self._clients[device_id]
        first_notification = asyncio.Event()

        def callback(_, data: bytearray):
            measurements = self.parsers.parse_ti_ir_temperature_notification(device_id, bytes(data))
            for measurement in measurements: self.registry.add_measurement(device_id, measurement)
            self._update_ir_reading(device_id, measurements)
            first_notification.set()

        # See _start_environmental for why this update happens before
        # subscribing rather than after the period/config writes.
        self.registry.update(device_id, ir_temperature_sensor={**sensor, "active": True, "status": "starting"})
        await client.start_notify(TI_IR_TEMPERATURE_DATA, callback)
        await client.write_gatt_char(TI_IR_TEMPERATURE_PERIOD, period_hex, response=True)
        await client.write_gatt_char(TI_IR_TEMPERATURE_CONFIG, b"\x01", response=True)
        try:
            await asyncio.wait_for(first_notification.wait(), timeout=first_notification_timeout)
        except asyncio.TimeoutError:
            current = self.registry.get(device_id).get("ir_temperature_sensor") or {}
            self.registry.update(device_id, ir_temperature_sensor={**current, "status": "starting_no_data_yet"})
        return self.registry.get(device_id)

    def start_ir_temperature_measurements(self, device_id: str) -> dict[str, Any]:
        return self._submit(self._start_ir_temperature(device_id), 30)

    async def _stop_ir_temperature(self, device_id: str) -> dict[str, Any]:
        record = self.registry.get(device_id)
        sensor = record.get("ir_temperature_sensor") or {}
        client = self._clients.get(device_id)
        if client and client.is_connected:
            try:
                await client.write_gatt_char(TI_IR_TEMPERATURE_CONFIG, b"\x00", response=True)
            finally:
                await client.stop_notify(TI_IR_TEMPERATURE_DATA)
        reading = sensor.get("last_reading")
        self.registry.update(device_id, ir_temperature_sensor={**sensor, "active": False, "status": "disabled", "last_reading": {**reading, "stale": True} if reading else None})
        return self.registry.get(device_id)

    def stop_ir_temperature_measurements(self, device_id: str) -> dict[str, Any]:
        return self._submit(self._stop_ir_temperature(device_id), 20)

    async def _start_legacy_sensor(self, device_id: str, sensor_name: str) -> dict[str, Any]:
        if sensor_name not in self.LEGACY_SENSORS: raise KeyError(sensor_name)
        if device_id not in self._clients or not self._clients[device_id].is_connected: await self._connect(device_id)
        profile=self.registry.get(device_id); inventory=profile.get("sensor_inventory",{})
        if not inventory.get(sensor_name,{}).get("present"): raise PermissionError("SENSOR_NOT_PRESENT_IN_HARDWARE_PROFILE")
        spec=dict(self.LEGACY_SENSORS[sensor_name]); client=self._clients[device_id]
        if sensor_name=="barometer" and profile.get("probable_platform")=="CC2650":
            spec={"data":"f000aa41-0451-4000-b000-000000000000","config":"f000aa42-0451-4000-b000-000000000000","period":"f000aa44-0451-4000-b000-000000000000","enable":b"\x01"}
        states=dict(profile.get("sensor_states",{})); states[sensor_name]={"status":"configuring","active":False}; self.registry.update(device_id,sensor_states=states)
        if sensor_name=="barometer" and spec.get("calibration"):
            calibration=bytes(await client.read_gatt_char(spec["calibration"])); states[sensor_name]["calibration_raw_hex"]=calibration.hex(); states[sensor_name]["calibration_status"]="preserved_pending_validated_conversion"
        def callback(_,data:bytearray):
            measurements=self.parsers.parse_ti_legacy_sensor(device_id,sensor_name,spec["data"],bytes(data))
            for item in measurements:self.registry.add_measurement(device_id,item)
            current=dict(self.registry.get(device_id).get("sensor_states",{})); current[sensor_name]={**current.get(sensor_name,{}),"status":"active","active":True,"last_reading":measurements,"raw_hex":bytes(data).hex()}; self.registry.update(device_id,sensor_states=current)
        try:
            await client.start_notify(spec["data"],callback)
            if spec.get("period"): await client.write_gatt_char(spec["period"],b"\x64",response=True)
            if spec.get("config"): await client.write_gatt_char(spec["config"],spec["enable"],response=True)
        except Exception as error:
            states=dict(self.registry.get(device_id).get("sensor_states",{})); states[sensor_name]={**states.get(sensor_name,{}),"status":"failed","active":False,"error":f"{type(error).__name__}:{error}"}; self.registry.update(device_id,sensor_states=states); raise
        states=dict(self.registry.get(device_id).get("sensor_states",{})); states[sensor_name]={**states.get(sensor_name,{}),"status":"starting","active":True}; self.registry.update(device_id,sensor_states=states)
        return self.registry.get(device_id)

    def start_legacy_sensor(self,device_id:str,sensor_name:str)->dict[str,Any]: return self._submit(self._start_legacy_sensor(device_id,sensor_name),30)

    async def _stop_legacy_sensor(self,device_id:str,sensor_name:str)->dict[str,Any]:
        record=self.registry.get(device_id); spec=dict(self.LEGACY_SENSORS[sensor_name]); client=self._clients.get(device_id)
        if sensor_name=="barometer" and record.get("probable_platform")=="CC2650": spec={"data":"f000aa41-0451-4000-b000-000000000000","config":"f000aa42-0451-4000-b000-000000000000"}
        if client and client.is_connected:
            if spec.get("config"): await client.write_gatt_char(spec["config"],b"\x00",response=True)
            await client.stop_notify(spec["data"])
        states=dict(self.registry.get(device_id).get("sensor_states",{})); states[sensor_name]={**states.get(sensor_name,{}),"status":"disabled","active":False}; self.registry.update(device_id,sensor_states=states); return self.registry.get(device_id)

    def stop_legacy_sensor(self,device_id:str,sensor_name:str)->dict[str,Any]: return self._submit(self._stop_legacy_sensor(device_id,sensor_name),20)

    def start_supported_sensors(self,device_id:str)->dict[str,Any]:
        results=[]
        record=self.registry.get(device_id); present=record.get("sensor_inventory",{})
        for name in self.LEGACY_SENSORS:
            if not present.get(name,{}).get("present"): continue
            try:self.start_legacy_sensor(device_id,name);results.append({"sensor":name,"status":"started"})
            except Exception as error:results.append({"sensor":name,"status":"failed","error":f"{type(error).__name__}:{error}"})
        return {"device":self.registry.get(device_id),"results":results,"active":sum(x["status"]=="started" for x in results),"failed":sum(x["status"]=="failed" for x in results)}

    def inventory(self) -> dict[str, Any]:
        return {"schema_version": "1.0", "source": "native_ble_winrt", "devices": [{**item, "vendor": "unknown", "model": "unknown", "values_in_advertising": item.get("data_mode") == "ADVERTISEMENT_VALUE", "gatt_required": item.get("data_mode") in {"GATT_READ", "GATT_NOTIFY"}, "next_action": "inspect_gatt_characteristics" if not item.get("parser_available") else "validate_parser_against_reference"} for item in self.registry.list()]}
