from __future__ import annotations

import json
import pickle
import time
from pathlib import Path
from typing import Any

import numpy as np

READINESS_MIN_MACRO_F1 = 0.50
READINESS_MIN_CLASSES = 2
SUPPORTED_EXPERIMENT_TYPES = {
    "e5_spectral_feature_baseline",
    "e1_raw_iq_cnn1d",
    "e3_spectrogram_cnn2d",
}
E1_REJECTION_REASON = (
    "E1 requires raw IQ samples; only FFT/PSD is available from the live spectrum stream. "
    "Use Capture Lab to record an IQ file and run batch inference."
)
E3_REJECTION_REASON = (
    "E3 requires a spectrogram or waterfall image; live spectrum provides only FFT/PSD. "
    "Capture an IQ file first, then use Representations to generate a spectrogram."
)


class ModelReadinessGate:
    @staticmethod
    def check(result_dir: Path, experiment_type: str) -> dict[str, Any]:
        reasons: list[str] = []

        metrics_path = result_dir / "metrics.json"
        if not metrics_path.exists():
            reasons.append("missing metrics.json")
        else:
            try:
                metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
                f1 = metrics.get("macro_f1")
                if f1 is None or float(f1) < READINESS_MIN_MACRO_F1:
                    reasons.append(
                        f"macro_f1 {f1!r} is below readiness threshold {READINESS_MIN_MACRO_F1}"
                    )
            except Exception as exc:
                reasons.append(f"failed to parse metrics.json: {exc}")

        label_schema_path = result_dir / "label_schema.json"
        label_schema: dict[str, Any] | None = None
        if not label_schema_path.exists():
            reasons.append("missing label_schema.json")
        else:
            try:
                label_schema = json.loads(label_schema_path.read_text(encoding="utf-8"))
                n = len((label_schema or {}).get("labels", []))
                if n < READINESS_MIN_CLASSES:
                    reasons.append(f"only {n} classes in label_schema (need >= {READINESS_MIN_CLASSES})")
            except Exception as exc:
                reasons.append(f"failed to parse label_schema.json: {exc}")

        is_e5 = "e5" in experiment_type
        is_e1 = "e1" in experiment_type
        is_e3 = "e3" in experiment_type
        model_file: Path | None = None
        if is_e5:
            model_file = result_dir / "model.pkl"
            if not model_file.exists():
                reasons.append("missing model.pkl")
        elif is_e1 or is_e3:
            model_file = result_dir / "model.pt"
            if not model_file.exists():
                reasons.append("missing model.pt")

        live_compatible = is_e5
        if is_e1:
            reasons.append(E1_REJECTION_REASON)
        elif is_e3:
            reasons.append(E3_REJECTION_REASON)

        if is_e5:
            input_type = "fft_psd_features"
        elif is_e1:
            input_type = "raw_iq"
        else:
            input_type = "spectrogram"

        return {
            "ready_for_live_inference": live_compatible and len(reasons) == 0,
            "live_compatible": live_compatible,
            "rejection_reasons": reasons,
            "label_schema": label_schema,
            "input_type": input_type,
            "model_file": str(model_file) if model_file else None,
        }


