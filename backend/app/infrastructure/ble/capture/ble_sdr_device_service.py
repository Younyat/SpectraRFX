from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SdrProbeConfig:
    python_executable: Path
    tool_path: Path
    runtime_root: Path | None = None
    timeout_seconds: float = 90.0


class BleSdrDeviceService:
    def __init__(self, config: SdrProbeConfig) -> None:
        self.config = config
        self._private_args: dict[str, dict[str, str]] = {}
        self._public_devices: dict[str, dict[str, Any]] = {}
        self._last_successful_probe_monotonic = 0.0
        self._last_probe_monotonic = 0.0
        self._last_probe_response: dict[str, Any] | None = None
        self._probe_lock = threading.RLock()
        self.last_diagnostics: dict[str, Any] = {}

    def _environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        root = self.config.runtime_root
        if root:
            system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
            environment["PATH"] = os.pathsep.join(str(path) for path in (root / "Library" / "bin", root / "Scripts", root, system32))
            environment["SOAPY_SDR_PLUGIN_PATH"] = str(root / "Library" / "lib" / "SoapySDR" / "modules0.8")
        return environment

    @staticmethod
    def _copy_response(value: dict[str, Any]) -> dict[str, Any]:
        # Device capability payloads contain only JSON values. A JSON roundtrip
        # prevents callers from mutating the cache shared by concurrent views.
        return json.loads(json.dumps(value))

    def list_devices(self, force_probe: bool = False, maximum_age_seconds: float = 30.0) -> dict[str, Any]:
        """Return one recent enumeration unless a physical refresh is requested.

        UHD opens and initializes a B200 while enumerating it. The BLE dashboard
        has more than one consumer of this endpoint, so probing for every read
        needlessly resets the receiver and floods the operator log. The cache is
        deliberately short and every capture still performs a fresh preflight.
        """
        with self._probe_lock:
            recent = time.monotonic() - self._last_probe_monotonic <= maximum_age_seconds
            if not force_probe and recent and self._last_probe_response is not None:
                return self._copy_response(self._last_probe_response)
            response = self._probe_devices()
            self._last_probe_monotonic = time.monotonic()
            self._last_probe_response = self._copy_response(response)
            return self._copy_response(response)

    def _probe_devices(self) -> dict[str, Any]:
        if not self.config.python_executable.is_file() or not self.config.tool_path.is_file():
            return self._unavailable("SDR_RUNTIME_UNAVAILABLE", "The configured SDR runtime is unavailable.")
        pnp_response = self._probe_devices_with_windows_pnp()
        if pnp_response is not None:
            return pnp_response
        if os.name == "nt":
            return self._unavailable("NO_COMPATIBLE_SDR", "No compatible SDR receiver was detected.")
        uhd_response = self._probe_devices_with_uhd()
        if uhd_response is not None:
            return uhd_response
        try:
            result = subprocess.run(
                [str(self.config.python_executable), str(self.config.tool_path), "devices"],
                capture_output=True, text=True, timeout=self.config.timeout_seconds, check=False, env=self._environment(),
            )
        except Exception as error:
            self.last_diagnostics = {"classification": "SDR_PROBE_EXCEPTION", "exception": repr(error)}
            logging.getLogger(__name__).warning("SoapySDR probe could not be executed: %r", error)
            return self._unavailable("SDR_PROBE_FAILED", "The SDR probe could not be executed.")
        if result.returncode != 0:
            self.last_diagnostics = {
                "classification": "SDR_PROBE_NONZERO_EXIT",
                "returncode": result.returncode,
                "stderr": result.stderr[-8192:],
                "stdout": result.stdout[-2048:],
            }
            if result.stderr:
                logging.getLogger(__name__).warning("SoapySDR probe failed: %s", result.stderr[-8192:])
            return self._unavailable("SDR_PROBE_FAILED", "The SDR probe did not complete successfully.")
        try:
            response = json.loads(result.stdout); raw_devices = response.get("devices", [])
            self.last_diagnostics = {"classification": "SOAPY_DEVICE_ENUMERATION_EMPTY" if not raw_devices else "OK",
                                     "runtime": response.get("runtime", {}), "stderr": result.stderr[-8192:]}
            if result.stderr: logging.getLogger(__name__).warning("SoapySDR probe diagnostics: %s", result.stderr[-8192:])
        except Exception:
            return self._unavailable("SDR_PROBE_INVALID_RESPONSE", "The SDR probe returned invalid data.")
        devices = []
        self._private_args.clear()
        for raw in raw_devices:
            args = {str(k): str(v) for k, v in raw.pop("device_args", {}).items()}
            stable_identity = {key: args[key] for key in ("driver", "serial") if args.get(key)} or args
            identity = json.dumps(stable_identity, sort_keys=True, separators=(",", ":"))
            device_id = "sdr-" + hashlib.sha256(identity.encode()).hexdigest()[:16]
            # Enumeration metadata such as label/name/product is descriptive,
            # not a stable set of constructor arguments. UHD reliably reopens
            # the same physical receiver using its driver and serial.
            connection_args = {key: args[key] for key in ("driver", "serial") if args.get(key)}
            self._private_args[device_id] = connection_args or args
            raw["device_id"] = device_id
            raw["serial_masked"] = self._mask(raw.get("serial"))
            raw.pop("serial", None)
            raw["available"] = True
            devices.append(raw)
        if not devices:
            return self._unavailable("NO_COMPATIBLE_SDR", "No compatible SDR receiver was detected.")
        self._public_devices = {item["device_id"]: dict(item) for item in devices}
        self._last_successful_probe_monotonic = time.monotonic()
        return {"available": True, "devices": devices}

    def _probe_devices_with_windows_pnp(self) -> dict[str, Any] | None:
        if os.name != "nt":
            return None
        try:
            result = subprocess.run(
                ["pnputil", "/enum-devices", "/connected"],
                capture_output=True,
                text=True,
                timeout=20.0,
                check=False,
            )
        except FileNotFoundError:
            return None
        except Exception as error:
            self.last_diagnostics = {"classification": "WINDOWS_PNP_PROBE_EXCEPTION", "exception": repr(error)}
            logging.getLogger(__name__).warning("Windows PnP SDR probe could not be executed: %r", error)
            return self._unavailable("SDR_PROBE_FAILED", "The SDR probe could not be executed.")
        output = f"{result.stdout}\n{result.stderr}"
        if result.returncode != 0:
            self.last_diagnostics = {
                "classification": "WINDOWS_PNP_PROBE_NONZERO_EXIT",
                "returncode": result.returncode,
                "stderr": result.stderr[-8192:],
                "stdout": result.stdout[-2048:],
            }
            return self._unavailable("SDR_PROBE_FAILED", "The SDR probe did not complete successfully.")
        serials = []
        for match in re.finditer(r"USB\\VID_(?:2500|4C64)&PID_0020\\([^\r\n]+)", output, re.IGNORECASE):
            serial = match.group(1).strip()
            if serial and serial not in serials:
                serials.append(serial)
        devices = [self._b200_device(serial) for serial in serials]
        self.last_diagnostics = {
            "classification": "OK" if devices else "WINDOWS_PNP_ENUMERATION_EMPTY",
            "runtime": {"sdr_runtime": "windows_pnputil", "device_probe_succeeded": bool(devices)},
            "stderr": result.stderr[-8192:],
        }
        if not devices:
            return self._unavailable("NO_COMPATIBLE_SDR", "No compatible SDR receiver was detected.")
        self._private_args = {item["device_id"]: {"driver": "uhd", "serial": item["_serial"]} for item in devices}
        for item in devices:
            item.pop("_serial", None)
        self._public_devices = {item["device_id"]: dict(item) for item in devices}
        self._last_successful_probe_monotonic = time.monotonic()
        return {"available": True, "devices": devices}

    def _probe_devices_with_uhd(self) -> dict[str, Any] | None:
        try:
            result = subprocess.run(
                ["uhd_find_devices"],
                capture_output=True,
                text=True,
                timeout=min(self.config.timeout_seconds, 60.0),
                check=False,
                env=self._environment(),
            )
        except FileNotFoundError:
            return None
        except Exception as error:
            self.last_diagnostics = {"classification": "UHD_PROBE_EXCEPTION", "exception": repr(error)}
            logging.getLogger(__name__).warning("UHD probe could not be executed: %r", error)
            return self._unavailable("SDR_PROBE_FAILED", "The SDR probe could not be executed.")
        output = f"{result.stdout}\n{result.stderr}"
        if result.returncode != 0 and "No UHD Devices Found" not in output:
            self.last_diagnostics = {
                "classification": "UHD_PROBE_NONZERO_EXIT",
                "returncode": result.returncode,
                "stderr": result.stderr[-8192:],
                "stdout": result.stdout[-2048:],
            }
            return self._unavailable("SDR_PROBE_FAILED", "The SDR probe did not complete successfully.")
        serials = [match.group(1).strip() for match in re.finditer(r"serial:\s*([^\r\n]+)", output, re.IGNORECASE)]
        products = [match.group(1).strip() for match in re.finditer(r"product:\s*([^\r\n]+)", output, re.IGNORECASE)]
        devices = []
        self._private_args.clear()
        for index, serial in enumerate(serials):
            product = products[index] if index < len(products) else "B200"
            args = {"driver": "uhd", "serial": serial}
            device = self._b200_device(serial, product)
            device_id = str(device["device_id"])
            self._private_args[device_id] = args
            device.pop("_serial", None)
            devices.append(device)
        self.last_diagnostics = {
            "classification": "OK" if devices else "UHD_DEVICE_ENUMERATION_EMPTY",
            "runtime": {"sdr_runtime": "uhd_find_devices", "device_probe_succeeded": bool(devices)},
            "stderr": result.stderr[-8192:],
        }
        if not devices:
            return self._unavailable("NO_COMPATIBLE_SDR", "No compatible SDR receiver was detected.")
        self._public_devices = {item["device_id"]: dict(item) for item in devices}
        self._last_successful_probe_monotonic = time.monotonic()
        return {"available": True, "devices": devices}

    def _b200_device(self, serial: str, product: str = "B200") -> dict[str, Any]:
        args = {"driver": "uhd", "serial": serial}
        device_id = "sdr-" + hashlib.sha256(json.dumps(args, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]
        return {
            "_serial": serial,
            "device_id": device_id,
            "driver": "uhd",
            "label": f"{product} {serial}".strip(),
            "serial_masked": self._mask(serial),
            "rx_channels": 1,
            "frequency_ranges_hz": [{"minimum": 42_000_000.0, "maximum": 6_008_000_000.0}],
            "sample_rate_ranges_sps": [{"minimum": 31_250.0, "maximum": 16_000_000.0}],
            "bandwidth_ranges_hz": [{"minimum": 200_000.0, "maximum": 56_000_000.0}],
            "gain_elements": ["PGA"],
            "antenna_options": ["TX/RX", "RX2"],
            "stream_formats": ["CS8", "CS16", "CF32", "CF64"],
            "clock_sources": ["internal", "external", "gpsdo"],
            "time_sources": ["none", "internal", "external", "gpsdo"],
            "available": True,
        }

    def cached_device(self, device_id: str, maximum_age_seconds: float = 10.0) -> dict[str, Any] | None:
        if time.monotonic() - self._last_successful_probe_monotonic > maximum_age_seconds:
            return None
        value = self._public_devices.get(device_id)
        return dict(value) if value else None

    def resolve_device(self, requested_device_id: str | None = None, maximum_age_seconds: float = 10.0) -> dict[str, Any]:
        """Resolve one receiver from one probe/cache snapshot.

        Browser-visible IDs are hints, never hardware authority. When exactly
        one SDR is present it is safe to select it even if a previous probe
        produced another ID. Multiple receivers still require an exact ID.
        """
        recent = time.monotonic() - self._last_successful_probe_monotonic <= maximum_age_seconds
        devices = list(self._public_devices.values()) if recent else []
        if not devices:
            probe = self.list_devices(force_probe=True)
            devices = list(probe.get("devices", []))
            if not devices:
                raise ValueError(f"UNKNOWN_OR_UNAVAILABLE_SDR_DEVICE:{probe.get('reason_code','NO_COMPATIBLE_SDR')}")
        exact = next((item for item in devices if item.get("device_id") == requested_device_id), None)
        if exact:
            return dict(exact)
        if len(devices) == 1:
            return dict(devices[0])
        raise ValueError("UNKNOWN_OR_UNAVAILABLE_SDR_DEVICE:MULTIPLE_RECEIVERS_REQUIRE_EXACT_ID")

    def private_args(self, device_id: str) -> dict[str, str]:
        if device_id not in self._private_args:
            self.list_devices()
        if device_id not in self._private_args:
            raise ValueError("UNKNOWN_SDR_DEVICE")
        return dict(self._private_args[device_id])

    @staticmethod
    def _mask(serial: Any) -> str | None:
        value = str(serial or "").strip()
        return None if not value else ("*" * max(0, len(value) - 4) + value[-4:])

    @staticmethod
    def _unavailable(code: str, message: str) -> dict[str, Any]:
        return {"available": False, "reason_code": code, "message": message, "devices": []}
