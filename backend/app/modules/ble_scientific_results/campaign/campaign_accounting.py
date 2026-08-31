"""Fase 2, Sections C+D: campaign accounting and experimental balance.

Operates ONLY on the four canonical record tables Section B already wrote
under `01_inputs/canonical_records/` (never re-reads ble_rffi_studio
directly) plus the frozen AnalysisContract's own declared design
(`campaign_schedule`, `device_population`, `channels`,
`minimum_independent_blocks`). Every counter here is a real aggregation
over those tables -- never a hardcoded number, never a ratio computed
against an assumed denominator.

Dimensions the protocol's real capture schema cannot populate today
(day_id, capture_order, pre_or_post, intervention_arm, packet_condition,
receiver_epoch -- see capture_records.py) collapse to a single
"NOT_DOCUMENTED" bucket in every balance matrix rather than silently
omitting the dimension or fabricating values for it. This is the expected,
correct output against every real dataset in this repository today.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from app.infrastructure.ble.capture.ble_capture_metadata import atomic_json

from .._shared_pandas import NOT_DOCUMENTED, fillna_not_documented, read_table
from ..contracts import AnalysisContract


def build_campaign_accounting(*, run_dir: Path, contract: AnalysisContract) -> dict[str, Any]:
    records_dir = run_dir / "01_inputs" / "canonical_records"
    accounting_dir = run_dir / "03_campaign_accounting"
    accounting_dir.mkdir(parents=True, exist_ok=True)

    captures = read_table(records_dir, "capture_records")
    bursts = read_table(records_dir, "burst_records")
    windows = read_table(records_dir, "decision_window_records")
    deviations = read_table(records_dir, "campaign_deviations")

    # ------------------------------------------------------------------
    # C: funnel counters
    # ------------------------------------------------------------------
    observed_captures = len(captures)
    missing_captures = int((deviations["deviation_type"] == "CAPTURE_NOT_FOUND").sum()) if not deviations.empty else 0
    duplicate_captures = int((deviations["deviation_type"] == "DUPLICATE_CAPTURE").sum()) if not deviations.empty else 0
    # Deviation classification counts -- kept structurally separate so a
    # normal candidate-level exclusion is never presented as a protocol
    # failure. protocol_deviation_count is the only one that should worry a
    # reader of "did the campaign follow its frozen design".
    protocol_deviation_count = int((deviations["classification"] == "PROTOCOL_DEVIATION").sum()) if not deviations.empty and "classification" in deviations.columns else 0
    capture_exclusion_count = int((deviations["classification"] == "CAPTURE_EXCLUSION").sum()) if not deviations.empty and "classification" in deviations.columns else 0
    candidate_exclusion_count = int((deviations["classification"] == "CANDIDATE_EXCLUSION").sum()) if not deviations.empty and "classification" in deviations.columns else 0

    declared_planned = (contract.campaign_schedule or {}).get("planned_captures")
    planned_captures = declared_planned if declared_planned is not None else observed_captures
    planned_captures_is_declared = declared_planned is not None

    technically_valid = int((captures["capture_quality"] == "PASSED").sum()) if not captures.empty else 0
    captures_with_bursts = int(bursts["capture_id"].nunique()) if not bursts.empty else 0
    captures_with_crc = int(bursts.loc[bursts["burst_class"].isin(["CRC_VALID_PACKET", "TARGET_ASSOCIATED_PACKET"]), "capture_id"].nunique()) if not bursts.empty else 0
    captures_with_target_association = int(bursts.loc[bursts["burst_class"] == "TARGET_ASSOCIATED_PACKET", "capture_id"].nunique()) if not bursts.empty else 0
    eligible_captures = int((captures["capture_eligible"] == True).sum()) if not captures.empty else 0  # noqa: E712

    declared_channels = sorted(set(contract.channels or []))
    observed_channels = sorted(set(int(c) for c in captures["channel"].dropna().unique())) if not captures.empty and "channel" in captures.columns else []
    complete_channel_blocks = len([c for c in declared_channels if c in observed_channels])

    active_windows = int((windows["window_status"] != "INACTIVE").sum()) if not windows.empty else 0
    eligible_windows = int((windows["window_status"] == "ACTIVE_ELIGIBLE").sum()) if not windows.empty else 0

    counters = {
        "planned_captures": planned_captures, "planned_captures_is_declared": planned_captures_is_declared,
        "observed_captures": observed_captures, "missing_captures": missing_captures, "duplicate_captures": duplicate_captures,
        "technically_valid_captures": technically_valid, "captures_with_bursts": captures_with_bursts,
        "captures_with_crc_valid_packets": captures_with_crc, "captures_with_target_association": captures_with_target_association,
        "eligible_captures": eligible_captures,
        # NOT_DOCUMENTED design dimensions -- always 0/0, never fabricated (see module docstring).
        "planned_pre_post_pairs": 0, "complete_pre_post_pairs": 0,
        "planned_intervention_blocks": 0, "valid_intervention_blocks": 0,
        "planned_content_blocks": 0, "complete_content_blocks": 0,
        "planned_channel_blocks": len(declared_channels), "complete_channel_blocks": complete_channel_blocks,
        "active_windows": active_windows, "eligible_windows": eligible_windows,
        "protocol_deviation_count": protocol_deviation_count, "capture_exclusion_count": capture_exclusion_count,
        "candidate_exclusion_count": candidate_exclusion_count,
    }

    # ------------------------------------------------------------------
    # C: exclusion reasons -- one row per object x reason, never collapsed
    # ------------------------------------------------------------------
    # blocking_reason_codes and diagnostic_flags are kept in separate
    # columns -- a blocking reason means the object cannot be used for the
    # corresponding purpose; a diagnostic flag is an observation that does
    # not, by itself, block anything.
    exclusion_rows: list[dict[str, Any]] = []
    if not captures.empty:
        for _, row in captures.iterrows():
            for reason in row.get("blocking_reason_codes") or []:
                exclusion_rows.append({"object_type": "capture", "object_id": row["capture_id"], "kind": "blocking", "reason": reason})
            for flag in row.get("diagnostic_flags") or []:
                exclusion_rows.append({"object_type": "capture", "object_id": row["capture_id"], "kind": "diagnostic", "reason": flag})
    if not bursts.empty:
        for _, row in bursts.iterrows():
            for reason in row.get("blocking_reason_codes") or []:
                exclusion_rows.append({"object_type": "burst", "object_id": row["burst_id"], "kind": "blocking", "reason": reason})
            for flag in row.get("diagnostic_flags") or []:
                exclusion_rows.append({"object_type": "burst", "object_id": row["burst_id"], "kind": "diagnostic", "reason": flag})
    exclusion_frame = pd.DataFrame(exclusion_rows, columns=["object_type", "object_id", "kind", "reason"])
    exclusion_frame.to_csv(accounting_dir / "campaign_exclusion_reasons.csv", index=False)

    # ------------------------------------------------------------------
    # C: missingness -- null counts per column, per table
    # ------------------------------------------------------------------
    missingness_rows: list[dict[str, Any]] = []
    for table_name, frame in (("capture_records", captures), ("burst_records", bursts), ("decision_window_records", windows)):
        if frame.empty:
            continue
        for column in frame.columns:
            null_count = int(frame[column].isna().sum())
            if null_count:
                missingness_rows.append({"table": table_name, "field": column, "null_count": null_count, "total": len(frame)})
    pd.DataFrame(missingness_rows, columns=["table", "field", "null_count", "total"]).to_csv(accounting_dir / "campaign_missingness.csv", index=False)

    # ------------------------------------------------------------------
    # D: balance matrices
    # ------------------------------------------------------------------
    balance: dict[str, Any] = {}
    if not captures.empty:
        filled = fillna_not_documented(captures, ["day_id", "capture_order", "intervention_arm", "packet_condition", "receiver_epoch", "pre_or_post", "physical_unit_id", "channel"])
        filled["physical_unit_id"] = filled["physical_unit_id"].fillna(NOT_DOCUMENTED)

        def pivot(index: str, column: str) -> dict[str, Any]:
            table = pd.pivot_table(filled, index=index, columns=column, values="capture_id", aggfunc="count", fill_value=0)
            return json.loads(table.to_json(orient="index"))

        balance["unit_by_day"] = pivot("physical_unit_id", "day_id")
        balance["unit_by_acquisition_position"] = pivot("physical_unit_id", "capture_order")
        balance["unit_by_intervention_arm"] = pivot("physical_unit_id", "intervention_arm")
        balance["unit_by_channel"] = pivot("physical_unit_id", "channel")
        balance["unit_by_packet_condition"] = pivot("physical_unit_id", "packet_condition")
        balance["day_by_receiver_epoch"] = pivot("day_id", "receiver_epoch")
        balance["day_by_pre_post"] = pivot("day_id", "pre_or_post")
    atomic_json(accounting_dir / "campaign_balance_report.json", balance)

    # ------------------------------------------------------------------
    # Write accounting.json/csv
    # ------------------------------------------------------------------
    atomic_json(accounting_dir / "campaign_accounting.json", counters)
    pd.DataFrame([counters]).to_csv(accounting_dir / "campaign_accounting.csv", index=False)

    return {"counters": counters, "balance": balance, "exclusion_reason_row_count": len(exclusion_frame), "missingness_row_count": len(missingness_rows)}
