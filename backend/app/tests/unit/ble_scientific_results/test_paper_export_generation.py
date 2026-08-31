"""Paper progress dashboard, point 2 (2026-08-11): the paper export
generator must actually generate CSV/LaTeX/figure files when a real source
artifact exists, and record SKIPPED_NO_DATA with a reason when it does not
-- never a fabricated row or a zero-filled figure. All fixtures here are
written directly into an isolated tmp_path repository (never real storage).
"""
from __future__ import annotations

import csv
import hashlib
import json

from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository
from app.modules.ble_scientific_results.paper_export import (
    channel_transport_rows,
    confusion_matrix_rows,
    development_decision_window_summary_rows,
    generate_paper_exports,
    offline_nearlive_rows,
    qualification_summary_rows,
    render_latex_tables,
    rq1_result_rows,
    rq2_result_rows,
)


def _repo(tmp_path):
    return ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")


def _write_json(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_run(repo, run_id: str = "RUN-1") -> None:
    """Real paper run directories are only recognized via `run.json` (see
    `list_runs()`/`_most_recent_run_dir()`) -- write the minimal marker so
    the exporter's run-scoped lookups (RQ1/RQ3/RQ4/S1/S2) find this fixture."""
    _write_json(repo.root / run_id / "run.json", {
        "paper_run_id": run_id, "campaign_id": "C1", "protocol_id": "P1", "protocol_version": 1,
        "dataset_id": "DS1", "dataset_version": "1.0.0", "scientific_task": "SAME_MODEL_UNIT_IDENTIFICATION",
        "analysis_code_commit": "deadbeef", "analysis_environment_hash": "envhash",
        "storage_path": str(repo.root / run_id), "created_at": "2026-08-01T00:00:00Z",
    })


def _entry(manifest, filename):
    return next(e for e in manifest["entries"] if e["file"] == filename)


def test_empty_repository_generates_only_study_status_paper_readiness_and_completeness(tmp_path):
    repo = _repo(tmp_path)
    manifest = generate_paper_exports(repo)
    assert _entry(manifest, "study_status.json")["status"] == "GENERATED"
    assert _entry(manifest, "paper_readiness.json")["status"] == "GENERATED"
    for filename in ("rq1_results.csv", "rq3_results.csv", "rq4_results.csv", "channel_transport_results.csv", "offline_nearlive_results.csv"):
        entry = _entry(manifest, filename)
        assert entry["status"] == "SKIPPED_NO_DATA"
        assert entry["detail"]
    # scientific_completeness.csv is the one export that ALWAYS has real
    # data to report (its whole purpose is stating "not available yet" with
    # a real reason) -- so paper_tables.tex now has at least this one real
    # section even on an otherwise-empty repository.
    assert _entry(manifest, "scientific_completeness.csv")["status"] == "GENERATED"
    assert _entry(manifest, "paper_tables.tex")["status"] == "GENERATED"
    assert (tmp_path / "sci_results" / "paper_exports" / "study_status.json").is_file()


def test_qualification_summary_generated_when_preflight_report_exists(tmp_path):
    repo = _repo(tmp_path)
    _write_json(repo.root / "campaign_qualification_preflight_report.json", {"items": {"b200_detected": {"status": "READY", "detail": "ok"}}})
    manifest = generate_paper_exports(repo)
    entry = _entry(manifest, "qualification_summary.csv")
    assert entry["status"] == "GENERATED"
    rows = list(csv.DictReader((repo.root / "paper_exports" / "qualification_summary.csv").open(encoding="utf-8")))
    assert rows == [{"gate": "b200_detected", "status": "READY", "detail": "ok"}]


def test_scientific_completeness_and_tx_composition_are_generated_regardless_of_closed_set_state(tmp_path):
    """These two exports must be real and present even with zero registered
    units / zero paper runs -- scientific_completeness's whole purpose is
    reporting real absence, and tx_composition legitimately lists 0 rows."""
    repo = _repo(tmp_path)
    manifest = generate_paper_exports(repo)
    assert _entry(manifest, "scientific_completeness.csv")["status"] == "GENERATED"
    rows = list(csv.DictReader((repo.root / "paper_exports" / "scientific_completeness.csv").open(encoding="utf-8")))
    assert any(r["item"] == "strong_native_sdr_association" and r["status"] == "BLOCKED" for r in rows)
    # tx_composition has nothing to report on an empty registry -- honest SKIPPED, not a fabricated empty CSV.
    assert _entry(manifest, "tx_composition.csv")["status"] == "SKIPPED_NO_DATA"


def test_closed_set_exports_generated_from_a_real_multi_device_classification_run(tmp_path):
    repo = _repo(tmp_path)
    _write_json(repo.root / "CLOSED-RUN" / "run.json", {
        "paper_run_id": "CLOSED-RUN", "campaign_id": "C1", "protocol_id": "P1", "protocol_version": 1,
        "dataset_id": "IDENTITY-DS", "dataset_version": "v1", "scientific_task": "MULTI_DEVICE_CLASSIFICATION",
        "analysis_code_commit": "deadbeef", "analysis_environment_hash": "envhash",
        "storage_path": str(repo.root / "CLOSED-RUN"), "created_at": "2026-08-17T00:00:00Z",
    })
    _write_json(repo.root / "CLOSED-RUN" / "06_statistics" / "rq2_representation_comparison_report.json", {
        "schema_version": "ble-scientific-results-rq2-representation-comparison-v1",
        "branches": [{
            "branch": "engineered_rf", "analysis_role": "PRIMARY", "evaluation_domain": "VALIDATION",
            "model_type": "random_forest", "training_run_id": "TRAIN-1", "balanced_accuracy": 0.7, "macro_f1": 0.65,
        }],
        "generated_at": "2026-08-17T00:00:00Z",
    })
    _write_json(repo.ble_root / "splits" / "IDENTITY-DS__v1__MULTI_DEVICE_CLASSIFICATION.json", {
        "schema_version": "ble-rffi-studio-split-v1", "dataset_id": "IDENTITY-DS", "dataset_version": "v1",
        "scientific_task": "MULTI_DEVICE_CLASSIFICATION", "policy": "test", "split_status": "READY",
        "assignments": [{"example_id": "e1", "physical_unit_id": "UNIT-A", "capture_id": "CAP-1", "session_id": "S1", "split": "VALIDATION", "split_reason": "t"}],
        "leakage_check": {"status": "PASSED"}, "created_at": "2026-08-17T00:00:00Z", "split_manifest_sha256": "hash",
    })
    _write_json(repo.ble_root / "training_runs" / "TRAIN-1" / "evaluation_report.json", {
        "TEST": {
            "accuracy": 0.8, "balanced_accuracy": 0.75, "macro_f1": 0.7,
            "recall_per_class": {"UNIT-A": 0.9, "UNIT-B": 0.5}, "precision_per_class": {"UNIT-A": 0.8, "UNIT-B": 0.6}, "f1_per_class": {"UNIT-A": 0.85, "UNIT-B": 0.55},
            "confusion_matrix": {"UNIT-A": {"UNIT-A": 9, "UNIT-B": 1}, "UNIT-B": {"UNIT-A": 1, "UNIT-B": 1}},
        },
    })
    _write_json(repo.root / "CLOSED-RUN" / "06_statistics" / "coverage_analysis_report.json", {
        "schema_version": "ble-scientific-results-coverage-analysis-v1", "generated_at": "2026-08-17T00:00:00Z",
        "paper_run_id": "CLOSED-RUN", "bundle_ids": {"engineered_rf": "BUNDLE-1"}, "window_duration_s": 10.0, "minimum_eligible_bursts": 1,
        "overall": None, "by_evaluation_domain": {"TEST": {"abstained_windows": 0, "coverage": 1.0, "decided_windows": 2, "eligible_windows": 2}},
        "by_branch": {}, "by_physical_unit": {}, "abstention_reason_counts": "NOT_AVAILABLE",
        "window_level_evaluation": {
            "engineered_rf": {
                "acceptance_threshold": 0.66, "acceptance_threshold_calibrated_on": "VALIDATION",
                "by_evaluation_domain": {
                    "TEST": {
                        "evidence_maturity": "CURRENT_TEST", "balanced_accuracy": 0.5, "macro_f1": 0.5,
                        "confusion_matrix": {"UNIT-A": {"UNIT-A": 1, "UNIT-B": 0}, "UNIT-B": {"UNIT-A": 1, "UNIT-B": 0}}, "n_comparable": 2,
                        "risk_coverage": [{"coverage": 1.0, "risk": 0.5, "threshold": 0.7, "n_decided": 2, "n_abstained": 0}],
                    },
                },
                "decision_windows": [
                    {"branch": "engineered_rf", "evaluation_domain": "TEST", "decision_window_id": "w1", "capture_id": "CAP-1", "window_duration_s": 10.0,
                     "burst_count": 3, "true_physical_unit_id": "UNIT-A", "predicted_class": "UNIT-A", "class_probability": 0.9,
                     "final_decision": "IDENTIFIED", "abstention_reason": None},
                    {"branch": "engineered_rf", "evaluation_domain": "TEST", "decision_window_id": "w2", "capture_id": "CAP-2", "window_duration_s": 10.0,
                     "burst_count": 2, "true_physical_unit_id": "UNIT-B", "predicted_class": "UNIT-A", "class_probability": 0.6,
                     "final_decision": "IDENTIFIED", "abstention_reason": None},
                ],
            },
        },
    })

    manifest = generate_paper_exports(repo)

    assert _entry(manifest, "closed_set_partition_composition.csv")["status"] == "GENERATED"
    partition_rows = list(csv.DictReader((repo.root / "paper_exports" / "closed_set_partition_composition.csv").open(encoding="utf-8")))
    validation_row = next(r for r in partition_rows if r["domain"] == "VALIDATION")
    assert validation_row["n_examples"] == "1"
    assert validation_row["n_captures"] == "1"

    per_tx_entry = _entry(manifest, "closed_set_per_transmitter.csv")
    assert per_tx_entry["status"] == "GENERATED"
    assert per_tx_entry.get("figure_classification") == "PAPER_PRIMARY"
    assert (repo.root / "paper_exports" / "closed_set_per_transmitter.csv.provenance.json").is_file()
    per_tx_rows = list(csv.DictReader((repo.root / "paper_exports" / "closed_set_per_transmitter.csv").open(encoding="utf-8")))
    assert {r["physical_unit_id"] for r in per_tx_rows} == {"UNIT-A", "UNIT-B"}

    normalized_entry = _entry(manifest, "figures/closed_set_confusion_matrix_normalized.pdf")
    assert normalized_entry["status"] == "GENERATED"
    assert (repo.root / "paper_exports" / "figures" / "closed_set_confusion_matrix_normalized.pdf").read_bytes()[:4] == b"%PDF"
    assert (repo.root / "paper_exports" / "figures" / "closed_set_confusion_matrix_normalized.svg").is_file()
    assert (repo.root / "paper_exports" / "figures" / "closed_set_confusion_matrix_normalized.png").is_file()

    assert _entry(manifest, "figures/campaign_timeline.pdf")["status"] == "GENERATED"
    # No bundle was ever exported for TRAIN-1 in this fixture -- forensic
    # lineage must still generate, honestly stating "not exported yet".
    assert _entry(manifest, "figures/forensic_lineage.pdf")["status"] == "GENERATED"

    # Closed-set 10-second decision windows + window-level risk-coverage --
    # same real coverage_analysis_report.json the Coverage tab reads.
    assert _entry(manifest, "closed_set_decision_windows.csv")["status"] == "GENERATED"
    dw_rows = list(csv.DictReader((repo.root / "paper_exports" / "closed_set_decision_windows.csv").open(encoding="utf-8")))
    assert {(r["decision_window_id"], r["true_physical_unit_id"], r["predicted_class"]) for r in dw_rows} == {("w1", "UNIT-A", "UNIT-A"), ("w2", "UNIT-B", "UNIT-A")}

    assert _entry(manifest, "closed_set_risk_coverage_window_level.csv")["status"] == "GENERATED"
    rc_rows = list(csv.DictReader((repo.root / "paper_exports" / "closed_set_risk_coverage_window_level.csv").open(encoding="utf-8")))
    assert rc_rows[0]["evaluation_domain"] == "TEST"
    assert rc_rows[0]["n_decided"] == "2"
    assert rc_rows[0]["n_abstained"] == "0"
    assert rc_rows[0]["selective_error"] == "0.5"

    # DEVELOPMENT EVIDENCE closure pass (2026-08-18): compact per-partition
    # decision-window summary + the TEST window-level confusion matrix, both
    # read from the SAME coverage_analysis_report.json above.
    assert _entry(manifest, "development_decision_window_summary.csv")["status"] == "GENERATED"
    summary_rows = list(csv.DictReader((repo.root / "paper_exports" / "development_decision_window_summary.csv").open(encoding="utf-8")))
    assert len(summary_rows) == 1  # only TEST has real window_level_evaluation data in this fixture
    test_summary = summary_rows[0]
    assert test_summary["partition"] == "TEST"
    assert test_summary["n_windows"] == "2"
    assert test_summary["n_decided"] == "2"
    assert test_summary["accuracy"] == "0.5"  # UNIT-A correctly identified once, UNIT-B misclassified once
    assert json.loads(test_summary["n_per_tx"]) == {"UNIT-A": 1, "UNIT-B": 1}  # one real decision window per true TX (w1, w2)
    assert test_summary["evaluation_unit"] == "DECISION_WINDOW"
    assert test_summary["evidence_status"] == "DEVELOPMENT"

    assert _entry(manifest, "development_test_window_confusion_matrix.csv")["status"] == "GENERATED"
    matrix_rows = list(csv.DictReader((repo.root / "paper_exports" / "development_test_window_confusion_matrix.csv").open(encoding="utf-8")))
    assert matrix_rows == [
        {"true_label": "UNIT-A", "predicted_UNIT-A": "1", "predicted_UNIT-B": "0"},
        {"true_label": "UNIT-B", "predicted_UNIT-A": "1", "predicted_UNIT-B": "0"},
    ]


def test_closed_set_decision_window_exports_skipped_when_no_coverage_report_exists(tmp_path):
    # Same closed-set fixture as above, minus coverage_analysis_report.json
    # -- must be honestly SKIPPED_NO_DATA, never a fabricated empty table.
    repo = _repo(tmp_path)
    _write_json(repo.root / "CLOSED-RUN" / "run.json", {
        "paper_run_id": "CLOSED-RUN", "campaign_id": "C1", "protocol_id": "P1", "protocol_version": 1,
        "dataset_id": "IDENTITY-DS", "dataset_version": "v1", "scientific_task": "MULTI_DEVICE_CLASSIFICATION",
        "analysis_code_commit": "deadbeef", "analysis_environment_hash": "envhash",
        "storage_path": str(repo.root / "CLOSED-RUN"), "created_at": "2026-08-17T00:00:00Z",
    })
    _write_json(repo.root / "CLOSED-RUN" / "06_statistics" / "rq2_representation_comparison_report.json", {
        "schema_version": "ble-scientific-results-rq2-representation-comparison-v1",
        "branches": [{
            "branch": "engineered_rf", "analysis_role": "PRIMARY", "evaluation_domain": "VALIDATION",
            "model_type": "random_forest", "training_run_id": "TRAIN-1", "balanced_accuracy": 0.7, "macro_f1": 0.65,
        }],
        "generated_at": "2026-08-17T00:00:00Z",
    })
    _write_json(repo.ble_root / "splits" / "IDENTITY-DS__v1__MULTI_DEVICE_CLASSIFICATION.json", {
        "schema_version": "ble-rffi-studio-split-v1", "dataset_id": "IDENTITY-DS", "dataset_version": "v1",
        "scientific_task": "MULTI_DEVICE_CLASSIFICATION", "policy": "test", "split_status": "READY",
        "assignments": [{"example_id": "e1", "physical_unit_id": "UNIT-A", "capture_id": "CAP-1", "session_id": "S1", "split": "VALIDATION", "split_reason": "t"}],
        "leakage_check": {"status": "PASSED"}, "created_at": "2026-08-17T00:00:00Z", "split_manifest_sha256": "hash",
    })

    manifest = generate_paper_exports(repo)
    assert _entry(manifest, "closed_set_decision_windows.csv")["status"] == "SKIPPED_NO_DATA"
    assert _entry(manifest, "closed_set_risk_coverage_window_level.csv")["status"] == "SKIPPED_NO_DATA"


def test_rq1_results_and_figures_generated_when_rq1_report_exists(tmp_path):
    repo = _repo(tmp_path)
    _write_run(repo)
    run_dir = repo.root / "RUN-1"
    _write_json(run_dir / "06_statistics" / "rq1_acquisition_dependence_report.json", {
        "ba_window": 0.9, "ba_capture": 0.6, "ba_future": None, "ba_future_status": "NOT_APPLICABLE",
        "delta_dependence": 0.3, "delta_future": None,
        "confusion_matrix_capture": {"A": {"A": 5, "B": 1}, "B": {"A": 2, "B": 4}},
        "confusion_matrix_future": None,
        "per_unit_recall": {"UNIT-A": {"recall": 0.8}, "UNIT-B": {"recall": None}},
    })
    manifest = generate_paper_exports(repo)

    assert _entry(manifest, "rq1_results.csv")["status"] == "GENERATED"
    assert _entry(manifest, "figures/rq1_acquisition_dependence.pdf")["status"] == "GENERATED"
    assert (repo.root / "paper_exports" / "figures" / "rq1_acquisition_dependence.pdf").read_bytes()[:4] == b"%PDF"
    # Multi-format output (2026-08-18): the SAME rendering also saved as PNG
    # -- what readme_img/evidence_rq1_domains.png is a plain copy of.
    png_path = repo.root / "paper_exports" / "figures" / "rq1_acquisition_dependence.png"
    assert png_path.is_file()
    assert png_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    # figure_manifest.json (2026-08-18): a real, verifiable artifact -> figure
    # trace -- source_artifact_sha256 must match the REAL bytes on disk of
    # the exact rq1_acquisition_dependence_report.json this figure was
    # rendered from, not a fabricated or stale hash.
    figure_manifest = json.loads((repo.root / "paper_exports" / "figure_manifest.json").read_text(encoding="utf-8"))
    rq1_figure_entry = next(f for f in figure_manifest["figures"] if f["figure_path"] == "figures/rq1_acquisition_dependence.png")
    assert rq1_figure_entry["source_artifact"] == "RUN-1/06_statistics/rq1_acquisition_dependence_report.json"
    real_bytes = (run_dir / "06_statistics" / "rq1_acquisition_dependence_report.json").read_bytes()
    assert rq1_figure_entry["source_artifact_sha256"] == hashlib.sha256(real_bytes).hexdigest()
    assert rq1_figure_entry["paper_run_id"] == "RUN-1"
    assert rq1_figure_entry["evaluation_unit"] == "EXAMPLE_RECORD"  # fixture predates the evidence_status/evaluation_unit fields -- defaults apply
    assert rq1_figure_entry["evidence_status"] == "DEVELOPMENT"
    assert rq1_figure_entry["generator"] == "figures/paper_figures.py::bar_with_ci_figure"
    assert rq1_figure_entry["generated_at"]

    assert _entry(manifest, "confusion_matrix_capture.csv")["status"] == "GENERATED"
    assert _entry(manifest, "figures/rq1_confusion_matrix_capture.pdf")["status"] == "GENERATED"
    assert (repo.root / "paper_exports" / "figures" / "rq1_confusion_matrix_capture.pdf").read_bytes()[:4] == b"%PDF"
    assert _entry(manifest, "confusion_matrix_future.csv")["status"] == "SKIPPED_NO_DATA"
    assert _entry(manifest, "figures/rq1_confusion_matrix_future.pdf")["status"] == "SKIPPED_NO_DATA"
    assert _entry(manifest, "figures/rq1_per_unit_recall.pdf")["status"] == "GENERATED"
    assert (repo.root / "paper_exports" / "figures" / "rq1_per_unit_recall.pdf").read_bytes()[:4] == b"%PDF"
    assert _entry(manifest, "paper_tables.tex")["status"] == "GENERATED"
    tex = (repo.root / "paper_exports" / "paper_tables.tex").read_text(encoding="utf-8")
    assert "rq1_results" in tex


def test_channel_transport_figure_skips_none_scores_never_plots_a_fabricated_zero(tmp_path):
    repo = _repo(tmp_path)
    _write_run(repo)
    run_dir = repo.root / "RUN-1"
    _write_json(run_dir / "06_statistics" / "channel_transport_report.json", {
        "per_channel": [
            {"channel": 37, "center_frequency_hz": 2_402_000_000, "frozen_bundle_id": "B1", "windows": 10, "balanced_accuracy": None, "macro_f1": None, "coverage": None},
        ],
    })
    manifest = generate_paper_exports(repo)
    assert _entry(manifest, "channel_transport_results.csv")["status"] == "GENERATED"
    assert _entry(manifest, "figures/channel_transport.pdf")["status"] == "SKIPPED_NO_DATA"


def test_offline_nearlive_skipped_when_no_real_pairs_matched(tmp_path):
    repo = _repo(tmp_path)
    _write_run(repo)
    run_dir = repo.root / "RUN-1"
    _write_json(run_dir / "06_statistics" / "offline_nearlive_report.json", {
        "pairing_status": "NO_DATA", "analytical_agreement": None,
        "computational_behavior": {"median_latency_ms": "NOT_MEASURED"},
    })
    manifest = generate_paper_exports(repo)
    assert _entry(manifest, "offline_nearlive_results.csv")["status"] == "SKIPPED_NO_DATA"


def test_rq3_and_rq4_generated_from_confirmatory_future_analysis_report(tmp_path):
    repo = _repo(tmp_path)
    _write_run(repo)
    run_dir = repo.root / "RUN-1"
    _write_json(run_dir / "06_statistics" / "confirmatory_future_analysis_report.json", {
        "rq3_within_device_permutation_test": {"status": "EXECUTED", "detail": None, "value": {"observed_statistic": 0.2, "p_value": 0.01}},
        "rq4_paired_comparison": {"status": "EXECUTED", "detail": None, "value": {"delta": 0.05}},
        "non_inferiority": {"status": "EXECUTED", "detail": None, "value": {"margin": 0.1, "estimate": 0.02}},
        "holm_correction": {"status": "EXECUTED", "detail": None, "value": {"adjusted_p_values": [0.01, 0.02]}},
        "risk_coverage": {"status": "EXECUTED", "detail": None, "value": [{"coverage": 1.0, "risk": 0.1, "threshold": 0.5}, {"coverage": 0.5, "risk": 0.02, "threshold": 0.9}]},
    })
    manifest = generate_paper_exports(repo)
    assert _entry(manifest, "rq3_results.csv")["status"] == "GENERATED"
    assert _entry(manifest, "rq4_results.csv")["status"] == "GENERATED"
    assert _entry(manifest, "coverage_results.csv")["status"] == "GENERATED"
    assert _entry(manifest, "figures/risk_coverage.pdf")["status"] == "GENERATED"
    assert (repo.root / "paper_exports" / "figures" / "risk_coverage.pdf").read_bytes()[:4] == b"%PDF"
    # No rq2_representation_comparison_report.json was persisted in this
    # fixture -- honest gap (absence of data, not absence of mechanism).
    assert _entry(manifest, "rq2_results.csv")["status"] == "SKIPPED_NO_DATA"


def test_rq3_and_rq4_figures_generated_from_the_validation_dry_run_series(tmp_path):
    """Fast-closure pass (2026-08-12): rq3_pairs/rq3_reset_mean_d_ci/
    rq4_region_report only ever live in confirmatory_statistical_plan_
    report.json (the VALIDATION dry-run, from run_rq3_frr_analysis/
    run_rq4_region_analysis) -- confirmatory_future_analysis_report.json
    never carries them. The PRE-POST/D/region-comparison/non-inferiority
    figures must read the VALIDATION series for their per-unit/per-region
    data while the pass/fail hypothesis-test status still comes exclusively
    from the FUTURE-gated report."""
    repo = _repo(tmp_path)
    _write_run(repo)
    run_dir = repo.root / "RUN-1"
    _write_json(run_dir / "06_statistics" / "confirmatory_future_analysis_report.json", {
        "rq3_within_device_permutation_test": {"status": "EXECUTED", "detail": None, "value": {"observed_statistic": 0.2, "p_value": 0.01}},
        "rq4_paired_comparison": {"status": "EXECUTED", "detail": None, "value": {"delta": 0.05}},
        "non_inferiority": {"status": "EXECUTED", "detail": None, "value": {"mean_difference": 0.02, "ci_low": -0.01, "margin": 0.05, "non_inferior": True}},
        "holm_correction": {"status": "EXECUTED", "detail": None, "value": {"adjusted_p_values": [0.01, 0.02]}},
    })
    _write_json(run_dir / "06_statistics" / "confirmatory_statistical_plan_report.json", {
        "rq3_pairs": [
            {"physical_unit_id": "UNIT-A", "intervention_arm": "RESET", "valid": True, "pre_frr": 0.2, "post_frr": 0.3},
            {"physical_unit_id": "UNIT-B", "intervention_arm": "CONTROL", "valid": False, "pre_frr": None, "post_frr": None},
        ],
        "rq3_reset_mean_d_ci": {"point_estimate": 0.1, "ci_low": 0.05, "ci_high": 0.15, "n_resamples": 200, "confidence_level": 0.95},
        "rq3_control_mean_d_ci": None,
        "rq4_region_report": {
            "matched_region_blocks": [
                {"regions": {"FULL_BURST": {"recall": 0.9}, "ADVA_EXCLUDED": {"recall": 0.7}, "PRE_PDU": {"recall": 0.6}}},
            ],
        },
    })
    manifest = generate_paper_exports(repo)

    assert _entry(manifest, "figures/rq3_pre_post.pdf")["status"] == "GENERATED"
    assert (repo.root / "paper_exports" / "figures" / "rq3_pre_post.pdf").read_bytes()[:4] == b"%PDF"
    assert _entry(manifest, "figures/rq3_delta_cycle.pdf")["status"] == "GENERATED"
    assert (repo.root / "paper_exports" / "figures" / "rq3_delta_cycle.pdf").read_bytes()[:4] == b"%PDF"
    assert _entry(manifest, "figures/rq4_region_dependence.pdf")["status"] == "GENERATED"
    assert (repo.root / "paper_exports" / "figures" / "rq4_region_dependence.pdf").read_bytes()[:4] == b"%PDF"
    assert _entry(manifest, "figures/rq4_noninferiority.pdf")["status"] == "GENERATED"
    assert (repo.root / "paper_exports" / "figures" / "rq4_noninferiority.pdf").read_bytes()[:4] == b"%PDF"


def test_rq2_results_and_figures_generated_when_rq2_report_exists(tmp_path):
    repo = _repo(tmp_path)
    _write_run(repo)
    repo.persist_rq2_representation_comparison_report(
        paper_run_id="RUN-1", protocol_id="PROTO-1", protocol_version=1, contract_sha256="hash",
        dataset_id="DS1", dataset_version="1.0.0", split_manifest_id="SPLIT-1", split_manifest_sha256="split-hash",
        branch_results=[
            {"branch": "raw_iq", "analysis_role": "PRIMARY", "evaluation_domain": "VALIDATION", "balanced_accuracy": 0.91, "coverage": 0.97},
            {"branch": "stft", "analysis_role": "UNSELECTED", "evaluation_domain": "VALIDATION"},
        ],
    )
    manifest = generate_paper_exports(repo)
    assert _entry(manifest, "rq2_results.csv")["status"] == "GENERATED"
    assert _entry(manifest, "figures/rq2_representation_comparison.pdf")["status"] == "GENERATED"
    assert (repo.root / "paper_exports" / "figures" / "rq2_representation_comparison.pdf").read_bytes()[:4] == b"%PDF"
    assert (repo.root / "paper_exports" / "figures" / "rq2_representation_comparison.png").is_file()
    # Only raw_iq has a real coverage value -- stft's is absent, not 0.
    assert _entry(manifest, "figures/rq2_coverage.pdf")["status"] == "GENERATED"
    rows = list(csv.DictReader((repo.root / "paper_exports" / "rq2_results.csv").open(encoding="utf-8")))
    assert len(rows) == 2

    figure_manifest = json.loads((repo.root / "paper_exports" / "figure_manifest.json").read_text(encoding="utf-8"))
    rq2_figure_entry = next(f for f in figure_manifest["figures"] if f["figure_path"] == "figures/rq2_representation_comparison.png")
    assert rq2_figure_entry["source_artifact"] == "RUN-1/06_statistics/rq2_representation_comparison_report.json"
    assert rq2_figure_entry["paper_run_id"] == "RUN-1"
    assert rq2_figure_entry["evaluation_unit"] == "EXAMPLE_RECORD"
    assert rq2_figure_entry["evidence_status"] == "DEVELOPMENT"
    assert rq2_figure_entry["generator"] == "figures/paper_figures.py::bar_with_ci_figure"


def test_manifest_counts_reflect_generated_and_skipped_entries(tmp_path):
    repo = _repo(tmp_path)
    manifest = generate_paper_exports(repo)
    assert manifest["generated_count"] == sum(1 for e in manifest["entries"] if e["status"] == "GENERATED")
    assert manifest["skipped_count"] == sum(1 for e in manifest["entries"] if e["status"] == "SKIPPED_NO_DATA")
    assert manifest["generated_count"] + manifest["skipped_count"] == len(manifest["entries"])


# --- Pure per-export transforms (independent of any filesystem state) ---

def test_qualification_summary_rows_shape():
    rows = qualification_summary_rows({"items": {"g1": {"status": "READY", "detail": "d"}}})
    assert rows == [{"gate": "g1", "status": "READY", "detail": "d"}]


def test_confusion_matrix_rows_is_square_and_ordered():
    rows = confusion_matrix_rows({"A": {"A": 3, "B": 1}, "B": {"A": 0, "B": 4}})
    assert rows == [{"true_label": "A", "predicted_A": 3, "predicted_B": 1}, {"true_label": "B", "predicted_A": 0, "predicted_B": 4}]


def test_rq1_result_rows_reports_delta_rows():
    rows = rq1_result_rows({"ba_window": 0.9, "ba_capture": 0.6, "ba_future": None, "ba_future_status": "NOT_APPLICABLE", "delta_dependence": 0.3, "delta_future": None})
    assert any(r["domain"] == "delta_dependence" and r["ba"] == 0.3 for r in rows)


def test_rq2_result_rows_shape():
    rows = rq2_result_rows({"branches": [
        {"branch": "raw_iq", "analysis_role": "PRIMARY", "evaluation_domain": "VALIDATION", "balanced_accuracy": 0.91, "macro_f1": 0.89, "coverage": 0.97, "model_bundle_id": "B1"},
        {"branch": "stft", "analysis_role": "UNSELECTED", "evaluation_domain": "VALIDATION"},
    ]})
    assert rows[0]["branch"] == "raw_iq"
    assert rows[0]["analysis_role"] == "PRIMARY"
    assert rows[1]["balanced_accuracy"] is None


def test_channel_transport_rows_shape():
    rows = channel_transport_rows({"per_channel": [{"channel": 37, "center_frequency_hz": 1, "frozen_bundle_id": "B1", "windows": 5, "balanced_accuracy": 0.9, "macro_f1": 0.8, "coverage": 1.0}]})
    assert rows[0]["channel"] == 37
    assert rows[0]["bundle_id"] == "B1"


def test_offline_nearlive_rows_flattens_both_sections():
    rows = offline_nearlive_rows({"analytical_agreement": {"decision_count": 2}, "computational_behavior": {"median_latency_ms": "NOT_MEASURED"}})
    assert {"category": "analytical_agreement", "metric": "decision_count", "value": 2} in rows
    assert {"category": "computational_behavior", "metric": "median_latency_ms", "value": "NOT_MEASURED"} in rows


def test_development_decision_window_summary_rows_one_row_per_real_partition():
    coverage_report = {
        "window_duration_s": 10.0,
        "by_evaluation_domain": {
            "VALIDATION": {"abstained_windows": 0, "coverage": 1.0},
            "TEST": {"abstained_windows": 1, "coverage": 0.5},
        },
        "window_level_evaluation": {
            "engineered_rf": {
                "by_evaluation_domain": {
                    "VALIDATION": {"balanced_accuracy": 0.75, "n_comparable": 4, "confusion_matrix": {"A": {"A": 2, "B": 0}, "B": {"A": 1, "B": 1}}},
                    "TEST": {"balanced_accuracy": 1.0, "n_comparable": 2, "confusion_matrix": {"A": {"A": 1, "B": 0}, "B": {"A": 0, "B": 1}}},
                },
            },
        },
    }
    rows = development_decision_window_summary_rows(coverage_report, "engineered_rf")
    assert [r["partition"] for r in rows] == ["VALIDATION", "TEST"]
    validation_row = rows[0]
    assert validation_row["n_windows"] == 4
    assert validation_row["n_decided"] == 4
    assert validation_row["accuracy"] == 0.75  # (2 + 1) correct / 4
    assert json.loads(validation_row["n_per_tx"]) == {"A": 2, "B": 2}
    assert validation_row["n_abstained"] == 0
    assert validation_row["coverage"] == 1.0
    assert validation_row["evaluation_unit"] == "DECISION_WINDOW"
    assert validation_row["window_duration_s"] == 10.0
    assert validation_row["evidence_status"] == "DEVELOPMENT"
    test_row = rows[1]
    assert test_row["accuracy"] == 1.0
    assert test_row["n_abstained"] == 1


def test_development_decision_window_summary_rows_empty_when_branch_missing():
    assert development_decision_window_summary_rows({"window_level_evaluation": {}}, "engineered_rf") == []


def test_render_latex_tables_skips_empty_sections():
    tex = render_latex_tables({"real_section": [{"a": 1}], "empty_section": []})
    assert "real_section" in tex
    assert "empty_section" not in tex
