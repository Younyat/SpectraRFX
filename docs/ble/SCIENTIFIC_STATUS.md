# BLE Scientific Status

Snapshot commit: `5f1ddbba` (2026-08-05) for §1-§15 below (left as originally
written and verified, except for the specific in-place corrections marked
`[2026-08-09 correction]`). §16 (2026-08-09) documents a real, substantial
correction pass over the working tree at commit `0d00bb7f` — not yet
committed at the time §16 was written, so treat §16 as describing the
current working tree, not a tagged release. Repo root below is
`spectrum-lab/`.

This document is the detailed technical companion to the `## BLE-RFFI Studio`
section of the root [`README.md`](../../README.md). It exists because BLE
work in this repository spans **two structurally independent systems** that
must never be conflated:

1. **`rf_experiment_lab`** (`backend/app/modules/rf_experiment_lab/`) — the
   paper-replication technique registry, codes `E0`, `E1`, `E2`, `E3`, `E5`,
   `E8`, `E9`, `E10`, `S1`, `S2`, `S4` (`experiment_registry.py:56-158`).
   These experiments are **general RF techniques evaluated on whatever RF
   captures are on hand** — not all of them BLE, not all of them
   device-fingerprinting.
2. **`e6_oracle_style`** (`backend/app/modules/e6_oracle_style/`) — code
   `E6`, a structurally separate module registered independently
   (`api_module.py:14-20`), never listed inside `experiment_registry.py`.
3. **BLE-RFFI Studio** (`backend/app/modules/ble_rffi_studio/`) — a third,
   independent module purpose-built for BLE device identification. It does
   **not** use E0–E6 codes at all; its own taxonomy is a `ScientificTask`
   enum (`TARGET_VS_BACKGROUND`, `MULTI_DEVICE_CLASSIFICATION`,
   `SAME_MODEL_UNIT_IDENTIFICATION`, `UNKNOWN_DEVICE_REJECTION`,
   `contracts/split.py`). A grep across
   `backend/app/modules/ble_rffi_studio/` for `rf_experiment_lab` and
   `e6_oracle_style` finds exactly one hit — a documentation aside in
   `ble_rffi_studio/README.md` about an unrelated CI note — confirming
   **no code, dataset schema, or metric implementation is shared** between
   BLE-RFFI Studio and E0/E1/E3/E5/E6.

**No experimental code was renamed or reused across systems anywhere in this
document.** E0/E1/E3/E5/E6 keep exactly their existing meaning; BLE-RFFI
Studio's `TARGET_VS_BACKGROUND` etc. are a separate vocabulary that has never
been called "E-anything" in code.

Banned-terms discipline used throughout this document and enforced in the
README summary: **"validated", "robust", "reproducible", "real-time",
"receiver-invariant", "forensic attribution"** are used only where an
explicit criterion and a real, cited execution back them. Anything not
determinable from code or on-disk artifacts is marked exactly
`NOT DOCUMENTED — requires experimental confirmation`.

**Status categories (2026-08-18, used consistently across this document, the
README, the dashboard, and `PAPER_EVIDENCE_MAP.md`)**: every scientific
result in this repository carries exactly one of three statuses, never
mixed:

1. **DEVELOPMENT EVIDENCE** — `AVAILABLE`. Real, current, non-confirmatory
   evidence from today's short (~10 s) captures and the existing frozen
   `CONFIRMATORY` split (an internal manifest role name, not a claim of
   confirmatory scientific status — see §18). Cite as DEVELOPMENT, never as
   confirmatory/definitive/FUTURE.
2. **DEFINITIVE / PROTECTED FUTURE** — `NOT_YET_AVAILABLE`. The frozen-protocol,
   120 s / 12-decision-window campaign and its one-time protected evaluation.
   Fail-closed: not executed, not readable, not generatable by accident.
3. **RQ3 / RQ4 packet-condition / CH37→CH38 transport / CH39 / near-live** —
   `PENDING` or `NOT_AVAILABLE`. The real mechanism exists and is tested; the
   real campaign data or analysis it needs does not exist yet (RQ3: 0/80 real
   pairs; RQ4 packet-condition: 0/4 eligible units; CH37→CH38: real CH38 RF
   data already exists — 1,663 admitted examples for the four enrolled units
   — but the transport analysis itself has not been run; CH39: 0 real
   captures for the four enrolled units; near-live: no real
   prediction-collection mechanism wired yet). Distinct from the
   **DEVELOPMENT_EXPLORATORY** analytical-region control (FULL_BURST vs.
   PRE_PDU, §19), which has already been executed and does not change any of
   the statuses above.

---

## 1. Official experiment/model taxonomy

### 1.1 `rf_experiment_lab` registry (E0/E1/E2/E3/E5/E8/E9/E10, S1/S2/S4)

Single source of truth: `backend/app/modules/rf_experiment_lab/experiment_registry.py`,
`TECHNIQUES` list (lines 56–158). There is no `E4`, `E6`, or `E7` entry in
this registry.

| Code | Name | Task | Implementation status | Real run(s) on disk |
|---|---|---|---|---|
| E0 | Morphological baseline region detector | `region_detection` (stage_1), non-trainable | Implemented (`region_detection/morphological_adapter.py`) | 1 (`results/exp_region_morphological_baseline_v1/20260501T153202Z/`) — **no ground-truth annotations supplied**, so IoU/precision/recall are `null` |
| E1 | Raw IQ CNN fingerprinting | `device_fingerprinting_closed_set` (stage_2) | Implemented: `cnn1d` only (`SmallCNN1D`, `e1_raw_iq_cnn1d.py:495-512`). Registry also lists `resnet1d` as a `model_type` (`experiment_registry.py:101`) but **no `resnet1d` code exists anywhere in the file** | 1 (`results/e1_raw_iq_cnn1d/20260502T231159233923Z/`) — `accuracy=0.0, macro_f1=0.0`, confusion matrix `[[0,0],[24,0]]` (single-class collapse) |
| E2 | (registry entry) | — | `not_implemented` (`experiment_registry.py:104-112`) | none |
| E3 | Spectrogram/waterfall CNN | `signal_recognition` or `device_fingerprinting` | Implemented: `simple_cnn2d` (`SmallCNN2D`), `resnet18`, `vgg11` (all `weights=None`, never pretrained — tested, `e3_spectrogram_cnn2d.py:604-626`) | 1 (`results/e3_spectrogram_cnn2d/20260502T231313943275Z/`) — `accuracy=0.0, macro_f1=0.0`, same single-class-collapse pattern |
| E5 | PSD/MFCC/LFCC classical ML | `signal_recognition` or `device_fingerprinting` | Implemented: PSD-only, 13 hand-crafted features (`e5_spectral_baseline.py:19-33`), 4 sklearn models (`logistic_regression`, `random_forest`, `svm_rbf`, `knn`). **MFCC and LFCC are registered but explicitly `not_implemented`** (`e5_spectral_baseline.py:56-57`) | 6 (`results/e5_spectral_feature_baseline/`) — best stored run shows `accuracy=1.0` on **2 TEST samples of a single class** (`number_of_test_samples: 2`), not evidence of multi-class generalization |
| S1, S2, S4, E8, E9, E10 | (registry entries) | — | `not_implemented` | none |

### 1.2 `e6_oracle_style` (E6) — structurally separate

Not present in `TECHNIQUES`. Registered as its own top-level
`BackendModuleDefinition("e6_oracle_style", ...)`
(`e6_oracle_style/api_module.py`). Classical tabular fingerprinting over
**external, non-BLE** reference datasets (`kri_wifi`, `uav_lightbridge`,
`ieee_cbrs`) plus locally created ones, via 8 sklearn model types
(`train.py:33-42`). What "Oracle" stands for as an acronym is
**NOT DOCUMENTED IN CODE** — used only as a style label referencing an
external project not present in this repository. Real evidence: 15 trained
`.joblib` models on disk under `storage/e6/models/`, but **no automated test
file exists for E6** anywhere in `backend/app/tests/`.

Known internal inconsistency (not corrected here, only documented): the
module description claims "37 tabular features"
(`e6_oracle_style/api_module.py:14-20`) but `feature_extractor.py`'s own
`feature_names()` enumerates 36 (24 base + 12 FFT bins).

E6 is not a BLE-specific system: none of its three shipped reference
datasets are BLE, and it shares no dataset schema, metrics code, or storage
root with either `rf_experiment_lab` or BLE-RFFI Studio.

### 1.3 BLE-RFFI Studio's own taxonomy — not an E-code

`ScientificTask` (`contracts/split.py`), exactly four values:
`TARGET_VS_BACKGROUND`, `MULTI_DEVICE_CLASSIFICATION`,
`SAME_MODEL_UNIT_IDENTIFICATION`, `UNKNOWN_DEVICE_REJECTION`. This is a
**dataset/split classification**, not a model-architecture registry like
`rf_experiment_lab`'s. It must never be read as "E7" or folded into the
E0–E10 numbering — the module's own README and code never call it that.
Model architectures available inside BLE-RFFI Studio are a separate,
five-value `ModelType` enum (`contracts/training.py:11`) —
`logistic_regression`, `svm_rbf`, `random_forest`, `cnn1d`, `cnn2d` — see
§9.

---

## 2. BLE capability status

States used: `IMPLEMENTED / PARTIALLY_IMPLEMENTED / TESTED_SYNTHETIC /
TESTED_REAL_IQ / REPEATED / VALIDATED / PENDING`. "REPEATED" below means
exercised on real B200 IQ across more than one independent real session/run
with the result recorded on disk. "VALIDATED" means an explicit acceptance
criterion exists in code *and* was checked against real data with a real
pass/fail outcome recorded on disk (not merely "code exists").

| # | Capability | State | Evidence |
|---|---|---|---|
| 1 | Native BLE scanning (Bleak/WinRT, brackets each B200 capture) | REPEATED | `ble_native_scan_worker.py`; 146 real captures, each with a paired native-scan session |
| 2 | USRP B200 real IQ acquisition (SoapySDR, frozen RF profile) | REPEATED | `ble_sdr_capture_worker.py:407-616`; 140/146 captures `data_origin=REAL_B200` |
| 3 | Candidate burst detection (median/MAD block-energy threshold) | REPEATED | `detect_bursts()`, `ble_sdr_capture_worker.py:278-308`; drives every real replay |
| 4 | Symbol timing/sync recovery (16-phase hypothesis bank vs. preamble+AA) | TESTED_REAL_IQ | `timing_interpolator.py` (external `ble-worker-lab`); decoder itself flagged non-frozen (see §3, Gate 2A.2 caveat) |
| 5 | GFSK discriminator demodulation | TESTED_REAL_IQ | `dsp_receiver.py:56-59`; same Gate 2A.2 caveat |
| 6 | Dewhitening (BLE 7-bit LFSR, spec-correct) | TESTED_REAL_IQ | `whitening.py:3-15`; replay engine does **not** independently count per-candidate dewhitening success (`"dewhitening_completed": "NOT_INSTRUMENTED_BY_CURRENT_DECODER"`, `ble_offline_replay.py:1091`) |
| 7 | PDU reconstruction (preamble/AA/header/length gates) | TESTED_REAL_IQ | `bitstream_decoder.py:27-73` |
| 8 | CRC-24 validation (spec-correct polynomial `0x00065B`, init `0x555555`) | TESTED_REAL_IQ | `crc.py:3-15` |
| 9 | Native↔SDR packet association (`_associate()`, ±250 ms window) | TESTED_REAL_IQ | `ble_offline_replay.py:923-1047`; **0 `STRONG` associations among any real (`REAL_B200`) example in the current corpus** — see §5 |
| 10 | Physical Device Registry / address-binding resolution | REPEATED | `registry/physical_device_registry.py`; 7,671 `CONFIRMED` label decisions across the real corpus |
| 11 | Evidence Stage (per-packet example + annotation generation, contradiction detection) | REPEATED | `evidence/evidence_stage.py`; 47,051 examples generated to date |
| 12 | Dataset Builder (freeze, quality gate, `class_distribution`) | REPEATED | `dataset/dataset_builder.py`; 34 quality reports ever generated (32 `ACCEPTED_FOR_TRAINING`), 8 datasets currently frozen |
| 13 | Split Builder (capture/execution/session/candidate/packet/sample-range-disjoint TRAIN/VALIDATION/TEST + leakage check) | VALIDATED | `split_builder.py`; **2 of the 8 currently-frozen datasets' splits are `NOT_FEASIBLE`** with the recorded reason `Leakage check failed on field(s): ['capture_id','execution_id','session_id']` — a real, on-disk case of the gate actually rejecting real data |
| 14 | Model training, 5 architectures (`logistic_regression`,`svm_rbf`,`random_forest`,`cnn1d`,`cnn2d`) — **[2026-08-09: a 6th, `frozen_morphological_baseline`, was added; see §9 and §16.9]** | REPEATED | `training_service.py`; 173 `TrainingRun` records ever generated (all under the original 5 -- no real run yet exists under the 6th) |
| 15 | VALIDATION-only composite-score selection + single guaranteed TEST evaluation | REPEATED | `model_selector.py:37-68`; every training run |
| 16 | Opt-in multi-candidate TEST comparison (`evaluate_training_run_on_test_opt_in`) | REPEATED | 22 of the 27 currently-exported bundles carry `test_evaluation_provenance=OPT_IN_MULTI_CANDIDATE_COMPARISON` |
| 17 | Device Scrubbing (packet-window excision + real quiet-segment substitution) | REPEATED | `scrubbing/device_scrubber.py`; 2 independent real rounds for `SHELLY-PLUG-01` (3-session and 8-session), see `backend/README.md` |
| 18 | Live-spectrum single-model health check (baseline-vs-device-on comparison) | TESTED_REAL_IQ | `real_spectrum_stream.py`; `SHELLY-PLUG-01` `random_forest` bundle, 10 real live samples, 6/10 crossed `acceptance_threshold=0.7` and returned `IDENTIFIED` (`backend/README.md:1080-1089`) |
| 19 | Simultaneous multi-device live watching (N bundles vs. one shared decoded burst) | IMPLEMENTED | `_live_check_worker_loop()`, `real_spectrum_stream.py`; wired end-to-end and used interactively, but **no dedicated on-disk log of a multi-device-simultaneous real session exists** — `NOT DOCUMENTED — requires experimental confirmation` for a quantified multi-device live accuracy claim |

