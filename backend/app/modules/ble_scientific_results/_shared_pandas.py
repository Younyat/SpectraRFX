"""Tiny helpers shared by campaign_accounting.py and quality_summary.py --
both need the same "fields ble_rffi_studio's real schema cannot populate
collapse to one NOT_DOCUMENTED bucket, never a fabricated value" rule."""
from __future__ import annotations

import pandas as pd

NOT_DOCUMENTED = "NOT_DOCUMENTED"


def read_table(records_dir, name: str) -> pd.DataFrame:
    import json
    from pathlib import Path

    path = Path(records_dir) / f"{name}.json"
    if not path.is_file():
        return pd.DataFrame()
    rows = json.loads(path.read_text(encoding="utf-8"))
    return pd.DataFrame(rows)


def fillna_not_documented(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    frame = frame.copy()
    for column in columns:
        if column not in frame.columns:
            frame[column] = NOT_DOCUMENTED
        else:
            frame[column] = frame[column].fillna(NOT_DOCUMENTED)
    return frame
