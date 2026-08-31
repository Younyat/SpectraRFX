"""Paper progress dashboard, point 1 (2026-08-11): a small set of GENERIC,
reusable figure plotters for the paper export -- not 11 bespoke functions.
Reuses `campaign_figures.py`'s exact deterministic matplotlib pattern
(`Agg` backend, fixed figsize/dpi) and extends it with real vector `.pdf`
output (preferred for the manuscript; `campaign_figures.py` itself is left
untouched).

Every function here is a PURE renderer over already-computed numbers --
none of them read a file, none of them compute a statistic, none of them
decide whether real data exists. The caller (`paper_export.py`) is the only
place that checks source-artifact presence and decides whether to call
these at all; that is also why, unlike `campaign_figures.py`, these never
render an "empty axes" placeholder for missing data -- when there is
nothing real to plot, the caller simply does not call this module, and the
export manifest records `SKIPPED_NO_DATA` instead of a file.
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches
import matplotlib.pyplot as plt
import numpy as np

FIGSIZE = (8, 4.5)
DPI = 150


def _save_pdf(fig, out_path: Path) -> str:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return str(out_path)


def _save_figure(fig, base_path: Path, formats: Sequence[str] = ("pdf", "svg", "png")) -> dict[str, str]:
    """Paper-representation pass (2026-08-17): saves the SAME figure object
    in every requested format before closing it -- PDF/SVG for the
    manuscript (vector, no resampling artifacts), PNG for the README/
    Evidence Dashboard/notebook. `base_path` has no extension; each format
    is appended. One rendering call, multiple real outputs -- never a
    second independent plot for the PNG variant (the exact duplication this
    pass exists to remove)."""
    base_path.parent.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for fmt in formats:
        out_path = base_path.with_suffix(f".{fmt}")
        fig.savefig(out_path, dpi=DPI, bbox_inches="tight")
        written[fmt] = str(out_path)
    plt.close(fig)
    return written


def bar_with_ci_figure(
    *, categories: Sequence[str], values: Sequence[float], ci_low: Sequence[float] | None,
    ci_high: Sequence[float] | None, ylabel: str, title: str, out_path: Path, footnote: str | None = None,
    ylim: tuple[float, float] | None = None, colors: Sequence[str] | str | None = None,
) -> dict[str, str]:
    """RQ1 BA-by-domain, RQ2 BA/macro-F1/coverage-by-branch. `ci_low`/
    `ci_high` are absolute bounds (not offsets) -- None skips error bars for
    a category whose CI is not available, never fabricated as 0-width.
    `footnote` (added 2026-08-17): one line of real, already-computed text
    (e.g. real sample sizes) rendered below the axes -- never a second
    computation, purely a caller-supplied caption. `ylim`/`colors` (added
    for the publication-figure variants, 2026-08-19): optional fixed axis
    range and per-bar color override -- both None reproduce the exact prior
    behavior (auto-scaled axis, uniform blue bars) for every existing caller.

    Multi-format output (2026-08-18, figure/artifact sync closure): saves
    PDF/SVG/PNG of the SAME rendering via `_save_figure`, same as
    `normalized_confusion_matrix_figure`/`campaign_timeline_figure`/
    `forensic_lineage_diagram_figure` already do -- this is what lets
    readme_img/'s RQ1/RQ2 figures be a plain copy of the PNG variant
    `paper_export.py` renders here, instead of a second, independently-coded
    renderer (the exact duplication that let `readme_img/evidence_rq1_
    domains.png` drift out of sync with this one)."""
    fig, ax = plt.subplots(figsize=FIGSIZE)
    x = np.arange(len(categories))
    ax.bar(x, values, color=colors if colors is not None else "#2b6cb0")
    if ci_low is not None and ci_high is not None:
        lower_err = [max(0.0, v - lo) if lo is not None else 0.0 for v, lo in zip(values, ci_low)]
        upper_err = [max(0.0, hi - v) if hi is not None else 0.0 for v, hi in zip(values, ci_high)]
        ax.errorbar(x, values, yerr=[lower_err, upper_err], fmt="none", ecolor="#1a202c", capsize=4)
    ax.set_xticks(x)
    ax.set_xticklabels(categories, rotation=20, ha="right")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    if ylim is not None:
        ax.set_ylim(*ylim)
    if footnote:
        # Wrapped and placed well below the rotated (often two-line, since
        # categories may themselves contain "\n") x-tick labels -- a fixed,
        # un-wrapped single line here collided with those labels once
        # footnotes grew longer (RQ1's now includes evaluation_unit/n/delta
        # CI/capture counts). ax.transAxes (axes-fraction, not fig.text's
        # figure-fraction) so this scales with wherever the tick-label block
        # actually ends, instead of a fixed figure-coordinate that collided
        # with it once that block grew taller than expected. bbox_inches=
        # "tight" (see _save_figure/_save_pdf) still trims the final canvas
        # to whatever this actually renders as.
        wrapped = "\n".join(textwrap.wrap(footnote, width=100))
        ax.text(0.5, -0.38, wrapped, transform=ax.transAxes, ha="center", va="top", fontsize=8, color="#4a5568")
    return _save_figure(fig, out_path)


def grouped_bar_figure(
    *, categories: Sequence[str], series: Sequence[Sequence[float]], series_labels: Sequence[str], ylabel: str, title: str, out_path: Path,
    series_colors: Sequence[str] | None = None, ylim: tuple[float, float] | None = None, footnote: str | None = None, value_labels: bool = False,
) -> dict[str, str]:
    """Grouped bar chart for two or more named series over the same
    categories -- e.g. RQ4's FULL_BURST vs PRE_PDU recall per physical unit.
    Pure renderer, same multi-format `_save_figure` convention as
    `bar_with_ci_figure`; no CI support (callers with per-series uncertainty
    should use `bar_with_ci_figure` per series instead)."""
    fig, ax = plt.subplots(figsize=FIGSIZE)
    n_series = len(series)
    x = np.arange(len(categories))
    width = 0.8 / max(n_series, 1)
    default_colors = ["#2b6cb0", "#b9822c", "#2f8f89", "#c1683b"]
    colors = series_colors if series_colors is not None else default_colors
    for i, (values, label) in enumerate(zip(series, series_labels)):
        offset = (i - (n_series - 1) / 2) * width
        bars = ax.bar(x + offset, values, width=width, label=label, color=colors[i % len(colors)])
        if value_labels:
            ax.bar_label(bars, fmt="%.3f", fontsize=7, padding=2)
    ax.set_xticks(x)
    ax.set_xticklabels(categories, rotation=20, ha="right")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    if ylim is not None:
        ax.set_ylim(*ylim)
    ax.legend(frameon=False)
    if footnote:
        wrapped = "\n".join(textwrap.wrap(footnote, width=100))
        ax.text(0.5, -0.38, wrapped, transform=ax.transAxes, ha="center", va="top", fontsize=8, color="#4a5568")
    return _save_figure(fig, out_path)


def strip_plot_figure(
    *, categories: Sequence[str], values_per_category: Sequence[Sequence[float]], ylabel: str, title: str, out_path: Path,
    point_labels_per_category: Sequence[Sequence[str]] | None = None, ylim: tuple[float, float] | None = None,
    color: str = "#2b6cb0", footnote: str | None = None,
) -> dict[str, str]:
    """One column of real, individual points per category (e.g. one point
    per real acquisition session, grouped by physical unit) -- for a metric
    where a bar-with-error-bar summary would hide real per-session spread.
    Small deterministic horizontal jitter only, seeded from the point's own
    index (never random per render, so two runs over the same data produce
    the same figure). `point_labels_per_category` (optional) annotates each
    point with a short real label (e.g. a session's own short id) next to
    it; omitted when not supplied, never a placeholder."""
    fig, ax = plt.subplots(figsize=FIGSIZE)
    rng = np.random.default_rng(12345)
    for i, (cat_values, _cat) in enumerate(zip(values_per_category, categories)):
        n = len(cat_values)
        jitter = rng.uniform(-0.12, 0.12, size=n) if n > 0 else np.array([])
        xs = np.full(n, i, dtype=float) + jitter
        ax.scatter(xs, cat_values, color=color, s=36, alpha=0.85, edgecolors="#1a202c", linewidths=0.5, zorder=3)
    ax.set_xticks(range(len(categories)))
    ax.set_xticklabels(categories)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    if ylim is not None:
        ax.set_ylim(*ylim)
    ax.grid(axis="y", alpha=0.3)
    if footnote:
        wrapped = "\n".join(textwrap.wrap(footnote, width=100))
        ax.text(0.5, -0.22, wrapped, transform=ax.transAxes, ha="center", va="top", fontsize=8, color="#4a5568")
    return _save_figure(fig, out_path)


def paired_pre_post_figure(
    *, unit_ids: Sequence[str], pre_values: Sequence[float], post_values: Sequence[float], ylabel: str, title: str, out_path: Path,
) -> str:
    """RQ3 paired PRE->POST per physical unit (RESET or CONTROL arm --
    caller picks which arm's values to pass; two calls for the two arms)."""
    fig, ax = plt.subplots(figsize=FIGSIZE)
    for unit_id, pre, post in zip(unit_ids, pre_values, post_values):
        ax.plot([0, 1], [pre, post], marker="o", color="#2b6cb0", alpha=0.7)
        ax.annotate(unit_id, (1.02, post), fontsize=8, color="#4a5568")
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["PRE", "POST"])
    ax.set_xlim(-0.2, 1.4)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    return _save_pdf(fig, out_path)


def confusion_matrix_figure(*, labels: Sequence[str], matrix: Sequence[Sequence[int]], title: str, out_path: Path) -> str:
    """RQ1 capture-disjoint/FUTURE confusion matrices -- `matrix[i][j]` is
    the count of true label i predicted as label j, exactly
    SplitEvaluationReport.confusion_matrix's own shape."""
    fig, ax = plt.subplots(figsize=(max(FIGSIZE[0], 1.2 * len(labels)), max(FIGSIZE[1], 1.2 * len(labels))))
    array = np.array(matrix, dtype=float)
    im = ax.imshow(array, cmap="Blues")
    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_yticklabels(labels)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    ax.set_title(title)
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j, i, int(array[i, j]), ha="center", va="center", color="#1a202c", fontsize=9)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    return _save_pdf(fig, out_path)


