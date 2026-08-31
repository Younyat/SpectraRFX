# BLE-RFFI Studio module technical README

Audience: programmers maintaining the BLE-RFFI End-to-End Studio (the
independent module that turns already-captured/replayed B200 IQ into
CaptureRecord -> Evidence -> Dataset -> Training -> Evaluation -> Export ->
Inference).

This README is part of the project audit trail. Any meaningful change to this
module must update this file in the same work item: what changed, why it
changed, what scientific/UX assumption it protects, and how it was verified.

## 2026-08-18 update: RQ1 window-level dependence diagnostic + coverage_analysis scoping fix

RQ1's own naming was ambiguous: `build_rq1_dependence_diagnostic()` (unchanged,
`quality/split_builder.py`) splits by `ExampleRecord` hash-order, which can
place fitting-role and diagnostic-role bursts inside the exact same real 10s
decision window (`inference/decision_windows.py`) -- confirmed a real problem
for a window-level BA claim, not a naming quibble. New method
`SplitBuilder.build_rq1_window_level_dependence_diagnostic()` fixes this
properly: for each real capture with >=2 real decision windows (grouped via
the SAME `group_examples_into_windows()` the platform already uses for
RQ3/RQ4/coverage -- never a second windowing formula), the first half of its
window indexes (deterministic ascending order, never result-dependent) is
reserved for fitting, the second half for the diagnostic role. Grouped and
split **per capture** (not per session, unlike the original method), so
`capture_ids_train == capture_ids_diagnostic` and the two window-id sets are
disjoint by construction -- `same capture=YES, same decision window=NO,
shared bursts=NO`. New `split_purpose`:
`RQ1_WINDOW_LEVEL_ACQUISITION_DEPENDENCE_DIAGNOSTIC` (`contracts/split.py`).
Today's real closed-set captures are short enough that every one yields at
most 1 complete window -- this never fabricates a result for that case:
`split_status=NOT_FEASIBLE`, `infeasibility_reason` starting
`NOT_AVAILABLE_FOR_WINDOW_LEVEL_DEPENDENT_DIAGNOSTIC`, verified against real
data, not just unit-tested. Not yet frozen into any manifest or wired to a
runner -- ready for the definitive 120s/12-window campaign. IMPLEMENTED AND
TESTED (`test_split_builder.py`).

The import of `..inference.decision_windows` needed by the new method is
lazy (inside the method body, not module-level): `..inference/__init__.py`
imports `offline_inference` -> `..training.training_service`, which imports
`train_label_for` back from this same `quality/split_builder.py` -- a
module-level import created a circular-import crash on any import of
`ble_rffi_studio.quality` (caught by the test suite, not manually).

`ble_scientific_results.api.scientific_results_repository.run_coverage_
analysis` had a real scoping bug (not fixed here, but exercised by the new
method's design): it rebuilt each capture's decision windows from ALL its
raw bursts, then required every burst in a window to agree on one split
domain -- one stray non-admitted burst poisoned an otherwise-valid window as
`MIXED_SPLIT_ASSIGNMENT_WITHIN_WINDOW`. Fixed by partitioning a capture's
examples by split domain *before* windowing, so each domain-subset only ever
sees its own examples -- that reason code is now structurally impossible.
Real effect on the existing closed-set data: VALIDATION/TEST window counts
went from an artificially deflated 5/5 to the real 12/12 (all 4 units
represented in both), TRAIN from 2 to 34.

## 2026-08-09 update (2): campaign runner, origin metadata, and decoder burst variables

Documents a round of work that predates the block below chronologically but
was not yet written up here. Same IMPLEMENTED / EXPERIMENTALLY VALIDATED
distinction. `ble_scientific_results`-side counterparts (association
semantics, eligibility split, protocol-deviation classification, real
decision windows, holdout groups, Guided Validation) are documented in
`docs/ble/SCIENTIFIC_STATUS.md` §17, not here -- that is a separate module.

- **Campaign runner**: `campaign/paper_campaign_runner.py` --
  `PaperCampaignSchedule`/`PaperCampaignRunner` with `freeze_schedule`,
  `next_planned_capture`, `execute`, `reject_out_of_schedule`. `execute()`
  calls the existing `CampaignOrchestrator.run_session()` -- it does not
  reimplement capture or talk to the SDR/arbiter directly; it only writes
  the frozen schedule's declared metadata onto the capture manifest right
  after the real capture completes. An out-of-schedule capture is rejected
  and recorded, never improvised. IMPLEMENTED AND TESTED. The qualification
  pilot a human operator must run with this runner against real hardware,
  before the definitive 20-day campaign, is `docs/ble/PILOT_CHECKLIST.md`
  -- **not executed or simulated as part of writing that checklist.**
- **Origin metadata on `CaptureRecord`**: beyond `day_id`/`receiver_epoch`
  (see the block below), `contracts/capture.py` also carries
  `campaign_period`, `pre_or_post`, `intervention_arm`, `packet_variant`,
  `host_id`, `firmware_hash`, `configuration_hash`, `operator_id`,
  `planned_capture_id`. `capture_stage.py` reads all of them straight from
  the manifest -- `None` when absent, never a guessed default. IMPLEMENTED
  AND TESTED; still 0/150 real historical captures declare most of these,
  same honest gap as before -- the campaign runner above is what is meant
  to populate them going forward, not a retroactive fix.
- **Decoder burst variables**: `backend/tools/ble_decode_burst_directory.py`
  now reads `synchronization_score`, `symbol_phase`, `frequency_offset_hz`,
  and `frequency_fit_quality` from the real decoder output (previously
  computed and silently discarded); `ble_offline_replay.py` copies them
  into `packet_association_ledger.jsonl`. IMPLEMENTED AND TESTED.
  `competing_energy`, `clipping_overlap`, `discontinuity_overlap`,
  `edge_margin_samples`, `burst_snr_db` remain genuinely absent from any
  real source -- not invented to fill the gap.

## 2026-08-09 update: protocol-adaptation and scientific-rigor correction pass

Everything below is real, implemented, and covered by real tests unless
marked otherwise. Distinction used throughout, matching the root README and
`docs/ble/SCIENTIFIC_STATUS.md` §16: **IMPLEMENTED** = exists in code, wired
into the real pipeline, tested. **EXPERIMENTALLY VALIDATED** = additionally
exercised by a real campaign meeting an explicit criterion. This section
never claims the second for something that is only the first. Full detail,
real numbers, and per-item tests: `docs/ble/SCIENTIFIC_STATUS.md` §16;
Eq.(6)-(7) full derivation: `docs/ble/PREPROCESSING.md`.

- **RQ4 artifacts**: `ADVA_MASKED` (zero-filled in place) is retired --
  replaced by `packet_content/field_mapping.py`'s `ADVA_EXCLUDED`, which
  genuinely splices the AdvA sample range OUT of the analytical window
  (shorter array, no synthetic zero block standing in for it, no mask
  channel). `PRE_PDU` is unchanged and re-verified: `preamble + access
  address`, ending exactly before the PDU header starts. IMPLEMENTED, no
  definitive RQ4 campaign yet.
- **Preprocessing**: `preprocessing/paper_compliant_cfo.py` implements the
  paper's real Eq.(6)-(7) (`q[n]` frozen reference, `z_b[n]`, `ψ_b[n]`,
  frozen `I_b` = `PRE_PDU`, joint least-squares `(φ_b0, f_b)`, affine
  compensation, per-burst provenance) under profile `paper-eq6-7-v1`, with
  `offset-retaining-v1` as its sensitivity-analysis counterpart (same
  pipeline, offset not compensated). The older `cfo-compensated-v1` remains
  available for historical/ablation use only and is explicitly labeled
  **heuristic/legacy** -- it is not Eq.(6)-(7) (no reference waveform, no
  frozen index set, no joint regression, nothing persisted per burst) and
  must not be described as such anywhere in this file. IMPLEMENTED AND
  TESTED; no definitive real model bundle has been trained under
  `paper-eq6-7-v1` by a real campaign yet.
- **RQ2's 4th branch**: `training/frozen_reference_baseline.py` -- a frozen
  (no iterative optimization), nearest-centroid classifier over an
  L2-normalized coarse time-frequency representation
  (`frozen_morphological_baseline`, `ModelType` in `contracts/training.py`
  now has 6 values, not 5). Deliberately not `rf_experiment_lab`'s E0 (a
  region detector, not a device-fingerprinting baseline). IMPLEMENTED,
  wired into `prepare_and_train`'s "normal" speed profile; no definitive
  common RQ2 benchmark run yet.
- **Decision windows / abstention / coverage**:
  `OfflineInferenceService.run_decision_windows()` groups examples into real
  time windows, scores each burst with the bundle's own frozen model,
  aggregates by a declared, frozen rule (median probability per class), and
  abstains (`INSUFFICIENT_EVIDENCE`) below a minimum eligible-burst count --
  before the acceptance threshold is ever applied. `risk_coverage_curve`
  and `hierarchical_cluster_bootstrap` (previously real but
  production-unused) are now wired to real results:
  `SplitEvaluationReport.risk_coverage` and
  `StudioRepository.bootstrap_accuracy_ci` (session-clustered, never
  per-burst). IMPLEMENTED; no definitive campaign report produced yet.
- **Protected future holdout / confirmatory eligibility**:
  `export_and_approve_all_candidates` no longer opens TEST for any
  non-recommended candidate -- selection is VALIDATION-only; TEST opens
  exactly once, for the recommended candidate, freezing a real
  `ble_scientific_results.AnalysisContract` and logging a real,
  hash-chained holdout-access entry. `ModelBundleManifest.confirmatory_
  eligible` is a new, enforced field: **the 22 already-exported
  `OPT_IN_MULTI_CANDIDATE_COMPARISON` bundles remain `APPROVED_FOR_LIVE_
  PILOT` (status preserved) but now carry `confirmatory_eligible=False`,
  permanently, and must not be read as confirmatory evidence for any
  paper-level claim.** 5 bundles (the real VALIDATION-recommended
  candidate per device) carry `confirmatory_eligible=True`. IMPLEMENTED
  AND VERIFIED against the real 27-bundle migration; no paper-level
  confirmatory result has been produced through this mechanism yet.
- **RQ3 / RESET-CONTROL pairing**: `campaign/pre_post_pairing.py` pairs a
  physical unit's PRE/POST captures within one device-day and intervention
  arm, invalidating a pair when `receiver_epoch` (or, if supplied, the
  qualified preprocessing profile) differs between the two captures.
  IMPLEMENTED and tested; **0 real pairs exist** --
  `campaign_period`/`pre_or_post`/`intervention_arm`/`packet_variant`
  remain undeclared on every real capture (0/150), matching this file's
  own long-standing honesty about undeclared paper-campaign metadata.
- **Receiver identity / `receiver_epoch`**: `acquisition/receiver_identity.py`
  now separates `receiver_identity_id` (canonical physical B200 -- SDR
  model + real hardware serial ONLY, never the old, unreliable `device_id`
  field) from `qualified_acquisition_profile_hash` (sample rate, bandwidth,
  gain/mode, antenna/RX channel, clock/time source, capture-tool version).
  `receiver_epoch` (`acquisition/receiver_epoch_assignment.py`) is a real
  sequential session id: a new epoch starts at the first capture of an
  identity, on a qualified-profile change, or when the gap since the
  previous capture of the same identity exceeds a documented 1-hour proxy
  threshold (checked against real gap statistics, not an arbitrary
  constant) -- **not direct physical evidence of a B200 restart**, since no
  field anywhere upstream records a real boot/reconnect event. Real bug
  found and fixed: the old logic split the SAME physical B200 into 2
  spurious epochs (133 vs. 11 captures) because the legacy `device_id`
  field inconsistently held a hashed id for some captures and the raw
  serial for others. `migrate_v3_receiver_epoch.py`, run for real: 144 real
  captures unified under 1 identity, resolving into 10 real sessions.
- **`day_id` provenance**: now sourced from `capture_manifest.json`'s real
  `b200_rf_started_at` (actual RF-sampling start) first, falling back to
  `created_at_utc` (job start) only when absent; `day_id_source` is
  persisted (`B200_RF_STARTED_AT` / `CREATED_AT_FALLBACK` /
  `MANIFEST_DECLARED`). Checked against all 148 real captures with both
  fields: 0 produce a different calendar day under the old vs. new source
  -- no historical rewrite was needed.
- **Inference provenance**: every real offline inference run now persists a
  manifest (`inference_runs/<id>.json`) binding the real bundle content
  hash (`bundle_sha256`) and the real source capture's `iq_sha256` to every
  prediction -- `run_inference()`'s own public return shape is unchanged.
- **Migration ledger**: `migrations/migration_ledger.py`, a general,
  append-only audit mechanism for any script that rewrites already-persisted
  metadata (never I/Q). 150 real, non-retroactive entries plus 214
  retroactively reconstructed entries (explicitly flagged
  `retroactive: true`, using each artifact's real on-disk modification time
  as a documented timestamp proxy, never the exact original edit instant)
  for migrations performed before this ledger existed.
- **Association mechanism**: `ScientificResultsRepository.
  find_frozen_association_policy()` is implemented and **fail-closed** --
  scans real calibration attempts for one with `status=FROZEN`. **Current
  real state: it returns `None`.** All 4 real calibration attempts on disk
  show `NO_THRESHOLD_SATISFIES_CRITERIA` (coverage=0.0, false_strong=0 at
  every threshold tried), and the real corpus contains **0 STRONG
  associations among any real (`REAL_B200`) example** -- unchanged by this
  correction pass, and not weakened to produce a different result. Strong,
  source-corroborated labeling stays structurally disabled
  (`STRONG_ASSOCIATION_DISABLED_UNTIL_POLICY_FROZEN`) until a real
  calibration produces a policy that satisfies the criteria.

None of the above changes any model architecture, adds a new one, or alters
any earlier dated entry below -- they are historical records of what was
true when written and are left as-is. Where an earlier entry below describes
a state one of the items above has since changed, this block is the
authoritative current state; the entry below remains the accurate record of
what was known at that entry's own date.

## 2026-07-31 update: real identity diagnostic, see `BLE_RFFI_IDENTITY_DIAGNOSTIC_2026-07-31.md`

