# Real-Time Spectrum / Device Visualization — Technical Audit

**Audit generated:** 2026-08-25T00:00:00Z (UTC), from direct inspection of code (file/line cited
throughout) and two real, already-committed screenshots. No experiment was executed, no artifact was
changed, and no `.tex`, `.bib`, or PDF file was touched. Nothing below is inferred from general domain
knowledge — every claim cites an exact file/line or is marked **NOT DOCUMENTED** / **NOT MEASURED**.

## Objective

Determine, precisely, what this platform can show *today* about a live RF/BLE observation overlaid on
a spectrum display — and separate that honestly from a validated RF-fingerprint (RFFI) enrolled-device
identification. Three structurally different capabilities exist under names that are easy to conflate
in prose; this document keeps them apart.

---

## 1. Two independent SDR subsystems, confirmed at the UI and API level

Already established in
[`B200_ACQUISITION_CHAIN_TECHNICAL_AUDIT.md`](B200_ACQUISITION_CHAIN_TECHNICAL_AUDIT.md) at the
acquisition-code level; this section adds direct UI/runtime confirmation:

- The real screenshot [`readme_img/live_monitor_rf_intelligence_overlay.png`](../../readme_img/live_monitor_rf_intelligence_overlay.png)
  shows the Live Monitor's own telemetry panel reporting **`Driver: uhd_gnuradio`** directly in the UI.
- That string is produced only by the general spectrum-tools codebase — never by the BLE-RFFI/SoapySDR
  path, whose persisted `device_driver` field is literally `"uhd"` (SoapySDR device args), not
  `"uhd_gnuradio"` — confirmed in `device_controller.py`, `container.py`,
  `backend/tools/spectrum_stream_worker.py`, `backend/tools/probe_uhd_device.py`, and
  `backend/README.md:9` ("Driver reported by the API: `uhd_gnuradio`").
- `backend/tools/spectrum_stream_worker.py` opens the B200 via GNU Radio's `uhd.usrp_source` directly
  (real Python import, confirmed in the earlier B200 audit) — a continuous, persistent subprocess, not
  a per-capture invocation.

**Exclusivity between the two subsystems — a real, one-directional asymmetry, not a clean mutex:**
- Subsystem 1 (BLE-RFFI capture) uses a real, cross-process, file-based lock —
  `SdrDeviceArbiter` (`backend/app/modules/ble_rffi_studio/hardware/sdr_device_arbiter.py`) — acquired
  by `campaign_orchestrator.py` before spawning `ble_sdr_capture_worker.py`, raising a documented,
  tested `CampaignSessionError("B200_BUSY:...")` when denied (exercised in
  `test_campaign_orchestrator.py`, `test_hardware_qualification.py`).
- Subsystem 2 (`real_spectrum_stream.py`, Live Monitor) **never references `SdrDeviceArbiter` at all**
  — it only holds its own in-process `threading.Lock` (`begin_exclusive_operation`/
  `end_exclusive_operation`, `real_spectrum_stream.py:212-221`), used to coordinate *other*
  same-process features (live audio demod, modulated-signal analysis), not to signal subsystem 1.
- **Consequence, stated exactly as found, not resolved further by static reading**: if Live Monitor is
  already streaming from the B200, subsystem 1's arbiter has no way to know that — any real exclusion
  between "Live Monitor running" and "a BLE-RFFI capture starting" would have to come from the UHD
  driver itself refusing a second open on the same busy USB device, not from this codebase's own
  arbiter.

---

## 2. The three distinct capabilities that exist today

### 2.A. RF Intelligence — rule-based RF-object hypothesis (general spectrum subsystem)

A rule-based band-profile matcher, not a trained ML classifier and not BLE-RFFI.

- Detection: `detect_signal_candidates()` — energy-threshold candidates from one spectrum frame
  ([`backend/app/modules/rf_intelligence/detector.py`](../../backend/app/modules/rf_intelligence/detector.py)).