**Capabilities added 2026-08-09** (confirmatory-evaluation discipline,
receiver-epoch redesign, `day_id` source correction, RQ2's 4th model
branch, RQ3/RQ4 infrastructure, decision windows, coverage/risk-coverage,
fixed seed set, inference provenance manifest, migration ledger) are not
retrofitted into the table above — they use the same evidence discipline
but are documented in full, with the explicit IMPLEMENTED vs.
EXPERIMENTALLY VALIDATED distinction, in **§16**.

---

## 3. BLE acquisition chain — stage by stage

Every stage below traces one real example back to raw IQ. Sourcing note: the
bit-level DSP (sync, GFSK demod, dewhitening, PDU/CRC) lives in a **separate
repository on the same machine**, `C:\Users\Usuario\ble-worker-lab` (package
`ble_worker`), invoked from `spectrum-lab` only via the environment variable
`BLE_GATE2A2_REPOSITORY` (default `C:\Users\Usuario\ble-worker-lab`,
`ble_offline_replay.py:191`) — that code is outside this repo's own git
history and is cited by file path in the external repo, not by commit hash.

| Stage | Input | Output | Acceptance criterion | Failure state | File | Artifact |
|---|---|---|---|---|---|---|
| 1. Native scan | BLE advertising RF, OS BLE stack | `NativeObservationRecord` rows (address, RSSI, tx_power, manufacturer/service data — **no raw PDU bytes**, `raw_advertising_pdu_available: False`) | Scanner started without exception | Scan never starts / no rows | `ble_native_scan_worker.py:70-172` | native scan session log |
| 2. B200 acquisition | Antenna RF at a declared channel (37/38/39) | `.cf32` IQ file, `cf32_le`, 4 Msps, 2 MHz BW | `acquisition_quality=PASSED`, `discontinuities` counted | `FAILED`/`INCOMPLETE` (schema-representable; **never actually observed** — 47,051/47,051 examples show `quality_status=PASSED`) | `ble_sdr_capture_worker.py:407-616` | `CaptureRecord.iq_path` + `iq_sha256` |
| 3. Candidate burst detection | Full `.cf32` file | Candidate segments (`start_sample`,`end_sample`) | `power > max(noise*4, noise+8*MAD, 1e-12)` | No active blocks → 0 candidates | `detect_bursts()`, `ble_sdr_capture_worker.py:278-308` | `candidate_manifest` entries |
| 4. Sync/timing recovery | One candidate segment | Selected sampling phase (of 16) | `sync_distance <= max_sync_errors(2)` vs 40-bit preamble+AA pattern | `timing_not_locked` | `timing_interpolator.py`, `dsp_receiver.py:104-112` (external repo) | none persisted beyond pass/fail |
| 5. GFSK demod | Time-domain samples at selected phase | Soft/hard bit stream | N/A (deterministic discriminator) | N/A | `dsp_receiver.py:56-59` (external repo) | none persisted directly |
| 6. Dewhitening | Air bits + channel index | Dewhitened bits | N/A (deterministic LFSR) | N/A (not independently instrumented — see §2 row 6) | `whitening.py:3-15` (external repo) | none persisted directly |
| 7. PDU reconstruction | Dewhitened header+PDU bits | `BleDecodedPacket` (type, addr, length, payload) | Preamble ≥7/8 match, AA Hamming distance 0, valid length for PDU type | Rejected at whichever gate fails first | `bitstream_decoder.py:27-73` (external repo) | packet fields on the replay ledger row |
| 8. CRC-24 check | PDU bits + received CRC | `crc_received == crc_computed` | Exact match | CRC mismatch → packet dropped | `crc.py:3-15` (external repo) | `crc_valid_packets` counter |
| 9. Association | Decoded packet + native rows within ±250 ms | `association_strength` (`STRONG`/`WEAK`/`NONE`) + rejection reason | Address present, exactly one native match in window, matches declared target | `ADDRESS_NOT_PRESENT_IN_PDU` / `ADDRESS_MISMATCH` / `MULTIPLE_NATIVE_CALLBACKS` / `WINDOWS_TIMESTAMP_UNAVAILABLE` / `TIME_DELTA_ABOVE_THRESHOLD` | `_associate()`, `ble_offline_replay.py:923-1047` | replay ledger row, `replay_final_report.json` |
| 10. Evidence Stage resolution | Decoded packet address + Physical Device Registry | `physical_unit_id` (or `None`) + `LabelDecision` | `registry.find_binding_for_address()` returns a bound unit, or operator `isolation_declared_physical_unit_id` | `dataset_eligibility=QUARANTINED` on a declared-off contradiction | `evidence/evidence_stage.py:90-160` | `ExampleRecord` + `LabelDecision` (`evidence/<capture>/examples.jsonl`, `annotations.jsonl`) |
| 11. Dataset freeze | Selected `ExampleRecord`s | Frozen `DatasetManifest` with `class_distribution` | Deterministic hash of composition; quality gate `ACCEPTED_FOR_TRAINING` | `NOT_ACCEPTED_FOR_TRAINING` (2/34 real reports) | `dataset/dataset_builder.py` | `datasets/<id>__<version>.json` |
| 12. Split | Frozen dataset | TRAIN/VALIDATION/TEST assignment | No leakage on `capture_id, execution_id, session_id, candidate_id, packet_id, sample_range`; minimum-evidence rule per `ScientificTask` | `NOT_FEASIBLE` (2/8 current splits — see §2 row 13) | `split_builder.py` | `splits/<id>__<version>__<task>.json` |
| 13. Training | Split + `model_type` | `TrainingRun` + weights | Converges without exception | `FAILED` (schema-representable) | `training_service.py` | `training_runs/<id>.json` |
| 14. VALIDATION scoring/selection | All trained candidates | `composite_score`, one recommended | `0.5*macro_f1 + 0.3*balanced_accuracy_proxy - unknown_capability_penalty` | N/A | `model_selector.py:37-68` | score dict on the training result |
| 15. TEST evaluation | Recommended (always) + opt-in others | `evaluation_report.json` | `test_evaluation_provenance` recorded honestly | N/A | `evaluator.py` | `bundles/<id>/evaluation_report.json` |
| 16. Export/approval | Trained model + all required files | `ModelBundleManifest`, `approval_status` | All 16 `REQUIRED_BUNDLE_FILES` present and hashed | `REJECTED` / `TEST_NOT_EXECUTED` (schema-representable) | `contracts/bundle.py:26` | `bundles/<id>/bundle_manifest.json` |
| 17. Live inference | Live decoded burst from the same B200 stream Live Monitor uses | `IDENTIFIED` / `UNKNOWN` / `INSUFFICIENT_EVIDENCE` (+ `SAMPLE_RATE_MISMATCH` / `NO_BLE_PACKET_DECODED` / `LIVE_ACQUISITION_INCOMPATIBLE_WITH_BUNDLE`) | `acceptance_threshold` calibrated on VALIDATION only | Any of the live-path-specific errors above | `real_spectrum_stream.py`, `offline_inference.py` | live check result (not persisted to disk by default) |

Linking IDs that let any model score be traced back to raw IQ:
`iq_sha256` (capture) → `candidate_id` (deterministic hash of
`source_iq_sha256:start_sample:end_sample:analysis_configuration_id`) →
`packet_id`/`packet_sha256` → `example_id` (hash of
`capture.iq_sha256, iq_start_sample, iq_end_sample, candidate_id, packet_id`)
→ `dataset_manifest_sha256` → `split_manifest_sha256` → `training_run_id` →
`bundle_id`.

**Gate 2A.2 caveat (applies to stages 4–8 collectively)**: this decoder is
explicitly documented in `ble_rffi_studio/README.md:1536-1546` and
`ble_live_burst_decoder.py:25-32` as **not frozen**: best development-sweep
result 381/384 (not the required 384/384), `iq_recovery_validated=false`,
`ota_validated=false`, Holdout B not yet created. Live decoding is gated off
by default (`BLE_LIVE_DECODE_ENABLED`, default `false`) for exactly this
reason.

---

## 4. Hardware/acquisition configuration

**Actually used** (real captures, frozen since capture time, enforced in
code — `ble_offline_replay.py:31-35`, `ble_hybrid_campaign_manager.py:56-161`,
`ble_capture_job_manager.py:16`):

| Parameter | Value |
|---|---|
| SDR | USRP B200 via SoapySDR (not raw UHD API) |
| Sample format | `cf32_le` |
| Sample rate | 4,000,000 sps |
| Bandwidth | 2,000,000 Hz |
| Gain mode | manual (`setGainMode(..., False)`) |
| Gain | 20 dB (positive-pilot protocol) |
| Antenna | RX2 |
| Duration | 10 s |
| USB mode | USB 3 |
| Receiver serial | `E3R04Z1B2` |
| BLE channels | 37 → 2,402,000,000 Hz; 38 → 2,426,000,000 Hz; 39 → 2,480,000,000 Hz (validated against declared channel before replay, `ble_offline_replay.py:315-334`) |

**Supported but not the frozen default**: `channel ∈ {37,38,39}` is
validated generically (`ble_hybrid_campaign_manager.py:164`), so any of the
three channels can be used per session — real captures observed on channel
37 and 38 (per the `CC2650-UNIT-01` channel-mismatch finding documented in
`ble_rffi_studio/README.md`), never all three combined into one training
run.

**Frozen for future / declared but not exercised in the current real
corpus**: `NOT DOCUMENTED — requires experimental confirmation` for any
value outside the table above (e.g. alternate antennas, alternate gain
values) — none were found enforced or exercised in the artifacts inspected
for this document.

---

## 5. BLE label authority

Two **distinct, non-conflatable** mechanisms exist:

**(a) Replay-level candidate funnel `_associate()`**
(`ble_offline_replay.py:923-1047`, described stage-by-stage in §3 row 9).
Tolerance window: ±250 ms, symmetric. `association_strength = STRONG` only
if the matched native address equals the campaign's declared target **and**
exactly one native candidate exists in the window; `WEAK` if a match exists
but isn't the target; `NONE` otherwise. This is a **greedy, first-come
match in decoded-packet iteration order**, not a globally optimal bipartite
assignment — a real methodological detail, not a bug the code itself flags.

**Real finding, checked directly against the current on-disk corpus**:
across all 47,051 examples ever generated, `association_status=STRONG`
occurs on exactly **72** examples — and **all 72 come from a single
`SYNTHETIC_TEST_ONLY` capture** (`capture_id` prefix
`SYNTHETIC-CAP-SYNTHETIC-SESSION-...`, `project_id=SYNTHETIC_DEMO`).
**Among real (`REAL_B200`) evidence, `association_status=STRONG` occurs zero
times in the current corpus.** This is the single most important caveat for
any claim about label quality: no real example currently in this repository
has ever been confirmed via the independently-corroborated (address +
Windows-native-timestamp) path.

**[2026-08-09 addition — `ble_scientific_results`'s parallel labeling
mechanism, not `ble_rffi_studio`'s own `_associate()` above]**
`ble_scientific_results` (the separate, paper-evidence layer) has its own,
structurally distinct STRONG-labeling gate:
`burst_records.py::_passes_target_association_criterion` returns `False`
unconditionally whenever no real, frozen `AssociationPolicy` is supplied —
this was already correctly fail-closed before 2026-08-09. What changed:
`ScientificResultsRepository.find_frozen_association_policy()` now scans
every real `guided_validation/*/association_policy.json` calibration attempt
and auto-supplies the first one with `status=FROZEN` to `build_records()` —
closing a real gap where nothing ever looked one up automatically. **Current
real state, checked 2026-08-09**: all 4 real calibration attempts on disk
show `status=NO_THRESHOLD_SATISFIES_CRITERIA` (coverage=0.0 and
false_strong=0 at every threshold in the grid `[50, 100, 150, 200, 250, 300,
400, 500]` ms); `find_frozen_association_policy()` correctly returns `None`.
**Mechanism: IMPLEMENTED, fail-closed, verified. Experimental calibration:
NOT YET VALIDATED — no frozen policy exists, and none is fabricated.** See
§16.7.

**(b) Evidence Stage's own registry resolution**
(`evidence_stage.py:90-160`, via `registry.find_binding_for_address()`
against the Physical Device Registry, `contracts/physical_unit.py`). This
is the mechanism that actually sets `ExampleRecord.physical_unit_id`, which
is what every dataset's real `class_distribution` is built from — it is
**independent of and downstream from** `_associate()`'s own
`STRONG`/`WEAK`/`NONE` value; a dataset can (and, per the finding above,
in practice does) contain real, non-`STRONG` examples resolved through this
path.

**`CONFIRMED` label-decision breakdown** (from `annotations.jsonl` across
all 146 captures' evidence, 46,979 annotations total — 72 fewer than the
47,051 examples, exactly matching the 72 synthetic `STRONG` examples, which
were seeded directly by `synthetic_demo_seeder.py` and never passed through
the annotation-generating Evidence Stage):

| `decision_status` | Count |
|---|---|
| `PROVISIONAL` | 37,421 |
| `AMBIGUOUS` | 1,959 |
| `CONFIRMED` | 7,599 |

Of the 7,599 `CONFIRMED` decisions, **100% cite the reason text**
*"Physical isolation declared by the operator ... NOT an address-based or
Windows-corroborated association. Weaker ground truth than a STRONG match:
it depends entirely on the physical setup being correct, with no
independent cross-check."* Zero cite an address+Windows-corroborated
reason. Breakdown by device: `keyfobdemo 01`=4,338, `CC2650-UNIT-01`=2,923,
`SHELLY-PLUG-01`=338 (no `CONFIRMED` annotations currently exist for
`CC2541SensorTag` or `keyfobdemo 02` — those devices' training labels come
entirely through path (b) above, via `physical_unit_id` resolution rather
than a `CONFIRMED` `LabelDecision`).

**Tolerances**: ±250 ms native/SDR timestamp window (path a);
`isolation_declared_physical_unit_id` has no numeric tolerance — it is a
binary operator declaration (path b, weaker ground truth, explicitly
documented as such in `contracts/capture.py:80-93`).

**Ambiguous-case handling**: `MULTIPLE_NATIVE_CALLBACKS` (more than one
native row with the same address inside the window) →
`address_match_status=AMBIGUOUS`, real count 1,959 examples
(`association_status=CONFLICT`, distinct from the `AMBIGUOUS` value —
see §6 for the exact enum-vs-real-usage mapping).

---

## 6. Evidence/dataset state taxonomy

New semantic names, distinct from any E-code, none of which existed before
this documentation pass — they are descriptive labels for the real,
already-implemented pipeline stages, not new code:

| Semantic name | Corresponds to (code) | Real count (of 47,051 examples) |
|---|---|---|
| `CONTEXT_ONLY` | A `CaptureRecord` exists but Evidence Stage has not yet produced an `ExampleRecord` for it | not separately counted — every registered capture eventually produces examples once replayed |
| `RF_ACTIVITY_ONLY` | A candidate segment exists (§3 stage 3) but did not yield a CRC-valid packet | not separately counted in the example corpus (examples only exist for CRC-valid packets — see stage 8→10 in §3) |
| `CRC_VALID_PACKET` | `ExampleRecord.quality_status=PASSED` | 47,051 / 47,051 (100% — `FAILED`/`INCOMPLETE` are schema-representable but never observed) |
| `TARGET_ASSOCIATED_PACKET` | `ExampleRecord.association_status ∈ {STRONG, PHYSICAL_ISOLATION_DECLARED}` (a positive association of some kind, either strength) | 72 (`STRONG`, all synthetic) + 7,599 (`PHYSICAL_ISOLATION_DECLARED`, all real) = 7,671 |
| `TRAINING_ELIGIBLE_EXAMPLE` | `ExampleRecord.dataset_eligibility` actually selected into a frozen dataset's `example_ids` | real per-dataset totals in §12 (sum of the 8 current datasets' `class_distribution` values) |