Ran the first-ever `SAME_MODEL_UNIT_IDENTIFICATION` training attempt with real B200 data (`keyfobdemo 01`,
`keyfobdemo 02`, `CC2541SensorTag` -- 13061 real examples, session-disjoint split, `leakage_check=PASSED`).
Result: `NO_MODEL_ACCEPTED` across all 5 candidates (logistic_regression, svm_rbf, random_forest, cnn1d,
cnn2d). The best (random_forest) hits TRAIN accuracy 1.0 but VALIDATION recall 0.0 for 2 of 3 classes --
session memorization, not physical fingerprinting, reproduced identically across 4 different model
architectures. Full numbers, root-cause breakdown (0% `STRONG` provenance, single-channel dataset, severe
session imbalance), and concrete next-capture priorities are in
`BLE_RFFI_IDENTITY_DIAGNOSTIC_2026-07-31.md`. The 3-layer dataset spec (RAW/CURATED/FROZEN, mapped to the
real contracts already in this module, plus the gaps that don't exist yet) is in
`BLE_RFFI_DATASET_SPEC_v1.md`. Neither of these touches the external 100+GB dataset audit already done
separately at `C:\Users\Usuario\Desktop\NICS\datasets\rf oracle\README_INSPECCION_DATASETS_ORACLE.md`.

## Current status and action plan (read this first)

As of 2026-07-30: no model trained so far in this project should be treated
as a validated BLE device detector or identifier. This is not a regression --
it is the honest conclusion of two independent diagnoses done this session
(one from reading the live-inference code path directly, one from a static
audit of every local dataset/evidence/training artifact,
`README_BLE_RFFI_INSPECCION.md` at the repo root). Both are summarized in
full, with code references, in "Why live detection fails despite a good TEST
score" below. This section is the short, practical answer to "what do I
actually do now" -- read the section below it for the *why*.

**Do this now -- no new captures needed:**

1. Restart the backend process. Every fix below (routes, contract fields,
   bug fixes) is already merged but a running process silently ignores code
   changes until restarted (see "Verification" at the end of this file).
2. Open the new **Benchmark** panel (Guided mode, below "Acceso directo") --
   it lists every model ever trained in this project, including the ones
   currently `REJECTED`, side by side with VALIDATION/TEST accuracy,
   macro-F1, balanced accuracy, and label provenance (% of the dataset's
   examples backed by `STRONG` association vs. `PHYSICAL_ISOLATION_DECLARED`
   vs. other/contested evidence).
3. A `REJECTED` model is not broken and does not need retraining -- it is
   `REJECTED` almost always because it was never the one model
   `prepare_and_train()` picked for the single TEST evaluation (see "Multi-
   model export" and "Opt-in TEST evaluation" below). If you want to compare
   it live in Live Monitor anyway, use its "Evaluar sobre TEST (opcional)"
   button (Step 6) or the Benchmark panel, acknowledge the one-time warning,
   export it, and approve it. This works on data you already have.
4. If you just want to redo training with the *same* captures (e.g. after
   registering a few more captures under the same project since), use
   "Reentrenar (mismas capturas)" in the Benchmark panel, or the "Restaurar
   la ultima seleccion usada" banner in Step 3. Neither needs a single new
   physical capture.

**Do NOT expect new captures + retraining alone to fix live detection.**
The dominant reason Live Monitor detects nothing real (or "detects" the
device while it is off) is a **software pipeline bug**, not a data
quantity/quality problem: Live Monitor classifies a raw energy-threshold
burst window, while every TRAIN/VALIDATION/TEST example was built from a
fully BLE-demodulated, CRC-validated, bit-aligned packet window -- two
different kinds of window feeding the same feature extractor. Retraining on
the exact same captures, or on a pile of brand-new ones, changes nothing
about this mismatch, because the mismatch lives in
`offline_inference.py::run_live()` / `spectrum_stream_worker.py`, not in any
dataset. **A fix now exists and is ON by default when started via
`start_unified.ps1`/`scripts/run_dev.ps1`** (real BLE decoding of the live
burst before classification, via `BLE_LIVE_DECODE_ENABLED` -- see "Live BLE
decode: closing the train/live window-alignment gap" below for the full
design, the real-data verification performed, and why it was built as an
additive change to the existing pipeline rather than a new dashboard).

**New captures ARE required, but for a different, separate goal: real device
*identity*.** Almost every real model trained so far answers "is a signal
compatible with my target present" (`TARGET_VS_BACKGROUND`), not "which
physical unit is this" (`SAME_MODEL_UNIT_IDENTIFICATION`) -- and even that
presence task leans heavily on `PHYSICAL_ISOLATION_DECLARED` ground truth
(the operator's own declaration that only one unit was nearby) rather than
independently corroborated association. If identity is the actual goal, that
needs a **new, deliberately designed capture campaign** -- multiple physical
units, >=3 independent sessions per unit (ideally across >=2 different
days), explicit negative controls, and less reliance on declared isolation
-- following the protocol proposed in `README_BLE_RFFI_INSPECCION.md`
("Protocolo minimo propuesto para el siguiente dataset BLE profesional").
No software change substitutes for this; it is genuinely new physical data
collection, not a code fix.

**Until further notice: keep working with the existing captures/models for
anything that does not depend on live detection working correctly** (Steps
1-6 of the Guided flow, offline evaluation, the Benchmark panel, exporting
and comparing candidates) -- all of that is real, working, unaffected by the
live-inference gap. Do not rely on Live Monitor's verdict as ground truth
until the live decode fix above ships.

## Module scope

This module never re-captures or re-decodes IQ itself. It reads the
already-validated legacy B200 capture tree (`ble/capture` module) and the
already-replayed/decoded packets (`ble/packet_analysis` module), then owns
everything downstream of that:

- `contracts/` -- pydantic schemas for every artifact (`CaptureRecord`,
  `ExampleRecord`/`ExampleAnnotation`, `DatasetManifest`, `SplitManifest`,
  `TrainingRun`, `ModelBundleManifest`, `DatasetQualityReport`). One
  vocabulary, versioned via `*_SCHEMA_VERSION` constants.
- `acquisition/capture_stage.py` -- builds a `CaptureRecord` from a legacy
  capture directory.
- `registry/` -- Physical Device Registry: `PhysicalUnitRecord` +
  `AddressBinding`, the only place an operator-declared identity is turned
  into a binding a BLE radio address can resolve to.
- `evidence/evidence_stage.py` -- turns one replayed capture into
  `ExampleRecord`/`ExampleAnnotation` pairs (association/quality/eligibility
  separated, never auto-promoted to `ELIGIBLE`).
- `dataset/`, `quality/`, `training/`, `evaluation/`, `export/`, `inference/`
  -- Fase 2-5: dataset freezing, quality gate, VALIDATION-only model
  selection + single TEST evaluation, bundle export with
  `data_origin`/`operational_use` gating, offline inference.
- `campaign/campaign_orchestrator.py` -- orchestrates a REAL capture campaign
  session end to end (hybrid B200+native-scan session -> CaptureStage ->
  resumable offline replay -> EvidenceStage), reusing the `ble_lab` module's
  hybrid/capture managers as pure mechanism.
- `api/` -- `StudioRepository` (all read/write logic), `StudioJobManager`
  (background jobs: evidence build, training, prepare-and-train, campaign
  session), `studio_routes.py` (FastAPI routes).
- `demo/synthetic_demo_seeder.py` -- SYNTHETIC_TEST_ONLY fixture generator.
  No UI entry point in Guided mode (see below); kept only as a backend
  regression fixture (`test_data_origin_gating.py`) and reachable from
  Advanced mode.
- `scientific_basis/` -- technique/preprocessing/model evidence registry (see
  its own README).

It does not perform BLE demodulation, RF acquisition, or native Windows BLE
scanning -- those remain the `ble/capture`, `ble/packet_analysis` and
`ble_lab` modules' responsibility.

## Guided Mode: capture purpose contract

The Guided UI's very first question is **"¿Que quieres capturar ahora?"** --
never a device picker forced up front, since an environment/background
capture may not need one at all. This is a real contract on `CaptureRecord`
(`contracts/capture.py`), not just frontend state:

```text
CapturePurpose = "TARGET_DEVICE" | "BACKGROUND_ENVIRONMENT"
TargetState    = "POWERED_ON" | "OPERATOR_DECLARED_POWERED_OFF_OR_REMOVED"
DatasetRole    = "POSITIVE_CANDIDATE" | "NEGATIVE_CANDIDATE"
```

- `capture_purpose` / `target_state` / `dataset_role` are derived together,
  never set independently of each other (`CampaignOrchestrator.run_session`
  and `StudioRepository._capture_type_and_decision` are the two places that
  do this derivation -- keep them in sync if this mapping ever changes).
- `target_reference_id` is documentary only: which physical unit this
  capture's declared purpose is about (the unit selected for TARGET_DEVICE,
  or the unit the operator says was off/removed for BACKGROUND_ENVIRONMENT).
  It is **never** treated as ground truth for labeling on its own.
- `CampaignOrchestrator.run_session` validates: `TARGET_DEVICE` requires a
  `physical_unit_id`; `BACKGROUND_ENVIRONMENT` requires
  `operator_confirmed_target_absent=True` (raises otherwise) and always
  forces `isolation_declared=False`, regardless of what the caller passed --
  physical isolation ("only this unit was transmitting nearby") asserts the
  opposite of what a background capture is for, so a stale/incorrect
  frontend request can never smuggle a positive label onto it.
- **The system never infers `POWERED_OFF` from the absence of a signal.**
  That state comes exclusively from the operator's explicit confirmation at
  capture time. `EvidenceStage._build_example` enforces this at the evidence
  layer: if a `BACKGROUND_ENVIRONMENT` capture's `target_reference_id` is
  set and an example's resolved `physical_unit_id` happens to match it (via
  the normal, unreliable address-binding lookup), that is treated as a real,
  honestly-surfaced **contradiction** -- `association_status="CONFLICT"`,
  `physical_unit_id=None` -- never silently trusted as a positive example.
  This reuses the existing `CONFLICT`/quarantine bucket
  (`MULTIPLE_NATIVE_CALLBACKS` uses the same status for a different reason;
  `EvidenceStage._build_annotation`'s `is_background_contradiction` check
  distinguishes the two for the annotation's `decision_reason` text).

`StudioRepository._capture_type_and_decision(capture_id)` computes, fresh
from the capture + its examples (never stored/duplicated on the capture
itself):

- `capture_type_label` -- human text for the Guided UI's captures list:
  `"Dispositivo encendido"` / `"Entorno -- dispositivo apagado"` /
  `"Entorno general"` / `"Sin clasificar"` (legacy/pre-this-feature capture,
  `capture_purpose is None`) / `"Sintetica de pruebas"`.
- `capture_decision` -- `ELIGIBLE_AS_POSITIVE` / `ELIGIBLE_AS_BACKGROUND` /
  `QUARANTINED` / `REJECTED` / `NOT_ANALYZED_YET`. "Eligible so far" here
  means the same includable set `DatasetBuilder.select_examples()` itself
  uses (quality `PASSED`, `dataset_eligibility` in
  `{PENDING_REVIEW, ELIGIBLE}`) -- Evidence Stage never itself promotes an
  example all the way to `ELIGIBLE` (that is the Fase 2 Dataset
  Builder/Analyzer gate's call, made per-dataset, not per-capture).

Both are exposed on every row from `StudioRepository.list_legacy_captures()`
(`GET /legacy-captures`), alongside the pre-existing `device_label`/
`device_source` (which answer *which device*, a different question from
*what was this capture for*).

## Frontend contract point

`frontend/src/presentation/views/ble-rffi-studio/BleRffiStudioGuided.tsx` is
the only consumer of this contract today:

- Step 1: the two-button gate (`chooseCapturePurpose`).
- Step 2: conditional device selection + the isolation checkbox
  (TARGET_DEVICE) or the operator-absence-confirmation checkbox
  (BACKGROUND_ENVIRONMENT) -- never both. Unregistered devices detected by
  the native scan are shown in a collapsed `<details>` dropdown (opened on
  click, not by default) with filters by name, MAC substring, minimum RSSI
  (dBm) and max age since last seen (`filteredUnregisteredActiveDevices`) --
  a real scan in a populated area returns many far-away devices, and the
  operator needs to narrow that down rather than scroll past all of them.
  The RSSI floor defaults to -127 dBm (the practical floor of the scale, so
  nothing is excluded until the operator opts in) -- a first version
  defaulted to -100 dBm and silently hid real far-away devices the operator
  used to see, since BLE RSSI commonly goes below -100 for those.
  Registered units' own "ACTIVO AHORA" badge also shows the matching scanned
  device's live RSSI (`activeDeviceFor(unit)`) -- an operator judging
  distance/orientation needs the number, not just an on/off indicator.

  `unregisteredActiveDevices` (the dropdown's contents) is deliberately NOT
  gated by `isDeviceActiveNow`'s 45s freshness check -- only by whether an
  address is already bound. It's a review of the LAST SCAN's results, not a
  "who is broadcasting this exact instant" indicator, so it must stay
  reviewable (collapsed, reopenable on click) even minutes later, e.g. while
  a slow capture/analysis step is still running. A first version gated the
  whole dropdown's existence on that same freshness check, so it visibly
  vanished the moment 45s elapsed since the scan -- recency is now only one
  of the opt-in filters inside it (`deviceFilterMaxAgeSeconds`, defaulted to
  3600s rather than 45s for the same reason), never a reason to unmount the
  section itself. The registered-unit "ACTIVO AHORA" badge keeps using the
  time-sensitive check, since that one genuinely means "right now".

  The scan window itself (`scanDurationSeconds`, default 8s, operator
  adjustable 1-120s next to the "Detectar dispositivos" button) was
  hardcoded at first -- 8s is a reasonable default, not a hardware limit; a
  longer window catches devices that advertise less often or are weaker,
  at the cost of a longer wait before `stop()`/`devices()` run (see above).

  `detectActiveDevices()` calls `nativeScan.stop()` **before**
  `nativeScan.devices()`, never the other way around. This isn't
  stylistic: `BleNativeJobManager` (`backend/app/infrastructure/ble/native/`,
  a separate, unmodified module) only merges the scan worker's fresh
  observations into its persistent device registry inside `_stop_scan()`'s
  `_write_scan_devices_snapshot()` call -- `GET /devices` itself
  (`manager.devices()`) just returns whatever is already in that in-memory
  registry, with no live read of the worker's snapshot. Fetching devices()
  before stop() (the original ordering) therefore only ever returned
  whatever a PREVIOUS scan had merged, which is frequently already older
  than `NATIVE_DEVICE_FRESHNESS_SECONDS` (45s) by the time it's read -- a
  real regression that showed 0 detected devices despite a real scan having
  genuinely just run. `stop()` itself can take several seconds (up to ~10s
  wait for the worker process to exit gracefully, plus SIGTERM/SIGKILL
  fallback) -- the Playwright test's timeout accounts for this.
- Step 3: launches a real campaign session (`launchCampaignSession`, forwards
  `capture_purpose`/`operator_confirmed_target_absent`) or reuses existing
  legacy captures (`useRealCaptures`) -- the latter always **rebuilds** the
  `CaptureRecord` and re-runs the evidence job rather than reusing a
  previously-built one, so a stale declaration from an earlier session
  reusing the same legacy `capture_id` can never linger. Per-session results
  (Tipo / Estado declarado / Paquetes / Elegibles / Calidad / Decision) and
  device-vs-environment progress counters are shown here.
- Captures list: "Tipo de captura" column +
  `[Todas][Dispositivo][Entorno][Sin analizar]` filters
  (`matchesCaptureFilter`).
- Technical IDs/contracts/internal states stay in Advanced mode; nothing
  above should ever require the operator to know a `capture_purpose` string
  literal exists.

Covered by `frontend/tests/e2e/ble-rffi-studio.spec.ts` -- in particular the
three mandatory tests named `Prueba 1/2/3`: a `BACKGROUND_ENVIRONMENT`
capture is never linked as positive for the declared-absent unit, a
`TARGET_DEVICE` capture's decision is a real computed verdict (never a
fabricated default), and capture type/declaration/decision survive a full
page reload (because they live on the backend's `CaptureRecord`, never only
in React state).

## Capture vs. OFFLINE_REPLAY+Evidence: deliberately separable

`OFFLINE_REPLAY` (decode) is by far the slowest phase of a campaign session
-- it can take many minutes, while the real B200 acquisition itself is only
as long as `duration_seconds` (a handful of seconds). An operator capturing
several physical devices while they happen to be powered on should not have
to wait on decode between every single one. `CampaignOrchestrator` is
structured around this split (`_acquire_capture` for the real B200 session,
`_run_replay_and_evidence` for the decode+evidence tail -- both private, both
reused by every public entry point below):

- `run_session(...)` -- the original all-in-one call: capture, then replay,
  then evidence. Holds the B200 arbiter lease for the **entire** duration,
  including decode -- fine for a single capture, wasteful for several in a
  row.
- `run_capture_only(...)` -- real B200 acquisition only. Builds the
  `CaptureRecord` and releases the B200 arbiter lease immediately after,
  *before* any decode starts. `capture_decision` for these captures reads
  `NOT_ANALYZED_YET` until replay/evidence is applied later.
- `run_replay_and_evidence_for_capture(capture_id, project_id, ble_channel)`
  -- runs the resumable decode + Evidence Stage for a `CaptureRecord` that
  already exists (from either of the above, or a manually-selected legacy
  capture). Never touches the B200 or its arbiter -- pure CPU work on an
  already-recorded file, so it can run at any time, independent of any live
  capture elsewhere.

`StudioRepository.run_campaign_session(..., capture_only: bool = False)`
picks between `run_session`/`run_capture_only`; `run_replay_and_evidence(...,
force: bool = False)` wraps the standalone replay+evidence call with an
**idempotency check**: a capture that already has evidence is reported
`{"skipped": True, "reason": "ALREADY_HAS_EVIDENCE"}` rather than silently
re-decoded (real minutes of decode time, not free) -- `force=True` is the
explicit, deliberate opt-in to redo it anyway (e.g. after fixing an
`AddressBinding`). Routes: `POST /campaign/sessions` (existing, now accepts
`capture_only`) and the new `POST
/captures/{capture_id}/replay-and-evidence-jobs` (`project_id`, `ble_channel`,
optional `force`), both via `StudioJobManager` background jobs
(`CAMPAIGN_SESSION` / `REPLAY_AND_EVIDENCE` job types).

Guided UI: a checkbox ("Solo capturar ahora (aplicar el analisis mas
tarde)") on the launch panel sets `capture_only`; both the live-session
results table and the "Capturas ya existentes" list get an "Analisis" column
-- a capture with `capture_decision === 'NOT_ANALYZED_YET'` shows an "Aplicar
analisis" button (`applyAnalysis(captureId)`), an already-processed one
shows its decision badge plus an optional "repetir" link
(`applyAnalysis(captureId, force=true)`). `useRealCaptures()` (the
"Usar captura(s) real(es)" flow) was fixed at the same time to call this new
replay+evidence job instead of the evidence-only one it used before --
evidence-only assumes a replay already exists, which silently only worked
for the one pre-replayed fixture capture every test happened to reuse; a
genuinely fresh, never-decoded legacy capture would have failed.

## Data origin / operational use gating (unchanged by the above)

Independent of `capture_purpose`, every `CaptureRecord`/`DatasetManifest`/
`TrainingRun`/`ModelBundleManifest` still carries `data_origin` (`REAL_B200`
vs `SYNTHETIC_TEST_ONLY`). A bundle trained on any synthetic data is capped at
`SYNTHETIC_PIPELINE_VERIFIED` and can never reach `EVALUATED` or
`APPROVED_FOR_LIVE_PILOT` (`export/bundle_builder.py`,
`test_data_origin_gating.py`). This gate and `capture_purpose` are
orthogonal: a capture can be `REAL_B200` + `BACKGROUND_ENVIRONMENT`, for
example, and both facts are enforced independently.

## Legacy capture list hygiene: discarded RF-failure retries + deletion

The campaign retry loop (`CampaignOrchestrator._acquire_capture`, ~46%
measured single-attempt RF overflow rate) leaves a real, complete
`capture_manifest.json` behind for **every** attempt, not just the one that
finally succeeded -- `BleCaptureLocator.list_captures()` lists any directory
with a manifest, regardless of success. Only the successful `capture_id`
ever gets a Studio `CaptureRecord` built, so every failed retry used to show
up in the Guided captures list as a bare "Sin clasificar" row,
indistinguishable from a real capture the operator just hadn't gotten to
yet -- with dozens of these accumulating from a single busy capture session,
the list looked confusingly "mixed".

`StudioRepository.list_legacy_captures()` now relabels these specifically:
a row with `acquisition_quality == "FAILED"` (overflow/discontinuity/
short-read/write-error counts, or a non-`VERIFIED` hash) that never got a
`CaptureRecord` built is shown as `"Descartada (fallo de adquisicion RF)"`
instead of `"Sin clasificar"` -- there is nothing to analyze in one, only to
discard. A capture an operator deliberately built a `CaptureRecord` for
despite `FAILED` quality (rare, e.g. investigating the overflow itself)
keeps its real label, never silently overridden.

`StudioRepository.delete_legacy_capture(capture_id)` (`DELETE
/legacy-captures/{capture_id}`) permanently removes the raw IQ directory
(real, irreversible -- these are hundreds of MB each) plus this module's own
`CaptureRecord`/evidence for it, if any were built. Validates `capture_id`
against path traversal before touching the filesystem (rejects `/`, `\`,
`..`, and any resolved path outside `legacy_capture_root`). Guided UI: a
per-row "Borrar" button behind a `window.confirm(...)` prompt (mainly meant
for cleaning up the discarded-RF-failure rows above).

## Bulk analysis + live progress for replay+evidence

The Guided captures list has sort controls (hora asc/desc, tipo, decision)
and two bulk actions -- "Aplicar analisis a la seleccion" and "...a todas las
visibles" -- alongside the existing per-row "Aplicar analisis"/"repetir".
All three funnel into the same `queueAnalysis(captureIds, force)` /
`applyAnalysis(captureId, force)` pair in `BleRffiStudioGuided.tsx`, which
process one `capture_id` at a time (sequential decodes, never concurrent)
through a small queue (`analysisQueue`/`currentAnalysisCaptureId`/
`analysisJob` state + two `useEffect`s: one advances the queue, the other
polls the active job). Discarded-RF-failure rows are excluded from bulk runs
automatically (nothing to analyze in them -- attempting one would just raise
`CAPTURE_NOT_BUILT_YET`).

This is wired into the same `ensureOperation`/`updateOperation`/
`finishOperation`/`failOperation` global-activity overlay the live B200
capture session already uses (`operationTelemetry.ts`), showing live
phase/progress/detail exactly like a capture session does -- confirmed live
against the real backend (a real capture's analysis produces the
`"APLICANDO ANALISIS (REPLAY + EVIDENCIA)"` overlay text and a real network
request to `/replay-and-evidence-jobs`, not a silent no-op).

## Step 3 -> 4 handoff: a real confusion point

Checking capture-list checkboxes does nothing by itself -- `step3Done`
(which gates Steps 4/5) only becomes true once the operator clicks "Usar N
captura(s) real(es)" (`useRealCaptures()`, which builds/rebuilds the
`CaptureRecord`s and sets `captureIds`/`dataSource`). An operator who
selected several already-analyzed captures but never clicked that button
saw every later step stay disabled with no indication why. Fixed with:
a highlighted (ring) button plus an inline banner, shown only while
`selectedLegacyIds.length > 0 && !step3Done`, stating the live device/
environment/eligible counts of the current *selection* (computed straight
from `legacy.captures`, independent of `campaignSessions`, which only
reflects this browser session's own live captures) and explicitly naming
the button to click next. Step 4 and Step 5 also each gained a short,
plain-language explanation (what "objetivo" means, and that model
selection/training is fully automatic across several candidates -- never a
manual "pick a model" step) -- see `BleRffiStudioGuided.tsx` just above each
`StepHeader`.

Still missing at that point, though: which **mix of capture types** to
actually check in the list. Nothing explained, at the point of selection,
that e.g. `TARGET_VS_BACKGROUND` needs several sessions of the SAME
device plus at least one environment session, while
`SAME_MODEL_UNIT_IDENTIFICATION` needs TWO DIFFERENT physical units (not
more sessions of one). An always-open `<details>` panel right above the
captures table now spells this out in plain language, with the real
thresholds `quality/feasibility_explainer.py`/`split_builder.py` enforce
(`_MIN_TARGET_SESSIONS=3`, `_MIN_BACKGROUND_SESSIONS=3`,
`_MIN_SESSIONS_PER_UNIT=3`, `_MIN_UNKNOWN_SESSIONS=2` -- kept in sync by
citing these constants directly in code comments, not just in prose, so a
future threshold change is a visible signal to update this panel too).

`useRealCaptures()` ("Usar N captura(s) real(es)") used to give ZERO visual
feedback while it ran -- it loops over every selected capture_id doing a
createCapture + (if not already analyzed) a full resumable replay+evidence
poll, entirely inside the generic `busy` string that only disables buttons,
with no spinner or text anywhere. With several captures selected this is
real, visible time with nothing on screen suggesting anything was
happening. Now wired into the same `ensureOperation`/`updateOperation`/
`finishOperation`/`failOperation` global-activity overlay every other
long-running action in this module uses, showing "USANDO N CAPTURA(S)
EXISTENTE(S)" with live per-capture detail ("Captura 2/10: analizando
BLE-IQ-xxxx (replay + evidencia si hace falta)...") -- confirmed live
against the real backend.

Wiring this up surfaced a real, previously-latent bug: `useRealCaptures()`
always rebuilds the `CaptureRecord` for a re-selected capture (so the
operator's just-declared `capture_purpose` always governs, see the "always
rebuild" note in `useRealCaptures()`), but rebuilding without the capture's
own `execution_id`/`session_id` fails with `SESSION_ID_MISSING_ON_CAPTURE`
for any capture that was originally built by a live campaign session --
the raw legacy manifest never records `session_id` at all (only the
orchestrator's live hybrid session ever knew it; see `CaptureStage`'s own
comment on this). Fixed by fetching the existing `CaptureRecord` (if any,
via `GET /captures/{id}`) before rebuilding and carrying its
`execution_id`/`session_id` forward -- only `capture_purpose`/
`target_state`/`target_reference_id`/`dataset_role` get freshly
re-declared, never the immutable acquisition identity.

## Per-module log file

`StudioJobManager` writes every background job's progress AND every
exception to a dedicated, human-readable log file --
`<module_root>/logs/ble_rffi_studio.log` (rotates at 5 MB, keeps 3 backups;
`module_logging.build_module_logger()`). This is in ADDITION to, never
instead of, each job's own `job.json` state -- the log is what to check
when a problem needs finding quickly without re-running the UI action while
watching the network tab. Every job type funnels through
`StudioJobManager._write()` (the one method every `_run_*_job` calls for
every progress update), so logging there covers `CAMPAIGN_SESSION`,
`REPLAY_AND_EVIDENCE`, `EVIDENCE_BUILD`, `TRAINING_RUN`, and
`PREPARE_AND_TRAIN` from a single choke point; each job's own exception
handler additionally logs the full traceback (`logger.exception(...)`, not
just the short `str(error)` `job.json` stores). Confirmed live: triggering
a real replay-and-evidence job produces a matching log line with job_id,
job_type, phase, and outcome.

## TARGET_VS_BACKGROUND single-class TRAIN bug: root cause + fix

A real B200 pilot campaign (7 `TARGET_DEVICE` captures, 0
`BACKGROUND_ENVIRONMENT` captures) produced a "successful"-looking training
result -- accuracy 1.0, a recommended model, an export-ready bundle -- while
the campaign summary showed 0 eligible examples and 0 environment sessions.
Every layer of that result was wrong, for three separate reasons:

1. **`_target_vs_background()`'s split policy was itself the bug.** The
   original design deliberately kept negative (background) examples OUT of
   TRAIN ("negatives never in TRAIN, only VALIDATION/TEST") on the theory
   that TRAIN should only ever see the positive class. This meant TRAIN
   could **never** contain more than one class for this task, by
   construction -- with 0 real background sessions this went unnoticed
   because there was nothing to exclude in the first place, but the design
   was broken even with background data present. Fixed: both target and
   background sessions are now round-robin distributed across
   TRAIN/VALIDATION/TEST identically (the same pattern already used for
   closed-set tasks), with `_MIN_BACKGROUND_SESSIONS` raised from `1` to `3`
   (one per split, symmetric with `_MIN_TARGET_SESSIONS=3`).
2. **"Background" was inferred from silence, not declared.** An example with
   `physical_unit_id=None` was counted as background purely because its
   address never matched a registered unit -- regardless of whether the
   owning capture was actually declared `BACKGROUND_ENVIRONMENT` (real
   negative evidence) or `TARGET_DEVICE` that simply failed to match (an
   inconclusive quarantine/no-match, never confirmed absence). This is the
   same "never infer `POWERED_OFF` from the absence of a signal" principle
   from the capture-purpose contract above, now found violated on the
   consuming side. Fixed by adding `ExampleRecord.capture_purpose` (a
   denormalized copy of the owning capture's declared purpose, set by
   `EvidenceStage._build_example`) and requiring
   `capture_purpose == "BACKGROUND_ENVIRONMENT"` everywhere a background
   example is counted: `SplitBuilder._target_vs_background()` and
   `feasibility_explainer.py`'s `background_declared_sessions` (renamed from
   the old, conflated `background_sessions` -- `UNKNOWN_DEVICE_REJECTION`'s
   own "unknown device" count is a genuinely different concept, ANY
   unmatched example, and stayed unfiltered on purpose).
3. **Logistic Regression/SVM raised on a single TRAIN class; Random
   Forest/CNN1D/CNN2D did not**, so the same single-class TRAIN split
   produced a hard failure for two model types and a trivial, meaningless
   "success" for the other three. Fixed with one shared, universal gate in
   `SplitBuilder._finalize()`: computed from a new `train_label_for(
   scientific_task, example)` (`TARGET_DEVICE`/`BACKGROUND_ENVIRONMENT` for
   `TARGET_VS_BACKGROUND`, else `physical_unit_id or "UNKNOWN"` -- the single
   source of truth `training_service.py`'s actual training labels also use,
   so the gate and the real training labels can never drift apart), if
   `len(train_labels) < 2` the split itself becomes `NOT_FEASIBLE` with
   reason `TRAINING_REQUIRES_AT_LEAST_TWO_CLASSES: ...` -- before any model
   type ever sees the data, so this blocks every model type uniformly
   (five at the time this gate was written; a sixth was added 2026-08-09,
   see the update block at the top of this file -- the gate is
   task-agnostic and applies to it unchanged).
   `evaluation/evaluator.py`'s `SplitEvaluationReport.evaluation_validity`
   additionally carries `INVALID_SINGLE_CLASS_EVALUATION` if `evaluate_split`
   is ever reached with under 2 known classes -- defense in depth, expected
   to be unreachable now that training itself refuses, not the primary guard.
   `export/bundle_builder.py._evaluate_acceptance` re-checks this a third
   time at export time (`TRAINING_DATA_SINGLE_CLASS` if `label_classes` has
   fewer than 2 distinct entries, `BACKGROUND_CLASS_MISSING` if a
   `TARGET_VS_BACKGROUND` bundle's `label_classes` never included
   `BACKGROUND_ENVIRONMENT`) -- a bundle is the artifact someone could hand
   to a live pilot, so it never trusts an earlier stage's gate alone.

`UNKNOWN_DEVICE_REJECTION`'s own feasibility check still literally reads
`units_ready >= 1`, but the shared `_finalize()` gate above means a single
known unit can never actually reach `READY` in practice (one known unit is
one TRAIN class). `feasibility_explainer.py` was fixed to report the real
`>= 2` requirement so the recommender never promises something the split
gate then refuses -- `_unknown_device_rejection()`'s own internal check was
deliberately left as-is, relying on the shared gate as the actual
enforcement point rather than duplicating it.

**Two more integrity gates**, both hit by the same review:
`StudioRepository._require_captures_belong_to_project()` rejects
`CAPTURE_PROJECT_MISMATCH` if any capture in a dataset's `capture_ids`
belongs to a different `project_id` than the one the dataset declares (a
dataset must never silently widen its scope with a stray capture from
another project); `export/bundle_builder.py._evaluate_acceptance`'s
`DATASET_COUNTER_MISMATCH` check rejects a bundle whose split assignments
reference an `example_id` outside the frozen `DatasetManifest.example_ids`
(proof the split was actually built from that exact frozen dataset, not a
stale or different one).

**Frontend counter bug, same root cause as #2 above but on the display
side:** the Guided UI's "ejemplos elegibles" counters (`BleRffiStudioGuided.
tsx`) filtered on `dataset_eligibility === 'ELIGIBLE'` -- but Evidence Stage
never itself sets that literal value (only `PENDING_ANALYSIS`; reaching
`ELIGIBLE` is the Dataset Builder/Analyzer gate's call, made per-dataset).
This counter had shown 0 since it was written, regardless of how many
genuinely includable examples existed -- exactly the "interface shows 0,
training uses hundreds" contradiction. Fixed with a shared
`isDatasetIncludable()` helper matching the same set
`StudioRepository._capture_decision()`/`DatasetBuilder.select_examples()`
already use (`quality_status === 'PASSED'` and `dataset_eligibility` in
`{PENDING_ANALYSIS, ELIGIBLE}`), used at all three call sites.

**Pre-training review screen**, the reviewer's explicit closing demand:
`StudioRepository.dataset_training_preview()` (`GET /datasets/{id}/
{version}/splits/{task}/training-preview`) reads strictly from the frozen
`DatasetManifest.example_ids` and the already-built `SplitManifest.
assignments` -- never recomputed independently -- and returns, per split
(TRAIN/VALIDATION/TEST): classes present, sessions per class, examples per
class, and capture_ids actually used, plus `ready_to_train` (mirrors
`split_status == "READY"`) and quarantined/excluded capture info. Guided UI
Step 5 gained a "Revisar datos que se van a usar antes de entrenar" button
(reuses the existing `ensurePreviewDataset`/`buildSplit` preview-dataset
mechanism Step 4's feasibility check already uses, version `0.0.0`) that
must be clicked before "Preparar dataset y entrenar" becomes enabled --
the button stays disabled until `trainingPreview.ready_to_train` is true,
so an operator can no longer reach training on a dataset the interface
never actually showed them.

## Capture-purpose taxonomy v2: a capture must know its own outcome immediately

The fix above corrected the training pipeline's math, but not its root cause:
an operator could still capture something genuinely broken (target never
detected, or -- worse -- detected during a supposedly target-off recording)
and only discover it minutes/hours later, at dataset-preparation time,
instead of the moment evidence for that specific capture finished building.
This section describes the fix: every capture must reach an honest,
immediate, capture-purpose-aware verdict.

### `CapturePurpose` v2 (`contracts/capture.py`)

The old 2-value `capture_purpose` (`TARGET_DEVICE` / `BACKGROUND_ENVIRONMENT`)
collapsed three genuinely different experimental intents into one generic
"background" bucket. Replaced with four:

```text
TARGET_DEVICE_ON            -- the selected physical unit is powered on;
                                positive examples are the goal.
BACKGROUND_TARGET_OFF       -- a specific unit is declared off/removed;
                                its absence is the EXPECTED, correct result.
BACKGROUND_GENERAL          -- environment recorded with no specific unit
                                in question at all.
UNKNOWN_DEVICE_COLLECTION   -- capturing unregistered transmitters, for
                                UNKNOWN_DEVICE_REJECTION only -- NEVER
                                counted as TARGET_VS_BACKGROUND negative
                                evidence.
```

Two new fields ride alongside it, both denormalized onto `ExampleRecord` too
(same pattern as the existing `capture_purpose` denormalization):

- `background_kind` (`TARGET_DECLARED_OFF_OR_REMOVED` / `GENERAL_AMBIENT`,
  `None` for the other two purposes) -- preserves the exact experimental
  flavor as its own field, independent of `capture_purpose` itself.
- `target_presence_status` (`DETECTED` / `NOT_DETECTED` / `INCONCLUSIVE` /
  `NOT_APPLICABLE`) -- computed once Evidence Stage actually runs (`None`
  before that), and persisted back onto the `CaptureRecord` at the end of
  `StudioRepository.build_evidence()` (the ONE decision-derived fact this
  module persists rather than only computing fresh each time --
  `capture_type_label`/`capture_decision` stay purely computed, per
  `_capture_decision`'s own docstring).

`DatasetRole` gained `UNKNOWN_CANDIDATE` (for `UNKNOWN_DEVICE_COLLECTION`) and
`CONTROL_ONLY` (a technically-clean capture with too few fragments to be
useful on its own). `DatasetEligibility`'s `PENDING_REVIEW` was renamed to
`PENDING_ANALYSIS` throughout (contracts, `EvidenceStage`, `DatasetBuilder`,
frontend `isDatasetIncludable()`), matching the same-meaning name the
reviewer specified.

`CampaignOrchestrator._validate_and_derive()` now derives
`(capture_purpose, target_state, dataset_role, background_kind,
target_reference_id, isolation_declared)` for all four purposes:
`TARGET_DEVICE_ON` requires `physical_unit_id`; `BACKGROUND_TARGET_OFF`
requires `operator_confirmed_target_absent` but its `target_reference_id` is
optional (the operator may declare "the target is off" without pinning one
specific registered unit); `BACKGROUND_GENERAL`/`UNKNOWN_DEVICE_COLLECTION`
need neither and always force `target_reference_id=None`; isolation
(`isolation_declared`) is forced off for every purpose except
`TARGET_DEVICE_ON` (it asserts "only this unit was transmitting nearby",
the opposite of what the other three are for).

### The capture-level decision state machine (`StudioRepository._capture_decision`)

The actual root-cause fix. The SAME raw fact -- "no eligible positive match
in this capture's own evidence" -- means opposite things depending on
`capture_purpose`:

| capture_purpose | no positive match, no contradiction | contradiction found |
|---|---|---|
| `TARGET_DEVICE_ON` | `REPETITION_NEEDED` (real problem -- never silently reinterpreted as background) | `QUARANTINED` |
| `BACKGROUND_TARGET_OFF` / `BACKGROUND_GENERAL` | `ELIGIBLE_AS_BACKGROUND` if real fragments were recovered, else `CONTROL_ONLY` -- **never penalized for the target's expected, intended absence** | `QUARANTINED` |
| `UNKNOWN_DEVICE_COLLECTION` | `ELIGIBLE_AS_UNKNOWN` if an unregistered transmitter was recovered, else `CONTROL_ONLY` | `QUARANTINED` |

`QUARANTINED` for a `BACKGROUND_*` capture is deliberately narrow:
`_has_background_contradiction()` only fires for the specific "declared-off
target actually detected with strong evidence" case (reads the annotation's
own `decision_reason` text, since `association_status=CONFLICT` alone
doesn't distinguish that from ordinary `MULTIPLE_NATIVE_CALLBACKS`
ambiguity -- `EvidenceStage` deliberately puts both in the same bucket).
That specific contradiction quarantines the WHOLE capture-level verdict even
when other, genuinely unrelated clean background traffic exists in the same
recording (the exact original bug: a real contradiction hiding behind
unrelated good data elsewhere in the same capture) -- ordinary association
ambiguity unrelated to the target-off claim does not.

`acquisition_quality` (already existed) is what plays the role of
"acquisition_status" the reviewer asked to keep separate from training
eligibility -- `PASSED` there means only "the B200 produced a correct I/Q
file", never "this capture is dataset-ready"; that is exactly what
`capture_decision` answers, computed independently.

Guided UI: `CAPTURE_DECISION_TEXT`/`CAPTURE_DECISION_TONE` render the visible
states (`VALIDADA COMO DISPOSITIVO` / `VALIDADA COMO ENTORNO` / `VALIDADA
COMO DESCONOCIDO` / `CONTROL VALIDO SIN EJEMPLOS SUFICIENTES` / `REPETICION
NECESARIA` / `CUARENTENA POR CONTRADICCION` / `SIN ANALIZAR`). The transient
"captura RF completada, analisis en curso" state is NOT a `capture_decision`
value -- it is the existing job-progress overlay (`ensureOperation`/
`updateOperation`) shown while a replay-and-evidence job is still running;
`capture_decision` only ever describes a FINISHED analysis. `"Solo capturar
ahora"` (Advanced-mode-only fast-capture checkbox) still leaves a capture at
`NOT_ANALYZED_YET` until replay/evidence is applied, exactly as before.

### Repair guidance / "Corregir y repetir" (`quality/repair_guidance.py`)

`repair_guidance(capture, examples, target_presence_status)` returns a list
of `{code, message}` items -- concrete, named causes, never a vague "capture
failed": `RF_DISCONTINUITIES` (from `capture.discontinuities`),
`INSUFFICIENT_BLE_ACTIVITY` / `LOW_ELIGIBLE_EXAMPLE_RATE` / `LOW_SNR` (a CRC-
invalid-ratio proxy -- see below), `TARGET_NOT_DETECTED`
(`TARGET_DEVICE_ON`), `TARGET_DETECTED_DURING_BACKGROUND` (`BACKGROUND_*`).
Exposed via `StudioRepository.capture_repair_guidance()` /
`GET /captures/{id}/repair-guidance`, and folded directly into
`list_legacy_captures()` rows whenever `capture_decision` is
`REPETITION_NEEDED`/`CONTROL_ONLY`/`QUARANTINED`.

**Deliberately does NOT attempt real RF saturation/SNR measurement** --
`LOW_SNR` here is a CRC-failure-ratio proxy, not a power measurement,
because Evidence Stage only ever sees already-decoded packets, never raw I/Q
power/amplitude. `ble/capture/ble_rf_diagnostics.py` already computes real
clipping ratio / noise floor / PSD from a capture's raw I/Q file as a
separate, manual qualification tool (`qualification_only: true`, `does_not_
replace_qualification: true`) -- wiring that into this automatic pipeline as
a genuine pre-capture RF preflight (comprobar saturacion y ruido antes de
capturar, per the reviewer's section 5) is NOT done here: it would mean
building new signal-processing logic with no real hardware in this session
to validate it against, which risks giving confidently wrong advice --
strictly worse than no advice. What IS implemented from section 5: the
existing native-scan "detectar dispositivos activos" mechanism already lets
an operator check whether the target is currently visible before declaring
`TARGET_DEVICE_ON`/`BACKGROUND_TARGET_OFF`; a true automated preflight gate
wired into the capture-launch flow itself is future work, to be validated
against real hardware.

Guided UI: captures table shows a `<details>` "Por que -- N causa(s)"
disclosure under the decision badge, listing every guidance message, plus a
"Corregir y repetir" button (`applyRepairAndRepeat`) that pre-fills Step
1/2's `capturePurpose`/`selectedUnitId`/`projectId` from the failed
capture's own `CaptureRecord` and scrolls to Step 3's launch button --
the operator adjusts the specific parameter the guidance named (duration,
gain, physical setup) and launches a genuinely NEW capture/session; the
original I/Q is never touched.

### Campaign versioning on objetivo change

`changeScientificTask()` (Guided UI): if the operator changes `scientificTask`
AFTER `step3Done` (captures already selected/used under the current
campaign), a confirmation dialog explains that this starts a new campaign
version, then `campaignVersion` increments, `campaignId` gets a `-v{N}`
suffix, and `captureIds`/`dataSource`/`selectedLegacyIds`/`campaignSessions`
reset -- the existing captures are never deleted, but they can no longer be
silently reinterpreted as evidence for a different scientific question than
the one they were actually gathered for.

### Migration: existing real B200 data was on disk under the old vocabulary

`migrations/migrate_v2_capture_purpose_taxonomy.py` -- a one-time,
idempotent script (`migrate_captures()` / `migrate_examples()` /
`recompute_target_presence_status()`, the last one reusing the real
`StudioRepository._capture_decision()` logic rather than reimplementing it)
that rewrites `captures/*.json` and `evidence/*/examples.jsonl` from the old
2-value vocabulary to v2, translating `BACKGROUND_ENVIRONMENT` to
`BACKGROUND_TARGET_OFF` (if `target_reference_id` was set) or
`BACKGROUND_GENERAL` (otherwise). This was not optional: this project's real,
already-captured B200 pilot data (29 captures, 42 evidence directories) was
sitting on disk under the old contract when it changed, and a stale value is
no longer valid against the new `CapturePurpose`/`DatasetEligibility`
literals (pydantic would raise reading it back). Run via
`python -m app.modules.ble_rffi_studio.migrations.
migrate_v2_capture_purpose_taxonomy` from `backend/`, with the real
storage backed up first and the live uvicorn process stopped before running
(a stale process holding the old contract in memory must never write
alongside a migration in progress). All 29/42 real records migrated cleanly;
the live backend was restarted afterward and confirmed to serve the
migrated data with no errors.

### What is NOT covered here (needs the operator's real hardware)

- **Prueba E** (a real, physical B200 campaign producing a genuine 2-class
  `TARGET_DEVICE`/`BACKGROUND_ENVIRONMENT` confusion matrix end to end) --
  requires the operator's own capture campaign (>=3 `TARGET_DEVICE_ON`
  sessions of the real device, several independent `BACKGROUND_TARGET_OFF`/
  `BACKGROUND_GENERAL` sessions with it genuinely off/removed). The
  equivalent SYNTHETIC_TEST_ONLY proof (the pipeline logic works, not that
  the physical RFFI signal is separable) already exists in
  `test_prepare_and_train.py`'s `..._on_synthetic_target_vs_background_data`
  test.
- **Live RF saturation/SNR preflight before capture** (section 5) -- see the
  "Repair guidance" section above for exactly what was and wasn't
  implemented, and why.

## Quick native-scan presence check (fast triage before "Aplicar analisis")

`GET /ble-rffi-studio/captures/{capture_id}/quick-presence-check`
(`StudioRepository.quick_presence_check` ->
`BleOfflineReplayService.quick_native_presence_check` in
`app/infrastructure/ble/capture/ble_offline_replay.py`) answers, in
under a second and without touching the IQ file at all, "was the
declared target physically seen by the native Windows BLE scan during
this capture's RF window?" It reads only `capture_manifest.json`'s
`b200_rf_started_at`/`b200_rf_finished_at` window plus the
already-preserved `advertisements.jsonl` for the session -- the
expensive part of "Aplicar analisis" (OFFLINE_REPLAY: full IQ burst
detection + decode, minutes per capture) never runs.

The target address(es) checked come from the Physical Device Registry's
own bindings for `capture.target_reference_id`
(`self.registry.list_bindings()` filtered to `project_id` +
`bound_physical_unit_id` + `binding_status == "BOUND"`) -- the SAME
resolution path `EvidenceStage._build_example` uses, never the hybrid
session's own `target_address` field (that field is always null for
this module's captures: `campaign_orchestrator.py` always launches the
native scan in `any_device`/`exploratory_target_search` mode, never a
pre-selected target).

`target_observed=False` is a reliable early `REPETITION_NEEDED`
predictor (no decode can invent a native corroboration that never
happened) -- surfaced in the Guided UI as a "verificar ahora" action the
operator can run right after capture, before committing to the slow
analysis. `target_observed=True` is NOT a guarantee of
`ELIGIBLE_AS_POSITIVE`: `MULTIPLE_NATIVE_CALLBACKS` ambiguity is only
resolved by the full packet-level `_associate()` correlation, which this
check deliberately skips. Not applicable (returns `applicable: false`
with a reason code) for isolation-declared captures (native correlation
is bypassed entirely for those), non-`TARGET_DEVICE_ON` captures, or a
target unit with no `BOUND` address yet.

### Real bug found and fixed while building this: `useRealCaptures()` silently relabeled already-declared captures

The "Capturas ya existentes" picker lets an operator multi-select
captures spanning several DIFFERENT devices at once (e.g. batching
several previously-captured sessions before training). `useRealCaptures()`
used to rebuild EVERY selected capture's `CaptureRecord` with whatever
`capture_purpose`/`target_reference_id` was selected in Step 1/2 AT THE
MOMENT "Usar N capturas" was clicked -- silently overwriting captures
that had already been correctly declared for a DIFFERENT device during
their own original live session. Root-caused via the new
quick-presence-check itself: a capture whose evidence-derived
`device_label` genuinely showed `CC2650-UNIT-01 (direccion confirmada)`
still had `target_reference_id="CC2541SensorTag"` on its `CaptureRecord`
-- the label from whichever unit happened to be selected in Step 2 the
last time captures were batch-"used", not from that capture's own
original declaration.

This did NOT corrupt the dataset itself -- `ExampleRecord.physical_unit_id`
is always derived from the real matched BLE address via the registry,
never from `capture.target_reference_id` -- but it did corrupt the
operator-facing declared-purpose labels (explaining both the confusing
"Dispositivo CC2541SensorTag: 11 sesion(es)..." summary line seen with a
batch that was mostly a different unit, and false negatives from the new
quick-presence-check against already-mislabeled captures).

Fixed in `BleRffiStudioGuided.tsx`'s `useRealCaptures()`: a capture that
already has its own `capture_purpose` (i.e. it was already
declared/built before, whenever it was first captured or classified)
now keeps its own identity untouched. Only a capture with NO prior
declaration at all (genuinely being classified for the first time) uses
today's Step 1/2 fields. Captures relabeled by the old bug before this
fix keep their corrupted `target_reference_id` on disk (no automatic
repair) until the operator re-declares them individually via "repetir
analisis" -- the frontend's evidence-derived "Dispositivo" column
(added to the Step 3 review table alongside this fix) is the reliable
source of truth for which device a capture's evidence actually shows.

## Live Monitor model check (real-time, over the SAME shared B200 session)

A "BLE-RFFI Studio" dropdown in Live Monitor's spectrum view (styled after
Spectrum Tools -- see `frontend/src/features/spectrum-tools/ui/SpectrumToolsPanel.tsx`),
implemented in `frontend/src/presentation/views/ble-rffi-studio/BleRffiLiveModelPanel.tsx`
and wired into `SpectrumView.tsx` as one additive line, lets an operator
activate/deactivate one exported+`APPROVED_FOR_LIVE_PILOT` bundle at a time to
score live BLE traffic while watching the spectrum -- **without opening a
second B200 session**. Only enabled while the current tuning overlaps the BLE
band (2400-2483.5 MHz); leaving the band auto-disables it.

Architecture (B200 opened once, shared IQ flow, FFT path never touched):

- `backend/tools/spectrum_stream_worker.py` (the existing GNU Radio flowgraph
  that already owns the UHD source for Live Monitor's spectrum) reads raw
  complex64 IQ every interval (`samples = np.asarray(tb.sink.data(), ...)`)
  for its own FFT -- this was always the one place raw IQ existed in this
  pipeline, previously discarded right after the FFT. A small, additive,
  **opt-in-only** (`ble_live_check_enabled`, off by default, toggled via the
  same "update" stdin command every other runtime setting uses) 2-slot
  rolling IQ window plus `_detect_energy_bursts()` (a lightweight in-memory
  reimplementation of `ble_sdr_capture_worker.py`'s own energy-threshold
  burst detector -- duplicated rather than imported, since that one is
  file/memmap-oriented for the disk-batch OFFLINE_REPLAY pipeline) runs ONLY
  when `_within_ble_band(center_freq_hz, sample_rate_hz)` is true, i.e. zero
  added cost while tuned to FM/WiFi/anything else. A detected burst is
  base64-encoded and emitted as a separate `"source": "ble_rffi_iq_burst"`
  JSON line, interleaved with (never replacing) the normal spectrum frames on
  the same stdout channel.
- `app/infrastructure/sdr/real_spectrum_stream.py`'s `_read_stdout` recognizes
  that source and stores it in a **single-slot** `_pending_burst` (a newer
  burst overwrites an unprocessed older one -- "keep up or drop", never a
  growing backlog), signaled via `threading.Event` to a dedicated
  `_live_check_worker_loop` background thread so a slow/failing inference
  call can never delay or block the spectrum-reading thread. Toggling is
  re-asserted automatically after any worker respawn (e.g. an unrelated
  frequency/gain change), since a fresh subprocess always starts with the
  flag back off.
- `inference/offline_inference.py`'s new `OfflineInferenceService.run_live()`
  reuses `_load_bundle`/`_representation`/`_predict_proba` UNCHANGED (the
  exact same bundle-loading, preprocessing, and scoring path `run()` uses for
  offline batch inference) but takes a raw IQ window directly -- never an
  `ExampleRecord`/`capture_id`, never touches dataset/evidence/training/
  reporting at all.
- `StudioRepository.live_check()` is the ONLY place compatibility is
  enforced. **Redesigned from an initial exact-match version**: the first
  cut required center frequency within 1 kHz AND exact sample rate equality,
  which broke the whole feature the moment the operator nudged Live
  Monitor's span/gain even slightly -- a real, reported bug ("cambio la
  banda un poco y deja de funcionar"). What actually matters physically is
  only which BLE advertising **channel** (37/38/39) the burst was captured
  on, since the feature extractor's Hz-based features (`cfo_estimate_hz`,
  `spectral_centroid_hz`, etc. -- see `representation_profiles.py`) are
  already computed correctly for whatever real `sample_rate_sps` is passed
  in. `_resolve_ble_channel()` now matches by nearest channel with a
  10 MHz tolerance; sample rate is no longer gated at all. Bandwidth is
  reported but never gated either: Live Monitor's worker only ever
  configures `center_freq_hz`/`sample_rate_hz` on the UHD source, with no
  independent analog-bandwidth concept to compare against a capture's
  `frontend_bandwidth_hz`. The acquisition reference itself comes from
  `resolve_bundle_acquisition_reference()`, reading the bundle's first
  referenced capture through the registry -- works for bundles exported
  before this feature existed too, no re-export required.
- `StudioRepository._describe_predicted_class()`: `TARGET_VS_BACKGROUND`'s
  raw classes (`TARGET_DEVICE` / `BACKGROUND_ENVIRONMENT`) are meaningless
  to an operator without knowing WHICH physical unit was the declared
  target -- this maps `TARGET_DEVICE` back to the bundle's own
  `physical_units[0]` (e.g. `"keyfobdemo 01"`) and `BACKGROUND_ENVIRONMENT`
  to a plain-language `"Entorno (sin el dispositivo objetivo)"`, returned as
  `identified_device` alongside the raw `predicted_class`. Other tasks
  (`SAME_MODEL_UNIT_IDENTIFICATION` etc.) already predict a real
  `physical_unit_id`, so it passes through unchanged.
- New routes (`api/studio_routes.py`): `GET /live-monitor/models` (only
  `APPROVED_FOR_LIVE_PILOT` bundles whose acquisition reference still
  resolves -- see "device-grouped dropdown" below for why everything else
  is silently excluded rather than shown disabled), `POST /live-monitor/enable/{bundle_id}`
  / `POST /live-monitor/disable`, `GET /live-monitor/result`, plus the
  lower-level `POST /live-monitor/live-check` (one-shot, directly testable
  via curl). Deliberately a separate URL namespace from `/bundles/{bundle_id}`
  to avoid any path-matching ambiguity, and deliberately living in this
  module's router rather than `spectrum_controller.py`, so Live Monitor's
  own spectrum routes/DI wiring stay completely untouched -- the two
  systems only ever interact through the shared `real_spectrum_stream`
  singleton, the same integration pattern other unrelated features (live
  audio demodulation) already use via
  `begin_exclusive_operation`/`end_exclusive_operation`.

### Device-grouped dropdown (real operator feedback: the first version was unreadable)

The first cut listed every bundle (including 9 unapproved synthetic ones,
each showing "Requiere aprobacion") with raw label-class names
(`TARGET_DEVICE vs BACKGROUND_ENVIRONMENT`) and no indication of model type
-- reported back as "un usuario normal no va a entender esto." Redesigned:
`list_live_selectable_bundles()` now silently excludes anything not
`APPROVED_FOR_LIVE_PILOT` or whose acquisition reference can't resolve
(never a disabled/greyed-out placeholder row -- a bundle that doesn't work
has no reason to appear at all), and additionally returns `physical_units`
(from `dataset_reference.json`, the actual device the model was trained
for) and `model_type` (from `model_manifest.json`). The frontend groups
entries by device (`groupByDevice()`) and shows a compact
`MODEL_TYPE_LABELS` badge ("Random Forest", "CNN1D", ...) next to the task
name, so the dropdown reads "keyfobdemo 01 -> Detectar el objetivo frente
al entorno [Random Forest]" instead of a bundle_id and a raw label pair.

### Result display: color reflects real confidence, not a binary flag

Originally any `final_decision == 'IDENTIFIED'` showed solid green
regardless of how close to the calibrated threshold it was -- reported back
as misleading ("me sale en verde... tengo el dispositivo apagado"). Fixed
in `BleRffiLiveModelPanel.tsx`'s `resultHue()`: nothing identified is always
red; identified below 70% confidence is a red-to-green gradient scaled by
how far above the bundle's own `acceptance_threshold` the confidence sits;
only >=70% is solid green. This is purely a presentation fix -- it makes a
weak/borderline detection visually distinguishable from a strong one, it
does not change what the model actually outputs (see "known limitation"
below for that).

A "Retener resultado (s)" control (default 6s, operator-adjustable) holds
the last positive (`IDENTIFIED`) result on screen for that long even if the
next poll comes back negative -- live burst timing varies enough that a
real detection can otherwise flash by unnoticed between two 1.5s polls.

### On-spectrum band overlay

Requested to match the other model overlays already in Live Monitor (RF
Experiment Lab's marker-band annotation): while a bundle is active, a
colored vertical band is drawn directly on the spectrum at the bundle's own
training-time channel/bandwidth (same left%/width% frequency-to-pixel math
`SpectrumView.tsx`'s own RF Experiment overlay already uses), labeled with
the device name, model type, and (when identified) the mapped device name +
confidence -- using the same red/gradient/green color as the small badge.

### Automated real-detection health check + one-click retrain

`BleRffiLiveModelPanel.tsx` (frontend-only, no new backend job type)
automates the exact manual baseline-vs-device-on comparison used to
diagnose the model-quality gap below. Two 15-second phases (device OFF,
then device ON, each operator-confirmed with a single button press since
only they know when they've actually flipped the switch), comparing
identification RATE and mean confidence between them (`computeVerdict()`):
passes only if the device-on phase shows a real jump (`+30` points of
identification rate OR `+15` points of mean confidence) -- never a raw
accuracy number, since with a live stream there is no ground truth to score
against, only "did turning the device on change anything." The verdict is
persisted to `localStorage` per `bundle_id`
(`ble-rffi-health-check-{bundle_id}`) so "los ultimos resultados reales"
survive a page reload instead of resetting to blank.

On a failing verdict, a **"Reentrenar con las capturas ya existentes"**
button appears. `StudioRepository.retrain_reference(bundle_id)` (new,
read-only resolver -- `GET /bundles/{bundle_id}/retrain-reference`) resolves
`project_id`/`campaign_id`/`scientific_task`/`ble_channel` from the bundle's
own `TrainingRun`, and `capture_ids` as **every** capture currently
registered under that `project_id` (not just the frozen dataset's original
list) -- so any real session captured since this bundle was trained (e.g.
after a failed check told the operator to record more) is automatically
picked up. The frontend then calls the pre-existing
`POST /prepare-and-train` job with that reference verbatim -- no new
training pipeline, no new job type, just the same orchestration the Guided
flow already uses, reused from a different entry point.

### Known limitation (not a bug -- a real, confirmed model-quality gap)

Manually verified against real hardware (device physically toggled on/off,
50 live samples total): the currently deployed `keyfobdemo 01` bundle
predicts `TARGET_DEVICE` on essentially every sample regardless of whether
the real device is on, off, or nothing is transmitting at all -- confidence
oscillates 0.52-0.82 in a way that tracks noise, not device presence, and it
never once predicted `BACKGROUND_ENVIRONMENT` across the whole test. A
genuine, strong RF burst (peak power jumping ~19 dB above the noise floor,
consistent with the device actually transmitting) did NOT produce a
meaningfully higher confidence than pure ambient noise elsewhere. Root
cause: too little real training data (a single physical unit, few
background sessions) for the model to have learned a real decision
boundary -- not a pipeline bug (burst detection, band matching, and fresh
per-poll scoring were all independently confirmed working). This is
exactly the gap the automated health check above is meant to catch
automatically instead of requiring a manual live A/B test every time.

### Not yet implemented: multiple simultaneous live models

Requested (now that two devices -- `keyfobdemo 01` and `CC2650-UNIT-01` --
each have an approved bundle): running two bundles' checks concurrently
against the same burst stream. Current design is deliberately single-slot
(`real_spectrum_stream._live_check_bundle_id`/`_live_check_repository`,
one active bundle at a time, activating a new one replaces the old one) --
extending this to score each detected burst against N active bundles is a
real, scoped extension (loop over active bundles in
`_live_check_worker_loop`, one `_latest_live_check_result` per bundle_id
instead of one global) but has not been built yet.

## Exporting is never restricted to the recommended model

Reported: "BLE-RFFI Studio no me deja exportar el modelo con baja
detectibilidad... quiero libertad de exportar el modelo que quiero aparte
del recomendado." Investigated and confirmed: `StudioRepository.export_bundle()`
never actually had this restriction -- it only requires
`self.get_evaluation(training_run_id)` to exist, which it does for **every**
trained candidate (every candidate gets a VALIDATION-only evaluation
persisted to disk during `prepare_and_train`'s comparison pass, win or
lose). Verified directly: exported a non-recommended, quality-gate-rejected
CNN1D candidate via `POST /training-runs/{id}/export` and it succeeded
(HTTP 201), correctly marked `REJECTED` with its real gate reasons.

The restriction was purely in the Guided UI (`BleRffiStudioGuided.tsx`):
the export handler was hardcoded to `result.recommended_training_run_id`
and the button only rendered when that was non-null. Fixed: every row in
the trained-candidates table (both the normal comparison table and the
`NO_MODEL_ACCEPTED` table) now has a radio button
(`selectedExportTrainingRunId`), and `exportSelectedModel()` exports
whichever is selected. Exporting a non-recommended candidate is labeled
"(sin TEST)" -- only the recommended run ever gets a one-time TEST
evaluation (evaluating every candidate on TEST would leak the held-out set
through model selection, so the others are exported honestly with
VALIDATION-only evaluation, never a fabricated TEST number).

## "Forzar apagado B200" (Live Monitor toolbar)

Reported: the B200 "se enciende solo y se queda encendido sin ninguna
razon." Root cause: `real_spectrum_stream.ensure_started()` auto-starts the
worker on **any** `/api/spectrum/live` poll (i.e. just having Live Monitor
open), independent of the frontend's own `isConnected` flag -- but the
existing "Disconnect" button (the only thing that calls
`real_spectrum_stream.stop()` from the UI) only renders/works when
`isConnected` is already `true`. If the stream auto-started from passive
polling without the operator ever pressing "Connect USB", there was no
visible way to stop it.

Fixed with a new button in `SpectrumView.tsx`, right next to "Connect USB",
calling the pre-existing `stopDeviceStream()` -> `POST /api/device/stream/stop`
-> `real_spectrum_stream.stop()` path **unconditionally** (no new backend
code) -- always visible and enabled regardless of `isConnected`. Verified:
calling the endpoint terminates the real worker subprocess immediately.

## "Acceso directo": export any past training run without repeating Steps 1-5

Reported: "no puedo exportar un modelo porque simplemente no salen los
modelos entrenados sin tener que pasar por etapa 1 y luego 2 o luego 3."
Root cause: the Guided wizard's `result`/`trained_models` only ever exist in
React state right after `prepare_and_train` finishes in that same page
load -- a reload, or wanting to export something trained in an earlier
session, had no path except re-running the whole guided flow (which, being
fully deterministic on the same captures/seed, wastes real time for zero
new information -- see the retrain-determinism note above).

Every training run's evaluation is already persisted to disk regardless of
whether the wizard is even open. Fixed with a new, always-visible
collapsible panel at the top of the Guided page (`allTrainingRuns`, already
fetched for the pipeline status block -- no new backend endpoint needed):
lists every training run ever created, click a row to expand its saved
evaluation (`GET /training-runs/{id}/evaluation`) and export it directly
(`POST /training-runs/{id}/export`) with its own `bundle_id`, independent of
Steps 1-5 entirely.

### Two follow-up gaps found immediately after shipping this

Reported: "no se sabe cada modelo cuando fue entrenado de que dispositivo,"
plus a bundle showing `Estado: REJECTED` with zero explanation. Both fixed:

- **`StudioTrainingRun`'s frontend type was incomplete** -- the backend
  contract has always included `started_at`/`completed_at`, but the TS
  interface never declared them, so the table couldn't show when a run was
  trained. Added both fields; new "Entrenado" column.
- **Device column**: resolved from `dataset_id`/`dataset_version` against
  `api.datasets()`'s own `physical_units` field, fetched **once** for the
  whole panel (not per row -- a naive per-row fetch would be N+1 calls
  against 47+ training runs).
- **`gate_reasons` were silently discarded.** `exportBundle()` always
  returns them (`StudioExportResult.gate_reasons`), but `exportDirect()`
  only kept `exported.bundle`, throwing away the one piece of information
  that explains `REJECTED` (`TRAINING_DATA_SINGLE_CLASS`,
  `BACKGROUND_CLASS_MISSING`, TEST accuracy below minimum, etc. -- see the
  single-class TRAIN gate section above). Now stored and displayed inline,
  with an explicit note that a `REJECTED` export is expected, correct
  behavior (the bundle really was saved; the system just won't let it be
  approved for live use) -- not a UI bug. `gate_reasons` are only ever
  returned at export time, never persisted on the bundle itself, so a
  bundle exported in an EARLIER session shows a "Reexportar para ver el
  motivo" button instead (harmless -- same `training_run_id` always
  recomputes the identical, deterministic result).

### "Acceso directo" score column: a real, confirmed trap

Added a "Puntuacion (VALIDATION)" column (`run_.metrics.VALIDATION.accuracy`,
already on the list response, no extra fetch) -- then immediately hit the
exact confusion this whole session has been about: a stale training run
(`AUTO-cnn2d-5dfed2c161`, trained BEFORE the single-class TRAIN gate fix
above) shows **100%**, and gets `REJECTED` on export with
`TRAINING_DATA_SINGLE_CLASS`. The 100% isn't wrong, it's meaningless -- a
model that only ever saw one class in TRAIN/VALIDATION trivially "predicts"
it correctly every time; that is not evidence of discrimination.

Tried to flag this using `SplitEvaluationReport.evaluation_validity`
(the `INVALID_SINGLE_CLASS_EVALUATION` field added earlier this session) --
it read back `null` for this run, because `evaluation_report.json` was
cached to disk **before** that field existed and `get_evaluation()` just
reads the stale file rather than recomputing. Fixed with a fallback that
works regardless of when the file was last written:
`confusion_matrix`'s own key count (`Object.keys(...).length < 2`) has
always been part of the schema, so it reliably flags an old cached
single-class evaluation even when the newer `evaluation_validity` field is
missing. Shown as a warning banner directly above the raw evaluation JSON
when expanded, plus an asterisk + tooltip on the score column itself.

### Root-level cleanup, not another warning: hide single-class AND failed runs by default

Two follow-ups reported in quick succession. First: "por que sale esto en
todo, no has pensado en solucionar esto desde la raiz" -- fair, a warning
banner on every single-class row was treating the symptom, not the cause.
Second (separately, exposing a real crash): "no se ha podido exportar ni un
modelo" -- caused by a genuine bug introduced while building the fix below
(`allTrainingRuns` referenced in a `useEffect` dependency array before its
own `useState` declaration later in the same component -- a real
temporal-dead-zone `ReferenceError` that broke the ENTIRE Guided page, not
just this panel, until fixed and reverified with a clean Playwright run).

Root fix: `isJunkRun()` combines two "will never be exportable" conditions
-- `status !== 'COMPLETED'` (a `FAILED` run has no `predictions.json`/
`evaluation_report.json` at all, so `export_bundle()` correctly refuses it
with `TRAINING_RUN_NOT_EVALUATED_YET`, which surfaced to the operator as a
bare, confusing 404) and the single-class check above -- and both are
**hidden from the list by default**, with a "Mostrar tambien los
descartados" checkbox to reveal them, rather than requiring the operator to
click into each one to discover it's unusable. All 47 evaluations are
fetched once, in parallel, when the panel opens (`directEvaluationsLoading`
shown while that runs), so the filter is accurate immediately instead of
each row lying until individually expanded. Expanding a revealed `FAILED`
row shows the real training exception (`run_.error`) instead of an empty
export form that can only ever fail.

## Guided capture: probe the spectrum before recording, instead of trusting the operator's word

Real request: "cuando pulso lanzar captura tiene que analisar el espectro...
en busqueda de falta de señal y luego decirme ahora enciende el dispositivo...
detectarlo primero via B200 y luego lanzar la captura real... y para captura
de entorno... analizar que no hay ninguna señal muy potente que este
destruyendo la captura." The standing problem this targets: a capture today
is only as trustworthy as the operator's manual timing -- clicking "iniciar
captura" before the device is actually on (or with something loud still
transmitting into a "background" capture) silently produces a mislabeled or
saturated recording that nothing downstream can detect, and which then
becomes exactly the kind of ambient-BLE-contaminated training data
"Known limitation" above traces the deployed model's unreliability to.

Two designs were considered: a continuous IQ stream analyzed in real time
(same mechanism as `spectrum_stream_worker.py`'s live burst detection), or a
loop of short, throwaway probe captures reusing the existing
`capture_manager.create()`/`get()` path and discarding each one immediately.
**User's explicit call: "aplica la solucion menos costosa y menos
riesgada"** -- the probe-loop approach was implemented, not the streaming
one, specifically because it adds no new long-lived hardware session and
reuses an already-proven, already-tested code path instead of a new
always-on capture mode.

`CampaignOrchestrator.run_guided_capture_only()` (`campaign/campaign_orchestrator.py`):

1. Acquires the B200 arbiter lease exactly like a normal session (same
   exclusivity guarantee -- see `SdrDeviceArbiter` above).
2. For `TARGET_DEVICE_ON`: takes a best-effort baseline probe (`PROBE_BASELINE`,
   non-fatal if it still sees energy -- the operator may already have the
   device on), then reports phase `WAITING_FOR_DEVICE` and loops short probe
   captures (default 1.0 s each, up to `probe_timeout_seconds`, default 30 s)
   until `_probe_has_energy()` sees a real burst. If nothing is detected
   within the timeout, it raises `GUIDED_CAPTURE_NO_SIGNAL_DETECTED` instead
   of silently recording an empty/negative capture under a `TARGET_DEVICE_ON`
   label.
3. For `BACKGROUND_TARGET_OFF`/`BACKGROUND_GENERAL`: reports phase
   `PROBE_ENVIRONMENT` and loops the same probe captures until
   `_probe_has_destructive_signal()` is **false** -- i.e. nothing near
   full-scale (`> 0.9` on cf32 samples nominally in [-1, 1]) is present. If
   still saturated after the timeout, raises `GUIDED_CAPTURE_ENVIRONMENT_TOO_HOT`.
4. Only then does it launch the real, kept capture (phase `REAL_CAPTURE`),
   build the `CaptureRecord` (phase `CAPTURE_STAGE`), and return the same
   result shape as `run_session()`/`run_capture_only()` -- OFFLINE_REPLAY and
   Evidence Stage are left pending, applied later via the existing "Aplicar
   analisis" action, exactly like the "Solo capturar ahora" checkbox already
   does for the non-guided flow.

Every probe capture is deleted (`repository.delete_legacy_capture()`)
immediately after its energy check, success or failure, so a guided session
never leaves throwaway probe data behind for the dataset builder to
accidentally pick up.

### Two deliberately different thresholds, not one shared "is there a signal" check

`_probe_has_energy()` (median/MAD noise-floor burst detection, same math as
`spectrum_stream_worker.py`'s `_detect_energy_bursts()`) answers "is a real
BLE burst present" -- used to confirm the device is actually on.
`_probe_has_destructive_signal()` answers a completely different question:
"is something clipping the ADC" (`> 0.9` peak magnitude). These are NOT the
same bar on purpose -- per the user's own noisy IoT environment, ambient BLE
traffic is normal and expected in a background capture (a background capture
full of ordinary neighborhood BLE is still valid background data); only a
signal strong enough to risk the ~46% RF-overflow retry rate previously
diagnosed in this environment should block a background capture from
starting. Reusing the burst-detection threshold for the background check
would have rejected almost every real background session in this operator's
environment.

### Job type + endpoint

`POST /campaign/guided-sessions` (`studio_routes.py`) accepts the same body
as `/campaign/sessions` plus optional `probe_duration_seconds` (default 1.0)
and `probe_timeout_seconds` (default 30.0), and returns a `StudioJob` with
`job_type: "GUIDED_CAPTURE"` whose `phase` field is one of
`PROBE_BASELINE` / `WAITING_FOR_DEVICE` / `PROBE_ENVIRONMENT` / `REAL_CAPTURE`
/ `CAPTURE_STAGE` / `DONE` while running.

### Frontend: reuses the existing campaign-session job state, not a parallel one

Because `run_guided_capture_only()`'s `result_summary` has the exact same
shape as the existing `launchCampaignSession()` flow (`session_id`,
`capture_id`, `capture_purpose`, `target_state`, ...), `launchGuidedCapture()`
in `BleRffiStudioGuided.tsx` feeds the SAME `campaignJob` state and the SAME
polling `useEffect` used for the normal real-capture button -- no separate
job-tracking state was needed. A "Captura guiada (verifica senal antes de
grabar)" button sits next to "Iniciar captura real con B200" in Step 3. The
`WAITING_FOR_DEVICE` phase gets a large, pulsing, impossible-to-miss banner
("AHORA ENCIENDE EL DISPOSITIVO") directly in the page (not just the small
global activity toolbar, which also gets a matching title override) since
this is the one moment the operator must act on immediately. Failures for
`GUIDED_CAPTURE_NO_SIGNAL_DETECTED`/`GUIDED_CAPTURE_ENVIRONMENT_TOO_HOT` get
their own plain-language error boxes instead of the generic "la sesion de
captura fallo" fallback.

## Sample-overlap QC failures: name the exact pair, never just a count

Real request, after "1 overlapping (non-identical) sample-range pair(s)
found." blocked Step 5: "No entiendo que ejemplos producen el error... quiero
que la interfaz muestre la pareja exacta." Explicit constraints from the
operator: never relax or disable the gate to make the message go away; if the
overlap crosses TRAIN/VALIDATION/TEST, it must be treated as leakage and
resolved automatically; if it's inside one partition, say so clearly instead
of leaving it ambiguous with a cross-partition leak.

`DatasetAnalyzer.check_sample_overlap()` (`quality/dataset_analyzer.py`) now
returns `pair_details: list[SampleOverlapPairDetail]` alongside the existing
`overlapping_pairs` (kept for backward compatibility). Each detail carries
both example_ids, both capture_ids, both exact `iq_start_sample`/
`iq_end_sample`, `overlap_samples`, `overlap_fraction_of_smaller_window`, and
a `reason` computed strictly from evidence already on the two
`ExampleRecord`s -- never guessed:

- `IDENTICAL_PACKET_DECODED_TWICE` -- same `packet_id` twice: a real
  extractor bug.
- `TWO_DISTINCT_PACKETS_SAME_BURST_WINDOW` -- different `packet_id`, same
  `candidate_id`: two independently decoded, CRC-valid packets inside one
  detected RF burst. If both also carry `association_status ==
  PHYSICAL_ISOLATION_DECLARED` with different `logical_transmitter_id`
  (decoded address), the reason names the specific likely cause: a second,
  unregistered transmitter was active nearby during an isolation-declared
  capture, so both packets got blindly attributed to the declared unit. This
  is the case that showed up in real hardware use -- see below.
- `TWO_DISTINCT_BURSTS_OVERLAP` -- different `candidate_id` entirely: two
  separately detected bursts whose windows still overlap in raw samples.

None of these three is "the extractor allows overlapping windows on
purpose" -- confirmed by reading `EvidenceStage.build_examples()`, which
emits exactly one `ExampleRecord` per decoded packet with no sliding-window
step at all. Every FAILED pair is two independently detected real RF events
landing close together, never intentional windowing.

`split_a`/`split_b`/`cross_partition` are filled in only in
`StudioRepository.dataset_training_preview()` (the exact screen "Revisar
datos que se van a usar antes de entrenar" shows), since `check_sample_
overlap()` alone runs before any split is chosen and has no split to
consult. **Cross-partition leakage never needs separate automatic-removal
logic here**: `SplitBuilder` assigns splits **session-disjoint** (a whole
capture/session belongs to exactly one of TRAIN/VALIDATION/TEST -- see
`split_builder.py`'s module docstring), and `sample_overlap`'s own overlap
check only compares examples sharing the same `source_iq_sha256` (i.e. the
same capture) -- so two overlapping examples are, by construction, always in
the same capture and therefore always the same split. `cross_partition` is
still computed for real (never assumed true) so this guarantee is visible
instead of taken on faith; and `SplitBuilder._compute_leakage` independently
checks `sample_range` as one of its own `_LEAKAGE_FIELDS`, which would mark
the whole split `NOT_FEASIBLE` (forcing a rebuild) if that invariant were
ever violated by a future split policy change -- belt and suspenders, not
one single point of failure.

Frontend (`BleRffiStudioGuided.tsx`, Step 5): when `sample_overlap_pairs` is
non-empty, each pair renders as its own card -- a `FUGA ENTRE PARTICIONES`
badge if `cross_partition` (should never appear given the guarantee above)
or a `Misma particion (TRAIN/VALIDATION/TEST)` badge otherwise, a two-row
table (`A`/`B`) with `example_id`/`capture_id`/`sample_start`/`sample_end`/
`particion`, the overlap size and percentage, and the full `reason` text --
instead of the bare "N overlapping pairs found" count that gave no way to
act on it.

Real case found and explained this way (BLE-IQ-f37b9df07274, isolation
declared for "keyfobdemo 01"): two packets decoded ~21 samples apart, CRC
valid on both, addresses `38:27:73:88:E6:A2` and `84:DD:20:F0:8D:20` --
different real devices. The gate correctly blocked training; the fix was not
a code change but removing that one contaminated capture from the dataset
selection (confirmed via a standalone script reproducing the exact same
check against the real evidence files before this UI existed).

## "Restaurar la ultima seleccion usada": skip re-checking 20-30 boxes to retrain

Real complaint: "cada vez que quiero entrenar modelos tengo que volver a
hacer el proceso largo de nuevo" -- Steps 1-3's capture picker required
manually re-ticking every checkbox (often 20-30 real captures) each time the
operator wanted to retrain, even though `useRealCaptures()`'s own logic
already respects each capture's own prior declaration and does not need
Step 1/2's fields for anything already classified.

Client-side only, per browser (`localStorage`, key
`ble-rffi-studio-last-capture-selection`): the exact `capture_ids` list
behind the last successful "Usar N captura(s) real(es)" click is remembered,
together with when it was used. A banner above the capture picker offers
"Restaurar y usar esta seleccion de nuevo" -- filtered live against captures
that still exist (so a deleted capture is silently dropped from the restored
set, never a dangling reference) -- which calls the exact same
`useRealCaptures()` action the original button does (now accepting an
optional override list) instead of a separate, parallel code path. Not a
substitute for a full dataset browser (see the still-pending "Acceso directo
a datasets" idea) -- purely a one-click shortcut back to whatever was last
selected.

## Why live detection fails despite a good TEST score, and the professional Benchmark panel

Real report: after exporting and approving `random_forest` (VALIDATION 0.717,
TEST 0.907), Live Monitor still never detected the real device and seemed to
"detect" it even while off. Root cause, confirmed by reading the code (not
guessed): **training/TEST examples and Live Monitor's live window are built
by two completely different pipelines.**

- Training/TEST (`EvidenceStage.build_examples()`): one `ExampleRecord` per
  **actually decoded BLE packet** -- `ble_offline_replay.py` does real bit
  sync, finds the preamble/access-address, decodes the PDU, checks the CRC,
  and computes `iq_start_sample`/`iq_end_sample` from the exact
  `packet_start_bit`/`packet_end_bit`. A precise, packet-aligned window.
- Live Monitor (`spectrum_stream_worker.py::_detect_energy_bursts()` ->
  `offline_inference.py::run_live()`): a pure median/MAD energy-threshold
  burst detector, with zero BLE demodulation, CRC check, or bit alignment --
  just "where did power cross a threshold", padded a couple of blocks either
  side.

The classifier's hand-crafted features (`spectral_centroid_hz`,
`cfo_estimate_hz`, `papr_db`, ...) are computed on a fundamentally different
kind of window live than in training, so it is being scored out-of-distribution
at inference time regardless of how good it looks offline -- this is also
exactly why plain energy detection alone works better live: it never depended
on that alignment in the first place.

A companion, independent professional audit
(`README_BLE_RFFI_INSPECCION.md`, static inspection of local artifacts) found
a second, compounding problem: almost every real model trained so far solves
`TARGET_VS_BACKGROUND` (presence vs. environment), not real device *identity*
(`SAME_MODEL_UNIT_IDENTIFICATION`), and a large share of positive ground
truth rests on `PHYSICAL_ISOLATION_DECLARED` (72 `STRONG` associations vs.
12,092 declared-isolation across this project's real evidence) -- weaker,
operator-trusted ground truth, not independent corroboration. Both findings
are real and compound each other; neither alone explains 100% of the
symptom.

**Decision** (this codebase's own emphasis on ground-truth rigor, per both
findings): the correct fix for the window mismatch is to run real BLE
decoding on the live burst too (same packet-aligned window as training),
**not** to retrain on undecoded energy-burst windows -- that would make
ground truth strictly worse, exactly the opposite of what both diagnoses
call for. Porting the offline BLE demodulator to run in real time on an
in-memory burst is a substantial, focused engineering task of its own and is
**not yet implemented** -- tracked here as the priority next step, not
silently attempted piecemeal.

Implemented now, informed by both diagnoses:

- **`operational_use` bug fixed** (`export/bundle_builder.py`): a `REJECTED`
  bundle could previously still read `operational_use=ALLOWED` just because
  its `data_origin` was `REAL_B200` -- now `FORBIDDEN` whenever
  `approval_status == "REJECTED"` too, regardless of data origin.
- **`macro_f1`/`balanced_accuracy` added to `SplitEvaluationReport`**
  (`evaluation/evaluator.py`): derived from the same per-class
  precision/recall/f1 already computed (never independently recomputed), so
  a model that only ever predicts the majority class can no longer hide
  behind a high raw accuracy number.
- **Label provenance report** (`StudioRepository.label_provenance_report()`,
  `GET /datasets/{id}/{version}/label-provenance`): the `association_status`
  distribution (STRONG / PHYSICAL_ISOLATION_DECLARED / AMBIGUOUS / CONFLICT /
  NONE) for any dataset's frozen examples -- purely informational, never a
  gate, so a score backed mostly by declared isolation is never presented as
  equivalent to one backed by strong independent association.
- **Benchmark panel** (`BleRffiStudioGuided.tsx`, new collapsible section
  below "Acceso directo"): every COMPLETED training run side by side --
  model type, task (explicitly labeled "Deteccion de presencia" vs.
  "Identidad de dispositivo" vs. "Rechazo de desconocidos", never shown as
  interchangeable), dataset, VALIDATION/TEST accuracy + macro-F1 + balanced
  accuracy, label provenance %, current bundle approval status, a
  "Reverificar (VALIDATION)" button (re-runs real evaluation, not cached),
  and "Reentrenar (mismas capturas)".
- **`retrain_reference_from_training_run()` +
  `GET /training-runs/{id}/retrain-reference`**: same idea as the existing
  bundle-based `retrain_reference()`, but starting from any training_run_id
  directly (works even for a candidate that was never exported). Powers
  "Reentrenar (mismas capturas)": resolves project/campaign/objetivo/canal
  and every capture currently registered under that project (picking up
  anything captured since), then calls the exact same `useRealCaptures()`
  action "Usar N captura(s) real(es)" uses (now accepting an override list),
  landing directly at Step 3 already launched -- skipping Steps 1-2 entirely.

Deliberately NOT attempted in this pass (real, substantial work, not a
quick patch): live BLE demodulation in the loop; a new multi-day,
multi-session `SAME_MODEL_UNIT_IDENTIFICATION` dataset with real
environmental audits (`README_BLE_RFFI_INSPECCION.md`'s full protocol) --
no software change can substitute for new physical data collection across
several independent days/sessions per unit.

### Benchmark panel: launching a comparison over all models, or a chosen subset

Real follow-up: the first version of the panel only ever displayed whatever
was already cached -- there was no way to actually "launch" a comparison,
and every task (`TARGET_VS_BACKGROUND`, `SAME_MODEL_UNIT_IDENTIFICATION`,
`UNKNOWN_DEVICE_REJECTION`) was interleaved in one flat list even though
models on different tasks never answer the same question and are not
comparable to each other.

- **Task filter** (`Todas las tareas` / `Deteccion de presencia` /
  `Identidad de dispositivo` / `Rechazo de desconocidos`): narrows the table
  to a genuinely comparable subset. `IDENTITY` groups
  `SAME_MODEL_UNIT_IDENTIFICATION` and `MULTI_DEVICE_CLASSIFICATION`
  together -- a UI bucket only, never used to compare a raw score across
  tasks.
- **Checkboxes + "Seleccionar todos los visibles" + "Comparar seleccionados
  (N)" / "Comparar todos los visibles (N)"**: `compareModels()` runs a REAL,
  sequential `POST /training-runs/{id}/evaluation` (VALIDATION-only) over
  exactly the chosen training_run_ids (or every currently-visible row if
  none are checked) -- this is the actual "launch", never a cached replay.
  Progress ("Verificando i/N: training_run_id") is shown while it runs.
- **Sorted by task group, then by VALIDATION accuracy descending**: the
  table is no longer in arbitrary/insertion order. The top-scoring row
  within each task group gets a `MEJOR` badge (based on VALIDATION accuracy
  only, computed fresh from whatever is in `directEvaluations` at render
  time -- disappears/moves the instant a fresher comparison changes it,
  never a stale label).

### Bug found and fixed the same day: bulk re-verification was silently deleting real TEST evaluations

Real, observed data loss: the first version of "Reverificar (VALIDATION)"
and the bulk "Comparar" action both call `evaluate_training_run(...,
include_test=False)` -- correct for a quick VALIDATION-only refresh. But
`evaluate_training_run()` always **overwrote** `evaluation_report.json`
wholesale with only the currently-requested splits, so calling it on a
training_run_id that already had a real TEST evaluation (the recommended
model's one-time evaluation, or an opt-in multi-candidate one) silently
**deleted that TEST entry from disk**. This was a pre-existing latent bug in
`evaluate_training_run()` itself (present before this session), but nothing
called it that way before -- the new Benchmark buttons were the first
callers that could ever trigger it, and clicking "Comparar todos los
visibles" over all 55 real training runs did trigger it for the project's
`APPROVED_FOR_LIVE_PILOT` models.

Fixed in `evaluate_training_run()`: when called with `include_test=False`,
it now reads any existing `TEST` entry from the current
`evaluation_report.json` on disk and carries it forward into the new one,
instead of dropping it. An explicit `include_test=True` call still freely
overwrites TEST (that is the one legitimate, deliberate case).

No permanent data was lost: `BundleBuilder.build()` writes its own frozen
copy of `evaluation_report.json` inside the bundle directory at export
time, completely independent of the training run's live file -- so every
already-exported bundle's own evaluation was untouched throughout. The 3
affected `APPROVED_FOR_LIVE_PILOT` training runs
(`AUTO-random_forest-41b410e64b`, `AUTO-random_forest-a13395082d`,
`AUTO-random_forest-f21b0cf7e1`) had their live `evaluation_report.json`'s
`TEST` entry restored from their own bundle's frozen copy, and
`evaluation_provenance.json` set back to `SINGLE_SELECTION_GUARANTEE` (what
they actually were, before the bug -- never
`OPT_IN_MULTI_CANDIDATE_COMPARISON`, which would have mislabeled them).

## Live BLE decode: closing the train/live window-alignment gap (opt-in)

Direct follow-up to "Why live detection fails despite a good TEST score"
above. Real ask: build this properly, but "con cuidado, no quiero romper
nada de lo que ya funciona" -- so this is implemented as a fully additive,
**opt-in, off-by-default** module, never a change to existing behavior
until explicitly turned on.

### What was actually needed (not a new dashboard)

The proposal on the table was a second, duplicate Live Monitor dashboard.
That would have been the wrong fix: the mismatch lives in one backend
pipeline step (burst detected -> classify), not in the UI. Duplicating the
whole dashboard (waterfall, toolbar, everything) would have doubled
maintenance for zero benefit. The real fix stays inside the SAME, single
Live Monitor.

### A discovery that changed the plan: training already depends on Gate 2A.2

Before touching any live code, traced exactly which decoder
`ble_offline_replay.py` uses for every training `ExampleRecord` -- it
subprocess-invokes `backend/tools/ble_decode_burst_directory_parallel.py`,
which imports `ble_worker.dsp_receiver`/`dsp_models` from
`C:\Users\Usuario\ble-worker-lab` (`BLE_GATE2A2_REPOSITORY`). Per
`docs/technical-readmes/ble/README.md`, this is the **same, explicitly
not-frozen Gate 2A.2 DSP/IQ-recovery effort**: best development-sweep result
381/384 (not the required 384/384), `iq_recovery_validated=false`,
`ota_validated=false`, Holdout B not yet created. **This was not previously
documented as a BLE-RFFI Studio dependency anywhere in this module's own
README** -- it is now: every real training example's ground truth already
rests on this not-yet-validated decoder, a real, pre-existing limitation
this module inherits, not one this live-decode work introduces. This
actually *supports* reusing the same decoder live (it keeps live consistent
with training, at the SAME existing risk level) rather than avoiding it.

### New module: `app/infrastructure/ble/capture/ble_live_burst_decoder.py`

`live_decode_burst(iq_samples, channel)` calls `ble_worker.dsp_receiver
.run_offline_receiver()` **directly, in-process, on the in-memory burst
array** (no subprocess, no temp files -- `run_offline_receiver` already
takes a raw numpy array and returns structured candidates/decoded results
with no file I/O of its own, confirmed by reading `dsp_receiver.py`
directly). Returns the first CRC-valid confirmed packet's precise
`packet_start_sample`/`packet_end_sample` (computed from
`candidate.sample_start + packet_start_bit/end_bit * candidate
.samples_per_symbol`, the exact same bit-to-sample conversion
`EvidenceStage._iq_end_sample()` uses for training) plus its decoded
address, or `None` if disabled, `ble-worker-lab` is unavailable, or no valid
BLE packet was found in the burst (common -- the energy detector fires on
any 2.4 GHz activity, not just BLE).

**Verified against real, already-existing data**, not just synthetic
inputs: extracted a real burst window (with margin) from
`BLE-IQ-ba2d9c0f6f78`'s actual `.sigmf-data` around a known, already-decoded
training example (`iq_start_sample=5860, iq_end_sample=7364`,
`logical_transmitter_id=TX-148E23C9A701`). `live_decode_burst()` on that raw
burst independently redecoded a CRC-valid packet at the same address
(`14:8E:23:C9:A7:01`, exact match) and the same packet length (1504
samples), offset by ~100 samples from the original absolute-file-offset
computation -- expected, since the burst was decoded with less surrounding
context than the full 40M-sample capture, not a bug.

### Wiring: `real_spectrum_stream.py::_live_check_worker_loop()`

Additive changes only, guarded so `BLE_LIVE_DECODE_ENABLED` unset/false
(the default) reproduces the exact prior behavior:

1. If enabled, resolve the BLE channel from the burst's own
   `center_frequency_hz` and call `live_decode_burst()`.
2. If it returns `None` (or a degenerate empty slice), the burst is reported
   as `final_decision: "NO_BLE_PACKET_DECODED"` -- classification is
   correctly **skipped** rather than run on a window the model never saw
   the shape of. This is a new, informative outcome, not an error; existing
   frontend code that only special-cases `final_decision === 'IDENTIFIED'`
   (`BleRffiLiveModelPanel.tsx`'s `resultHue()`/health-check summarizer)
   already treats any other value the same as `'UNKNOWN'` -- **zero
   frontend changes were required** for this to render safely.
3. If it succeeds, the classifier receives the packet-aligned sub-window
   (`iq_window[packet_start_sample:packet_end_sample]`) instead of the raw
   energy-threshold burst -- the actual fix. The decoded address is
   attached to the result (`decoded_address`, new optional field on
   `StudioLiveCheckResult`) as a diagnostic, unused by any scoring logic.

`BLE_LIVE_DECODE_ENABLED` (module-level default in
`ble_live_burst_decoder.py`, read directly from the OS environment) is
**off** unless set to `1`/`true`/`yes` -- until then this entire feature is
inert and Live Monitor's behavior is unchanged from before this work.
However, `scripts/run_dev.ps1` (the actual launcher `start_unified.ps1`
wraps) sets it to **on by default** via its own `-EnableBleLiveDecode`
parameter (default `$true`), alongside the other BLE feature flags
(`EnableBleIqCapture`/`EnableBleReplay`/`EnableBleOfflineIqAnalysis`) --
real request: "quiero esta variable en el comando principal" (stop
requiring `$env:BLE_LIVE_DECODE_ENABLED = "1"` to be set by hand in the
same terminal every time). So in practice: on whenever the app is started
the normal way, off only if something calls uvicorn directly without going
through `run_dev.ps1`. Still overridable both ways -- pass
`-EnableBleLiveDecode $false` to `run_dev.ps1`/`start_unified.ps1`, or set
`BLE_LIVE_DECODE_ENABLED` in `runtime_settings.json` -- to turn it back off
without touching code, e.g. if a hardware/environment issue is ever
suspected to be related to it.

### Verification

- New synthetic + real-data validation of `live_decode_burst()` (above).
- Full backend suite (`app/tests/`, not just `ble_rffi_studio/`) run before
  and after this change to isolate any regression risk from touching a
  shared, non-BLE-RFFI-Studio file (`real_spectrum_stream.py`): identical
  pre-existing failures in unrelated modules (`test_rf_experiment_lab.py`,
  `test_rf_intelligence.py`, `test_ti_cc2650_sensortag.py`) confirmed present
  on the unmodified file too -- not caused by this change.
  `ble_rffi_studio` suite: 200 passed, 31 skipped, both before and after.
- `npx tsc --noEmit -p .` clean after adding the new optional
  `decoded_address` field.

### Known limitation this does not remove

Even with this enabled, the underlying decoder is still the same
not-yet-frozen Gate 2A.2 candidate described above -- this closes the
train/live window-*alignment* gap, it does not make the decoder itself
independently holdout-validated. A `NO_BLE_PACKET_DECODED` result is honest
information (no valid packet found), not proof the environment is silent.

### Real, live on/off/on/off test (2026-07-30): pipeline works, model doesn't discriminate

With `BLE_LIVE_DECODE_ENABLED=1`, ran a controlled test against
`AUTO-random_forest-41b410e64b-bundle` (CC2650-UNIT-01, registered address
`B0:B4:48:C0:36:06`), polling `GET /live-monitor/result` while the operator
physically toggled the device and reported each state change in real time:

| Moment | Real device state | `decoded_address` | Matches CC2650-UNIT-01? | `class_probability` |
|---|---|---|---|---|
| Baseline | OFF | `0E:E6:DF:2E:07:A6` (ambient) | No | 0.71-0.72 |
| A few seconds after power-on | **ON** | `B0:B4:48:C0:36:06` | **Yes, real** | 0.85 -> 0.97 |
| Powered off again | OFF | `0E:E6:DF:2E:07:A6` (same ambient device) | No | 0.69 -> **0.97** |

**The pipeline fix works exactly as designed**: `peak_power_dbfs` rose
measurably (~-19/-20 dBFS baseline -> -17 dBFS) at the moment the operator
powered the device on, and `decoded_address` correctly matched the real
registered address only while it was genuinely transmitting -- both energy
detection and live BLE decoding track physical reality correctly.

**The classifier itself does not discriminate**: with the device OFF, over
a completely unrelated ambient transmitter's real, CRC-valid packets, it
reached **0.97 confidence** -- statistically indistinguishable from its
confidence on the device's own real, address-confirmed packets. This is
live, real-hardware confirmation of exactly what the professional
inspection report predicted from static analysis alone: the model was never
trained to discriminate a specific device's RF hardware fingerprint from
"some real BLE packet exists" in general. Fixing the window-alignment bug
above was necessary (it stopped the classifier from being fed literally the
wrong kind of window) but is **not sufficient** on its own -- the
deeper fix is still the dataset-quality work in "Current status and action
plan" above (real device-identity task, strong association ground truth,
multi-session/multi-day, explicit hard negatives from other real
transmitters -- this ambient device is now a documented, reproducible
candidate for exactly that hard-negative role).

## Dataset-quality follow-up: a near-miss, and two safe informational reports

Direct follow-up to the live on/off/on/off test above ("real, live... pipeline
works, model doesn't discriminate"): the operator asked to start fixing
dataset-quality problems per `README_BLE_RFFI_INSPECCION.md`'s
recommendations, explicitly prioritizing safe, non-behavior-changing
additions first after a near-miss (below).

### Near-miss: a naive isolation-contamination gate was reverted before shipping

First attempt: auto-quarantine every `PHYSICAL_ISOLATION_DECLARED` example
in a capture whenever 2+ distinct real addresses were decoded anywhere in
it. This would have **broken an existing, deliberately-designed test**
(`test_physical_isolation_declared_labels_every_packet_to_that_unit_regardless_of_address`
in `test_evidence_stage.py`, against real capture `BLE-IQ-e8edc49b59a0`):
BLE devices legitimately rotate their radio-layer address over time for
privacy, so a single real device can show 2+ different addresses across a
whole 10-second capture -- that is normal, not contamination. The real,
confirmed contamination case this session (`BLE-IQ-f37b9df07274`) had two
different addresses **21 samples (5 microseconds) apart** -- physically
impossible for one device transmitting sequentially, and a completely
different signal (near-simultaneity) than "somewhere in the same capture".
Conflating the two would have quarantined legitimate data. **Reverted before
being used anywhere** (verified via `git diff`, full suite re-run: 200
passed, 31 skipped, byte-identical to before the attempt). The already-built
dataset-level `check_sample_overlap()` gate (see "Sample-overlap QC
failures" above) is the correct mechanism for the near-simultaneity case --
it is what caught `BLE-IQ-f37b9df07274` in the first place -- and was left
untouched. A properly time-aware version of a capture-level contamination
gate remains a real, valid idea for later, but needs to check sample
proximity, never just "distinct address count over the whole capture".

### Two new, purely informational reports (no gate, no behavior change)

- **`StudioRepository.dataset_composition_report()`**
  (`GET /datasets/{id}/{version}/composition-report`): per-dataset counts by
  BLE channel, real capture day (the referenced `CaptureRecord`'s own
  `created_at` -- never the `ExampleRecord`'s, which is evidence-build time
  and can be much later than the actual RF capture), session, and physical
  unit. Surfaces a lopsided capture protocol (everything on one channel, all
  captured in one afternoon) that an aggregate accuracy number hides
  completely.
- Wired into Step 5's "Revisar datos que se van a usar antes de entrenar"
  (`BleRffiStudioGuided.tsx`), alongside the existing quality-gate/sample-
  overlap display, plus the previously-Benchmark-only `label_provenance_report()`
  now shown at this same review moment -- both purely informational,
  colored by severity, never disabling the "Preparar dataset y entrenar"
  button.

## "Captura guiada" vs "Iniciar captura real con B200": when short probes miss a real device

Real, live-hardware confusion this caused: guided capture reported
`GUIDED_CAPTURE_NO_SIGNAL_DETECTED` three times in a row for a keyfobdemo 01
that native Windows BLE scan confirmed was genuinely active (-51 dBm). Root
cause, confirmed by pulling raw `GET /api/spectrum/live` frames directly
(not guessed): the B200 hardware chain was fine the whole time -- polling
showed a real, momentary 48 dB-above-noise spike at 2402 MHz while the
device was on (a genuine BLE burst), on top of a **constant, harmless ~15-20
dB artifact permanently sitting at exactly 2402.000 MHz regardless of device
state** (LO/DC leakage, a normal SDR receiver characteristic, confirmed by
capturing the same baseline level with the device OFF too -- never BLE
traffic, never a bug).

The actual problem: "Captura guiada"'s `WAITING_FOR_DEVICE` probe loop takes
short (1s), *spaced-out* (every ~5s) snapshots -- a real but infrequent BLE
advertisement can fall in one of the gaps between probes and be missed by
bad luck, even though the exact same hardware sees it fine during a
**continuous** capture. "Iniciar captura real con B200" records the full
configured duration with no gaps at all, so it structurally cannot miss a
sparse advertisement the same way.

This is not a reason to remove "Captura guiada" -- its actual designed use
case (verifying a `BACKGROUND` capture's environment isn't currently
saturated by something too loud, via `_probe_has_destructive_signal()`) has
no "catch a sparse event" requirement at all, since it is checking for the
*absence* of an overly strong signal, not waiting to catch a rare one. The
problem was purely that nothing explained the tradeoff, so an operator
whose actual goal was "record my device reliably" reached for the wrong
button and got a repeatedly failing, misleading result.

Fixed in `BleRffiStudioGuided.tsx`, additive only (no orchestrator/backend
change):

- The "Captura guiada" button's tooltip now states the tradeoff explicitly
  (short/spaced probes vs. continuous capture) and recommends the normal
  button when the goal is recording real training data.
- A permanent caption under both buttons explains the difference in plain
  language.
- The `GUIDED_CAPTURE_NO_SIGNAL_DETECTED` error banner no longer implies the
  device is off/far away -- it now says this explicitly does not mean that,
  recommends trying the continuous capture first, and only suggests
  checking channel/distance/power if *that* also finds nothing.

## "Solo capturar ahora" batch captures: showing the DECLARED device before analysis

Real gap: "Solo capturar ahora" exists specifically to batch-capture several
devices quickly while they're on, applying `OFFLINE_REPLAY`/evidence later --
but every not-yet-analyzed capture's "Dispositivo" column showed the exact
same generic "Sin analizar aun", with no way to tell which capture was which
device after capturing 3-4 of them back to back, until every single one had
been analyzed.

`_device_label_for_capture()` now checks `capture.target_reference_id` (the
operator's own Step 2 unit selection, already recorded on the CaptureRecord
independent of isolation) before falling back to the generic message: shows
`"{unit} (declarado, sin confirmar aun)"` with a new `DECLARED_NOT_CONFIRMED`
device_source, rendered in a distinct (violet) badge color in
`DeviceLabelBadge` -- visually never confusable with `ISOLATION_DECLARED`
(cyan) or a real post-analysis `ADDRESS_MATCH` (emerald). This is the
operator's own stated intent for the capture, never a confirmed identity --
"Aplicar analisis" can still reveal a different real address, exactly the
same as before this fix. The "Solo capturar ahora" checkbox's own caption
now explains this explicitly too.

## Verification

- Backend: `backend/.venv-validation/Scripts/python.exe -m pytest
  app/tests/unit/ble_rffi_studio/` -- **200 passed, 31 skipped** as of the
  Live Monitor model-check work above (re-run after every change in this
  session with zero regressions), including
  `test_capture_decision_state_machine.py` -- Pruebas A/B/C/D plus a
  CONTROL_ONLY case -- and `test_migrate_v2_capture_purpose_taxonomy.py` --
  this venv has the full dependency set including
  `torch`/`scikit-learn`/`pydantic`; `backend/venv` is missing some of these
  and will fail to collect).
- Frontend: `npx tsc --noEmit -p .` and
  `npx playwright test tests/e2e/ble-rffi-studio.spec.ts` (8 tests, including
  `Prueba 1/2/3` and a dedicated BACKGROUND_GENERAL/UNKNOWN_DEVICE_COLLECTION
  test; the "honestly blocked" test drives the Step 5 review gate above --
  "Preparar dataset y entrenar" must stay disabled, never clicked directly,
  when the review reports infeasible) with the real backend running
  (`radioconda` or `.venv-validation` python, no `--reload` -- restart it
  after any backend code change in this module, since a stale process
  silently ignores new contract fields instead of erroring).
- Live Monitor model-check feature specifically: verified end-to-end against
  the real running backend (not just unit tests) -- `curl` against
  `/live-monitor/models`, `/live-monitor/live-check` (both a
  channel-compatible and a channel-incompatible request), `/live-monitor/enable`
  `/disable`/`result`, and `/bundles/{id}/retrain-reference`, plus ad hoc
  Playwright checks (written temporarily in `tests/e2e/`, then removed --
  not committed as permanent test files) confirming the BLE-RFFI Studio
  dropdown and Spectrum Tools render side by side without overlapping and
  remain independently clickable, and that the band-gating/disabled-checkbox
  behavior outside the BLE band is correct. Real hardware was also used
  directly (B200 physically toggled on/off) to confirm burst detection
  reacts to genuine RF changes -- see "Known limitation" above for what that
  test actually found.
- Guided capture specifically: full backend suite re-run after adding
  `run_guided_capture_only()` and the new job/route wiring -- **200 passed,
  31 skipped, zero regressions**. The probe math itself
  (`_probe_has_energy`/`_probe_has_destructive_signal`) was independently
  verified with synthetic IQ data covering pure noise (both false), a
  realistic moderate burst at ~0.3 peak magnitude (energy true, destructive
  false), and a near-clipping signal at 0.95 peak (both true) -- no real B200
  access was available in this session to drive the probe loop against
  actual hardware, so the `WAITING_FOR_DEVICE`/`PROBE_ENVIRONMENT` timeout
  and retry behavior still needs a live run before it's trusted end-to-end.
  Frontend: `npx tsc --noEmit -p .` clean, plus a Playwright load of the
  Guided page with the backend intentionally down (worst case: every API
  call fails) confirming zero `pageerror`s -- the new button/banner code
  does not crash the page even when nothing behind it is reachable; a full
  click-through of the guided flow still needs the real backend + hardware.
- Benchmark panel + operational_use fix + label provenance specifically:
  full backend suite (200 passed, 31 skipped) and `npx tsc --noEmit -p .`
  both clean. Playwright against the REAL running backend (real project
  data, not mocked) confirmed the panel opens, loads real evaluations, and
  rendered 55 "Reentrenar (mismas capturas)" buttons (one per real completed
  training run) with zero `pageerror`s. **The running backend process was
  still the pre-change one at verification time (its own `/openapi.json`
  only shows the old bundle-based `retrain-reference` route) -- restart it
  to actually pick up `/label-provenance`, `/training-runs/{id}/
  retrain-reference`, the opt-in TEST-evaluation routes, and the
  operational_use/macro_f1/balanced_accuracy fixes**, same restart caveat as
  every other backend change in this module.
- Dataset composition/label-provenance reports at Step 5: full backend
  suite (200 passed, 31 skipped) and `npx tsc --noEmit -p .` both clean;
  Playwright confirmed zero `pageerror`s. The reverted contamination-gate
  attempt was verified via `git diff` to leave `evidence_stage.py`
  byte-identical to its pre-attempt state (only earlier, unrelated
  session changes remain in the diff).
- Sample-overlap diagnostic specifically: `check_sample_overlap()` re-run
  against the exact real conflicting pair (reconstructed from the actual
  `ExampleRecord`s of BLE-IQ-f37b9df07274, since the capture itself was
  already deleted by the time this diagnostic existed) reproduces the same
  FAILED status and produces the correct `TWO_DISTINCT_PACKETS_SAME_BURST_
  WINDOW` + isolation-violation reason text; full backend suite (200 passed,
  31 skipped) and `npx tsc --noEmit -p .` both clean after the contract/
  frontend changes.
- `TEST_NOT_EXECUTED` bundle status + Benchmark tie-break display (real
  operator report): `full backend suite (201 passed, 31 skipped, 1 new)` and
  `npx tsc --noEmit -p .` both clean. Verified live against the real running
  backend, not just tests: re-exported an existing real `REJECTED` bundle
  (`AUTO-logistic_regression-1b0b6f905e-bundle`, from before this fix) and
  confirmed it now reads `TEST_NOT_EXECUTED` with a "not a failure" reason,
  same artifact_hashes/model otherwise unchanged. Of 37 real bundles on disk
  at the time, 18 were `REJECTED` this way -- most were victims of this exact
  conflation, not genuine quality failures.

### `TEST_NOT_EXECUTED` vs `REJECTED`: a non-recommended candidate is not "invalid"

Real operator report: after `prepare_and_train()` trained 5 model types that
all tied at the same VALIDATION score (0.787) and `logistic_regression` was
picked by the latency tie-break, exporting the other 4 (still-good, just
not-selected) candidates showed `REJECTED` -- reading as if training had
failed or the data were invalid, when in fact every real acceptance gate
(frozen dataset, split READY, leakage PASSED, >=2 TRAIN classes, VALIDATION
threshold) had passed. The single actual gap was `min_test_accuracy`, which
`_evaluate_acceptance()` (`export/bundle_builder.py`) could not check because
these candidates never had a TEST evaluation -- TEST stays reserved for the
one model `prepare_and_train()` itself selects (see `run_prepare_and_train()`
in `studio_repository.py`: `include_test=False` for every scored candidate,
`include_test=True` exactly once, only for `recommended`). A missing
measurement and a failed measurement were being reported identically.

Fixed by splitting `ApprovalStatus` (`contracts/bundle.py`) into a real,
distinct fifth value: `TEST_NOT_EXECUTED`. `_evaluate_acceptance()` now
tracks "hard" gate failures (genuinely broken data/training) separately from
"TEST simply was never run yet" -- only the former produces `REJECTED`; a
bundle whose sole gap is a missing TEST evaluation gets `TEST_NOT_EXECUTED`
instead, with a reason string that says so explicitly
("`TEST_NOT_EXECUTED: ... Not a failure -- opt in to a TEST evaluation...`").
`operational_use` stays `FORBIDDEN` for both statuses (neither is safe to act
on yet), and `approve_for_live_pilot()` refuses both, but with a status-
specific error message now (`CANNOT_APPROVE_A_BUNDLE_WITH_NO_TEST_EVALUATION`
vs the generic not-evaluated one) -- also fixed a pre-existing bug in that
same guard, where a real `REAL_B200`-origin `REJECTED`/`TEST_NOT_EXECUTED`
bundle used to surface the unrelated "synthetic origin" error message
(it checked `operational_use == "FORBIDDEN"` together with `data_origin`,
and both statuses set `operational_use=FORBIDDEN` regardless of origin).

Frontend (`BleRffiStudioGuided.tsx`): every place that rendered a bundle's
`approval_status` (Step 6's per-model export cell, "Acceso directo", and the
cross-run Benchmark table's Estado column) now styles `TEST_NOT_EXECUTED`
amber with an explicit "no es un rechazo" caption, distinct from `REJECTED`'s
rose styling -- and keeps the "Evaluar sobre TEST (opcional)" opt-in button
reachable even after a `TEST_NOT_EXECUTED` bundle already exists, so the
operator can complete the loop (opt in, then re-export the same bundle_id to
pick up the fresh TEST evaluation) without hunting for a separate control.

Step 6's `trained_models` table was also split from one ambiguous "Estado"
column into five explicit ones -- Modelo / Entrenamiento (always
"Completado" for anything in this list) / Candidato final (Seleccionado vs.
No seleccionado) / Puntuacion (VALIDATION) / TEST (Unico-por-seleccion vs.
No ejecutado (reservado) vs. Opcional (comparacion multiple)) / Exportar-
Live Monitor -- so "not selected" can never again be read as "not trained"
or "invalid".

**Benchmark panel's "MEJOR" tie-break bug**: `topByGroup` used to crown
whichever run happened to sort first among several runs sharing the exact
same VALIDATION accuracy as "MEJOR" -- when CNN1D and `logistic_regression`
both scored 0.787, CNN1D got the "MEJOR" badge purely from array order, even
though Step 6's real selection (`composite_score`, which also weighs latency
and unknown-rejection capability) had picked `logistic_regression` instead.
Two different rankings disagreeing about the "best" model, with only one of
them ever shown, was a real, visible inconsistency. Fixed by comparing
VALIDATION accuracy rounded to the same 3 decimals the table displays (so
two runs that show as the same number can never disagree on tie status):
a **sole** top scorer still gets the `MEJOR` badge unchanged; a **tied** top
group instead gets an amber `EMPATE` badge on every member, and -- when
`result.recommended_training_run_id` (Step 6's real pick) is one of the tied
runs -- a cyan `SELECCIONADO (desempate)` badge plus a visible (not just a
hover tooltip) line: *"Empatados en validacion; {modelo} seleccionado por
desempate ({result.recommended_reason})."*, reusing the backend's own
already-computed `_recommendation_reason()` text rather than recomputing a
separate, potentially-diverging explanation.

**TEST-reservation guarantee, verified already correct, no change needed**:
a real concern raised alongside the above ("no quiero evaluar
automaticamente todos los modelos en TEST") turned out to already be
satisfied by the existing design -- `run_prepare_and_train()` only ever calls
`evaluate_training_run(..., include_test=True)` once, for the single
`recommended` run; the generic `POST /training-runs/{id}/evaluation` route
defaults `include_test=False` and the Benchmark panel's "Comparar
seleccionados" (`compareModels()`) never passes `include_test=True`, so
re-verifying several candidates side by side stays VALIDATION-only by
construction. The only path that evaluates a non-recommended candidate on
TEST is the explicit, `window.confirm`-gated opt-in
(`optInTestEvalForResultModel`/`evaluate-on-test-opt-in`), which permanently
tags the resulting evaluation `OPT_IN_MULTI_CANDIDATE_COMPARISON` rather than
letting it pass as the single-selection guarantee.

### UI-reachable fix for the quality gate: `resolve_overlaps()` + "Resolver automaticamente"

Real operator report: the Paso 5 quality gate blocked training outright on
"1 overlapping (non-identical) sample-range pair(s) found" -- two
independently decoded, CRC-valid BLE packets (`TWO_DISTINCT_PACKETS_SAME_
BURST_WINDOW`) inside the same RF burst candidate, 95.5% sample overlap.
This gate (`check_sample_overlap()`, `quality/dataset_analyzer.py`) is
correct to block -- two "independent" training examples sharing almost the
same raw IQ samples would be leakage -- but until now the only way past it
was a developer manually inspecting the pair and hand-editing evidence.
Real ask: fix this specific case at the root, AND put a button in the UI so
any future occurrence of this class of error is self-service.

Added `DatasetAnalyzer.resolve_overlaps(examples) -> dict[example_id,
reason]` (`quality/dataset_analyzer.py`): a deterministic, reproducible
resolution, never a guess at which of two decodes is "better" (there is no
signal on an `ExampleRecord` this pipeline can independently trust for
that -- both already passed CRC/`quality_status` before reaching here).
Two rules:
- **Exact duplicates** (identical `source_iq_sha256`/start/end): keep the
  lexicographically-lowest `example_id`, exclude the rest.
- **Overlapping-but-not-identical pairs**: within each source IQ file, run
  the textbook "maximum non-overlapping interval subset" greedy sweep (sort
  by `iq_end_sample`, keep an interval only if it starts at or after the
  last KEPT interval's end) -- keeps the largest possible number of
  independent examples, and its result cannot depend on input ordering
  (verified: `test_resolve_overlaps_keeps_the_maximum_non_overlapping_
  subset` also asserts an unrelated, non-overlapping third example is never
  touched).

`StudioRepository.resolve_dataset_duplicates(capture_ids)` applies this
directly to each capture's persisted evidence (`examples.jsonl`), setting
`dataset_eligibility="QUARANTINED"` on the losing example of each
pair -- never deleted, still on disk for audit, just excluded from future
dataset builds (`DatasetBuilder.select_examples()` already treats
QUARANTINED as excluded, unchanged). Idempotent: re-running against an
already-resolved set finds nothing left to exclude. New route
`POST /datasets/resolve-duplicates` (body: `{capture_ids}`); frontend
`api.resolveDatasetDuplicates()`. Paso 5's quality-gate-failed card now has
a "Resolver automaticamente (excluir el minimo necesario) y revisar de
nuevo" button that calls it and immediately re-runs `doReviewDataset()`
(the review logic extracted out of `reviewDataset()` specifically so this
new action can await it without nesting two `run()` calls -- same reasoning
as `retrainFromTrainingRun`'s existing comment on that pattern).

Verified against the exact real reported pair, not just synthetic tests:
`resolve_dataset_duplicates()` on the real 11 selected captures quarantined
exactly `ex-8cc206af19f7c83f5157ee8574696ca1` (the same example_id shown in
the operator's own bug report) inside `BLE-IQ-1c807826ca1b`, and a fresh
dataset/quality-report rebuild from that now-fixed evidence returned
`exact_duplicates.status=PASSED`, `sample_overlap.status=PASSED`,
`gate_decision=ACCEPTED_FOR_TRAINING` (was `NOT_ACCEPTED_FOR_TRAINING`
before the fix, on the same 11 captures). Full backend suite: 204 passed,
31 skipped (3 new tests for `resolve_overlaps` itself), `npx tsc --noEmit
-p .` clean.
