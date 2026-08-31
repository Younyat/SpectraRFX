"""Builds docs/ble/evidence_figures.ipynb from the real PNGs
generate_evidence_figures.py just wrote to readme_img/ -- a single source of
truth, never a second render pass that could drift from the README images.
Each code cell calls the SAME real functions from generate_evidence_figures.py
(so re-running the notebook regenerates real figures from the platform's own
real, persisted evidence), pre-populated with the already-rendered PNG as its
output so the notebook is legible on GitHub without executing anything.

No nbformat/jupyter package dependency -- an .ipynb file is plain JSON
(nbformat v4 schema); this writes it directly.

Run from the repo root, after generate_evidence_figures.py:
    backend/.venv-validation/Scripts/python.exe docs/ble/build_evidence_notebook.py
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
IMG_DIR = REPO_ROOT / "readme_img"
OUT_PATH = REPO_ROOT / "docs" / "ble" / "evidence_figures.ipynb"

# (markdown explaining paper relevance, code cell source, png filename)
SECTIONS: list[tuple[str, str, str]] = [
    (
        "## RQ1 -- closed-set acquisition dependence\n\n"
        "`delta_dependence = BA_window - BA_capture`, the manuscript's Eq. 12 contrast. "
        "`BA_window` is the intentionally capture-dependent diagnostic (train/validation "
        "windows share a session); `BA_capture` is the confirmatory, capture-disjoint "
        "result. The gap between them is real, on-hardware evidence of the acquisition-"
        "dependence optimism the manuscript's methodology section argues for.",
        "fig_rq1_domains(summary)",
        "evidence_rq1_domains.png",
    ),
    (
        "## RQ2 -- signal-representation comparison\n\n"
        "All four branches (`coarse_morphology`, `engineered_rf`, `raw_iq`, `stft`) "
        "trained on the same admitted acquisition groups and decision windows. "
        "PRIMARY branch selected on VALIDATION only.",
        "fig_rq2_branches(summary)",
        "evidence_rq2_branches.png",
    ),
    (
        "## Confusion matrices\n\n"
        "Capture-disjoint VALIDATION (left) vs. held-out TEST (right) for the PRIMARY "
        "branch -- CC2650-UNIT-01 is perfectly separated (recall 1.0) in both.",
        "fig_confusion_validation = fig_confusion(\n"
        "    summary['closed_set']['rq1']['confusion_matrix_capture'],\n"
        "    'Confusion matrix -- VALIDATION (capture-disjoint)', 'evidence_confusion_validation.png')",
        "evidence_confusion_validation.png",
    ),
    (
        "",
        "fig_confusion_test = fig_confusion(\n"
        "    summary['closed_set']['primary_test']['confusion_matrix'],\n"
        "    'Confusion matrix -- TEST (PRIMARY branch)', 'evidence_confusion_test.png')",
        "evidence_confusion_test.png",
    ),
    (
        "## Per-unit precision / recall / F1 (TEST)\n\n"
        "Reported per unit, not only as an aggregate, because the closed-set TEST split "
        "is naturally imbalanced (1,857 KEYFOB01 examples vs. 166 KEYFOB02) -- balanced "
        "accuracy and macro-F1 (used throughout this study) are exactly the metrics that "
        "stay informative under this imbalance, unlike raw accuracy.",
        "fig_per_unit_metrics(summary)",
        "evidence_per_unit_metrics.png",
    ),
    (
        "## Risk-coverage curve (TEST, PRIMARY branch)\n\n"
        "The selective-prediction curve (El-Yaniv & Wiener, 2010) the manuscript's "
        "abstention mechanism is built on -- one point per achievable confidence "
        "threshold, real predictions from the real held-out TEST split.",
        "fig_risk_coverage(summary)",
        "evidence_risk_coverage.png",
    ),
    (
        "## Seed variability (PRIMARY branch)\n\n"
        "The PRIMARY branch re-trained under the platform's two other frozen seeds "
        "(`137`, `2024`), VALIDATION-only -- a real reproducibility check, not a claim "
        "about TEST stability.",
        "fig_seed_variability(summary)",
        "evidence_seed_variability.png",
    ),
    (
        "## Computational cost by RQ2 branch\n\n"
        "Real inference latency and serialized model size per branch, supporting the "
        "manuscript's stated computational-cost comparison.",
        "fig_computational_cost(summary)",
        "evidence_computational_cost.png",
    ),
    (
        "## Per-unit auxiliary TARGET_VS_BACKGROUND runs\n\n"
        "The 4 individual per-unit binary detectors, kept as an auxiliary analysis, "
        "never substituted for the closed-set result above -- their own real "
        "`delta_dependence` is consistently smaller than the closed-set effect, "
        "because target-vs-background is an easier task with more redundant evidence "
        "per window.",
        "fig_per_unit_auxiliary_rq1(summary)",
        "evidence_per_unit_auxiliary_rq1.png",
    ),
    (
        "## Campaign timeline (real, current status)\n\n"
        "Every study phase -- qualification through protected FUTURE and confirmatory "
        "analysis -- colored by its real `execution_state`. Rendered once by the paper-"
        "export pipeline (`figures/paper_figures.py`) and copied here, not re-plotted, so "
        "this view can never drift from the manuscript's own timeline figure.",
        "sync_consolidated_figures(repo)",
        "evidence_campaign_timeline.png",
    ),
    (
        "## Confusion matrix, normalized by true class (TEST, PRIMARY branch)\n\n"
        "Same real counts as the raw confusion matrix above, row-normalized to a "
        "per-class percentage with `n` kept as secondary per-cell information -- the "
        "canonical normalized view for the manuscript, from the same paper-export "
        "renderer as the timeline above.",
        "# already rendered by sync_consolidated_figures(repo) above",
        "evidence_confusion_normalized.png",
    ),
    (
        "## Forensic evidence lineage\n\n"
        "Source I/Q -> burst -> PDU -> admitted example -> dataset -> split -> "
        "preprocessing -> model -> window decision, traced with real IDs/hashes from the "
        "closed-set PRIMARY branch -- not a dashboard screenshot, a diagram built from the "
        "same real artifacts as every other figure in this notebook.",
        "# already rendered by sync_consolidated_figures(repo) above",
        "evidence_forensic_lineage.png",
    ),
]

INTRO_MD = """# SpectraRFˣ -- real closed-set evidence figures