Real aggregate, `association_status` across all 47,051 examples ever
generated: `NONE`=36,604, `CONFLICT`=1,959, `AMBIGUOUS`=817,
`PHYSICAL_ISOLATION_DECLARED`=7,599, `STRONG`=72.

Real aggregate, `dataset_eligibility`: `PENDING_ANALYSIS`=45,088,
`QUARANTINED`=1,963. **`ELIGIBLE` and `INELIGIBLE` are schema-representable
values (`contracts/example.py`) that have never been assigned to any
example in the corpus inspected** — eligibility for training is decided
later, at Dataset Builder selection time, not written back onto the
`ExampleRecord` itself.

---

## 7. Negative control types

Two overlapping, non-identical systems exist — BLE-RFFI Studio's
`CampaignOrchestrator` explicitly reuses the older hybrid-campaign
mechanism's *mechanism only, never its scientific vocabulary or dataset
decisions* (`campaign_orchestrator.py:1-5`, verbatim docstring).

**(a) Older `campaign_policy.py` / `BleHybridCampaignManager` layer** (not
BLE-RFFI Studio's own scientific vocabulary, but the plumbing BLE-RFFI
Studio's capture step still runs through):
`NEGATIVE_CONTROL_TYPES = {target_powered_off, target_physically_absent,
other_device_substituted, ambient_only}` (`campaign_policy.py:21-26`),
requiring `operator_confirmation=True`. A basic control is
`negative_control_passed` iff zero native observations and zero B200
CRC-valid packets are attributed to the target
(`ble_hybrid_campaign_manager.py:484,525,353`). A **reinforced control**
additionally requires a positive reference match to *some* device (proof
the RF chain worked) and a clean capture (no overflow/discontinuity)
(`reinforced_control` field, line 527).

**(b) BLE-RFFI Studio's own vocabulary** (`contracts/capture.py`,
`campaign_orchestrator.py:132-165`, `evidence_stage.py:113-134`) — this is
what actually governs dataset admission:

- `BACKGROUND_TARGET_OFF`: requires `operator_confirmed_target_absent=True`
  or the session start raises
  `CampaignSessionError("BACKGROUND_TARGET_OFF_REQUIRES_OPERATOR_CONFIRMATION")`.
  **Declared** ground truth — never inferred from the absence of a
  detection.
- **Observed contradiction handling**: if a `BACKGROUND_TARGET_OFF`
  capture's own evidence nonetheless address-matches the declared-off
  `target_reference_id`, Evidence Stage forces
  `association_status=CONFLICT`, `physical_unit_id=None`,
  `dataset_eligibility=QUARANTINED` — the address match is never trusted
  over the operator's declaration.
- `BACKGROUND_GENERAL`: no specific target in question at all (no
  presence/absence claim being tested).
- **Real counts**: of 146 real+synthetic captures, `capture_purpose`
  breakdown is `TARGET_DEVICE_ON`=102, `BACKGROUND_TARGET_OFF`=25,
  `BACKGROUND_GENERAL`=13, `UNKNOWN_DEVICE_COLLECTION`=0, and 6 captures
  predate this field (`capture_purpose=None`, legacy).

The literal string `"reinforced negative control"` does not appear in
BLE-RFFI Studio's own code — only in the older, separate
`ble_hybrid_campaign_manager.py` layer described in (a). BLE-RFFI Studio's
own reinforcement is the `_has_background_contradiction()` /
`QUARANTINED` vs `CONTROL_ONLY` vs `ELIGIBLE_AS_BACKGROUND` decision in
`StudioRepository._capture_decision()` (`api/studio_repository.py:312-449`),
which is a distinct policy from (a)'s `reinforced_control` field.

---

## 8. Dataset Builder schema and admission policy

`DatasetManifest` (`contracts/dataset.py`): frozen-once discipline (`frozen`
field, never mutated after quality-gate acceptance), `derived_from` lineage
field (unused so far — all 8 current datasets show `derived_from: None`,
i.e. none are derived from another frozen dataset in the current corpus),
`creation_policy.source_captures` (explicit list of capture IDs admitted),
`dataset_manifest_sha256` (deterministic hash of the frozen composition).

**Disjointness fields actually enforced by the leakage check**
(`split_builder.py`, `_LEAKAGE_FIELDS`): `capture_id`, `execution_id`,
`session_id`, `candidate_id`, `packet_id`, `sample_range`. **Not enforced as
a leakage field**: day-disjointness, receiver-disjointness — deliberately
not added (single-receiver study; a day-disjoint requirement was never part
of any of the four `ScientificTask` designs) — see §16.3.

**[2026-08-09 correction]** Channel is handled differently from the other
two: `SplitBuilder.build()` now excludes every example whose `channel != 37`
from the split ENTIRELY, before assignment, for all four current
`ScientificTask`s — a real, scoped **split policy**, not a leakage-field
addition. Real finding from applying this for the first time: 4 already-frozen
real datasets (`CC2541SensorTag-AUTO-TVB`, `CC2650-UNIT-01-AUTO-TVB`,
`keyfobdemo 01-AUTO-TVB`, `keyfobdemo 02-AUTO-TVB`) had real channel-38
examples mixed into TRAIN/VALIDATION/TEST — 1,995 / 2,646 / 2,696 / 1,481
examples respectively, now excluded and recorded on each split's own
`channel_scope_excluded_example_ids` field. The excluded examples are never
deleted — they remain in `evidence/*/examples.jsonl`, available to a future,
distinct channel-transport analysis (RQ4-adjacent, not yet implemented) —
this is a scoping decision for the current benchmark, not a data-retention
decision. See §16.3 for the full correction and §16.9 for the migration
ledger entries this produced.

**Quality gate** (`DatasetQualityReport`, `contracts/quality_report.py`):
`ExactDuplicatesResult`, `SampleOverlapResult` (both real, blocking checks),
and `NearDuplicateResult` — explicitly typed as
`Literal["DIAGNOSTIC_CHECK", "NOT_EXECUTED"]` only, "per design correction
#12", i.e. **near-duplicate detection structurally cannot be a blocking
gate** in the current schema, by design, not by omission.
`GateDecision = ACCEPTED_FOR_TRAINING | ACCEPTED_WITH_LIMITATIONS |
NOT_ACCEPTED_FOR_TRAINING`. Real aggregate across all 34 quality reports
ever generated: 32 `ACCEPTED_FOR_TRAINING`, 2 `NOT_ACCEPTED_FOR_TRAINING`,
**0 `ACCEPTED_WITH_LIMITATIONS`** — that middle state is schema-representable
but has never actually been assigned in this corpus.

---

## 9. Real BLE models actually available

