from __future__ import annotations

import importlib.util
import random
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from app.modules.rf_experiment_lab.experiment_config_schema import ExperimentSplitConfig
from app.modules.rf_experiment_lab.metrics_service import MetricsService


class E1RawIQCNN1DService:
    experiment_id = "e1_raw_iq_cnn1d"
    paper_reference = "Riyaz et al.; Jian et al."

    def __init__(self, representation_service, dataset_adapter, split_manager, result_store) -> None:
        self.representation_service = representation_service
        self.dataset_adapter = dataset_adapter
        self.split_manager = split_manager
        self.result_store = result_store
        self.metrics_service = MetricsService()

    def preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = self._config(payload)
        captures = self._selected_captures(config)
        labels = self._labels(captures, config)
        split = self._split(captures, config)
        windows = self._build_window_index(captures, config, split["assignments"], preview=True)
        warnings = self._warnings(windows, labels["labels"])
        eligibility = self.dataset_adapter.training_eligibility_summary(config)
        return {
            "experiment_id": self.experiment_id,
            "preview_only": True,
            "training_started": False,
            "paper_reference": self.paper_reference,
            "stage": "stage_2",
            "task": "device_fingerprinting_closed_set",
            "input_representation": "raw_iq",
            "input_shape": [2, config["window_size_samples"]],
            "torch": {"available": self._torch_available(config), "status": "available" if self._torch_available(config) else "not_available"},
            "dataset": {
                "capture_count": len(captures),
                "sample_count": len(windows),
                "class_count": len(labels["labels"]),
                "labels": labels["labels"],
                "class_balance": dict(Counter(item["label"] for item in windows)),
                "missing_label_capture_ids": labels["missing_capture_ids"],
                "weak_label_capture_ids": labels["weak_label_capture_ids"],
                "label_field": config["label_field"],
                "training_readiness_policy": config["training_readiness_policy"],
                "training_eligibility": eligibility,
            },
            "split": split,
            "warnings": warnings,
            "available_for_training": self._torch_available(config) and not labels["missing_capture_ids"] and not labels["weak_label_capture_ids"] and len(labels["labels"]) >= 2,
        }

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = self._config(payload)
        if not self._torch_available(config):
            raise RuntimeError("PyTorch is unavailable; E1 Raw IQ CNN 1D training is disabled")
        captures = self._selected_captures(config)
        eligibility = self.dataset_adapter.training_eligibility_summary(config)
        if not captures:
            raise ValueError(
                "E1 found no eligible captures for closed-set fingerprinting under "
                f"{config['training_readiness_policy']}. "
                f"Eligibility summary: {eligibility}. "
                "E1 requires reviewed physical transmitter_id labels, not only band-profile weak labels."
            )
        labels = self._labels(captures, config)
        if labels["missing_capture_ids"] or labels["weak_label_capture_ids"]:
            raise ValueError(
                "E1 is closed-set physical fingerprinting and requires strong transmitter labels. "
                f"Missing: {', '.join(labels['missing_capture_ids']) or 'none'}. "
                f"Weak/unconfirmed: {', '.join(labels['weak_label_capture_ids']) or 'none'}. "
                "Do not train E1 from band-profile weak labels; confirm physical transmitter_id in Dataset Builder first."
            )
        if len(labels["labels"]) < 2:
            raise ValueError(
                "E1 requires at least two physical device classes after readiness filtering. "
                f"Label field: {config['label_field']}. Labels found: {labels['labels']}. "
                f"Eligibility summary: {eligibility}."
            )
        split = self._split(captures, config)
        windows = self._build_window_index(captures, config, split["assignments"], preview=False)
        train_items = [item for item in windows if item["split"] == "train"]
        eval_items = [item for item in windows if item["split"] in {"validation", "test"}]
        if not train_items or not eval_items:
            raise ValueError("E1 split produced empty train or evaluation set")
        if len({item["label"] for item in train_items}) < 2:
            raise ValueError("E1 training split must contain at least two classes")
        missing_from_train = sorted({item["label"] for item in eval_items} - {item["label"] for item in train_items})
        if missing_from_train:
            raise ValueError("E1 closed-set evaluation has transmitter classes missing from train split: " + ", ".join(missing_from_train))

        import torch
        from torch import nn
        from torch.utils.data import DataLoader, Dataset

        self._set_seed(config["seed"], torch)
        device = torch.device("cuda" if torch.cuda.is_available() and config["device"] == "auto" else "cpu")
        label_to_idx = {label: idx for idx, label in enumerate(labels["labels"])}

        class WindowDataset(Dataset):
            def __init__(self, outer, items):
                self.outer = outer
                self.items = items

            def __len__(self):
                return len(self.items)

            def __getitem__(self, index):
                item = self.items[index]
                iq = self.outer.representation_service.read_iq_window_for_features(item["context"], item["window"])
                channels = np.stack([iq.real, iq.imag]).astype(np.float32)
                return torch.from_numpy(channels), torch.tensor(label_to_idx[item["label"]], dtype=torch.long), item

        def collate(batch):
            x = torch.stack([item[0] for item in batch])
            y = torch.stack([item[1] for item in batch])
            meta = [item[2] for item in batch]
            return x, y, meta

        model = SmallCNN1D(len(labels["labels"])).to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=config["learning_rate"], weight_decay=config["weight_decay"])
        criterion = nn.CrossEntropyLoss()
        train_loader = DataLoader(WindowDataset(self, train_items), batch_size=config["batch_size"], shuffle=True, collate_fn=collate)
        eval_loader = DataLoader(WindowDataset(self, eval_items), batch_size=config["batch_size"], shuffle=False, collate_fn=collate)

        history = []
        best_loss = float("inf")
        stale = 0
        started = time.perf_counter()
        for epoch in range(1, config["epochs"] + 1):
            epoch_started = time.perf_counter()
            model.train()
            train_loss = self._epoch_train(model, train_loader, optimizer, criterion, device)
            val_loss = self._epoch_loss(model, eval_loader, criterion, device)
            train_acc = self._accuracy(model, train_loader, device)
            val_acc = self._accuracy(model, eval_loader, device)
            history.append(
                {
                    "epoch": epoch,
                    "train_loss": train_loss,
                    "validation_loss": val_loss,
                    "train_accuracy": train_acc,
                    "validation_accuracy": val_acc,
                    "learning_rate": optimizer.param_groups[0]["lr"],
                    "epoch_time_ms": (time.perf_counter() - epoch_started) * 1000.0,
                }
            )
            if val_loss < best_loss:
                best_loss = val_loss
                stale = 0
            else:
                stale += 1
            if config["early_stopping"] and stale >= config["patience"]:
                break
        training_time_ms = (time.perf_counter() - started) * 1000.0

        started = time.perf_counter()
        predictions = self._predict(model, eval_loader, device, labels["labels"])
        inference_time_ms = (time.perf_counter() - started) * 1000.0
        truth = [item["true_label"] for item in predictions]
        pred = [item["predicted_label"] for item in predictions]
        metrics = self.metrics_service.classification_metrics(truth, pred)
        group_metrics = self._group_metrics(predictions)
        confidence_summary = self._confidence_summary(predictions)
        overfitting_summary = self._overfitting_summary(history, config, len(labels["labels"]))
        metrics.update(
            {
                "train_loss": history[-1]["train_loss"] if history else None,
                "validation_loss": history[-1]["validation_loss"] if history else None,
                "training_time_ms": training_time_ms,
                "inference_time_ms": inference_time_ms,
                "number_of_train_samples": len(train_items),
                "number_of_test_samples": len(eval_items),
                "number_of_classes": len(labels["labels"]),
                "accuracy_by_capture_id": group_metrics["accuracy_by_capture_id"],
                "accuracy_by_session_id": group_metrics["accuracy_by_session_id"],
                "accuracy_by_day_id": group_metrics["accuracy_by_day_id"],
                "accuracy_by_snr_bin": group_metrics["accuracy_by_snr_bin"],
                "accuracy_by_class": group_metrics["accuracy_by_class"],
            }
        )
        result_dir = self.result_store.root / "results" / self.experiment_id / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        result_dir.mkdir(parents=True, exist_ok=False)
        model_path = result_dir / "model.pt"
        torch.save({"model_state_dict": model.state_dict(), "label_to_idx": label_to_idx, "config": config}, model_path)
        metrics["model_size_bytes"] = model_path.stat().st_size
        model_metadata = self._model_metadata(model, config, device, torch, split)
        package = self.result_store.write_e1_artifacts(
            result_dir,
            config,
            model_path,
            str(model),
            metrics,
            predictions,
            split,
            [{"step": "training", "status": "ok", "message": f"{len(history)} epochs", "latency_ms": training_time_ms}],
            history,
            overfitting_summary=overfitting_summary,
            group_metrics=group_metrics,
            confidence_summary=confidence_summary,
            model_metadata=model_metadata,
        )
        return {
            "experiment_id": self.experiment_id,
            "preview_only": False,
            "training_started": True,
            "training_completed": True,
            "paper_reference": self.paper_reference,
            "config": config,
            "metrics": metrics,
            "result_package": package,
        }

    def _config(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "dataset_version": payload.get("dataset_version", "unversioned"),
            "dataset_manifest_path": payload.get("dataset_manifest_path") or payload.get("rf_experiment_dataset_path"),
            "capture_ids": payload.get("capture_ids") or [],
            "label_field": payload.get("label_field", "transmitter_id"),
            "split": payload.get("split") or {"strategy": "session_disjoint", "group_by": ["session_id"]},
            "window_size_samples": int(payload.get("window_size_samples", 2048)),
            "overlap": float(payload.get("overlap", 0.0)),
            "max_windows": int(payload.get("max_windows", 128)),
            "epochs": int(payload.get("epochs", 30)),
            "batch_size": int(payload.get("batch_size", 32)),
            "learning_rate": float(payload.get("learning_rate", 0.001)),
            "optimizer": payload.get("optimizer", "adam"),
            "weight_decay": float(payload.get("weight_decay", 0.0)),
            "early_stopping": bool(payload.get("early_stopping", True)),
            "patience": int(payload.get("patience", 5)),
            "seed": int(payload.get("seed", 42)),
            "device": payload.get("device", "auto"),
            "force_torch_unavailable": bool(payload.get("force_torch_unavailable", False)),
            "training_readiness_policy": payload.get("training_readiness_policy", "scientific_strict"),
            "allow_weak_labels_debug": bool(payload.get("allow_weak_labels_debug", False)),
        }

    def _torch_available(self, config: dict[str, Any]) -> bool:
        return not config.get("force_torch_unavailable") and importlib.util.find_spec("torch") is not None

    def _selected_captures(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        captures = self.dataset_adapter.list_training_records(config)
        ids = {str(item) for item in config.get("capture_ids", [])}
        if ids:
            captures = [item for item in captures if str(item.get("capture_id")) in ids]
        return [item for item in captures if item.get("raw_file") and item.get("metadata_file")]

    def _labels(self, captures: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
        return self.dataset_adapter.validate_training_label_policy(
            captures,
            config["label_field"],
            allow_weak_labels=bool(config.get("allow_weak_labels_debug")),
        )

    def _split(self, captures: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
        split_payload = config.get("split") or {}
        split_config = ExperimentSplitConfig.model_validate(
            {
                "strategy": split_payload.get("strategy", "session_disjoint"),
                "group_by": split_payload.get("group_by", ["session_id"]),
                "train_ratio": split_payload.get("train_ratio", 0.7),
                "validation_ratio": split_payload.get("validation_ratio", 0.15),
                "test_ratio": split_payload.get("test_ratio", 0.15),
            }
        )
        return self.split_manager.build_split(captures, split_config)

    def _build_window_index(self, captures, config, assignments, preview: bool) -> list[dict[str, Any]]:
        items = []
        per_capture = max(1, config["max_windows"] // max(len(captures), 1))
        for capture in captures:
            payload = {
                "metadata_path": capture["metadata_file"],
                "iq_path": capture["raw_file"],
                "window_size_samples": config["window_size_samples"],
                "overlap": config["overlap"],
                "max_preview_windows": per_capture,
                "max_export_windows": per_capture,
                "preview": preview,
            }
            context, windows = self.representation_service.spectral_feature_source_windows(payload)
            for index, window in enumerate(windows):
                items.append(
                    {
                        "sample_id": f"{capture.get('capture_id')}:w{index:04d}",
                        "capture_id": str(capture.get("capture_id")),
                        "session_id": capture.get("session_id"),
                        "day_id": capture.get("day_id"),
                        "snr_bin": self._snr_bin(capture.get("snr_db")),
                        "label": self._label_value(capture, config["label_field"]),
                        "split": assignments.get(str(capture.get("capture_id"))),
                        "context": context,
                        "window": window,
                    }
                )
                if len(items) >= config["max_windows"]:
                    return items
        return items

    @staticmethod
    def _label_value(capture: dict[str, Any], label_field: str) -> str:
        value = capture.get(label_field)
        if value in (None, "") and capture.get("label_type") == label_field:
            value = capture.get("label")
        return str(value)

    def _snr_bin(self, snr_value: Any) -> str | None:
        if snr_value is None:
            return None
        try:
            snr = float(snr_value)
        except (TypeError, ValueError):
            return None
        if snr < 10:
            return "lt_10db"
        if snr < 20:
            return "10_20db"
        if snr < 30:
            return "20_30db"
        return "gte_30db"

    def _warnings(self, windows: list[dict[str, Any]], labels: list[str]) -> list[str]:
        warnings = []
        counts = Counter(item["label"] for item in windows)
        for label in labels:
            if counts.get(label, 0) < 2:
                warnings.append(f"class {label} has too few samples")
        train_labels = {item["label"] for item in windows if item["split"] == "train"}
        eval_labels = {item["label"] for item in windows if item["split"] in {"validation", "test"}}
        for label in labels:
            if label not in train_labels:
                warnings.append(f"class {label} missing in train split")
            if label not in eval_labels:
                warnings.append(f"class {label} missing in evaluation split")
        return warnings

    def _set_seed(self, seed: int, torch) -> None:
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)

    def _epoch_train(self, model, loader, optimizer, criterion, device) -> float:
        losses = []
        for x, y, _ in loader:
            x = x.to(device)
            y = y.to(device)
            optimizer.zero_grad()
            loss = criterion(model(x), y)
            loss.backward()
            optimizer.step()
            losses.append(float(loss.item()))
        return float(np.mean(losses)) if losses else 0.0

    def _epoch_loss(self, model, loader, criterion, device) -> float:
        import torch

        model.eval()
        losses = []
        with torch.no_grad():
            for x, y, _ in loader:
                losses.append(float(criterion(model(x.to(device)), y.to(device)).item()))
        return float(np.mean(losses)) if losses else 0.0

    def _accuracy(self, model, loader, device) -> float:
        import torch

        model.eval()
        correct = 0
        total = 0
        with torch.no_grad():
            for x, y, _ in loader:
                pred = torch.argmax(model(x.to(device)), dim=1).cpu()
                correct += int(torch.sum(pred == y).item())
                total += int(y.numel())
        return correct / max(total, 1)

    def _predict(self, model, loader, device, labels: list[str]) -> list[dict[str, Any]]:
        import torch

        model.eval()
        rows = []
        with torch.no_grad():
            for x, y, meta in loader:
                probs = torch.softmax(model(x.to(device)), dim=1).cpu().numpy()
                pred_idx = np.argmax(probs, axis=1)
                for i, item in enumerate(meta):
                    true_label = labels[int(y[i].item())]
                    predicted = labels[int(pred_idx[i])]
                    rows.append(
                        {
                            "sample_id": item["sample_id"],
                            "true_label": true_label,
                            "predicted_label": predicted,
                            "correct": str(true_label == predicted).lower(),
                            "confidence": float(np.max(probs[i])),
                            "model_name": "cnn1d",
                            "split": item["split"],
                            "capture_id": item["capture_id"],
                            "session_id": item.get("session_id"),
                            "day_id": item.get("day_id"),
                            "snr_bin": item.get("snr_bin"),
                        }
                    )
        return rows

    def _group_metrics(self, predictions: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "accuracy_by_capture_id": self._accuracy_by(predictions, "capture_id"),
            "accuracy_by_session_id": self._accuracy_by(predictions, "session_id"),
            "accuracy_by_day_id": self._accuracy_by(predictions, "day_id"),
            "accuracy_by_snr_bin": self._accuracy_by(predictions, "snr_bin"),
            "accuracy_by_class": self._accuracy_by(predictions, "true_label"),
        }

    def _accuracy_by(self, predictions: list[dict[str, Any]], key: str) -> dict[str, Any]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in predictions:
            value = str(row.get(key) or "unknown")
            groups.setdefault(value, []).append(row)
        return {
            group: {
                "accuracy": sum(1 for row in rows if row.get("correct") == "true") / max(len(rows), 1),
                "count": len(rows),
            }
            for group, rows in groups.items()
        }

    def _confidence_summary(self, predictions: list[dict[str, Any]]) -> dict[str, Any]:
        correct = [float(row["confidence"]) for row in predictions if row.get("correct") == "true" and row.get("confidence") is not None]
        incorrect = [float(row["confidence"]) for row in predictions if row.get("correct") == "false" and row.get("confidence") is not None]
        high_errors = [row for row in predictions if row.get("correct") == "false" and float(row.get("confidence") or 0.0) >= 0.8]
        low_correct = [row for row in predictions if row.get("correct") == "true" and float(row.get("confidence") or 0.0) <= 0.55]
        mean_correct = float(np.mean(correct)) if correct else None
        mean_incorrect = float(np.mean(incorrect)) if incorrect else None
        return {
            "mean_confidence_correct": mean_correct,
            "mean_confidence_incorrect": mean_incorrect,
            "high_confidence_errors": len(high_errors),
            "low_confidence_correct": len(low_correct),
            "calibration_warning": bool(mean_incorrect is not None and mean_correct is not None and mean_incorrect >= mean_correct),
        }

    def _overfitting_summary(self, history: list[dict[str, Any]], config: dict[str, Any], class_count: int) -> dict[str, Any]:
        if not history:
            return {}
        best = min(history, key=lambda row: row["validation_loss"])
        final = history[-1]
        patience = max(int(config.get("patience", 5)), 1)
        recent = history[-patience:] if len(history) >= patience else history
        overfit = len(recent) >= patience and recent[-1]["train_loss"] <= recent[0]["train_loss"] and recent[-1]["validation_loss"] > recent[0]["validation_loss"]
        chance = 1.0 / max(class_count, 1)
        underfit = bool(final.get("train_accuracy", 0.0) <= chance + 0.05 and final.get("validation_accuracy", 0.0) <= chance + 0.05)
        return {
            "best_epoch": best["epoch"],
            "best_validation_loss": best["validation_loss"],
            "final_train_loss": final["train_loss"],
            "final_validation_loss": final["validation_loss"],
            "train_val_loss_gap": final["validation_loss"] - final["train_loss"],
            "early_stopped": len(history) < config["epochs"],
            "overfitting_warning": bool(overfit),
            "underfitting_warning": bool(underfit),
        }

    def _model_metadata(self, model, config: dict[str, Any], device, torch, split: dict[str, Any]) -> dict[str, Any]:
        parameter_count = sum(int(p.numel()) for p in model.parameters())
        trainable = sum(int(p.numel()) for p in model.parameters() if p.requires_grad)
        return {
            "model_type": "cnn1d",
            "architecture_name": "SmallCNN1D",
            "input_shape": [2, config["window_size_samples"]],
            "parameter_count": parameter_count,
            "trainable_parameter_count": trainable,
            "device_used": str(device),
            "torch_version": torch.__version__,
            "cuda_available": bool(torch.cuda.is_available()),
            "dataset_version": config.get("dataset_version"),
            "split_strategy": split.get("strategy"),
            "paper_reference": self.paper_reference,
        }


def SmallCNN1D(num_classes: int):
    import torch.nn as nn

    return nn.Sequential(
        nn.Conv1d(2, 16, kernel_size=7, padding=3),
        nn.BatchNorm1d(16),
        nn.ReLU(),
        nn.MaxPool1d(2),
        nn.Conv1d(16, 32, kernel_size=5, padding=2),
        nn.BatchNorm1d(32),
        nn.ReLU(),
        nn.MaxPool1d(2),
        nn.Conv1d(32, 64, kernel_size=3, padding=1),
        nn.ReLU(),
        nn.AdaptiveAvgPool1d(1),
        nn.Flatten(),
        nn.Linear(64, num_classes),
    )
