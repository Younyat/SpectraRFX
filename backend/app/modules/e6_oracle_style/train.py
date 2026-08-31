"""
E6 training pipeline — Oracle-style classical ML fingerprinting.

Replicates and extends the rf_device_pipeline.py logic from the
reference project, adapted for the lab's dataset manifest format.
"""
from __future__ import annotations

import importlib.util
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.preprocessing import LabelEncoder

from app.modules.e6_oracle_style.dataset_manifest import load_manifest
from app.modules.e6_oracle_style.feature_extractor import (
    FEATURE_EXTRACTOR_VERSION,
    extract_features,
    feature_names,
)
from app.modules.e6_oracle_style.iq_loader import read_iq_window, select_windows

MODEL_CATALOG: Dict[str, str] = {
    "hist_gradient_boosting": "HistGradientBoostingClassifier — modern tabular boosting",
    "random_forest": "RandomForestClassifier — robust ensemble",
    "extra_trees": "ExtraTreesClassifier — randomised ensemble",
    "mlp": "MLPClassifier — dense neural network over tabular features",
    "svm_rbf": "SVC RBF — non-linear support vector machine",
    "knn": "KNeighborsClassifier — geometric baseline",
    "svm_linear": "SVC linear — strong linear baseline",
    "logistic_regression": "LogisticRegression — linear probabilistic baseline",
}


def sklearn_available() -> bool:
    return importlib.util.find_spec("sklearn") is not None


def joblib_available() -> bool:
    return importlib.util.find_spec("joblib") is not None


def make_estimator(kind: str, random_state: int = 42):
    from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.neural_network import MLPClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import SVC

    if kind not in MODEL_CATALOG:
        raise ValueError(f"Unknown model: {kind}. Supported: {sorted(MODEL_CATALOG)}")

    scaler = StandardScaler()
    if kind == "knn":
        clf = KNeighborsClassifier(n_neighbors=5, weights="distance")
    elif kind == "svm_linear":
        clf = SVC(kernel="linear", class_weight="balanced", probability=True, random_state=random_state)
    elif kind == "svm_rbf":
        clf = SVC(kernel="rbf", C=10.0, gamma="scale", class_weight="balanced", probability=True, random_state=random_state)
    elif kind == "random_forest":
        clf = RandomForestClassifier(n_estimators=180, min_samples_leaf=2, class_weight="balanced_subsample", n_jobs=-1, random_state=random_state)
    elif kind == "extra_trees":
        clf = ExtraTreesClassifier(n_estimators=220, min_samples_leaf=2, class_weight="balanced", n_jobs=-1, random_state=random_state)
    elif kind == "logistic_regression":
        # scikit-learn 1.8 removed the multi_class parameter. Keeping the
        # estimator signature current prevents the E6 benchmark from failing
        # only on the logistic regression baseline.
        clf = LogisticRegression(max_iter=4000, class_weight="balanced", random_state=random_state)
    elif kind == "mlp":
        clf = MLPClassifier(hidden_layer_sizes=(128, 64), activation="relu", solver="adam", alpha=1e-4,
                            max_iter=260, early_stopping=True, n_iter_no_change=15, random_state=random_state)
    else:  # hist_gradient_boosting
        clf = HistGradientBoostingClassifier(learning_rate=0.08, max_iter=160, l2_regularization=0.05, random_state=random_state)
    return Pipeline([("scaler", scaler), ("classifier", clf)])


def build_feature_matrix(
    captures: List[dict[str, Any]],
    window_size: int = 4096,
    windows_per_file: int = 3,
    window_strategy: str = "linspace",
    _progress_cb=None,
    _progress_base: int = 5,
    _progress_end: int = 65,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, List[dict[str, Any]], int]:
    """Extract feature matrix from a list of capture records.

    Returns (X, labels, groups, used_captures, total_iq_bytes).
    """
    rows: List[np.ndarray] = []
    labels: List[str] = []
    groups: List[str] = []
    used: List[dict[str, Any]] = []
    total_iq_bytes: int = 0
    n_total = len(captures)

    for i, cap in enumerate(captures):
        iq_path = Path(str(cap.get("iq_path", "")))
        if not iq_path.exists():
            continue
        dtype = str(cap.get("dtype") or "cf32")
        label = str(cap.get("label") or "unknown")
        group = str(cap.get("group") or cap.get("capture_id") or iq_path.stem)
        sample_count = cap.get("sample_count")

        try:
            total_iq_bytes += iq_path.stat().st_size
        except OSError:
            pass

        if _progress_cb and n_total > 0:
            pct = _progress_base + int((i / n_total) * (_progress_end - _progress_base))
            _progress_cb(pct, f"Extracting features {i + 1}/{n_total} · {label}")

        starts = select_windows(iq_path, dtype, sample_count, window_size, windows_per_file, window_strategy)
        ok = 0
        for start in starts:
            try:
                iq = read_iq_window(iq_path, dtype, start, window_size)
                rows.append(extract_features(iq))
                labels.append(label)
                groups.append(group)
                ok += 1
            except Exception:
                continue
        if ok:
            used.append({**cap, "windows_extracted": ok})

    if not rows:
        raise RuntimeError("No features could be extracted from any capture")
    if _progress_cb:
        _progress_cb(_progress_end, f"Feature extraction done: {len(rows)} windows from {len(used)} files")
    return np.vstack(rows), np.asarray(labels), np.asarray(groups), used, total_iq_bytes


