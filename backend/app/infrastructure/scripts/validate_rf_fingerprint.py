#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#C:\Users\Usuario\radioconda\python.exe validate_rf_fingerprint.py --val-root rf_data/val --model-dir remote_trained_model --output-json validation_report.json
import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def load_cfile(path: str) -> np.ndarray:
    return np.fromfile(path, dtype=np.complex64)


def normalize_window(iq: np.ndarray) -> np.ndarray:
    iq = iq - np.mean(iq)
    power = np.sqrt(np.mean(np.abs(iq) ** 2) + 1e-12)
    iq = iq / power
    return iq.astype(np.complex64)


def segment_indices(num_samples: int, window_size: int, stride: int) -> List[int]:
    if num_samples < window_size:
        return []
    return list(range(0, num_samples - window_size + 1, stride))


class RFEncoder(nn.Module):
    def __init__(self, embedding_dim: int = 128):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv1d(2, 32, kernel_size=7, padding=3),
            nn.BatchNorm1d(32),
            nn.ReLU(inplace=True),
            nn.MaxPool1d(2),

            nn.Conv1d(32, 64, kernel_size=5, padding=2),
            nn.BatchNorm1d(64),
            nn.ReLU(inplace=True),
            nn.MaxPool1d(2),

            nn.Conv1d(64, 128, kernel_size=5, padding=2),
            nn.BatchNorm1d(128),
            nn.ReLU(inplace=True),
            nn.MaxPool1d(2),

            nn.Conv1d(128, 256, kernel_size=3, padding=1),
            nn.BatchNorm1d(256),
            nn.ReLU(inplace=True),

            nn.AdaptiveAvgPool1d(1),
        )
        self.embedding = nn.Linear(256, embedding_dim)

    def forward(self, x):
        x = self.features(x)
        x = x.squeeze(-1)
        z = self.embedding(x)
        z = F.normalize(z, p=2, dim=1)
        return z


class RFClassifier(nn.Module):
    def __init__(self, num_classes: int, embedding_dim: int = 128):
        super().__init__()
        self.encoder = RFEncoder(embedding_dim=embedding_dim)
        self.classifier = nn.Linear(embedding_dim, num_classes)

    def forward(self, x):
        z = self.encoder(x)
        logits = self.classifier(z)
        return logits, z


class ValidationWindowDataset(Dataset):
    def __init__(self, records: List[dict], device_to_label: Dict[str, int], window_size: int, stride: int):
        self.records = records
        self.device_to_label = device_to_label
        self.window_size = window_size
        self.stride = stride
        self.index = []
        self.cache = {}

        for rec_idx, rec in enumerate(records):
            iq = load_cfile(rec["iq_file"])
            starts = segment_indices(len(iq), self.window_size, self.stride)
            for st in starts:
                self.index.append((rec_idx, st))

        if not self.index:
            raise RuntimeError("No validation windows generated")

    def __len__(self):
        return len(self.index)

    def __getitem__(self, idx):
        rec_idx, start = self.index[idx]
        rec = self.records[rec_idx]
        path = rec["iq_file"]

        if path not in self.cache:
            self.cache[path] = load_cfile(path)

        iq = self.cache[path][start:start + self.window_size]
        iq = normalize_window(iq)
        x = np.stack([iq.real, iq.imag], axis=0).astype(np.float32)
        y = np.int64(self.device_to_label[rec["emitter_device_id"]])
        return torch.from_numpy(x), torch.tensor(y), rec_idx


