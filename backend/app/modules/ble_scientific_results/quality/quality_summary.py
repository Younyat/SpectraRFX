"""Fase 2, Section E: descriptive quality summaries. Purely descriptive --
count/mean/median/std/min/max/quartiles/missing count, grouped by the 8
dimensions the user's specification names. No confidence interval, no
p-value, no hypothesis test anywhere in this module (that is Fase 3+,
RQ1-4/S1-S2, explicitly out of scope here).

Operates only on the canonical capture_records/burst_records/
decision_window_records tables Section B already wrote -- never re-reads
ble_rffi_studio directly. Grouping dimensions this repository's real
capture schema cannot populate today (intervention_arm, packet_condition,
receiver_epoch, day_id -- unless a capture went through
paper_campaign_runner.py) collapse to a single NOT_DOCUMENTED group rather
than being silently dropped -- the descriptive table for that dimension
still exists, it just has one honestly-labeled row.

**Association timing residual policy (documented here verbatim, not
re-derived)**: `ASSOCIATION_TIME_THRESHOLD_MS = 250.0` is the exact
constant `_associate()` hardcodes in `ble_offline_replay.py` (also restated
in `records/burst_records.py::ASSOCIATION_TIME_THRESHOLD_MS`, the two are
required to never drift apart). How it was selected: **not documented in
code** -- it is a hardcoded value with no recorded calibration study behind
it (confirmed by reading `ble_offline_replay.py`; this module states that
honestly rather than inventing a justification). Native-callback batching
policy: **no explicit batching by "callback batch" exists** -- the closest
real grouping available is `capture_id` (one native-scan session per
capture), used as the practical batching unit below. Duplicate policy: each
native observation is consumed by at most one decoded packet, first-come in
decoded-packet iteration order (`used.add(...)` in `_associate()`).
Tie-breaking policy: **none beyond iteration order** -- a real, documented
limitation, not a designed rule. A field campaign calibration of the native
adapter's real callback delay (to justify or revise the 250 ms threshold)
requires real hardware and has not been performed as part of this pass --
same status as the physical pilot (see PILOT_CHECKLIST.md).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from app.infrastructure.ble.capture.ble_capture_metadata import atomic_json

from .._shared_pandas import fillna_not_documented, read_table

GROUP_DIMENSIONS = ["physical_unit_id", "day_id", "session_id", "pre_or_post", "intervention_arm", "channel", "packet_condition", "receiver_epoch"]

# The exact constant records/burst_records.py enforces -- restated here for
# the docstring above, never re-derived independently.
ASSOCIATION_TIME_THRESHOLD_MS = 250.0

# Only columns that genuinely exist with real, non-fabricated values on the
# canonical records qualify here. SNR/noise/signal-power/clipping/near-zero/
# occupied-bandwidth/frequency-offset have no source at capture OR burst
# granularity in ble_rffi_studio today (see capture_records.py and
# burst_records.py's own not_documented_fields) -- they are deliberately
# absent from this list rather than described from a column of nulls.
CAPTURE_NUMERIC_FIELDS = ["duration_s", "observed_samples", "expected_samples", "overflow_count", "discontinuity_count"]
WINDOW_NUMERIC_FIELDS = ["candidate_count", "crc_valid_count", "target_associated_count", "eligible_count"]


def _describe(frame: pd.DataFrame, group_cols: list[str], value_cols: list[str]) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    present_group_cols = [c for c in group_cols if c in frame.columns]
    present_value_cols = [c for c in value_cols if c in frame.columns]
    if not present_group_cols or not present_value_cols:
        return []
    filled = fillna_not_documented(frame, present_group_cols)
    rows: list[dict[str, Any]] = []
    grouped = filled.groupby(present_group_cols, dropna=False)
    for group_key, group_frame in grouped:
        if not isinstance(group_key, tuple):
            group_key = (group_key,)
        for value_col in present_value_cols:
            series = pd.to_numeric(group_frame[value_col], errors="coerce")
            non_null = series.dropna()
            row = dict(zip(present_group_cols, group_key))
            row["field"] = value_col
            row["n"] = int(len(group_frame))
            row["missing_count"] = int(series.isna().sum())
            if non_null.empty:
                row.update({"mean": None, "median": None, "std": None, "min": None, "max": None, "q1": None, "q3": None})
            else:
                row.update({
                    "mean": float(non_null.mean()), "median": float(non_null.median()),
                    "std": float(non_null.std()) if len(non_null) > 1 else 0.0,
                    "min": float(non_null.min()), "max": float(non_null.max()),
                    "q1": float(non_null.quantile(0.25)), "q3": float(non_null.quantile(0.75)),
                })
            rows.append(row)
    return rows


def build_quality_summary(*, run_dir: Path) -> dict[str, Any]:
    records_dir = run_dir / "01_inputs" / "canonical_records"
    quality_dir = run_dir / "04_quality"
    quality_dir.mkdir(parents=True, exist_ok=True)

    captures = read_table(records_dir, "capture_records")
    bursts = read_table(records_dir, "burst_records")
    windows = read_table(records_dir, "decision_window_records")

    summary_rows = _describe(captures, GROUP_DIMENSIONS, CAPTURE_NUMERIC_FIELDS)
    unit_day_rows = _describe(captures, ["physical_unit_id", "day_id"], CAPTURE_NUMERIC_FIELDS)
    window_rows = _describe(windows, GROUP_DIMENSIONS, WINDOW_NUMERIC_FIELDS)

    # Association summary: real, checkable fields -- CRC-valid rate,
    # association coverage, association timing residual (real per-burst
    # fields from packet_association_ledger.jsonl, via ScientificBurstRecord).
    # One global aggregate row (unchanged, for quick reference) PLUS a full
    # distribution broken out by capture/device/day/association_status --
    # a single mean can never be presented as "the" residual again.
    association_rows: list[dict[str, Any]] = []
    residual_distribution_rows: list[dict[str, Any]] = []
    if not bursts.empty:
        total = len(bursts)
        # CRC validity is the candidate's OWN decode outcome (crc_status),
        # never inferred from burst_class -- burst_class encodes IDENTITY
        # STRENGTH (see burst_records.py), which is an orthogonal axis: a
        # CRC-valid packet can land in any of the three burst_class values
        # depending on what identity evidence exists for it (e.g. disabled
        # via STRONG_ASSOCIATION_DISABLED_UNTIL_POLICY_FROZEN moves a
        # CRC-valid, operator-declared packet to SOURCE_CONTEXT_ONLY without
        # its CRC status changing at all).
        crc_valid = int((bursts["crc_status"] == "VALID").sum())
        associated = int(bursts["association_status"].notna().sum())
        residuals = pd.to_numeric(bursts.get("association_time_residual_ms"), errors="coerce").dropna()
        above_threshold = int((residuals > ASSOCIATION_TIME_THRESHOLD_MS).sum())
        association_rows.append({
            "capture_count": int(bursts["capture_id"].nunique()), "burst_count": total,
            "crc_valid_rate": (crc_valid / total) if total else None,
            "association_coverage": (associated / total) if total else None,
            "association_time_residual_ms_mean": float(residuals.mean()) if not residuals.empty else None,
            "association_time_residual_ms_n": int(len(residuals)),
            "association_time_threshold_ms": ASSOCIATION_TIME_THRESHOLD_MS,
            "residuals_above_threshold_count": above_threshold,
        })

        # capture_id doubles as the practical "native callback batch" unit
        # (see module docstring -- no finer batching concept exists).
        joined = bursts.copy()
        if not captures.empty:
            join_cols = [c for c in ("capture_id", "physical_unit_id", "day_id") if c in captures.columns]
            joined = joined.merge(captures[join_cols], on="capture_id", how="left", suffixes=("", "_capture"))
        for group_col in ("physical_unit_id", "day_id"):
            if group_col not in joined.columns:
                joined[group_col] = None
        joined = fillna_not_documented(joined, ["physical_unit_id", "day_id", "association_status"])
        joined["capture_id"] = joined["capture_id"].fillna("NOT_DOCUMENTED")

        for group_key, group_frame in joined.groupby(["capture_id", "physical_unit_id", "day_id", "association_status"], dropna=False):
            series = pd.to_numeric(group_frame["association_time_residual_ms"], errors="coerce").dropna()
            row = dict(zip(["capture_id", "physical_unit_id", "day_id", "association_status"], group_key))
            row["count"] = int(len(series))
            if series.empty:
                row.update({"median": None, "p75": None, "p90": None, "p95": None, "maximum": None, "iqr": None})
            else:
                q1, q3 = float(series.quantile(0.25)), float(series.quantile(0.75))
                row.update({
                    "median": float(series.median()), "p75": float(series.quantile(0.75)), "p90": float(series.quantile(0.90)),
                    "p95": float(series.quantile(0.95)), "maximum": float(series.max()), "iqr": q3 - q1,
                })
            residual_distribution_rows.append(row)

    pd.DataFrame(summary_rows).to_csv(quality_dir / "quality_summary.csv", index=False)
    atomic_json(quality_dir / "quality_summary.json", {"capture_field_summary": summary_rows, "window_field_summary": window_rows})
    pd.DataFrame(unit_day_rows).to_csv(quality_dir / "quality_by_unit_day.csv", index=False)
    pd.DataFrame(association_rows).to_csv(quality_dir / "association_summary.csv", index=False)
    pd.DataFrame(residual_distribution_rows).to_csv(quality_dir / "association_timing_residual_distribution.csv", index=False)

    return {
        "capture_field_summary": summary_rows, "window_field_summary": window_rows, "unit_day_summary": unit_day_rows,
        "association_summary": association_rows, "association_timing_residual_distribution": residual_distribution_rows,
    }
