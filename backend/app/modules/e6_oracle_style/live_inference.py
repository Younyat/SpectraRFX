"""
E6 live inference — predict from raw IQ array or frozen spectrum window.

The same feature extractor used during training is applied here.
No secondary extraction path is allowed to diverge from train.py.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, List, Optional

import numpy as np

from app.modules.e6_oracle_style.feature_extractor import (
    FEATURE_EXTRACTOR_VERSION,
    extract_features,
    feature_names,
)
from app.modules.e6_oracle_style.iq_loader import read_iq_window, select_windows


def load_bundle(model_path: str):
    import joblib
    return joblib.load(str(model_path))


def predict_from_iq_array(
    model_path: str,
    iq: np.ndarray,
    window_size: Optional[int] = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Predict on a raw complex IQ numpy array."""
    bundle = load_bundle(model_path)
    ws = int(window_size or bundle.get("window_size") or 4096)
    iq = iq.astype(np.complex64, copy=False)

    # Take centre window if IQ is longer than window_size
    if iq.size >= ws:
        start = max(0, (iq.size - ws) // 2)
        iq_win = iq[start:start + ws]
    else:
        iq_win = iq

    t0 = time.perf_counter()
    feat = extract_features(iq_win)
    x = feat.reshape(1, -1)
    infer_ms = (time.perf_counter() - t0) * 1000.0

    return _run_prediction(bundle, x, infer_ms, top_k, ws, 0)


def predict_from_iq_file(
    model_path: str,
    iq_path: str,
    dtype: Optional[str] = None,
    sample_count: Optional[int] = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """Predict on an IQ binary file."""
    bundle = load_bundle(model_path)
    ws = int(bundle.get("window_size") or 4096)
    resolved_dtype = dtype or str(bundle.get("dtype_default") or "cf32")

    path = Path(iq_path)
    if not path.exists():
        raise FileNotFoundError(f"IQ file not found: {iq_path}")

    starts = select_windows(path, resolved_dtype, sample_count, ws, 3, str(bundle.get("window_strategy") or "linspace"))
    feats = []
    t0 = time.perf_counter()
    for start in starts:
        try:
            iq = read_iq_window(path, resolved_dtype, start, ws)
            feats.append(extract_features(iq))
        except Exception:
            continue
    if not feats:
        raise RuntimeError("Could not extract any features from IQ file")
    x = np.vstack(feats)
    infer_ms = (time.perf_counter() - t0) * 1000.0

    return _run_prediction(bundle, x, infer_ms, top_k, ws, starts[0])


def predict_from_spectrum_window(
    model_path: str,
    frequency_array_hz: List[float],
    power_levels_db: List[float],
    marker_start_hz: Optional[float] = None,
    marker_stop_hz: Optional[float] = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """
    Predict on a spectrum window (frequency / power arrays from the live display).

    The spectrum power is converted to a synthetic IQ amplitude signal for
    feature extraction.  This is an approximation; use IQ-based prediction
    when full IQ data is available.
    """
    bundle = load_bundle(model_path)
    freq = np.asarray(frequency_array_hz, dtype=np.float64)
    pwr = np.asarray(power_levels_db, dtype=np.float64)

    if marker_start_hz is not None and marker_stop_hz is not None:
        mask = (freq >= marker_start_hz) & (freq <= marker_stop_hz)
        if mask.sum() >= 8:
            freq = freq[mask]
            pwr = pwr[mask]

    # Convert dBm → linear amplitude, treat as synthetic IQ (I=amp, Q=0)
    amp = np.sqrt(10.0 ** (pwr / 10.0))
    synthetic_iq = amp.astype(np.complex64)

    t0 = time.perf_counter()
    feat = extract_features(synthetic_iq)
    x = feat.reshape(1, -1)
    infer_ms = (time.perf_counter() - t0) * 1000.0

    result = _run_prediction(bundle, x, infer_ms, top_k, len(synthetic_iq), 0)
    result["source"] = "spectrum_window"
    result["warning"] = "Spectrum-window prediction uses a synthetic IQ approximation. Use IQ-based prediction for scientific results."
    return result


def _run_prediction(bundle: dict, x: np.ndarray, infer_ms: float, top_k: int, window_size: int, window_start: int) -> dict[str, Any]:
    model = bundle["model"]
    encoder = bundle["label_encoder"]

    feat_names_bundle = bundle.get("feature_names", feature_names())
    if x.shape[1] != len(feat_names_bundle):
        raise RuntimeError(
            f"Feature count mismatch: model expects {len(feat_names_bundle)}, got {x.shape[1]}. "
            "Ensure the same feature_extractor_version is used in training and inference."
        )

    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(x).mean(axis=0)
        order = np.argsort(proba)[::-1]
        best_int = int(order[0])
        top = [
            {"label": str(encoder.inverse_transform([int(i)])[0]), "probability": float(proba[int(i)])}
            for i in order[:top_k]
        ]
        prediction = top[0]["label"]
        confidence = float(top[0]["probability"])
    else:
        pred = model.predict(x)
        vals, counts = np.unique(pred, return_counts=True)
        best_int = int(vals[np.argmax(counts)])
        prediction = str(encoder.inverse_transform([best_int])[0])
        confidence = float(np.max(counts) / np.sum(counts))
        top = [{"label": prediction, "probability": confidence}]

    return {
        "model_id": bundle.get("model_id", "unknown"),
        "task": bundle.get("task", "device_fingerprinting"),
        "prediction": prediction,
        "confidence": confidence,
        "top_k": top,
        "window_start": window_start,
        "window_size": window_size,
        "inference_time_ms": infer_ms,
        "feature_extractor_version": bundle.get("feature_extractor_version", FEATURE_EXTRACTOR_VERSION),
        "classes": bundle.get("classes", encoder.classes_.tolist()),
        "source": "iq",
    }
