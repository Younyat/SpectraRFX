"""SigMF metadata parser for E6 datasets."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional


def load_sigmf_meta(meta_path: Path) -> dict[str, Any]:
    return json.loads(meta_path.read_text(encoding="utf-8-sig"))


def sigmf_dtype(meta: dict[str, Any], fallback: str = "cf32") -> str:
    g = meta.get("global") or {}
    return str(g.get("core:datatype") or fallback)


def sigmf_sample_rate(meta: dict[str, Any]) -> Optional[float]:
    g = meta.get("global") or {}
    v = g.get("core:sample_rate")
    return float(v) if v is not None else None


def sigmf_center_frequency(meta: dict[str, Any]) -> Optional[float]:
    captures = meta.get("captures")
    if isinstance(captures, list) and captures:
        v = captures[0].get("core:frequency")
        if v is not None:
            return float(v)
    g = meta.get("global") or {}
    v = g.get("core:center_frequency")
    return float(v) if v is not None else None


def sigmf_sample_count(meta: dict[str, Any]) -> Optional[int]:
    ann = meta.get("annotations")
    if isinstance(ann, dict):
        v = ann.get("core:sample_count")
        return int(v) if v is not None else None
    if isinstance(ann, list) and ann:
        v = ann[0].get("core:sample_count")
        return int(v) if v is not None else None
    return None


def kri_wifi_label(meta_path: Path) -> str:
    match = re.search(r"WiFi_air_X310_([^_]+)_", meta_path.name)
    if not match:
        raise ValueError(f"Cannot extract device ID from KRI filename: {meta_path.name}")
    return match.group(1)


def uav_lightbridge_label(meta: dict[str, Any]) -> str:
    ann = meta.get("annotations") or {}
    if isinstance(ann, dict):
        tx = ann.get("transmitter") or {}
        return str(tx.get("core:device_id_genesys_lab") or tx.get("core:UAV") or "unknown_uav")
    return "unknown_uav"


def ieee_cbrs_label(meta: dict[str, Any], meta_path: Path, target: str = "auto") -> str:
    ann_list = meta.get("annotations") or [{}]
    ann = ann_list[0] if isinstance(ann_list, list) else {}
    rx_seid = (ann.get("system_components:receiver") or {}).get("seid")
    tx_block = ann.get("system_components:transmitter") or {}
    tx_ids = []
    for v in tx_block.values():
        if isinstance(v, dict):
            seid = (v.get("signal:emitter") or {}).get("seid")
            if seid:
                tx_ids.append(seid)
    label_field = ann.get("core:label")
    band = meta_path.parent.name
    choices = {
        "tx_combo": "+".join(sorted(tx_ids)),
        "receiver": rx_seid,
        "signal_label": label_field,
        "band": band,
    }
    if target != "auto":
        return str(choices.get(target) or "unknown_ieee")
    # auto: prefer band (folder = bandwidth category, e.g. 5M/10M/15M/20M) —
    # CBRS datasets from IEEE are organised by bandwidth config, not by hardware.
    # tx_combo is only useful when there are genuinely different transmitter sets.
    return str(choices["band"] or choices["tx_combo"] or choices["signal_label"] or choices["receiver"] or "unknown_ieee")
