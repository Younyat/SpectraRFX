from __future__ import annotations

import hashlib
from typing import Any

from app.modules.rf_experiment_lab.experiment_config_schema import ExperimentSplitConfig


class SplitManager:
    def build_split(self, captures: list[dict[str, Any]], config: ExperimentSplitConfig) -> dict[str, Any]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for capture in captures:
            key = self._group_key(capture, config.group_by)
            groups.setdefault(key, []).append(capture)

        ordered_keys = sorted(groups, key=lambda item: hashlib.sha256(item.encode("utf-8")).hexdigest())
        group_count = len(ordered_keys)
        train_cut = int(round(group_count * config.train_ratio))
        val_cut = train_cut + int(round(group_count * config.validation_ratio))
        train_keys = set(ordered_keys[:train_cut])
        val_keys = set(ordered_keys[train_cut:val_cut])
        test_keys = set(ordered_keys[val_cut:])

        assignments: dict[str, str] = {}
        for key in train_keys:
            for capture in groups[key]:
                assignments[str(capture.get("capture_id"))] = "train"
        for key in val_keys:
            for capture in groups[key]:
                assignments[str(capture.get("capture_id"))] = "validation"
        for key in test_keys:
            for capture in groups[key]:
                assignments[str(capture.get("capture_id"))] = "test"

        return {
            "strategy": config.strategy,
            "group_by": config.group_by,
            "debug_only": config.strategy == "random",
            "scientific_result_allowed": config.strategy != "random",
            "warning": "random split is debug_only and must not be used as the primary scientific result." if config.strategy == "random" else None,
            "group_count": group_count,
            "capture_count": len(captures),
            "counts": {
                "train": sum(1 for value in assignments.values() if value == "train"),
                "validation": sum(1 for value in assignments.values() if value == "validation"),
                "test": sum(1 for value in assignments.values() if value == "test"),
            },
            "assignments": assignments,
            "leakage_check": self.validate_no_group_leakage(captures, assignments, config.group_by),
        }

    def validate_no_group_leakage(
        self,
        captures: list[dict[str, Any]],
        assignments: dict[str, str],
        group_by: list[str],
    ) -> dict[str, Any]:
        seen: dict[str, set[str]] = {}
        for capture in captures:
            capture_id = str(capture.get("capture_id"))
            split = assignments.get(capture_id)
            if not split:
                continue
            key = self._group_key(capture, group_by)
            seen.setdefault(key, set()).add(split)
        leaking = {key: sorted(value) for key, value in seen.items() if len(value) > 1}
        return {
            "passed": not leaking,
            "leaking_groups": leaking,
            "rule": "No capture/session/day/environment/distance/receiver group may appear in multiple splits.",
        }

    def _group_key(self, capture: dict[str, Any], group_by: list[str]) -> str:
        parts = [str(capture.get(field) or f"missing:{field}:{capture.get('capture_id')}") for field in group_by]
        return "|".join(parts)
