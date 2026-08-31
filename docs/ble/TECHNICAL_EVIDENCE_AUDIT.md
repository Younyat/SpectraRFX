# BLE-RFFI Technical Evidence Audit

Snapshot generated: 2026-08-23, from live queries against real persisted artifacts and code in this repository. No experiments were executed to produce this document. No model was retrained. TEST was not re-opened (all TEST values below are read from already-persisted artifacts). CH37→CH38 transport, RQ3, RQ4 packet-condition, and FUTURE were not executed.

`paper_run_id`: `paper-run-2805869e6282778ad729a26d022ec9b0`
`dataset_id` / `dataset_version` (canonical closed-set dataset): `IDENTITY-c52850a953` / `20260814T224525.782975Z`
`split_manifest_id`: `IDENTITY-c52850a953__20260814T224525.782975Z__MULTI_DEVICE_CLASSIFICATION`
`git_sha` recorded on the RQ1/RQ2/RQ4 artifacts: `c7c3343029aebea51eedb5f5c4de6c27f7cae339`

---

## 1. RQ1 — current result

| Domain | BA | 95% CI | n_examples | n_sessions |
|---|---|---|---|---|
| Capture-dependent (diagnostic) | 0.9578781766067187 | [0.9389651703995975, 0.9751987706077437] | 1,790 | 34 |
| Capture-disjoint VALIDATION | 0.6338138990398197 | [0.5912219610540254, 0.6850857789866278] | 2,203 | 12 |
| Δ (dependence) | 0.32406427756689904 | [0.2686419390410907, 0.3706519487491247] | — | — |

Source artifact: `06_statistics/rq1_acquisition_dependence_report.json`, field `uncertainty_ci`. Repository path: [`backend/app/infrastructure/persistence/storage/scientific_reports/ble/paper-run-2805869e6282778ad729a26d022ec9b0/06_statistics/rq1_acquisition_dependence_report.json`](../../backend/app/infrastructure/persistence/storage/scientific_reports/ble/paper-run-2805869e6282778ad729a26d022ec9b0/06_statistics/rq1_acquisition_dependence_report.json) (already versioned in this repository, no copy made).

**Method actually implemented (verified against code, not against prose):**
- Cluster unit: `session_id`.
- Stratification: `physical_unit_id` — each enrolled unit's own sessions are resampled independently of the other units' sessions inside each replicate, so no replicate can ever drop a class from the 4-class balanced-accuracy estimand.
- `n_resamples=2000`, percentile CI, `seed=12345`.
- Δ is **not** a paired/matched statistic: the two domains (capture-dependent, capture-disjoint) have no physical session pairing, so each domain is resampled **independently** and the difference is taken per replicate pair. This is recorded verbatim in the artifact's own `method` string: `"independent_domain_bootstrap_delta_ci (independent, class-stratified resample of each domain, per-replicate difference; NOT paired ... NOT ci_window - ci_capture)"`.

**Code:**
- `stratified_hierarchical_cluster_bootstrap()` — `backend/app/modules/ble_scientific_results/statistics/inference.py:301`
- `independent_domain_bootstrap_delta_ci()` — `backend/app/modules/ble_scientific_results/statistics/inference.py:415`
- Wired into `Evaluator.bootstrap_balanced_accuracy_ci_stratified_by_class()` / `.bootstrap_balanced_accuracy_delta_ci_stratified_by_class()` — `backend/app/modules/ble_rffi_studio/evaluation/evaluator.py:278`, `:301`
- Orchestrated by `run_rq1_acquisition_dependence()` — `backend/app/modules/ble_scientific_results/rq1_runner.py:95`

`confirmatory_split_manifest_sha256`: `a9e11cba02ecf4db6dd1ca60b46bb7bf52cd73761e7dd64894c4f45b7c47495d` — recomputed independently this session via the model's own `content_hash()` and confirmed byte-identical to the stored field (§15).

---

## 2. RQ2 — four pipelines

All four branches evaluated on the identical 2,203-example, 12-session capture-disjoint VALIDATION partition.

| Branch | Model | BA | Macro-F1 | n_examples | n_sessions | Candidate model families | Hyperparameter searches | training_run_id |
|---|---|---|---|---|---|---|---|---|
| `engineered_rf` (PRIMARY) | random_forest | 0.6338138990398197 | 0.5864106215528908 | 2,203 | 12 | 3 (logistic_regression, svm_rbf, random_forest) | 0 | `TRAIN-20260814T224700-4DEVICES-5d06e404-random_forest-a598bd` |
| `stft` | cnn2d | 0.5368629979844066 | 0.4981031304046958 | 2,203 | 12 | 1 | 0 | `TRAIN-20260814T224700-4DEVICES-5d06e404-cnn2d-6b08d1` |
| `coarse_morphology` | frozen_morphological_baseline | 0.27722602530013735 | 0.1280526288155485 | 2,203 | 12 | 1 | 0 | `TRAIN-20260814T224700-4DEVICES-5d06e404-frozen_morphological_baseline-c28278` |
| `raw_iq` | cnn1d | 0.24807692307692308 | 0.22643802322441264 | 2,203 | 12 | 1 | 0 | `TRAIN-20260814T224700-4DEVICES-5d06e404-cnn1d-3e0511` |

Bundle: `CLOSED-SET-4DEVICES-random_forest-bundle` (`engineered_rf`/PRIMARY only — the other three branches are not exported as bundles). Bundle manifest published at [`docs/ble/evidence/bundle_manifest_PRIMARY_CLOSED-SET-4DEVICES-random_forest-bundle.json`](evidence/bundle_manifest_PRIMARY_CLOSED-SET-4DEVICES-random_forest-bundle.json) (the underlying `ble_rffi_studio/bundles/` tree is not otherwise versioned in this repository).

Source artifact: `06_statistics/rq2_representation_comparison_report.json`. Repository path: [`backend/.../06_statistics/rq2_representation_comparison_report.json`](../../backend/app/infrastructure/persistence/storage/scientific_reports/ble/paper-run-2805869e6282778ad729a26d022ec9b0/06_statistics/rq2_representation_comparison_report.json) (already versioned, no copy made).

**Facts, no ranking claim:** `engineered_rf` had 3 candidate model families evaluated on VALIDATION with the best of the three selected (`select_primary_rq2_branch_from_validation`); `raw_iq`, `stft`, and `coarse_morphology` each ran exactly 1 fixed configuration. None of the four branches ran a hyperparameter search (grid/random/other) inside its own family. This is a fact about selection budget, not an evaluation of which representation is scientifically superior.

---

## 3. Engineered RF — the 10 features

Code: `feature_vector_representation()`, `backend/app/modules/ble_rffi_studio/preprocessing/representation_profiles.py:77-124`. `FEATURE_NAMES` list at line 70.

