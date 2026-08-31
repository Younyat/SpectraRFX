"""Paper progress dashboard, point 1 (2026-08-11): the 6 generic figure
plotters are pure renderers -- these tests feed them explicitly-synthetic
fixture numbers (never touching real repository storage) and confirm a
real, non-empty PDF is produced. Real/absent-data decisions belong to
paper_export.py, tested separately.
"""
from __future__ import annotations

from app.modules.ble_scientific_results.figures.paper_figures import (
    bar_with_ci_figure,
    confusion_matrix_figure,
    ecdf_figure,
    histogram_figure,
    non_inferiority_figure,
    paired_pre_post_figure,
    risk_coverage_figure,
)

# Explicitly synthetic -- used only to exercise the renderer, never written
# to any real repository path.
RQ1_BAR_SYNTHETIC_FIXTURE = {
    "categories": ["capture-dependent", "capture-disjoint", "future"],
    "values": [0.95, 0.78, 0.71],
    "ci_low": [0.90, 0.70, 0.60],
    "ci_high": [0.99, 0.85, 0.80],
}
RQ3_PAIRED_SYNTHETIC_FIXTURE = {
    "unit_ids": ["UNIT-A", "UNIT-B", "UNIT-C"],
    "pre_values": [0.02, 0.03, 0.01],
    "post_values": [0.08, 0.05, 0.04],
}
CONFUSION_MATRIX_SYNTHETIC_FIXTURE = {
    "labels": ["UNIT-A", "UNIT-B"],
    "matrix": [[8, 2], [1, 9]],
}
RISK_COVERAGE_SYNTHETIC_FIXTURE = {
    "coverage": [1.0, 0.8, 0.6, 0.4, 0.2],
    "risk": [0.15, 0.10, 0.07, 0.03, 0.01],
}
LATENCY_SYNTHETIC_FIXTURE = {"values": [10.0, 12.0, 11.5, 30.0, 14.0, 13.0, 12.5]}
PERMUTATION_SYNTHETIC_FIXTURE = {"values": [-0.02, 0.01, 0.00, 0.03, -0.01, 0.02, 0.015, -0.005]}


def _assert_real_pdf(path_str: str) -> None:
    from pathlib import Path
    path = Path(path_str)
    assert path.is_file()
    assert path.suffix == ".pdf"
    assert path.stat().st_size > 200  # a real rendered PDF, not an empty stub
    assert path.read_bytes()[:4] == b"%PDF"


def test_bar_with_ci_figure_writes_real_pdf_svg_and_png(tmp_path):
    # Multi-format output (2026-08-18): the SAME rendering saved as PDF
    # (manuscript), SVG, and PNG (README/dashboard) -- never a second,
    # independently-coded PNG renderer.
    out = bar_with_ci_figure(
        categories=RQ1_BAR_SYNTHETIC_FIXTURE["categories"], values=RQ1_BAR_SYNTHETIC_FIXTURE["values"],
        ci_low=RQ1_BAR_SYNTHETIC_FIXTURE["ci_low"], ci_high=RQ1_BAR_SYNTHETIC_FIXTURE["ci_high"],
        ylabel="Balanced accuracy", title="RQ1 BA by domain", out_path=tmp_path / "rq1_domains.pdf",
    )
    assert set(out.keys()) == {"pdf", "svg", "png"}
    _assert_real_pdf(out["pdf"])
    assert (tmp_path / "rq1_domains.svg").is_file()
    png_path = tmp_path / "rq1_domains.png"
    assert png_path.is_file()
    assert png_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_bar_with_ci_figure_handles_missing_ci_without_error(tmp_path):
    out = bar_with_ci_figure(
        categories=["A", "B"], values=[0.5, 0.6], ci_low=None, ci_high=None,
        ylabel="y", title="t", out_path=tmp_path / "no_ci.pdf",
    )
    _assert_real_pdf(out["pdf"])


def test_paired_pre_post_figure_writes_a_real_pdf(tmp_path):
    out = paired_pre_post_figure(
        unit_ids=RQ3_PAIRED_SYNTHETIC_FIXTURE["unit_ids"], pre_values=RQ3_PAIRED_SYNTHETIC_FIXTURE["pre_values"],
        post_values=RQ3_PAIRED_SYNTHETIC_FIXTURE["post_values"], ylabel="FRR", title="RESET PRE->POST",
        out_path=tmp_path / "rq3_reset.pdf",
    )
    _assert_real_pdf(out)


def test_confusion_matrix_figure_writes_a_real_pdf(tmp_path):
    out = confusion_matrix_figure(
        labels=CONFUSION_MATRIX_SYNTHETIC_FIXTURE["labels"], matrix=CONFUSION_MATRIX_SYNTHETIC_FIXTURE["matrix"],
        title="Confusion matrix (capture-disjoint)", out_path=tmp_path / "confusion.pdf",
    )
    _assert_real_pdf(out)


def test_risk_coverage_figure_writes_a_real_pdf(tmp_path):
    out = risk_coverage_figure(
        coverage=RISK_COVERAGE_SYNTHETIC_FIXTURE["coverage"], risk=RISK_COVERAGE_SYNTHETIC_FIXTURE["risk"],
        title="Risk-coverage", out_path=tmp_path / "risk_coverage.pdf",
    )
    _assert_real_pdf(out)


def test_ecdf_figure_writes_a_real_pdf(tmp_path):
    out = ecdf_figure(values=LATENCY_SYNTHETIC_FIXTURE["values"], xlabel="latency_ms", title="Latency ECDF", out_path=tmp_path / "ecdf.pdf")
    _assert_real_pdf(out)


def test_histogram_figure_writes_a_real_pdf(tmp_path):
    out = histogram_figure(values=PERMUTATION_SYNTHETIC_FIXTURE["values"], bins=10, xlabel="delta_cycle (permuted)", title="Permutation null", out_path=tmp_path / "hist.pdf")
    _assert_real_pdf(out)


def test_non_inferiority_figure_writes_a_real_pdf(tmp_path):
    out = non_inferiority_figure(
        mean_difference=0.02, ci_low=-0.01, margin=0.05, non_inferior=True, title="RQ4 non-inferiority", out_path=tmp_path / "ni.pdf",
    )
    _assert_real_pdf(out)
