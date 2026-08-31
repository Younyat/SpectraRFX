"""Generates real, static figures from the platform's own real, persisted
evidence -- the exact same aggregation the Evidence Dashboard tab reads live
(ScientificResultsRepository.get_evidence_dashboard_summary()), rendered to
PNG so they are visible directly on GitHub/README without running the
platform. Computes NO new science: every number plotted here is read
verbatim from the same real artifacts the dashboard already serves.

Run from the repo root:
    backend/.venv-validation/Scripts/python.exe docs/ble/generate_evidence_figures.py
    backend/.venv-validation/Scripts/python.exe docs/ble/generate_evidence_figures.py --paper-run <id> --verify

Regenerate whenever the underlying real results change (new RQ1/RQ2 runs,
RQ3 campaign progress, RQ4 eligibility) -- this script is the single source
both readme_img/evidence_*.png and docs/ble/evidence_figures.ipynb are built
from, so the two never drift apart.

Figure/artifact sync closure (2026-08-18): artifact -> figure generator ->
PNG/PDF is now the ONLY path for every scientific figure (RQ1/RQ2 today).
`fig_rq1_domains`/`fig_rq2_branches`, which used to render
readme_img/evidence_rq1_domains.png and readme_img/evidence_rq2_branches.png
independently from `get_evidence_dashboard_summary()`, are GONE -- they were
a second, separately-coded renderer for the exact same figure `paper_export.py`
already renders (via `figures/paper_figures.py::bar_with_ci_figure`, now
multi-format PDF+SVG+PNG), and that duplication is exactly what let the
README copy silently drift out of sync (stale "BA_window" label) while the
paper's own copy had already been fixed. Both figures are now produced ONLY
by `ScientificResultsRepository.run_paper_export()` and copied verbatim into
readme_img/ below, via `CONSOLIDATED_FIGURES`, same as the campaign timeline/
confusion-matrix/forensic-lineage figures already were. The remaining
`fig_*` functions below (per-unit metrics, risk-coverage, seed variability,
computational cost, per-unit auxiliary RQ1) are unrelated diagnostic/
sensitivity figures with no paper_export.py counterpart yet -- still computed
directly from `get_evidence_dashboard_summary()`, unchanged.

`--verify` (added 2026-08-18): reads `paper_exports/figure_manifest.json`
(written by `run_paper_export()`) and cross-checks it against the REAL
artifact bytes on disk right now -- never trusts the manifest's own claims.
Read-only: does not regenerate anything, so it can catch "someone edited/
regenerated the artifact but not the figure." See `verify_figures()` below
for the exact failure conditions.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from app.config.settings import settings
from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository

OUT_DIR = REPO_ROOT / "readme_img"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# (paper_exports/figures PNG name, readme_img PNG name) -- copied verbatim
# after run_paper_export(), never re-rendered. RQ1/RQ2 joined this list
# 2026-08-18 -- see module docstring. Methodological audit item 7
# (2026-08-19): README-facing evidence_rq1_domains.png/evidence_rq2_branches
# .png/evidence_forensic_lineage.png now come from the PUBLICATION variant
# each (same real data, no DEVELOPMENT-EVIDENCE caption/footnote text, no
# truncated hashes, human-readable RQ2 labels, fixed [0,1] BA axis) --
# paper_exports/figures/*.png (without the _publication suffix) still exist
# with the full diagnostic caption/footnote for the supplementary bundle,
# just no longer copied into readme_img/.
CONSOLIDATED_FIGURES = [
    ("rq1_acquisition_dependence_publication.png", "evidence_rq1_domains.png"),
    ("rq2_representation_comparison_publication.png", "evidence_rq2_branches.png"),
    ("rq4_full_burst_vs_pre_pdu.png", "evidence_rq4_regions.png"),
    ("rq4_per_unit_recall.png", "evidence_rq4_per_unit_recall.png"),
    ("feature_group_ablation.png", "evidence_feature_group_ablation.png"),
    ("session_stability.png", "evidence_session_stability.png"),
    ("campaign_timeline.png", "evidence_campaign_timeline.png"),
    ("closed_set_confusion_matrix_normalized.png", "evidence_confusion_normalized.png"),
    ("forensic_lineage_publication.png", "evidence_forensic_lineage.png"),
]

# Every figure_manifest.json entry (figure_path) that MUST exist -- see
# verify_figures()'s MISSING_REQUIRED_SOURCE check.
REQUIRED_FIGURE_PATHS = {
    "figures/rq1_acquisition_dependence_publication.png", "figures/rq2_representation_comparison_publication.png",
    "figures/rq4_full_burst_vs_pre_pdu.png", "figures/feature_group_ablation.png", "figures/session_stability.png",
}

# Matches the platform's own dark research-console palette (BleScientific
# ResultsPage.tsx is Tailwind slate/cyan) -- kept legible against GitHub's
# light background instead of mimicking it verbatim.
COLORS = {
    "window": "#b9822c", "capture": "#2f6fb3",
    "primary": "#b9822c", "unselected": "#8892a0",
    "reset": "#c1683b", "control": "#2f8f89",
}
plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white", "axes.edgecolor": "#333333",
    "axes.grid": True, "grid.alpha": 0.25, "font.size": 10.5, "axes.titlesize": 11.5, "axes.titleweight": "bold",
})


def load_repository() -> ScientificResultsRepository:
    root = settings.storage.storage_root
    return ScientificResultsRepository(root / "scientific_reports" / "ble", ble_rffi_studio_root=root / "ble_rffi_studio")


def load_summary() -> dict:
    return load_repository().get_evidence_dashboard_summary()


def sync_consolidated_figures(repo: ScientificResultsRepository) -> list[Path]:
    """Runs the real paper-export pipeline and copies the PNG variant of the
    figures it already rendered into readme_img/ -- see module docstring."""
    repo.run_paper_export()
    figures_dir = repo.root / "paper_exports" / "figures"
    written: list[Path] = []
    for source_name, dest_name in CONSOLIDATED_FIGURES:
        source_path = figures_dir / source_name
        if not source_path.is_file():
            continue
        dest_path = OUT_DIR / dest_name
        shutil.copyfile(source_path, dest_path)
        print("wrote", dest_path, "(copied from paper_exports/figures, not re-rendered)")
        written.append(dest_path)
    return written


def _save(fig, name: str) -> Path:
    path = OUT_DIR / name
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print("wrote", path)
    return path


def fig_confusion(matrix: dict | None, title: str, filename: str) -> Path | None:
    if not matrix:
        return None
    labels = list(matrix.keys())
    grid = np.array([[matrix[t].get(p, 0) for p in labels] for t in labels], dtype=float)
    fig, ax = plt.subplots(figsize=(5, 4.4))
    im = ax.imshow(grid, cmap="Blues")
    ax.set_xticks(range(len(labels))); ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_yticks(range(len(labels))); ax.set_yticklabels(labels)
    ax.set_xlabel("predicted"); ax.set_ylabel("true")
    ax.set_title(title)
    vmax = grid.max() or 1
    for i in range(len(labels)):
        for j in range(len(labels)):
            color = "white" if grid[i, j] > vmax * 0.5 else "#222222"
            ax.text(j, i, int(grid[i, j]), ha="center", va="center", color=color, fontsize=9)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    return _save(fig, filename)


def fig_per_unit_metrics(summary: dict) -> Path | None:
    primary_test = (summary.get("closed_set") or {}).get("primary_test") or {}
    recall = primary_test.get("recall_per_class") or {}
    precision = primary_test.get("precision_per_class") or {}
    f1 = primary_test.get("f1_per_class") or {}
    if not recall:
        return None
    units = list(recall.keys())
    x = np.arange(len(units))
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.bar(x - 0.27, [recall.get(u, 0) for u in units], width=0.27, label="Recall", color="#2f6fb3")
    ax.bar(x, [precision.get(u, 0) for u in units], width=0.27, label="Precision", color="#b9822c")
    ax.bar(x + 0.27, [f1.get(u, 0) for u in units], width=0.27, label="F1", color="#2f8f89")
    ax.set_xticks(x); ax.set_xticklabels(units, rotation=15)
    ax.set_ylim(0, 1.05)
    ax.set_title("Per-unit precision / recall / F1 -- TEST, PRIMARY branch")
    ax.legend(frameon=False)
    return _save(fig, "evidence_per_unit_metrics.png")


def fig_risk_coverage(summary: dict) -> Path | None:
    # Classification (2026-08-18): this is the EXAMPLE_RECORD-level (burst,
    # ~2200 comparable examples) TEST risk-coverage curve from the training
    # run's own evaluation_report.json -- a real, larger-sample curve, but a
    # DIFFERENT evaluation_unit from the DECISION_WINDOW-level one
    # (12 windows/domain, DEVELOPMENT_EXPLORATORY, see coverage_analysis_
    # report.json's window_level_evaluation -- exported as
    # paper_exports/closed_set_risk_coverage_window_level.csv, rendered live
    # in CoverageTab.tsx, not yet a static figure here). Never conflated.
    points = ((summary.get("closed_set") or {}).get("primary_test") or {}).get("risk_coverage") or []
    if not points:
        return None
    pts = sorted(points, key=lambda p: p["coverage"])
    fig, ax = plt.subplots(figsize=(7, 4.3))
    ax.plot([p["coverage"] for p in pts], [p["risk"] for p in pts], color="#2f6fb3", marker="o", markersize=2.5, linewidth=1.4)
    ax.set_xlabel("coverage"); ax.set_ylabel("risk")
    ax.set_xlim(0, 1)
    ax.set_title("Risk-coverage (TEST, PRIMARY branch)\nevaluation_unit=EXAMPLE_RECORD -- DEVELOPMENT AUXILIARY\nEl-Yaniv & Wiener (2010)", fontsize=10.5)
    return _save(fig, "evidence_risk_coverage.png")


def fig_seed_variability(summary: dict) -> Path | None:
    branches = ((summary.get("closed_set") or {}).get("rq2") or {}).get("branches") or []
    primary = next((b for b in branches if b.get("analysis_role") == "PRIMARY"), None)
    seeds = (primary or {}).get("seed_variability") or []
    if not seeds:
        return None
    labels = [f"seed {s['seed']}" for s in seeds]
    values = [s.get("validation_balanced_accuracy") or 0 for s in seeds]
    fig, ax = plt.subplots(figsize=(4.5, 4))
    bars = ax.bar(labels, values, color="#2f6fb3")
    ax.bar_label(bars, fmt="%.3f", padding=3)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Balanced accuracy (VALIDATION)")
    ax.set_title(f"Seed variability -- {primary['branch']} (PRIMARY) -- DEVELOPMENT / SENSITIVITY")
    return _save(fig, "evidence_seed_variability.png")


def fig_computational_cost(summary: dict) -> Path | None:
    branches = ((summary.get("closed_set") or {}).get("rq2") or {}).get("branches") or []
    branches = [b for b in branches if b.get("inference_latency_ms") is not None and b.get("serialized_model_size_bytes") is not None]
    if not branches:
        return None
    names = [b["branch"] for b in branches]
    latency = [b["inference_latency_ms"] for b in branches]
    size_kb = [b["serialized_model_size_bytes"] / 1024 for b in branches]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8.5, 4))
    ax1.bar(names, latency, color="#2f6fb3"); ax1.set_ylabel("ms"); ax1.set_title("Inference latency"); ax1.tick_params(axis="x", rotation=20)
    ax2.bar(names, size_kb, color="#b9822c"); ax2.set_ylabel("KB"); ax2.set_title("Serialized model size"); ax2.tick_params(axis="x", rotation=20)
    fig.suptitle("Computational cost by RQ2 branch -- DEVELOPMENT")
    # Real methodology (training_service.py::_measure_latency_ms): wall-clock
    # time.perf_counter() around a single-sample predict_proba call, mean of
    # 10 repeats, measured on VALIDATION data for every branch of the SAME
    # training run -- so the 4 branches are comparable to each other, but the
    # specific host/machine identity was never captured at measurement time
    # (real gap, not fabricated here) and is not the same as any embedded
    # deployment target.
    fig.text(0.5, -0.03, "latency = mean of 10 repeats, single-sample predict_proba, wall-clock (host not captured at measurement time)",
              ha="center", va="top", fontsize=7.5, color="#4a5568")
    return _save(fig, "evidence_computational_cost.png")


def fig_per_unit_auxiliary_rq1(summary: dict) -> Path | None:
    runs = summary.get("per_unit_auxiliary") or []
    runs = [r for r in runs if r.get("rq1")]
    if not runs:
        return None
    names = [r["dataset_id"] for r in runs]
    window = [r["rq1"].get("ba_window") or 0 for r in runs]
    capture = [r["rq1"].get("ba_capture") or 0 for r in runs]
    x = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    ax.bar(x - 0.2, window, width=0.4, label="BA_window", color=COLORS["window"])
    ax.bar(x + 0.2, capture, width=0.4, label="BA_capture", color=COLORS["capture"])
    ax.set_xticks(x); ax.set_xticklabels(names, rotation=15, ha="right")
    ax.set_ylim(0, 1.05)
    ax.set_title("Per-unit auxiliary TARGET_VS_BACKGROUND -- RQ1 (4 real runs)")
    ax.legend(frameon=False)
    return _save(fig, "evidence_per_unit_auxiliary_rq1.png")


FIGURES = [
    ("Per-unit precision/recall/F1 (TEST)", fig_per_unit_metrics),
    ("Risk-coverage (TEST)", fig_risk_coverage),
    ("Seed variability (PRIMARY branch)", fig_seed_variability),
    ("Computational cost by branch", fig_computational_cost),
    ("Per-unit auxiliary RQ1 (4 real runs)", fig_per_unit_auxiliary_rq1),
]


def main() -> None:
    repo = load_repository()
    summary = repo.get_evidence_dashboard_summary()
    fig_confusion((summary.get("closed_set") or {}).get("rq1", {}).get("confusion_matrix_capture"),
                  "Confusion matrix -- VALIDATION (capture-disjoint)", "evidence_confusion_validation.png")
    fig_confusion((summary.get("closed_set") or {}).get("primary_test", {}).get("confusion_matrix"),
                  "Confusion matrix -- TEST (PRIMARY branch)", "evidence_confusion_test.png")
    for _title, fn in FIGURES:
        fn(summary)
    sync_consolidated_figures(repo)


def verify_figures(repo: ScientificResultsRepository, paper_run_id: str | None) -> list[str]:
    """Read-only. Cross-checks `paper_exports/figure_manifest.json` (written
    by `run_paper_export()`) against the REAL artifact bytes on disk right
    now -- never trusts the manifest's own claims. Returns a list of real
    failure reasons (empty list = pass). Does not regenerate anything, so it
    can actually catch "the artifact changed but the figure was not
    regenerated" instead of trivially passing right after a fresh run."""
    exports_dir = repo.root / "paper_exports"
    manifest_path = exports_dir / "figure_manifest.json"
    if not manifest_path.is_file():
        return ["paper_exports/figure_manifest.json does not exist -- run generate_evidence_figures.py without --verify first"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    figures_by_path = {f["figure_path"]: f for f in manifest["figures"]}
    failures: list[str] = []

    for required in sorted(REQUIRED_FIGURE_PATHS):
        if required not in figures_by_path:
            failures.append(f"MISSING_REQUIRED_SOURCE: {required} has no figure_manifest.json entry")

    for figure_path, entry in figures_by_path.items():
        source_artifact = entry.get("source_artifact") or ""
        source_path = repo.root / source_artifact
        if not source_path.is_file():
            failures.append(f"{figure_path}: source_artifact {source_artifact!r} does not exist on disk")
            continue

        real_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
        if real_sha256 != entry.get("source_artifact_sha256"):
            failures.append(
                f"{figure_path}: STALE_ARTIFACT -- figure_manifest.json's source_artifact_sha256 does not match "
                f"the real current bytes of {source_artifact} (the artifact changed since this figure was last generated -- re-run without --verify)"
            )

        source_json = json.loads(source_path.read_text(encoding="utf-8"))
        real_evaluation_unit = source_json.get("evaluation_unit")
        if real_evaluation_unit and real_evaluation_unit != entry.get("evaluation_unit"):
            failures.append(f"{figure_path}: EVALUATION_UNIT_MISMATCH -- manifest says {entry.get('evaluation_unit')!r}, artifact says {real_evaluation_unit!r}")

        if paper_run_id is not None:
            if entry.get("paper_run_id") != paper_run_id:
                failures.append(f"{figure_path}: PAPER_RUN_ID_MISMATCH -- manifest says {entry.get('paper_run_id')!r}, --paper-run asked for {paper_run_id!r}")
            if not source_artifact.startswith(f"{paper_run_id}/"):
                failures.append(f"{figure_path}: PAPER_RUN_ID_MISMATCH -- source_artifact {source_artifact!r} does not belong to run {paper_run_id!r}")

        # RQ1-specific: a required CI must be present whenever the point
        # estimate it belongs to is present, and capture-disjoint/TEST must
        # never be claimed as protected FUTURE while ba_future is still None.
        if figure_path == "figures/rq1_acquisition_dependence.png":
            ba_capture_ci = (source_json.get("uncertainty_ci") or {}).get("ba_capture_ci") or {}
            if source_json.get("ba_capture") is not None and (ba_capture_ci.get("ci_low") is None or ba_capture_ci.get("ci_high") is None):
                failures.append(f"{figure_path}: MISSING_REQUIRED_CI -- ba_capture is present but uncertainty_ci.ba_capture_ci is not")
            if source_json.get("ba_future") is None and entry.get("evidence_status") == "PROTECTED_FUTURE":
                failures.append(f"{figure_path}: TEST_LABELED_AS_FUTURE -- ba_future is not yet available but evidence_status claims PROTECTED_FUTURE")

            # Real rendered-text checks (2026-08-18): SVG embeds every label/
            # footnote as literal <text> content -- read the SAME sibling
            # .svg _save_figure() wrote and search it directly, rather than
            # trusting the manifest's own claims about what the figure says.
            svg_path = (exports_dir / figure_path).with_suffix(".svg")
            if not svg_path.is_file():
                failures.append(f"{figure_path}: no sibling .svg found to verify rendered label/CI text against")
            else:
                svg_text = svg_path.read_text(encoding="utf-8", errors="ignore")
                if real_evaluation_unit == "EXAMPLE_RECORD" and "BA_window" in svg_text:
                    failures.append(f"{figure_path}: BA_WINDOW_LABEL_FOUND -- rendered SVG contains the raw 'BA_window' label while evaluation_unit=EXAMPLE_RECORD")
                # The FUTURE bar's category label is "protected FUTURE\n({ba_future_status})"
                # -- only ever added to the figure when ba_future is a real,
                # non-None number (see paper_export.py). Checking for the bare
                # substring "protected FUTURE" would also match "Held-out TEST
                # (not protected FUTURE)"'s own label, a false positive -- the
                # real ba_future_status VALUE (e.g. "NOT_YET_AVAILABLE") only
                # ever gets embedded alongside a real future bar, so its
                # presence while ba_future is None is the real, unambiguous
                # signal of a mislabeled TEST-as-FUTURE bar.
                future_status = source_json.get("ba_future_status")
                if source_json.get("ba_future") is None and future_status and future_status in svg_text:
                    failures.append(f"{figure_path}: TEST_LABELED_AS_FUTURE -- rendered SVG contains ba_future_status {future_status!r} (the protected-FUTURE bar's own label) while ba_future is not yet available")
                delta_ci = (source_json.get("uncertainty_ci") or {}).get("delta_dependence_ci") or {}
                if delta_ci.get("ci_low") is not None and delta_ci.get("ci_high") is not None:
                    expected_ci_text = f"[{delta_ci['ci_low']:.3f}, {delta_ci['ci_high']:.3f}]"
                    if expected_ci_text not in svg_text:
                        failures.append(f"{figure_path}: CI_NOT_IN_FIGURE -- delta_dependence 95% CI {expected_ci_text} from the artifact does not appear in the rendered SVG text")

        # RQ4-specific: FULL_BURST/PRE_PDU point estimates and the delta CI
        # must be embedded as real rendered text (same discipline as RQ1
        # above), and it must never claim a hardware/physical fingerprint
        # finding it did not measure.
        if figure_path == "figures/rq4_full_burst_vs_pre_pdu.png":
            svg_path = (exports_dir / figure_path).with_suffix(".svg")
            if not svg_path.is_file():
                failures.append(f"{figure_path}: no sibling .svg found to verify rendered label/CI text against")
            else:
                svg_text = svg_path.read_text(encoding="utf-8", errors="ignore")
                delta = source_json.get("delta") or {}
                if delta.get("ci_low") is not None and delta.get("ci_high") is not None:
                    expected_ci_text = f"[{delta['ci_low']:.3f}, {delta['ci_high']:.3f}]"
                    if expected_ci_text not in svg_text:
                        failures.append(f"{figure_path}: CI_NOT_IN_FIGURE -- delta 95% CI {expected_ci_text} from the artifact does not appear in the rendered SVG text")
                for forbidden in ("hardware fingerprint", "physical fingerprint retained", "physical fingerprint"):
                    if forbidden.lower() in svg_text.lower():
                        failures.append(f"{figure_path}: FORBIDDEN_PHRASING_FOUND -- rendered SVG contains {forbidden!r}, which this exploratory result must not claim")
                # Human-readable figure discipline (2026-08-24): this
                # figure's visible text is meant for a human reader, not a
                # machine -- internal enum/field-name strings must not leak
                # into the rendered title/footnote (the real evidence_status
                # and evaluation_unit values stay in the source JSON and this
                # figure's own figure_manifest.json entry instead).
                for internal_text in ("DEVELOPMENT_EXPLORATORY", "EXAMPLE_RECORD", "evaluation_unit="):
                    if internal_text in svg_text:
                        failures.append(f"{figure_path}: INTERNAL_ENUM_TEXT_FOUND -- rendered SVG contains internal text {internal_text!r}, which should only appear in the source JSON/manifest, not the human-facing figure")

        # Feature-group ablation (2026-08-24): same human-readable-figure
        # discipline as RQ4 above -- real BA values/CI embedded as text, no
        # internal enum/field-name leakage, no interpretive claim about what
        # the result "means" baked into the image.
        if figure_path == "figures/feature_group_ablation.png":
            svg_path = (exports_dir / figure_path).with_suffix(".svg")
            if not svg_path.is_file():
                failures.append(f"{figure_path}: no sibling .svg found to verify rendered label/CI text against")
            else:
                svg_text = svg_path.read_text(encoding="utf-8", errors="ignore")
                for internal_text in ("DEVELOPMENT_EXPLORATORY", "EXAMPLE_RECORD"):
                    if internal_text in svg_text:
                        failures.append(f"{figure_path}: INTERNAL_ENUM_TEXT_FOUND -- rendered SVG contains internal text {internal_text!r}")
                for forbidden in ("hardware fingerprint", "dominated by", "explains the model", "demonstrates", "proves"):
                    if forbidden.lower() in svg_text.lower():
                        failures.append(f"{figure_path}: FORBIDDEN_INTERPRETIVE_PHRASING_FOUND -- rendered SVG contains {forbidden!r}")
                delta_ab = (source_json.get("contrasts") or {}).get("FULL_minus_POWER_AMPLITUDE_LEVEL") or {}
                if delta_ab.get("point_estimate") is not None:
                    expected_delta_text = f"{delta_ab['point_estimate']:.3f}, 95% CI [{delta_ab['ci_low']:.3f}, {delta_ab['ci_high']:.3f}]"
                    if expected_delta_text not in svg_text:
                        failures.append(f"{figure_path}: CI_NOT_IN_FIGURE -- delta (Full - Power/amplitude) {expected_delta_text} from the artifact does not appear in the rendered SVG text")

        # Publication-figure variants (2026-08-19, methodological audit item
        # 7): the README-facing figures must NOT bake in the DEVELOPMENT-
        # EVIDENCE caption/footnote text, the "(real, traced)" qualifier,
        # RQ2's internal snake_case branch keys / "(UNSELECTED)" suffix, or
        # a truncated hash fragment -- checked directly against the rendered
        # SVG text, never assumed from the generator code alone.
        if figure_path in (
            "figures/rq1_acquisition_dependence_publication.png", "figures/rq2_representation_comparison_publication.png",
            "figures/forensic_lineage_publication.png",
        ):
            svg_path = (exports_dir / figure_path).with_suffix(".svg")
            if not svg_path.is_file():
                failures.append(f"{figure_path}: no sibling .svg found to verify rendered label text against")
            else:
                svg_text = svg_path.read_text(encoding="utf-8", errors="ignore")
                if real_evaluation_unit == "EXAMPLE_RECORD" and "BA_window" in svg_text:
                    failures.append(f"{figure_path}: BA_WINDOW_LABEL_FOUND -- rendered SVG contains the raw 'BA_window' label while evaluation_unit=EXAMPLE_RECORD")
                if "DEVELOPMENT EVIDENCE" in svg_text:
                    failures.append(f"{figure_path}: DEV_EVIDENCE_CAPTION_FOUND -- publication figure must not bake the DEVELOPMENT EVIDENCE caption into the image")
                if "real, traced" in svg_text:
                    failures.append(f"{figure_path}: REAL_TRACED_TEXT_FOUND -- publication figure must not bake the '(real, traced)' qualifier into the image")
                if re.search(r"[0-9a-f]{16}\.\.\.", svg_text):
                    failures.append(f"{figure_path}: TRUNCATED_HASH_FOUND -- publication figure must not embed a truncated hash fragment")
        if figure_path == "figures/rq2_representation_comparison_publication.png":
            svg_path = (exports_dir / figure_path).with_suffix(".svg")
            if svg_path.is_file():
                svg_text = svg_path.read_text(encoding="utf-8", errors="ignore")
                if "(UNSELECTED)" in svg_text or "(PRIMARY)" in svg_text:
                    failures.append(f"{figure_path}: ANALYSIS_ROLE_SUFFIX_FOUND -- publication figure must convey PRIMARY/UNSELECTED via color, not a text suffix")
                for internal_key in ("coarse_morphology", "engineered_rf", "raw_iq", "stft"):
                    if internal_key in svg_text:
                        failures.append(f"{figure_path}: INTERNAL_BRANCH_KEY_FOUND -- rendered SVG contains the internal snake_case key {internal_key!r} instead of its human-readable label")

    # readme_img/'s copy must be byte-identical to the figure paper_export.py
    # rendered -- proves it really is a copy, not a second independent
    # render (structurally guaranteed by sync_consolidated_figures(), but
    # verified here rather than assumed).
    for source_name, dest_name in CONSOLIDATED_FIGURES:
        source_png = exports_dir / "figures" / source_name
        dest_png = OUT_DIR / dest_name
        if source_png.is_file() and dest_png.is_file() and source_png.read_bytes() != dest_png.read_bytes():
            failures.append(f"readme_img/{dest_name}: DIVERGED_FROM_PAPER_EXPORT -- not byte-identical to paper_exports/figures/{source_name} (copy is stale, re-run without --verify)")

    return failures


def _approx_equal(a, b, tol: float = 0.0006) -> bool:
    return a is not None and b is not None and abs(float(a) - float(b)) < tol


def _real_reference_values(repo: ScientificResultsRepository) -> dict:
    """Single source for every number verify_documentation_matches_artifacts()
    checks README.md/SCIENTIFIC_STATUS.md against -- computed once, straight
    from the same real artifacts the figures/dashboard/paper_export.py read,
    never re-derived a second way."""
    dashboard = repo.get_evidence_dashboard_summary()
    closed_set = dashboard.get("closed_set") or {}
    rq1 = closed_set.get("rq1") or {}
    primary_test = closed_set.get("primary_test") or {}
    values = {
        "rq1_ba_window": rq1.get("ba_window"), "rq1_ba_capture": rq1.get("ba_capture"),
        "rq1_delta_dependence": rq1.get("delta_dependence"),
        "rq1_ba_capture_ci": (rq1.get("uncertainty_ci") or {}).get("ba_capture_ci") or {},
        "rq1_delta_ci": (rq1.get("uncertainty_ci") or {}).get("delta_dependence_ci") or {},
        "primary_test_ba": primary_test.get("balanced_accuracy"),
        "association_status": (repo.get_latest_association_calibration_summary() or {}).get("status"),
    }
    summary_csv = repo.root / "paper_exports" / "development_decision_window_summary.csv"
    if summary_csv.is_file():
        rows = {row["partition"]: row for row in csv.DictReader(summary_csv.open(encoding="utf-8"))}
        for partition in ("TRAIN", "VALIDATION", "TEST"):
            row = rows.get(partition)
            values[f"{partition.lower()}_windows"] = int(row["n_windows"]) if row else None
            values[f"{partition.lower()}_window_ba"] = float(row["balanced_accuracy"]) if row else None
            values[f"{partition.lower()}_window_accuracy"] = float(row["accuracy"]) if row else None
    return values


def verify_documentation_matches_artifacts(repo: ScientificResultsRepository) -> list[str]:
    """Read-only. Parses the exact real numbers README.md and docs/ble/
    SCIENTIFIC_STATUS.md claim (regexes tied to this project's own current
    wording -- update them alongside the prose if it changes) and compares
    them against `_real_reference_values()`. Never edits either file --
    only reports where they've drifted from the real artifacts."""
    values = _real_reference_values(repo)
    failures: list[str] = []

    readme_text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    status_text = (REPO_ROOT / "docs" / "ble" / "SCIENTIFIC_STATUS.md").read_text(encoding="utf-8")

    readme_checks = [
        ("README", r"Capture-dependent \(same capture,[^|]*\|\s*([\d.]+)\s*\|", "rq1_ba_window", None),
        ("README", r"Capture-disjoint \(VALIDATION\)\s*\|\s*([\d.]+)\s*\|", "rq1_ba_capture", None),
        ("README", r"Held-out TEST \(PRIMARY branch, not protected FUTURE\)\s*\|\s*([\d.]+)\s*\|", "primary_test_ba", None),
        ("README", r"delta_dependence = capture-dependent [^=]*=\s*\+([\d.]+)", "rq1_delta_dependence", None),
        ("README", r"`VALIDATION`: `BA=([\d.]+)`, `accuracy=([\d.]+)`", "validation_window_ba", "validation_window_accuracy"),
        ("README", r"`TEST`: `BA=([\d.]+)`, `accuracy=([\d.]+)`", "test_window_ba", "test_window_accuracy"),
    ]
    status_checks = [
        ("SCIENTIFIC_STATUS.md", r"RQ1 capture-dependent BA.*?\|\s*`([\d.]+)`", "rq1_ba_window", None),
        ("SCIENTIFIC_STATUS.md", r"RQ1 capture-disjoint \(VALIDATION\) BA.*?\|\s*`([\d.]+)`", "rq1_ba_capture", None),
        ("SCIENTIFIC_STATUS.md", r"RQ1 held-out TEST BA \(not protected FUTURE\)\s*\|\s*`([\d.]+)`", "primary_test_ba", None),
        ("SCIENTIFIC_STATUS.md", r"RQ1 `delta_dependence` / 95% CI\s*\|\s*`([\d.]+)`", "rq1_delta_dependence", None),
        ("SCIENTIFIC_STATUS.md", r"VALIDATION window-level BA / argmax accuracy / operational coverage\s*\|\s*`([\d.]+)`\s*/\s*`([\d.]+)`", "validation_window_ba", "validation_window_accuracy"),
        ("SCIENTIFIC_STATUS.md", r"TEST window-level BA / argmax accuracy / operational coverage\s*\|\s*`([\d.]+)`\s*/\s*`([\d.]+)`", "test_window_ba", "test_window_accuracy"),
    ]
    for doc_name, text in (("README", readme_text), ("SCIENTIFIC_STATUS.md", status_text)):
        for label, pattern, key_a, key_b in (readme_checks if doc_name == "README" else status_checks):
            match = re.search(pattern, text, re.DOTALL)
            if not match:
                failures.append(f"{doc_name}: could not find the expected '{key_a}' claim (pattern {pattern!r} not found -- prose may have changed without updating this check)")
                continue
            claimed_a = float(match.group(1))
            if not _approx_equal(claimed_a, values.get(key_a)):
                failures.append(f"{doc_name}: {key_a} claims {claimed_a}, real artifact says {values.get(key_a)!r}")
            if key_b:
                claimed_b = float(match.group(2))
                if not _approx_equal(claimed_b, values.get(key_b)):
                    failures.append(f"{doc_name}: {key_b} claims {claimed_b}, real artifact says {values.get(key_b)!r}")

    window_match = re.search(r"`TRAIN=(\d+)`,\s*`VALIDATION=(\d+)`,\s*`TEST=(\d+)`", readme_text)
    if not window_match:
        failures.append("README: could not find the TRAIN/VALIDATION/TEST decision-window count claim")
    else:
        for partition, claimed in zip(("train", "validation", "test"), window_match.groups()):
            if int(claimed) != values.get(f"{partition}_windows"):
                failures.append(f"README: {partition}_windows claims {claimed}, real artifact says {values.get(f'{partition}_windows')!r}")

    status_window_match = re.search(r"10-second decision windows\s*\|\s*`TRAIN=(\d+)`,\s*`VALIDATION=(\d+)`,\s*`TEST=(\d+)`", status_text)
    if not status_window_match:
        failures.append("SCIENTIFIC_STATUS.md: could not find the TRAIN/VALIDATION/TEST decision-window count claim")
    else:
        for partition, claimed in zip(("train", "validation", "test"), status_window_match.groups()):
            if int(claimed) != values.get(f"{partition}_windows"):
                failures.append(f"SCIENTIFIC_STATUS.md: {partition}_windows claims {claimed}, real artifact says {values.get(f'{partition}_windows')!r}")

    status_assoc_match = re.search(r"Association calibration\s*\|\s*`([A-Z_]+)`", status_text)
    if not status_assoc_match:
        failures.append("SCIENTIFIC_STATUS.md: could not find the association calibration status claim")
    elif status_assoc_match.group(1) != values.get("association_status"):
        failures.append(f"SCIENTIFIC_STATUS.md: association status claims {status_assoc_match.group(1)!r}, real artifact says {values.get('association_status')!r}")

    return failures


def verify_preprocessing_profile_provenance(repo: ScientificResultsRepository, paper_run_id: str) -> list[str]:
    """Methodological-audit lock-in (2026-08-22, item 1): every real training
    run behind the closed-set RQ1/RQ2 canonical numbers must use
    base_preprocessing_profile_id="base-v1" (identity preprocessing) --
    confirmed true as of this audit, and pinned here so it can never silently
    drift (e.g. someone later wiring paper-eq6-7-v1 into a "PRIMARY" run
    without updating the paper's Section IV.A claim that raw-I/Q/STFT "use a
    conservative affine phase compensation" -- which is currently NOT what
    produced the published numbers). Read-only: reads real training_run.json
    files, never retrains, never changes which profile is used."""
    failures: list[str] = []
    rq1_report = repo.get_rq1_acquisition_dependence_report(paper_run_id)
    rq2_report = repo.get_rq2_representation_comparison_report(paper_run_id)
    studio_root = getattr(repo, "ble_root", None)
    if studio_root is None:
        return ["verify_preprocessing_profile_provenance: repository has no ble_root attribute -- cannot read training_run.json files"]

    training_run_ids: set[str] = set()
    if rq1_report:
        diag_id = rq1_report.get("diagnostic_split_manifest_id")  # actually the diagnostic TRAINING RUN id, per rq1_runner.py convention
        if diag_id:
            training_run_ids.add(diag_id)
    if rq2_report:
        for branch in rq2_report.get("branches", []):
            if branch.get("training_run_id"):
                training_run_ids.add(branch["training_run_id"])

    if not training_run_ids:
        return ["verify_preprocessing_profile_provenance: no real training_run_ids found via rq1/rq2 canonical reports -- nothing to verify"]

    for training_run_id in sorted(training_run_ids):
        run_path = studio_root / "training_runs" / training_run_id / "training_run.json"
        if not run_path.is_file():
            failures.append(f"PREPROCESSING_PROFILE_PROVENANCE: {training_run_id} has no training_run.json at {run_path}")
            continue
        real_profile_id = json.loads(run_path.read_text(encoding="utf-8")).get("base_preprocessing_profile_id")
        if real_profile_id != "base-v1":
            failures.append(
                f"PREPROCESSING_PROFILE_DRIFT: {training_run_id} real base_preprocessing_profile_id={real_profile_id!r}, "
                f"expected 'base-v1' -- the closed-set canonical numbers are no longer confirmed to be identity-preprocessing "
                f"only; Section IV.A's phase-compensation claim and this audit's item-1 finding must be re-verified"
            )
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-run", dest="paper_run_id", default=None, help="paper_run_id every figure's source_artifact must belong to (only used with --verify)")
    parser.add_argument("--verify", action="store_true", help="read-only: verify figure_manifest.json against real artifacts on disk instead of regenerating")
    args = parser.parse_args()

    if args.verify:
        repo = load_repository()
        failures = verify_figures(repo, args.paper_run_id) + verify_documentation_matches_artifacts(repo)
        preprocessing_paper_run_id = args.paper_run_id or "paper-run-2805869e6282778ad729a26d022ec9b0"
        failures += verify_preprocessing_profile_provenance(repo, preprocessing_paper_run_id)
        if failures:
            print("FIGURE_VERIFICATION_FAILED:")
            for reason in failures:
                print(" -", reason)
            sys.exit(1)
        print(
            f"OK -- figure_manifest.json, README.md, and SCIENTIFIC_STATUS.md all verified against real artifacts on disk "
            f"({len(REQUIRED_FIGURE_PATHS)} required figure(s) present, no staleness/mismatch/drift found)."
        )
    else:
        main()
