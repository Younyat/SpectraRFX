"""Paper export structure (2026-08-10, real generation added 2026-08-11) --
writes `paper_exports/` under the repository root. Pure reporting: never
computes a scientific value itself, only reads what
`ScientificResultsRepository` (or the ble_rffi_studio storage it reads)
already computed/persisted for real, and turns it into a CSV/LaTeX
table/figure.

Every planned export whose real source artifact does not exist yet is
recorded as SKIPPED_NO_DATA in `export_manifest.json` -- never a fabricated
CSV row, an empty placeholder PDF, or a zero-filled table. Each export
function below is a pure transform over an already-parsed dict (unit-
tested directly against synthetic fixtures in
test_paper_export_generation.py); only `generate_paper_exports` touches the
filesystem to decide whether real source data exists.
"""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.infrastructure.ble.capture.ble_capture_metadata import atomic_json

from . import paper_figure_aggregations
from .figures import paper_figures

EXPORT_MANIFEST_SCHEMA_VERSION = "ble-scientific-results-paper-export-manifest-v1"

# Publication-figure variants (2026-08-19, methodological audit item 7):
# RQ2's real branch identifiers are internal snake_case keys
# (_MODEL_TYPE_TO_RQ2_BRANCH's own vocabulary) -- fine for CSV/JSON, not for
# a manuscript figure. Maps the SAME 4 real branches to the human-readable
# labels the paper actually uses; PRIMARY/UNSELECTED is conveyed by bar
# color in the publication figure instead of a "(UNSELECTED)" text suffix.
RQ2_BRANCH_PUBLICATION_LABELS = {
    "coarse_morphology": "Coarse morphology", "engineered_rf": "Engineered RF",
    "raw_iq": "Raw I/Q", "stft": "STFT",
}

# Human-readable algorithm name for the forensic-lineage publication figure's
# "Training" node -- distinct from RQ2_BRANCH_PUBLICATION_LABELS above,
# which names the *representation* (e.g. "Engineered RF"), not the fitted
# algorithm (e.g. "Random Forest").
MODEL_TYPE_PUBLICATION_LABELS = {
    "random_forest": "Random Forest", "logistic_regression": "Logistic Regression", "svm_rbf": "RBF-SVM",
    "cnn1d": "1D CNN", "cnn2d": "2D CNN", "frozen_morphological_baseline": "Nearest-centroid baseline",
}

# Display-only pseudonym labels for the four enrolled physical units,
# applied exclusively to human-facing figure labels -- never to any
# persisted identifier, manifest field, or provenance record, which keep
# their real physical_unit_id unchanged everywhere. IMPORTANT PROVENANCE
# NOTE: no canonical artifact in this repository (PhysicalDeviceRegistry,
# docs/ble/physical_device_inventory.json) defines a TX-0x scheme for these
# units -- confirmed by inspection (2026-08-24) before adding this mapping.
# This assignment was supplied directly by the user for this repository's
# human-readable documentation layer and is applied here verbatim; it is
# not derived from, and does not modify, any existing canonical mapping.
PHYSICAL_UNIT_PSEUDONYM_LABELS = {
    "CC2541SensorTag": "TX-01", "keyfobdemo 01": "TX-03", "keyfobdemo 02": "TX-04", "CC2650-UNIT-01": "TX-05",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ExportOutcome:
    status: str  # "GENERATED" | "SKIPPED_NO_DATA"
    detail: str
    would_be_derived_from: str | None = None


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# ----------------------------------------------------------------------
# Per-export pure transforms: (parsed source dict) -> (csv rows, figure
# calls). Each is independently unit-testable with a synthetic fixture.
# ----------------------------------------------------------------------

def qualification_summary_rows(preflight_report: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"gate": name, "status": item.get("status"), "detail": item.get("detail")} for name, item in preflight_report.get("items", {}).items()]


def association_summary_rows(calibration_attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for attempt in calibration_attempts:
        rows.append({
            "status": attempt.get("status"), "threshold_ms": (attempt.get("policy") or {}).get("threshold_ms"),
            "calibration_campaign_id": (attempt.get("policy") or {}).get("calibration_campaign_id"),
            "detail": attempt.get("detail"),
            # Paper-representation pass (2026-08-17): the real per-threshold
            # sweep, structured (json-encoded per cell since a CSV cell is
            # scalar) -- present on every attempt persisted after this pass,
            # regardless of whether a policy was ever frozen.
            "acceptance_criterion": attempt.get("acceptance_criterion"),
            "coverage_by_threshold_ms": json.dumps(attempt["coverage_by_threshold_ms"]) if attempt.get("coverage_by_threshold_ms") is not None else None,
            "false_strong_by_threshold_ms": json.dumps(attempt["false_strong_by_threshold_ms"]) if attempt.get("false_strong_by_threshold_ms") is not None else None,
            "ambiguous_by_threshold_ms": json.dumps(attempt["ambiguous_by_threshold_ms"]) if attempt.get("ambiguous_by_threshold_ms") is not None else None,
        })
    return rows


def rq1_result_rows(rq1_report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"domain": "capture-dependent (BA_window)", "ba": rq1_report.get("ba_window"), "n_comparable": rq1_report.get("ba_window_n_comparable")},
        {"domain": "capture-disjoint (BA_capture)", "ba": rq1_report.get("ba_capture"), "n_comparable": rq1_report.get("ba_capture_n_comparable")},
        {"domain": f"protected future ({rq1_report.get('ba_future_status')})", "ba": rq1_report.get("ba_future"), "n_comparable": rq1_report.get("ba_future_n_comparable")},
        {"domain": "delta_dependence", "ba": rq1_report.get("delta_dependence"), "n_comparable": None},
        {"domain": "delta_future", "ba": rq1_report.get("delta_future"), "n_comparable": None},
    ]


def confusion_matrix_rows(confusion_matrix: dict[str, dict[str, int]]) -> list[dict[str, Any]]:
    labels = list(confusion_matrix.keys())
    rows = []
    for true_label in labels:
        row = {"true_label": true_label}
        row.update({f"predicted_{predicted_label}": confusion_matrix[true_label].get(predicted_label, 0) for predicted_label in labels})
        rows.append(row)
    return rows


def statistical_method_rows(confirmatory_report: dict[str, Any], method_names: list[str]) -> list[dict[str, Any]]:
    rows = []
    for name in method_names:
        entry = confirmatory_report.get(name) or {}
        rows.append({"method": name, "status": entry.get("status"), "detail": entry.get("detail"), "value": json.dumps(entry.get("value")) if entry.get("value") is not None else None})
    return rows


def rq2_result_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for branch in report.get("branches", []):
        rows.append({
            "branch": branch.get("branch"), "analysis_role": branch.get("analysis_role"), "evaluation_domain": branch.get("evaluation_domain"),
            "balanced_accuracy": branch.get("balanced_accuracy"), "macro_f1": branch.get("macro_f1"), "coverage": branch.get("coverage"),
            "serialized_model_size_bytes": branch.get("serialized_model_size_bytes"), "inference_latency_ms": branch.get("inference_latency_ms"),
            "model_bundle_id": branch.get("model_bundle_id"),
        })
    return rows


def rq4_result_rows(rq4_report: dict[str, Any]) -> list[dict[str, Any]]:
    """DEVELOPMENT_EXPLORATORY FULL_BURST vs PRE_PDU analytical-region
    control -- distinct from the still-not-executed RQ4 packet-condition
    intervention (no CSV/figure exists for that one; it has no data yet)."""
    rows: list[dict[str, Any]] = []
    for key in ("full_burst", "pre_pdu"):
        block = rq4_report.get(key) or {}
        ci = block.get("balanced_accuracy_ci") or {}
        rows.append({
            "region": block.get("label", key), "balanced_accuracy": block.get("balanced_accuracy"),
            "ci_low": ci.get("ci_low"), "ci_high": ci.get("ci_high"), "macro_f1": block.get("macro_f1"),
            "accuracy": block.get("accuracy"), "n_examples": block.get("n_examples"), "n_sessions": block.get("n_sessions"),
            "training_run_id": block.get("training_run_id"),
        })
    delta = rq4_report.get("delta") or {}
    rows.append({
        "region": "delta (full_burst - pre_pdu)", "balanced_accuracy": delta.get("point_estimate"),
        "ci_low": delta.get("ci_low"), "ci_high": delta.get("ci_high"),
    })
    return rows


def feature_group_ablation_result_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """DEVELOPMENT_EXPLORATORY feature-group ablation (FULL vs.
    POWER_AMPLITUDE_LEVEL vs. REMAINING_SIX) -- one row per condition with
    its metrics, plus one row per recall_per_class entry (pseudonym label
    applied for the `physical_unit` column only; the row's own
    `physical_unit_id` column keeps the real internal id)."""
    rows: list[dict[str, Any]] = []
    for condition, block in (report.get("results") or {}).items():
        ci = block.get("balanced_accuracy_ci") or {}
        base_row = {
            "condition": condition, "balanced_accuracy": block.get("balanced_accuracy"),
            "ci_low": ci.get("ci_low"), "ci_high": ci.get("ci_high"), "macro_f1": block.get("macro_f1"),
            "accuracy": block.get("accuracy"), "n_examples": block.get("n_comparable_to_known_classes") or block.get("n_examples"),
        }
        for unit, recall in (block.get("recall_per_class") or {}).items():
            rows.append({
                **base_row, "physical_unit_id": unit, "physical_unit_pseudonym": PHYSICAL_UNIT_PSEUDONYM_LABELS.get(unit, unit), "recall": recall,
            })
    return rows


