# Paper evidence map (DEVELOPMENT phase)

Links every quantitative claim used in the current manuscript to its
canonical artifact, the exact real function that produced it, and the
figure/table the paper draws from. **This file contains no new results** --
only pointers to evidence that already exists on disk / in the dashboard.
When a number in the paper changes, the fix always happens at the source
artifact (regenerated via the commands in §"How to regenerate"), never by
hand-editing a figure or this table.

Companion documents: `SCIENTIFIC_STATUS.md` §18 (dashboard tab ↔ artifact
map, broader than just this paper's current claims) and `README.md`
(experimental-status summary).

## Run identity (this DEVELOPMENT phase)

| Field | Value |
|---|---|
| `paper_run_id` | `paper-run-2805869e6282778ad729a26d022ec9b0` |
| `dataset_id` / `dataset_version` | `IDENTITY-c52850a953` / `20260814T224525.782975Z` |
| `scientific_task` | `MULTI_DEVICE_CLASSIFICATION` |
| `model_bundle_id` | `CLOSED-SET-4DEVICES-random_forest-bundle` |
| `model_bundle_sha256` | `36c9ef76a859b9fecacf8da8eeee78dbe6f7b768ec924b6c5066a5d874eab9be` |
| `confirmatory_split_manifest_sha256` | `a9e11cba02ecf4db6dd1ca60b46bb7bf52cd73761e7dd64894c4f45b7c47495d` |

The `CONFIRMATORY` string above is the split manifest's internal
`split_purpose` field name (`contracts/split.py`) -- it names the manifest's
role as the platform's one reference partition, not a claim that any result
built on it is scientifically confirmatory in the paper. Every row below is
`DEVELOPMENT` unless stated otherwise.

## Evidence table

| Paper item | Scientific status | Evaluation unit | Artifact | Generator | Figure/table | Dataset ID | Split manifest SHA | Model bundle SHA |
|---|---|---|---|---|---|---|---|---|
| RQ1 -- capture-dependent vs. capture-disjoint (BA, 95% CI, delta) | DEVELOPMENT | `EXAMPLE_RECORD` | `06_statistics/rq1_acquisition_dependence_report.json` | `rq1_runner.run_rq1_acquisition_dependence()` (persists) → `paper_export.py::generate_paper_exports()` (renders, via `figures/paper_figures.py::bar_with_ci_figure`) | `paper_exports/figures/rq1_acquisition_dependence.{pdf,svg,png}`, copied verbatim into `readme_img/evidence_rq1_domains.png` (`generate_evidence_figures.py`'s `CONSOLIDATED_FIGURES` -- never re-rendered independently, see §Figure pipeline below) | IDENTITY-c52850a953 | a9e11cba...c47495d | 36c9ef76...4eab9be |
| RQ1 -- held-out TEST (BA, not protected FUTURE) | DEVELOPMENT | `EXAMPLE_RECORD` | `ble_rffi_studio/training_runs/<id>/evaluation_report.json` (`TEST`) | `StudioRepository.evaluate_training_run(include_test=True)`, surfaced via `get_evidence_dashboard_summary()["closed_set"]["primary_test"]` | same figure, third bar ("Held-out TEST (not protected FUTURE)") + `evidence_confusion_test.png` | IDENTITY-c52850a953 | a9e11cba...c47495d | 36c9ef76...4eab9be |
| RQ1 -- protected FUTURE | `NOT_YET_AVAILABLE` (not executed) | `EXAMPLE_RECORD` (once run) | `rq1_acquisition_dependence_report.json` (`ba_future=null`) | not executed | not rendered (figure omits this bar while `ba_future is None`; `--verify`'s `TEST_LABELED_AS_FUTURE` check fails the build if this is ever violated) | — | — | — |
| RQ2 -- four representations (BA, macro-F1, per-class recall) | DEVELOPMENT | `EXAMPLE_RECORD` | `06_statistics/rq2_representation_comparison_report.json` | `rq2_benchmark.run_rq2_benchmark()` (persists) → `paper_export.py::generate_paper_exports()` (renders) | `paper_exports/figures/rq2_representation_comparison.{pdf,svg,png}`, copied into `readme_img/evidence_rq2_branches.png` + `paper_exports/rq2_results.csv` | IDENTITY-c52850a953 | a9e11cba...c47495d | 36c9ef76...4eab9be |
| RQ2 -- computational cost (latency, model size) | DEVELOPMENT | `EXAMPLE_RECORD` | same `rq2_representation_comparison_report.json` (`inference_latency_ms`, `serialized_model_size_bytes` per branch) | `training_service.py::_measure_latency_ms`, persisted by the same RQ2 runner | `Rq2Tab.tsx` (dashboard, live) + `readme_img/evidence_computational_cost.png` (labeled DEVELOPMENT) | IDENTITY-c52850a953 | a9e11cba...c47495d | 36c9ef76...4eab9be |
| Decision-window scoping fix (TRAIN 34 / VALIDATION 12 / TEST 12, 4/4 TX) | DEVELOPMENT | `DECISION_WINDOW` (10 s) | `06_statistics/coverage_analysis_report.json` (`domain_resolution_diagnostic`) | `ScientificResultsRepository.run_coverage_analysis(evaluate_window_level=True)` | `CoverageTab.tsx` (dashboard) + `paper_exports/development_decision_window_summary.csv` | IDENTITY-c52850a953 | a9e11cba...c47495d | 36c9ef76...4eab9be |
| VALIDATION/TEST -- window-level BA + argmax accuracy (0.750/0.833, 0.875/0.917) **and** operational coverage (0.833 in both, not 1.000 -- see `operational_breakdown`) | DEVELOPMENT | `DECISION_WINDOW` (10 s) | same `coverage_analysis_report.json` (`window_level_evaluation.engineered_rf.by_evaluation_domain.*.operational_breakdown`, added by `operational_coverage_breakdown()`) | same `run_coverage_analysis` | `paper_exports/development_decision_window_summary.csv` (`paper_export.py::development_decision_window_summary_rows`) | IDENTITY-c52850a953 | a9e11cba...c47495d | 36c9ef76...4eab9be |
| TEST -- window-level confusion matrix | DEVELOPMENT | `DECISION_WINDOW` (10 s) | same `coverage_analysis_report.json` (`window_level_evaluation.engineered_rf.by_evaluation_domain.TEST.confusion_matrix`) | same `run_coverage_analysis` | `paper_exports/development_test_window_confusion_matrix.csv` (`paper_export.py::confusion_matrix_rows`) | IDENTITY-c52850a953 | a9e11cba...c47495d | 36c9ef76...4eab9be |
| Window-level risk-coverage (12 windows/domain) | DEVELOPMENT / EXPLORATORY (sample too small for a stable curve) | `DECISION_WINDOW` (10 s) | same `coverage_analysis_report.json` (`window_level_evaluation.engineered_rf.by_evaluation_domain.*.risk_coverage`) | same `run_coverage_analysis` | `CoverageTab.tsx` (chart+table) + `paper_exports/closed_set_risk_coverage_window_level.csv` | IDENTITY-c52850a953 | a9e11cba...c47495d | 36c9ef76...4eab9be |
| Risk-coverage, EXAMPLE_RECORD-level (TEST, ~2200 examples) | DEVELOPMENT / EXPLORATORY | `EXAMPLE_RECORD` | `ble_rffi_studio/training_runs/<id>/evaluation_report.json` (`TEST.risk_coverage`) | `Evaluator._risk_coverage()` | `readme_img/evidence_risk_coverage.png` (labeled DEVELOPMENT / EXPLORATORY) | IDENTITY-c52850a953 | a9e11cba...c47495d | 36c9ef76...4eab9be |
| Enrolled-population class-exclusion metric sensitivity (renamed 2026-08-22 -- **not** leave-one-device-out; the model is never retrained without the excluded class, only the aggregate metric is recomputed post-hoc from PRIMARY's own already-scored predictions) | SENSITIVITY | `EXAMPLE_RECORD` | `06_statistics/sensitivity_report.json` (`enrolled_population_class_exclusion_sensitivity`) | `ScientificResultsRepository.run_sensitivity_analysis()` -> `statistics/sensitivity.py::enrolled_population_class_exclusion_sensitivity()` | `SensitivityTab.tsx` (dashboard, real table+chart) | IDENTITY-c52850a953 | a9e11cba...c47495d | 36c9ef76...4eab9be |
| Offset-retaining preprocessing sensitivity (**not currently informative** -- `offset-retaining-v1` resolves to the same identity flags as PRIMARY's own `base-v1`, so `delta_vs_primary=0.0` is trivial by construction, not a validated CFO-compensation finding; see `PREPROCESSING.md`) | SENSITIVITY | `EXAMPLE_RECORD` | same `sensitivity_report.json` (`offset_retaining`) | same `run_sensitivity_analysis()` -> `StudioRepository.train_offset_retaining_sensitivity()` | `SensitivityTab.tsx` | IDENTITY-c52850a953 | a9e11cba...c47495d | 36c9ef76...4eab9be |
| RQ4 exploratory analytical-region control (FULL_BURST vs PRE_PDU) -- `DEVELOPMENT_EXPLORATORY`, post-hoc, not the still-not-executed RQ4 packet-condition intervention | DEVELOPMENT_EXPLORATORY | `EXAMPLE_RECORD` | `06_statistics/rq4_full_burst_vs_pre_pdu_exploratory_report.json` | `ScientificResultsRepository.get_rq4_full_burst_vs_pre_pdu_exploratory_report()` (real re-fit persisted separately) -> `paper_export.py::generate_paper_exports()` (renders, via `figures/paper_figures.py::bar_with_ci_figure`) | `paper_exports/figures/rq4_full_burst_vs_pre_pdu.{pdf,svg,png}`, copied into `readme_img/evidence_rq4_regions.png` + `paper_exports/rq4_full_burst_vs_pre_pdu_results.csv` | IDENTITY-c52850a953 | a9e11cba...c47495d | PRIMARY: 36c9ef76...4eab9be / PRE_PDU: be02b560...965e2 (independent bundle, `TEST_NOT_EXECUTED`) |
| RQ4 exploratory -- per-unit recall, FULL_BURST vs PRE_PDU (`keyfobdemo 02` unchanged at 0.006 under both regions) | DEVELOPMENT_EXPLORATORY | `EXAMPLE_RECORD` | same `rq4_full_burst_vs_pre_pdu_exploratory_report.json` (`full_burst.recall_per_class`, `pre_pdu.recall_per_class`) | same generator, via `figures/paper_figures.py::grouped_bar_figure` | `paper_exports/figures/rq4_per_unit_recall.{pdf,svg,png}`, copied into `readme_img/evidence_rq4_per_unit_recall.png` | IDENTITY-c52850a953 | a9e11cba...c47495d | same as above |
| Seed variability (seeds 137, 2024) | SENSITIVITY | `EXAMPLE_RECORD` | `rq2_representation_comparison_report.json` (`branches[PRIMARY].seed_variability`), reused verbatim into `sensitivity_report.json` | RQ2 runner (seed re-trains) | `readme_img/evidence_seed_variability.png` (labeled DEVELOPMENT / SENSITIVITY) + `SensitivityTab.tsx` | IDENTITY-c52850a953 | a9e11cba...c47495d | 36c9ef76...4eab9be |
| Association calibration -- fail-closed result | DEVELOPMENT (negative result, part of the forensic interpretation) | n/a (association event, not a classifier prediction) | `association_calibration_summary` (computed on read from `guided_validation/*/association_policy.json`) | `ScientificResultsRepository.get_latest_association_calibration_summary()` | `AssociationTab.tsx` (dashboard, live) | n/a | n/a | n/a |
| `classifier_acceptance_threshold` vs. `association_time_threshold_ms` | DEVELOPMENT | n/a | `coverage_analysis_report.json` (`window_level_evaluation.engineered_rf`) -- `classifier_acceptance_threshold=0.66` (calibrated on VALIDATION), `association_time_threshold_ms=null` (no calibrated time-based association threshold exists) | `run_coverage_analysis` | `CoverageTab.tsx` (both badges shown side by side, never conflated) | IDENTITY-c52850a953 | a9e11cba...c47495d | 36c9ef76...4eab9be |

## Figure pipeline (2026-08-18)

`artifact -> figure generator -> PNG/PDF` is the only path for every
scientific figure. There is exactly one renderer per figure
(`figures/paper_figures.py`, called from `paper_export.py`) -- readme_img/'s
copies are byte-identical copies of the PDF/SVG/PNG that renderer already
wrote, never a second independently-coded plot. `paper_exports/
figure_manifest.json` records, per figure: `figure_path`, `source_artifact`,
`source_artifact_sha256` (computed from the real bytes at generation time),
`paper_run_id`, `evaluation_unit`, `evidence_status`, `generator_commit`,
`generated_at`.

```
backend/.venv-validation/Scripts/python.exe docs/ble/generate_evidence_figures.py --paper-run <id> --verify
```

Read-only; fails (non-zero exit) if: a figure's `evaluation_unit`/
`evidence_status` disagrees with its real source artifact; a required CI is
missing; TEST is ever labeled `PROTECTED_FUTURE`; the source artifact
doesn't belong to `--paper-run <id>`; the artifact's real current bytes
don't match the manifest's recorded `source_artifact_sha256` (stale figure);
`readme_img/`'s copy diverged from `paper_exports/figures/`'s; or a required
figure has no manifest entry at all.

## How to regenerate

```
cd backend
./.venv-validation/Scripts/python.exe -m pytest app/tests/unit/ble_scientific_results app/tests/unit/ble_rffi_studio -q
cd ..
backend/.venv-validation/Scripts/python.exe docs/ble/generate_evidence_figures.py
```

`generate_evidence_figures.py` calls `ScientificResultsRepository.run_paper_export()`
internally (writing every CSV/PDF/SVG under `paper_exports/`), then renders
the remaining `readme_img/evidence_*.png` figures and copies the three
figures the paper-export pipeline already renders. It reads only
already-persisted `06_statistics/*.json` reports and the evidence dashboard
summary built from them -- it computes no new science and will not fabricate
a row for evidence that has not been computed yet (see `SKIPPED_NO_DATA` in
`paper_exports/export_manifest.json`).

If a report referenced above (`rq1_acquisition_dependence_report.json`,
`rq2_representation_comparison_report.json`, `coverage_analysis_report.json`
with `evaluate_window_level=true`, `sensitivity_report.json`) does not exist
yet for the current `paper_run_id`, regenerate it first from the Study
Control Center tab or the Coverage tab's own button (see
`SCIENTIFIC_STATUS.md` §18) -- never hand-fill the figure/table with a
stand-in value.