| # | Code name | Formula (as implemented) | Unit | Attribution to a specific RF impairment |
|---|---|---|---|---|
| 1 | `mean_power_dbfs` | `10*log10(mean(|x|²) + 1e-12)` | dBFS | GENERAL STATISTIC |
| 2 | `std_power_db` | `std(10*log10(|x|²+1e-12))` | dB | GENERAL STATISTIC |
| 3 | `mean_abs_amplitude` | `mean(|x|)` | linear amplitude | GENERAL STATISTIC |
| 4 | `std_abs_amplitude` | `std(|x|)` | linear amplitude | GENERAL STATISTIC |
| 5 | `spectral_centroid_hz` | `sum(f·|FFT(x)|)/sum(|FFT(x)|)`, 128-point FFT | Hz | GENERAL STATISTIC |
| 6 | `spectral_bandwidth_hz` | `sqrt(sum((f-centroid)²·|FFT(x)|)/sum(|FFT(x)|))` | Hz | GENERAL STATISTIC |
| 7 | `cfo_estimate_hz` | `estimate_cfo_hz(x)` — see §5 | Hz | **NOT IMPLEMENTED** as an isolated transmitter-CFO estimator; see §5 for exactly what it does measure |
| 8 | `papr_db` | `10*log10(max(|x|²)/(mean(|x|²)+1e-12))` | dB | GENERAL STATISTIC |
| 9 | `amplitude_kurtosis` | `scipy.stats.kurtosis(|x|)` | dimensionless | GENERAL STATISTIC |
| 10 | `amplitude_skewness` | `scipy.stats.skew(|x|)` | dimensionless | GENERAL STATISTIC |

Preprocessing applied before feature extraction for every real closed-set training run to date (PRIMARY, all RQ2 branches, RQ4 both arms): `base_preprocessing_profile_id="base-v1"` — identity, no signal-altering step. See §5 for the registry that proves this.

**DIRECT MEASUREMENT** appears for none of the 10 features with respect to PA nonlinearity, phase noise, I/Q imbalance, DC offset, gain error, spectral regrowth, or phase error — the code contains no estimator for any of those six mechanisms individually. `cfo_estimate_hz` is the only feature presented as an estimator of a specific physical quantity (apparent frequency offset), and even that is qualified (§5); the code comment on `feature_vector_representation()` (lines 81-94) makes this explicit for all 10 features in one place.

---

## 4. Frequency-offset feature — `cfo_estimate_hz`

Implementation: `estimate_cfo_hz()`, `backend/app/modules/ble_rffi_studio/preprocessing/base_preprocessing.py:77-107`.

```python
if len(window) < 2:
    return 0.0
phase = np.unwrap(np.angle(window))
mean_phase_step = np.mean(np.diff(phase))
return float(mean_phase_step * sample_rate_sps / (2 * np.pi))
```

- **Samples used:** the entire burst window (no restriction to a known-bit span).
- **Region:** whole burst — not the preamble+access-address span used by the real Eq.(6)-(7) estimator.
- **Reference correlation:** none. No `q[n]` reference waveform, no frozen index set, no least-squares fit.
- **Preprocessing applied before this feature is computed:** `base-v1` (identity) for every real closed-set training run — see registry below.
- **Possible receiver contribution:** because the window is uncompensated, the returned value is the unresolved sum of (a) GFSK modulation phase trajectory, (b) transmitter frequency offset, and (c) the B200 receiver's own local-oscillator offset. These three are not separable from a single-receiver measurement without an independent reference tone.

**Difference from `paper-eq6-7-v1`:** a *separate*, real implementation exists — `paper_compliant_cfo.py::estimate_phi0_and_fb` — that does reference-correlate against a frozen BLE preamble+access-address waveform over a fixed index set `I_b`, via joint least-squares fit of phase intercept and frequency slope. This is registered as profile `paper-eq6-7-v1` in the registry below. It was **not** used to produce any of the RQ1/RQ2/RQ4 results in this document.

**Preprocessing profile registry** (`backend/app/modules/ble_rffi_studio/preprocessing/base_preprocessing_registry.py`):

| `profile_id` | Flags | Used for reported results? |
|---|---|---|
| `base-v1` | all `False` (identity) | **Yes** — PRIMARY, all RQ2 branches, PRE_PDU arm |
| `offset-retaining-v1` | all `False` (identity) — same flags as `base-v1` | No result depends on this being distinct from `base-v1`; behaviorally identical |
| `cfo-compensated-v1` | `cfo_correction=True, phase_normalization=True` (heuristic, not Eq.6-7) | No |
| `paper-eq6-7-v1` | `paper_eq6_7_compensation=True` (real Eq.6-7 reference-correlated fit) | No |

`sensitivity_report.json.offset_retaining.profiles_behaviorally_identical = true`, `interpretive_validity = "NOT_INFORMATIVE_IDENTICAL_PREPROCESSING_PROFILES"`, `delta_vs_primary = 0.0` (exact, by construction — both profiles resolve to the same identity flags).

---

## 5. 10-second decisions — VALIDATION and TEST

Source: `06_statistics/coverage_analysis_report.json`, `window_level_evaluation.engineered_rf.by_evaluation_domain`.

Threshold: `classifier_acceptance_threshold = 0.66`, calibrated on `VALIDATION`. `minimum_eligible_bursts = 1`. `window_duration_s = 10.0`.

| Field | VALIDATION | TEST |
|---|---|---|
| total_admissible_windows | 12 | 12 |
| n_identified (IDENTIFIED) | 10 | 10 |
| n_unknown_below_threshold (UNKNOWN) | 2 | 2 |
| n_insufficient_evidence | 0 | 0 |
| operational_coverage | 0.8333333333333334 | 0.8333333333333334 |
| argmax_accuracy_ignoring_threshold | 0.8333333333333334 | 0.9166666666666666 |
| accuracy_among_identified | 0.9 | 1.0 |
| n_correct_rejected | 1 | 1 |
| n_errors_rejected | 1 | 1 |
| n_errors_accepted (incorrect-and-identified) | 1 | 0 |

`argmax_accuracy_ignoring_threshold` = **classification result** (every admissible window scored by its winning class regardless of threshold). `operational_coverage` × `accuracy_among_identified` jointly describe the **operational accepted decision** (only `IDENTIFIED` windows). These are computed from different subsets of the same 12 windows and must not be added or substituted for one another.

TEST argmax: 11/12 correct (0.9167); TEST accepted-and-correct: 10/12 (the 1 argmax error was itself rejected by the threshold, not accepted — 0 TEST windows were incorrectly accepted). VALIDATION argmax: 10/12 correct (0.8333); VALIDATION has 1 window that was an argmax error **and** accepted by the threshold (`n_errors_accepted=1`) — this is the single case across both partitions where a wrong device decision was actually presented as accepted.

Code: `operational_coverage_breakdown()`, `backend/app/modules/ble_scientific_results/coverage_analysis.py:81`. Repository path of the source artifact: [`backend/.../06_statistics/coverage_analysis_report.json`](../../backend/app/infrastructure/persistence/storage/scientific_reports/ble/paper-run-2805869e6282778ad729a26d022ec9b0/06_statistics/coverage_analysis_report.json) (already versioned, no copy made).