def session_stability_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per real (physical_unit_id, session_id) pair -- purely
    descriptive session-level breakdown over PRIMARY's own VALIDATION
    predictions, never a retrained model or a causal estimate."""
    rows: list[dict[str, Any]] = []
    for session in report.get("sessions") or []:
        row = {
            "physical_unit_pseudonym": session.get("physical_unit_pseudonym"), "physical_unit_id": session.get("physical_unit_id"),
            "session_id": session.get("session_id"), "n_examples": session.get("n_examples"),
            "recall": session.get("recall"), "accuracy": session.get("accuracy"),
            "median_correct_class_score": session.get("median_correct_class_score"),
            "top_competing_class": session.get("top_competing_class"), "top_competing_class_share": session.get("top_competing_class_share"),
        }
        for fname, value in (session.get("feature_medians") or {}).items():
            row[f"median_{fname}"] = value
        rows.append(row)
    return rows


def channel_transport_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"channel": row.get("channel"), "center_frequency_hz": row.get("center_frequency_hz"), "bundle_id": row.get("frozen_bundle_id"),
         "windows": row.get("windows"), "balanced_accuracy": row.get("balanced_accuracy"), "macro_f1": row.get("macro_f1"), "coverage": row.get("coverage")}
        for row in report.get("per_channel", [])
    ]


def offline_nearlive_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        {"category": "pairing", "metric": "matched_pair_count", "value": report.get("matched_pair_count")},
        {"category": "pairing", "metric": "unpaired_offline_count", "value": report.get("unpaired_offline_count")},
        {"category": "pairing", "metric": "unpaired_nearlive_count", "value": report.get("unpaired_nearlive_count")},
    ]
    agreement = report.get("analytical_agreement") or {}
    for key, value in agreement.items():
        rows.append({"category": "analytical_agreement", "metric": key, "value": value})
    for key, value in (report.get("computational_behavior") or {}).items():
        rows.append({"category": "computational_behavior", "metric": key, "value": value})
    return rows


def tx_composition_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"physical_unit_id": r.get("physical_unit_id"), "device_family": r.get("device_family"), "manufacturer": r.get("manufacturer"),
         "model": r.get("model"), "project_id": r.get("project_id"), "status": r.get("status"), "rq4_eligibility": r.get("rq4_eligibility"),
         "real_capture_count": r.get("real_capture_count"), "channels": ",".join(str(c) for c in (r.get("channels") or [])),
         "day_first": (r.get("day_range") or {}).get("first"), "day_last": (r.get("day_range") or {}).get("last")}
        for r in rows
    ]


def partition_composition_rows(table: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for domain in ("TRAIN", "VALIDATION", "TEST"):
        counts = table.get("domains", {}).get(domain, {})
        # n_examples (renamed 2026-08-17, was n_windows): real ExampleRecord
        # count from SplitManifest.assignments -- NOT a 10-second decision-
        # window count (see coverage_analysis_report.json's
        # domain_resolution_diagnostic for that, a separate real number).
        rows.append({"domain": domain, "n_examples": counts.get("n_examples"), "n_captures": counts.get("n_captures"), "n_sessions": counts.get("n_sessions")})
    return rows


def receiver_epoch_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"receiver_epoch": r.get("receiver_epoch"), "boundary_reason": r.get("boundary_reason"), "n_captures": r.get("n_captures"),
         "day_ids": ",".join(r.get("day_ids") or []), "channels": ",".join(str(c) for c in (r.get("channels") or [])),
         "physical_units": ",".join(r.get("physical_units") or [])}
        for r in rows
    ]


def scientific_completeness_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"item": item.get("item"), "status": item.get("status"), "reason": item.get("reason"), "missing_evidence": "; ".join(item.get("missing_evidence") or [])}
        for item in report.get("items", [])
    ]


def per_transmitter_rows(
    recall: dict[str, float] | None, precision: dict[str, float] | None, f1: dict[str, float] | None,
    confusion_matrix: dict[str, dict[str, int]] | None = None,
) -> list[dict[str, Any]]:
    """One row per real transmitter -- never a single pooled BA hiding
    per-source spread. Any of the three may be None/absent for a unit
    (never a fabricated 0). `n` (2026-08-17): the unit's real true-class row
    total from the SAME confusion matrix already exported alongside this
    table -- never a second count, never a bootstrap (per-unit CI is not
    computed yet; deliberately left absent rather than a fabricated one)."""
    units = sorted(set((recall or {}).keys()) | set((precision or {}).keys()) | set((f1 or {}).keys()))
    return [
        {
            "physical_unit_id": u, "recall": (recall or {}).get(u), "precision": (precision or {}).get(u), "f1": (f1 or {}).get(u),
            "n": sum((confusion_matrix or {}).get(u, {}).values()) if confusion_matrix and u in confusion_matrix else None,
        }
        for u in units
    ]


def decision_window_rows(coverage_report: dict[str, Any], branch: str) -> list[dict[str, Any]]:
    """One row per real 10-second decision window (decided AND abstained) --
    true TX/predicted TX/score/decision-abstention/burst_count, read
    verbatim from `06_statistics/coverage_analysis_report.json`'s own
    `window_level_evaluation[branch].decision_windows` (produced by
    run_coverage_analysis(evaluate_window_level=True)) -- never
    recomputed here."""
    branch_eval = (coverage_report.get("window_level_evaluation") or {}).get(branch) or {}
    return list(branch_eval.get("decision_windows") or [])


def window_level_risk_coverage_rows(coverage_report: dict[str, Any], branch: str) -> list[dict[str, Any]]:
    """One row per real point on the decision-window-level risk-coverage
    curve, across every real evaluation domain -- `risk` is the real
    selective_error (El-Yaniv & Wiener, 2010), `n_decided`/`n_abstained` are
    the real integer counts behind the coverage ratio. Read verbatim from
    the same coverage_analysis_report.json, never recomputed."""
    branch_eval = (coverage_report.get("window_level_evaluation") or {}).get(branch) or {}
    rows: list[dict[str, Any]] = []
    for domain, domain_eval in sorted((branch_eval.get("by_evaluation_domain") or {}).items()):
        for point in domain_eval.get("risk_coverage") or []:
            rows.append({
                "evaluation_domain": domain, "evidence_maturity": domain_eval.get("evidence_maturity"),
                "coverage": point.get("coverage"), "selective_error": point.get("risk"), "threshold": point.get("threshold"),
                "n_decided": point.get("n_decided"), "n_abstained": point.get("n_abstained"),
            })
    return rows


def development_decision_window_summary_rows(coverage_report: dict[str, Any], branch: str) -> list[dict[str, Any]]:
    """One row per real partition (TRAIN/VALIDATION/TEST) at 10-second
    decision-window granularity -- read verbatim from the SAME
    `06_statistics/coverage_analysis_report.json` `window_level_evaluation`
    the Coverage tab already renders (never a second decision-window
    evaluation). `n_per_tx`/`accuracy`/`n_decided` are pure arithmetic over
    that domain's own already-real confusion matrix (row-sum / trace /
    total), the exact same idiom `per_transmitter_rows` already uses --
    never a second metric definition. `n_abstained`/`coverage` come from
    coverage_analysis_report.json's own top-level `by_evaluation_domain`
    (pooled across every real branch scored, not just this one -- the same
    real number as the Coverage tab's top summary cards; with a single real
    branch today the two scopes coincide). DEVELOPMENT evidence_status --
    never labeled confirmatory/definitive/FUTURE here."""
    branch_eval = (coverage_report.get("window_level_evaluation") or {}).get(branch) or {}
    by_domain_window = branch_eval.get("by_evaluation_domain") or {}
    by_domain_coarse = coverage_report.get("by_evaluation_domain") or {}
    rows = []
    for domain in ("TRAIN", "VALIDATION", "TEST"):
        window_eval = by_domain_window.get(domain)
        if not window_eval:
            continue
        matrix = window_eval.get("confusion_matrix") or {}
        n_decided = sum(sum(row.values()) for row in matrix.values())
        n_correct = sum(matrix.get(unit, {}).get(unit, 0) for unit in matrix)
        n_per_tx = {unit: sum(matrix.get(unit, {}).values()) for unit in matrix}
        coarse = by_domain_coarse.get(domain) or {}
        rows.append({
            "partition": domain, "n_windows": window_eval.get("n_comparable"), "n_per_tx": json.dumps(n_per_tx),
            "balanced_accuracy": window_eval.get("balanced_accuracy"), "accuracy": (n_correct / n_decided) if n_decided else None,
            "n_decided": n_decided, "n_abstained": coarse.get("abstained_windows"), "coverage": coarse.get("coverage"),
            "evaluation_unit": "DECISION_WINDOW", "window_duration_s": coverage_report.get("window_duration_s"), "evidence_status": "DEVELOPMENT",
        })
    return rows


def render_latex_tables(sections: dict[str, list[dict[str, Any]]]) -> str:
    """Minimal, dependency-free LaTeX table templating -- one `table`
    environment per non-empty section. Never called with a section whose
    rows the caller didn't already confirm are real."""
    lines = ["% Auto-generated by paper_export.py -- real data only, regenerate via the paper export tab.", ""]
    for label, rows in sections.items():
        if not rows:
            continue
        columns = list(rows[0].keys())
        lines.append(f"\\begin{{table}}[htbp]\\centering\\caption{{{label}}}\\label{{tab:{label}}}")
        lines.append("\\begin{tabular}{" + "l" * len(columns) + "}\\toprule")
        lines.append(" & ".join(columns) + " \\\\\\midrule")
        for row in rows:
            lines.append(" & ".join(str(row.get(c, "")).replace("_", "\\_") for c in columns) + " \\\\")
        lines.append("\\bottomrule\\end{tabular}\\end{table}")
        lines.append("")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Orchestration: real filesystem reads, decides GENERATED vs SKIPPED_NO_DATA.
# ----------------------------------------------------------------------