class LiveInferenceAdapter:
    def model_registry(self, results_dir: Path) -> list[dict[str, Any]]:
        registry: list[dict[str, Any]] = []
        for path in sorted(results_dir.glob("*/*"), key=lambda p: p.stat().st_mtime, reverse=True):
            if not path.is_dir():
                continue
            exp_type = path.parent.name
            if exp_type not in SUPPORTED_EXPERIMENT_TYPES:
                continue
            readiness = ModelReadinessGate.check(path, exp_type)
            metrics = self._load_json(path / "metrics.json") or {}
            config = self._load_config(path)
            registry.append(
                {
                    "model_id": f"{exp_type}:{path.name}",
                    "experiment_type": exp_type,
                    "run_id": path.name,
                    "ready_for_live_inference": readiness["ready_for_live_inference"],
                    "live_compatible": readiness["live_compatible"],
                    "rejection_reasons": readiness["rejection_reasons"],
                    "label_schema": readiness["label_schema"],
                    "input_type": readiness["input_type"],
                    "task": config.get("task") or "unknown",
                    "label_field": config.get("label_field"),
                    "metrics_summary": {
                        k: metrics.get(k)
                        for k in ["accuracy", "balanced_accuracy", "macro_f1", "precision_macro", "recall_macro"]
                    },
                    "model_file": readiness["model_file"],
                }
            )
        return registry

    def run_e5_live_inference(
        self,
        model_pkl_path: str,
        label_schema: dict[str, Any],
        frequency_array_hz: list[float],
        power_levels_db: list[float],
        center_frequency_hz: float,
        marker_start_hz: float | None = None,
        marker_stop_hz: float | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()

        freq = np.asarray(frequency_array_hz, dtype=np.float64)
        power_db = np.asarray(power_levels_db, dtype=np.float64)

        if freq.shape != power_db.shape or len(freq) < 4:
            raise ValueError(
                f"Spectrum data is too short for feature extraction (got {len(freq)} bins, need >= 4)"
            )

        if marker_start_hz is not None and marker_stop_hz is not None and marker_stop_hz > marker_start_hz:
            mask = (freq >= marker_start_hz) & (freq <= marker_stop_hz)
            if mask.sum() >= 4:
                freq = freq[mask]
                power_db = power_db[mask]

        # Convert dB to linear amplitude to match training code's mag -> power^2 representation.
        # Training uses FFT magnitudes (linear amplitude); live uses dB power.
        # power_db assumed to be power in dBFS/dBm: mag = 10^(db/20) so power = mag^2 = 10^(db/10).
        mag = np.power(10.0, power_db / 20.0)
        power = np.maximum(mag**2, 1e-20)
        total = float(np.sum(power))
        weights = power / max(total, 1e-20)

        centroid = float(np.sum(freq * weights))
        spread = float(np.sqrt(np.sum(((freq - centroid) ** 2) * weights)))
        n = weights.size
        entropy = float(-np.sum(weights * np.log2(np.maximum(weights, 1e-20))) / max(np.log2(n), 1.0))
        flatness = float(
            np.exp(np.mean(np.log(np.maximum(power, 1e-20)))) / max(float(np.mean(power)), 1e-20)
        )
        thirds = np.array_split(power, 3)
        ratios = [float(np.sum(part) / max(total, 1e-20)) for part in thirds]
        while len(ratios) < 3:
            ratios.append(0.0)

        peak_idx = int(np.argmax(power))
        noise_floor_db = float(np.percentile(power_db, 10))
        snr_db = float(float(np.max(power_db)) - noise_floor_db)
        center = float(center_frequency_hz) if center_frequency_hz else float(np.mean(freq))
        occ_bw = float(freq[-1] - freq[0]) if len(freq) > 1 else 0.0

        feature_vector = np.array(
            [
                float(np.mean(power)),
                float(np.max(power)),
                float(freq[peak_idx] - center),
                occ_bw,
                centroid,
                spread,
                flatness,
                entropy,
                ratios[0],
                ratios[1],
                ratios[2],
                noise_floor_db,
                snr_db,
            ],
            dtype=np.float32,
        ).reshape(1, -1)

        with open(model_pkl_path, "rb") as handle:
            payload = pickle.load(handle)
        model = payload["model"] if isinstance(payload, dict) else payload

        prediction = str(model.predict(feature_vector)[0])
        top_k: list[dict[str, Any]] = []
        confidence: float | None = None
        if hasattr(model, "predict_proba"):
            probs = model.predict_proba(feature_vector)[0]
            classes = model.classes_
            top_k = sorted(
                [{"label": str(cls), "score": float(prob)} for cls, prob in zip(classes, probs)],
                key=lambda x: x["score"],
                reverse=True,
            )[:5]
            confidence = float(np.max(probs))

        latency_ms = (time.perf_counter() - started) * 1000.0
        return {
            "predicted_label": prediction,
            "confidence": confidence,
            "top_k": top_k,
            "latency_ms": round(latency_ms, 2),
            "band_bins_used": len(freq),
            "marker_filtered": marker_start_hz is not None,
        }

    def _load_json(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _load_config(self, path: Path) -> dict[str, Any]:
        for name in ("training_config.json", "config.yaml"):
            p = path / name
            if not p.exists():
                continue
            try:
                text = p.read_text(encoding="utf-8")
                if name.endswith(".json"):
                    return json.loads(text)
                result: dict[str, Any] = {}
                for line in text.splitlines():
                    if ":" not in line or line.startswith(" "):
                        continue
                    key, _, value = line.partition(":")
                    value = value.strip()
                    try:
                        result[key.strip()] = json.loads(value)
                    except Exception:
                        result[key.strip()] = value
                return result
            except Exception:
                continue
        return {}
