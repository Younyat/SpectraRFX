"""Protocol-freeze close-out, point 4 (2026-08-10):
persist_rq1_acquisition_dependence_report is the ONLY place that writes
evaluate_rq1_acquisition_dependence()'s in-memory numbers to a canonical,
disk-persisted artifact, and only ever with real, caller-supplied linking
metadata (protocol_version, contract_sha256, git_sha, bundle/split ids and
hashes, source evaluation domains) -- it invents nothing.
"""
from __future__ import annotations

import json

from app.modules.ble_rffi_studio.evaluation import Evaluator, evaluate_rq1_acquisition_dependence
from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository


def _repo(tmp_path):
    return ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")


def _real_rq1_report():
    evaluator = Evaluator()
    known_classes = ["A", "B"]
    predictions = [
        {"example_id": "c0", "true_label": "A", "predicted_label": "A"},
        {"example_id": "c1", "true_label": "A", "predicted_label": "A"},
        {"example_id": "b0", "true_label": "B", "predicted_label": "B"},
    ]
    same = evaluator.evaluate_split("VALIDATION", predictions, known_classes)
    return evaluate_rq1_acquisition_dependence(scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", window_report=same, capture_report=same)


def _imbalanced_split_report():
    """Deliberately imbalanced (majority class recall=1.0 hides a minority
    class's recall=0.0), so accuracy and balanced_accuracy MUST disagree --
    a fixture where the two coincide (like _real_rq1_report() above) cannot
    catch the real .accuracy-vs-.balanced_accuracy bug this guards against."""
    evaluator = Evaluator()
    known_classes = ["A", "B"]
    predictions = [{"example_id": f"a{i}", "true_label": "A", "predicted_label": "A"} for i in range(9)]
    predictions.append({"example_id": "b0", "true_label": "B", "predicted_label": "A"})
    return evaluator.evaluate_split("VALIDATION", predictions, known_classes)


def test_persisted_ba_window_and_ba_capture_are_never_raw_accuracy_end_to_end(tmp_path):
    # Coherence-audit regression guard (2026-08-19): a real bug persisted
    # SplitEvaluationReport.accuracy into the ba_window/ba_capture fields
    # instead of .balanced_accuracy, undetected because no end-to-end test
    # exercised the full evaluate_rq1_acquisition_dependence() ->
    # persist_rq1_acquisition_dependence_report() chain with a fixture where
    # the two definitions actually disagree.
    repo = _repo(tmp_path)
    split_report = _imbalanced_split_report()
    assert split_report.accuracy != split_report.balanced_accuracy  # fixture sanity check
    rq1_report = evaluate_rq1_acquisition_dependence(scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", window_report=split_report, capture_report=split_report)

    artifact = repo.persist_rq1_acquisition_dependence_report(
        paper_run_id="RUN-RQ1-IMBALANCED", protocol_id="PROTO-1", protocol_version=1, contract_sha256="real-contract-hash",
        rq1_report=rq1_report, model_bundle_id="BUNDLE-1", model_bundle_sha256="bundle-hash",
        confirmatory_split_manifest_id="SPLIT-CONF-1", confirmatory_split_manifest_sha256="split-conf-hash",
        diagnostic_split_manifest_id="SPLIT-DIAG-1", diagnostic_split_manifest_sha256="split-diag-hash",
        source_evaluation_domains={"window": "same-capture", "capture": "capture-disjoint"},
    )
    assert artifact["ba_window"] == split_report.balanced_accuracy
    assert artifact["ba_capture"] == split_report.balanced_accuracy
    assert artifact["ba_window"] != split_report.accuracy
    assert artifact["ba_capture"] != split_report.accuracy


def test_persists_a_real_canonical_artifact_with_every_required_linking_field(tmp_path):
    repo = _repo(tmp_path)
    rq1_report = _real_rq1_report()

    artifact = repo.persist_rq1_acquisition_dependence_report(
        paper_run_id="RUN-RQ1-1", protocol_id="PROTO-1", protocol_version=1, contract_sha256="real-contract-hash",
        rq1_report=rq1_report, model_bundle_id="BUNDLE-1", model_bundle_sha256="bundle-hash",
        confirmatory_split_manifest_id="SPLIT-CONF-1", confirmatory_split_manifest_sha256="split-conf-hash",
        diagnostic_split_manifest_id="SPLIT-DIAG-1", diagnostic_split_manifest_sha256="split-diag-hash",
        source_evaluation_domains={"window": "same-capture", "capture": "capture-disjoint"},
        uncertainty_ci={"ci_low": 0.5, "ci_high": 0.9}, coverage=0.95,
    )

    for required_field in (
        "protocol_id", "protocol_version", "contract_sha256", "git_sha", "model_bundle_id", "model_bundle_sha256",
        "confirmatory_split_manifest_id", "confirmatory_split_manifest_sha256",
        "diagnostic_split_manifest_id", "diagnostic_split_manifest_sha256",
        "source_evaluation_domains", "ba_window", "ba_capture", "ba_future", "delta_dependence", "delta_future",
        "uncertainty_ci", "coverage", "generated_at", "evaluation_unit", "evidence_status",
    ):
        assert required_field in artifact, required_field

    assert artifact["protocol_id"] == "PROTO-1"
    assert artifact["contract_sha256"] == "real-contract-hash"
    assert artifact["ba_window"] == rq1_report.ba_window
    assert artifact["delta_dependence"] == rq1_report.delta_dependence
    # Figure/artifact sync closure (2026-08-18): evidence_status is a real,
    # persisted field the figure generator/figure_manifest.json read
    # directly -- never a default the caller silently overrides here.
    assert artifact["evaluation_unit"] == "EXAMPLE_RECORD"
    assert artifact["evidence_status"] == "DEVELOPMENT"


def test_persisted_artifact_round_trips_from_disk(tmp_path):
    repo = _repo(tmp_path)
    rq1_report = _real_rq1_report()
    repo.persist_rq1_acquisition_dependence_report(
        paper_run_id="RUN-RQ1-2", protocol_id="PROTO-1", protocol_version=1, contract_sha256="real-contract-hash",
        rq1_report=rq1_report, model_bundle_id="BUNDLE-1", model_bundle_sha256="bundle-hash",
        confirmatory_split_manifest_id="SPLIT-CONF-1", confirmatory_split_manifest_sha256="split-conf-hash",
        diagnostic_split_manifest_id="SPLIT-DIAG-1", diagnostic_split_manifest_sha256="split-diag-hash",
        source_evaluation_domains={},
    )
    path = tmp_path / "sci_results" / "RUN-RQ1-2" / "06_statistics" / "rq1_acquisition_dependence_report.json"
    assert path.is_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["model_bundle_id"] == "BUNDLE-1"

    reloaded = repo.get_rq1_acquisition_dependence_report("RUN-RQ1-2")
    assert reloaded == on_disk
    assert repo.get_rq1_acquisition_dependence_report("RUN-NEVER-RAN") is None


def test_uncertainty_and_coverage_stay_none_when_not_supplied_never_fabricated(tmp_path):
    repo = _repo(tmp_path)
    rq1_report = _real_rq1_report()
    artifact = repo.persist_rq1_acquisition_dependence_report(
        paper_run_id="RUN-RQ1-3", protocol_id="PROTO-1", protocol_version=1, contract_sha256="real-contract-hash",
        rq1_report=rq1_report, model_bundle_id="BUNDLE-1", model_bundle_sha256="bundle-hash",
        confirmatory_split_manifest_id="SPLIT-CONF-1", confirmatory_split_manifest_sha256="split-conf-hash",
        diagnostic_split_manifest_id="SPLIT-DIAG-1", diagnostic_split_manifest_sha256="split-diag-hash",
        source_evaluation_domains={},
    )
    assert artifact["uncertainty_ci"] is None
    assert artifact["coverage"] is None


def test_evaluation_unit_defaults_to_example_record_and_cross_reference_is_pass_through(tmp_path):
    # Investigation finding (2026-08-17): RQ1's real evaluation unit is the
    # ExampleRecord, never a 10-second decision window -- this field makes
    # that explicit and machine-readable on every persisted artifact.
    repo = _repo(tmp_path)
    rq1_report = _real_rq1_report()
    artifact = repo.persist_rq1_acquisition_dependence_report(
        paper_run_id="RUN-RQ1-4", protocol_id="PROTO-1", protocol_version=1, contract_sha256="real-contract-hash",
        rq1_report=rq1_report, model_bundle_id="BUNDLE-1", model_bundle_sha256="bundle-hash",
        confirmatory_split_manifest_id="SPLIT-CONF-1", confirmatory_split_manifest_sha256="split-conf-hash",
        diagnostic_split_manifest_id="SPLIT-DIAG-1", diagnostic_split_manifest_sha256="split-diag-hash",
        source_evaluation_domains={},
    )
    assert artifact["evaluation_unit"] == "EXAMPLE_RECORD"
    assert artifact["decision_window_cross_reference"] is None  # never fabricated when the caller has none real

    cross_reference = {
        "source_artifact": "06_statistics/coverage_analysis_report.json", "window_duration_s": 10.0,
        "note": "real cross-reference, not RQ1's evaluation unit",
        "by_evaluation_domain": {"TEST": {"n_decision_windows": 5}, "VALIDATION": {"n_decision_windows": 5}, "TRAIN": {"n_decision_windows": 2}},
    }
    artifact_with_ref = repo.persist_rq1_acquisition_dependence_report(
        paper_run_id="RUN-RQ1-5", protocol_id="PROTO-1", protocol_version=1, contract_sha256="real-contract-hash",
        rq1_report=rq1_report, model_bundle_id="BUNDLE-1", model_bundle_sha256="bundle-hash",
        confirmatory_split_manifest_id="SPLIT-CONF-1", confirmatory_split_manifest_sha256="split-conf-hash",
        diagnostic_split_manifest_id="SPLIT-DIAG-1", diagnostic_split_manifest_sha256="split-diag-hash",
        source_evaluation_domains={}, decision_window_cross_reference=cross_reference,
    )
    assert artifact_with_ref["decision_window_cross_reference"] == cross_reference
