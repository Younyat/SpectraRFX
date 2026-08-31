"""Fase 2, Section F: 8 descriptive figures, deterministic (fixed figsize/
dpi, Agg backend, no system-font/color dependence), each reading ONLY from
the CSV/JSON already written by Sections B/C/D/E -- never from in-memory
state or the frontend. No ROC/DET/risk-coverage/p-value/confidence-interval/
model-ranking/RQ-conclusion figure exists here -- that is Fase 3+,
explicitly out of scope.

Where the underlying dimension is NOT_DOCUMENTED in every real dataset
today (SNR, acquisition order), the figure is still generated -- it shows
an honest "no data available" panel instead of a fabricated bar.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

FIGSIZE = (8, 4.5)
DPI = 150


def _empty_axes(ax, title: str, message: str) -> None:
    ax.set_title(title)
    ax.text(0.5, 0.5, message, ha="center", va="center", transform=ax.transAxes, fontsize=11, color="#666666")
    ax.set_xticks([])
    ax.set_yticks([])


def _save(fig, out_dir: Path, name: str) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for suffix in (".svg", ".png"):
        path = out_dir / f"{name}{suffix}"
        fig.savefig(path, dpi=DPI, bbox_inches="tight")
        written.append(str(path))
    plt.close(fig)
    return written


def _read_json(path: Path) -> dict | list | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def build_campaign_figures(*, run_dir: Path) -> list[str]:
    accounting_dir = run_dir / "03_campaign_accounting"
    quality_dir = run_dir / "04_quality"
    records_dir = run_dir / "01_inputs" / "canonical_records"
    out_dir = run_dir / "07_figures"

    written: list[str] = []
    counters = _read_json(accounting_dir / "campaign_accounting.json") or {}

    # 1. Campaign_Attrition
    fig, ax = plt.subplots(figsize=FIGSIZE)
    stages = ["planned_captures", "observed_captures", "technically_valid_captures", "captures_with_bursts", "captures_with_crc_valid_packets", "captures_with_target_association", "eligible_captures"]
    values = [counters.get(s, 0) or 0 for s in stages]
    if any(values):
        ax.barh(range(len(stages)), values, color="#2b6cb0")
        ax.set_yticks(range(len(stages)))
        ax.set_yticklabels(stages)
        ax.invert_yaxis()
        ax.set_xlabel("Captures")
        ax.set_title("Campaign Attrition")
    else:
        _empty_axes(ax, "Campaign Attrition", "No campaign_accounting.json data available -- run build-records first.")
    written += _save(fig, out_dir, "Campaign_Attrition")

    # 2. Campaign_Design_Completeness
    fig, ax = plt.subplots(figsize=FIGSIZE)
    dims = [("channel_blocks", counters.get("planned_channel_blocks", 0), counters.get("complete_channel_blocks", 0))]
    if dims and dims[0][1]:
        labels = [d[0] for d in dims]
        planned = [d[1] for d in dims]
        complete = [d[2] for d in dims]
        x = range(len(labels))
        ax.bar([i - 0.2 for i in x], planned, width=0.4, label="planned", color="#a0aec0")
        ax.bar([i + 0.2 for i in x], complete, width=0.4, label="complete", color="#2f855a")
        ax.set_xticks(list(x))
        ax.set_xticklabels(labels)
        ax.legend()
        ax.set_title("Campaign Design Completeness")
    else:
        _empty_axes(ax, "Campaign Design Completeness", "No design dimension was declared as planned in the frozen protocol.")
    written += _save(fig, out_dir, "Campaign_Design_Completeness")

    # 3. Capture_Quality_By_Unit_Day
    unit_day = _read_csv(quality_dir / "quality_by_unit_day.csv")
    fig, ax = plt.subplots(figsize=FIGSIZE)
    duration_rows = unit_day[unit_day.get("field") == "duration_s"] if not unit_day.empty and "field" in unit_day.columns else pd.DataFrame()
    if not duration_rows.empty and "physical_unit_id" in duration_rows.columns:
        ax.errorbar(range(len(duration_rows)), duration_rows["mean"], yerr=duration_rows["std"], fmt="o", color="#2b6cb0")
        ax.set_xticks(range(len(duration_rows)))
        ax.set_xticklabels(duration_rows["physical_unit_id"], rotation=45, ha="right")
        ax.set_ylabel("duration_s (mean +/- std)")
        ax.set_title("Capture Quality by Unit/Day")
    else:
        _empty_axes(ax, "Capture Quality by Unit/Day", "No quality_by_unit_day.csv data available.")
    written += _save(fig, out_dir, "Capture_Quality_By_Unit_Day")

    # 4. SNR_By_Unit_Day -- honestly empty on every real dataset today.
    fig, ax = plt.subplots(figsize=FIGSIZE)
    _empty_axes(ax, "SNR by Unit/Day", "NOT_DOCUMENTED: no per-capture or per-burst SNR field exists anywhere in ble_rffi_studio's real schema today.")
    written += _save(fig, out_dir, "SNR_By_Unit_Day")

    # 5. CRC_And_Association_Rates
    association = _read_csv(quality_dir / "association_summary.csv")
    fig, ax = plt.subplots(figsize=FIGSIZE)
    if not association.empty:
        row = association.iloc[0]
        labels = ["crc_valid_rate", "association_coverage"]
        values = [row.get("crc_valid_rate") or 0, row.get("association_coverage") or 0]
        ax.bar(labels, values, color=["#2b6cb0", "#805ad5"])
        ax.set_ylim(0, 1)
        ax.set_title(f"CRC and Association Rates (n={int(row.get('burst_count', 0))})")
    else:
        _empty_axes(ax, "CRC and Association Rates", "No association_summary.csv data available.")
    written += _save(fig, out_dir, "CRC_And_Association_Rates")

    # 6. Association_Timing_Residuals -- histogram from the canonical burst table (Section B), not an aggregate.
    bursts_path = records_dir / "burst_records.json"
    fig, ax = plt.subplots(figsize=FIGSIZE)
    bursts_payload = _read_json(bursts_path)
    residuals = pd.Series(dtype=float)
    if bursts_payload:
        frame = pd.DataFrame(bursts_payload)
        if "association_time_residual_ms" in frame.columns:
            residuals = pd.to_numeric(frame["association_time_residual_ms"], errors="coerce").dropna()
    if not residuals.empty:
        ax.hist(residuals, bins=30, color="#2b6cb0")
        ax.set_xlabel("association_time_residual_ms")
        ax.set_ylabel("count")
        ax.set_title(f"Association Timing Residuals (n={len(residuals)})")
    else:
        _empty_axes(ax, "Association Timing Residuals", "No association_time_residual_ms values available (0 associated bursts, or field absent).")
    written += _save(fig, out_dir, "Association_Timing_Residuals")

    # 7. Missingness_And_Exclusions
    missingness = _read_csv(accounting_dir / "campaign_missingness.csv")
    exclusions = _read_csv(accounting_dir / "campaign_exclusion_reasons.csv")
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5))
    if not missingness.empty:
        top = missingness.sort_values("null_count", ascending=False).head(10)
        ax1.barh(top["field"], top["null_count"], color="#c05621")
        ax1.invert_yaxis()
        ax1.set_title("Top missing fields")
    else:
        _empty_axes(ax1, "Missingness", "No missingness data available.")
    if not exclusions.empty:
        counts = exclusions["reason"].value_counts().head(10)
        ax2.barh(counts.index, counts.values, color="#c53030")
        ax2.invert_yaxis()
        ax2.set_title("Top exclusion reasons")
    else:
        _empty_axes(ax2, "Exclusions", "No exclusion data available.")
    written += _save(fig, out_dir, "Missingness_And_Exclusions")

    # 8. Acquisition_Order_Balance -- capture_order is NOT_DOCUMENTED today.
    fig, ax = plt.subplots(figsize=FIGSIZE)
    _empty_axes(ax, "Acquisition Order Balance", "NOT_DOCUMENTED: no capture_order field exists anywhere in ble_rffi_studio's real capture schema today.")
    written += _save(fig, out_dir, "Acquisition_Order_Balance")

    return written