`abstention_reason_counts` field in the artifact: `"NOT_AVAILABLE"` (not computed at this schema version — informational, does not affect the breakdown above, which is derived directly from `CoverageRow.final_decision`).

---

## 6. Per-transmitter results — FULL_BURST and PRE_PDU

Source: `06_statistics/rq4_full_burst_vs_pre_pdu_exploratory_report.json`.

### Recall by unit

| Unit | n_examples | FULL_BURST recall | PRE_PDU recall | Δ |
|---|---|---|---|---|
| CC2541SensorTag | 187 | 0.7807486631016043 | 0.679144385026738 | +0.1016 |
| CC2650-UNIT-01 | 166 | 0.9518072289156626 | 0.8554216867469879 | +0.0964 |
| keyfobdemo 01 | 1,690 | 0.7964497041420119 | 0.6834319526627219 | +0.1130 |
| keyfobdemo 02 | 160 | 0.00625 | 0.00625 | +0.0000 |

**keyfobdemo 02, exact behavior:** 1 of 160 VALIDATION examples correctly recalled (recall = 0.00625) under **both** FULL_BURST and PRE_PDU. Under FULL_BURST, 159/160 (99.375%) are assigned to `keyfobdemo 01`, 0 to either sensor-platform unit. Under PRE_PDU, the misclassification shifts slightly: 157/160 (98.125%) are assigned to `keyfobdemo 01` and 2/160 (1.25%) to `CC2650-UNIT-01`, 0 to `CC2541SensorTag`. Recall is unchanged at 0.00625 in both regions; the *distribution* of the 159 misclassified examples is not identical between regions.

### Confusion matrices

**FULL_BURST** (rows = true class, columns = predicted):

| True \ Pred | CC2541SensorTag | CC2650-UNIT-01 | keyfobdemo 01 | keyfobdemo 02 |
|---|---|---|---|---|
| CC2541SensorTag | 146 | 0 | 15 | 26 |
| CC2650-UNIT-01 | 0 | 158 | 1 | 7 |
| keyfobdemo 01 | 185 | 13 | 1346 | 146 |
| keyfobdemo 02 | 0 | 0 | 159 | 1 |

**PRE_PDU**:

| True \ Pred | CC2541SensorTag | CC2650-UNIT-01 | keyfobdemo 01 | keyfobdemo 02 |
|---|---|---|---|---|
| CC2541SensorTag | 127 | 0 | 14 | 46 |
| CC2650-UNIT-01 | 5 | 142 | 1 | 18 |
| keyfobdemo 01 | 29 | 281 | 1155 | 225 |
| keyfobdemo 02 | 0 | 2 | 157 | 1 |

---

## 7. FULL_BURST vs PRE_PDU — full consolidation

Source: `06_statistics/rq4_full_burst_vs_pre_pdu_exploratory_report.json`, `evidence_status = "DEVELOPMENT_EXPLORATORY"`.

| | FULL_BURST | PRE_PDU |
|---|---|---|
| BA | 0.6338138990398197 | 0.556062006109112 |
| 95% CI | [0.5912219610540254, 0.6850857789866278] | [0.5026723884198467, 0.6281322273718891] |
| macro-F1 | 0.5864106215528908 | 0.49513305249417133 |
| accuracy | 0.7494325919201089 | 0.6468452110758057 |
| n_examples | 2,203 | 2,203 |
| n_sessions | 12 | 12 |
| training_run_id | `TRAIN-20260814T224700-4DEVICES-5d06e404-random_forest-a598bd` (= PRIMARY, reused, not retrained) | `TRAIN-20260814T224700-4DEVICES-5d06e404-random_forest-a598bd-region-pre-pdu` (new, independent) |
| bundle_id | `CLOSED-SET-4DEVICES-random_forest-bundle` | `TRAIN-20260814T224700-4DEVICES-5d06e404-random_forest-a598bd-region-pre-pdu-bundle` |

**Δ (FULL_BURST − PRE_PDU):** point estimate `0.07775189293070772`, 95% CI `[0.04633805792574756, 0.09975261870737617]`.

**Δ method:** `matched_stratified_bootstrap_delta_ci` — genuinely joint bootstrap: one set of resampled `session_id` cluster indices is drawn per `physical_unit_id` stratum per replicate and applied identically to both FULL_BURST and PRE_PDU (never two independent draws), because both populations are the same real evidence (identical example_ids/sessions) scored under two analytical regions. `n_resamples=2000`, `seed=12345`. `no_confirmatory_significance_test_performed = true`. Code: `matched_stratified_bootstrap_delta_ci()`, `backend/app/modules/ble_scientific_results/statistics/inference.py:352`.

**Matched-set verification** (`confirmations.matched_validation_sets_verified`): `n_examples_excluded_from_intersection=0`, `same_example_id_set=true`, `same_order=true`, `same_sessions=true`, `same_4_classes=true`.

**TRAIN-only refit / VALIDATION-only evaluation:** a fresh `TrainOnlyScaler` was fit exclusively on PRE_PDU-TRAIN; VALIDATION/TEST features were only ever transformed. Same code path PRIMARY itself used (`confirmations.scaler_fit_train_only_no_leakage`).

**Model configuration (identical to PRIMARY):** `RandomForestClassifier(random_state=42, n_estimators=100, max_depth=None)`, `hyperparameters_declared={}`, `base_preprocessing_profile_id="base-v1"`, `representation_profile_id="feature_vector-v1"`. No hyperparameter search, no model selection (`confirmations.no_tuning_no_model_selection`).

**TEST_NOT_EXECUTED:** PRE_PDU bundle `approval_status = "TEST_NOT_EXECUTED"`, gate reason `"this training_run_id has no TEST evaluation yet"` — read directly from the real `export_bundle()` gate output.