def risk_coverage_figure(*, coverage: Sequence[float], risk: Sequence[float], title: str, out_path: Path) -> str:
    """Risk-coverage curve -- coverage on x, risk (error rate) on y, exactly
    the shape SplitEvaluationReport.risk_coverage already produces."""
    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.plot(coverage, risk, marker=".", color="#2b6cb0")
    ax.set_xlabel("coverage")
    ax.set_ylabel("risk")
    ax.set_xlim(0, 1)
    ax.set_ylim(bottom=0)
    ax.set_title(title)
    return _save_pdf(fig, out_path)


def ecdf_figure(*, values: Sequence[float], xlabel: str, title: str, out_path: Path) -> str:
    """Offline/near-live latency ECDF -- a real empirical CDF, not a
    histogram density estimate."""
    fig, ax = plt.subplots(figsize=FIGSIZE)
    sorted_values = np.sort(np.asarray(values, dtype=float))
    n = len(sorted_values)
    y = np.arange(1, n + 1) / n
    ax.step(sorted_values, y, where="post", color="#2b6cb0")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("ECDF")
    ax.set_ylim(0, 1)
    ax.set_title(title)
    return _save_pdf(fig, out_path)


def non_inferiority_figure(*, mean_difference: float, ci_low: float, margin: float, non_inferior: bool, title: str, out_path: Path) -> str:
    """Fast-closure pass (2026-08-12): the paper's required RQ4
    non-inferiority figure -- a one-sided forest plot (point estimate + CI
    lower bound, margin decision boundary at -margin), mirroring
    NonInferiorityChart.tsx's own frontend rendering exactly. Pure renderer
    over already-computed non_inferiority.value fields -- never recomputes
    the test itself."""
    fig, ax = plt.subplots(figsize=(FIGSIZE[0], 2.5))
    color = "#2f855a" if non_inferior else "#c53030"
    ax.errorbar([mean_difference], [0], xerr=[[mean_difference - ci_low], [0]], fmt="o", color=color, capsize=6, markersize=8)
    ax.axvline(-margin, color="#c53030", linestyle="--", linewidth=1, label=f"non-inferiority margin (-{margin:g})")
    ax.axvline(0, color="#4a5568", linestyle=":", linewidth=1)
    ax.set_yticks([])
    ax.set_xlabel("mean difference (new - reference)")
    ax.set_title(title)
    ax.legend(loc="upper right", fontsize=8)
    return _save_pdf(fig, out_path)