def discover_validation_records(val_root: Path) -> List[dict]:
    records = []
    for meta_path in sorted(val_root.rglob("*.json")):
        try:
            meta = load_json(meta_path)
        except Exception:
            continue

        iq_file = meta.get("iq_file")
        if not iq_file:
            continue

        iq_path = Path(iq_file)
        if not iq_path.exists():
            continue

        emitter = meta.get("emitter_device_id", "").strip()
        session_id = meta.get("session_id", "").strip()
        if not emitter or not session_id:
            continue

        records.append({
            "iq_file": str(iq_path),
            "metadata_file": str(meta_path),
            "emitter_device_id": emitter,
            "session_id": session_id,
            "receiver_id": meta.get("receiver_id", ""),
            "environment_id": meta.get("environment_id", ""),
            "center_frequency_hz": float(meta.get("center_frequency_hz", 0.0)),
            "original_center_frequency_hz": float(meta.get("original_center_frequency_hz", meta.get("center_frequency_hz", 0.0))),
            "sample_rate_hz": float(meta.get("canonical_sample_rate_hz", meta.get("sample_rate_hz", 0.0))),
            "canonicalized": bool(meta.get("canonicalized", False)),
            "canonical_center_hz": float(meta.get("canonical_center_hz", 0.0)),
            "canonical_sample_rate_hz": float(meta.get("canonical_sample_rate_hz", meta.get("sample_rate_hz", 0.0))),
            "canonical_bandwidth_hz": float(meta.get("canonical_bandwidth_hz", meta.get("bandwidth_hz", 0.0))),
            "canonical_segment_length_samples": int(meta.get("canonical_segment_length_samples", 0) or 0),
            "preprocessing_profile_id": str(meta.get("preprocessing_profile_id", "")).strip(),
        })
    return records