def stratified_group_split(
    labels: np.ndarray,
    groups: np.ndarray,
    test_size: float,
    random_state: int,
) -> Tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(random_state)
    train_groups: set = set()
    test_groups: set = set()
    for lbl in sorted(set(labels.tolist())):
        label_groups = sorted(set(groups[labels == lbl].tolist()))
        if len(label_groups) < 2:
            train_groups.update(label_groups)
            continue
        arr = np.array(label_groups)
        rng.shuffle(arr)
        n_test = max(1, int(round(len(arr) * test_size)))
        n_test = min(n_test, len(arr) - 1)
        test_groups.update(arr[:n_test].tolist())
        train_groups.update(arr[n_test:].tolist())
    train_idx = np.array([i for i, g in enumerate(groups) if g in train_groups], dtype=int)
    test_idx = np.array([i for i, g in enumerate(groups) if g in test_groups], dtype=int)
    if train_idx.size == 0 or test_idx.size == 0:
        from sklearn.model_selection import GroupShuffleSplit
        spl = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=random_state)
        train_idx, test_idx = next(spl.split(np.zeros(len(labels)), labels, groups))
    return train_idx, test_idx


def train_from_manifest(
    dataset_name: str,
    e6_datasets_dir: Path,
    e6_models_dir: Path,
    model_kind: str = "extra_trees",
    window_size: int = 4096,
    windows_per_file: int = 3,
    window_strategy: str = "linspace",
    test_size: float = 0.25,
    random_state: int = 42,
    split_from_manifest: bool = True,
    progress_cb=None,
) -> dict[str, Any]:
    """Full training pipeline: load manifest → extract features → split → train → evaluate → save."""
    def _cb(pct: int, msg: str, **kw) -> None:
        if progress_cb:
            progress_cb(pct, msg, **kw)

    if not sklearn_available():
        raise RuntimeError("scikit-learn is required for E6 training")
    if not joblib_available():
        raise RuntimeError("joblib is required for E6 model saving")
    import joblib

    _cb(2, "Loading dataset manifest")
    dataset_dir = e6_datasets_dir / dataset_name
    manifest = load_manifest(dataset_dir)
    captures = manifest.get("captures", [])
    if not captures:
        raise ValueError(f"Dataset '{dataset_name}' has no captures")

    labels_present = sorted({c["label"] for c in captures if c.get("label")})
    if len(labels_present) < 2:
        raise ValueError(f"Dataset '{dataset_name}' has only {len(labels_present)} class(es). Need ≥ 2.")

    _cb(4, f"Starting feature extraction for {len(captures)} captures")
    started = time.perf_counter()
    x, labels, groups, used, total_iq_bytes = build_feature_matrix(
        captures, window_size, windows_per_file, window_strategy,
        _progress_cb=_cb, _progress_base=5, _progress_end=65,
    )
    feature_time_ms = (time.perf_counter() - started) * 1000.0

    class_names = sorted(set(labels.tolist()))
    if len(class_names) < 2:
        raise RuntimeError(f"After feature extraction only {len(class_names)} class(es) remain. Need ≥ 2.")

    _cb(66, f"{len(class_names)} classes · {x.shape[0]} windows · {x.shape[1]} features")
    encoder = LabelEncoder()
    y = encoder.fit_transform(labels)

    _cb(68, "Building train / test split")
    # Respect manifest splits when available
    if split_from_manifest and manifest.get("splits", {}).get("train"):
        splits = manifest["splits"]
        train_cap_ids = set(splits.get("train", []))
        test_cap_ids = set(splits.get("validation", []) + splits.get("test", []))
        cap_group_to_split: Dict[str, str] = {}
        for c in captures:
            cid = c["capture_id"]
            if cid in train_cap_ids:
                cap_group_to_split[c.get("group", cid)] = "train"
            elif cid in test_cap_ids:
                cap_group_to_split[c.get("group", cid)] = "test"
        train_idx = np.array([i for i, g in enumerate(groups) if cap_group_to_split.get(g, "train") == "train"], dtype=int)
        test_idx = np.array([i for i, g in enumerate(groups) if cap_group_to_split.get(g, "train") == "test"], dtype=int)
        if train_idx.size == 0 or test_idx.size == 0:
            train_idx, test_idx = stratified_group_split(labels, groups, test_size, random_state)
    else:
        train_idx, test_idx = stratified_group_split(labels, groups, test_size, random_state)

    _cb(72, f"Training {model_kind} — {len(train_idx)} windows")
    model = make_estimator(model_kind, random_state)
    t0 = time.perf_counter()
    model.fit(x[train_idx], y[train_idx])
    train_time_ms = (time.perf_counter() - t0) * 1000.0

    _cb(88, f"Evaluating on {len(test_idx)} test windows")
    t1 = time.perf_counter()
    pred = model.predict(x[test_idx])
    infer_ms_per_window = ((time.perf_counter() - t1) * 1000.0) / max(len(test_idx), 1)

    acc = float(accuracy_score(y[test_idx], pred))
    bal_acc = float(balanced_accuracy_score(y[test_idx], pred))
    mac_f1 = float(f1_score(y[test_idx], pred, average="macro", zero_division=0))
    wei_f1 = float(f1_score(y[test_idx], pred, average="weighted", zero_division=0))
    mac_prec = float(precision_score(y[test_idx], pred, average="macro", zero_division=0))
    mac_rec = float(recall_score(y[test_idx], pred, average="macro", zero_division=0))
    cm = confusion_matrix(y[test_idx], pred).tolist()
    clf_report = classification_report(
        y[test_idx], pred,
        target_names=encoder.classes_,
        labels=list(range(len(encoder.classes_))),
        zero_division=0,
        output_dict=True,
    )

    _cb(93, "Saving model bundle (.joblib)")
    # Save model bundle
    e6_models_dir.mkdir(parents=True, exist_ok=True)
    model_id = f"e6_{dataset_name}_{model_kind}"
    model_path = e6_models_dir / f"{model_id}.joblib"

    bundle = {
        "model_id": model_id,
        "model": model,
        "label_encoder": encoder,
        "feature_names": feature_names(),
        "feature_extractor_version": FEATURE_EXTRACTOR_VERSION,
        "window_size": window_size,
        "windows_per_file": windows_per_file,
        "window_strategy": window_strategy,
        "dtype_default": manifest.get("dtype", "cf32"),
        "classes": encoder.classes_.tolist(),
        "task": manifest.get("task", "device_fingerprinting"),
        "dataset_name": dataset_name,
        "model_kind": model_kind,
        "training_metadata": {
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "windows_total": int(x.shape[0]),
            "features": int(x.shape[1]),
            "train_windows": int(len(train_idx)),
            "test_windows": int(len(test_idx)),
            "random_state": random_state,
            "feature_time_ms": feature_time_ms,
            "train_time_ms": train_time_ms,
        },
    }
    joblib.dump(bundle, model_path)
    model_size_bytes = model_path.stat().st_size

    metrics = {
        "accuracy": acc,
        "balanced_accuracy": bal_acc,
        "macro_f1": mac_f1,
        "weighted_f1": wei_f1,
        "precision_macro": mac_prec,
        "recall_macro": mac_rec,
        "inference_time_ms": infer_ms_per_window,
        "model_size_bytes": model_size_bytes,
        "train_time_ms": train_time_ms,
        "windows_total": int(x.shape[0]),
        "train_windows": int(len(train_idx)),
        "test_windows": int(len(test_idx)),
        "classes": encoder.classes_.tolist(),
        "class_count": len(encoder.classes_),
        "confusion_matrix": cm,
        "classification_report": clf_report,
    }

    _cb(99, f"Done · acc={acc:.3f} · {model_kind} saved ({model_size_bytes // 1024} KB)")
    return {
        "model_id": model_id,
        "model_path": str(model_path),
        "dataset_name": dataset_name,
        "model_kind": model_kind,
        "metrics": metrics,
        "classes": encoder.classes_.tolist(),
        "feature_names": feature_names(),
        "window_size": window_size,
        "window_strategy": window_strategy,
        "windows_per_file": windows_per_file,
        "feature_extractor_version": FEATURE_EXTRACTOR_VERSION,
        "dataset_iq_size_bytes": total_iq_bytes,
    }