**[2026-08-09 correction]** `ModelType` (`contracts/training.py`) now has
**six** values, not five: `logistic_regression`, `svm_rbf`, `random_forest`,
`cnn1d`, `cnn2d`, and `frozen_morphological_baseline` (added as RQ2's 4th
representation branch — a frozen, non-iterative nearest-centroid classifier
over an L2-normalized coarse time-frequency representation,
`training/frozen_reference_baseline.py`; deliberately not a copy of
`rf_experiment_lab`'s E0, which is a region detector, not a
device-fingerprinting baseline). **No other architecture is implemented,
UI-exposed, or planned for BLE-RFFI Studio** — in particular, no
Transformer, no ResNet variant, no MFCC/LFCC representation exists inside
this module (those specific not-implemented items belong to
`rf_experiment_lab`'s E1/E5, a different module — see §1).

| Model type | Backing implementation | Representation |
|---|---|---|
| `logistic_regression` | sklearn `LogisticRegression` | 10-dim hand-crafted `feature_vector-v1` (`mean_power_dbfs, std_power_db, mean_abs_amplitude, std_abs_amplitude, spectral_centroid_hz, spectral_bandwidth_hz, cfo_estimate_hz, papr_db, amplitude_kurtosis, amplitude_skewness`), scaled via `TrainOnlyScaler` |
| `svm_rbf` | sklearn `SVC(kernel="rbf", probability=True)` | same as above |
| `random_forest` | sklearn `RandomForestClassifier` | same as above |
| `cnn1d` | custom 2-conv-layer `nn.Module` | raw IQ, `raw_iq-v1`, shape `[2, 800]` |
| `cnn2d` | custom 2-conv-layer `nn.Module` | `spectrogram-v1` — **docstring says one-sided `[1, n_fft//2+1, target_frames]`, but `scipy.signal.stft(..., return_onesided=False)` actually produces a two-sided `[1,64,32]` tensor** — a real code/docstring discrepancy, not corrected here |

**[2026-08-09 correction]** `random_seed=42` is no longer a bare literal:
`FROZEN_TRAINING_SEEDS = (42, 137, 2024)` (`api/studio_repository.py`) is a
real, explicit, frozen seed SET. `42` (the set's first element) is still
what every normal training run uses — unchanged real behavior — while
`train_seed_variability_analysis()` retrains the same configuration under
the other two frozen seeds, VALIDATION-only, real per-run results, never
opening TEST. IMPLEMENTED and tested (§16.9); **no real optimization-
variability report over a definitive campaign has been produced from it
yet** — the 173 real `TrainingRun` records below all still used only the
single seed `42`, since seed-variability analysis is a distinct, separately
invoked diagnostic, not run automatically by `prepare_and_train`.

Currently exported and `APPROVED_FOR_LIVE_PILOT`: **27 bundles**, all
trained before the 6th architecture (§9's 2026-08-09 correction, above)
existed — 25 are all 5 architectures × 5 real physical devices
(`CC2541SensorTag`,
`CC2650-UNIT-01`, `SHELLY-PLUG-01` [scrubbed-background dataset only, see
§12], `keyfobdemo 01`, `keyfobdemo 02`); the remaining 2
(`TRAIN-20260803T144755-SHELLY-PLUG-01-random_forest`/`-svm_rbf`) are a
second, independent training run over the same `SHELLY-PLUG-01`
scrubbed-background dataset, produced via the Training Service's explicit
dataset+model-selection flow rather than the automatic per-device flow, and
carry their own separate `training_run_id`s. Every one of the 27 has a
real, on-disk TEST
evaluation — 5 via `test_evaluation_provenance=SINGLE_SELECTION_GUARANTEE`
(the one model `prepare_and_train`/`train_selected_models` itself picked),
22 via `OPT_IN_MULTI_CANDIDATE_COMPARISON` (operator explicitly chose to
TEST-evaluate a non-recommended candidate too, permanently tagged as such
on the bundle — never silently indistinguishable from the guarantee).
`data_origin=REAL_B200` and `operational_use=ALLOWED` on all 27 — no
synthetic-origin bundle exists among them (`SYNTHETIC_PIPELINE_VERIFIED` is
a structural ceiling: `BundleBuilder` never assigns `EVALUATED` to a
synthetic-origin bundle, so one cannot reach `APPROVED_FOR_LIVE_PILOT`,
`contracts/bundle.py:11-14`).

**Externally evaluated**: none — `NOT DOCUMENTED — requires experimental
confirmation` for any evaluation performed outside this repository's own
TEST-split mechanism.

---

## 10. Comparability conditions between model comparisons

Two models are only directly comparable on their TEST numbers when **all**
of the following hold, per what the code actually enforces/records:

1. Same frozen `dataset_id`/`dataset_version` (same `class_distribution`,
   same `dataset_manifest_sha256`).
2. Same `split_manifest_sha256` (same TRAIN/VALIDATION/TEST assignment —
   the leakage-disjointness fields in §8, not day/receiver/channel).
3. Same `scientific_task`.
4. `evaluation_validity=VALID` on both `evaluation_report.json`s (present
   in every real report inspected for this document).

**Not held constant across the 27 real bundles**: TEST-set size varies
substantially by device (e.g. `CC2650-UNIT-01` TEST n=384 vs.
`SHELLY-PLUG-01`-scrubbed TEST n=122) — comparing macro-F1 across devices
is therefore comparing runs with materially different statistical power,
and that difference is never normalized or flagged automatically anywhere
in the pipeline. Any cross-device comparison in this document or the README
should be read device-by-device, not as a ranked leaderboard.

---

## 11. Offline vs. live-spectrum inference semantics

The **same** `OfflineInferenceService._representation()`/`_predict_proba()`
code path is genuinely shared between offline (`run()`) and live
(`run_live()`) inference (`offline_inference.py`) — this is a real,
verified code-sharing fact, not a documentation claim without backing.

**Live-spectrum inference** (never called "real-time" in this document,
per the constraint below) scores a burst selected by one of two window
strategies: a raw energy-threshold burst (median/MAD noise floor) by
default, or — only when `BLE_LIVE_DECODE_ENABLED=true` (default `false`) —
a packet-decode-aligned window via the Gate 2A.2 decoder, falling back
silently to the raw-energy window if decoding is unavailable.
`acceptance_threshold` is calibrated on VALIDATION only
(`calibrate_unknown_threshold()`, maximizing recall subject to
precision≥0.9).

**Why "real-time" is not used anywhere in this document**: that term would
require a stated deadline, measured latency, measured throughput, and a
measured dropped-window rate, plus an offline-vs-live agreement
reconciliation. None of these exist in code:

- **No latency-measurement code exists for the live inference path** (only
  an offline VALIDATION-latency benchmark used purely for model-comparison
  scoring, unrelated to the live path).
- **No dropped-window counter exists** — the pending-burst slot is a single
  overwrite-on-newer slot, explicitly uncounted.
- **No offline-vs-live agreement-reconciliation code exists** anywhere in
  the module.

This document therefore uses **"online experimental inference"** or
**"live-spectrum inference"** exclusively for this capability, matching the
banned-terms constraint.

Decision values actually returned by the live path: `IDENTIFIED`,
`UNKNOWN`, `INSUFFICIENT_EVIDENCE` (shared with offline, from `Evaluator`),
plus live-path-specific `SAMPLE_RATE_MISMATCH`, `NO_BLE_PACKET_DECODED`,
`LIVE_ACQUISITION_INCOMPATIBLE_WITH_BUNDLE`.

---

## 12. BLE Experimental Evidence Available in the Repository

Real executions only — favorable, unfavorable, and ambiguous alike. All
numbers below were read directly from on-disk artifacts on 2026-08-05.

| Execution | Task | Dataset (frozen) | Split | Result | Artifact |
|---|---|---|---|---|---|
| `CC2650-UNIT-01` — 5 candidates | `TARGET_VS_BACKGROUND` | `CC2650-UNIT-01-AUTO-TVB__20260801T185545` (class_distribution: `CC2650-UNIT-01`=1,796, `UNKNOWN`=8,505) | `READY` | Best TEST: `cnn2d` macro_f1=1.000 (n=384); worst: `svm_rbf` macro_f1=0.917 (n=384) | `bundles/CC2650-UNIT-01-*-bundle/evaluation_report.json` |
| `CC2541SensorTag` — 5 candidates | `TARGET_VS_BACKGROUND` | `CC2541SensorTag-AUTO-TVB__20260801T221949` (class_distribution: `CC2541SensorTag`=1,199, `UNKNOWN`=6,927) | `READY` | Best TEST: `cnn2d` macro_f1=0.959 (n=348); worst: `cnn1d` macro_f1=0.499 (near-chance) | `bundles/CC2541SensorTag-*-bundle/evaluation_report.json` |
| `keyfobdemo 01` — 5 candidates | `TARGET_VS_BACKGROUND` | `keyfobdemo 01-AUTO-TVB__20260801T185108` (class_distribution: `keyfobdemo 01`=5,763, `UNKNOWN`=9,699) | `READY` | Best TEST: `random_forest` macro_f1=0.874 (n=592); worst: `svm_rbf` macro_f1=0.432 (near-chance) | `bundles/keyfobdemo01-*-bundle/evaluation_report.json` |
| `keyfobdemo 02` — 5 candidates | `TARGET_VS_BACKGROUND` | `keyfobdemo 02-AUTO-TVB__20260801T185405` (class_distribution: `keyfobdemo 02`=1,442, `UNKNOWN`=7,467) | `READY` | Best TEST: `logistic_regression` macro_f1=0.987 (n=330); worst: `cnn1d` macro_f1=0.429 (near-chance) | `bundles/keyfobdemo02-*-bundle/evaluation_report.json` |
| `SHELLY-PLUG-01`, original (unscrubbed) background, round 1 | `TARGET_VS_BACKGROUND` | `SHELLY-PLUG-01-ORIGINAL-BG-TVB__20260803T115411` | `NOT_FEASIBLE` (leakage on `capture_id, execution_id, session_id`) | **No model trained** — the contaminated capture contributed an example to both classes simultaneously | `splits/SHELLY-PLUG-01-ORIGINAL-BG-TVB__20260803T115411...json` |
| `SHELLY-PLUG-01`, original (unscrubbed) background, round 2 (8 sessions) | `TARGET_VS_BACKGROUND` | `SHELLY-PLUG-01-ORIGINAL-BG-TVB__20260803T130001` | `NOT_FEASIBLE` (same reason, confirming contamination, not session count, was the cause) | **No model trained** | `splits/SHELLY-PLUG-01-ORIGINAL-BG-TVB__20260803T130001...json` |
| `SHELLY-PLUG-01`, scrubbed background, round 1 (3 sessions) | `TARGET_VS_BACKGROUND` | `SHELLY-PLUG-01-SCRUBBED-BG-TVB__20260803T115411` (n=122 TEST) | `READY` | All 5 candidates trained; none met `prepare_and_train`'s own VALIDATION acceptance thresholds (`macro_f1≥0.5, balanced_accuracy≥0.5`) — reported `NO_MODEL_ACCEPTED`, all 5 still exported. Real TEST: `random_forest` macro_f1≈0.21 (best), others ≈0.10 | `backend/README.md:1034-1045` |
| `SHELLY-PLUG-01`, scrubbed background, round 2 (8 sessions) | `TARGET_VS_BACKGROUND` | `SHELLY-PLUG-01-SCRUBBED-BG-TVB__20260803T130001` (n=122 TEST) | `READY` | `random_forest` macro_f1=1.000, `svm_rbf`=0.945, `logistic_regression`=0.832, `cnn1d`=0.470, `cnn2d`=0.433 | `bundles/SHELLY-PLUG-01-SCRUBBED-BG-*-bundle/evaluation_report.json` |
| `SHELLY-PLUG-01` live-spectrum check, `random_forest`, `acceptance_threshold=0.7` | live-spectrum inference | (bundle above) | n/a | 6/10 real live samples returned `IDENTIFIED, identified_device: SHELLY-PLUG-01` (confidence 0.68–0.71); 4/10 sat just under threshold | `backend/README.md:1080-1089` |
| `E0` morphological baseline | region detection (not BLE-specific) | n/a | n/a | 1 real region detected; **no ground truth supplied**, IoU/precision/recall = `null` | `rf_experiment_lab/results/exp_region_morphological_baseline_v1/20260501T153202Z/metrics.json` |
| `E1` raw-IQ CNN1D | closed-set fingerprinting (not BLE-specific) | n/a | n/a | `accuracy=0.0, macro_f1=0.0`, single-class collapse on real data | `rf_experiment_lab/results/e1_raw_iq_cnn1d/20260502T231159233923Z/metrics.json` |
| `E3` spectrogram CNN2D | closed-set fingerprinting (not BLE-specific) | n/a | n/a | `accuracy=0.0, macro_f1=0.0`, same collapse pattern | `rf_experiment_lab/results/e3_spectrogram_cnn2d/20260502T231313943275Z/metrics.json` |
| `E5` PSD classical ML | classification (not BLE-specific) | n/a | n/a | Best of 6 runs: `accuracy=1.0` on 2 TEST samples of 1 class — not generalization evidence | `rf_experiment_lab/results/e5_spectral_feature_baseline/*/metrics.json` |

---

## 13. Reproducibility requirements

**Environment**: the *only* Python environment on this machine with the
full dependency set (`pydantic`, `torch`, `scikit-learn`, `pytest`) is
`backend/.venv-validation/`. Confirmed directly: system Python and two
other local environments (`radioconda`, `anaconda3`, `backend/venv/`) each
fail to even *collect* the BLE-RFFI Studio test suite with
`ModuleNotFoundError` for one dependency or another. All commands below
assume `backend/.venv-validation/Scripts/python.exe`.

**Automated reproduction** (fastest, does not require B200 hardware):

```
cd backend
./.venv-validation/Scripts/python.exe -m pytest app/tests/unit/ble_rffi_studio/
```

236 tests collect cleanly under this environment as of commit `5f1ddbba`.

**Full real-hardware reproduction sequence** (requires a USRP B200 and the
target BLE device physically present):

1. Register/select the target `physical_unit_id` in the Physical Device
   Registry (`/ble-rffi-studio` UI, or `POST` to the registry route).
2. Launch a `TARGET_DEVICE_ON` capture (device powered on, ~10 s, channel
   37/38/39, 20 dB gain, RX2 — see §4) via the Guided flow or
   `CampaignOrchestrator`.
3. Launch matching `BACKGROUND_TARGET_OFF` or `BACKGROUND_GENERAL`
   captures for negative evidence (§7).
4. Run offline replay for each capture (`BleOfflineReplayService`) —
   produces `replay_final_report.json` with `iq_sha256`,
   `decoder_version`/`worker_version` git commit hashes of the external
   `ble-worker-lab` repo, and `scientific_decision`.
5. Build the dataset (`StudioRepository.build_dataset`), which runs the
   quality gate.
6. Build the split (`StudioRepository.build_split`,
   `scientific_task=TARGET_VS_BACKGROUND`), which runs the leakage check.
7. Train (`train_selected_models` / `prepare_and_train`), export
   (`export_and_approve_all_candidates`).
8. Optionally run the live-spectrum health check or multi-device watching
   against the exported bundle.

**What gets versioned / hashed, enabling a score to be traced back to raw
IQ** (see §3's linking-ID list): `iq_sha256`, `candidate_id`,
`packet_id`/`packet_sha256`, `example_id`, `dataset_manifest_sha256`,
`split_manifest_sha256`, `training_run_id`, `bundle_id`,
`bundle_sha256`/`artifact_hashes` (per-file SHA-256 inside each bundle),
plus `decoder_version`/`worker_version` (external repo commit hash) and
this repository's own commit hash at documentation time (`5f1ddbba`).

**Not currently versioned**: the external `ble-worker-lab` repository's
full dependency/environment specification is `NOT DOCUMENTED — requires
experimental confirmation` from within `spectrum-lab` itself (it is a
sibling repo, referenced only by path, never pinned to a commit inside
`spectrum-lab`'s own manifests).

---

## 14. Current Scientific Scope

BLE-RFFI Studio's real evidence, as of commit `5f1ddbba` (2026-08-05),
covers: **5 physical BLE devices** (`CC2541SensorTag`, `CC2650-UNIT-01`,
`SHELLY-PLUG-01`, `keyfobdemo 01`, `keyfobdemo 02`), **1 receiver**
(USRP B200, serial `E3R04Z1B2`), across **146 real+synthetic capture
sessions spanning 2026-07-28 to 2026-08-03**, all recorded at a single
physical location on a single set of RF hardware.

**[2026-08-09 correction]** The channel claim above ("1 BLE channel per
device's training set, no dataset currently mixes...") was **checked and
found false** for the frozen `DatasetManifest`s themselves — real channel-38
examples were present and, before this correction, were being assigned into
TRAIN/VALIDATION/TEST by `SplitBuilder`. The dataset-level composition is
unchanged (datasets are frozen, never rewritten), but the *split* is now
channel-37-only by policy for the main benchmark — see §8 and §16.3. Every
trained-and-exported model's TRAIN/VALIDATION/TEST split is disjoint on the
fields listed in §8 (capture/execution/session/candidate/packet/sample-range)
AND, since 2026-08-09, scoped to channel 37 only — not on day or receiver,
because no dataset currently spans more than one receiver, and a day-disjoint
requirement was never part of any of the four `ScientificTask` designs (see
§16.3). No population, receiver, or channel generalization claim is made
anywhere in this document or the README, and none is currently measurable
from the evidence on disk.

---

## 15. Industry 5.0 / forensics framing

Per the required template: *BLE-RFFI Studio implements a real, end-to-end
capture-to-inference pipeline against genuine USRP B200 acquisitions, with
per-device classification scores traceable to raw IQ; it does not currently
constitute a deployed industrial identification system, and no output of
this pipeline should be read as forensic attribution without an explicit
population definition, a stated set of alternative-source propositions, and
an independent validation study — none of which exist for this module as
of this document.* No score produced by any bundle in §9/§12 is called an
"attribution" anywhere in this document, consistent with that constraint.

---

## 16. 2026-08-09 correction pass — protocol-adaptation and scientific-rigor fixes

A real, substantial correction pass over the working tree (not yet
committed as of this writing — HEAD is `0d00bb7f`). Every item below
follows the same `IMPLEMENTED` vs. `EXPERIMENTALLY VALIDATED` distinction
the rest of this document already uses: **IMPLEMENTED** means the code
exists, is wired into the real pipeline, and has real tests passing.
**EXPERIMENTALLY VALIDATED** means, additionally, that a real campaign was
run and produced evidence meeting an explicit, stated criterion.
Implementation is never described as validation anywhere below.

### 16.1 Confirmatory-evaluation discipline (TRAIN → VALIDATION → FREEZE → FUTURE TEST)

**IMPLEMENTED.** `export_and_approve_all_candidates` no longer opens TEST
for any non-recommended candidate — model selection uses VALIDATION only;
TEST opens exactly once, for the VALIDATION-recommended candidate, via
`_freeze_and_log_test_access`, which freezes a real
`ble_scientific_results.AnalysisContract` (capturing the run's actual
frozen seed/dataset/split hashes, never a placeholder) and appends a real,
hash-chained entry to `ble_scientific_results`'s holdout access log —
independently verifiable via `verify_holdout_access_chain()`. A
`ModelBundleManifest.confirmatory_eligible` field now exists and is
enforced by `approve_for_live_pilot`: a bundle whose TEST evaluation is
`OPT_IN_MULTI_CANDIDATE_COMPARISON` (an operator explicitly comparing
several candidates against TEST) can never be approved for live pilot use,
and is never presented as confirmatory evidence.

**Real migration of the 22 already-exported `OPT_IN_MULTI_CANDIDATE_
COMPARISON` bundles**: all 22 remain `APPROVED_FOR_LIVE_PILOT` (status
preserved, per an explicit decision not to revoke already-approved bundles)
but now carry `confirmatory_eligible=False`, permanently. **These 22
bundles must not be read as confirmatory evidence for any paper-level
claim** — they were multiple-comparison-exposed to TEST by design, a real,
documented statistical caveat, not a defect being hidden. 5 bundles (one
per real device, the actual VALIDATION-recommended candidate in each case)
carry `confirmatory_eligible=True`.

**EXPERIMENTALLY VALIDATED**: the mechanism itself — verified against real
training runs (5 new tests, `test_export_and_approve_all_candidates.py`)
and the real 27-bundle migration. **NOT experimentally validated**: no
paper-level confirmatory result has been produced through this mechanism
yet — that requires a real, definitive campaign run, not yet executed.

### 16.2 Association-policy hash — see §5's 2026-08-09 addition

Unchanged summary: **IMPLEMENTED, fail-closed, verified**.
`association_policy_hash` on a frozen `AnalysisContract` now reflects a real
calibrated `AssociationPolicy` when one exists (prefixed
`NO_CALIBRATED_POLICY_YET:` otherwise, honestly) instead of a bare
source-code hash. **No such policy currently exists** — 0/4 real
calibration attempts reached `FROZEN`. Strong, source-corroborated
association remains structurally disabled until one does.

### 16.3 Split policy: channel scope, split completeness, and no indiscriminate leakage fields

**IMPLEMENTED.** `SplitBuilder` now excludes non-channel-37 examples before
building any of the four `ScientificTask` splits — a scoped **split
policy**, deliberately not a blanket leakage-field addition (day and
receiver disjointness were deliberately NOT added as leakage fields: this
is a single-receiver study, and no `ScientificTask` design requires
day-disjointness). See §8's 2026-08-09 correction for the real, on-disk
finding this produced (4 datasets had channel-38 examples mixed into
TRAIN/VALIDATION/TEST). A new, independent gate also now rejects a split
where VALIDATION or TEST is missing real support for a class TRAIN has
(`SPLIT_INCOMPLETE_MISSING_CLASS_SUPPORT`) — `balanced_accuracy`/`macro_f1`
formulas themselves are unchanged (a missing class is treated as an
incomplete split, never papered over by excluding it from the metric).

**EXPERIMENTALLY VALIDATED**: the channel-scope exclusion, against the 4
real datasets above (real, on-disk before/after counts). The
split-completeness gate has not yet rejected any real split (every
currently-READY split already had full class coverage by construction) —
its correctness is unit-tested, not yet exercised by a real rejection.

### 16.4 `receiver_epoch` — identity, qualified acquisition profile, and session boundary

**IMPLEMENTED.** Three real, separate fields replace the old bare-hash
`receiver_epoch`: `receiver_identity_id` (canonical physical receiver —
SDR model + real hardware serial ONLY, never the legacy `device_id` field),
`qualified_acquisition_profile_hash` (every acquisition-chain parameter
that can plausibly change what the receiver measures: sample rate,
bandwidth, gain/mode, antenna/RX channel, clock/time source, capture-tool
version), and `receiver_epoch` itself — a sequential session id, assigned
by `acquisition/receiver_epoch_assignment.py` over every real capture of
one identity, ordered by acquisition time. A new epoch starts at the first
capture of an identity, whenever the qualified profile hash changes, or
whenever the gap since the previous capture of the same identity exceeds
`RECEIVER_SESSION_GAP_S = 3600.0` seconds — **a documented proxy for
reinitialization/reconnection, not direct physical evidence of a B200
restart**: no field anywhere in the legacy `capture_manifest.json` records
a real USRP boot/session id. The threshold is not an arbitrary guess: of
154 real captures (single physical serial `E3R04Z1B2`), exactly 9 gaps
exceed 1 hour (from ~1.7h to ~4 days), consistent with real distinct
capture-day boundaries in this campaign's actual history.

**Real bug found and fixed**: the previous `receiver_epoch` used the
legacy `device_id` field, which real data showed inconsistently held either
a normalized/hashed id (133 captures) or the raw hardware serial (11
captures) for the **same physical B200** — silently splitting one real
receiver into two epochs with no real hardware event behind the split.
`migrate_v3_receiver_epoch.py`, run for real against the on-disk corpus:
**144 real captures unified under 1 receiver identity, resolving into 10
real sequential sessions** (previously: 2 spurious identities). Verified
idempotent (a second run makes 0 further changes).

**EXPERIMENTALLY VALIDATED**: the identity-unification fix, against the
real 144-capture corpus. **NOT experimentally validated**: the
session-gap proxy's correspondence to genuine B200 reinitialization events
— that would require a real capture campaign with logged, ground-truth
restart timestamps to compare against, which does not exist. RQ3's
PRE/POST pairing (§16.6) inherits this same limitation.

### 16.5 `day_id` — real RF-acquisition timestamp, not job-start time

**[correction to a distinction §4/§14 did not previously draw]**
`day_id` is now derived from `capture_manifest.json`'s real
`b200_rf_started_at` field (the actual RF-sampling start) when present,
falling back to `created_at_utc` (the acquisition job's own start time,
which real data shows can precede real RF sampling by several seconds)
only when `b200_rf_started_at` is absent. `day_id_source` is persisted
(`B200_RF_STARTED_AT` / `CREATED_AT_FALLBACK` / `MANIFEST_DECLARED`) so the
provenance is auditable. **Checked against all 148 real captures with both
fields**: 0 produce a different calendar day under the old vs. new source —
the historical `day_id` values were never actually wrong for this corpus,
only derived from the less-precise field by design; no historical rewrite
was needed or performed.

### 16.6 RQ3 infrastructure — device-day PRE/POST pairing

**IMPLEMENTED, no real pairs yet.** `campaign/pre_post_pairing.py` pairs a
physical unit's PRE and POST captures within one device-day and
intervention arm (RESET/CONTROL), invalidating a pair when
`receiver_epoch` differs between the two captures (or, when supplied, when
the qualified preprocessing profile differs) — real, tested logic (10
tests), including the exact real "same B200, spurious split" scenario from
§16.4. **`campaign_period`/`pre_or_post`/`intervention_arm`/`packet_variant`
remain undeclared on every real capture in the corpus** (0/150) — these
fields have no derivation fallback (nothing else recorded implies a real
intervention/arm), matching the same honest gap already documented for
`campaign_period` elsewhere in this document. Confirmed directly:
`build_pre_post_pairs()` against the real 150-capture corpus returns `[]`.
**A definitive PRE/RESET/POST vs. PRE/CONTINUOUS/POST campaign has not been
run.** See §16.4's limitation note — the receiver-epoch invalidation this
pairing relies on uses the same session-gap proxy, not confirmed restart
evidence.

### 16.7 RQ4 infrastructure — FULL_BURST / ADVA_EXCLUDED / PRE_PDU

**IMPLEMENTED, no definitive campaign yet.**
`packet_content/field_mapping.py` derives, from the same original I/Q a
burst's `ExampleRecord` already points to: `FULL_BURST` (the original
window, byte-for-byte, never mutated), `PRE_PDU` (preamble + access
address only, ending exactly where the PDU header starts — unchanged from
before, verified against the real BLE field layout), and `ADVA_EXCLUDED`
(the AdvA sample range **genuinely spliced out** — `np.concatenate` of the
samples before and after it, producing a shorter array). This corrects a
real design flaw caught during review: an earlier `ADVA_MASKED` variant
zero-filled the AdvA range in place, leaving a fixed-size, fixed-position,
exactly-zero block in every masked burst — itself a trivially learnable
digital artifact, unrelated to any RF fingerprint. The shorter
`ADVA_EXCLUDED` window's length is recovered by the SAME zero-pad-at-end
convention every representation function already applies to any short
window (`REPRESENTATION_OWN_ZERO_PAD_AT_END`) — no special-casing, no mask
channel or flag marking where the exclusion happened. `adv_address`
(hence `ADVA_EXCLUDED`) is `None` for any PDU type outside
`{ADV_IND, ADV_NONCONN_IND, ADV_SCAN_IND, ADV_DIRECT_IND, SCAN_RSP}` —
`pdu_type_name` is read from the same `packet_association_ledger.jsonl`
row the real decoder already produced, never assumed. 14 tests
(`test_packet_content.py`). **No RQ2-style common benchmark comparing
FULL_BURST/ADVA_EXCLUDED/PRE_PDU has been run against real data.**

### 16.8 Decision windows, abstention, and coverage/risk-coverage

**IMPLEMENTED, no definitive campaign yet.**
`OfflineInferenceService.run_decision_windows()` groups examples into real
time windows (the same formula `ble_scientific_results`'s own accounting
already uses), scores every burst with the bundle's existing frozen model
(never a second scoring path), aggregates each window by a declared,
frozen rule (median probability per class — robust to one outlier burst,
no fitted combination weights), and applies the bundle's own calibrated
`acceptance_threshold` to the aggregated distribution. A window with fewer
than `minimum_eligible_bursts` scored bursts abstains
(`INSUFFICIENT_EVIDENCE`) before the threshold check ever runs. Real,
previously-production-unused statistical primitives are now wired to real
results: `risk_coverage_curve` → `SplitEvaluationReport.risk_coverage`
(per-split, sweeping every achievable confidence threshold);
`hierarchical_cluster_bootstrap` → `StudioRepository.bootstrap_accuracy_ci`
(a session-clustered percentile CI — resampling whole sessions, never
individual bursts, matching the same clustering unit the leakage check
itself uses). 11 tests across both. **No real decision-window campaign or
coverage/risk-coverage report over a definitive real evaluation has been
produced** — these are real, tested capabilities exercised so far only
against synthetic fixtures and existing training-run predictions, not a
purpose-run campaign.

### 16.9 Fixed seed set and inference provenance manifest

**IMPLEMENTED.** `FROZEN_TRAINING_SEEDS = (42, 137, 2024)` replaces the
previous bare, uncontextualized `random_seed=42` literal — the first
element is still what every normal training run uses (unchanged behavior),
while `train_seed_variability_analysis()` retrains the same configuration
under the other frozen seeds, VALIDATION-only (never opens TEST for a
seed-variability run — verified directly: `analysis_contract_protocol_id`
stays `None` on every seed-variant run). Every real offline inference run
now produces a persisted manifest (`inference_runs/<id>.json`) binding the
real bundle content hash (`bundle_sha256`) and the real source capture's
`iq_sha256` to every prediction — closing a real, previously-true finding
that "the provenance chain terminates at the model." 9 tests across both.

### 16.10 Migration-provenance ledger

**IMPLEMENTED.** `migrations/migration_ledger.py` provides a general,
append-only audit mechanism (`migration_id`, `migration_version`,
`timestamp_utc`, `code_revision` — a real `git rev-parse HEAD`,
`artifact_type`, `artifact_id`, `field`, `old_value`, `new_value`,
`reason`, `migration_tool`, `status`, `retroactive`) — every migration
script in this correction pass uses it. Real counts on the current corpus:
**150 real, non-retroactive entries** (`migrate_v3_receiver_epoch.py`) plus
**214 retroactively reconstructed entries**, explicitly flagged
`retroactive: true`, for the 5 real migrations performed earlier in this
same correction pass before this ledger existed (6 synthetic-capture
frequency corrections, 150 `day_id` backfills, 4 split regenerations, 27
`confirmatory_eligible` additions, 27 `resolved_flags` additions). **The
retroactive entries' `timestamp_utc` is each artifact file's own real
on-disk modification time — a documented proxy for when the edit actually
happened, not the exact original instant** (which was not captured at the
time, since the ledger did not yet exist). No I/Q file was ever written by
any migration in this pass, confirmed directly (every migration script only
opens `.json`/`.jsonl` metadata files).

### 16.11 Test suite state

`714 passed, 38 skipped` (full backend suite) at the time of this section.
**18 pre-existing failures are unrelated to this correction pass** —
`rf_experiment_lab` integration tests, `test_rf_intelligence.py`, and
`test_ti_cc2650_sensortag.py` — confirmed via `git status` (none of their
underlying modules were touched) and by reproducing the same 18 failures in
complete isolation from every other test file. **One known flaky test**,
`test_run_frozen_reference_baseline_trains_and_beats_chance_on_separable_
synthetic_data` (RQ2's frozen-baseline branch, §9): passes reliably in
isolation (confirmed 3/3), fails intermittently only in full-suite runs —
apparent test-order-dependent RNG interaction in the shared synthetic-data
helper, not yet root-caused. **This is real, open technical debt, tracked
here explicitly rather than hidden — it should be resolved before any
capability described in this document is treated as ready for a frozen,
citable release, but does not block the correction-pass work itself.**

**None of the passing test counts above is evidence of scientific
validation** — they confirm the code does what its own tests assert, not
that a real campaign produced a result meeting the four RQs' scientific
criteria. See the root README's Current scientific status table for what
"EXPERIMENTALLY VALIDATED" requires beyond a passing test suite.

### 16.12 Preprocessing profiles: `paper-eq6-7-v1`, `offset-retaining-v1`, `cfo-compensated-v1` (legacy)

**Correction: this section was missing from this document until now**,
despite being summarized in the root README and derived in full in
[`docs/ble/PREPROCESSING.md`](PREPROCESSING.md) — added here so this
document's own claim to be "the complete evidence-to-decision trace" holds.

`preprocessing/paper_compliant_cfo.py` implements the paper's real
Eq.(6)-(7): a frozen BLE reference waveform `q[n]`, `z_b[n] = x_b[n]·q*[n]`,
unwrapped phase `ψ_b[n]`, a frozen fitting interval `I_b` (the burst's own
`PRE_PDU` span), a real joint least-squares estimate of `(φ_b0, f_b)` via
`np.linalg.lstsq`, and affine compensation
`x̃_b[n] = x_b[n]·exp(-j(φ_b0 + 2π·f_b·n/Fs))` applied to the whole burst.
Per-burst provenance (reference-waveform hash, `I_b`, `φ_b0`, `f_b`,
`compensation_status`) is persisted for every TRAIN example and every
inference decision, via one shared function
(`apply_base_preprocessing_with_provenance`) — never two implementations.
Registered as profile `paper-eq6-7-v1`; `offset-retaining-v1` is the
identical pipeline with the offset deliberately left uncompensated, for
sensitivity analysis. The older, simpler `cfo-compensated-v1` (mean
phase-step CFO + first-sample phase zeroing) remains available for
historical/ablation use only and is explicitly labeled
**heuristic/legacy** — no reference waveform, no frozen `I_b`, no joint
regression, no per-burst persisted parameters, and it must never be
described as Eq.(6)-(7).

IMPLEMENTED AND TESTED (injected-known-offset recovery of `φ_b0`/`f_b` to
~1e-6 rad / ~1 Hz). **No definitive model bundle has been trained under
`paper-eq6-7-v1` by a real campaign yet.**

---

## 17. Association semantics, eligibility, decision windows, campaign runner, holdout groups, and Guided Validation

This section documents a round of `ble_scientific_results`/`ble_rffi_studio`
work that predates §16 chronologically but was not yet written up here.
IMPLEMENTED/EXPERIMENTALLY VALIDATED distinction as everywhere else in this
document.

### 17.1 Association semantics (`ble_scientific_results/records/burst_records.py`)

`BurstClass` is now `SOURCE_CONTEXT_ONLY | CRC_VALID_PACKET |
TARGET_ASSOCIATED_PACKET` (`contracts/record_contracts.py`).
`_passes_target_association_criterion` requires ALL of: a real frozen
`AssociationPolicy` (else always `False`), `association_strength=="STRONG"`,
`address_match_status=="MATCHED"`, no `association_rejection_reason`,
`target_address_match is True`, `time_delta_ms <= policy.threshold_ms`. A
resolved `physical_unit_id` alone (e.g. via `PHYSICAL_ISOLATION_DECLARED`)
now produces `SOURCE_CONTEXT_ONLY` with `source_identity_origin=
OPERATOR_CONTEXT_DECLARED`, never `TARGET_ASSOCIATED_PACKET` -- the
`label_authority` field records the exact rule text that decided each row.
IMPLEMENTED AND TESTED; unchanged bottom line, still 0 STRONG (§16.2, §17.10).

### 17.2 Eligibility vs. diagnostics split

`ScientificCaptureRecord`: `capture_eligible`, `blocking_reason_codes`,
`diagnostic_flags` (old `eligible`/`exclusion_reason_codes` removed).
`ScientificBurstRecord`: `packet_eligible`, `label_eligible`,
`training_eligible`, `blocking_reason_codes`, `diagnostic_flags`. A
technical blocker (no CRC, capture excluded) is a `blocking_reason_code`;
a quality/ambiguity note on an already-usable row (e.g.
`STRONG_ASSOCIATION_DISABLED_UNTIL_POLICY_FROZEN`) is a `diagnostic_flag`
and never blocks eligibility by itself. IMPLEMENTED AND TESTED.

### 17.3 Protocol-deviation classification

`ScientificCampaignDeviationRecord.classification` is
`CANDIDATE_EXCLUSION | CAPTURE_EXCLUSION | PROTOCOL_DEVIATION`.
`CAPTURE_EXCLUSION`: `OVERFLOW`, `DISCONTINUITY`, `METADATA_INCOMPLETE`.
`PROTOCOL_DEVIATION`: `DUPLICATE_CAPTURE`, `CAPTURE_NOT_FOUND`,
`SPLIT_CONFLICT`, `NOT_DOCUMENTED_DESIGN_DIMENSION`, plus real runner-
rejection codes from `paper_campaign_runner.py`: `CAPTURE_OUT_OF_SCHEDULE`,
`WRONG_CAPTURE_ORDER`, `WRONG_UNIT`, `WRONG_CHANNEL`,
`WRONG_PRE_POST_STATE`, `WRONG_INTERVENTION_ARM`, `WRONG_PACKET_VARIANT`,
`RECEIVER_EPOCH_MISMATCH`, `FIRMWARE_MISMATCH`, `CONFIGURATION_MISMATCH`.
`CANDIDATE_EXCLUSION` is declared in the type but not currently emitted as
a deviation row -- that case lives only as a `diagnostic_flag` on the burst
record (§17.2). **Correction**: `campaign_deviations.py`'s own module
docstring lists a slightly different, aspirational set of runner-rejection
code names (`WRONG_ACQUISITION_ORDER`, `UNIT_WRONG_ARM`,
`RECEIVER_EPOCH_NOT_ALLOWED`, `INTERVENTION_NOT_EXECUTED`,
`EARLY_HOLDOUT_ACCESS`, `CHANNEL_OR_VARIANT_MISMATCH`) that do not exist in
code -- the real names are the ones listed above; the docstring itself is
stale and is not fixed by this documentation pass (no code was changed to
produce this correction). IMPLEMENTED AND TESTED.

### 17.4 Real decision windows

`decision_window_records.py` groups bursts by real elapsed time
(`window_index = burst.sample_start // window_samples`), not one window per
candidate. `window_duration_s` defaults to `10.0`
(`DEFAULT_WINDOW_DURATION_S`, `capture_records.py`). `WindowStatus` is
`INACTIVE | ACTIVE_INSUFFICIENT_BURSTS | ACTIVE_ELIGIBLE`. IMPLEMENTED AND
TESTED; no definitive campaign report produced through this path yet.

### 17.5 Origin metadata on captures

`ble_rffi_studio/contracts/capture.py`'s `CaptureRecord` carries
`campaign_period`, `pre_or_post`, `intervention_arm`, `packet_variant`,
`host_id`, `firmware_hash`, `configuration_hash`, `operator_id`,
`planned_capture_id` (in addition to `day_id`/`receiver_epoch`, §16.4-16.5).
`capture_stage.py`'s `build_capture_record` reads all of them directly from
the manifest -- no fallback, `None` when absent, never guessed.
IMPLEMENTED AND TESTED; 0/150 real historical captures declare most of
these (unchanged finding, consistent with earlier sections) -- they exist
for the campaign runner (§17.8) to populate going forward.

### 17.6 Decoder burst variables exposed

`backend/tools/ble_decode_burst_directory.py` now reads
`synchronization_score` (`detector_score`), `symbol_phase`
(`estimated_timing_phase`), `frequency_offset_hz` (`estimated_cfo_hz`), and
`frequency_fit_quality` from the real decoder output;
`ble_offline_replay.py` copies them into `packet_association_ledger.jsonl`;
`burst_records.py` reads them directly (removed from
`_STRUCTURALLY_ABSENT_BURST_FIELDS`). `competing_energy`,
`clipping_overlap`, `discontinuity_overlap`, `edge_margin_samples`,
`burst_snr_db` remain genuinely absent -- not invented. IMPLEMENTED AND
TESTED.

### 17.7 Association timing residuals

`ble_scientific_results/quality/quality_summary.py` breaks
`association_timing_residual` down per `(capture_id, physical_unit_id,
day_id, association_status)` with median/p75/p90/p95/max/iqr, written to
`association_timing_residual_distribution.csv`. `ASSOCIATION_TIME_
THRESHOLD_MS = 250.0` is documented honestly as a hardcoded value with **no
recorded calibration study behind it** -- not upgraded to look justified by
this pass. IMPLEMENTED AND TESTED against the real `CC2650-UNIT-01-AUTO-TVB`
dataset (`test_preflight_real_data.py`).

### 17.8 Campaign runner

`ble_rffi_studio/campaign/paper_campaign_runner.py`: `PaperCampaignSchedule`
(`qualification_only` flag), `PaperCampaignRunner.freeze_schedule`,
`next_planned_capture`, `execute`, `reject_out_of_schedule`. `execute()`
calls the existing `CampaignOrchestrator.run_session()` -- it does not talk
to the SDR/arbiter directly, and only writes previously-frozen schedule
metadata onto the manifest after the real capture completes. Rejections are
persisted append-only and converted into real
`ScientificCampaignDeviationRecord`s (§17.3). IMPLEMENTED AND TESTED; see
[`docs/ble/PILOT_CHECKLIST.md`](PILOT_CHECKLIST.md) for the qualification
pilot a human operator must run with real hardware before the definitive
20-day campaign -- **not executed or simulated as part of writing that
checklist**.

### 17.9 Holdout group mechanism

`ble_scientific_results/contracts/holdout_groups.py`: `HoldoutGroupAssignment`,
`HoldoutGroup = TRAIN | VALIDATION | FUTURE_TEST`.
`ScientificResultsRepository.freeze_holdout_groups` / `list_holdout_groups`
/ `read_group` (the latter gates and logs any `FUTURE_TEST` read through the
existing holdout-access hash chain, §16.1). **Mechanism only: zero real
`HoldoutGroupAssignment`s exist on disk** -- confirmed, no
`_holdout_groups` directory exists under real storage; only tests exercise
it, since no 20-day campaign has run yet to assign real groups to.
IMPLEMENTED, NOT YET EXPERIMENTALLY VALIDATED (nothing real to validate
against yet).

### 17.10 Guided Validation

`ble_scientific_results/guided_validation/service.py`:
`GuidedBleScientificValidationService` -- a real, wired capture-first wizard
tab (`/ble-scientific-results`, and the **default active tab** in the
frontend): device listing, new capture session, Live Timing Diagnostic
(`run_timing_diagnostic`, a real hardware action via
`CampaignOrchestrator.run_session`, cancellable), Reinforced Target-Absence
Control (`run_target_absence_control`, also cancellable, requires explicit
per-device `confirmed_devices_off`), and a disk cleanup center that deletes
only derived artifacts, never raw I/Q. IMPLEMENTED AND TESTED.

**Real evidence** (not a fixture): four real runs exist on disk under
`storage/scientific_reports/ble/guided_validation/`, timestamped 2026-08-07.
The most complete one (`GVAL-20260807T170247Z-7333a5`):
`overall_status="BLOCKED"`, `capture_totals={total_captures: 138,
association_calibration_eligible: 91, diagnostic_only: 47}`,
`association_summary={total_calibration_events: 34352,
matched_target_count: 0, by_status_percent: {NO_CANDIDATE_IN_WINDOW: 65.8,
MISMATCH: 26.5, AMBIGUOUS: 5.5, MATCHED_NON_TARGET: 2.1}}`,
`target_absence_summary={candidates_checked: 25, has_valid_control:
false}`. This is a real, current negative result consistent with the 0
STRONG associations already stated in §16.2 and the root README -- not a
different or contradicting number, and not weakened to produce a pass.

---

## 18. Reproducibility map — scientific report ↔ dashboard button ↔ canonical artifact

### 18.0 Current DEVELOPMENT evidence snapshot

Real numbers, current as of this section's own last edit -- always verify
against the canonical artifacts named below (or run `docs/ble/generate_
evidence_figures.py --verify`) rather than trusting this snapshot frozen in
time.

**Coherence-audit correction (2026-08-19)**: `evaluate_rq1_acquisition_
dependence()` (`ble_rffi_studio/evaluation/rq1_acquisition_dependence.py`)
read `SplitEvaluationReport.accuracy` instead of `.balanced_accuracy` for
`ba_window`/`ba_capture`/`ba_future` -- a real bug, found because RQ1's
capture-disjoint VALIDATION (previously reported 0.749) silently disagreed
with RQ2's `engineered_rf` PRIMARY branch VALIDATION (0.634) despite both
reading the exact same `predictions.json` for the exact same training run
(`TRAIN-20260814T224700-4DEVICES-5d06e404-random_forest-a598bd`) over the
exact same 2,203 VALIDATION examples (confirmed identical by hashing both
real example_id sets). Fixed at the source; the RQ1 artifact was
regenerated from the already-real, already-computed evaluation reports of
the existing diagnostic run and the existing recommended run -- no
retraining, no new capture, no threshold/criteria change. Bootstrap CIs
were never affected (already balanced-accuracy-based). The four per-unit
`TARGET_VS_BACKGROUND` auxiliary RQ1 reports (§ "Per-unit auxiliary RQ1",
`readme_img/evidence_per_unit_auxiliary_rq1.png`) go through the SAME
function and are very likely affected the same way, but have **not** been
regenerated as part of this fix -- flagged, not silently corrected, pending
an explicit decision to re-run them.

**Bootstrap-method correction (2026-08-22)**: the RQ1 CIs below were
regenerated with a corrected, class-stratified, session-clustered bootstrap
(`stratified_hierarchical_cluster_bootstrap` /
`independent_domain_bootstrap_delta_ci`,
`backend/app/modules/ble_scientific_results/statistics/inference.py`). The
prior, unstratified pooled resample of the 12-session capture-disjoint
domain dropped at least one enrolled class from a nontrivial fraction of its
replicates; the delta CI was also previously described as a "paired cluster
bootstrap", which it is not — the two domains have no physical session
pairing and are resampled independently. Point estimates (0.958 / 0.634 /
delta 0.324) are unchanged; only the CI construction and terminology were
corrected. Full method detail and a canonical artifact inventory with
SHA-256: [`docs/ble/TECHNICAL_EVIDENCE_AUDIT.md`](TECHNICAL_EVIDENCE_AUDIT.md).

| Item | Value | Source |
|---|---|---|
| RQ1 `evaluation_unit` | `EXAMPLE_RECORD` | `06_statistics/rq1_acquisition_dependence_report.json` |
| RQ1 capture-dependent BA / 95% CI / n / sessions | `0.958` / `[0.939, 0.975]` / `1790` / `34` | same |
| RQ1 capture-disjoint (VALIDATION) BA / 95% CI / n / sessions | `0.634` / `[0.591, 0.685]` / `2203` / `12` | same |
| RQ1 `delta_dependence` / 95% CI | `0.324` / `[0.269, 0.371]` (class-stratified, session-clustered, independently-resampled domains — not paired) | same |
| RQ1 held-out TEST BA (not protected FUTURE) | `0.767` (no CI persisted for this domain) | `ble_rffi_studio/training_runs/<id>/evaluation_report.json` (`TEST`) |
| RQ2 PRIMARY branch (`engineered_rf`) BA / macro-F1 | `0.634` / `0.586`, from 3 candidate model families (logistic regression, RBF-SVM, random forest), 0 hyperparameter search | `06_statistics/rq2_representation_comparison_report.json` |
| RQ2 other branches (`stft`/`coarse_morphology`/`raw_iq`) BA / macro-F1 | `0.537`/`0.498`, `0.277`/`0.128`, `0.248`/`0.226` — each 1 fixed configuration, 0 hyperparameter search | same |
| RQ4 exploratory analytical-region control (FULL_BURST vs. PRE_PDU) BA / 95% CI | `0.634` `[0.591, 0.685]` vs. `0.556` `[0.503, 0.628]`; delta `0.078` `[0.046, 0.100]` (matched, class-stratified, session-clustered bootstrap); `DEVELOPMENT_EXPLORATORY`, PRE_PDU is an independent TRAIN-only re-fit, TEST not opened for either arm | `06_statistics/rq4_full_burst_vs_pre_pdu_exploratory_report.json` |
| 10-second decision windows | `TRAIN=34`, `VALIDATION=12`, `TEST=12` -- all 4/4 classes in every partition | `06_statistics/coverage_analysis_report.json` |
| VALIDATION window-level BA / argmax accuracy / operational coverage | `0.750` / `0.833` (10/12) / `0.833` (not `1.000` — 2/12 rejected by the acceptance threshold as `UNKNOWN`; accuracy among accepted = `0.9`, 9/10, plus 1 accepted-and-incorrect) | `paper_exports/development_decision_window_summary.csv`, `coverage_analysis_report.json`'s `operational_breakdown` |
| TEST window-level BA / argmax accuracy / operational coverage | `0.875` / `0.917` (11/12) / `0.833` (not `1.000` — 2/12 rejected; accuracy among accepted = `1.0`, 10/10; the 1 argmax error was itself rejected, not accepted) | same |
| Enrolled-population class-exclusion metric sensitivity (worst case, `CC2650-UNIT-01` omitted from the metric only — **not** retrained, **not** leave-one-device-out) | BA `0.528`, delta `-0.106` vs. full-set `0.634` | `06_statistics/sensitivity_report.json` (`enrolled_population_class_exclusion_sensitivity`) |
| DEVELOPMENT label provenance (4-class closed-set, 9,891 examples) | `PHYSICAL_ISOLATION_DECLARED` 4,338 (43.9%) + registry address-binding (`association_status` NONE/AMBIGUOUS) 5,553 (56.1%) — **0 STRONG** | `evidence_stage.py::_build_example()`, real counts from `evidence/<capture_id>/examples.jsonl` filtered to `IDENTITY-c52850a953`'s real `example_ids` |
| Offset-retaining sensitivity | BA `0.634`, delta `0.000` vs. PRIMARY — **not informative**: `offset-retaining-v1` resolves to the same identity flags as PRIMARY's own `base-v1`, so this equality is trivial by construction, not a validated CFO-compensation finding | same |
| Association calibration | `NO_THRESHOLD_SATISFIES_CRITERIA` (fail-closed; coverage=0.0, false_strong=0 at every threshold in the 50-500ms grid; 0 STRONG across all 5 registered units) | `association_calibration_summary` |
| Protected FUTURE | `NOT_YET_AVAILABLE` -- not executed, fail-closed | `rq1_acquisition_dependence_report.json` (`ba_future=null`) |
| Protocol freeze | `NOT_STARTED` -- 15 required fields/gates still missing (real, versioned freeze mechanism exists; DEVELOPMENT artifacts already version-pinned/reproducible is not the same as a confirmatory freeze) | `get_scientific_completeness_report()` |
| Same-family verification (`keyfobdemo 01`/`02`) | Not verified -- `same_model_groups.verified_groups` empty for every enrolled pair; referred to as *two key-fob-class units*, never a validated same-family pair | `docs/ble/physical_device_inventory.json` |
| RQ3 | `PENDING` -- 0 real captures carry RQ3 metadata, 0 valid empirical intervention pairs, of 80 pairs targeted | `_rq3_campaign_progress()` |
| RQ4 packet-condition intervention | `NOT_AVAILABLE` -- 0/4 enrolled units eligible; distinct from the already-executed analytical-region control above | `get_scientific_completeness_report()` |
| CH37→CH38 transport | Real CH38 RF data already exists (1,663 admitted examples, 4 enrolled units), transport analysis itself not executed | dataset composition + `06_statistics/channel_transport_report.json` (does not exist yet) |
| CH39 | 0 real captures for the four enrolled units (1 CH39 capture exists in the whole store, for an unrelated diagnostic unit) | live channel/capture query, `docs/ble/TECHNICAL_EVIDENCE_AUDIT.md` §10 |
| Near-live | `NOT_AVAILABLE` -- no real prediction-collection mechanism wired yet | — |

Standing rule (2026-08-18): every number that goes into the paper must be
reproducible and auditable by anyone on the team through the
`/ble-scientific-results` dashboard, not just something one person can pull
via a script. Before hand-deriving a report, check this table first --
almost everything already has a real "run" button and a real read-only view.
If a genuine gap is found (no button, no artifact, no tab), close it the
same way these were closed, then add a row here.

`/ble-scientific-results` (`BleScientificResultsPage.tsx`) is organized in
four sections (A–D); every tab below lives under **C. Scientific Results**
unless noted. `RunScopedJsonReport`-based tabs are read-only viewers of an
already-persisted `06_statistics/*.json` file; the "run" button that
produces that file lives in the **Study Control Center** tab (section A)
unless the tab has its own inline button (Coverage does).

| Report | Regenerate | Visualize | Canonical artifact |
|---|---|---|---|
| RQ1 (same-capture dependent vs. capture-disjoint BA, CI, delta, confusion matrix) | Study Control Center → RQ1 Acquisition Dependence | `Rq1Tab.tsx` | `06_statistics/rq1_acquisition_dependence_report.json` |
| RQ2 (four representations: BA, macro F1, per-class recall, model size, inference latency, seed variability) | Study Control Center → RQ2 Benchmark | `Rq2Tab.tsx` | `06_statistics/rq2_representation_comparison_report.json` |
| Coverage / decision-window scoping (TRAIN/VALIDATION/TEST window counts, domain-resolution diagnostic) | `CoverageTab.tsx`'s own "Correr Coverage Analysis" button | `CoverageTab.tsx` | `06_statistics/coverage_analysis_report.json` |
| VALIDATION/TEST window-level BA, confusion matrix, per-TX counts, risk-coverage (10 s decision windows) | same button, with the "incluir BA/matriz de confusion/risk-coverage a nivel de decision-window" checkbox ticked (`evaluate_window_level=true`) | `CoverageTab.tsx` → `window_level_evaluation` section (per branch, per domain: confusion matrix heatmap, risk-coverage chart+table, raw decision-window rows) | same file, `window_level_evaluation` key |
| Sensitivity: enrolled-population class-exclusion metric sensitivity (renamed 2026-08-22 -- not leave-one-device-out, model never retrained), offset-retaining preprocessing (not currently informative), seed variability (reused from RQ2, never recomputed) | Study Control Center → Sensitivity Analysis | `SensitivityTab.tsx` | `06_statistics/sensitivity_report.json` |
| RQ4 exploratory analytical-region control (FULL_BURST vs. PRE_PDU, `DEVELOPMENT_EXPLORATORY`) | already executed; re-run via `train_region_specific_variant()` | not yet wired to a dashboard tab -- `readme_img/evidence_rq4_regions.png` / `evidence_rq4_per_unit_recall.png` | `06_statistics/rq4_full_burst_vs_pre_pdu_exploratory_report.json` |
| Association calibration sweep (fail-closed result, per-threshold coverage/false_strong/ambiguous) | none needed -- always shows the latest real attempt live | `AssociationTab.tsx` | `association_calibration_summary` (computed on read, not persisted as a run-scoped file) |
| Channel transport (S1), offline vs. near-live (S2) | Study Control Center → respective phase button | `ChannelTransportTab.tsx`, `OnlineEquivalenceTab.tsx` | `06_statistics/channel_transport_report.json`, `06_statistics/offline_nearlive_report.json` |
| RQ3 / RQ4 packet-condition intervention | Study Control Center → respective phase button | `Rq3Tab.tsx`, `Rq4Tab.tsx` | `confirmatory_statistical_plan_report.json` (`rq3_pairs`, `rq4_region_report`) |
| Cross-cutting summary tables (TX composition, partition composition, receiver epochs) | none needed -- computed on read from already-real captures/splits | `SupportingTablesTab.tsx` | not persisted -- always live |
| Scientific completeness rollup | none needed | `ScientificCompletenessTab.tsx` | not persisted -- always live |

No single button regenerates all of the above at once, by design: RQ1/RQ2/
Coverage/Sensitivity/RQ3/RQ4 are deliberately separate real analyses with
separate preconditions (e.g. Coverage needs a frozen RQ2 PRIMARY branch
first) -- bundling them into one mega-job would hide which precondition
failed. `BleScientificResultsPage.tsx` already reserves a `reproducibility`
tab id for a possible future single index view (`enabled: false` — not
built).

---

## 19. Methodological audit (2026-08-19) — acquisition profile, bootstrap spec, corpus counts, RQ2 paired uncertainty, model configs, TEST vs. protected FUTURE, publication figures

Pre-registered scope for this audit: no new captures, no retraining, no
threshold/split/scientific-criteria changes, no change to the RQ1/RQ2
numeric results already corrected in §18.0's 2026-08-19 coherence-audit
entry. Every value below is read directly from a real, on-disk artifact;
anything not present in a real schema/artifact is marked `NOT_AVAILABLE`,
never reconstructed.

### 19.1 RF acquisition profile (closed-set `IDENTITY-c52850a953`, 79 real captures)

Every field below is uniform across all 79 real `CaptureRecord`s backing
this dataset (read from each capture's own JSON, not assumed from one
sample). `contracts/capture.py`'s real schema has no field at all for
antenna model/type, TX-RX distance/geometry, or environment/location
descriptor — those three rows are `NOT_AVAILABLE` because the field does
not exist, not because a value was missing.

| Field | Value | Source (`CaptureRecord` field) |
|---|---|---|
| Receiver device id | `sdr-018ca73b3c2d07b3` | `receiver_device_id` |
| SDR model / serial | `B200` / `E3R04Z1B2` | `sdr_model` / `sdr_serial` |
| RX channel / antenna port | `RX2` / `RX2` | `rx_channel` / `antenna_port` |
| BLE channel actually split-assigned | channel 37 only — 100% of TRAIN/VALIDATION/TEST (3,561+2,203+2,464 = 8,228 = the exact real channel-37 example count). Channel 38 exists in the dataset (1,663 examples) but is never split-assigned. | cross-check of `center_frequency_hz` against the real split manifest's `assignments` |
| Center frequency | `2,402,000,000 Hz` (channel 37, split-assigned); `2,426,000,000 Hz` (channel 38, dataset-only, unused by any split) | `center_frequency_hz` |
| Sample rate | `4,000,000 sps` | `sample_rate_sps` |
| Sample format | `cf32_le`, `little_endian` | `sample_dtype` / `byte_order` |
| Analog/frontend bandwidth | `2,000,000 Hz` (`frontend_bandwidth_hz` == `effective_bandwidth_hz`) | `frontend_bandwidth_hz` / `effective_bandwidth_hz` |
| RX gain | `20.0 dB`, `manual` | `gain_db` / `gain_mode` |
| Capture duration | `10.0 s` nominal — uniform across all 79 real captures, no deviation | `capture_duration_s` |
| Capture tool | `ble-sdr-capture-v3` | `capture_tool` |
| Capture tool version | `NOT_AVAILABLE` — schema field exists, never populated | `capture_tool_version` |
| Clock source / time source | `NOT_AVAILABLE` — schema fields exist, never populated | `clock_source` / `time_source` |
| Discontinuities | `0` across all 79 captures | `discontinuities` |
| Antenna model/type | `NOT_AVAILABLE` — no schema field exists | — |
| TX–RX distance/geometry | `NOT_AVAILABLE` — no schema field exists | — |
| Environment/location descriptor | `NOT_AVAILABLE` — no schema field exists | — |

### 19.2 RQ1 bootstrap specification (canonical BA=0.958/BA=0.634 result)

**Superseded by the 2026-08-22 bootstrap-method correction (§18.0).** This
subsection is kept as the real, historical record of what was true on
2026-08-19 — the `hierarchical_cluster_bootstrap`/`paired_cluster_bootstrap_
delta_ci` functions it describes are unstratified and were found (2026-08-22)
to drop at least one enrolled class from a nontrivial fraction of replicates
on the 12-session capture-disjoint domain, and the delta procedure described
below is not actually a valid pairing (the two domains have no physical
session correspondence). The real, current RQ1 CIs use
`stratified_hierarchical_cluster_bootstrap` / `independent_domain_bootstrap_
delta_ci` instead — same cluster unit (`session_id`), same `n_resamples=2000`,
same percentile CI, same seed `12345`, additionally stratified by
`physical_unit_id`, with the delta computed by resampling the two domains
independently rather than "pairing" resample draws. Full detail:
[`docs/ble/TECHNICAL_EVIDENCE_AUDIT.md` §1](TECHNICAL_EVIDENCE_AUDIT.md#1-rq1--current-result).

- **Cluster unit**: the real `session_id` — grouping is done by real session
  boundary, never by individual example (`_session_clustered_label_pairs`,
  `ble_rffi_studio/evaluation/evaluator.py`). In this dataset a session is
  1:1 with a capture (§19.3), so "session-clustered" and "capture-clustered"
  are the same real grouping here.
- **Independent clusters in the dependent (capture-dependent diagnostic)
  domain**: **34** real sessions, `n=1,790` comparable examples (the
  diagnostic run `RQ1DIAG-IDENTITY-c52850a953-random_forest-511086ab`'s
  VALIDATION predictions).
- **Independent clusters in the capture-disjoint VALIDATION domain**: **12**
  real sessions, `n=2,203` comparable examples (the recommended run
  `TRAIN-20260814T224700-4DEVICES-5d06e404-random_forest-a598bd`'s
  VALIDATION predictions).
- **Disjointness verified directly**: the 34-session pool and the 12-session
  pool have **zero** session ids in common (set intersection computed on
  the real `predictions.json`/dataset session map for both runs) — not
  merely asserted by design, confirmed by construction.
- **Bootstrap replicate count**: `n_resamples=2000` (the real default at the
  `StudioRepository.bootstrap_balanced_accuracy_ci`/
  `bootstrap_balanced_accuracy_delta_ci` call layer — `inference.py`'s own
  `hierarchical_cluster_bootstrap`/`paired_cluster_bootstrap_delta_ci`
  default to `5000`, but no real caller in this codebase leaves that
  default in place; every real RQ1 CI was computed at `n_resamples=2000`).
- **CI method**: percentile (`np.quantile` at `alpha/2`/`1-alpha/2` over the
  resample-statistic array) — never BCa.
- **Confidence level**: `0.95`.
- **Random seed**: `np.random.default_rng(12345)` — the real default inside
  `hierarchical_cluster_bootstrap` whenever a caller passes `rng=None`; no
  real call site in this codebase ever overrides it, so every RQ1 bootstrap
  CI in this repository is deterministic and reproducible from this seed.
- **Delta (`delta_dependence`) resampling procedure**: `paired_cluster_
  bootstrap_delta_ci` resamples the dependent-domain population and the
  capture-disjoint population **independently** (each its own
  `hierarchical_cluster_bootstrap` call, own resample draws), then pairs
  the *i*-th resample of population A with the *i*-th resample of
  population B into `delta_i = statistic(A_i) - statistic(B_i)`, and takes
  the percentile CI of that `delta_i` array. It never subtracts two
  separately-computed marginal CIs' bounds — that would discard the shape
  of the actual resampling distribution and is not a valid CI for a
  difference.
- **Do the 0.958 CI and the 0.634 CI use the same resampling scheme?**
  **Yes.** Both are computed by the exact same function chain
  (`Evaluator.bootstrap_balanced_accuracy_ci` → `hierarchical_cluster_
  bootstrap`), the same statistic (mean-per-class recall over pooled,
  resampled `(true_label, predicted_label)` pairs — `evaluate_split()`'s own
  `balanced_accuracy` definition, never a second one), the same
  `n_resamples=2000`, the same `confidence_level=0.95`, and the same
  seed-default (`12345`, freshly instantiated per call since both callers
  pass `rng=None`). The only real difference between them is the input
  cluster population (34 clusters/1,790 examples vs. 12 clusters/2,203
  examples) — exactly what a bootstrap CI is supposed to reflect, not a
  methodological inconsistency between the two numbers.

### 19.3 Corpus composition by class (`IDENTITY-c52850a953`, `MULTI_DEVICE_CLASSIFICATION` split)

Computed directly from the real split manifest's `assignments` (8,228 real
rows, each carrying its own real `capture_id`/`session_id`/`physical_unit_id`
/`split`). **The independent experimental unit here is the capture/session,
not the individual example record** — every unit×domain cell below has
`n_captures == n_sessions` (1:1 pairing in this dataset — no capture spans
more than one session or vice versa) and, cross-checked against
`paper_exports/development_decision_window_summary.csv`, `n_captures ==
n_windows` too (1 capture = 1 real 10-second decision window in the current
pre-120s-campaign regime). `n_examples` is the ExampleRecord count — many
examples (bursts) per capture, never confused with the capture/session count.

| Physical unit | Domain | n_examples | n_captures | n_sessions |
|---|---|---:|---:|---:|
| CC2541SensorTag | TRAIN | 447 | 5 | 5 |
| CC2541SensorTag | VALIDATION | 187 | 2 | 2 |
| CC2541SensorTag | TEST | 216 | 2 | 2 |
| CC2650-UNIT-01 | TRAIN | 522 | 7 | 7 |
| CC2650-UNIT-01 | VALIDATION | 166 | 3 | 3 |
| CC2650-UNIT-01 | TEST | 225 | 3 | 3 |
| keyfobdemo 01 | TRAIN | 1,743 | 14 | 14 |
| keyfobdemo 01 | VALIDATION | 1,690 | 5 | 5 |
| keyfobdemo 01 | TEST | 1,857 | 5 | 5 |
| keyfobdemo 02 | TRAIN | 849 | 8 | 8 |
| keyfobdemo 02 | VALIDATION | 160 | 2 | 2 |
| keyfobdemo 02 | TEST | 166 | 2 | 2 |
| **TOTAL** | **TRAIN** | **3,561** | **34** | **34** |
| **TOTAL** | **VALIDATION** | **2,203** | **12** | **12** |
| **TOTAL** | **TEST** | **2,464** | **12** | **12** |

### 19.4 RQ2 paired uncertainty between representations

`RQ2_PAIRED_UNCERTAINTY`: **available**, using only the existing, already-
tested `StudioRepository.bootstrap_balanced_accuracy_delta_ci()` — no new
statistic was implemented. This mechanism was built for RQ1's two
*disjoint* populations, but it is also valid here for a different, verified
reason: all 4 RQ2 branches (`engineered_rf`, `stft`, `raw_iq`,
`coarse_morphology`, all real training runs under `TRAIN-20260814T224700-
4DEVICES-5d06e404-*`) were trained on the exact **same** VALIDATION split,
and their real `predictions.json` were confirmed, by direct inspection, to
carry the identical 2,203 `example_id`s in the identical order and the
identical 12-session grouping order. Because each branch's CI draw uses a
freshly-seeded `np.random.default_rng(12345)` of the identical size, the
two populations' resample-index draws are literally identical index-for-
index — turning the "independent-population" delta bootstrap into a real,
valid matched-pairs bootstrap for this specific, verified case (same
seed + same cluster count + same cluster order ⇒ same resampled clusters on
both sides of the difference).

Computed for this audit (read-only — **not** written into the persisted
`rq2_representation_comparison_report.json`, which keeps its original
content per this audit's "no changes to already-fixed RQ2 results" scope):

| Contrast | Δ balanced accuracy (point estimate) | 95% CI |
|---|---:|---|
| Engineered RF − STFT | `+0.097` | `[-0.001, 0.247]` |
| Engineered RF − Raw I/Q | `+0.386` | `[0.213, 0.552]` |
| Engineered RF − Coarse morphology | `+0.357` | `[0.266, 0.585]` |

Method: `StudioRepository.bootstrap_balanced_accuracy_delta_ci(training_run_id_a, training_run_id_b, split_a="VALIDATION", split_b="VALIDATION")`,
`n_resamples=2,000`, `confidence_level=0.95`. No branch in the currently
persisted RQ2 report carries a real marginal `balanced_accuracy_ci` either
(this artifact predates the 2026-08-17 per-branch CI addition to
`rq2_benchmark.py`) — this is why the RQ2 publication figure (§19.7) shows
point estimates only.

### 19.5 Exact model configurations (closed-set, real training runs, `random_seed=42` for all six)

All six real hyperparameter values below come from the hardcoded defaults
in `training/baseline_models.py`/`training/cnn_models.py`/`training/
frozen_reference_baseline.py` — every real `training_run.json`'s own
`hyperparameters` field is `{}` (no per-run override was ever passed), so
these defaults are exactly what trained every real closed-set model.

- **Engineered RF branch** — 3 real candidates trained, `random_forest`
  selected as PRIMARY by real VALIDATION composite score:
  - `RandomForestClassifier(random_state=42, n_estimators=100, max_depth=None)` — **selected**
  - `LogisticRegression(random_state=42, max_iter=1000, C=1.0)` — trained, not selected
  - `SVC(kernel="rbf", probability=True, random_state=42, C=1.0, gamma="scale")` — trained, not selected
- **Raw I/Q CNN (`cnn1d`)**: `Conv1d(2→16, k=7, pad=3)` → ReLU → `max_pool1d(k=2)` → `Conv1d(16→32, k=5, pad=2)` → ReLU → `AdaptiveAvgPool1d(1)` → `Linear(32→num_classes)`. Optimizer `Adam`, `learning_rate=1e-3`, `batch_size=16`, `epochs=30` (fixed, no early stopping/patience rule), loss `CrossEntropyLoss`, `torch.manual_seed(42)`.
- **STFT CNN (`cnn2d`)**: `Conv2d(1→8, k=3, pad=1)` → ReLU → `max_pool2d(k=2)` → `Conv2d(8→16, k=3, pad=1)` → ReLU → `AdaptiveAvgPool2d(1)` → `Linear(16→num_classes)`. Same optimizer/LR/batch/epochs/seed as `cnn1d` (shared `CnnTrainer.fit`).
- **Coarse morphology (`frozen_morphological_baseline`)**: no iterative optimization at all — one per-class centroid (mean of `morphological_coarse_tf_representation` vectors over TRAIN), classified by nearest centroid (Euclidean distance), converted to a probability distribution via softmax over negative distances. `random_seed`/hyperparameters are accepted for interface parity but genuinely unused (nothing stochastic or tunable to seed).

### 19.6 TEST ≠ protected FUTURE — formal confirmation with real identifiers

Confirmed structurally, not just by convention: `SplitManifest`'s `TEST`
role (`SplitName = Literal["TRAIN", "VALIDATION", "TEST"]`,
`ble_rffi_studio/contracts/split.py`) and protected FUTURE's `FUTURE_TEST`
role (`HoldoutGroup = Literal["TRAIN", "VALIDATION", "FUTURE_TEST"]`,
`ble_scientific_results/contracts/holdout_groups.py`) are two entirely
separate contract types with separate storage, separate access-gating, and
separate real state today:

- **TEST** (current DEVELOPMENT held-out partition): the 2,464-example
  partition of the closed-set split
  `IDENTITY-c52850a953__20260814T224525.782975Z__MULTI_DEVICE_CLASSIFICATION`
  (§19.3) — the **same acquisition domain** as TRAIN/VALIDATION (same
  dataset, same 79 real captures, same channel-37 scope), held out only by
  session-disjoint split assignment, not by a separate campaign.
- **FUTURE_TEST** (protected FUTURE): requires its own frozen
  `HoldoutGroupAssignment` record (`assignment_id`, real
  `physical_unit_ids`/`day_ids`/`session_ids`, `group_manifest_sha256`) —
  **zero such records exist on disk today** (confirmed: no
  `HoldoutGroupAssignment` file anywhere under storage; the only file is
  `holdout_access_log.jsonl`, an access log, not an assignment). Its own
  module docstring states this explicitly: *"no 20-day campaign has run, so
  there is nothing real to assign FUTURE_TEST to today."* The real access
  log (`holdout_access_log.jsonl`, 9 entries) shows every real access to
  date is `access_type="OPEN_TEST"` (the `SplitManifest` TEST role) — zero
  entries have `FUTURE_TEST` in their `access_path`. The only real read
  path for `FUTURE_TEST` data anywhere in the repository
  (`ScientificResultsRepository`'s confirmatory-future runner) is gated
  behind 5 checks including `DATASET_HAS_NO_FUTURE_TEST_HOLDOUT_ROLE`,
  which raises today because no real `FUTURE_TEST` `HoldoutGroupAssignment`
  exists.

**TEST is not FUTURE.** They are different contract types, different
storage locations, different real state (TEST: populated and read 9 times
already; FUTURE_TEST: zero real assignments, zero real reads, structurally
blocked from being read even if someone tried).

### 19.7 Publication figures regenerated

Three README-facing figures regenerated from the same real canonical
artifacts as their existing internal/diagnostic counterparts — no
underlying data changed, only the rendering. New generator code lives in
`ble_scientific_results/paper_export.py` (RQ1/RQ2 publication blocks,
`figures/publication` naming) and `ble_scientific_results/figures/
paper_figures.py` (`bar_with_ci_figure` gained optional `ylim`/`colors`
params, reused rather than duplicated). `docs/ble/generate_evidence_
figures.py`'s `CONSOLIDATED_FIGURES` now copies these publication variants
— not the internal diagnostic ones — into `readme_img/`; `--verify` gained
matching checks (no `DEVELOPMENT EVIDENCE`/`real, traced` text, no
truncated hashes, no internal snake_case branch keys or `(UNSELECTED)`
suffix in the rendered SVG).

| Figure | `readme_img/` file | What changed vs. the internal diagnostic figure |
|---|---|---|
| RQ1 domains | `evidence_rq1_domains.png` | No `DEVELOPMENT EVIDENCE` caption, no footnote (n/CI/delta text) baked into the image; fixed `[0, 1]` balanced-accuracy axis; real error bars kept (RQ1 has real, persisted, canonical CIs) |
| RQ2 branches | `evidence_rq2_branches.png` | Human-readable labels (`Coarse morphology`/`Engineered RF`/`Raw I/Q`/`STFT`) instead of internal snake_case keys; PRIMARY vs. UNSELECTED conveyed by bar color (amber/grey), never a `(UNSELECTED)` text suffix; fixed `[0, 1]` axis; point estimates only — no fabricated error bars, since no branch in the persisted canonical report currently carries a real marginal CI (§19.4) |
| Forensic lineage | `evidence_forensic_lineage.png` | Title dropped `"(real, traced)"`; node detail text dropped truncated `sha256` fragments (kept the real, meaningful identifiers: dataset id/version, split id, training run id, model bundle id, PRIMARY branch) |

**2026-08-23 addition**: `evidence_forensic_lineage.png` regenerated again to
add a real `Preprocessing` node (`base_preprocessing_profile_id=base-v1`,
read live from the PRIMARY training run's own `training_run.json`) — the
prior version of this figure omitted preprocessing from the chain entirely.
Two new figures joined the same code path (`paper_export.py` →
`figures/paper_figures.py::bar_with_ci_figure`/`grouped_bar_figure` →
`generate_evidence_figures.py`'s `CONSOLIDATED_FIGURES`, same
single-computation discipline as the three above): `evidence_rq4_regions.png`
(FULL_BURST vs. PRE_PDU BA+CI, real footnote with n/sessions/delta) and
`evidence_rq4_per_unit_recall.png` (per-unit recall grouped bars, including
`keyfobdemo 02`'s unchanged 0.006 recall, never hidden). Full detail:
[`docs/ble/TECHNICAL_EVIDENCE_AUDIT.md`](TECHNICAL_EVIDENCE_AUDIT.md).

Full provenance (source artifact path + sha256, `evaluation_unit`,
`evidence_status`, generator, git sha) is preserved for all three in
`paper_exports/figure_manifest.json` — never shown inside the image itself,
per this audit's requirement. `docs/ble/generate_evidence_figures.py
--verify` passes against all of the above.

---

## Appendix: banned-terms self-check

A search of this document confirms every use of "validated" is either the
`VALIDATED` capability-state token (§2, defined with an explicit criterion),
a quoted code field name (`iq_recovery_validated`, `ota_validated`), or a
narrow, code-cited check ("validated against declared channel before
replay", `ble_offline_replay.py:315-334`; "validated generically",
`ble_hybrid_campaign_manager.py:164`) — never a free-standing claim about
the pipeline's overall correctness. **"real-time"** does not appear anywhere
except inside this sentence and §11's explanation of why it is avoided.
**"robust"** does not appear as an unqualified claim. **"reproducible"**
appears only in §13's own heading, about the *requirements* for
reproduction, not a claim that results already reproduce.
**"receiver-invariant"** and **"forensic attribution"** are not used as
unqualified claims anywhere in this document (§15 uses "forensic
attribution" only inside an explicit negation).

**§16 (2026-08-09) self-check**: every capability in §16 is explicitly
labeled `IMPLEMENTED` and, where applicable, separately marked
`EXPERIMENTALLY VALIDATED` only for the specific, narrower thing a real
execution actually checked (e.g. "the identity-unification fix, against the
real 144-capture corpus" — never the broader mechanism it's part of). Every
subsection that has no real campaign behind it yet says so explicitly
("no definitive campaign yet", "no real pairs yet", "not yet exercised"),
rather than being silently omitted.