def _read_json(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _most_recent_run_dir(repository: Any) -> Path | None:
    """Only a directory with a real `run.json` (the same marker
    `ScientificResultsRepository.list_runs()` uses) counts as a paper run --
    NOT any other subdirectory of the repository root (e.g. `logs/`, whose
    mtime can outrace a real run directory's and previously caused this
    function to silently pick the wrong -- non-run -- directory). Ranked by
    the run's own declared `created_at`, never filesystem mtime."""
    run_json_paths = sorted(repository.root.glob("*/run.json"))
    if not run_json_paths:
        return None
    best_path, best_created_at = None, ""
    for path in run_json_paths:
        created_at = json.loads(path.read_text(encoding="utf-8")).get("created_at", "")
        if created_at >= best_created_at:
            best_path, best_created_at = path, created_at
    return best_path.parent


def generate_paper_exports(repository: Any) -> dict[str, Any]:
    exports_dir = repository.root / "paper_exports"
    figures_dir = exports_dir / "figures"
    exports_dir.mkdir(parents=True, exist_ok=True)

    study_status = repository.get_study_status()
    atomic_json(exports_dir / "study_status.json", study_status)
    readiness = repository.get_paper_readiness()
    atomic_json(exports_dir / "paper_readiness.json", {"generated_at": _utc_now(), "elements": readiness})

    entries: list[dict[str, Any]] = [
        {"file": "study_status.json", "status": "GENERATED", "detail": "real, from get_study_status()"},
        {"file": "paper_readiness.json", "status": "GENERATED", "detail": "real, from get_paper_readiness()"},
    ]
    # Figure/artifact sync closure (2026-08-18): one manifest row per
    # scientific figure, real provenance only -- see figure_manifest.json
    # below. Built alongside `entries` (never a second pass over the
    # filesystem to reconstruct what was just generated).
    figure_manifest_entries: list[dict[str, Any]] = []

    def emit(
        filename: str, outcome: ExportOutcome, *, classification: str | None = None, provenance: dict[str, Any] | None = None,
        figure_source: tuple[str, str, str, str] | None = None,
    ) -> None:
        entry = {"file": filename, "status": outcome.status, "detail": outcome.detail}
        if outcome.would_be_derived_from:
            entry["would_be_derived_from"] = outcome.would_be_derived_from
        # Paper-representation pass (2026-08-17): PAPER_PRIMARY/SUPPLEMENTARY/
        # DIAGNOSTIC classification + a real provenance stamp (protocol/
        # dataset/split identity, git_sha, etc, built from fields already on
        # the source report -- never re-derived) -- both optional so every
        # pre-existing emit() call above stays valid unchanged.
        if classification:
            entry["figure_classification"] = classification
        if provenance:
            entry["provenance"] = provenance
            atomic_json(exports_dir / f"{filename}.provenance.json", provenance)
        # figure_source = (source_artifact relpath under repository.root,
        # evaluation_unit, evidence_status, generator) -- ONLY passed by callers
        # rendering a real scientific figure via a real canonical artifact
        # (RQ1/RQ2 today). sha256 is computed here, once, from the real
        # bytes on disk at generation time -- never a second hash source,
        # never fabricated when the source file is somehow missing (raises
        # instead, since a GENERATED figure with no readable source artifact
        # is a real bug, not a SKIPPED_NO_DATA case).
        if figure_source and outcome.status == "GENERATED":
            source_artifact, evaluation_unit, evidence_status, generator = figure_source
            source_path = repository.root / source_artifact
            source_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
            figure_manifest_entries.append({
                "figure_path": f"figures/{Path(filename).name.rsplit('.', 1)[0]}.png",
                "source_artifact": source_artifact, "source_artifact_sha256": source_sha256,
                "paper_run_id": run_dir.name if run_dir else None, "evaluation_unit": evaluation_unit, "evidence_status": evidence_status,
                "generator": generator, "generator_commit": study_status.get("git_sha"), "generated_at": _utc_now(),
            })
        entries.append(entry)

    # --- Repo-root-scoped exports (no paper_run_id needed) ---
    preflight = _read_json(repository.root / "campaign_qualification_preflight_report.json")
    if preflight is not None:
        _write_csv(exports_dir / "qualification_summary.csv", qualification_summary_rows(preflight))
        emit("qualification_summary.csv", ExportOutcome("GENERATED", "real, from campaign_qualification_preflight_report.json"))
    else:
        emit("qualification_summary.csv", ExportOutcome("SKIPPED_NO_DATA", "no campaign_qualification_preflight_report.json on disk", "campaign_qualification_preflight_report.json"))

    guided_validation_dir = repository.root / "guided_validation"
    calibration_attempts = []
    if guided_validation_dir.is_dir():
        for path in sorted(guided_validation_dir.glob("*/association_policy.json")):
            data = _read_json(path)
            if data is not None:
                calibration_attempts.append(data)
    if calibration_attempts:
        _write_csv(exports_dir / "association_summary.csv", association_summary_rows(calibration_attempts))
        emit("association_summary.csv", ExportOutcome("GENERATED", f"real, from {len(calibration_attempts)} calibration attempt(s)"))
    else:
        emit("association_summary.csv", ExportOutcome("SKIPPED_NO_DATA", "no guided_validation/*/association_policy.json on disk", "guided_validation/*/association_policy.json"))

    # dataset/exclusions summaries need a real paper run's canonical records.
    run_dir = _most_recent_run_dir(repository)
    # Reuses get_evidence_dashboard_summary() (already real, already tested,
    # discriminates the closed-set MULTI_DEVICE_CLASSIFICATION run from the
    # per-unit TARGET_VS_BACKGROUND auxiliary runs via list_runs()) as the
    # SINGLE data source for every new table/figure below -- never a second
    # run-selection logic, never a second independent computation. Computed
    # here (moved up from its previous, later position) so the RQ1 figure
    # block below can use it too, once `run_dir` above happens to be the
    # SAME real run (checked explicitly, never assumed).
    dashboard = repository.get_evidence_dashboard_summary()
    closed_set = dashboard.get("closed_set")
    base_provenance = {"protocol_id": dashboard.get("protocol_id"), "protocol_version": dashboard.get("protocol_version"),
                        "contract_sha256": dashboard.get("contract_sha256"), "git_sha": dashboard.get("git_sha")}
    # None unless `run_dir` (whatever paper run is most recent) IS the real
    # closed-set run `dashboard` resolved -- guards every RQ1-figure
    # enhancement below from mixing two different runs' data.
    closed_set_for_run_dir = closed_set if (closed_set and run_dir and closed_set.get("paper_run_id") == run_dir.name) else None
    canonical_dir = (run_dir / "01_inputs" / "canonical_records") if run_dir else None
    captures_payload = _read_json(canonical_dir / "capture_records.json") if canonical_dir else None
    if captures_payload:
        rows = [{"capture_id": c.get("capture_id"), "physical_unit_id": c.get("physical_unit_id"), "day_id": c.get("day_id"), "channel": c.get("channel")} for c in captures_payload]
        _write_csv(exports_dir / "dataset_summary.csv", rows)
        emit("dataset_summary.csv", ExportOutcome("GENERATED", f"real, from {run_dir.name}/01_inputs/canonical_records/capture_records.json"))
    else:
        emit("dataset_summary.csv", ExportOutcome("SKIPPED_NO_DATA", "no canonical capture_records.json for any real paper run", "01_inputs/canonical_records/capture_records.json"))

    deviations_payload = _read_json(canonical_dir / "campaign_deviations.json") if canonical_dir else None
    if deviations_payload:
        rows = [{"deviation_type": d.get("deviation_type"), "classification": d.get("classification"), "severity": d.get("severity")} for d in deviations_payload]
        _write_csv(exports_dir / "exclusions_summary.csv", rows)
        emit("exclusions_summary.csv", ExportOutcome("GENERATED", f"real, from {run_dir.name}/01_inputs/canonical_records/campaign_deviations.json"))
    else:
        emit("exclusions_summary.csv", ExportOutcome("SKIPPED_NO_DATA", "no canonical campaign_deviations.json for any real paper run", "01_inputs/canonical_records/campaign_deviations.json"))

    # --- Run-scoped statistics/RQ exports ---
    rq1_report = repository.get_rq1_acquisition_dependence_report(run_dir.name) if run_dir else None
    if rq1_report:
        _write_csv(exports_dir / "rq1_results.csv", rq1_result_rows(rq1_report))
        emit("rq1_results.csv", ExportOutcome("GENERATED", f"real, from {run_dir.name}/06_statistics/rq1_acquisition_dependence_report.json"))
        rq1_source_artifact = f"{run_dir.name}/06_statistics/rq1_acquisition_dependence_report.json" if run_dir else "06_statistics/rq1_acquisition_dependence_report.json"
        if rq1_report.get("ba_window") is not None and rq1_report.get("ba_capture") is not None:
            # Label fix (2026-08-18, figure/artifact sync closure): this is
            # now the ONLY renderer for this figure -- readme_img/evidence_
            # rq1_domains.png is a plain copy of the PNG this call writes
            # (see docs/ble/generate_evidence_figures.py's CONSOLIDATED_
            # FIGURES), never a second, independently-coded renderer. Labels
            # never say "BA_window"/"BA_capture" (the raw JSON field names,
            # which read as if they were the platform's separate 10-second
            # decision-window unit -- they are not; evaluation_unit below is
            # always EXAMPLE_RECORD for every bar here). capture-dependent ->
            # capture-disjoint -> Held-out TEST -> protected FUTURE (only
            # once it exists -- never mislabeled as FUTURE before then).
            # Both point estimates get their own real, persisted CI (rq1_
            # runner.py's 2026-08-17 pass added ba_window_ci specifically
            # because the capture-dependent diagnostic being intentionally
            # leakage-optimistic does not make its own resampling
            # uncertainty any less real or reportable -- fixed 2026-08-19,
            # this renderer had been silently dropping it).
            domains = ["Capture-dependent diagnostic\n(same capture)", "Capture-disjoint\n(VALIDATION)"]
            values = [rq1_report["ba_window"], rq1_report["ba_capture"]]
            ba_window_ci = (rq1_report.get("uncertainty_ci") or {}).get("ba_window_ci") or {}
            ba_capture_ci = (rq1_report.get("uncertainty_ci") or {}).get("ba_capture_ci") or {}
            ci_low: list[float | None] = [ba_window_ci.get("ci_low"), ba_capture_ci.get("ci_low")]
            ci_high: list[float | None] = [ba_window_ci.get("ci_high"), ba_capture_ci.get("ci_high")]
            footnote_parts = []
            if closed_set_for_run_dir and closed_set_for_run_dir.get("primary_test", {}).get("balanced_accuracy") is not None:
                domains.append("Held-out same-campaign\nTEST")
                values.append(closed_set_for_run_dir["primary_test"]["balanced_accuracy"])
                ci_low.append(None)
                ci_high.append(None)
            if rq1_report.get("ba_future") is not None:
                domains.append(f"protected FUTURE\n({rq1_report.get('ba_future_status')})")
                values.append(rq1_report["ba_future"])
                ci_low.append(None)
                ci_high.append(None)
            # n (examples, NOT decision windows -- see evaluation_unit on the
            # persisted RQ1 report): RQ1's OWN real per-domain comparable-
            # example counts (never re-derived from the split -- avoids two
            # independent counting paths that could silently disagree).
            # n_captures: distinct real acquisition groups from the
            # closed-set VALIDATION/TEST split (RQ1's own report carries no
            # capture-level count).
            evaluation_unit = rq1_report.get("evaluation_unit") or "EXAMPLE_RECORD"
            footnote_parts.append(f"evaluation_unit={evaluation_unit}")
            if rq1_report.get("ba_window_n_comparable") is not None:
                footnote_parts.append(f"capture-dependent n={rq1_report['ba_window_n_comparable']}")
            if rq1_report.get("ba_capture_n_comparable") is not None:
                footnote_parts.append(f"capture-disjoint n={rq1_report['ba_capture_n_comparable']}")
            delta = rq1_report.get("delta_dependence")
            if delta is not None:
                delta_ci = (rq1_report.get("uncertainty_ci") or {}).get("delta_dependence_ci") or {}
                delta_ci_low, delta_ci_high = delta_ci.get("ci_low"), delta_ci.get("ci_high")
                if delta_ci_low is not None and delta_ci_high is not None:
                    footnote_parts.append(f"delta_dependence={delta:+.3f} 95% CI [{delta_ci_low:.3f}, {delta_ci_high:.3f}]")
                else:
                    footnote_parts.append(f"delta_dependence={delta:+.3f}")
            if closed_set_for_run_dir:
                partition_table = repository.build_partition_composition_table(
                    closed_set_for_run_dir["dataset_id"], closed_set_for_run_dir["dataset_version"], "MULTI_DEVICE_CLASSIFICATION",
                )
                domains_counts = partition_table["domains"]
                footnote_parts.append(
                    f"VALIDATION: {domains_counts['VALIDATION']['n_captures']} captures"
                    f"  ·  TEST: {domains_counts['TEST']['n_captures']} captures"
                )
            paper_figures.bar_with_ci_figure(
                categories=domains, values=values, ci_low=ci_low, ci_high=ci_high, ylabel="Balanced accuracy",
                title="RQ1 -- BA by evaluation domain (DEVELOPMENT EVIDENCE -- not definitive, not confirmatory, not protected FUTURE)",
                out_path=figures_dir / "rq1_acquisition_dependence.pdf",
                footnote=" | ".join(footnote_parts) or None,
            )
            emit(
                "figures/rq1_acquisition_dependence.pdf", ExportOutcome("GENERATED", "real"),
                figure_source=(rq1_source_artifact, evaluation_unit, rq1_report.get("evidence_status") or "DEVELOPMENT", "figures/paper_figures.py::bar_with_ci_figure"),
            )
            # Publication-figure variant (2026-08-19, methodological audit
            # item 7): SAME real domains/values/ci_low/ci_high the internal
            # figure above just plotted -- never a second computation --
            # rendered without the DEVELOPMENT-EVIDENCE caption/footnote text
            # or per-domain n/CI numbers baked into the image itself (those
            # stay real and inspectable in rq1_acquisition_dependence_report.
            # json and this figure's own figure_manifest.json entry, just not
            # burned into the pixels). Fixed [0,1] y-axis so bar heights are
            # visually comparable across figures; real error bars kept
            # (RQ1's CIs ARE canonical/persisted, unlike RQ2's -- see below).
            paper_figures.bar_with_ci_figure(
                categories=domains, values=values, ci_low=ci_low, ci_high=ci_high, ylabel="Balanced accuracy",
                title="RQ1 -- Balanced accuracy by evaluation domain", ylim=(0.0, 1.0),
                out_path=figures_dir / "rq1_acquisition_dependence_publication",
            )
            emit(
                "figures/rq1_acquisition_dependence_publication.pdf", ExportOutcome("GENERATED", "real, publication variant of figures/rq1_acquisition_dependence.pdf (same data, no caption/footnote text)"),
                figure_source=(rq1_source_artifact, evaluation_unit, rq1_report.get("evidence_status") or "DEVELOPMENT", "figures/paper_figures.py::bar_with_ci_figure"),
            )
        else:
            emit("figures/rq1_acquisition_dependence.pdf", ExportOutcome("SKIPPED_NO_DATA", "rq1_acquisition_dependence_report.json is missing ba_window/ba_capture", "06_statistics/rq1_acquisition_dependence_report.json"))
            emit("figures/rq1_acquisition_dependence_publication.pdf", ExportOutcome("SKIPPED_NO_DATA", "rq1_acquisition_dependence_report.json is missing ba_window/ba_capture", "06_statistics/rq1_acquisition_dependence_report.json"))
        if rq1_report.get("confusion_matrix_capture"):
            _write_csv(exports_dir / "confusion_matrix_capture.csv", confusion_matrix_rows(rq1_report["confusion_matrix_capture"]))
            emit("confusion_matrix_capture.csv", ExportOutcome("GENERATED", "real, from rq1_acquisition_dependence_report.json"))
            _emit_confusion_matrix_figure(emit, rq1_report["confusion_matrix_capture"], "figures/rq1_confusion_matrix_capture.pdf", figures_dir / "rq1_confusion_matrix_capture.pdf", "RQ1 -- confusion matrix (capture-disjoint)")
        else:
            emit("confusion_matrix_capture.csv", ExportOutcome("SKIPPED_NO_DATA", "rq1_acquisition_dependence_report.json has no confusion_matrix_capture", "06_statistics/rq1_acquisition_dependence_report.json"))
            emit("figures/rq1_confusion_matrix_capture.pdf", ExportOutcome("SKIPPED_NO_DATA", "rq1_acquisition_dependence_report.json has no confusion_matrix_capture", "06_statistics/rq1_acquisition_dependence_report.json"))
        if rq1_report.get("confusion_matrix_future"):
            _write_csv(exports_dir / "confusion_matrix_future.csv", confusion_matrix_rows(rq1_report["confusion_matrix_future"]))
            emit("confusion_matrix_future.csv", ExportOutcome("GENERATED", "real, from rq1_acquisition_dependence_report.json"))
            _emit_confusion_matrix_figure(emit, rq1_report["confusion_matrix_future"], "figures/rq1_confusion_matrix_future.pdf", figures_dir / "rq1_confusion_matrix_future.pdf", "RQ1 -- confusion matrix (protected FUTURE)")
        else:
            emit("confusion_matrix_future.csv", ExportOutcome("SKIPPED_NO_DATA", "rq1_acquisition_dependence_report.json has no confusion_matrix_future", "06_statistics/rq1_acquisition_dependence_report.json"))
            emit("figures/rq1_confusion_matrix_future.pdf", ExportOutcome("SKIPPED_NO_DATA", "rq1_acquisition_dependence_report.json has no confusion_matrix_future", "06_statistics/rq1_acquisition_dependence_report.json"))
        scored_units = {unit: v.get("recall") for unit, v in (rq1_report.get("per_unit_recall") or {}).items() if v.get("recall") is not None}
        if scored_units:
            paper_figures.bar_with_ci_figure(
                categories=list(scored_units.keys()), values=list(scored_units.values()),
                ci_low=None, ci_high=None, ylabel="Recall", title="RQ1 -- per-unit recall", out_path=figures_dir / "rq1_per_unit_recall.pdf",
            )
            emit("figures/rq1_per_unit_recall.pdf", ExportOutcome("GENERATED", "real"))
        else:
            emit("figures/rq1_per_unit_recall.pdf", ExportOutcome("SKIPPED_NO_DATA", "rq1_acquisition_dependence_report.json has no per-unit recall values", "06_statistics/rq1_acquisition_dependence_report.json"))
    else:
        for name in (
            "rq1_results.csv", "figures/rq1_acquisition_dependence.pdf", "figures/rq1_acquisition_dependence_publication.pdf",
            "confusion_matrix_capture.csv", "confusion_matrix_future.csv",
            "figures/rq1_per_unit_recall.pdf", "figures/rq1_confusion_matrix_capture.pdf", "figures/rq1_confusion_matrix_future.pdf",
        ):
            emit(name, ExportOutcome("SKIPPED_NO_DATA", "no rq1_acquisition_dependence_report.json for any real paper run", "06_statistics/rq1_acquisition_dependence_report.json"))

    rq2_report = repository.get_rq2_representation_comparison_report(run_dir.name) if run_dir else None
    rq2_source = "06_statistics/rq2_representation_comparison_report.json"
    if rq2_report and rq2_report.get("branches"):
        _write_csv(exports_dir / "rq2_results.csv", rq2_result_rows(rq2_report))
        emit("rq2_results.csv", ExportOutcome("GENERATED", f"real, from {run_dir.name}/{rq2_source}"))
        scored_branches = [b for b in rq2_report["branches"] if b.get("balanced_accuracy") is not None]
        if scored_branches:
            paper_figures.bar_with_ci_figure(
                categories=[f"{b['branch']} ({b['analysis_role']})" for b in scored_branches], values=[b["balanced_accuracy"] for b in scored_branches],
                ci_low=None, ci_high=None, ylabel="Balanced accuracy", title="RQ2 -- representation comparison",
                out_path=figures_dir / "rq2_representation_comparison.pdf",
            )
            emit(
                "figures/rq2_representation_comparison.pdf", ExportOutcome("GENERATED", "real"),
                figure_source=(f"{run_dir.name}/{rq2_source}", rq2_report.get("evaluation_unit") or "EXAMPLE_RECORD", rq2_report.get("evidence_status") or "DEVELOPMENT", "figures/paper_figures.py::bar_with_ci_figure"),
            )
            # Publication-figure variant (2026-08-19, methodological audit
            # item 7): human-readable branch labels (RQ2_BRANCH_PUBLICATION_
            # LABELS) instead of the internal snake_case branch key +
            # "(UNSELECTED)" suffix -- PRIMARY vs UNSELECTED is instead
            # conveyed by bar color (amber=PRIMARY, grey=UNSELECTED), fixed
            # [0,1] y-axis, no footnote. Point estimates only, never a
            # fabricated error bar: no branch in this canonical report
            # carries a real balanced_accuracy_ci today (confirmed during
            # this audit -- this artifact predates the 2026-08-17 per-branch
            # CI addition to rq2_benchmark.py), so ci_low/ci_high stay None
            # here rather than silently claiming an uncertainty this
            # specific persisted report does not actually have.
            publication_categories = [RQ2_BRANCH_PUBLICATION_LABELS.get(b["branch"], b["branch"]) for b in scored_branches]
            publication_colors = ["#b9822c" if b.get("analysis_role") == "PRIMARY" else "#8892a0" for b in scored_branches]
            paper_figures.bar_with_ci_figure(
                categories=publication_categories, values=[b["balanced_accuracy"] for b in scored_branches],
                ci_low=None, ci_high=None, ylabel="Balanced accuracy", title="RQ2 -- Representation comparison (amber = PRIMARY)",
                ylim=(0.0, 1.0), colors=publication_colors, out_path=figures_dir / "rq2_representation_comparison_publication",
            )
            emit(
                "figures/rq2_representation_comparison_publication.pdf", ExportOutcome("GENERATED", "real, publication variant of figures/rq2_representation_comparison.pdf (same data, human-readable labels, no footnote)"),
                figure_source=(f"{run_dir.name}/{rq2_source}", rq2_report.get("evaluation_unit") or "EXAMPLE_RECORD", rq2_report.get("evidence_status") or "DEVELOPMENT", "figures/paper_figures.py::bar_with_ci_figure"),
            )
        else:
            emit("figures/rq2_representation_comparison.pdf", ExportOutcome("SKIPPED_NO_DATA", "no branch in rq2_representation_comparison_report.json has a real balanced_accuracy", rq2_source))
            emit("figures/rq2_representation_comparison_publication.pdf", ExportOutcome("SKIPPED_NO_DATA", "no branch in rq2_representation_comparison_report.json has a real balanced_accuracy", rq2_source))
        covered_branches = [b for b in rq2_report["branches"] if b.get("coverage") is not None]
        if covered_branches:
            paper_figures.bar_with_ci_figure(
                categories=[f"{b['branch']} ({b['analysis_role']})" for b in covered_branches], values=[b["coverage"] for b in covered_branches],
                ci_low=None, ci_high=None, ylabel="Coverage", title="RQ2 -- coverage by branch",
                out_path=figures_dir / "rq2_coverage.pdf",
            )
            emit("figures/rq2_coverage.pdf", ExportOutcome("GENERATED", "real"))
        else:
            emit("figures/rq2_coverage.pdf", ExportOutcome("SKIPPED_NO_DATA", "no branch in rq2_representation_comparison_report.json has a real coverage value", rq2_source))
    else:
        for name in ("rq2_results.csv", "figures/rq2_representation_comparison.pdf", "figures/rq2_representation_comparison_publication.pdf", "figures/rq2_coverage.pdf"):
            emit(name, ExportOutcome("SKIPPED_NO_DATA", "no rq2_representation_comparison_report.json for any real paper run", rq2_source))

    # RQ4 exploratory analytical-region control (FULL_BURST vs PRE_PDU) --
    # a real, already-executed contrast, distinct from the still-not-executed
    # RQ4 packet-condition intervention (no export exists for that one; it
    # has no real data). PRE_PDU is an independent TRAIN-only re-fit; TEST
    # was not opened for either arm -- both facts are carried in the
    # footnote/caption below, never left implicit.
    rq4_report = repository.get_rq4_full_burst_vs_pre_pdu_exploratory_report(run_dir.name) if run_dir else None
    rq4_source = "06_statistics/rq4_full_burst_vs_pre_pdu_exploratory_report.json"
    if rq4_report and rq4_report.get("full_burst") and rq4_report.get("pre_pdu"):
        _write_csv(exports_dir / "rq4_full_burst_vs_pre_pdu_results.csv", rq4_result_rows(rq4_report))
        emit("rq4_full_burst_vs_pre_pdu_results.csv", ExportOutcome("GENERATED", f"real, from {run_dir.name}/{rq4_source}"))

        full_burst = rq4_report["full_burst"]
        pre_pdu = rq4_report["pre_pdu"]
        delta = rq4_report.get("delta") or {}
        categories = ["Full-burst", "Pre-PDU"]
        values = [full_burst.get("balanced_accuracy"), pre_pdu.get("balanced_accuracy")]
        full_ci = full_burst.get("balanced_accuracy_ci") or {}
        pre_ci = pre_pdu.get("balanced_accuracy_ci") or {}
        ci_low = [full_ci.get("ci_low"), pre_ci.get("ci_low")]
        ci_high = [full_ci.get("ci_high"), pre_ci.get("ci_high")]

        # Human-readable footnote (2026-08-24): the internal evaluation-unit/
        # evidence-status enum values stay in the source JSON and this
        # export's figure_manifest.json entry -- they are not repeated as
        # raw enum text in the figure itself, only as natural-language
        # sample-size/design facts a reader needs to interpret the bars.
        n_full, n_pre = full_burst.get("n_examples"), pre_pdu.get("n_examples")
        n_examples_text = f"{n_full:,} matched validation examples" if n_full == n_pre and n_full is not None else f"{n_full}/{n_pre} validation examples (full-burst/pre-PDU)"
        n_sessions_text = f"{full_burst.get('n_sessions')} acquisition sessions" if full_burst.get("n_sessions") == pre_pdu.get("n_sessions") else f"{full_burst.get('n_sessions')}/{pre_pdu.get('n_sessions')} acquisition sessions"
        footnote_parts = [
            n_examples_text, n_sessions_text,
            "Pre-PDU: independent TRAIN-only re-fit restricted to the pre-PDU region; TEST not opened for either arm",
        ]
        delta_low, delta_high = delta.get("ci_low"), delta.get("ci_high")
        if delta.get("point_estimate") is not None and delta_low is not None and delta_high is not None:
            footnote_parts.append(f"delta BA (full-burst - pre-PDU) = {delta['point_estimate']:.3f}, 95% CI [{delta_low:.3f}, {delta_high:.3f}]")

        paper_figures.bar_with_ci_figure(
            categories=categories, values=values, ci_low=ci_low, ci_high=ci_high, ylabel="Balanced accuracy",
            title="Exploratory VALIDATION comparison: full-burst vs pre-PDU",
            ylim=(0.0, 1.0), out_path=figures_dir / "rq4_full_burst_vs_pre_pdu",
            footnote=" | ".join(footnote_parts),
        )
        emit(
            "figures/rq4_full_burst_vs_pre_pdu.pdf", ExportOutcome("GENERATED", "real"),
            figure_source=(f"{run_dir.name}/{rq4_source}", "EXAMPLE_RECORD", rq4_report.get("evidence_status") or "DEVELOPMENT_EXPLORATORY", "figures/paper_figures.py::bar_with_ci_figure"),
        )

        recall_full = full_burst.get("recall_per_class") or {}
        recall_pre = pre_pdu.get("recall_per_class") or {}
        # Sorted by pseudonym label (TX-01, TX-03, TX-04, TX-05), not by the
        # internal physical_unit_id string, so the human-facing bar order is
        # the natural pseudonym order instead of an arbitrary alphabetical
        # one (CC2541SensorTag/CC2650-UNIT-01/keyfobdemo 01/keyfobdemo 02).
        units = sorted(recall_full.keys(), key=lambda u: PHYSICAL_UNIT_PSEUDONYM_LABELS.get(u, u))
        if units:
            # Pseudonym labels (2026-08-24): display-only -- categories below
            # are the human-facing figure labels; recall_full/recall_pre are
            # still indexed by the real physical_unit_id, never renamed.
            unit_labels = [PHYSICAL_UNIT_PSEUDONYM_LABELS.get(u, u) for u in units]
            paper_figures.grouped_bar_figure(
                categories=unit_labels, series=[[recall_full.get(u, 0) for u in units], [recall_pre.get(u, 0) for u in units]],
                series_labels=["Full-burst", "Pre-PDU"], series_colors=["#2b6cb0", "#b9822c"],
                ylabel="Recall (VALIDATION)", title="Exploratory VALIDATION comparison -- per-unit recall",
                ylim=(0.0, 1.05), out_path=figures_dir / "rq4_per_unit_recall", value_labels=True,
                footnote="Recall per enrolled transmitter under each analytical region; see the source artifact's confusion matrices for the full per-class breakdown.",
            )
            emit(
                "figures/rq4_per_unit_recall.pdf", ExportOutcome("GENERATED", "real"),
                figure_source=(f"{run_dir.name}/{rq4_source}", "EXAMPLE_RECORD", rq4_report.get("evidence_status") or "DEVELOPMENT_EXPLORATORY", "figures/paper_figures.py::grouped_bar_figure"),
            )
        else:
            emit("figures/rq4_per_unit_recall.pdf", ExportOutcome("SKIPPED_NO_DATA", "no per-unit recall_per_class in rq4_full_burst_vs_pre_pdu_exploratory_report.json", rq4_source))
    else:
        for name in ("rq4_full_burst_vs_pre_pdu_results.csv", "figures/rq4_full_burst_vs_pre_pdu.pdf", "figures/rq4_per_unit_recall.pdf"):
            emit(name, ExportOutcome("SKIPPED_NO_DATA", "no rq4_full_burst_vs_pre_pdu_exploratory_report.json for any real paper run", rq4_source))

    # Feature-group ablation (DEVELOPMENT_EXPLORATORY, 2026-08-24): FULL (10
    # engineered descriptors, reuses PRIMARY's own VALIDATION predictions --
    # no recomputation) vs. POWER_AMPLITUDE_LEVEL (4) vs. REMAINING_SIX (6),
    # all three scored on the identical VALIDATION population. Not a
    # model-improvement or model-selection exercise -- no tuning, no new
    # TRAIN/VALIDATION population, TEST never opened for either new fit.
    ablation_report = repository.get_feature_group_ablation_exploratory_report(run_dir.name) if run_dir else None
    ablation_source = "06_statistics/feature_group_ablation_exploratory_report.json"
    ablation_results = (ablation_report or {}).get("results") or {}
    if ablation_report and all(k in ablation_results for k in ("FULL", "POWER_AMPLITUDE_LEVEL", "REMAINING_SIX")):
        _write_csv(exports_dir / "feature_group_ablation_results.csv", feature_group_ablation_result_rows(ablation_report))
        emit("feature_group_ablation_results.csv", ExportOutcome("GENERATED", f"real, from {run_dir.name}/{ablation_source}"))

        full_r, power_r, remaining_r = ablation_results["FULL"], ablation_results["POWER_AMPLITUDE_LEVEL"], ablation_results["REMAINING_SIX"]
        categories = ["Full 10 descriptors", "Power/amplitude level (4)", "Remaining descriptors (6)"]
        values = [full_r.get("balanced_accuracy"), power_r.get("balanced_accuracy"), remaining_r.get("balanced_accuracy")]
        cis = [full_r.get("balanced_accuracy_ci") or {}, power_r.get("balanced_accuracy_ci") or {}, remaining_r.get("balanced_accuracy_ci") or {}]
        ci_low = [c.get("ci_low") for c in cis]
        ci_high = [c.get("ci_high") for c in cis]

        pop = ablation_report.get("population") or {}
        footnote_parts = [
            f"{pop.get('validation_n_examples')} matched validation examples, {pop.get('validation_n_sessions')} acquisition sessions (identical across all three conditions)",
            "Power/amplitude level and Remaining descriptors are independent TRAIN-only re-fits; Full reuses the existing PRIMARY model; TEST not opened for either new fit",
        ]
        contrasts = ablation_report.get("contrasts") or {}
        delta_ab = contrasts.get("FULL_minus_POWER_AMPLITUDE_LEVEL") or {}
        if delta_ab.get("point_estimate") is not None:
            footnote_parts.append(f"delta BA (Full - Power/amplitude) = {delta_ab['point_estimate']:.3f}, 95% CI [{delta_ab['ci_low']:.3f}, {delta_ab['ci_high']:.3f}]")
        delta_ac = contrasts.get("FULL_minus_REMAINING_SIX") or {}
        if delta_ac.get("point_estimate") is not None:
            footnote_parts.append(f"delta BA (Full - Remaining) = {delta_ac['point_estimate']:.3f}, 95% CI [{delta_ac['ci_low']:.3f}, {delta_ac['ci_high']:.3f}]")

        paper_figures.bar_with_ci_figure(
            categories=categories, values=values, ci_low=ci_low, ci_high=ci_high, ylabel="Balanced accuracy",
            title="Exploratory VALIDATION comparison: feature-group ablation",
            ylim=(0.0, 1.0), out_path=figures_dir / "feature_group_ablation",
            footnote=" | ".join(footnote_parts),
        )
        emit(
            "figures/feature_group_ablation.pdf", ExportOutcome("GENERATED", "real"),
            figure_source=(f"{run_dir.name}/{ablation_source}", "EXAMPLE_RECORD", ablation_report.get("evidence_status") or "DEVELOPMENT_EXPLORATORY", "figures/paper_figures.py::bar_with_ci_figure"),
        )
    else:
        for name in ("feature_group_ablation_results.csv", "figures/feature_group_ablation.pdf"):
            emit(name, ExportOutcome("SKIPPED_NO_DATA", "no feature_group_ablation_exploratory_report.json for any real paper run", ablation_source))

    # Session-stability analysis (DEVELOPMENT_EXPLORATORY, purely
    # descriptive, 2026-08-24): per-(physical_unit_id, session_id) recall
    # breakdown over PRIMARY's own real VALIDATION predictions -- no
    # retraining, no causal claim, TEST never opened.
    stability_report = repository.get_session_stability_analysis_report(run_dir.name) if run_dir else None
    stability_source = "06_statistics/session_stability_analysis_report.json"
    if stability_report and stability_report.get("sessions"):
        _write_csv(exports_dir / "session_stability_summary.csv", session_stability_rows(stability_report))
        emit("session_stability_summary.csv", ExportOutcome("GENERATED", f"real, from {run_dir.name}/{stability_source}"))

        sessions_by_unit: dict[str, list[dict[str, Any]]] = {}
        for session in stability_report["sessions"]:
            sessions_by_unit.setdefault(session["physical_unit_pseudonym"], []).append(session)
        pseudonym_order = sorted(sessions_by_unit, key=lambda p: p)
        categories = pseudonym_order
        values_per_category = [[s["recall"] for s in sessions_by_unit[p]] for p in pseudonym_order]

        paper_figures.strip_plot_figure(
            categories=categories, values_per_category=values_per_category, ylabel="Recall (per session)",
            title="Exploratory session-level recall by enrolled transmitter",
            ylim=(-0.02, 1.02), out_path=figures_dir / "session_stability",
            footnote="One point per real VALIDATION acquisition session (capture-disjoint domain), PRIMARY model, no retraining. Purely descriptive -- not a causal model of the TX/session confound.",
        )
        emit(
            "figures/session_stability.pdf", ExportOutcome("GENERATED", "real"),
            figure_source=(f"{run_dir.name}/{stability_source}", "EXAMPLE_RECORD", stability_report.get("evidence_status") or "DEVELOPMENT_EXPLORATORY", "figures/paper_figures.py::strip_plot_figure"),
        )
    else:
        for name in ("session_stability_summary.csv", "figures/session_stability.pdf"):
            emit(name, ExportOutcome("SKIPPED_NO_DATA", "no session_stability_analysis_report.json for any real paper run", stability_source))

    confirmatory_future = repository.get_confirmatory_future_analysis_report(run_dir.name) if run_dir else None
    sensitivity_source = repository.get_confirmatory_statistical_plan_report(run_dir.name) if run_dir else None
    _emit_confirmatory_derived_exports(emit, confirmatory_future, run_dir, exports_dir, figures_dir, validation_dry_run=sensitivity_source)

    if sensitivity_source and sensitivity_source.get("enrolled_population_class_exclusion_sensitivity", {}).get("status") == "EXECUTED":
        _write_csv(exports_dir / "sensitivity_results.csv", statistical_method_rows(sensitivity_source, ["enrolled_population_class_exclusion_sensitivity", "fixed_seed_variability"]))
        emit("sensitivity_results.csv", ExportOutcome("GENERATED", f"real, from {run_dir.name}/06_statistics/confirmatory_statistical_plan_report.json"))
    else:
        emit("sensitivity_results.csv", ExportOutcome("SKIPPED_NO_DATA", "no EXECUTED enrolled_population_class_exclusion_sensitivity in confirmatory_statistical_plan_report.json", "06_statistics/confirmatory_statistical_plan_report.json"))

    # --- S1/S2 engineering ---
    channel_transport = repository.get_channel_transport_report(run_dir.name) if run_dir else None
    if channel_transport:
        _write_csv(exports_dir / "channel_transport_results.csv", channel_transport_rows(channel_transport))
        emit("channel_transport_results.csv", ExportOutcome("GENERATED", f"real, from {run_dir.name}/06_statistics/channel_transport_report.json"))
        scored_channels = [row for row in channel_transport.get("per_channel", []) if row.get("balanced_accuracy") is not None]
        if scored_channels:
            paper_figures.bar_with_ci_figure(
                categories=[str(row["channel"]) for row in scored_channels], values=[row["balanced_accuracy"] for row in scored_channels],
                ci_low=None, ci_high=None, ylabel="Balanced accuracy", title="S1 -- bounded channel transport",
                out_path=figures_dir / "channel_transport.pdf",
            )
            emit("figures/channel_transport.pdf", ExportOutcome("GENERATED", "real"))
        else:
            emit("figures/channel_transport.pdf", ExportOutcome("SKIPPED_NO_DATA", "no channel in channel_transport_report.json has a real (non-None) balanced_accuracy", "06_statistics/channel_transport_report.json"))
    else:
        emit("channel_transport_results.csv", ExportOutcome("SKIPPED_NO_DATA", "no channel_transport_report.json for any real paper run", "06_statistics/channel_transport_report.json"))
        emit("figures/channel_transport.pdf", ExportOutcome("SKIPPED_NO_DATA", "no channel_transport_report.json for any real paper run", "06_statistics/channel_transport_report.json"))

    offline_nearlive = repository.get_offline_nearlive_report(run_dir.name) if run_dir else None
    if offline_nearlive and offline_nearlive.get("analytical_agreement"):
        _write_csv(exports_dir / "offline_nearlive_results.csv", offline_nearlive_rows(offline_nearlive))
        emit("offline_nearlive_results.csv", ExportOutcome("GENERATED", f"real, from {run_dir.name}/06_statistics/offline_nearlive_report.json"))
        latency = (offline_nearlive.get("computational_behavior") or {}).get("median_latency_ms")
        if isinstance(latency, (int, float)):
            emit("figures/offline_nearlive_latency.pdf", ExportOutcome("SKIPPED_NO_DATA", "latency ECDF needs a real distribution of samples, not just a median -- not yet supplied", "06_statistics/offline_nearlive_report.json"))
        else:
            emit("figures/offline_nearlive_latency.pdf", ExportOutcome("SKIPPED_NO_DATA", "no real latency distribution in offline_nearlive_report.json", "06_statistics/offline_nearlive_report.json"))
    else:
        emit("offline_nearlive_results.csv", ExportOutcome("SKIPPED_NO_DATA", "no offline_nearlive_report.json with real analytical_agreement for any real paper run", "06_statistics/offline_nearlive_report.json"))
        emit("figures/offline_nearlive_latency.pdf", ExportOutcome("SKIPPED_NO_DATA", "no offline_nearlive_report.json for any real paper run", "06_statistics/offline_nearlive_report.json"))

    # --- coverage_results.csv (from RQ1/confirmatory reports' own risk_coverage, when present) ---
    coverage_source = confirmatory_future.get("risk_coverage") if confirmatory_future else None
    if coverage_source and coverage_source.get("status") == "EXECUTED" and coverage_source.get("value"):
        points = coverage_source["value"]
        _write_csv(exports_dir / "coverage_results.csv", points if isinstance(points, list) else [points])
        emit("coverage_results.csv", ExportOutcome("GENERATED", f"real, from {run_dir.name}/06_statistics/confirmatory_future_analysis_report.json"))
        if isinstance(points, list) and points:
            paper_figures.risk_coverage_figure(
                coverage=[p.get("coverage") for p in points], risk=[p.get("risk") for p in points],
                title="Risk-coverage", out_path=figures_dir / "risk_coverage.pdf",
            )
            emit("figures/risk_coverage.pdf", ExportOutcome("GENERATED", "real"))
        else:
            emit("figures/risk_coverage.pdf", ExportOutcome("SKIPPED_NO_DATA", "risk_coverage value is empty", "06_statistics/confirmatory_future_analysis_report.json"))
    else:
        emit("coverage_results.csv", ExportOutcome("SKIPPED_NO_DATA", "no EXECUTED risk_coverage in confirmatory_future_analysis_report.json", "06_statistics/confirmatory_future_analysis_report.json"))
        emit("figures/risk_coverage.pdf", ExportOutcome("SKIPPED_NO_DATA", "no EXECUTED risk_coverage in confirmatory_future_analysis_report.json", "06_statistics/confirmatory_future_analysis_report.json"))

    # --- Paper-representation pass (2026-08-17): closed-set-aware exports ---
    tx_rows = tx_composition_rows(repository.build_tx_composition_table())
    if tx_rows:
        _write_csv(exports_dir / "tx_composition.csv", tx_rows)
        emit("tx_composition.csv", ExportOutcome("GENERATED", "real, from build_tx_composition_table()"), classification="PAPER_PRIMARY", provenance=base_provenance)
    else:
        emit("tx_composition.csv", ExportOutcome("SKIPPED_NO_DATA", "no physical units registered", "ble_rffi_studio/registry"))

    epoch_rows = receiver_epoch_rows(repository.build_receiver_epoch_table())
    if epoch_rows:
        _write_csv(exports_dir / "receiver_epochs.csv", epoch_rows)
        emit("receiver_epochs.csv", ExportOutcome("GENERATED", "real, from build_receiver_epoch_table()"), classification="PAPER_PRIMARY", provenance=base_provenance)
    else:
        emit("receiver_epochs.csv", ExportOutcome("SKIPPED_NO_DATA", "no real capture has a resolved receiver_epoch yet", "ble_rffi_studio/captures"))

    completeness = repository.get_scientific_completeness_report()
    _write_csv(exports_dir / "scientific_completeness.csv", scientific_completeness_rows(completeness))
    emit("scientific_completeness.csv", ExportOutcome("GENERATED", "real, from get_scientific_completeness_report()"), classification="PAPER_PRIMARY", provenance=base_provenance)

    if closed_set:
        closed_set_provenance = {**base_provenance, "dataset_id": closed_set.get("dataset_id"), "dataset_version": closed_set.get("dataset_version"),
                                  "paper_run_id": closed_set.get("paper_run_id"), "model_bundle_id": closed_set.get("primary_training_run_id")}
        partition_table = repository.build_partition_composition_table(closed_set["dataset_id"], closed_set["dataset_version"], "MULTI_DEVICE_CLASSIFICATION")
        _write_csv(exports_dir / "closed_set_partition_composition.csv", partition_composition_rows(partition_table))
        emit("closed_set_partition_composition.csv", ExportOutcome("GENERATED", "real, from build_partition_composition_table()"), classification="PAPER_PRIMARY", provenance=closed_set_provenance)

        primary_test = closed_set.get("primary_test") or {}
        per_transmitter = per_transmitter_rows(
            primary_test.get("recall_per_class"), primary_test.get("precision_per_class"), primary_test.get("f1_per_class"),
            primary_test.get("confusion_matrix"),
        )
        if per_transmitter:
            _write_csv(exports_dir / "closed_set_per_transmitter.csv", per_transmitter)
            emit("closed_set_per_transmitter.csv", ExportOutcome("GENERATED", "real, from the PRIMARY branch's real TEST evaluation"), classification="PAPER_PRIMARY", provenance=closed_set_provenance)
        else:
            emit("closed_set_per_transmitter.csv", ExportOutcome("SKIPPED_NO_DATA", "no real per-class TEST metrics for the PRIMARY branch yet", "06_statistics/rq2_representation_comparison_report.json"))

        raw_matrix = primary_test.get("confusion_matrix")
        if raw_matrix:
            labels = list(raw_matrix.keys())
            normalized = paper_figure_aggregations.normalize_confusion_matrix(raw_matrix)
            matrix_pct = [[normalized[t][p]["pct"] for p in labels] for t in labels]
            matrix_n = [[normalized[t][p]["n"] for p in labels] for t in labels]
            paper_figures.normalized_confusion_matrix_figure(
                labels=labels, matrix_pct=matrix_pct, matrix_n=matrix_n,
                title="Closed-set -- confusion matrix, normalized by true class (TEST)", out_path=figures_dir / "closed_set_confusion_matrix_normalized",
            )
            emit("figures/closed_set_confusion_matrix_normalized.pdf", ExportOutcome("GENERATED", "real, row-normalized from the same TEST confusion matrix already exported"), classification="PAPER_PRIMARY", provenance=closed_set_provenance)
        else:
            emit("figures/closed_set_confusion_matrix_normalized.pdf", ExportOutcome("SKIPPED_NO_DATA", "no real TEST confusion matrix for the PRIMARY branch yet", "06_statistics/rq2_representation_comparison_report.json"))

        # Closed-set 10-second decision windows + window-level risk-coverage
        # (2026-08-17) -- same real coverage_analysis_report.json the
        # Coverage tab's window_level_evaluation section reads (GET
        # /runs/{id}/coverage-analysis), never a second computation. Needs
        # run_coverage_analysis(evaluate_window_level=True) to have been run
        # at least once for this closed-set paper_run_id.
        coverage_report = repository.get_coverage_analysis_report(closed_set["paper_run_id"])
        primary_branch = closed_set.get("primary_branch")
        decision_windows = decision_window_rows(coverage_report, primary_branch) if coverage_report and primary_branch else []
        if decision_windows:
            _write_csv(exports_dir / "closed_set_decision_windows.csv", decision_windows)
            emit("closed_set_decision_windows.csv", ExportOutcome("GENERATED", f"real, from 06_statistics/coverage_analysis_report.json window_level_evaluation[{primary_branch}]"), classification="PAPER_PRIMARY", provenance=closed_set_provenance)
        else:
            emit("closed_set_decision_windows.csv", ExportOutcome("SKIPPED_NO_DATA", "no coverage_analysis_report.json with window_level_evaluation for the PRIMARY branch yet -- run Coverage Analysis with evaluate_window_level=true", "06_statistics/coverage_analysis_report.json"))

        window_risk_coverage = window_level_risk_coverage_rows(coverage_report, primary_branch) if coverage_report and primary_branch else []
        if window_risk_coverage:
            _write_csv(exports_dir / "closed_set_risk_coverage_window_level.csv", window_risk_coverage)
            emit("closed_set_risk_coverage_window_level.csv", ExportOutcome("GENERATED", f"real, from 06_statistics/coverage_analysis_report.json window_level_evaluation[{primary_branch}]"), classification="PAPER_PRIMARY", provenance=closed_set_provenance)
        else:
            emit("closed_set_risk_coverage_window_level.csv", ExportOutcome("SKIPPED_NO_DATA", "no window-level risk_coverage for the PRIMARY branch yet", "06_statistics/coverage_analysis_report.json"))

        # DEVELOPMENT EVIDENCE closure pass (2026-08-18): compact per-partition
        # decision-window summary (TRAIN/VALIDATION/TEST: n_windows, n_per_tx,
        # BA, accuracy, n_decided, n_abstained, coverage) + the real TEST
        # window-level confusion matrix -- both pure transforms over the SAME
        # coverage_analysis_report.json fetched above, never a second
        # decision-window evaluation. evidence_status is always DEVELOPMENT
        # here -- never confirmatory/definitive/FUTURE.
        window_summary = development_decision_window_summary_rows(coverage_report, primary_branch) if coverage_report and primary_branch else []
        if window_summary:
            _write_csv(exports_dir / "development_decision_window_summary.csv", window_summary)
            emit("development_decision_window_summary.csv", ExportOutcome("GENERATED", f"real, from 06_statistics/coverage_analysis_report.json window_level_evaluation[{primary_branch}]"), classification="PAPER_PRIMARY", provenance=closed_set_provenance)
        else:
            emit("development_decision_window_summary.csv", ExportOutcome("SKIPPED_NO_DATA", "no window-level evaluation for the PRIMARY branch yet", "06_statistics/coverage_analysis_report.json"))

        test_window_eval = ((coverage_report.get("window_level_evaluation") or {}).get(primary_branch) or {}).get("by_evaluation_domain", {}).get("TEST") if coverage_report and primary_branch else None
        if test_window_eval and test_window_eval.get("confusion_matrix"):
            _write_csv(exports_dir / "development_test_window_confusion_matrix.csv", confusion_matrix_rows(test_window_eval["confusion_matrix"]))
            emit("development_test_window_confusion_matrix.csv", ExportOutcome("GENERATED", f"real, from 06_statistics/coverage_analysis_report.json window_level_evaluation[{primary_branch}].by_evaluation_domain.TEST"), classification="PAPER_PRIMARY", provenance=closed_set_provenance)
        else:
            emit("development_test_window_confusion_matrix.csv", ExportOutcome("SKIPPED_NO_DATA", "no TEST window-level confusion matrix for the PRIMARY branch yet", "06_statistics/coverage_analysis_report.json"))
    else:
        for name in (
            "closed_set_partition_composition.csv", "closed_set_per_transmitter.csv", "figures/closed_set_confusion_matrix_normalized.pdf",
            "closed_set_decision_windows.csv", "closed_set_risk_coverage_window_level.csv",
            "development_decision_window_summary.csv", "development_test_window_confusion_matrix.csv",
        ):
            emit(name, ExportOutcome("SKIPPED_NO_DATA", "no paper_run with scientific_task=MULTI_DEVICE_CLASSIFICATION exists yet", "list_runs()"))

    # Campaign/partition timeline -- makes visible, as a figure, that
    # protected FUTURE stays gated behind protocol freeze (real 17-phase
    # status, already computed by get_study_control_center_status()).
    control_center = repository.get_study_control_center_status()
    phases = [{"label": p["label"], "execution_state": p["execution_state"]} for p in control_center.get("phases", [])]
    if phases:
        paper_figures.campaign_timeline_figure(phases=phases, title="Campaign timeline (real, current status)", out_path=figures_dir / "campaign_timeline")
        emit("figures/campaign_timeline.pdf", ExportOutcome("GENERATED", "real, from get_study_control_center_status()"), classification="PAPER_PRIMARY", provenance=base_provenance)
    else:
        emit("figures/campaign_timeline.pdf", ExportOutcome("SKIPPED_NO_DATA", "no phase status available", "get_study_control_center_status()"))

    # Forensic evidence lineage -- one real traced example, source I/Q all
    # the way to the closed-set PRIMARY model's real bundle (when exported).
    if closed_set and closed_set.get("primary_training_run_id"):
        bundle_info = repository._find_bundle_for_training_run(closed_set["primary_training_run_id"])
        # Real preprocessing profile actually used by the PRIMARY training
        # run -- read directly from training_run.json (the same file
        # verify_preprocessing_profile_provenance() checks), never assumed
        # to be any particular profile_id. Currently base-v1 (identity) for
        # every real closed-set run; shown here so the lineage diagram
        # cannot silently go stale if that ever changes.
        preprocessing_profile_id = None
        training_run_path = repository.ble_root / "training_runs" / closed_set["primary_training_run_id"] / "training_run.json"
        if training_run_path.is_file():
            preprocessing_profile_id = json.loads(training_run_path.read_text(encoding="utf-8")).get("base_preprocessing_profile_id")
        nodes = [
            {"label": "Dataset", "detail": f"{closed_set['dataset_id']} @ {closed_set['dataset_version']}"},
            {"label": "Split (TRAIN/VALIDATION/TEST)", "detail": f"leakage_check={(closed_set.get('rq1') or {}).get('confirmatory_split_manifest_sha256', 'n/a')[:16]}..."},
            {"label": "Preprocessing", "detail": f"base_preprocessing_profile_id={preprocessing_profile_id or 'unknown'}"},
            {"label": "Training run", "detail": closed_set["primary_training_run_id"]},
            {"label": "Model bundle", "detail": f"bundle_id={bundle_info['bundle_id']}, sha256={bundle_info['bundle_sha256'][:16]}..." if bundle_info else "not exported yet"},
            {"label": "RQ1/RQ2 decision", "detail": f"PRIMARY branch = {closed_set.get('primary_branch')}"},
        ]
        paper_figures.forensic_lineage_diagram_figure(nodes=nodes, title="Forensic evidence lineage (real, traced)", out_path=figures_dir / "forensic_lineage")
        emit("figures/forensic_lineage.pdf", ExportOutcome("GENERATED", "real, traced from the closed-set PRIMARY branch"), classification="PAPER_PRIMARY", provenance=closed_set_provenance)

        # Publication-figure variant (2026-08-19, methodological audit item
        # 7): same real chain of IDs, minus the truncated sha256 fragments
        # and the "(real, traced)" title qualifier -- the identifiers
        # themselves (dataset id/version, training_run_id, bundle_id, branch
        # name) are what makes this chain traceable, so they stay; only the
        # partial-hash display text is dropped, since a 16-char hash prefix
        # is not independently verifiable by a reader and full hashes remain
        # in the real artifacts/figure_manifest.json regardless.
        # Human-readable node detail text (2026-08-24): the full dataset
        # version timestamp, split-manifest compound id, training_run_id,
        # and bundle_id are long, machine-oriented identifiers -- dropped
        # from THIS visible figure only. Every one of them remains exactly
        # as before in the internal `nodes` figure above, in this export's
        # own provenance sidecar/figure_manifest.json entry, and in the
        # real, unmodified manifests/bundles on disk -- nothing persisted
        # was removed, only what gets drawn into the publication PNG.
        model_type = None
        if training_run_path.is_file():
            model_type = json.loads(training_run_path.read_text(encoding="utf-8")).get("model_type")
        publication_nodes = [
            {"label": "Dataset", "detail": f"{closed_set['dataset_id']} (closed-set, 4 enrolled transmitters)"},
            {"label": "Split", "detail": "TRAIN / VALIDATION / TEST -- channel-37 scoped, session-disjoint"},
            {"label": "Preprocessing", "detail": f"{preprocessing_profile_id or 'unknown'} (identity)" if preprocessing_profile_id == "base-v1" else (preprocessing_profile_id or "unknown")},
            {"label": "Training", "detail": f"{MODEL_TYPE_PUBLICATION_LABELS.get(model_type, model_type or 'unknown')} (PRIMARY)"},
            {"label": "Model bundle", "detail": "Exported, evaluated" if bundle_info else "not exported yet"},
            {"label": "RQ1/RQ2 decision", "detail": f"PRIMARY branch = {RQ2_BRANCH_PUBLICATION_LABELS.get(closed_set.get('primary_branch'), closed_set.get('primary_branch'))}"},
        ]
        paper_figures.forensic_lineage_diagram_figure(nodes=publication_nodes, title="Forensic evidence lineage", out_path=figures_dir / "forensic_lineage_publication")
        emit(
            "figures/forensic_lineage_publication.pdf", ExportOutcome("GENERATED", "real, publication variant of figures/forensic_lineage.pdf (same chain, no truncated hashes)"),
            classification="PAPER_PRIMARY", provenance=closed_set_provenance,
        )
    else:
        emit("figures/forensic_lineage.pdf", ExportOutcome("SKIPPED_NO_DATA", "no closed-set PRIMARY branch to trace yet", "get_evidence_dashboard_summary()"))
        emit("figures/forensic_lineage_publication.pdf", ExportOutcome("SKIPPED_NO_DATA", "no closed-set PRIMARY branch to trace yet", "get_evidence_dashboard_summary()"))

    # --- LaTeX tables: one section per CSV that was actually GENERATED ---
    csv_sections: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        if entry["status"] == "GENERATED" and entry["file"].endswith(".csv"):
            csv_path = exports_dir / entry["file"]
            with csv_path.open(encoding="utf-8") as handle:
                csv_sections[entry["file"].removesuffix(".csv")] = list(csv.DictReader(handle))
    if csv_sections:
        (exports_dir / "paper_tables.tex").write_text(render_latex_tables(csv_sections), encoding="utf-8")
        emit("paper_tables.tex", ExportOutcome("GENERATED", f"real, {len(csv_sections)} table section(s) from real CSVs"))
    else:
        emit("paper_tables.tex", ExportOutcome("SKIPPED_NO_DATA", "no real CSV was generated this run to build tables from", "all of the above, once real"))

    manifest = {
        "schema_version": EXPORT_MANIFEST_SCHEMA_VERSION, "generated_at": _utc_now(),
        "generated_count": sum(1 for e in entries if e["status"] == "GENERATED"),
        "skipped_count": sum(1 for e in entries if e["status"] == "SKIPPED_NO_DATA"),
        "entries": entries,
    }
    atomic_json(exports_dir / "export_manifest.json", manifest)

    # Figure/artifact sync closure (2026-08-18): a real, verifiable
    # artifact -> figure trace for every scientific figure this pass
    # produced (RQ1/RQ2 today) -- see docs/ble/generate_evidence_figures.py
    # --verify, which reads this file to confirm readme_img/'s copies were
    # generated from the exact same source artifact this manifest names
    # (never a second, independently-generated PNG).
    atomic_json(exports_dir / "figure_manifest.json", {
        "schema_version": "ble-scientific-results-figure-manifest-v1", "generated_at": _utc_now(),
        "figures": figure_manifest_entries,
    })
    return manifest


def _emit_confusion_matrix_figure(emit: Callable[[str, ExportOutcome], None], confusion_matrix: dict[str, dict[str, int]], filename: str, out_path: Path, title: str) -> None:
    labels = list(confusion_matrix.keys())
    matrix = [[confusion_matrix[t].get(p, 0) for p in labels] for t in labels]
    paper_figures.confusion_matrix_figure(labels=labels, matrix=matrix, title=title, out_path=out_path)
    emit(filename, ExportOutcome("GENERATED", "real"))


def _emit_confirmatory_derived_exports(
    emit: Callable[[str, ExportOutcome], None], confirmatory_future: dict[str, Any] | None, run_dir: Path | None,
    exports_dir: Path, figures_dir: Path, validation_dry_run: dict[str, Any] | None = None,
) -> None:
    """Fast-closure pass (2026-08-12): RQ3/RQ4's per-unit/per-region series
    (rq3_pairs, rq3_reset_mean_d_ci/rq3_control_mean_d_ci, rq4_region_report)
    are real but only ever attached to confirmatory_statistical_plan_report.json
    (the VALIDATION dry-run, from run_rq3_frr_analysis/run_rq4_region_analysis)
    -- run_confirmatory_future_analysis's own report never carries them (it
    only re-runs the aggregate 11-method engine over FUTURE-scoped data, see
    its own docstring). `validation_dry_run` is that VALIDATION report, read
    ONLY for these already-real series -- never for the confirmatory
    (CONFIRMATORY_FUTURE-vs-VALIDATION_DRY_RUN) hypothesis-test status
    itself, which still comes exclusively from confirmatory_future."""
    source = "06_statistics/confirmatory_future_analysis_report.json"
    validation_source = "06_statistics/confirmatory_statistical_plan_report.json"
    rq3 = (confirmatory_future or {}).get("rq3_within_device_permutation_test")
    if rq3 and rq3.get("status") == "EXECUTED":
        _write_csv(exports_dir / "rq3_results.csv", statistical_method_rows(confirmatory_future, ["rq3_within_device_permutation_test", "holm_correction"]))
        emit("rq3_results.csv", ExportOutcome("GENERATED", f"real, from {run_dir.name}/{source}" if run_dir else "real"))

        valid_pairs = [p for p in (validation_dry_run or {}).get("rq3_pairs", []) if p.get("valid") and p.get("pre_frr") is not None and p.get("post_frr") is not None]
        if valid_pairs:
            paper_figures.paired_pre_post_figure(
                unit_ids=[f"{p['physical_unit_id']} ({p['intervention_arm']})" for p in valid_pairs],
                pre_values=[p["pre_frr"] for p in valid_pairs], post_values=[p["post_frr"] for p in valid_pairs],
                ylabel="FRR", title="RQ3 -- PRE->POST (RESET/CONTROL)", out_path=figures_dir / "rq3_pre_post.pdf",
            )
            emit("figures/rq3_pre_post.pdf", ExportOutcome("GENERATED", f"real, from {run_dir.name}/{validation_source}" if run_dir else "real"))
        else:
            emit("figures/rq3_pre_post.pdf", ExportOutcome("SKIPPED_NO_DATA", "no valid rq3_pairs with real pre_frr/post_frr in confirmatory_statistical_plan_report.json", validation_source))

        reset_ci, control_ci = (validation_dry_run or {}).get("rq3_reset_mean_d_ci"), (validation_dry_run or {}).get("rq3_control_mean_d_ci")
        categories = [name for name, ci in (("RESET", reset_ci), ("CONTROL", control_ci)) if ci]
        if categories:
            values = [ci["point_estimate"] for name, ci in (("RESET", reset_ci), ("CONTROL", control_ci)) if ci]
            ci_low = [ci["ci_low"] for name, ci in (("RESET", reset_ci), ("CONTROL", control_ci)) if ci]
            ci_high = [ci["ci_high"] for name, ci in (("RESET", reset_ci), ("CONTROL", control_ci)) if ci]
            paper_figures.bar_with_ci_figure(
                categories=categories, values=values, ci_low=ci_low, ci_high=ci_high,
                ylabel="D = FRR_post - FRR_pre (bootstrap CI)", title="RQ3 -- D by arm, with cluster-bootstrap CI", out_path=figures_dir / "rq3_delta_cycle.pdf",
            )
            emit("figures/rq3_delta_cycle.pdf", ExportOutcome("GENERATED", f"real, from {run_dir.name}/{validation_source}" if run_dir else "real"))
        else:
            emit("figures/rq3_delta_cycle.pdf", ExportOutcome("SKIPPED_NO_DATA", "no rq3_reset_mean_d_ci/rq3_control_mean_d_ci in confirmatory_statistical_plan_report.json", validation_source))
    else:
        for name in ("rq3_results.csv", "figures/rq3_pre_post.pdf", "figures/rq3_delta_cycle.pdf"):
            emit(name, ExportOutcome("SKIPPED_NO_DATA", "no EXECUTED rq3_within_device_permutation_test in confirmatory_future_analysis_report.json", source))

    rq4 = (confirmatory_future or {}).get("rq4_paired_comparison")
    non_inferiority = (confirmatory_future or {}).get("non_inferiority")
    if rq4 and rq4.get("status") == "EXECUTED":
        _write_csv(exports_dir / "rq4_results.csv", statistical_method_rows(confirmatory_future, ["rq4_paired_comparison", "non_inferiority", "holm_correction"]))
        emit("rq4_results.csv", ExportOutcome("GENERATED", f"real, from {run_dir.name}/{source}" if run_dir else "real"))

        region_report = (validation_dry_run or {}).get("rq4_region_report") or {}
        blocks = region_report.get("matched_region_blocks") or []
        region_means: dict[str, list[float]] = {}
        for row in blocks:
            for region_name, cell in (row.get("regions") or {}).items():
                if cell and cell.get("recall") is not None:
                    region_means.setdefault(region_name, []).append(cell["recall"])
        if region_means:
            categories = sorted(region_means.keys())
            values = [sum(region_means[c]) / len(region_means[c]) for c in categories]
            paper_figures.bar_with_ci_figure(
                categories=categories, values=values, ci_low=None, ci_high=None,
                ylabel="Mean recall (1 - FRR)", title="RQ4 -- region comparison", out_path=figures_dir / "rq4_region_dependence.pdf",
            )
            emit("figures/rq4_region_dependence.pdf", ExportOutcome("GENERATED", f"real, from {run_dir.name}/{validation_source}" if run_dir else "real"))
        else:
            emit("figures/rq4_region_dependence.pdf", ExportOutcome("SKIPPED_NO_DATA", "no rq4_region_report.matched_region_blocks with a real recall value in confirmatory_statistical_plan_report.json", validation_source))

        if non_inferiority and non_inferiority.get("status") == "EXECUTED":
            ni_value = non_inferiority.get("value") or {}
            if all(ni_value.get(k) is not None for k in ("mean_difference", "ci_low", "margin")):
                paper_figures.non_inferiority_figure(
                    mean_difference=ni_value["mean_difference"], ci_low=ni_value["ci_low"], margin=ni_value["margin"],
                    non_inferior=bool(ni_value.get("non_inferior")), title="RQ4 -- non-inferiority", out_path=figures_dir / "rq4_noninferiority.pdf",
                )
                emit("figures/rq4_noninferiority.pdf", ExportOutcome("GENERATED", f"real, from {run_dir.name}/{source}" if run_dir else "real"))
            else:
                emit("figures/rq4_noninferiority.pdf", ExportOutcome("SKIPPED_NO_DATA", "non_inferiority.value is missing mean_difference/ci_low/margin", source))
        else:
            emit("figures/rq4_noninferiority.pdf", ExportOutcome("SKIPPED_NO_DATA", "no EXECUTED non_inferiority in confirmatory_future_analysis_report.json", source))
    else:
        for name in ("rq4_results.csv", "figures/rq4_region_dependence.pdf", "figures/rq4_noninferiority.pdf"):
            emit(name, ExportOutcome("SKIPPED_NO_DATA", "no EXECUTED rq4_paired_comparison in confirmatory_future_analysis_report.json", source))