**PRIMARY untouched:** every file backing the PRIMARY training run and bundle was SHA-256-hashed before and after this control; all 18 bundle-file hashes and all 11 training-run-file hashes are identical before/after (full lists in the artifact's `confirmations.primary_byte_identical_after`).

**PRE_PDU region definition** (`backend/app/modules/ble_rffi_studio/packet_content/field_mapping.py::PRE_PDU_BITS`): 8-bit preamble + 32-bit access address = 40 bits total, ending strictly before the PDU header (excludes PDU header, AdvA, payload). Fixed access address `0x8E89BED6`.

**What changes between FULL_BURST and PRE_PDU, technically, and nothing more:** the sample window read from the same unmodified source I/Q at training/inference time is restricted to the first 40-bit-equivalent span of the burst. `source_iq_sha256` and `iq_start_sample` on every `ExampleRecord` are unchanged (`confirmations.iq_never_modified`).

Repository paths: source artifact [`backend/.../06_statistics/rq4_full_burst_vs_pre_pdu_exploratory_report.json`](../../backend/app/infrastructure/persistence/storage/scientific_reports/ble/paper-run-2805869e6282778ad729a26d022ec9b0/06_statistics/rq4_full_burst_vs_pre_pdu_exploratory_report.json) (already versioned, no copy made); PRE_PDU bundle manifest published at [`docs/ble/evidence/bundle_manifest_PRE_PDU_region-pre-pdu-bundle.json`](evidence/bundle_manifest_PRE_PDU_region-pre-pdu-bundle.json).

---

## 8. Label provenance — 9,891 examples

Source: `StudioRepository.label_provenance_report("IDENTITY-c52850a953", "20260814T224525.782975Z")`.

| `association_status` | count | fraction |
|---|---|---|
| `PHYSICAL_ISOLATION_DECLARED` | 4,338 | 0.4386 |
| `NONE` (pre-registered address binding, no independent native-BLE/SDR match) | 5,525 | 0.5586 |
| `AMBIGUOUS` | 28 | 0.0028 |
| `STRONG` | 0 | 0.0 |

`NONE + AMBIGUOUS = 5,553` — the address-bound cohort. `strong_fraction = 0.0`.

**Authoritative source:** each `ExampleRecord.association_status` field, computed by the Evidence Stage at dataset-build time from the capture's declared basis (`isolation_declared_physical_unit_id` for physical isolation, address-registry binding for the rest) and, where applicable, the native-BLE/SDR calibrated matching-and-uniqueness rule (§9). This is a per-example field, not a derived report — `label_provenance_report()` only counts it.

**Append-only correction applied this audit cycle:** the machine-readable ledger explaining *why* the 5,553 address-bound labels were admitted had gone stale (it read as if no registry binding existed for the entire cohort) relative to the label actually used for training/evaluation. Correction mechanism: `ExampleAnnotation.superseded_by_annotation_id` — a new `annotation_version` was created with the corrected `label_decision`; the old version's `superseded_by_annotation_id` now points to it. `examples.jsonl` and the I/Q evidence were never touched.

**Confirmation that no `physical_unit_id` used for training/evaluation changed:** the `physical_unit_id` field on every `ExampleRecord` and the RQ1/RQ2/RQ4 point estimates (§1, §2, §7) are identical before and after this correction — the fix only replaced a stale *explanation* field, not the *label itself*. Verified by re-running RQ1/RQ2 from the same frozen `dataset.example_ids` and confirming point estimates unchanged (RQ1 `ba_capture=0.6338138990398197` matches the pre-correction value recorded in this repository's prior session).

**Published snapshot:** `label_provenance_report()` is normally computed on demand and was not otherwise saved as a standalone file; a frozen snapshot of its exact output (plus `dataset_composition_report()` and the per-unit/per-channel breakdown used in §10, §12) is published at [`docs/ble/evidence/label_provenance_and_composition_IDENTITY-c52850a953.json`](evidence/label_provenance_and_composition_IDENTITY-c52850a953.json), computed over the same frozen `dataset.example_ids` as [`docs/ble/evidence/dataset_manifest_IDENTITY-c52850a953.json`](evidence/dataset_manifest_IDENTITY-c52850a953.json) (itself a copy of the frozen dataset manifest, byte-identical — verified this session — to `ble_rffi_studio/datasets/IDENTITY-c52850a953__20260814T224525.782975Z.json`, which is not otherwise versioned in this repository).

---

## 9. Source association

Source: `ScientificResultsRepository.get_latest_association_calibration_summary()` / `find_frozen_association_policy()`, reading the real, most recent calibration attempt on disk (`guided_validation/GVAL-20260813T121103Z-a79485/`).

| | Value |
|---|---|
| `STRONG` (frozen, currently in use) | 0 |
| Frozen association policy | `None` — no calibration attempt has ever succeeded |
| Threshold grid evaluated (ms) | `[50, 100, 150, 200, 250, 300, 400, 500]` |
| `minimum_coverage` required | 0.95 |
| Acceptance criterion | smallest grid value where coverage ≥ 95% **and** zero false-strong associations in the reinforced target-absence control |
| Coverage achieved, every threshold | 0.0 |
| False-strong count, every threshold | 0 |
| Result | `NO_THRESHOLD_SATISFIES_CRITERIA` |

**Raw calibration-event breakdown** (`association_summary.json`, 34,352 total calibration events across all captures, not just the 4 enrolled units): `NO_CANDIDATE_IN_WINDOW` 22,612 (65.8%), `MISMATCH` 9,120 (26.5%), `AMBIGUOUS` 1,897 (5.5%), `MATCHED_NON_TARGET` 723 (2.1%), `matched_target_count = 0`.

**Per-unit `strong_association_count`** (`device_summary.json`): 0 for all five registered units (`CC2541SensorTag`, `CC2650-UNIT-01`, `keyfobdemo 01`, `keyfobdemo 02`, `SHELLY-PLUG-01`) — 0 achieved a strong native-BLE/SDR association under the current calibration attempt.

**Negative control:** `has_valid_control = false` (25 candidate captures checked; 20 rejected because an enrolled device was still detected active during what should have been a target-absent control window, 5 rejected for no native-scanner record).

**Temporal mechanism:** `|t_i − t̂_j| ≤ Δt_max` gate (`backend/app/modules/ble_rffi_studio/api/studio_repository.py` association path), `Δt_max` swept over the grid above. Timestamps: `t_i` = native BLE adapter event timestamp; `t̂_j` = SDR-recovered-packet estimated timestamp.

**Distinction preserved in the data model:** `development label admission` (`PHYSICAL_ISOLATION_DECLARED` or address-binding `NONE`/`AMBIGUOUS`, §8) is a separate field and separate mechanism from `STRONG` `independent native-BLE/SDR association` (this section) — no code path promotes one into the other.

**Published snapshot:** `guided_validation/` is not versioned in this repository (RF-capture-heavy path). The four real files behind this section are published as-is at [`docs/ble/evidence/association_calibration_GVAL-20260813T121103Z-a79485/`](evidence/association_calibration_GVAL-20260813T121103Z-a79485/) (`association_policy.json`, `association_summary.json`, `target_absence_summary.json`, `device_summary.json`).

---

## 10. CH37 / CH38 / CH39

Computed fresh from `ExampleRecord.channel`/`session_id`/`capture_id` on dataset `IDENTITY-c52850a953` (CH37/38) and from `CaptureRecord.center_frequency_hz` across the entire capture store (all channels, all campaigns, for the CH39 check).

### Within `IDENTITY-c52850a953` (the dataset used for RQ1/RQ2/RQ4)

| Unit | CH37 examples | CH37 sessions | CH38 examples | CH38 sessions |
|---|---|---|---|---|
| CC2541SensorTag | 850 | 9 | 349 | 5 |
| CC2650-UNIT-01 | 913 | 13 | 574 | 7 |
| keyfobdemo 01 | 5,290 | 24 | 473 | 6 |
| keyfobdemo 02 | 1,175 | 12 | 267 | 3 |
| **Total** | **8,228** | — | **1,663** | — |

CH37 total (8,228) = TRAIN (3,561) + VALIDATION (2,203) + TEST (2,464) exactly — confirms RQ1/RQ2/RQ4 use a channel-37-only-scoped split; the 1,663 CH38 examples are entirely outside that split.

### CH39 (2,480 MHz) — any dataset, any unit, whole capture store

Across all 156 captures in the store, exactly **1** capture has `center_frequency_hz = 2,480,000,000` (CH39). It belongs to `SHELLY-PLUG-01` (not one of the 4 closed-set enrolled units), campaign `SHELLY-RF-VISIBILITY-DIAGNOSTIC`, capture `BLE-IQ-0af07d179681`. **CH39 examples for the four enrolled units: 0.**

### Confirmations

- CH38 examples within the dataset: **1,663** (exact, real, already acquired — not synthetic, not projected).
- CH39 available for the four enrolled units: **No.**
- `channel-transport analysis executed` (CH37→CH38): **No** — not run this cycle or any prior cycle (`get_scientific_completeness_report()` item `S1` = `PENDING_REAL_ACQUISITION`, missing artifact `06_statistics/channel_transport_report.json`, which does not exist on disk).

**Published snapshot:** the CH37/CH38 breakdown is inside [`docs/ble/evidence/label_provenance_and_composition_IDENTITY-c52850a953.json`](evidence/label_provenance_and_composition_IDENTITY-c52850a953.json) (`dataset_composition.channel_counts`, `per_unit_channel_breakdown`); the whole-store CH39 check is published at [`docs/ble/evidence/channel39_availability_check.json`](evidence/channel39_availability_check.json).

---

## 11. RQ3, RQ4 packet-condition, FUTURE, same-family — factual status only

All values below were read live from `ScientificResultsRepository.get_scientific_completeness_report()` and `_rq3_campaign_progress()`, and from `docs/ble/physical_device_inventory.json`. None were changed this cycle.

| Item | Status | Detail |
|---|---|---|
| RQ3 (power-cycle intervention) | `PENDING_REAL_ACQUISITION` | 0 real captures carry RQ3 metadata, of 80 valid pairs targeted (160 captures) per the frozen `rq3_sample_size` decision. `captures_with_rq3_metadata = 0` of 156 total captures. |
| RQ4 packet-condition intervention | `NOT_ELIGIBLE` | 0/7 registered physical units eligible (the 7 includes the 4 closed-set units, `SHELLY-PLUG-01`, and 2 synthetic test units). Every real unit's eligibility reason cites: `configurable_payload`/`configurable_address` = `NOT_DOCUMENTED` in the inventory, and 0 of that unit's real captures have ever declared `packet_condition=CONTROLLED_VARIANT`. |
| Protected FUTURE | `protected_future_test_status = "UNTOUCHED"` | No acquisition in the protected future period exists. |
| Confirmatory protocol freeze | `BLOCKED` | 15 required fields/gates still missing: `threshold_selection_procedure`, `operating_threshold_ms`, `rq2_primary_branch`, `rq3_primary_analysis`, `sensitivity_analyses`, `preprocessing_profile`, `rq3_reset_control_definition`, `non_inferiority_margin`, `non_inferiority_direction`, `alpha`, `confirmatory_hypotheses`, `holm_family`, `qualification_state`, `association_policy_state`, `rq2_primary_selection`. |
| Same-family (keyfobdemo 01 / keyfobdemo 02) verification | Not verified | `docs/ble/physical_device_inventory.json.same_model_groups.verified_groups = []`. Both units share registry field `device_family="TI sensortag"`, flagged in the inventory itself as "looks like an operator registration copy/paste ... must NOT be read as proof this unit is a SensorTag or shares hardware." `radio_chip`, `hardware_revision`, `firmware_hash`, `configuration_hash` are `NOT_DOCUMENTED` for both units. |

None of these five states were modified as part of this audit cycle.

---

## 12. Session/device structure

Computed fresh from the 9,891-example `IDENTITY-c52850a953` dataset (`ExampleRecord.session_id` / `.physical_unit_id`).

| Unit | Sessions |
|---|---|
| CC2541SensorTag | 14 |
| CC2650-UNIT-01 | 20 |
| keyfobdemo 01 | 30 |
| keyfobdemo 02 | 15 |
| **Total distinct sessions** | **79** |

- **Sessions containing more than one enrolled physical unit: 0** (verified by grouping all 9,891 examples by `session_id` and checking `len(set(physical_unit_id)) > 1` per group — zero such groups; sum of per-unit session counts = 79 = total distinct sessions, confirming the per-unit session sets are fully disjoint).
- **Devices per session:** exactly 1 enrolled unit, for all 79 sessions.
- **capture/session relationship:** in this dataset, `capture_id` and `session_id` are in 1:1 correspondence for every example (each capture belongs to exactly one session and vice versa) — 79 sessions, 79 unique `capture_id` values contributing examples.
- **window/capture relationship:** decision windows are built as fixed 10-second, non-overlapping partitions of each capture's admitted burst sequence (§ RQ1 window cross-reference: 34 TRAIN + 12 VALIDATION + 12 TEST = 58 windows total, reconstructed from the 34+12+12 = 58 captures used by the channel-37-scoped split).

**Published snapshot:** `docs/ble/evidence/label_provenance_and_composition_IDENTITY-c52850a953.json`, field `session_device_structure`.

---

## 13. Dataset composition

Computed fresh via `StudioRepository.dataset_training_preview(dataset_id="IDENTITY-c52850a953", dataset_version="20260814T224525.782975Z", scientific_task="MULTI_DEVICE_CLASSIFICATION")`.

| Split | Examples | Captures | CC2541SensorTag (ex / sess) | CC2650-UNIT-01 (ex / sess) | keyfobdemo 01 (ex / sess) | keyfobdemo 02 (ex / sess) |
|---|---|---|---|---|---|---|
| TRAIN | 3,561 | 34 | 447 / 5 | 522 / 7 | 1,743 / 14 | 849 / 8 |
| VALIDATION | 2,203 | 12 | 187 / 2 | 166 / 3 | 1,690 / 5 | 160 / 2 |
| TEST | 2,464 | 12 | 216 / 2 | 225 / 3 | 1,857 / 5 | 166 / 2 |

Windows per split (10-s decision-window level, from `06_statistics/coverage_analysis_report.json` / RQ1 cross-reference): TRAIN 34, VALIDATION 12, TEST 12 — one window per capture in this corpus (each capture is exactly 10 s).

**Data provenance types** (`DataOrigin` is a closed set: `Literal["REAL_B200", "SYNTHETIC_TEST_ONLY"]`, `backend/app/modules/ble_rffi_studio/contracts/capture.py:14`):

| `data_origin` | Captures in `IDENTITY-c52850a953` |
|---|---|
| `REAL_B200` | 79 (all of them) |
| `SYNTHETIC_TEST_ONLY` | 0 |

There is no `fixture`/`replay` provenance category in this schema distinct from these two; replay status (`replay_status` field on `CaptureRecord`) records whether a capture has been fed through the offline-replay/burst-detection pipeline, not a different data-origin class — all 79 captures behind RQ1/RQ2/RQ4 are `data_origin=REAL_B200` with `replay_status` populated by the real detection pipeline, never `SYNTHETIC_TEST_ONLY`.

---

## 14. Traceability — one real VALIDATION prediction, one real TEST prediction

Both example_ids are the first entries of `predictions.json` for the PRIMARY training run (`TRAIN-20260814T224700-4DEVICES-5d06e404-random_forest-a598bd`).

### VALIDATION example

```
prediction:      example_id=ex-52d7881105e3ff97aa4cc328d2fdd1e8
                  predicted_label=CC2541SensorTag, true_label=CC2541SensorTag
                  probabilities={CC2541SensorTag:0.65, CC2650-UNIT-01:0.08, keyfobdemo 01:0.23, keyfobdemo 02:0.04}
→ model bundle:   CLOSED-SET-4DEVICES-random_forest-bundle (bundle_sha256=36c9ef76a859b9fecacf8da8eeee78dbe6f7b768ec924b6c5066a5d874eab9be)
→ preprocessing:  base_preprocessing_profile_id=base-v1, representation_profile_id=feature_vector-v1
→ split:          IDENTITY-c52850a953__20260814T224525.782975Z__MULTI_DEVICE_CLASSIFICATION, split=VALIDATION
→ example:        capture_id=BLE-IQ-b19a317bff1a, session_id=BLE-HYBRID-20260730T132022Z-faeed5,
                  channel=37, center_frequency_hz=2402000000, association_status=NONE
→ sample interval: iq_start_sample=169464, iq_end_sample=170072 (608 samples @ 4 MS/s)
→ source I/Q:     source_iq_sha256=f0f3fcecb9dfc1fac50b5d78f23eb9926f5e7c504190720e86b0dcfe0cb95ccc
→ SHA-256 (recomputed from the file on disk, this session): f0f3fcecb9dfc1fac50b5d78f23eb9926f5e7c504190720e86b0dcfe0cb95ccc  ✓ MATCH
```

### TEST example

```
prediction:      example_id=ex-533eb8d402e3ad66df003e5698b73c1e
                  predicted_label=CC2541SensorTag, true_label=CC2541SensorTag
                  probabilities={CC2541SensorTag:0.67, CC2650-UNIT-01:0.02, keyfobdemo 01:0.27, keyfobdemo 02:0.04}
→ model bundle:   CLOSED-SET-4DEVICES-random_forest-bundle (same bundle as above; TEST was evaluated once, approval_status=EVALUATED)
→ preprocessing:  base_preprocessing_profile_id=base-v1, representation_profile_id=feature_vector-v1
→ split:          IDENTITY-c52850a953__20260814T224525.782975Z__MULTI_DEVICE_CLASSIFICATION, split=TEST
→ example:        capture_id=BLE-IQ-8892eb606635, session_id=BLE-HYBRID-20260730T132145Z-d6ed19,
                  channel=37, center_frequency_hz=2402000000, association_status=NONE
→ sample interval: iq_start_sample=401432, iq_end_sample=402040 (608 samples @ 4 MS/s)
→ source I/Q:     source_iq_sha256=34e5c7b7055901b802181b70c8e4d4d75336d30d8e399237165a32ccfb867cc1
→ SHA-256 (recomputed from the file on disk, this session): 34e5c7b7055901b802181b70c8e4d4d75336d30d8e399237165a32ccfb867cc1  ✓ MATCH
```

Both `capture.iq_sha256` fields match their `example.source_iq_sha256` fields, and both were independently rehashed from the actual `.sigmf-data` file on disk this session (not read from any manifest) — full-chain byte integrity confirmed end to end for both examples.

**Weak point of provenance, stated plainly:** both traced examples have `association_status=NONE` — they are *development label admissions* (pre-registered address binding), not independently corroborated (`STRONG`) source associations (§8, §9). The file-integrity chain above is fully verified; the physical-source-identity claim behind the label itself rests on the controlled-acquisition protocol, not on an independent native-BLE/SDR match, for both of these two examples specifically.

---

## 15. Canonical artifact inventory

Every SHA-256 below is computed on the exact file published at the listed repository path, not on a copy regenerated afterward. Files marked "already versioned" were not duplicated — the listed path is their one real, stable location in this repository (per the instruction to link rather than copy when a stable path already exists). Files marked "published copy" live under an otherwise-gitignored storage path (`ble_rffi_studio/`, `scientific_reports/ble/guided_validation/`) and were copied byte-for-byte into `docs/ble/evidence/` so they are reachable in git; the copy's hash was verified identical to the source file's hash before publication.

| artifact | repository path | purpose | SHA-256 | status |
|---|---|---|---|---|
| RQ1 report | [`backend/.../06_statistics/rq1_acquisition_dependence_report.json`](../../backend/app/infrastructure/persistence/storage/scientific_reports/ble/paper-run-2805869e6282778ad729a26d022ec9b0/06_statistics/rq1_acquisition_dependence_report.json) | RQ1 acquisition-dependence result + CI | `22b540da50bb09c746a1ded8869ed425dc09e3c44ea38d21a4c729d2b2849828` | already versioned |
| RQ2 report | [`backend/.../06_statistics/rq2_representation_comparison_report.json`](../../backend/app/infrastructure/persistence/storage/scientific_reports/ble/paper-run-2805869e6282778ad729a26d022ec9b0/06_statistics/rq2_representation_comparison_report.json) | RQ2 four-branch comparison | `1cb5aadfd4064128eaa05902bf7c686e2f42d514745a2dae970e3a77134f6596` | already versioned |
| Coverage report | [`backend/.../06_statistics/coverage_analysis_report.json`](../../backend/app/infrastructure/persistence/storage/scientific_reports/ble/paper-run-2805869e6282778ad729a26d022ec9b0/06_statistics/coverage_analysis_report.json) | 10-s decision-window coverage/abstention breakdown, VALIDATION+TEST | `8c896510900c0c69b4ec7ab023726fefde41652bf668c56e4e733a8f548ba780` | already versioned |
| Sensitivity report | [`backend/.../06_statistics/sensitivity_report.json`](../../backend/app/infrastructure/persistence/storage/scientific_reports/ble/paper-run-2805869e6282778ad729a26d022ec9b0/06_statistics/sensitivity_report.json) | class-exclusion sensitivity, offset-retaining sensitivity, seed variability | `1e64970534df211533b8181539d41395854f7f806af28881d5653d69fd3466bf` | already versioned |
| RQ4 FULL_BURST vs PRE_PDU report | [`backend/.../06_statistics/rq4_full_burst_vs_pre_pdu_exploratory_report.json`](../../backend/app/infrastructure/persistence/storage/scientific_reports/ble/paper-run-2805869e6282778ad729a26d022ec9b0/06_statistics/rq4_full_burst_vs_pre_pdu_exploratory_report.json) | FULL_BURST vs PRE_PDU exploratory contrast | `7eeffd3f240cbc7ecc8e3bce2385a8a492c41ce7d6cdc56f05a51fd250efcbf8` | already versioned |
| Paper-ready values export | [`backend/.../06_statistics/paper_ready_values_export.json`](../../backend/app/infrastructure/persistence/storage/scientific_reports/ble/paper-run-2805869e6282778ad729a26d022ec9b0/06_statistics/paper_ready_values_export.json) | single aggregated source-of-truth over the five reports above | `ceae41b66d51640f94bc8d82a1c63295e68050adb610eaf4695ab6d43d389277` | already versioned |
| Dataset manifest | [`docs/ble/evidence/dataset_manifest_IDENTITY-c52850a953.json`](evidence/dataset_manifest_IDENTITY-c52850a953.json) | frozen dataset manifest, 9,891 `example_ids`, `IDENTITY-c52850a953` | `d38c6db89c4e194c322de7aa31d4d2228f6c3071aeb16e9559d8a7b7bb1cc283` (byte-identical to source; self-hash field `dataset_manifest_sha256=b989398147f7cd2ff858a0a4792d9e49ef75a1584317c062978165d6913c9658` recomputed via `content_hash()` this session, MATCH) | published copy |
| Split manifest | [`docs/ble/evidence/split_manifest_IDENTITY-c52850a953__MULTI_DEVICE_CLASSIFICATION.json`](evidence/split_manifest_IDENTITY-c52850a953__MULTI_DEVICE_CLASSIFICATION.json) | frozen TRAIN/VALIDATION/TEST assignment | `4dd7bda4ea59136e34cb1fc499cf4cc5e945385ca669ccee1342472125eb2443` (byte-identical to source; self-hash field `split_manifest_sha256=a9e11cba02ecf4db6dd1ca60b46bb7bf52cd73761e7dd64894c4f45b7c47495d` recomputed via `content_hash()` this session, MATCH) | published copy |
| PRIMARY bundle manifest | [`docs/ble/evidence/bundle_manifest_PRIMARY_CLOSED-SET-4DEVICES-random_forest-bundle.json`](evidence/bundle_manifest_PRIMARY_CLOSED-SET-4DEVICES-random_forest-bundle.json) | PRIMARY exported model bundle manifest | `ea857cafdb4ab38c643d7de1d4c2c881ed1dab0f95a1e74739500d64886bfa9c` (byte-identical to source; internal `bundle_sha256=36c9ef76a859b9fecacf8da8eeee78dbe6f7b768ec924b6c5066a5d874eab9be`, `approval_status=EVALUATED`) | published copy |
| PRE_PDU bundle manifest | [`docs/ble/evidence/bundle_manifest_PRE_PDU_region-pre-pdu-bundle.json`](evidence/bundle_manifest_PRE_PDU_region-pre-pdu-bundle.json) | PRE_PDU exported model bundle manifest | `be02b5604bd4982594b46cfbae1d8169bb27b5eb7e0c3e59f5b1073c403965e2` (`approval_status=TEST_NOT_EXECUTED`) | published copy |
| Association policy | [`docs/ble/evidence/association_calibration_GVAL-20260813T121103Z-a79485/association_policy.json`](evidence/association_calibration_GVAL-20260813T121103Z-a79485/association_policy.json) | latest real source-association calibration attempt | `0713b91cfdce14c6b8230089c856c87c5bb97c6e0bb06886f1201807375fff9f` | published copy |
| Association summary | [`docs/ble/evidence/association_calibration_GVAL-20260813T121103Z-a79485/association_summary.json`](evidence/association_calibration_GVAL-20260813T121103Z-a79485/association_summary.json) | raw calibration-event breakdown | `1cdc8f1f7c3c385b25761c55ded1205fd6a7c53e365551f378cd72d13eefb40e` | published copy |
| Target-absence summary | [`docs/ble/evidence/association_calibration_GVAL-20260813T121103Z-a79485/target_absence_summary.json`](evidence/association_calibration_GVAL-20260813T121103Z-a79485/target_absence_summary.json) | negative-control check | `d3cc7b547a3b382ba5245e1f2f59dd29f82476b0ea96e3f87ef4dd2558b18c45` | published copy |
| Device summary | [`docs/ble/evidence/association_calibration_GVAL-20260813T121103Z-a79485/device_summary.json`](evidence/association_calibration_GVAL-20260813T121103Z-a79485/device_summary.json) | per-unit `strong_association_count` etc. | `47f0d51bf18722003f4ad7b4b09c5a60428e4447784fa78e3aab048d9e686436` | published copy |
| Label provenance + dataset composition snapshot | [`docs/ble/evidence/label_provenance_and_composition_IDENTITY-c52850a953.json`](evidence/label_provenance_and_composition_IDENTITY-c52850a953.json) | §8/§10/§12 numbers — `label_provenance_report()`, `dataset_composition_report()`, per-unit/channel breakdown, session/device structure | `afbc8fec260cd3efdb2801dcb04f60968060bbd5a58fa85c84cff71e56e8d76c` | newly published snapshot, generated this cycle from the frozen dataset (no science change — see §16) |
| CH39 availability check | [`docs/ble/evidence/channel39_availability_check.json`](evidence/channel39_availability_check.json) | whole-store CH39 (2,480 MHz) capture check | `660c5ad11b9a7bc76fc3fdfcd09f9699771b203419c6d82d627e116039211752` | newly published snapshot, generated this cycle |
| Physical device inventory | [`docs/ble/physical_device_inventory.json`](physical_device_inventory.json) | registry-sourced physical unit facts, same-family verification state | `20c43397c1430cc98224944d89e9e613cbade71066d1a70626b7454aeecd521d` | already versioned |
| This document | [`docs/ble/TECHNICAL_EVIDENCE_AUDIT.md`](TECHNICAL_EVIDENCE_AUDIT.md) | narrative report | — | this file |
| Code/test diff for this phase | [`docs/ble/TECHNICAL_EVIDENCE_AUDIT.diff`](TECHNICAL_EVIDENCE_AUDIT.diff) | §16 code-change evidence | — | this file |

---

## 16. Changes made during this last phase

### CODE CHANGES

- `backend/app/modules/ble_scientific_results/statistics/inference.py`: added `stratified_hierarchical_cluster_bootstrap()`, `independent_domain_bootstrap_delta_ci()`, `matched_stratified_bootstrap_delta_ci()`.
- `backend/app/modules/ble_scientific_results/coverage_analysis.py`: added `final_decision` field to `CoverageRow`; added `operational_coverage_breakdown()`.
- `backend/app/modules/ble_rffi_studio/evaluation/evaluator.py`: added `_session_clustered_label_pairs_by_true_class()`, `bootstrap_balanced_accuracy_ci_stratified_by_class()`, `bootstrap_balanced_accuracy_delta_ci_stratified_by_class()`, `bootstrap_balanced_accuracy_delta_ci_matched_by_class()`.
- `backend/app/modules/ble_rffi_studio/api/studio_repository.py`: added wrapper methods for the two stratified-bootstrap Evaluator methods above.
- `backend/app/modules/ble_scientific_results/rq1_runner.py`: switched RQ1 persistence to the stratified bootstrap methods.
- `backend/app/modules/ble_rffi_studio/preprocessing/base_preprocessing.py`: `estimate_cfo_hz()` docstring corrected to describe it as a mean phase-rate/frequency-offset estimator, not validated CFO (no behavior change).
- `backend/app/modules/ble_rffi_studio/preprocessing/representation_profiles.py`: module/function docstrings corrected for the same reason (no behavior change; `FEATURE_NAMES` unchanged).
- `backend/app/modules/ble_scientific_results/api/scientific_results_repository.py`: `run_sensitivity_analysis()` extended with `profiles_behaviorally_identical`/`interpretive_validity`/`interpretive_note`; `run_coverage_analysis()` wired to `operational_coverage_breakdown()`.
- `backend/app/modules/ble_scientific_results/sensitivity_analysis.py`, `statistics/sensitivity.py`, `statistics/confirmatory_analysis_runner.py`, `statistics/__init__.py`, `api/scientific_results_job_manager.py`, `api/scientific_results_routes.py`, `engineering_reports.py`, `paper_export.py`: mechanical rename LODO → `enrolled_population_class_exclusion_sensitivity` (naming only, same computation).
- `docs/ble/generate_evidence_figures.py`: extended (see diff for exact scope).
- Test files (`test_bootstrap_accuracy_ci.py`, `test_coverage_analysis.py`, `test_statistics_inference.py`, `test_sensitivity_analysis.py`, `test_sensitivity_analysis_repository.py`, `test_statistics_sensitivity.py`, `test_confirmatory_analysis_runner.py`): extended with new tests for all of the above.

Full diff stat and unified diff: `docs/ble/TECHNICAL_EVIDENCE_AUDIT.diff` (986 insertions, 88 deletions across 24 non-generated code/test files; figure/CSV/provenance regenerations listed separately below, not in that diff).

### ARTIFACT CHANGES

- `rq1_acquisition_dependence_report.json`: regenerated — point estimates unchanged, `uncertainty_ci` block replaced with the new stratified-bootstrap intervals (§1).
- `coverage_analysis_report.json`: regenerated — added `operational_breakdown` to both VALIDATION and TEST (§5); no change to `balanced_accuracy`/confusion matrices.
- `sensitivity_report.json`: regenerated — `enrolled_population_class_exclusion_sensitivity` renamed key with method string; `offset_retaining` gained `profiles_behaviorally_identical`/`interpretive_validity`/`interpretive_note`; no row values changed.
- `rq4_full_burst_vs_pre_pdu_exploratory_report.json`: newly created this cycle — real PRE_PDU training run executed, real matched bootstrap computed (§7).
- `paper_ready_values_export.json`: newly created this cycle — pure aggregation of the five artifacts above, no independent computation.
- `paper_exports/*` (figures, CSVs, provenance sidecars): regenerated to reflect the updated `rq1_acquisition_dependence_report.json`/`coverage_analysis_report.json`/`sensitivity_report.json` inputs — same generator (`generate_evidence_figures.py` → `paper_export.py`), no plotting-logic change beyond what the diff shows.

**Publication-phase additions (this commit, no science involved):** `docs/ble/evidence/` created — byte-for-byte copies of the dataset manifest, split manifest, and both bundle manifests (all otherwise gitignored under `ble_rffi_studio/`); byte-for-byte copies of the four real `guided_validation/GVAL-20260813T121103Z-a79485/` calibration files (otherwise gitignored under `scientific_reports/ble/guided_validation/`); two newly generated read-only snapshots (`label_provenance_and_composition_IDENTITY-c52850a953.json`, `channel39_availability_check.json`) that persist the output of functions normally computed on demand (`label_provenance_report()`, `dataset_composition_report()`, a channel-grouping query), over the same already-frozen dataset — no new computation, no retraining, no artifact regeneration. No existing file was renamed or moved; every copy sits at a new path alongside the original.

### DATA CHANGES

- `ExampleAnnotation` provenance ledger for the 5,553-example address-binding cohort: append-only correction via `superseded_by_annotation_id` (§8). `examples.jsonl` and all I/Q evidence files were not modified. No `physical_unit_id` used for training/evaluation changed.

### UNCHANGED (byte-identical, verified this session)

- `IDENTITY-c52850a953__20260814T224525.782975Z.json` dataset manifest — `content_hash()` recomputed and matches the stored `dataset_manifest_sha256` field exactly (§15).
- `IDENTITY-c52850a953__20260814T224525.782975Z__MULTI_DEVICE_CLASSIFICATION.json` split manifest — `content_hash()` recomputed and matches the stored `split_manifest_sha256` field exactly (§15).
- PRIMARY training run and bundle (`TRAIN-...-a598bd` / `CLOSED-SET-4DEVICES-random_forest-bundle`) — all 18 bundle files and all 11 training-run files SHA-256-identical before and after the PRE_PDU control (§7, confirmed inside `rq4_full_burst_vs_pre_pdu_exploratory_report.json`).
- Both traced source I/Q `.sigmf-data` files (§14) — rehashed from disk this session, identical to their recorded `source_iq_sha256`.
- RQ1/RQ2/RQ4 point estimates (BA, macro-F1, confusion matrices) — unchanged by the label-provenance ledger correction (§8) and by the bootstrap-method fix (only the CI changed, not the point estimate).
- `FEATURE_NAMES` (the 10 engineered-feature field identifiers) — unchanged for artifact compatibility, only their docstrings were corrected.

---

## 17. Test suite

`./.venv-validation/Scripts/python.exe -m pytest app/tests/unit -q`

**Full suite:** 1,005 passed, 3 failed, 36 skipped (157.25s).

**Failures (all pre-existing, unrelated to any change in §16 — none of these three test modules were touched this phase):**
- `app/tests/unit/test_ble_real_iq_capture.py::test_hash_mismatch_fails_job`
- `app/tests/unit/test_rf_intelligence.py::test_rf_intelligence_detects_fm_broadcast_candidate`
- `app/tests/unit/test_ti_cc2650_sensortag.py::test_ir_temperature_object_and_ambient_are_distinct_measurements`

**Scoped to the modules actually touched this phase** (`app/tests/unit/ble_rffi_studio`, `app/tests/unit/ble_scientific_results`):

`./.venv-validation/Scripts/python.exe -m pytest app/tests/unit/ble_rffi_studio app/tests/unit/ble_scientific_results -q`

**895 passed, 0 failed, 36 skipped (137.88s).**

---

## 18. Explicit scope note

Nothing new was implemented for this document. No unfavorable result was adjusted. No tuning was performed. PRIMARY was not retrained (verified byte-identical, §16). TEST was not opened beyond reading its already-persisted `evaluation_report.json`/`predictions.json`. No further experiments (CH37→CH38 transport, RQ3, RQ4 packet-condition, FUTURE) were executed. This is a snapshot of what exists on disk and in code as of the timestamps recorded in §0 and each artifact's own `generated_at` field.
