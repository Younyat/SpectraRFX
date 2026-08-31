# Conventional BLE Adapter — Technical Audit

Read-only technical audit of the conventional Bluetooth/BLE adapter used in
parallel with the USRP B200 during hybrid campaigns. No experiment was
executed to produce this document, no artifact was changed, and no `.tex`,
`.bib`, or PDF file was touched. Every claim below is sourced directly from
code, dependency locks, and persisted campaign artifacts; anything not found
is marked **NOT DOCUMENTED** rather than inferred.

---

## 1. Adapter identity

| Field | Value |
|---|---|
| Manufacturer | **NOT DOCUMENTED** |
| Commercial model | **NOT DOCUMENTED** |
| Bluetooth chipset/controller | **NOT DOCUMENTED** |
| USB VID/PID | **NOT DOCUMENTED** |
| Hardware revision | **NOT DOCUMENTED** |
| Adapter firmware | **NOT DOCUMENTED** |
| Integrated vs. USB | **NOT DOCUMENTED** |
| Antenna | **NOT DOCUMENTED** |

The only code that queries the adapter is `_adapter_status()`
([`ble_native_job_manager.py:74-84`](../../backend/app/infrastructure/ble/native/ble_native_job_manager.py#L74-L84)):
it calls `winrt.windows.devices.bluetooth.BluetoothAdapter.get_default_async()`
— i.e. it asks the OS for "the default Bluetooth adapter" — and returns only
`{"available": true/false, "backend": "winrt", "scan_supported": true,
"gatt_supported": true}`. No hardware descriptor (VID/PID, manufacturer
string, chipset) is enumerated or persisted anywhere in this code path. No
other config file, capture manifest, or log was found that records adapter
hardware identity.

## 2. OS and Bluetooth stack

| Field | Value | Evidence |
|---|---|---|
| OS | Windows | Docstring: *"Isolated WinRT/Bleak scanner... The Windows BLE stack can terminate the hosting Python process..."* ([`ble_native_scan_worker.py:1-4`](../../backend/tools/ble_native_scan_worker.py#L1-L4)); `winrt.windows.devices.bluetooth` import |
| Windows version/build | **NOT DOCUMENTED** | No manifest in this pipeline persists `platform.platform()`. Contrast: `ble_gate2a2_offline_worker.py:201` and `ble_gate1b_replay_worker.py:168` write an `environment_manifest.json` with `python_version`/`platform` — that pattern does **not** exist for native BLE scanning |
| Library/API | Bleak | `from bleak import BleakScanner` ([`ble_native_scan_worker.py:79`](../../backend/tools/ble_native_scan_worker.py#L79)) |
| Bleak version | **0.22.3** | Pinned in [`backend/requirements.txt:34`](../../backend/requirements.txt#L34) and [`backend/requirements.dev-windows.txt:31`](../../backend/requirements.dev-windows.txt#L31); also persisted as a literal in every real session's `scan_manifest.json` ([`ble_native_job_manager.py:104`](../../backend/app/infrastructure/ble/native/ble_native_job_manager.py#L104)). This is a hardcoded string, not an `importlib.metadata` runtime query — it reflects the lockfile, not an active per-session check |
| Backend | WinRT | `bleak.backends.winrt.util.assert_mta()` ([`ble_native_scan_worker.py:76-78`](../../backend/tools/ble_native_scan_worker.py#L76-L78)); `winrt.windows.devices.bluetooth.BluetoothAdapter` ([`ble_native_job_manager.py:78`](../../backend/app/infrastructure/ble/native/ble_native_job_manager.py#L78)); persisted field `"backend":"winrt"` |
| Python version | **NOT DOCUMENTED** | No `pyproject.toml` `python_requires`, no `.python-version` in the repository; no artifact in this path persists `sys.version`. Runs under the same interpreter as the backend process (`sys.executable`, [`ble_native_job_manager.py:110`](../../backend/app/infrastructure/ble/native/ble_native_job_manager.py#L110)), but the concrete version is never recorded |
| `winrt` package version | **NOT DOCUMENTED** — transitive dependency of Bleak's WinRT backend, not independently pinned in `requirements.txt` |

## 3. Exact function of the adapter

Confirmed by code: the adapter only performs passive advertising detection
via `BleakScanner(detection_callback=callback)`
([`ble_native_scan_worker.py:141-142`](../../backend/tools/ble_native_scan_worker.py#L141-L142)),
delivering address/name/manufacturer_data/service_data/service_uuids/rssi/
tx_power/connectable already normalized by Bleak; the callback generates the
host-side timestamps.

In the real automated hybrid-campaign flow (`BleHybridCampaignManager._run`,
[`ble_hybrid_campaign_manager.py:225-235`](../../backend/app/infrastructure/ble/ble_hybrid_campaign_manager.py#L225-L235))
the adapter never performs a GATT connection — only `start_scan`/`stop_scan`
are invoked. GATT connection capability (TI CC2650 sensor reads) exists on
the manager (lines 258-470) but is not part of the BLE+B200 hybrid flow.

**Explicit confirmation:** the BLE adapter does **not** provide the I/Q
samples used for RFFI. No I/Q, raw-sample, or waveform field appears in
`ble_native_scan_worker.py` or in the `devices.json`/`advertisements.jsonl`
schema. The B200 is the only I/Q source, captured by a fully separate
component (`self.capture.create(request)`, line 228), orchestrated in
parallel but independently from the native BLE scan. The conventional
adapter acts as an auxiliary, application-level logical observation, used
to corroborate/associate packets recovered by the B200 — never as the RF
signal source under analysis.

## 4. Real BLE scan configuration

| Parameter | Real state |
|---|---|
| Active/passive | Not configured by the application — `BleakScanner(detection_callback=callback)` passes no `scanning_mode` → governed by Bleak/WinRT's own default, **not independently verified in this repository** |
| Scan interval/window | Not configured — no `interval`/`window` parameter is passed |
| Address/name/UUID filters | None — the scanner receives no filter |
| Duplicate filtering | **Explicitly disabled**: `"deduplication": False` persisted literally in `scan_manifest.json` ([`ble_native_job_manager.py:104`](../../backend/app/infrastructure/ble/native/ble_native_job_manager.py#L104)); confirmed by behavior — every callback appends a new line to `advertisements.jsonl` without deduplication |
| Callback/event types received | Only Bleak's advertising `detection_callback` |
| Channel pinning (37/38/39) | The application has **no parameter** to fix a channel — no "channel" field exists anywhere in the native scan; standard BLE central-role channel hopping is managed entirely by the Windows WinRT stack/driver, outside this code's visibility |
| PHY configuration | Not exposed — no PHY parameter anywhere in the code |
| Legacy vs. extended advertising | Not distinguished — the code itself states the limitation: `"raw_advertising_pdu_available": False, "raw_advertising_unavailable_reason": "bleak_backend_exposes_normalized_fields_only"` (identical in `ble_native_scan_worker.py` and `ble_device_registry.py`) |

**Explicit confirmation:** yes, WinRT/Bleak fully abstracts scan mode,
interval, window, channel, PHY, and legacy/extended handling, and the
application has no way to control them at this API level — this is a
structural limit of the abstraction layer used, not a configuration
omission.

## 5. Timestamps

**Generation point:** inside Python's `callback()` function, on the first
line of its body (`now = utc_now()`) — i.e. at the moment Bleak/WinRT
invokes the application's callback, **after** whatever internal WinRT/
Bluetooth-driver/Windows-BLE-stack processing already occurred, which is
opaque to this code.

**Two timestamps, generated at the same callback-invocation instant:**
- `timestamp_callback_utc` — wall-clock UTC, ISO 8601 (`datetime.now(timezone.utc).isoformat()`, `"Z"` suffix)
- `timestamp_callback_monotonic_ns` — `time.monotonic_ns()`, a monotonic counter with no defined epoch, valid only for measuring intervals

**Resolution:** nanosecond-nominal for the monotonic counter; the real
resolution of Windows' wall clock is not independently verified in this
code.

**Relation to actual RF reception:** the timestamp does **not** represent
the RF-reception instant of the advertising PDU — it represents the instant
the Python application layer receives the WinRT stack's notification. No
field measures or corrects for the buffering between real reception by the
Bluetooth chip and the Python callback's execution; that buffering is
unmeasured and uncharacterized.

**SDR/B200 side — key finding:** the "packet timestamp" used in
association is **not** a per-packet hardware timestamp. It is arithmetically
reconstructed:
```
packet_time = start + sample_start / sample_rate_sps
```
([`ble_correlate_session.py:20,22`](../../backend/tools/ble_correlate_session.py#L20)),
where `start = epoch(capture_manifest["created_at_utc"])` is the B200
capture's creation/start instant — a host wall-clock timestamp generated by
the backend when the capture is created, not a B200/UHD hardware timestamp.
This assumes the sample counter began exactly at `created_at_utc`, with no
correction for UHD/USB streaming start-up latency.

**Explicit cross-domain synchronization:** **none exists** — no PPS, no GPS,
no dedicated synchronization protocol — between the BLE adapter, the host,
UHD/B200, and the I/Q file. Association relies entirely on both timestamps
(BLE callback and reconstructed B200 packet time) being anchored to the
same host wall clock, compared against a fixed tolerance window:
```python
delta = (epoch(native["timestamp_callback_utc"]) - packet_time) * 1000
if abs(delta) > window_ms: continue   # window_ms = 250 in real use
```
([`ble_correlate_session.py:25-26`](../../backend/tools/ble_correlate_session.py#L25-L26),
invoked with `--window-ms 250` in
[`ble_hybrid_campaign_manager.py:252`](../../backend/app/infrastructure/ble/ble_hybrid_campaign_manager.py#L252)).
The ±250 ms tolerance is an empirically chosen value to absorb the
uncharacterized buffering/latency on both paths — not the result of a real
synchronization measurement.

## 6. Real per-event field schema

**(a) `devices.json`** — per-device aggregate, deduplicated by `device_id`,
last-seen-wins for most fields: `device_id, address, address_type(="unknown"
literal), local_name, rssi_dbm, tx_power_dbm, manufacturer_data,
service_data, service_uuids, raw_advertising_bytes(=None),
raw_advertising_pdu_available(=False), raw_advertising_unavailable_reason,
first_seen_utc, last_seen_utc, observation_count, data_mode,
parser_available, connection, advertising_seen, advertised_connectable,
windows_device_resolved, connection_attempted, connection_established,
gatt_discovery_attempted, gatt_discovery_succeeded, profile_recognized,
sensor_parser_supported, measurement_available, notification_supported,
native_state, native_status, gatt_diagnostics, scan_session_id,
measurements, gatt_services`.

**(b) `advertisements.jsonl`** — append-only, one line per callback, not
deduplicated (the real per-event ground-truth log): `schema_version
("ble-native-observation-v1"), native_observation_id, scan_session_id,
timestamp_callback_utc, timestamp_callback_monotonic_ns, address,
address_type, local_name, rssi_dbm, tx_power_dbm, connectable,
manufacturer_data, service_data, service_uuids`.

Every field above is **actually persisted** during real campaigns (both
writers run unconditionally on every real callback,
[`ble_native_scan_worker.py:172-176`](../../backend/tools/ble_native_scan_worker.py#L172-L176))
— not merely available from the API without being written. No commonly
available Bleak `AdvertisementData` field was found to be exposed but not
persisted.

`address_type` is always the fixed literal `"unknown"` — a constant string
in the code, not a value resolved by the backend. Real BLE address type
(public/random/resolvable-private/etc.) is neither determined nor persisted
anywhere in this pipeline.

## 7. RSSI / TX power

`rssi_dbm` (from `advertisement.rssi`) and `tx_power_dbm` (from
`advertisement.tx_power`) are captured and persisted in both schemas above,
in dBm.

**Confirmed usage:** diagnostic/informational only, per device. **Not**
used in the BLE↔SDR association logic —
[`ble_correlate_session.py:22-34`](../../backend/tools/ble_correlate_session.py#L22-L34)
uses exclusively `address_match` and `payload_match` plus the time window;
RSSI is never read or compared there. **Not** one of the ten engineered
RFFI-classifier feature descriptors (`mean_power_dbfs, std_power_db,
mean_abs_amplitude, std_abs_amplitude, spectral_centroid_hz,
spectral_bandwidth_hz, cfo_estimate_hz, papr_db, amplitude_kurtosis,
amplitude_skewness`), which are computed exclusively from B200 I/Q.

**Explicit clarification:** the conventional Bluetooth adapter's RSSI is
not part of the ten B200-derived RFFI classifier features; its only
confirmed role in code is diagnostic/logging.

## 8. Temporal relationship with the B200

Single orchestrator: `BleHybridCampaignManager._run()`
([`ble_hybrid_campaign_manager.py:225-235`](../../backend/app/infrastructure/ble/ble_hybrid_campaign_manager.py#L225-L235)),
run on one thread (line 224).

**Confirmed real sequence:**
1. `self.native.start_scan(sid)` is called first (line 227). This call
   **blocks** until `worker_status.json` reports `state=="running"` (polled
   every 0.1 s, default 60 s timeout —
   [`ble_native_job_manager.py:114-131`](../../backend/app/infrastructure/ble/native/ble_native_job_manager.py#L114-L131)),
   or raises if it fails.
2. Only then is the B200 capture job created: `job = self.capture.create(request)`
   (line 228).
3. The thread polls every 0.5 s until the capture reaches a terminal state
   (lines 229-231).
4. Only then is the native scan stopped: `self.native.stop_scan()` (line 232).

There is no shared start barrier and no hardware-triggered common
timestamp — the only guarantee is **ordering** (native scan is active before
and throughout the whole B200 capture), not simultaneous start. The real
interval between "scan confirmed running" and "the B200 capture actually
begins writing samples" is neither measured nor explicitly persisted —
it is only reconstructable post hoc by comparing
`scan_manifest.json.started_at_utc`/`started_monotonic_ns` against
`capture_manifest.json.created_at_utc`, both host wall-clock timestamps.

**Explicit confirmation:** there is no RF-level synchronization between the
BLE adapter and the B200 — the relationship is purely host-clock proximity
and ordering, managed by Python code sequencing, with no shared trigger,
PPS, or common hardware clock.

## 9. Exact evidence paths

- BLE scanner code: [`backend/tools/ble_native_scan_worker.py`](../../backend/tools/ble_native_scan_worker.py)
- Scan lifecycle orchestrator: [`backend/app/infrastructure/ble/native/ble_native_job_manager.py`](../../backend/app/infrastructure/ble/native/ble_native_job_manager.py)
- Device registry: [`backend/app/infrastructure/ble/native/ble_device_registry.py`](../../backend/app/infrastructure/ble/native/ble_device_registry.py)
- Hybrid BLE+B200 campaign orchestrator: [`backend/app/infrastructure/ble/ble_hybrid_campaign_manager.py`](../../backend/app/infrastructure/ble/ble_hybrid_campaign_manager.py)
- Association/correlation script (timestamp comparison): [`backend/tools/ble_correlate_session.py`](../../backend/tools/ble_correlate_session.py)
- Dependency pin: [`backend/requirements.txt:34`](../../backend/requirements.txt#L34), [`backend/requirements.dev-windows.txt:31`](../../backend/requirements.dev-windows.txt#L31) (`bleak==0.22.3`)
- Real per-scan-session artifacts (under `scans/<scan_session_id>/`): `scan_manifest.json`, `worker_status.json`, `devices.json`, `advertisements.jsonl`, `worker.stdout.log`, `worker.stderr.log`, `stop.requested`
- Real per-hybrid-campaign artifacts (under `BLE-HYBRID-<timestamp>-<hex>/`): `session_manifest.json`, `correlation/matches.jsonl`, `correlation/unmatched_native.jsonl`, `correlation/unmatched_sdr.jsonl`, `correlation/decoded_packets.jsonl`, `correlation/metrics.json`
- Cumulative (not per-session) device registry: `device_registry.json`

## 10. Reproducibility table

| Row | Real value | Evidence / path |
|---|---|---|
| Adapter manufacturer/model | NOT DOCUMENTED | `ble_native_job_manager.py:74-84` (only code that queries the adapter; captures no hardware identity) |
| Chipset | NOT DOCUMENTED | same |
| VID/PID | NOT DOCUMENTED | same |
| OS | Windows (version/build NOT DOCUMENTED) | `ble_native_scan_worker.py:1-4`; `ble_native_job_manager.py:78` |
| BLE library/API | Bleak | `ble_native_scan_worker.py:79` |
| Library version | `bleak==0.22.3` | `backend/requirements.txt:34`; `backend/requirements.dev-windows.txt:31`; persisted in `scan_manifest.json` |
| Backend | WinRT | `ble_native_scan_worker.py:76-78`; `ble_native_job_manager.py:76-81` (`"backend":"winrt"`) |
| Scan mode | Not configured by the app (Bleak/WinRT default, unverified) | `ble_native_scan_worker.py:142` |
| Scan duration | Tied to the B200 capture lifecycle (starts before, stops after); no fixed duration of its own | `ble_hybrid_campaign_manager.py:225-235` |
| Filters | None; deduplication explicitly disabled (`deduplication:false`) | `ble_native_job_manager.py:104`; `ble_native_scan_worker.py:142` |
| Timestamp source | Host wall clock + host monotonic clock, generated at Python callback invocation (not hardware/driver level) | `ble_native_scan_worker.py` (`callback()`) |
| Timestamp resolution | Nanosecond-nominal (monotonic_ns); real wall-clock resolution unverified | `ble_native_scan_worker.py` |
| RSSI persisted | Yes, dBm, diagnostic only — not used in association or in the RFFI classifier | `ble_native_scan_worker.py`; `ble_correlate_session.py:22-34` |
| Relation to B200 | Sequential host orchestration (BLE starts and confirms running first; stops only after B200 capture finishes); no shared start barrier or RF synchronization; later association via ±250 ms window over host wall-clock timestamps | `ble_hybrid_campaign_manager.py:225-235,252`; `ble_correlate_session.py:18-26` |

---

No experiment was executed and no artifact, code, `.tex`, `.bib`, or PDF was
modified to produce this document.