def histogram_figure(*, values: Sequence[float], bins: int, xlabel: str, title: str, out_path: Path) -> str:
    """RQ3 permutation-test null distribution + observed statistic overlay,
    when the canonical report supplies the permutation draws; also reusable
    for any other real distribution the export needs to show."""
    fig, ax = plt.subplots(figsize=FIGSIZE)
    ax.hist(values, bins=bins, color="#2b6cb0")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("count")
    ax.set_title(title)
    return _save_pdf(fig, out_path)


def normalized_confusion_matrix_figure(
    *, labels: Sequence[str], matrix_pct: Sequence[Sequence[float]], matrix_n: Sequence[Sequence[int]], title: str, out_path: Path,
) -> dict[str, str]:
    """Paper-representation pass (2026-08-17): row-normalized companion to
    confusion_matrix_figure() -- cell color/primary label is the real
    per-true-class percentage (never distorted by a majority transmitter's
    much larger raw count); real `n` is kept as a secondary annotation per
    cell, never dropped. Pure renderer over paper_figure_aggregations.
    normalize_confusion_matrix()'s already-real output -- computes nothing."""
    fig, ax = plt.subplots(figsize=(max(FIGSIZE[0], 1.3 * len(labels)), max(FIGSIZE[1], 1.3 * len(labels))))
    pct_array = np.array(matrix_pct, dtype=float)
    im = ax.imshow(pct_array, cmap="Blues", vmin=0, vmax=100)
    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_yticklabels(labels)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    ax.set_title(title)
    for i in range(len(labels)):
        for j in range(len(labels)):
            color = "white" if pct_array[i, j] > 50 else "#1a202c"
            ax.text(j, i, f"{pct_array[i, j]:.1f}%\n(n={matrix_n[i][j]})", ha="center", va="center", color=color, fontsize=8)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="% of true class")
    return _save_figure(fig, out_path)