Every figure below is generated directly from the platform's own real, persisted
evidence -- the exact same aggregation `ScientificResultsRepository.
get_evidence_dashboard_summary()` serves live to the Evidence Dashboard tab
(`GET /api/ble-scientific-results/evidence-dashboard`). No synthetic values, no
recomputation: this notebook only calls the plotting functions in
`generate_evidence_figures.py` and renders their real output.

Re-run this notebook any time the underlying real results change -- it always
reads current state, never a frozen snapshot.
"""

SETUP_SRC = """import sys
from pathlib import Path

REPO_ROOT = Path.cwd().resolve().parents[1] if Path.cwd().name == "ble" else Path.cwd()
sys.path.insert(0, str(REPO_ROOT / "docs" / "ble"))

from generate_evidence_figures import (
    load_repository, fig_rq1_domains, fig_rq2_branches, fig_confusion,
    fig_per_unit_metrics, fig_risk_coverage, fig_seed_variability,
    fig_computational_cost, fig_per_unit_auxiliary_rq1, sync_consolidated_figures,
)

repo = load_repository()
summary = repo.get_evidence_dashboard_summary()
"""


def _md_cell(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


def _code_cell(source: str, png_path: Path | None) -> dict:
    outputs = []
    if png_path and png_path.is_file():
        b64 = base64.b64encode(png_path.read_bytes()).decode("ascii")
        outputs.append({
            "output_type": "execute_result", "execution_count": 1,
            "data": {"image/png": b64, "text/plain": [f"<Figure: {png_path.name}>"]},
            "metadata": {},
        })
    return {
        "cell_type": "code", "execution_count": 1, "metadata": {}, "outputs": outputs,
        "source": source.splitlines(keepends=True),
    }


def main() -> None:
    cells = [_md_cell(INTRO_MD), _code_cell(SETUP_SRC, None)]
    for markdown, code, png_name in SECTIONS:
        if markdown:
            cells.append(_md_cell(markdown))
        cells.append(_code_cell(code, IMG_DIR / png_name))

    notebook = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.11"},
        },
        "nbformat": 4, "nbformat_minor": 5,
    }
    OUT_PATH.write_text(json.dumps(notebook, indent=1), encoding="utf-8")
    print("wrote", OUT_PATH)


if __name__ == "__main__":
    main()
