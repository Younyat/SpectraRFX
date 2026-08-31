from __future__ import annotations

from typing import Any


class DecisionFusionPipeline:
    method = "waterfall_visual_mlp_bispectral_fusion"

    def fuse(
        self,
        region: dict[str, Any] | None,
        visual: dict[str, Any] | None,
        mlp: dict[str, Any] | None,
        spectral_features: dict[str, Any] | None,
        bispectral_features: dict[str, Any] | None,
        legacy_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not region:
            return {
                "final_label": "unknown",
                "final_confidence": 0.0,
                "decision_status": "unknown",
                "method": self.method,
                "agreement": None,
                "evidence": {},
                "limitations": self._limitations(),
            }
        visual_label = (visual or {}).get("label", "unknown")
        mlp_label = (mlp or {}).get("label", "unknown")
        visual_conf = float((visual or {}).get("confidence", 0.0))
        mlp_conf = float((mlp or {}).get("confidence", 0.0))
        snr_db = float((spectral_features or {}).get("snr_db", 0.0))
        phase_coupling = float((bispectral_features or {}).get("phase_coupling_score", 0.0))
        nonlinear_ratio = float((bispectral_features or {}).get("nonlinear_energy_ratio", 0.0))
        context = self._legacy_context(region, legacy_result)

        if visual_label == mlp_label and visual_label != "unknown":
            label = visual_label
            confidence = min(0.97, (visual_conf * 0.55) + (mlp_conf * 0.35) + 0.1)
            status = "accepted"
        elif visual_label == "unknown" and mlp_label == "unknown":
            label = "unknown"
            confidence = max(visual_conf, mlp_conf) * 0.5
            status = "unknown"
        else:
            label = "ambiguous"
            confidence = max(visual_conf, mlp_conf) * 0.65
            status = "ambiguous"

        if snr_db < 6.0:
            confidence *= 0.72
            if phase_coupling > 0.55 and nonlinear_ratio > 0.35:
                confidence = min(confidence + 0.08, 0.88)
        elif snr_db > 15.0:
            confidence = min(confidence + 0.04, 0.98)

        label, confidence, status, context_notes = self._apply_contextual_consistency(
            label,
            confidence,
            status,
            region,
            legacy_result,
            context,
        )
        legacy_agreement = self._legacy_agreement(label, legacy_result)
        evidence = {
            "region_detection": region,
            "visual_classification": visual or {},
            "mlp_membership": mlp or {},
            "spectral_features": spectral_features or {},
            "bispectral_features": bispectral_features or {},
            "legacy_context": context,
            "contextual_consistency": context_notes,
        }
        if phase_coupling > 0.55 and nonlinear_ratio > 0.35:
            evidence["transmitter_specific_fingerprint_evidence"] = {
                "status": "possible",
                "reason": "Strong bispectral phase coupling and nonlinear energy were observed.",
            }
        return {
            "final_label": label,
            "final_confidence": float(max(0.0, min(confidence, 1.0))),
            "decision_status": status,
            "method": self.method,
            "agreement": legacy_agreement,
            "evidence": evidence,
            "limitations": self._limitations(),
        }

    def _legacy_agreement(self, label: str, legacy_result: dict[str, Any] | None) -> str | None:
        if not legacy_result or label in {"unknown", "ambiguous"}:
            return None
        legacy_text = f"{legacy_result.get('label', '')} {legacy_result.get('family', '')}".lower()
        if "ook" in label and ("ook" in legacy_text or "remote" in legacy_text or "ism" in legacy_text):
            return "compatible"
        if "fsk" in label and ("fsk" in legacy_text or "remote" in legacy_text or "ism" in legacy_text):
            return "compatible"
        if "ofdm" in label and any(term in legacy_text for term in ["wifi", "ofdm", "lte"]):
            return "compatible"
        if "fm_broadcast" in label and any(term in legacy_text for term in ["fm", "broadcast", "wfm"]):
            return "compatible"
        return "different"

    def _legacy_context(self, region: dict[str, Any], legacy_result: dict[str, Any] | None) -> dict[str, Any]:
        center_hz = float(region.get("center_frequency_hz", 0.0))
        legacy_text = ""
        legacy_confidence = 0.0
        if legacy_result:
            legacy_text = f"{legacy_result.get('label', '')} {legacy_result.get('family', '')}".lower()
            legacy_confidence = float(legacy_result.get("confidence", 0.0) or 0.0)
        return {
            "center_frequency_hz": center_hz,
            "inside_fm_broadcast_band": 87_500_000 <= center_hz <= 108_000_000,
            "legacy_label": legacy_result.get("label") if legacy_result else None,
            "legacy_family": legacy_result.get("family") if legacy_result else None,
            "legacy_confidence": legacy_confidence,
            "legacy_indicates_fm_broadcast": any(term in legacy_text for term in ["fm", "broadcast", "wfm"]),
            "legacy_indicates_ism_remote": any(term in legacy_text for term in ["ism", "remote"]),
            "legacy_indicates_wideband_ofdm": any(term in legacy_text for term in ["wifi", "ofdm", "lte", "5g", "nr"]),
        }

    def _apply_contextual_consistency(
        self,
        label: str,
        confidence: float,
        status: str,
        region: dict[str, Any],
        legacy_result: dict[str, Any] | None,
        context: dict[str, Any],
    ) -> tuple[str, float, str, list[str]]:
        notes: list[str] = []
        bandwidth = float(region.get("occupied_bandwidth_hz", 0.0) or 0.0)

        if context["inside_fm_broadcast_band"] and label in {"ook_like", "fsk_like", "psk_like"}:
            label = "fm_broadcast_like" if bandwidth >= 60_000 else "ambiguous"
            confidence = min(max(confidence, 0.50), 0.72)
            status = "accepted" if label == "fm_broadcast_like" else "ambiguous"
            notes.append("FM broadcast band context suppressed narrowband digital-like hypothesis.")

        if context["legacy_indicates_fm_broadcast"] and label in {"ook_like", "fsk_like", "psk_like"}:
            label = "fm_broadcast_like"
            confidence = min(max(confidence, float(context["legacy_confidence"]) * 0.85), 0.78)
            status = "accepted"
            notes.append("Legacy RF Intelligence indicates FM broadcast; new hypothesis corrected to fm_broadcast_like.")

        if context["legacy_indicates_wideband_ofdm"] and label in {"ook_like", "fsk_like", "psk_like"} and bandwidth > 1_000_000:
            label = "ofdm_like"
            confidence = min(max(confidence, float(context["legacy_confidence"]) * 0.8), 0.76)
            status = "accepted"
            notes.append("Legacy wideband OFDM context corrected narrowband-like hypothesis.")

        if context["legacy_indicates_ism_remote"] and label in {"ook_like", "fsk_like"}:
            confidence = min(confidence + 0.06, 0.92)
            notes.append("Legacy ISM remote context is compatible with OOK/FSK-like candidate.")

        if legacy_result and not notes and self._legacy_agreement(label, legacy_result) == "different":
            confidence *= 0.85
            if status == "accepted":
                status = "ambiguous"
            notes.append("Legacy and new hypotheses differ; decision downgraded for manual review.")

        if not notes:
            notes.append("No contextual correction applied.")
        return label, confidence, status, notes

    def _limitations(self) -> list[str]:
        return [
            "This is a candidate proposal pipeline; current detector and classifiers are heuristic until trained models are enabled.",
            "The result is a signal-type hypothesis, not protocol-level decoding.",
            "The transmitter identity requires a trained device-level fingerprint model.",
        ]