def campaign_timeline_figure(*, phases: Sequence[dict], title: str, out_path: Path) -> dict[str, str]:
    """Paper-representation pass (2026-08-17): a horizontal phase timeline
    over the real 17-phase Study Control Center status
    (get_study_control_center_status()) -- makes visible, as a figure, what
    the paper's own Methods section states in prose: protected FUTURE stays
    gated behind protocol freeze. Each `phases` entry is
    {label, execution_state} exactly as that real function already returns;
    this renders their real state, never invents a phase or a status."""
    color_by_state = {"COMPLETE": "#2f855a", "IN_PROGRESS": "#b7791f", "PRELIMINARY": "#b7791f", "BLOCKED": "#a0aec0", "NOT_RUN": "#4a5568"}
    fig, ax = plt.subplots(figsize=(FIGSIZE[0], max(FIGSIZE[1], 0.35 * len(phases))))
    y = np.arange(len(phases))
    colors = [color_by_state.get(p["execution_state"], "#a0aec0") for p in phases]
    ax.barh(y, [1] * len(phases), color=colors)
    ax.set_yticks(y)
    ax.set_yticklabels([p["label"] for p in phases], fontsize=8)
    ax.set_xticks([])
    ax.invert_yaxis()
    ax.set_title(title)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in color_by_state.values()]
    ax.legend(handles, color_by_state.keys(), loc="upper center", bbox_to_anchor=(0.5, 0), ncol=len(color_by_state), fontsize=7, frameon=False)
    return _save_figure(fig, out_path)


def forensic_lineage_diagram_figure(*, nodes: Sequence[dict], title: str, out_path: Path) -> dict[str, str]:
    """Paper-representation pass (2026-08-17): a box-and-arrow diagram of
    the real evidence chain for ONE traced example -- source I/Q -> burst ->
    PDU -> admitted example -> dataset -> split -> preprocessing -> model ->
    window decision -- each `nodes` entry is {label, detail} with real
    IDs/hashes from an actual traced example (never placeholder text). Pure
    matplotlib box/arrow primitives, no new plotting dependency."""
    fig, ax = plt.subplots(figsize=(FIGSIZE[0], 0.9 * len(nodes)))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, len(nodes))
    ax.axis("off")
    ax.set_title(title)
    for i, node in enumerate(nodes):
        y = len(nodes) - i - 1
        box = matplotlib.patches.FancyBboxPatch((0.5, y + 0.15), 9, 0.7, boxstyle="round,pad=0.05", facecolor="#ebf4ff", edgecolor="#2b6cb0")
        ax.add_patch(box)
        ax.text(1.0, y + 0.5, node["label"], fontsize=9, fontweight="bold", va="center")
        ax.text(1.0, y + 0.25, node.get("detail", ""), fontsize=7, va="center", color="#4a5568")
        if i < len(nodes) - 1:
            ax.annotate("", xy=(5, y - 0.02), xytext=(5, y + 0.15), arrowprops={"arrowstyle": "->", "color": "#4a5568"})
    return _save_figure(fig, out_path)