@torch.no_grad()
def main():
    parser = argparse.ArgumentParser(description="Validate trained RF fingerprint model on separate validation dataset")
    parser.add_argument("--val-root", required=True, help="Validation dataset root, for example rf_data/val")
    parser.add_argument("--model-dir", required=True, help="Directory with best_model.pt and enrollment_profiles.json")
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--output-json", default="validation_report.json")
    parser.add_argument("--selected-metadata-path", action="append", default=[])
    args = parser.parse_args()

    model_dir = Path(args.model_dir)
    ckpt = torch.load(model_dir / "best_model.pt", map_location="cpu")
    profiles = load_json(model_dir / "enrollment_profiles.json")

    device_to_label = ckpt["device_to_label"]
    label_to_device = ckpt["label_to_device"]
    window_size = ckpt["window_size"]
    stride = ckpt["stride"]
    embedding_dim = ckpt["embedding_dim"]

    val_records = discover_validation_records(Path(args.val_root))
    if args.selected_metadata_path:
        selected_set = {str(Path(p).resolve()) for p in args.selected_metadata_path}
        val_records = [r for r in val_records if str(Path(r["metadata_file"]).resolve()) in selected_set]
    if not val_records:
        raise RuntimeError("No validation records found")

    filtered_records = [r for r in val_records if r["emitter_device_id"] in device_to_label]
    if not filtered_records:
        raise RuntimeError("Validation set has no records matching trained device labels")

    expected_profile = ckpt.get("preprocessing_profile_id")
    expected_sample_rate = ckpt.get("canonical_sample_rate_hz")
    expected_bandwidth = ckpt.get("canonical_bandwidth_hz")
    expected_segment = ckpt.get("canonical_segment_length_samples", window_size)
    for rec in filtered_records:
        if not rec.get("canonicalized"):
            raise RuntimeError("Validation record is not canonicalized: {}".format(rec["metadata_file"]))
        if expected_profile and rec.get("preprocessing_profile_id") != expected_profile:
            raise RuntimeError("Validation preprocessing_profile_id mismatch. Model={} record={} file={}".format(expected_profile, rec.get("preprocessing_profile_id"), rec["metadata_file"]))
        if expected_sample_rate is not None and round(float(rec.get("canonical_sample_rate_hz", 0.0)), 6) != round(float(expected_sample_rate), 6):
            raise RuntimeError("Validation canonical_sample_rate_hz mismatch. Model={} record={} file={}".format(expected_sample_rate, rec.get("canonical_sample_rate_hz"), rec["metadata_file"]))
        if expected_bandwidth is not None and round(float(rec.get("canonical_bandwidth_hz", 0.0)), 3) != round(float(expected_bandwidth), 3):
            raise RuntimeError("Validation canonical_bandwidth_hz mismatch. Model={} record={} file={}".format(expected_bandwidth, rec.get("canonical_bandwidth_hz"), rec["metadata_file"]))
        if int(rec.get("canonical_segment_length_samples", 0)) != int(expected_segment):
            raise RuntimeError("Validation canonical_segment_length_samples mismatch. Model={} record={} file={}".format(expected_segment, rec.get("canonical_segment_length_samples"), rec["metadata_file"]))

    ds = ValidationWindowDataset(filtered_records, device_to_label, window_size, stride)
    dl = DataLoader(ds, batch_size=args.batch_size, shuffle=False, num_workers=0)

    model = RFClassifier(num_classes=len(device_to_label), embedding_dim=embedding_dim)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()

    profile_centroids = {}
    profile_thresholds = {}
    for dev_id, prof in profiles.items():
        profile_centroids[dev_id] = np.asarray(prof["centroid"], dtype=np.float32)
        profile_thresholds[dev_id] = float(prof["accept_threshold"])

    per_record = []
    for rec in filtered_records:
        per_record.append({
            "true_device": rec["emitter_device_id"],
            "session_id": rec["session_id"],
            "num_windows": 0,
            "pred_votes": {},
            "embeddings": []
        })

    total_correct = 0
    total_windows = 0

    for x, y, rec_idx in dl:
        logits, z = model(x)
        preds = torch.argmax(logits, dim=1)

        total_correct += (preds == y).sum().item()
        total_windows += x.size(0)

        z_np = z.numpy()
        preds_np = preds.numpy()
        rec_idx_np = rec_idx.numpy()

        for emb, pred, ridx in zip(z_np, preds_np, rec_idx_np):
            rec = per_record[int(ridx)]
            pred_dev = label_to_device[int(pred)]
            rec["num_windows"] += 1
            rec["pred_votes"][pred_dev] = rec["pred_votes"].get(pred_dev, 0) + 1
            rec["embeddings"].append(emb.tolist())

    report_records = []
    closed_set_record_acc = 0

    for rec in per_record:
        votes = rec["pred_votes"]
        predicted_device = max(votes.items(), key=lambda kv: kv[1])[0] if votes else None
        closed_set_ok = predicted_device == rec["true_device"]
        if closed_set_ok:
            closed_set_record_acc += 1

        emb = np.asarray(rec["embeddings"], dtype=np.float32)
        emb_mean = emb.mean(axis=0)
        emb_mean = emb_mean / (np.linalg.norm(emb_mean) + 1e-12)

        true_dev = rec["true_device"]
        centroid = profile_centroids[true_dev]
        dist_true = float(np.linalg.norm(emb_mean - centroid))
        accept_threshold = profile_thresholds[true_dev]
        same_device_accept = dist_true <= accept_threshold

        distances_all = {}
        for dev_id, c in profile_centroids.items():
            distances_all[dev_id] = float(np.linalg.norm(emb_mean - c))

        nearest_device = min(distances_all.items(), key=lambda kv: kv[1])[0]
        nearest_distance = distances_all[nearest_device]

        report_records.append({
            "true_device": true_dev,
            "session_id": rec["session_id"],
            "num_windows": rec["num_windows"],
            "predicted_device_majority_vote": predicted_device,
            "closed_set_correct": closed_set_ok,
            "distance_to_true_profile": dist_true,
            "true_accept_threshold": accept_threshold,
            "same_device_accept": same_device_accept,
            "nearest_profile_device": nearest_device,
            "nearest_profile_distance": nearest_distance,
            "all_profile_distances": distances_all,
            "vote_distribution": votes
        })

    report = {
        "num_validation_records": len(report_records),
        "window_level_closed_set_accuracy": total_correct / max(1, total_windows),
        "record_level_closed_set_accuracy": closed_set_record_acc / max(1, len(report_records)),
        "records": report_records
    }

    save_json(Path(args.output_json), report)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
