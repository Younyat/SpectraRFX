from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ForensicReportBuilder:
    def build_report(
        self,
        case_id: str,
        evidence_id: str,
        raw_iq_path: str | None,
        metadata_path: str | None,
        stage_1_result: dict[str, Any],
        stage_2_result: dict[str, Any] | None = None,
        detector_mode: str = "morphological_heuristic",
    ) -> dict[str, Any]:
        return {
            "case_id": case_id,
            "evidence_id": evidence_id,
            "sha256_raw_iq": self._sha256(raw_iq_path),
            "sha256_metadata": self._sha256(metadata_path),
            "detector_mode": detector_mode,
            "stage_1_result": stage_1_result,
            "stage_2_result": stage_2_result or {"stage_2_model": "disabled"},
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "chain_of_custody": [
                {
                    "event": "rf_experiment_lab_report_created",
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "tool": "RF Experiment Lab",
                }
            ],
        }

    def _sha256(self, path_value: str | None) -> str | None:
        if not path_value:
            return None
        path = Path(path_value)
        if not path.exists() or not path.is_file():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