- Classification: `classify_candidate()` scores each candidate against a static band-profile catalog —
  center frequency inside the profile's band (+0.45), occupied bandwidth inside the profile's expected
  range (+0.35), plus a small SNR term; below score 0.35 the result is `"Unknown RF signal"`
  ([`classifier_rules.py:10-32,45-60`](../../backend/app/modules/rf_intelligence/classifier_rules.py#L10-L32)).
  No trained weights, no `physical_unit_id`, anywhere in this path.
- A `"bluetooth_ble"` profile family exists in the catalog
  ([`classifier_rules.py:38-41`](../../backend/app/modules/rf_intelligence/classifier_rules.py#L38-L41))
  — RF Intelligence can label a candidate "in the BLE band" by frequency/bandwidth alone, which is a
  **band-profile guess**, never a decoded packet and never an enrolled-device identification.
- API: `GET /rf-intelligence/live` pulls the current spectrum frame synchronously and classifies it
  ([`routes.py:44-68`](../../backend/app/modules/rf_intelligence/routes.py#L44-L68)); the dedicated
  `RFIntelligenceView.tsx` polls a `getLiveRFScene` call every ~1500 ms, and the same detections are
  also drawn as bands directly on the Live Monitor spectrum canvas via `SpectrumView.tsx`'s own
  overlay, polled every 1200 ms (`window.setInterval(refreshRfScene, 1200)`,
  [`SpectrumView.tsx:683`](../../frontend/src/presentation/views/SpectrumView.tsx#L683)).

**Correct terminology:** *RF-object / protocol-class hypothesis from band-profile matching* ("RF scene
understanding," the platform's own term). Never "device detected," never "BLE device identified."

### 2.B. BLE-RFFI live-spectrum inference — a real trained model, a real on-spectrum overlay, one real documented failure case

**This is the capability closest to what the user's mockup in the request describes, and it is more
built than a first read of the general README suggested.** It genuinely exists, is genuinely wired to
a real trained bundle, and genuinely draws a labeled, frequency-positioned band on the live spectrum —
but it has one real, already-documented, human-run test showing the classifier does not discriminate
the target device from an unrelated ambient one.

**Real chain, end to end:**

1. `backend/tools/spectrum_stream_worker.py::_detect_energy_bursts()` (GNU Radio `uhd.usrp_source`
   subsystem, ~100 ms cadence at `fps=10`) runs every FFT loop; when BLE live-check is enabled and the
   tuning is in-band, it emits a `"source": "ble_rffi_iq_burst"` frame carrying the raw IQ window. This
   is an explicitly **separate, duplicated re-implementation** of subsystem 1's own `detect_bursts()`
   (`ble_sdr_capture_worker.py`), not shared code.
2. `backend/app/infrastructure/sdr/real_spectrum_stream.py` stores the latest such frame in a
   **single-slot buffer** (`_pending_burst`) — a newer burst silently overwrites an unprocessed older
   one (explicit "keep up or drop, never a growing backlog" design). `_live_check_worker_loop()` picks
   it up and, only when `BLE_LIVE_DECODE_ENABLED` is set, runs `live_decode_burst()` (the Gate 2A.2
   decoder) before classification; otherwise the raw energy-threshold window is classified directly.
   `BLE_LIVE_DECODE_ENABLED` defaults to `false` in the decoder module itself and is `true` only when
   launched with the explicit `-EnableBleLiveDecode $true` flag on `scripts/run_dev.ps1` — **not on by
   default from a bare `uvicorn` start**.
3. `StudioRepository.live_check()` checks BLE-channel compatibility, then calls
   `OfflineInferenceService.run_live()`, which loads a real exported `ModelBundleManifest` from disk
   (joblib Random Forest / SVM / Logistic Regression, or a `torch.load`ed CNN1D/CNN2D) and scores the
   window against a VALIDATION-calibrated `acceptance_threshold`.
4. Result fields, per watched `bundle_id`: `predicted_class`, `identified_device`, `class_probability`,
   `acceptance_threshold`, `final_decision` (`IDENTIFIED`/`UNKNOWN`/`NO_BLE_PACKET_DECODED`/
   `SAMPLE_RATE_MISMATCH`), `decoded_address`, `peak_power_dbfs`, and **`timestamp_utc`** — served via
   `GET /api/ble-rffi-studio/live-monitor/result` (routes at `studio_routes.py:594-662`).
5. Frontend: [`BleRffiLiveModelPanel.tsx`](../../frontend/src/presentation/views/ble-rffi-studio/BleRffiLiveModelPanel.tsx),
   imported and rendered directly inside `SpectrumView.tsx`
   ([`SpectrumView.tsx:16,2231`](../../frontend/src/presentation/views/SpectrumView.tsx#L2231)), polls
   the result every ~1500 ms and **draws a real, frequency-positioned graphical overlay**: a colored
   vertical band spanning the trained bundle's `center_frequency_hz ± bandwidth_hz/2`, computed as a
   left%/width% of the current spectrum span
   ([`BleRffiLiveModelPanel.tsx:483-556`](../../frontend/src/presentation/views/ble-rffi-studio/BleRffiLiveModelPanel.tsx#L483-L556)),
   with a floating label showing the physical unit(s), model type, `IDENTIFIED`/`No detectado`, and the
   confidence percentage. Devices sharing a channel are grouped into one band with stacked labels
   instead of overlapping rectangles. A "hold last positive result" timer (default a few seconds) keeps
   a detection visible across polls that would otherwise miss a short burst.

**Real, documented empirical result — not merely uncharacterized** (dated 2026-07-30, human-operated,
real hardware; full table and prose in
[`backend/app/modules/ble_rffi_studio/README.md:1852-1885`](../../backend/app/modules/ble_rffi_studio/README.md#L1852-L1885)):
with `BLE_LIVE_DECODE_ENABLED=1`, against bundle `AUTO-random_forest-41b410e64b-bundle`
(`CC2650-UNIT-01`, registered address `B0:B4:48:C0:36:06`), an operator toggled the physical device
on/off while polling the live result:

| Moment | Real device state | `decoded_address` | Matches the enrolled unit? | `class_probability` |
|---|---|---|---|---|
| Baseline | OFF | `0E:E6:DF:2E:07:A6` (ambient, unrelated) | No | 0.71–0.72 |
| A few seconds after power-on | **ON** | `B0:B4:48:C0:36:06` | **Yes, real** | 0.85 → 0.97 |
| Powered off again | OFF | `0E:E6:DF:2E:07:A6` (same ambient device) | No | 0.69 → **0.97** |

The energy detector and the Gate 2A.2 decoder both tracked physical reality correctly
(`peak_power_dbfs` rose measurably at power-on; `decoded_address` matched the real registered address
only while genuinely transmitting). **The classifier itself did not discriminate**: confidence on a
completely unrelated ambient transmitter's real BLE packets (0.97) was statistically indistinguishable
from confidence on the enrolled device's own real, address-confirmed packets. This is real,
live-hardware confirmation that the model was never trained to separate "this specific enrolled unit's
RF hardware" from "some real BLE packet exists" — the window-alignment fix (decode-before-classify) was
necessary but not sufficient.

The Gate 2A.2 decoder itself remains **not frozen** even when enabled: best development-sweep result
381/384 (not the required 384/384), `iq_recovery_validated=false`, `ota_validated=false`.

**Correct terminology for this capability:** the platform's own established term, **"online
experimental inference"** or **"live-spectrum inference"** — never "real-time," never "validated
real-time identification." A real trained RFFI model runs, a real graphical overlay exists, and one
real documented trial shows the model does not reliably discriminate the enrolled unit from ambient BLE
traffic.

### 2.C. What does NOT exist today

- No persisted, timestamped collection of live-check results — each result carries its own
  `timestamp_utc` (§2.B point 4) but nothing writes a running log of these to disk by default; a
  restart or a new poll simply replaces the transient in-memory value.
- No unified overlay merging RF Intelligence's rule-based hypothesis (§2.A) with a BLE-RFFI
  enrolled-device hypothesis (§2.B) — they are two separate features, two separate backends
  (`rf_intelligence` vs. `ble_rffi_studio.inference`), rendered as two separate overlay layers on the
  same canvas, never merged into one hypothesis.
- No automated test of any kind exercises the live chain end to end (§6).

---

## 3. Latency / timing characterization

| Stage | Value | Source |
|---|---|---|
| Spectrum trace backend→frontend poll interval | 100 ms default (`VITE_SPECTRUM_POLL_INTERVAL_MS`) | `frontend/src/shared/config/runtime.ts:1,23-26` |
| Waterfall backend→frontend poll interval | 100 ms default (`VITE_WATERFALL_POLL_INTERVAL_MS`) | `runtime.ts:2,27-30` |
| Spectrum-worker FFT/frame cadence | ~100 ms per frame (`fps=10` default) | `spectrum_stream_worker.py:358,363,407-408`, `--fps` passed from `real_spectrum_stream.py:162-163` |
| Burst-detection cadence | Same ~100 ms, over a 2-slot rolling raw-IQ buffer (current+previous interval, so a boundary-spanning burst is still captured) | `spectrum_stream_worker.py:398-405,458-478` |
| Burst→classification handoff | Single-pending-burst slot, `threading.Event` with a 0.5 s wait; a newer burst overwrites an unprocessed older one | `real_spectrum_stream.py:362-379` |
| RF Intelligence overlay poll interval | 1200 ms, hardcoded | `SpectrumView.tsx:683` |
| BLE-RFFI live-monitor result poll interval | ~1500 ms | `BleRffiLiveModelPanel.tsx:263` |
| Positive-result hold duration (BLE-RFFI panel) | A few seconds, operator-adjustable, default a few seconds | `BleRffiLiveModelPanel.tsx:52,154` |
| Detector / decoder / feature-extraction / classifier inference latency (live path) | **NOT MEASURED** — no timing is logged at any of these stages | — |
| Offline (TEST-split) inference latency, for comparison only | Real, measured, but for a *different* path — e.g. `validation_latency_ms: 5.28` in one training run's `latency.json` | `backend/.../training_runs/AUTO-random_forest-d23e2eab58/latency.json` |
| Total end-to-end latency (live path) | **NOT MEASURED / NOT RECONSTRUCTABLE** | — |
| Dropped-window rate | **Explicitly not counted** — single-slot overwrite, no counter | `real_spectrum_stream.py:362-379` |
| Offline-vs-live agreement reconciliation | **Does not exist** | — |
| Streaming vs. block vs. post-capture | **Continuous, block-by-block streaming** from a persistent GNU Radio subprocess reading directly off the B200 — no IQ file is written or read anywhere in this path | `spectrum_stream_worker.py` main loop |

**Why "real-time" is avoided, in this repository's own words** (already established prose, reused
here rather than restated differently): using that term "would require a stated deadline, measured
latency, measured throughput, and a measured dropped-window rate, plus an offline-vs-live agreement
reconciliation. None of these exist in code." This audit reaches the identical conclusion
independently, confirms it still holds, and adopts the same replacement terms.

A displayed detection corresponds to RF acquired within roughly one-to-two ~100 ms worker cycles of the
currently-tuned live spectrum (not a replay of a completed capture file) — but, per §2.B, the window
actually classified is frequently not a CRC-validated decoded packet, and even when it is, the
classifier's own confidence has one documented case of failing to discriminate the enrolled device from
ambient traffic.

---

## 4. Real visual evidence found

- [`readme_img/live_monitor_rf_intelligence_overlay.png`](../../readme_img/live_monitor_rf_intelligence_overlay.png)
  and [`readme_img/rf_intelligence.png`](../../readme_img/rf_intelligence.png) — real screenshots,
  committed `54ee9e3b79634d073c8773407d5e8f9c5058b1b6`, 2026-07-10, both showing **§2.A (RF
  Intelligence)** detecting broadcast-FM candidates, not BLE devices.
- **No real screenshot of §2.B (the BLE-RFFI on-spectrum band overlay) was found anywhere in this
  repository.** No screenshots/recordings folder, no E2E/Playwright artifact, and no test fixture
  captures its real rendered UI state.
- **One real, human-operated live-hardware trial is documented — in a table, not a screenshot** (§2.B):
  `backend/app/modules/ble_rffi_studio/README.md:1852-1885`, dated 2026-07-30, with real
  `decoded_address`/`class_probability`/device-state values recorded as the operator toggled a physical
  device. This is real evidence of the pipeline's behavior, but not a visual/UI artifact.
- A Playwright spec (`frontend/tests/e2e/ble-rffi-studio.spec.ts`) exists but exercises only the
  dataset/capture/training workflow, never `SpectrumView`/Live Monitor or `BleRffiLiveModelPanel`.
  `backend/app/tests/e2e/` is an empty package.

**Recommendation, not implemented here**: any future screenshot added as evidence for this capability
should carry an explicit UTC capture timestamp (filename or adjacent caption), since a file's git
commit date alone only proves when it was *added to the repository*, not when the underlying UI state
was actually captured. No such convention exists yet in this repository.

---

## 5. Relation to the BLE-RFFI acquisition/evidence pipeline

The model bundle scored in §2.B is a real `ModelBundleManifest` — the same contract type produced by
`prepare_and_train()`/`export_and_approve_all_candidates()` for RQ1/RQ2 — so the model *artifact* is
genuinely shared. What is **not** shared: the acquisition path (live inference rides the GNU-Radio B200
stream; training data came from the SoapySDR B200 stream) and the burst-detection code (§2.B point 1,
explicitly duplicated, not reused). No live-path prediction feeds back into any dataset, split, or
evidence artifact — `ble_rffi_studio` "never re-captures or re-decodes IQ itself" for its own
scientific pipeline, and live results are not persisted by default.

## 6. Relation to the GNU Radio / general spectrum subsystem

Both §2.A and §2.B run on top of the GNU Radio (`uhd_gnuradio`) live spectrum stream, explicitly
reusing Live Monitor's own already-open B200 session rather than opening a second SDR handle
(`bleRffiStudioApi.ts` and `studio_routes.py` both document this "reuses Live Monitor's own B200
session; never opens a second SDR session" design). Neither is part of the BLE-RFFI SoapySDR capture
pipeline (subsystem 1). §2.B is the one genuine bridge between the two halves of the platform: GNU
Radio stream in, BLE-RFFI-trained-model verdict out — but nothing flows back into subsystem 1's own
data pipeline.

## 7. Tests

No automated test (unit, integration, or e2e) exercises the live chain end to end: not the
`/live-monitor/*` routes, not `StudioRepository.live_check()`, not
`RealSpectrumStream._live_check_worker_loop`/`enable_ble_live_check`, not
`spectrum_stream_worker.py`'s burst-detection/live-check path, not `ble_live_burst_decoder.py`, and not
`BleRffiLiveModelPanel.tsx`. `OfflineInferenceService.run_live()` has isolated unit coverage
(`test_bundle_and_inference.py`) but only against a synthetic bundle and hand-built IQ, not the
streaming path. `SdrDeviceArbiter` has its own isolated test, but not a test of whether subsystem 2
actually participates in it (per §1, it does not). **The entire chain's only real validation is the
one manual, human-operated real-hardware session in §2.B/§4** — never an automated test.

---

## 8. Status classification

| Capability | Status |
|---|---|
| RF Intelligence rule-based RF-object/protocol-class hypothesis, drawn on the live spectrum trace | **IMPLEMENTED** — real, working, screenshotted; rule-based, not ML, not BLE-RFFI |
| BLE-RFFI live-spectrum inference: real trained bundle scoring a live-selected burst, with a real frequency-positioned on-spectrum overlay | **IMPLEMENTED_BUT_NOT_EMPIRICALLY_CHARACTERIZED** for latency/reliability at scale — but **not simply "uncharacterized"**: one real, documented, human-run trial (§2.B) already shows the classifier fails to discriminate the enrolled device from an unrelated ambient BLE transmitter |
| Persisted/collectible log of near-live BLE-RFFI predictions | **NOT_IMPLEMENTED** — each result carries `timestamp_utc` but nothing writes a running log by default |
| Automated end-to-end test coverage of the live chain | **NOT_IMPLEMENTED** |
| "Validated real-time RF device identification" | **NOT_IMPLEMENTED / not claimable** — this repository's own documentation already deliberately avoids "real-time" for this capability, and the one real empirical trial available is a documented negative result for discrimination, not a positive validation |

**§2.B in one sentence**: real streaming acquisition, a real trained RFFI classifier, and a real
frequency-positioned confidence overlay all genuinely exist and are wired together — but the one real
hardware trial run against this exact pipeline shows the classifier does not yet discriminate the
target enrolled device from ambient BLE traffic, and no latency, drop-rate, or offline/live agreement
measurement exists to characterize it further.

---

## 9. What would be needed for a scientifically solid "real-time identification" claim

1. A latency-instrumented live path (timestamps at capture, detection, decode, feature-extraction, and
   inference), so an end-to-end latency distribution can be reported instead of asserted.
2. A dropped-window/miss-rate counter, replacing the current single-slot overwrite.
3. An offline-vs-live agreement study: the same real bursts through both the offline (CRC-validated,
   bit-aligned) pipeline and the live (decode-enabled) pipeline, with agreement rate reported.
4. A real, deliberately designed hard-negative campaign using the ambient device already found in §2.B
   as a documented, reproducible negative example, extending toward the identity-task dataset-quality
   work already scoped in `backend/app/modules/ble_rffi_studio/README.md`'s "Current status and action
   plan."
5. Freezing the Gate 2A.2 decoder (currently 381/384 on its own development sweep) if the decode-aligned
   live window path is to be relied on instead of the raw-energy default.
6. A persisted, timestamped log of live predictions (the `timestamp_utc` field already exists per
   result — only the persistence step is missing), so any future claim traces back to inspectable
   records.
7. At least one automated test (even a mocked one) exercising the live chain, closing the gap in §7.

---

No experiment was executed and no artifact, code, `.tex`, `.bib`, or PDF was modified to produce this
document.
