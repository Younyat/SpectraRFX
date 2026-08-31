# USRP B200 Acquisition Chain — Technical Audit

Read-only technical audit of the real USRP B200 acquisition chain used by
the BLE-RFFI capture pipeline (the chain that produces every `CaptureRecord`
with `data_origin="REAL_B200"` behind the paper's dataset). No experiment
was executed, no artifact was changed, and no `.tex`, `.bib`, or PDF file
was touched. Every claim is sourced from code and real, already-persisted
campaign artifacts; anything not demonstrated is marked **NOT DOCUMENTED**
rather than inferred from general SoapySDR/UHD knowledge.

---

## 1. Scope note — two separate acquisition subsystems exist in this repository

This repository contains **two independent SDR acquisition code paths**.
Only one of them produces the BLE-RFFI dataset behind the paper.

- **BLE-RFFI capture path** (audited below): [`backend/tools/ble_sdr_capture_worker.py`](../../backend/tools/ble_sdr_capture_worker.py),
  driven through `BleCaptureJobManager`/`BleIqCaptureService`. Uses the
  **SoapySDR** Python bindings directly. This is the only path
  [`CaptureStage.build_capture_record()`](../../backend/app/modules/ble_rffi_studio/acquisition/capture_stage.py#L1-L11)
  reads from — its own docstring states it reads capture trees
  "written by `ble_sdr_capture_worker.py`", and every `CaptureRecord` it
  builds is tagged `data_origin="REAL_B200"`.
- **General-purpose spectrum tools** ("SpectraEase", documented in
  [`backend/README_SETUP.md`](../../backend/README_SETUP.md)): `backend/tools/spectrum_stream_worker.py`,
  `probe_uhd_device.py`, `capture_marker_band_iq.py`,
  `capture_and_demodulate_fm.py`, etc. These use **GNU Radio's UHD block**
  directly (`from gnuradio import uhd`, `uhd.usrp_source(...)`) —
  confirmed in [`probe_uhd_device.py:7,24-26`](../../backend/tools/probe_uhd_device.py#L7)
  and [`spectrum_stream_worker.py:15`](../../backend/tools/spectrum_stream_worker.py#L15).
  This is a **different** acquisition path, unrelated to the BLE-RFFI
  dataset. `README_SETUP.md`'s statement *"the active path is
  `uhd_gnuradio`"* ([`README_SETUP.md:312`](../../backend/README_SETUP.md#L312))
  describes this general spectrum-tools subsystem — its file-tree listing
  ([`README_SETUP.md:265-272`](../../backend/README_SETUP.md#L265-L272)) does
  not even mention `ble_sdr_capture_worker.py`. This is flagged here as a
  documentation-scope note, not corrected in that file (out of scope for
  this audit).

Everything below concerns the BLE-RFFI (SoapySDR) path only.

## 2. Real acquisition chain

```
UI (React, axios) → FastAPI route → BleCaptureJobManager → BleIqCaptureService
→ subprocess (RadioConda Python) → ble_sdr_capture_worker.py → SoapySDR (Python bindings)
→ SoapySDR "uhd" driver module (SoapyUHD) → USRP B200
```

| Layer | Real component | Function | Evidence |
|---|---|---|---|
| UI | [`frontend/src/app/services/bleApi.ts`](../../frontend/src/app/services/bleApi.ts) (`axios`) | Sends REST requests to the backend; never touches an SDR API | `bleApi.ts:1-20` — plain `axios.get`/`axios.post` calls against `/api/ble/...`; no native/SDR bindings in the frontend (structurally impossible from a browser) |
| Backend (routes) | [`ble_capture_routes.py`](../../backend/app/infrastructure/ble/capture/ble_capture_routes.py) (`POST /jobs`, `GET /devices`, ...) | HTTP endpoint layer, delegates to the job manager | `ble_capture_routes.py:15-75` (route declarations) |
| Backend (orchestration) | `BleCaptureJobManager.create()` / `_execute()` | Validates the request, resolves `device_args` via the device service, writes `request.json`, launches the capture subprocess on a thread | [`ble_capture_job_manager.py:58-73,142-153`](../../backend/app/infrastructure/ble/capture/ble_capture_job_manager.py#L58-L73) |
| Backend (worker launcher) | `BleIqCaptureService.capture()` | Spawns `ble_sdr_capture_worker.py capture` as a subprocess using the RadioConda Python interpreter, sets `SOAPY_SDR_PLUGIN_PATH` | [`ble_iq_capture_service.py:32-53`](../../backend/app/infrastructure/ble/capture/ble_iq_capture_service.py#L32-L53); composition root: [`ble_lab/module.py:54-74`](../../backend/app/modules/ble_lab/module.py#L54-L74) |
| SDR API | `import SoapySDR` inside `ble_sdr_capture_worker.py`'s `capture()` | Selects the device, sets frequency/sample rate/bandwidth/gain/antenna, opens the RX stream, reads I/Q | [`ble_sdr_capture_worker.py:597-634`](../../backend/tools/ble_sdr_capture_worker.py#L597-L634) |
| Driver/backend | SoapySDR's `uhd` driver module (SoapyUHD), selected via `driver=uhd` in `device_args` | Bridges SoapySDR's generic Device/Stream API to the USRP B200 | Real persisted `device_args:{"driver":"uhd","serial":"E3R04Z1B2"}` (`request.json`); real persisted `"device_driver":"uhd"` (`capture_manifest.json`) |
| Hardware | USRP B200 (Ettus Research), serial `E3R04Z1B2` | Performs the actual RF downconversion/sampling | Real `capture_manifest.json`: `"hardware":"B200"`, `"device_serial":"E3R04Z1B2"`, `"uhd_version":"UHD 4.8.0.0-release"` |

## 3. Direct SoapySDR usage — line-by-line

All inside `capture()`, [`backend/tools/ble_sdr_capture_worker.py`](../../backend/tools/ble_sdr_capture_worker.py):

| Step | Code | Line |
|---|---|---|
| Import | `import SoapySDR` | 408 |
| Device selection | `matches = list(SoapySDR.Device.enumerate(request["device_args"])); device = SoapySDR.Device(matches[0])` | 598, 603 |
| Sample rate | `device.setSampleRate(SoapySDR.SOAPY_SDR_RX, 0, request["sample_rate_sps"])` | 604 |
| Center frequency | `device.setFrequency(SoapySDR.SOAPY_SDR_RX, 0, request["center_frequency_hz"])` | 605 |
| Bandwidth | `device.setBandwidth(SoapySDR.SOAPY_SDR_RX, 0, request["bandwidth_hz"])` | 606 |
| Antenna | `device.setAntenna(SoapySDR.SOAPY_SDR_RX, 0, request["antenna"])` | 608 |
| Gain (manual/AGC) | `device.setGainMode(...)` / `device.setGain(SoapySDR.SOAPY_SDR_RX, 0, request["gain_db"])` | 610-613 |
| Hardware identity | `hw = str(device.getHardwareKey())`; `hw_info = dict(device.getHardwareInfo())` | 626-627 |
| Stream open | `stream = device.setupStream(SoapySDR.SOAPY_SDR_RX, wire_format, [0])` | 628 |
| Stream activate | `device.activateStream(stream)` | 631 |
| Sample read loop | `result = device.readStream(stream, [buffer], wanted, timeoutUs=1_000_000)` | 634 |
| Stream teardown | `device.deactivateStream(stream); device.closeStream(stream)` | 672-674, 720-724 |

This confirms directly: the application uses SoapySDR to select the
device, fix frequency/sample rate/bandwidth/gain, open the stream, and read
I/Q samples — the entire real-time RX path.

## 4. Driver/backend used for the B200, and its relation to UHD

**Driver key:** `"uhd"` — confirmed in two independent real, persisted
artifacts:
- `request.json` (real capture `BLE-IQ-0af07d179681`): `"device_args": {"driver": "uhd", "serial": "E3R04Z1B2"}`
- `capture_manifest.json` (real capture `BLE-IQ-0000c11f06c3`): `"device_driver": "uhd"`, `"hardware": "B200"`, `"device_serial": "E3R04Z1B2"`, `"uhd_version": "UHD 4.8.0.0-release"`

**Does the SoapySDR `uhd` driver module use UHD internally?** **Not
demonstrated by this repository's code.** That is a property of the
external SoapySDR/SoapyUHD project, not something this codebase proves —
this audit does not assert it from general SoapySDR architecture knowledge.

**Does the application call UHD directly, outside SoapySDR?** Yes, in two
confirmed places, both separate from the real-time RX path above:
- `uhd_config_info --version` — [`uhd_version()`, `ble_sdr_capture_worker.py:319-324`](../../backend/tools/ble_sdr_capture_worker.py#L319-L324), invoked only as a manifest-metadata fallback when building the post-capture manifest, never during the RF stream itself.
- `uhd_find_devices` — [`_probe_devices_with_uhd()`, `ble_sdr_device_service.py:173-219`](../../backend/app/infrastructure/ble/capture/ble_sdr_device_service.py#L173-L219), a non-Windows device-enumeration fallback. On Windows (`os.name == "nt"`), `list_devices()` never reaches this function (see §5).

**Dead code found, not part of the real chain:** [`backend/app/infrastructure/devices/uhd_device_adapter.py`](../../backend/app/infrastructure/devices/uhd_device_adapter.py)
defines a `UHDDeviceAdapter` class using the raw Python UHD bindings
directly (`import uhd; uhd.usrp.MultiUSRP(self.device_args)`). A
repository-wide search found **no instantiation of this class anywhere in
the backend** — it is not wired into `ble_lab/module.py`'s composition
root or any capture/job manager. It is not part of the real B200
acquisition chain.

## 5. Device listing vs. real capture — different code paths

`GET /devices` (`BleCaptureJobManager.capabilities()` → `BleSdrDeviceService.list_devices()`)
and the real `capture` action do **not** use the same enumeration
mechanism:

- On Windows, `list_devices()` tries [`_probe_devices_with_windows_pnp()`](../../backend/app/infrastructure/ble/capture/ble_sdr_device_service.py#L127-L171)
  first — it shells out to `pnputil /enum-devices /connected` and matches
  the USB pattern `VID_(2500|4C64)&PID_0020` (Ettus Research's USB
  VID/PID for the B2xx family), assuming `driver: "uhd"` **without
  verifying it through SoapySDR**. If this succeeds, the function returns
  immediately.
- If it fails and `os.name == "nt"`, `_probe_devices()` returns
  `NO_COMPATIBLE_SDR` directly (`ble_sdr_device_service.py:73-74`) —
  **the real SoapySDR `devices` probe subcommand is never invoked on
  Windows**, and the `_probe_devices_with_uhd()` (`uhd_find_devices`)
  fallback is only reached when `os.name != "nt"`.
- Only the **real capture** action (`capture()` in
  `ble_sdr_capture_worker.py`) is guaranteed to invoke SoapySDR, regardless
  of platform.

**Practical consequence:** on this Windows-based lab setup, the SoapySDR
version fields computed in `probe()` (`getLibVersion()`/`getAPIVersion()`/
`getABIVersion()`, lines 358-361) may rarely or never actually execute
during normal device-listing operation, since the Windows PnP path
short-circuits first.

## 6. Versions — what is demonstrated vs. NOT DOCUMENTED

| Item | Status | Evidence |
|---|---|---|
| UHD version | **Documented, real, persisted per capture.** Example: `"UHD 4.8.0.0-release"` | Real `capture_manifest.json` (`BLE-IQ-0000c11f06c3`), field `uhd_version`, populated by `hw_info.get("uhd_version") or hw_info.get("version") or uhd_version()` ([`ble_sdr_capture_worker.py:514`](../../backend/tools/ble_sdr_capture_worker.py#L514)). Which of the two possible sources (a SoapyUHD-populated `getHardwareInfo()` key, or the direct `uhd_config_info --version` subprocess) actually produced this specific value cannot be determined from the manifest alone — both are real, both are in the real code path. |
| SoapySDR library/API/ABI version | **NOT DOCUMENTED for any real capture.** Computed only inside `probe()` ([`ble_sdr_capture_worker.py:358-361`](../../backend/tools/ble_sdr_capture_worker.py#L358-L361)) and never written into `capture_manifest.json` or any other per-capture artifact. Per §5, on Windows this computation may not even run during normal `/devices` listing. |
| SoapyUHD module version (distinct from UHD/SoapySDR) | **NOT DOCUMENTED.** No code anywhere in this repository queries or persists a version distinct from the general SoapySDR library version. |
| RadioConda Python version (the interpreter executing `ble_sdr_capture_worker.py`) | **NOT DOCUMENTED.** No `sys.version`/`platform.python_version()` field is persisted in `capture_manifest.json`; the interpreter path itself (`BLE_SDR_PYTHON_PATH`/`RADIOCONDA_PYTHON`, default `C:\Users\Usuario\radioconda\python.exe` — [`ble_lab/module.py:54-56`](../../backend/app/modules/ble_lab/module.py#L54-L56)) is a runtime configuration value, not a per-capture recorded fact. |
| `backend_commit` (git SHA at capture time) | Persisted, but not always populated — the real example above shows `"backend_commit": null` for one completed capture, meaning the git-commit lookup ([`backend_commit()`, `ble_sdr_capture_worker.py:75-81`](../../backend/tools/ble_sdr_capture_worker.py#L75-L81)) can silently fail/return `None` with no recorded reason code. |

## 7. Real per-capture persistence — checked against an actual `capture_manifest.json`

Verified directly against a real, completed capture (`BLE-IQ-0000c11f06c3`):

| Data point | Persisted? | Field |
|---|---|---|
| SDR device selected (driver) | ✅ Yes | `device_driver: "uhd"` |
| Driver/backend used | ✅ Yes | `device_driver: "uhd"` (same field — no separate "backend" field exists) |
| SoapySDR version | ❌ **No** | absent from the manifest (see §6) |
| UHD version | ✅ Yes | `uhd_version: "UHD 4.8.0.0-release"` |
| B200 serial/identifier | ✅ Yes | `device_serial: "E3R04Z1B2"` (plus `device_serial_masked`) |
| Hardware key | ✅ Yes | `hardware: "B200"` (from `device.getHardwareKey()`) |
| Center frequency | ✅ Yes | `center_frequency_hz` |
| Sample rate | ✅ Yes | `sample_rate_sps` |
| Bandwidth | ✅ Yes | `bandwidth_hz` |
| Gain | ✅ Yes | `gain_configuration: {mode, gain_db}` |
| Sample format | ✅ Yes | `sample_format`, `cpu_format`, `otw_format`, `file_format` |
| USB mode | ✅ Yes | `usb_mode` (parsed from `capture.stderr.log`) |

## 8. Evidence paths

- Real acquisition worker: [`backend/tools/ble_sdr_capture_worker.py`](../../backend/tools/ble_sdr_capture_worker.py)
- Job orchestration: [`backend/app/infrastructure/ble/capture/ble_capture_job_manager.py`](../../backend/app/infrastructure/ble/capture/ble_capture_job_manager.py)
- Worker launcher / environment: [`backend/app/infrastructure/ble/capture/ble_iq_capture_service.py`](../../backend/app/infrastructure/ble/capture/ble_iq_capture_service.py)
- Device enumeration service: [`backend/app/infrastructure/ble/capture/ble_sdr_device_service.py`](../../backend/app/infrastructure/ble/capture/ble_sdr_device_service.py)
- HTTP routes: [`backend/app/infrastructure/ble/capture/ble_capture_routes.py`](../../backend/app/infrastructure/ble/capture/ble_capture_routes.py)
- Composition root / RadioConda paths: [`backend/app/modules/ble_lab/module.py:54-89`](../../backend/app/modules/ble_lab/module.py#L54-L89)
- Frontend API client: [`frontend/src/app/services/bleApi.ts`](../../frontend/src/app/services/bleApi.ts)
- Capture-record builder confirming this is the real dataset source: [`backend/app/modules/ble_rffi_studio/acquisition/capture_stage.py`](../../backend/app/modules/ble_rffi_studio/acquisition/capture_stage.py)
- Real, already-persisted example artifacts: `backend/app/infrastructure/persistence/storage/ble/iq_captures/BLE-IQ-0000c11f06c3/capture_manifest.json`, `backend/app/infrastructure/persistence/storage/ble/iq_captures/BLE-IQ-0af07d179681/request.json`
- Unrelated (general spectrum tools) subsystem, for scope contrast only: [`backend/tools/probe_uhd_device.py`](../../backend/tools/probe_uhd_device.py), [`backend/tools/spectrum_stream_worker.py`](../../backend/tools/spectrum_stream_worker.py), [`backend/README_SETUP.md`](../../backend/README_SETUP.md)
- Dead code, not part of the real chain: [`backend/app/infrastructure/devices/uhd_device_adapter.py`](../../backend/app/infrastructure/devices/uhd_device_adapter.py)

## 9. Proposed manifest improvements — NOT implemented, pending approval

The following are recommendations only. No code or manifest was changed to
produce this document; none of these will be implemented without explicit
approval.

- Persist `soapysdr_library_version`/`soapysdr_api_version`/`soapysdr_abi_version`
  into `capture_manifest.json` itself (currently computed only inside
  `probe()`, never written to any per-capture artifact).
- Record explicitly which of the two possible sources populated the
  persisted `uhd_version` value (a SoapyUHD `getHardwareInfo()` key vs. the
  direct `uhd_config_info --version` subprocess), removing the present
  ambiguity described in §6.
- Persist the RadioConda Python interpreter version
  (`platform.python_version()`) actually executing the worker for each
  capture.
- Persist a distinct SoapyUHD module version if/when such a value becomes
  queryable, rather than only the general SoapySDR library version.
- Persist a reason code when `backend_commit` resolves to `null`, rather
  than a silent `None` (a real completed capture already shows this gap).
- Persist the resolved RadioConda root / `SOAPY_SDR_PLUGIN_PATH` actually
  used at capture time (currently only a runtime environment default, not
  a per-capture recorded fact), so a specific capture's driver
  installation location remains reproducible even if the environment
  changes later.

---

No experiment was executed and no artifact, code, `.tex`, `.bib`, or PDF
was modified to produce this document.
