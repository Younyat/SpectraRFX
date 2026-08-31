from __future__ import annotations

from typing import Any


class ComparativeEvaluationPipeline:
    def compare(self, legacy: dict[str, Any], new_result: dict[str, Any]) -> dict[str, Any]:
        new_label = str(new_result.get("label") or new_result.get("final_label") or "").lower()
        legacy_text = f"{legacy.get('label', '')} {legacy.get('family', '')}".lower()
        compatible = False
        if "ook" in new_label and any(term in legacy_text for term in ["ook", "ism", "remote"]):
            compatible = True
        if "fsk" in new_label and any(term in legacy_text for term in ["fsk", "ism", "remote"]):
            compatible = True
        if "ofdm" in new_label and any(term in legacy_text for term in ["ofdm", "wifi", "lte"]):
            compatible = True
        return {
            "agreement": compatible,
            "agreement_level": "compatible" if compatible else "different_or_unresolved",
            "comment": "The legacy module provides a band-based hypothesis, while the new module provides time-frequency and model-based evidence.",
        }
