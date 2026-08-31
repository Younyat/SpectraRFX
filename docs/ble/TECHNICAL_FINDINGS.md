# BLE-RFFI Technical Findings

Read-only technical findings, each derived directly from persisted code and
artifacts in this repository. No experiment was executed to produce this
document. No model was trained or retrained. TEST was not opened. No
conclusion about what any of this "means" scientifically is stated here —
that interpretation happens outside this document.

Format per finding: **Question / Observed implementation or artifact / Exact
result / Evidence source / Technical limitation.**

---

## 1. FULL_BURST TRAIN vs. PRE_PDU TRAIN

### Question

Does the PRE_PDU analytical-region control (`06_statistics/rq4_full_burst_vs_pre_pdu_exploratory_report.json`)
use the same TRAIN population as FULL_BURST/PRIMARY, or a reduced one?

### Observed implementation/artifact

`region_restricted_provider_and_eligible_ids()` (`backend/app/modules/ble_rffi_studio/packet_content/service.py:66`)
computes, for every example in the dataset, a derived array for the
requested `analytical_region` via `derive_packet_content_variants()`
(`packet_content/field_mapping.py:115`). For `PRE_PDU` specifically, that
function's own docstring and implementation state the derived array is
**always real, never `None`** — it is clipped to the source window's own
length when a burst is shorter than the full 40-bit pre-PDU span, but never
dropped. (`ADVA_EXCLUDED` is the region that can be `None`, when the PDU
type's AdvA offset is unknown — not relevant to PRE_PDU.)
`train_region_specific_variant()` (`studio_repository.py:1838`) computes
`eligible_ids` over the dataset's full example set, then intersects it with
the frozen split's own `TRAIN` assignment when calling `run_training(...,
eligible_example_ids=eligible_ids)`.

### Exact result

Computed directly (read-only) by calling the real
`region_restricted_provider_and_eligible_ids()` function for
`analytical_region="PRE_PDU"` over dataset `IDENTITY-c52850a953` /
`20260814T224525.782975Z`, then intersecting with the real frozen `TRAIN`
split assignment:

| | FULL_BURST TRAIN | PRE_PDU TRAIN |
|---|---:|---:|
| n_examples | 3,561 | 3,561 |
| n_sessions | 34 | 34 |
| CC2541SensorTag | 447 / 5 sessions | 447 / 5 sessions |
| CC2650-UNIT-01 | 522 / 7 sessions | 522 / 7 sessions |
| keyfobdemo 01 | 1,743 / 14 sessions | 1,743 / 14 sessions |
| keyfobdemo 02 | 849 / 8 sessions | 849 / 8 sessions |

**FULL_BURST TRAIN = PRE_PDU TRAIN = 3,561, identical per-unit and
per-session, in every one of the four enrolled classes. Excluded TRAIN
examples: 0.** All 79 real captures behind this dataset resolved a real I/Q
path (`capture_iq_paths_for()` returned 79/79), so no example was dropped
for a missing capture file either.

**Eligibility criterion, stated exactly:**
- FULL_BURST: membership in the frozen split's `TRAIN` assignment. No
  further derivation needed — FULL_BURST is the example's own already-loaded
  window.
- PRE_PDU: membership in the frozen split's `TRAIN` assignment, **and** a
  non-`None` return from `derive_packet_content_variants()["PRE_PDU"]` for
  that example — which, per the implementation, is every example with a
  resolvable source I/Q window (all 3,561 here).

### Evidence source

- `backend/app/modules/ble_rffi_studio/packet_content/service.py:66-92`
  (`region_restricted_provider_and_eligible_ids`)
- `backend/app/modules/ble_rffi_studio/packet_content/field_mapping.py:115-147`
  (`derive_packet_content_variants`)
- `backend/app/modules/ble_rffi_studio/api/studio_repository.py:1838-1917`
  (`train_region_specific_variant`)
- Real frozen split manifest:
  `IDENTITY-c52850a953__20260814T224525.782975Z__MULTI_DEVICE_CLASSIFICATION`
  (`split_manifest_sha256=a9e11cba...c47495d`)
- Counts recomputed this session by calling the exact same real function
  listed above against the real dataset/split on disk — not read from a
  cached report, not asserted from memory.

### Technical limitation

This confirms TRAIN-population parity, not VALIDATION-population parity
(VALIDATION parity — 2,203/2,203, identical example_ids — is already
verified separately and persisted in
`rq4_full_burst_vs_pre_pdu_exploratory_report.json`'s own
`confirmations.matched_validation_sets_verified` block). This finding does
not by itself say anything about whether the PRE_PDU model *converged*
differently than the FULL_BURST model during the fit that already occurred
— it only establishes that both fits saw the same TRAIN examples.

---

## 2. CNN training diagnostics inventory (raw I/Q → CNN1D, STFT → CNN2D)

### Question

Is there enough persisted evidence to distinguish a correctly-trained CNN
with genuinely low VALIDATION performance from a CNN that simply failed to
learn its TRAIN set?

### Observed implementation/artifact

`CnnTrainer.fit()` (`backend/app/modules/ble_rffi_studio/training/cnn_models.py:58-87`)
trains for a fixed `epochs=30` (no early stopping, no patience rule),
`Adam` optimizer, `learning_rate=1e-3`, `batch_size=16`,
`CrossEntropyLoss`, `torch.manual_seed(random_seed)` +
a seeded `DataLoader` generator. It **computes a real per-epoch TRAIN loss
list internally** (`loss_history`, appended once per epoch) **and returns
it** — but the only caller, `training_service.py:315`
(`trainer.fit(model, X["TRAIN"], y_train_idx, random_seed=..., epochs=epochs)`),
**discards the return value** (no variable capture, nothing written to
disk). No validation loss or validation accuracy is computed at any point
during training — evaluation happens exactly once, after all 30 epochs
complete, via a single `predict_proba()` call per split (TRAIN/VALIDATION/TEST).
No checkpoint is saved at any epoch; only the final, post-epoch-30 model is
persisted (`model.pt`).

### Exact result

| Diagnostic | Exists / Does not exist / Partial | Path or code reference |
|---|---|---|
| Training loss per epoch | **Does not exist (persisted).** Computed in memory (`loss_history` in `CnnTrainer.fit()`) but discarded by the only caller — never written to any file. | `cnn_models.py:75,86-87` (computed); `training_service.py:315` (discarded) |
| Validation loss per epoch | **Does not exist.** No per-epoch validation pass is ever executed — `fit()` only sees TRAIN data. | `cnn_models.py:58-87` (no eval call inside the epoch loop) |
| Training accuracy or BA (final, single snapshot) | **Exists.** One post-training TRAIN-split accuracy value (not balanced accuracy — see limitation below). | `training_runs/<run>/metrics.json` → `TRAIN.accuracy` |
| Validation accuracy or BA (final, single snapshot) | **Exists.** One post-training VALIDATION-split accuracy value (raw accuracy). Balanced accuracy for VALIDATION is separately available from `rq2_representation_comparison_report.json`. | `metrics.json` → `VALIDATION.accuracy`; `06_statistics/rq2_representation_comparison_report.json` (`balanced_accuracy`, `macro_f1`) |
| Real number of epochs run | **Exists (by code inspection, not a persisted counter).** `epochs=30`, the function-signature default; confirmed no call site anywhere in the codebase overrides it, and every real `training_run.json`'s `hyperparameters` field is `{}` (no override recorded either). | `cnn_models.py:65`; `training_service.py:278,315`; `training_runs/<run>/training_run.json` (`hyperparameters={}`) |
| Optimizer | **Exists.** `torch.optim.Adam`, hardcoded, `lr=1e-3`. | `cnn_models.py:72` |
| Learning rate | **Exists.** `1e-3`, function-signature default, never overridden (same `hyperparameters={}` evidence as epochs). | `cnn_models.py:67` |
| Seed | **Exists.** `training_run.json`'s own `random_seed=42` for both real runs; passed into `torch.manual_seed()` and the `DataLoader`'s generator. | `training_runs/<run>/training_run.json` → `random_seed`; `cnn_models.py:69,71` |
| Early stopping | **Does not exist.** No patience/monitoring logic anywhere in `CnnTrainer`; the loop always runs the full fixed `epochs` count. | `cnn_models.py:77` (`for _ in range(epochs):`, unconditional) |
| Checkpoints (intermediate, per-epoch) | **Does not exist.** Only one model state is ever persisted, after the full 30-epoch loop completes. | `cnn_models.py:58-87` (no `torch.save` inside the loop); `training_runs/<run>/model.pt` (single file) |
| Training history / logs (structured file) | **Does not exist.** No log file, no history JSON/CSV, no stdout capture persisted anywhere under either training run's directory. | Directory listing of both `training_runs/TRAIN-...-cnn1d-3e0511/` and `...-cnn2d-6b08d1/` — 9 files each, none of them a log/history artifact |
| Evidence that TRAIN loss decreased | **Does not exist.** The only TRAIN-side number persisted is a single final accuracy, not a loss curve; there is no earlier or intermediate loss value to compare it against. | (absence — see loss_history row above) |

Real final numbers, for completeness (raw accuracy, single post-training
snapshot, from `metrics.json`):

| Branch | TRAIN accuracy | VALIDATION accuracy | TEST accuracy |
|---|---:|---:|---:|
| raw I/Q (`cnn1d`) | 0.6661050266778995 | 0.7612346799818429 | 0.6943993506493507 |
| STFT (`cnn2d`) | 0.6694748666105027 | 0.6913300045392646 | 0.7674512987012987 |

### Evidence source

- `backend/app/modules/ble_rffi_studio/training/cnn_models.py` (full file, 93 lines)
- `backend/app/modules/ble_rffi_studio/training/training_service.py:278-340`
- `backend/.../training_runs/TRAIN-20260814T224700-4DEVICES-5d06e404-cnn1d-3e0511/{training_run.json,metrics.json}`
- `backend/.../training_runs/TRAIN-20260814T224700-4DEVICES-5d06e404-cnn2d-6b08d1/{training_run.json,metrics.json}`
- Directory listing of both training-run folders (9 files each: `calibration.json`,
  `evaluation_report.json`, `feature_names.json`, `label_classes.json`,
  `latency.json`, `metrics.json`, `model.pt`, `predictions.json`, `training_run.json`)

### Technical limitation

`metrics.json`'s `TRAIN`/`VALIDATION`/`TEST` fields are **raw accuracy**, not
balanced accuracy — a real, separate distinction already documented
elsewhere in this repository for the closed-set comparison (raw accuracy on
an imbalanced split, dominated by the largest class, is a different number
from balanced accuracy). No persisted artifact anywhere in this repository
currently allows reconstructing a per-epoch TRAIN or VALIDATION curve for
either CNN branch, because that data was never written to disk in the first
place — it is not a matter of searching a different file, the information
does not currently exist in persisted form. Re-computing it would require
re-running training (explicitly out of scope for this task).

---

## 3. Power/amplitude feature-group ablation — feasibility only, not executed

### Question

Can a future ablation comparing the power/amplitude engineered features
(Group A) against the remaining engineered features (Group B) be executed
later using the existing TRAIN/VALIDATION data and methodology, without
opening TEST?

### Observed implementation/artifact

The 10 engineered features are computed as one fixed-order vector by
`feature_vector_representation()` (`backend/app/modules/ble_rffi_studio/preprocessing/representation_profiles.py:77-124`),
`FEATURE_NAMES` (same file, line 70):

| Index | Feature | Group |
|---:|---|---|
| 0 | `mean_power_dbfs` | A (power/amplitude) |
| 1 | `std_power_db` | A (power/amplitude) |
| 2 | `mean_abs_amplitude` | A (power/amplitude) |
| 3 | `std_abs_amplitude` | A (power/amplitude) |
| 4 | `spectral_centroid_hz` | B (remaining) |
| 5 | `spectral_bandwidth_hz` | B (remaining) |
| 6 | `cfo_estimate_hz` | B (remaining) |
| 7 | `papr_db` | B (remaining) |
| 8 | `amplitude_kurtosis` | B (remaining) |
| 9 | `amplitude_skewness` | B (remaining) |

The classical-model training path, `TrainingService.run_baseline()`
(`training_service.py:101-141`), computes
`X = {name: self._features_for(exs) for name, exs in by_split.items()}`
(the full 10-column matrix per split), fits a fresh `TrainOnlyScaler` on
`X["TRAIN"]` only, then fits the model
(`BaselineModelTrainer.build(model_type, random_seed, hyperparameters)` →
`RandomForestClassifier(random_state=42, n_estimators=100, max_depth=None)`
for PRIMARY). No feature-subset/column-mask parameter exists anywhere in
this path today — it always consumes all 10 columns.

### Exact result (feasibility, not an execution)

| Question | Answer |
|---|---|
| Same TRAIN as PRIMARY? | **Yes.** Same 3,561 TRAIN examples/34 sessions — only the feature *columns* consumed from the already-computed 10-column vector would differ, not the examples. |
| Same VALIDATION as PRIMARY? | **Yes.** Same 2,203 VALIDATION examples/12 sessions, same reasoning. |
| Requires new model fits? | **Yes.** A `RandomForestClassifier` fit on a 4-column (Group A) or 6-column (Group B) matrix is a different fitted model than PRIMARY's 10-column fit; PRIMARY's already-fit model cannot be reused or re-scored on a different column count. At minimum 2 new fits (Group A, Group B). |
| Can TEST remain fully closed? | **Yes.** `evaluate_training_run(..., include_test=False)` already exists and is the exact mechanism the PRE_PDU control used; nothing about a feature-subset ablation requires TEST. |
| Same Random Forest configuration reusable? | **Yes.** `RandomForestClassifier(random_state=42, n_estimators=100, max_depth=None)` does not declare a fixed input-feature count; the identical configuration fits directly on a 4- or 6-column matrix. |
| Same preprocessing reusable? | **Yes.** `base-v1` identity preprocessing already produces the full 10-feature vector as an intermediate; the ablation only needs a column subset of an already-computed vector — no new I/Q-level preprocessing. |
| Same seed reusable? | **Yes.** `random_seed=42` passes into `BaselineModelTrainer.build()` unchanged regardless of feature-matrix width. |
| Same session-clustered/class-stratified bootstrap reusable? | **Yes.** `matched_stratified_bootstrap_delta_ci()` (`backend/app/modules/ble_scientific_results/statistics/inference.py:352`) operates on `(true_label, predicted_label)` pairs from VALIDATION predictions and a `physical_unit_id`/`session_id` grouping — it does not depend on which features produced those predictions. Both ablation arms would score the *same* VALIDATION examples (same `example_id`s), which is exactly the precondition this function already requires (used verbatim for FULL_BURST vs. PRE_PDU). |
| New artifacts that would need to be created | Two new `TrainingRun`/bundle records (Group A, Group B), each with the same file shape as the PRE_PDU precedent (`training_run.json`, `model.joblib`, `scaler.joblib`, `predictions.json`, `metrics.json`, `evaluation_report.json` VALIDATION-only, exported bundle with `approval_status=TEST_NOT_EXECUTED`); a new persisted statistics report (analogous to `rq4_full_burst_vs_pre_pdu_exploratory_report.json`) holding both arms' BA/CI/macro-F1/confusion matrices plus the matched-bootstrap delta. |
| Code that already exists and is reusable as-is | `TrainOnlyScaler`, `BaselineModelTrainer` (RF config), `evaluate_training_run(include_test=False)`, the bundle-export `TEST_NOT_EXECUTED` gate, `matched_stratified_bootstrap_delta_ci()` — the entire PRE_PDU code path is a direct structural precedent. |
| Minimal code that would still be missing | A feature-column-subset hook in the classical training path (today `run_baseline()` always consumes all 10 columns) — e.g. an optional parameter selecting which `FEATURE_NAMES` indices to keep before fitting the scaler, analogous to how `train_region_specific_variant()` wraps `run_training()` with a region-restricted I/Q provider for PRE_PDU. No such column-subset hook exists today. |

**No BA, F1, CI, or any other metric is reported here — this ablation was
not executed.**

### Evidence source

- `backend/app/modules/ble_rffi_studio/preprocessing/representation_profiles.py:70-124`
- `backend/app/modules/ble_rffi_studio/training/training_service.py:101-141`
- `backend/app/modules/ble_rffi_studio/api/studio_repository.py:1838-1917` (`train_region_specific_variant`, the structural precedent)
- `backend/app/modules/ble_scientific_results/statistics/inference.py:352` (`matched_stratified_bootstrap_delta_ci`)
- `06_statistics/rq4_full_burst_vs_pre_pdu_exploratory_report.json` (the real, already-executed analogous case this feasibility analysis is modeled on)

### Technical limitation

This is a code-and-artifact feasibility read, not a guarantee about model
behavior — e.g., a 4-column or 6-column Random Forest fit could encounter a
degenerate case (a feature with zero variance within a stratum, an
edge-case interaction with `TrainOnlyScaler`) that would only surface at
actual fit time, not from static inspection. No claim is made here about
what such an ablation would show.

---

## 4. TX-0x pseudonym mapping — provenance note

### Question

Is the `TX-01`/`TX-03`/`TX-04`/`TX-05` pseudonym scheme defined by any
canonical artifact in this repository?

### Observed implementation/artifact

Searched `PhysicalDeviceRegistry` records
(`backend/app/infrastructure/persistence/storage/ble_rffi_studio/registry/physical_units/*.json`
for all four enrolled units) and `docs/ble/physical_device_inventory.json`
for any `TX-0x`-style field. A repository-wide search for `TX-01`/`TX-03`/
`TX-04`/`TX-05` found no match in any of these canonical sources. The only
real `TX-`-prefixed identifiers found anywhere in the repository are
`logical_transmitter_id` values inside per-capture
`transmitter_catalog.json` files (`packet_analysis_cache/BLE-PKTLAB-*/`) —
these are auto-assigned, per-capture labels for arbitrary *observed ambient
BLE addresses*, structurally unrelated to the four enrolled physical units
and not a candidate source for this mapping.

### Exact result

**No canonical artifact in this repository defines a `TX-01`/`TX-03`/
`TX-04`/`TX-05` pseudonym scheme for the four enrolled units.** The mapping
applied to figures in this change
(`CC2541SensorTag`→`TX-01`, `keyfobdemo 01`→`TX-03`, `keyfobdemo 02`→`TX-04`,
`CC2650-UNIT-01`→`TX-05`) was supplied directly this turn and is applied as
a new, display-only labeling convention
(`PHYSICAL_UNIT_PSEUDONYM_LABELS` in `paper_export.py`) — it does not
originate from, and was not cross-checked against, any pre-existing
registry field.

### Evidence source

- `backend/app/infrastructure/persistence/storage/ble_rffi_studio/registry/physical_units/{CC2541SensorTag,CC2650-UNIT-01,"keyfobdemo 01","keyfobdemo 02"}.json`
- `docs/ble/physical_device_inventory.json`
- Repository-wide search for `TX-0[1345]` across `*.py`/`*.json`/`*.md`

### Technical limitation

No internal identifier was renamed anywhere as a result of this mapping
(`physical_unit_id` values remain unchanged in every dataset, manifest,
bundle, and provenance record). Prose text in `README.md` and
`docs/ble/TECHNICAL_EVIDENCE_AUDIT.md` still refers to the four units by
their internal `physical_unit_id` throughout — the pseudonym substitution
in this change was applied only to the figure-generation code path listed
in the corresponding commit, not to existing prose in either document.
