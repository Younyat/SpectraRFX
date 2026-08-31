"""E6 Oracle-Style Lab — main service orchestrator."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from app.modules.e6_oracle_style import job_tracker as jt

_KNOWN_ALGORITHMS = [
    "hist_gradient_boosting", "random_forest", "extra_trees",
    "mlp", "svm_rbf", "knn", "svm_linear", "logistic_regression",
]


def _guess_algorithm_from_filename(name: str) -> str:
    stem = Path(name).stem.lower().replace("-", "_")
    for algo in sorted(_KNOWN_ALGORITHMS, key=len, reverse=True):
        if algo in stem:
            return algo
    return "unknown"


def _guess_dataset_from_filename(name: str, algorithm: str) -> str:
    stem = Path(name).stem
    if algorithm != "unknown" and algorithm in stem:
        idx = stem.find(algorithm)
        return stem[:idx].rstrip("_") or stem
    return stem

import numpy as np

from app.modules.e6_oracle_style import dataset_builder as db
from app.modules.e6_oracle_style import dataset_importer as di
from app.modules.e6_oracle_style import live_inference as li
from app.modules.e6_oracle_style import model_registry as mr
from app.modules.e6_oracle_style import train as tr
from app.modules.e6_oracle_style.dataset_manifest import (
    build_splits,
    list_datasets,
    load_manifest,
    save_manifest,
)
from app.modules.e6_oracle_style.feature_extractor import feature_names


class E6Service:
    def __init__(self, storage_root: Path) -> None:
        self.e6_root = storage_root / "e6"
        self.datasets_dir = self.e6_root / "datasets"
        self.models_dir = self.e6_root / "models"
        self.uploads_dir = self.e6_root / "uploads"
        self.e6_root.mkdir(parents=True, exist_ok=True)
        self.datasets_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

    # ── Health ──────────────────────────────────────────────────────────────

    def health(self) -> dict[str, Any]:
        import importlib.util
        sklearn_ok = importlib.util.find_spec("sklearn") is not None
        joblib_ok = importlib.util.find_spec("joblib") is not None
        return {
            "module": "e6_oracle_style",
            "available": sklearn_ok and joblib_ok,
            "sklearn_available": sklearn_ok,
            "joblib_available": joblib_ok,
            "datasets_dir": str(self.datasets_dir),
            "models_dir": str(self.models_dir),
            "supported_external_sources": list(di.SUPPORTED_EXTERNAL_SOURCES.keys()),
            "supported_models": list(tr.MODEL_CATALOG.keys()),
            "feature_count": len(feature_names()),
            "feature_names": feature_names(),
        }

    # ── External datasets ───────────────────────────────────────────────────

    def list_external_sources(self) -> List[dict[str, Any]]:
        return [{"source_type": k, **v} for k, v in di.SUPPORTED_EXTERNAL_SOURCES.items()]

    def scan_external_dataset(self, payload: dict[str, Any]) -> dict[str, Any]:
        return di.scan_external_dataset(
            source_type=str(payload["source_type"]),
            source_root=str(payload["source_root"]),
            ieee_target=str(payload.get("ieee_target") or "auto"),
            limit_files=payload.get("limit_files"),
        )

    def import_external_dataset(self, payload: dict[str, Any]) -> dict[str, Any]:
        source_type = str(payload["source_type"])
        dataset_name = str(payload["dataset_name"])
        job_id = jt.create_job("import", f"{source_type} → {dataset_name}")

        def _run() -> None:
            try:
                limit_files = payload.get("limit_files")
                import_pct = payload.get("import_percentage")
                if import_pct is not None and 0.0 < float(import_pct) < 1.0:
                    jt.update_job(job_id, 2, "Pre-scanning to compute file count")
                    scan = di.scan_external_dataset(
                        source_type=source_type,
                        source_root=str(payload["source_root"]),
                        ieee_target=str(payload.get("ieee_target") or "auto"),
                        limit_files=None,
                    )
                    total = scan.get("record_count", 0)
                    limit_files = max(1, int(total * float(import_pct)))
                    jt.update_job(job_id, 4, f"Importing {limit_files} of {total} files ({int(import_pct*100)}%)")

                result = di.import_external_dataset(
                    source_type=source_type,
                    source_root=str(payload["source_root"]),
                    dataset_name=dataset_name,
                    e6_datasets_dir=self.datasets_dir,
                    ieee_target=str(payload.get("ieee_target") or "auto"),
                    limit_files=limit_files,
                    max_files_per_class=payload.get("max_files_per_class"),
                    progress_cb=lambda pct, msg: jt.update_job(job_id, pct, msg),
                )
                jt.complete_job(job_id, result)
            except Exception as exc:
                jt.fail_job(job_id, str(exc))

        threading.Thread(target=_run, daemon=True).start()
        return {"job_id": job_id}

    # ── Local datasets ──────────────────────────────────────────────────────

    def list_datasets(self) -> List[dict[str, Any]]:
        return list_datasets(self.datasets_dir)

    def create_local_dataset(self, payload: dict[str, Any]) -> dict[str, Any]:
        return db.create_local_dataset(
            dataset_name=str(payload["dataset_name"]),
            e6_datasets_dir=self.datasets_dir,
            task=str(payload.get("task") or "device_fingerprinting"),
            signal_family=str(payload.get("signal_family") or ""),
            protocol=str(payload.get("protocol") or ""),
            center_frequency_hz=payload.get("center_frequency_hz"),
            sample_rate_hz=payload.get("sample_rate_hz"),
            bandwidth_hz=payload.get("bandwidth_hz"),
            dtype=str(payload.get("dtype") or "cf32"),
            receiver_model=str(payload.get("receiver_model") or "USRP B200"),
            receiver_serial=str(payload.get("receiver_serial") or ""),
            antenna=str(payload.get("antenna") or "RX2"),
            gain_db=payload.get("gain_db"),
            environment=str(payload.get("environment") or "lab"),
            notes=str(payload.get("notes") or ""),
        )

    def add_capture(self, payload: dict[str, Any]) -> dict[str, Any]:
        return db.add_local_capture(
            dataset_name=str(payload["dataset_name"]),
            e6_datasets_dir=self.datasets_dir,
            iq_path=str(payload["iq_path"]),
            label=str(payload["label"]),
            session_id=str(payload.get("session_id") or ""),
            dtype=payload.get("dtype"),
            sample_rate_hz=payload.get("sample_rate_hz"),
            center_frequency_hz=payload.get("center_frequency_hz"),
            sample_count=payload.get("sample_count"),
            notes=str(payload.get("notes") or ""),
        )

    def register_device(self, payload: dict[str, Any]) -> dict[str, Any]:
        return db.register_device(
            dataset_name=str(payload["dataset_name"]),
            e6_datasets_dir=self.datasets_dir,
            transmitter_id=str(payload["transmitter_id"]),
            device_type=str(payload.get("device_type") or ""),
            vendor=str(payload.get("vendor") or ""),
            model=str(payload.get("model") or ""),
            serial=str(payload.get("serial") or ""),
            mac_address=str(payload.get("mac_address") or ""),
            notes=str(payload.get("notes") or ""),
        )

    def get_dataset_summary(self, dataset_name: str) -> dict[str, Any]:
        return db.get_dataset_summary(dataset_name, self.datasets_dir)

    def delete_dataset(self, dataset_name: str) -> dict[str, Any]:
        return db.delete_dataset(dataset_name, self.datasets_dir)

    def build_splits(self, payload: dict[str, Any]) -> dict[str, Any]:
        dataset_name = str(payload["dataset_name"])
        dataset_dir = self.datasets_dir / dataset_name
        manifest = load_manifest(dataset_dir)
        splits = build_splits(
            manifest,
            train_ratio=float(payload.get("train_ratio") or 0.70),
            val_ratio=float(payload.get("val_ratio") or 0.15),
            seed=int(payload.get("seed") or 42),
        )
        save_manifest(dataset_dir, manifest)
        return {"dataset_name": dataset_name, "splits": splits}

    # ── Training ────────────────────────────────────────────────────────────

    def train(self, payload: dict[str, Any]) -> dict[str, Any]:
        dataset_name = str(payload["dataset_name"])
        model_kind = str(payload.get("model_kind") or "extra_trees")
        job_id = jt.create_job("train", f"{model_kind} on {dataset_name}")

        def _run() -> None:
            try:
                result = tr.train_from_manifest(
                    dataset_name=dataset_name,
                    e6_datasets_dir=self.datasets_dir,
                    e6_models_dir=self.models_dir,
                    model_kind=model_kind,
                    window_size=int(payload.get("window_size") or 4096),
                    windows_per_file=int(payload.get("windows_per_file") or 3),
                    window_strategy=str(payload.get("window_strategy") or "linspace"),
                    test_size=float(payload.get("test_size") or 0.25),
                    random_state=int(payload.get("random_state") or 42),
                    split_from_manifest=bool(payload.get("split_from_manifest", True)),
                    progress_cb=lambda pct, msg, **kw: jt.update_job(job_id, pct, msg, **kw),
                )
                jt.update_job(job_id, 99, "Registering model in registry")
                dataset_dir = self.datasets_dir / dataset_name
                manifest = load_manifest(dataset_dir)
                mr.register_model(
                    e6_root=self.e6_root,
                    model_id=result["model_id"],
                    model_name=str(payload.get("model_name") or f"{dataset_name} {model_kind}"),
                    algorithm=model_kind,
                    task=manifest.get("task", "device_fingerprinting"),
                    dataset_name=dataset_name,
                    model_path=result["model_path"],
                    classes=result["classes"],
                    feature_names=result["feature_names"],
                    window_size=result["window_size"],
                    dtype=manifest.get("dtype", "cf32"),
                    metrics=result["metrics"],
                    enabled_for_live=bool(payload.get("enabled_for_live", True)),
                    notes=str(payload.get("notes") or ""),
                )
                jt.complete_job(job_id, result)
            except Exception as exc:
                jt.fail_job(job_id, str(exc))

        threading.Thread(target=_run, daemon=True).start()
        return {"job_id": job_id}

    def train_all(self, payload: dict[str, Any]) -> dict[str, Any]:
        dataset_name = str(payload["dataset_name"])
        job_id = jt.create_job("train_all", f"All 8 models on {dataset_name}")

        def _run() -> None:
            try:
                dataset_dir = self.datasets_dir / dataset_name
                manifest = load_manifest(dataset_dir)
                task = manifest.get("task", "device_fingerprinting")
                dtype = manifest.get("dtype", "cf32")
                common: dict[str, Any] = dict(
                    dataset_name=dataset_name,
                    e6_datasets_dir=self.datasets_dir,
                    e6_models_dir=self.models_dir,
                    window_size=int(payload.get("window_size") or 4096),
                    windows_per_file=int(payload.get("windows_per_file") or 3),
                    window_strategy=str(payload.get("window_strategy") or "linspace"),
                    test_size=float(payload.get("test_size") or 0.25),
                    random_state=int(payload.get("random_state") or 42),
                    split_from_manifest=bool(payload.get("split_from_manifest", True)),
                )
                enabled_for_live = bool(payload.get("enabled_for_live", True))
                model_list = list(tr.MODEL_CATALOG.keys())
                n = len(model_list)
                ranked: List[dict[str, Any]] = []
                errors: List[dict[str, Any]] = []

                for idx, model_kind in enumerate(model_list):
                    base = idx * 100 // n
                    end_pct = (idx + 1) * 100 // n
                    jt.update_job(job_id, base, f"Training {model_kind} ({idx+1}/{n})",
                                  current_model=model_kind, model_index=idx + 1, total_models=n)

                    def _make_cb(mk: str, b: int, e: int, i: int) -> Any:
                        def cb(pct: int, msg: str, **kw: Any) -> None:
                            overall = b + pct * (e - b) // 100
                            jt.update_job(job_id, overall, f"[{mk}] {msg}",
                                          current_model=mk, model_index=i + 1, total_models=n, **kw)
                        return cb

                    try:
                        result = tr.train_from_manifest(
                            model_kind=model_kind,
                            progress_cb=_make_cb(model_kind, base, end_pct, idx),
                            **common,
                        )
                        mr.register_model(
                            e6_root=self.e6_root,
                            model_id=result["model_id"],
                            model_name=f"{dataset_name} {model_kind}",
                            algorithm=model_kind,
                            task=task,
                            dataset_name=dataset_name,
                            model_path=result["model_path"],
                            classes=result["classes"],
                            feature_names=result["feature_names"],
                            window_size=result["window_size"],
                            dtype=dtype,
                            metrics=result["metrics"],
                            enabled_for_live=enabled_for_live,
                        )
                        m = result["metrics"]
                        test_total = int(m.get("test_windows", 0))
                        correct = round(test_total * (m.get("accuracy") or 0))
                        ranked.append({
                            "model_kind": model_kind,
                            "model_id": result["model_id"],
                            "accuracy": m.get("accuracy"),
                            "macro_f1": m.get("macro_f1"),
                            "balanced_accuracy": m.get("balanced_accuracy"),
                            "weighted_f1": m.get("weighted_f1"),
                            "correct": correct,
                            "failed": test_total - correct,
                            "total_test": test_total,
                            "train_time_ms": m.get("train_time_ms"),
                            "model_size_bytes": m.get("model_size_bytes"),
                            "dataset_iq_size_bytes": result.get("dataset_iq_size_bytes", 0),
                        })
                    except Exception as exc:
                        errors.append({"model_kind": model_kind, "error": str(exc)})

                ranked.sort(key=lambda r: r.get("accuracy") or 0, reverse=True)
                for i, r in enumerate(ranked):
                    r["rank"] = i + 1

                jt.complete_job(job_id, {
                    "dataset_name": dataset_name,
                    "task": task,
                    "results": ranked,
                    "errors": errors,
                    "best_model": ranked[0]["model_kind"] if ranked else None,
                    "benchmark_at": datetime.now(timezone.utc).isoformat(),
                    "total_trained": len(ranked),
                    "total_errors": len(errors),
                })
            except Exception as exc:
                jt.fail_job(job_id, str(exc))

        threading.Thread(target=_run, daemon=True).start()
        return {"job_id": job_id}

    def retrain(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Retrain an existing model — returns a job_id immediately."""
        model_id = str(payload["model_id"])
        registry_entry = mr.get_model(self.e6_root, model_id)
        if registry_entry is None:
            raise ValueError(f"Model not found in registry: {model_id}")
        job_id = jt.create_job("retrain", f"Retrain {model_id}")

        def _run_retrain() -> None:
            self._retrain_sync(payload, registry_entry, job_id)

        threading.Thread(target=_run_retrain, daemon=True).start()
        return {"job_id": job_id}

    def _retrain_sync(self, payload: dict[str, Any], registry_entry: dict[str, Any], job_id: str) -> None:
        """Synchronous retrain body — runs in background thread."""
        import joblib as _joblib
        from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score
        from sklearn.preprocessing import LabelEncoder
        from app.modules.e6_oracle_style.feature_extractor import FEATURE_EXTRACTOR_VERSION, feature_names

        def cb(pct: int, msg: str) -> None:
            jt.update_job(job_id, pct, msg)

        model_id = str(payload["model_id"])
        try:
            cb(2, f"Loading model bundle for {model_id}")
            bundle = _joblib.load(str(registry_entry["model_path"]))
            original_dataset = str(bundle.get("dataset_name") or "")
            original_ws = int(bundle.get("window_size") or 4096)
            original_dtype = str(bundle.get("dtype_default") or "cf32")
            window_size = int(payload.get("window_size") or original_ws)

            if window_size != original_ws:
                raise ValueError(
                    f"window_size mismatch: model was trained with {original_ws}, requested {window_size}. "
                    "Retrain with the same window_size or create a new model."
                )

            cb(5, "Collecting captures from datasets")
            all_captures: List[dict[str, Any]] = []
            if original_dataset:
                try:
                    m = load_manifest(self.datasets_dir / original_dataset)
                    all_captures.extend(m.get("captures", []))
                except Exception:
                    pass

            additional_dataset = payload.get("additional_dataset_name")
            if additional_dataset:
                try:
                    m = load_manifest(self.datasets_dir / str(additional_dataset))
                    all_captures.extend(m.get("captures", []))
                except Exception:
                    pass

            iq_paths = payload.get("additional_iq_paths") or []
            extra_labels = payload.get("additional_labels") or []
            for iq_path, label in zip(iq_paths, extra_labels):
                all_captures.append({
                    "capture_id": f"adhoc_{iq_path}",
                    "iq_path": iq_path,
                    "label": label,
                    "dtype": original_dtype,
                    "group": iq_path,
                })

            if not all_captures:
                raise ValueError("No captures available for retrain")

            cb(8, f"Extracting features from {len(all_captures)} captures")
            x, label_arr, groups, used, total_iq_bytes = tr.build_feature_matrix(
                all_captures,
                window_size=window_size,
                windows_per_file=int(payload.get("windows_per_file") or 3),
                window_strategy=str(payload.get("window_strategy") or "linspace"),
                _progress_cb=cb,
                _progress_base=10,
                _progress_end=65,
            )

            encoder = LabelEncoder()
            y = encoder.fit_transform(label_arr)
            classes = sorted(set(label_arr.tolist()))
            if len(classes) < 2:
                raise ValueError("Need at least 2 classes after combining datasets")

            cb(68, "Building train/test split")
            train_idx, test_idx = tr.stratified_group_split(
                label_arr, groups, float(payload.get("test_size") or 0.25), int(payload.get("random_state") or 42)
            )

            cb(72, f"Fitting {registry_entry['algorithm']} — {len(train_idx)} windows")
            model = tr.make_estimator(str(registry_entry["algorithm"]), int(payload.get("random_state") or 42))
            model.fit(x[train_idx], y[train_idx])

            cb(88, f"Evaluating on {len(test_idx)} test windows")
            pred = model.predict(x[test_idx])
            metrics = {
                "accuracy": float(accuracy_score(y[test_idx], pred)),
                "balanced_accuracy": float(balanced_accuracy_score(y[test_idx], pred)),
                "macro_f1": float(f1_score(y[test_idx], pred, average="macro", zero_division=0)),
            }

            cb(93, "Saving versioned model bundle")
            base = Path(str(registry_entry["model_path"])).stem
            version = 2
            while (self.models_dir / f"{base}_v{version}.joblib").exists():
                version += 1
            new_path = self.models_dir / f"{base}_v{version}.joblib"
            new_model_id = f"{model_id}_v{version}"

            new_bundle = {**bundle, "model": model, "label_encoder": encoder,
                          "classes": encoder.classes_.tolist(), "model_id": new_model_id,
                          "feature_extractor_version": FEATURE_EXTRACTOR_VERSION,
                          "feature_names": feature_names()}
            _joblib.dump(new_bundle, new_path)
            model_size_bytes = new_path.stat().st_size

            mr.register_model(
                e6_root=self.e6_root,
                model_id=new_model_id,
                model_name=f"{registry_entry.get('model_name', model_id)} v{version}",
                algorithm=registry_entry["algorithm"],
                task=registry_entry["task"],
                dataset_name=registry_entry["dataset_name"],
                model_path=str(new_path),
                classes=encoder.classes_.tolist(),
                feature_names=feature_names(),
                window_size=window_size,
                dtype=original_dtype,
                metrics=metrics,
                enabled_for_live=True,
            )
            result = {
                "model_id": new_model_id,
                "model_path": str(new_path),
                "version": version,
                "metrics": metrics,
                "classes": encoder.classes_.tolist(),
                "model_size_bytes": model_size_bytes,
                "dataset_iq_size_bytes": total_iq_bytes,
            }
            jt.complete_job(job_id, result)
        except Exception as exc:
            jt.fail_job(job_id, str(exc))

    # ── Import pre-trained models ────────────────────────────────────────────

    def scan_models_directory(self, payload: dict[str, Any]) -> dict[str, Any]:
        models_dir = Path(str(payload["models_dir"]))
        if not models_dir.exists():
            raise FileNotFoundError(f"Directory not found: {models_dir}")
        registry = mr.load_registry(self.e6_root)
        registered_filenames = {Path(str(r.get("model_path", ""))).name for r in registry}
        found = []
        for f in sorted(models_dir.glob("*.joblib")):
            algo = _guess_algorithm_from_filename(f.name)
            dataset = _guess_dataset_from_filename(f.name, algo)
            found.append({
                "file_name": f.name,
                "file_path": str(f),
                "size_mb": round(f.stat().st_size / 1_000_000, 2),
                "algorithm": algo,
                "dataset_name": dataset,
                "already_registered": f.name in registered_filenames,
            })
        return {"models_dir": str(models_dir), "count": len(found), "models": found}

    def import_existing_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        import joblib
        import shutil as _shutil
        model_path = Path(str(payload["model_path"]))
        if not model_path.exists():
            raise FileNotFoundError(f"Model file not found: {model_path}")

        bundle = joblib.load(str(model_path))

        # Resolve metadata — handle both oracle reference and E6 native bundles
        algo = str(bundle.get("algorithm") or _guess_algorithm_from_filename(model_path.name))
        dataset_name = str(bundle.get("dataset_name") or _guess_dataset_from_filename(model_path.name, algo))
        raw_classes = bundle.get("classes", [])
        if hasattr(raw_classes, "tolist"):
            raw_classes = raw_classes.tolist()
        if not raw_classes:
            le = bundle.get("label_encoder")
            if le is not None and hasattr(le, "classes_"):
                raw_classes = le.classes_.tolist()
        classes: List[str] = [str(c) for c in raw_classes]
        feat_names: List[str] = list(bundle.get("feature_names") or [])
        window_size = int(bundle.get("window_size") or 4096)
        dtype = str(bundle.get("dtype_default") or "cf32")
        task = str(payload.get("override_task") or bundle.get("task") or "device_fingerprinting")
        model_id = model_path.stem.replace(" ", "_")

        dest = self.models_dir / model_path.name
        if dest.resolve() != model_path.resolve():
            _shutil.copy2(str(model_path), str(dest))

        return mr.register_model(
            e6_root=self.e6_root,
            model_id=model_id,
            model_name=model_id.replace("_", " "),
            algorithm=algo,
            task=task,
            dataset_name=dataset_name,
            model_path=str(dest),
            classes=classes,
            feature_names=feat_names,
            window_size=window_size,
            dtype=dtype,
            metrics={},
            enabled_for_live=bool(payload.get("enabled_for_live", True)),
            notes=str(payload.get("notes") or ""),
        )

    def import_models_directory(self, payload: dict[str, Any]) -> dict[str, Any]:
        scan = self.scan_models_directory({"models_dir": str(payload["models_dir"])})
        imported: List[str] = []
        errors: List[dict[str, str]] = []
        for m in scan["models"]:
            if m.get("already_registered"):
                continue
            try:
                entry = self.import_existing_model({
                    "model_path": m["file_path"],
                    "enabled_for_live": bool(payload.get("enabled_for_live", True)),
                })
                imported.append(entry["model_id"])
            except Exception as exc:
                errors.append({"file": m["file_name"], "error": str(exc)})
        return {"imported_count": len(imported), "error_count": len(errors), "imported": imported, "errors": errors}

    # ── Model registry ──────────────────────────────────────────────────────

    def list_models(self) -> List[dict[str, Any]]:
        return mr.load_registry(self.e6_root)

    def get_model(self, model_id: str) -> dict[str, Any]:
        entry = mr.get_model(self.e6_root, model_id)
        if entry is None:
            raise ValueError(f"Model not found: {model_id}")
        return entry

    def set_live_enabled(self, model_id: str, enabled: bool) -> dict[str, Any]:
        return mr.set_live_enabled(self.e6_root, model_id, enabled)

    def live_ready_models(self) -> List[dict[str, Any]]:
        return mr.live_ready_models(self.e6_root)

    # ── Inference ───────────────────────────────────────────────────────────

    def predict_file(self, payload: dict[str, Any]) -> dict[str, Any]:
        entry = self._resolve_model_entry(str(payload["model_id"]))
        return li.predict_from_iq_file(
            model_path=entry["model_path"],
            iq_path=str(payload["iq_path"]),
            dtype=payload.get("dtype"),
            sample_count=payload.get("sample_count"),
            top_k=int(payload.get("top_k") or 5),
        )

    def predict_live_window(self, payload: dict[str, Any]) -> dict[str, Any]:
        entry = self._resolve_model_entry(str(payload["model_id"]))
        real = np.asarray(payload.get("iq_samples_real") or [], dtype=np.float32)
        imag = np.asarray(payload.get("iq_samples_imag") or [], dtype=np.float32)
        if real.size == 0:
            raise ValueError("iq_samples_real must not be empty")
        iq = (real + 1j * imag).astype(np.complex64)
        return li.predict_from_iq_array(
            model_path=entry["model_path"],
            iq=iq,
            window_size=payload.get("window_size"),
            top_k=int(payload.get("top_k") or 5),
        )

    def predict_frozen_spectrum(self, payload: dict[str, Any]) -> dict[str, Any]:
        entry = self._resolve_model_entry(str(payload["model_id"]))
        return li.predict_from_spectrum_window(
            model_path=entry["model_path"],
            frequency_array_hz=list(payload.get("frequency_array_hz") or []),
            power_levels_db=list(payload.get("power_levels_db") or []),
            marker_start_hz=payload.get("marker_start_hz"),
            marker_stop_hz=payload.get("marker_stop_hz"),
            top_k=int(payload.get("top_k") or 5),
        )

    def _resolve_model_entry(self, model_id: str) -> dict[str, Any]:
        entry = mr.get_model(self.e6_root, model_id)
        if entry is None:
            raise ValueError(f"Model not found in E6 registry: {model_id}")
        if not Path(str(entry.get("model_path", ""))).exists():
            raise FileNotFoundError(f"Model file missing: {entry.get('model_path')}")
        return entry
