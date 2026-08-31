#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# primera vez 
#C:\Users\Usuario\radioconda\python.exe train_or_resume_rf_fingerprint.py --data-root rf_dataset --model-root rf_model_store --epochs 20 --batch-size 128 --window-size 1024 --stride 1024

#Día siguiente, tras añadir más capturas con el script de captura
#C:\Users\Usuario\radioconda\python.exe train_or_resume_rf_fingerprint.py --data-root rf_dataset --model-root rf_model_store --epochs 10 --batch-size 128 --window-size 1024 --stride 1024
import argparse
import copy
import hashlib
import json
import os
import random
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

os.environ.setdefault("PYTORCH_NVML_BASED_CUDA_CHECK", "1")

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def get_best_device(force_cpu: bool = False) -> torch.device:
    if force_cpu:
        return torch.device("cpu")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sanitize_name(s: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in s).strip("_")


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, obj: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def discover_records(data_root: Path) -> List[dict]:
    records = []
    for meta_path in sorted(data_root.rglob("*.json")):
        try:
            meta = load_json(meta_path)
        except Exception:
            continue

        iq_file = meta.get("iq_file")
        if not iq_file:
            continue

        iq_path = Path(iq_file)
        if not iq_path.exists():
            candidate = meta_path.with_suffix(".cfile")
            if candidate.exists():
                iq_path = candidate
            else:
                continue

        emitter_device_id = meta.get("emitter_device_id", "").strip()
        session_id = meta.get("session_id", "").strip()

        if not emitter_device_id or not session_id:
            continue

        rec = {
            "iq_file": str(iq_path.resolve()),
            "metadata_file": str(meta_path.resolve()),
            "emitter_device_id": emitter_device_id,
            "session_id": session_id,
            "receiver_id": meta.get("receiver_id", meta.get("source_device", "")),
            "environment_id": meta.get("environment_id", ""),
            "sample_rate_hz": float(meta.get("canonical_sample_rate_hz", meta.get("sample_rate_hz", 0.0))),
            "center_frequency_hz": float(meta.get("center_frequency_hz", 0.0)),
            "original_center_frequency_hz": float(meta.get("original_center_frequency_hz", meta.get("center_frequency_hz", 0.0))),
            "canonicalized": bool(meta.get("canonicalized", False)),
            "canonical_center_hz": float(meta.get("canonical_center_hz", 0.0)),
            "canonical_sample_rate_hz": float(meta.get("canonical_sample_rate_hz", meta.get("sample_rate_hz", 0.0))),
            "canonical_bandwidth_hz": float(meta.get("canonical_bandwidth_hz", meta.get("bandwidth_hz", 0.0))),
            "canonical_segment_length_samples": int(meta.get("canonical_segment_length_samples", 0) or 0),
            "preprocessing_profile_id": str(meta.get("preprocessing_profile_id", "")).strip(),
            "duration_seconds": float(meta.get("duration_seconds", 0.0)),
            "sha256": meta.get("sha256", ""),
            "label": meta.get("label", ""),
            "modulation_hint": meta.get("modulation_hint", ""),
        }
        records.append(rec)

    records.sort(key=lambda x: (x["emitter_device_id"], x["session_id"], x["iq_file"]))
    return records


def validate_records(records: List[dict]) -> None:
    if not records:
        raise RuntimeError("No valid JSON plus CFILE pairs were found")

    if not all(r.get("canonicalized") for r in records):
        raise RuntimeError("Training requires canonicalized=true for every record. Export the dataset through RF canonicalization first.")

    sample_rates = sorted({round(r["canonical_sample_rate_hz"], 6) for r in records})
    if len(sample_rates) != 1:
        raise RuntimeError("Mixed canonical_sample_rate_hz detected after preprocessing. Found: {}".format(sample_rates))

    bandwidths = sorted({round(r["canonical_bandwidth_hz"], 3) for r in records})
    if len(bandwidths) != 1:
        raise RuntimeError("Mixed canonical_bandwidth_hz detected after preprocessing. Found: {}".format(bandwidths))

    segment_lengths = sorted({int(r["canonical_segment_length_samples"]) for r in records})
    if len(segment_lengths) != 1:
        raise RuntimeError("Mixed canonical_segment_length_samples detected. Found: {}".format(segment_lengths))

    profile_ids = sorted({r["preprocessing_profile_id"] for r in records})
    if len(profile_ids) != 1 or not profile_ids[0]:
        raise RuntimeError("Training requires exactly one preprocessing_profile_id. Found: {}".format(profile_ids))

    devices = sorted({r["emitter_device_id"] for r in records})
    if len(devices) < 2:
        counts = {}
        for r in records:
            counts[r["emitter_device_id"]] = counts.get(r["emitter_device_id"], 0) + 1
        details = ", ".join("{}={}".format(k, counts[k]) for k in sorted(counts))
        raise RuntimeError(
            "At least two emitter_device_id values are required for classification training. "
            "Found {} unique IDs: {}".format(len(devices), details if details else "<none>")
        )

    sessions_per_device = {}
    for r in records:
        sessions_per_device.setdefault(r["emitter_device_id"], set()).add(r["session_id"])

    insufficient = [d for d, s in sessions_per_device.items() if len(s) < 2]
    if insufficient:
        print("[WARN] These devices have less than 2 sessions and evaluation rigor will be weaker: {}".format(insufficient))


def build_label_maps(records: List[dict]) -> Tuple[Dict[str, int], Dict[int, str]]:
    devices = sorted({r["emitter_device_id"] for r in records})
    device_to_label = {d: i for i, d in enumerate(devices)}
    label_to_device = {i: d for d, i in device_to_label.items()}
    return device_to_label, label_to_device


def build_split(records: List[dict], seed: int = 42, train_ratio: float = 0.8) -> dict:
    rng = random.Random(seed)
    sessions_by_device = {}
    for r in records:
        sessions_by_device.setdefault(r["emitter_device_id"], set()).add(r["session_id"])

    split = {"train_sessions": {}, "test_sessions": {}}
    for device_id, sessions in sessions_by_device.items():
        sessions = sorted(list(sessions))
        rng.shuffle(sessions)

        if len(sessions) == 1:
            split["train_sessions"][device_id] = sessions
            split["test_sessions"][device_id] = sessions
        else:
            n_train = max(1, int(len(sessions) * train_ratio))
            if n_train >= len(sessions):
                n_train = len(sessions) - 1
            train_sessions = sessions[:n_train]
            test_sessions = sessions[n_train:]
            split["train_sessions"][device_id] = train_sessions
            split["test_sessions"][device_id] = test_sessions

    return split


def split_records(records: List[dict], split: dict, subset: str) -> List[dict]:
    out = []
    key = "train_sessions" if subset == "train" else "test_sessions"
    for r in records:
        allowed = split[key].get(r["emitter_device_id"], [])
        if r["session_id"] in allowed:
            out.append(r)
    return out


def manifest_hash(records: List[dict]) -> str:
    data = json.dumps(records, sort_keys=True, ensure_ascii=False)
    return sha256_text(data)


def filter_records_by_center_frequency(
    records: List[dict],
    target_center_frequency_hz: float,
    tolerance_hz: float,
) -> List[dict]:
    out = []
    for r in records:
        if abs(float(r["center_frequency_hz"]) - float(target_center_frequency_hz)) <= float(tolerance_hz):
            out.append(r)
    return out


def load_cfile(path: str, max_complex_samples: int = None) -> np.ndarray:
    iq = np.fromfile(path, dtype=np.complex64)
    if max_complex_samples is not None:
        iq = iq[:max_complex_samples]
    return iq


def normalize_window(iq: np.ndarray) -> np.ndarray:
    iq = iq - np.mean(iq)
    power = np.sqrt(np.mean(np.abs(iq) ** 2) + 1e-12)
    iq = iq / power
    return iq.astype(np.complex64)


def segment_indices(num_samples: int, window_size: int, stride: int) -> List[int]:
    if num_samples < window_size:
        return []
    return list(range(0, num_samples - window_size + 1, stride))


class CFileWindowDataset(Dataset):
    def __init__(
        self,
        records: List[dict],
        device_to_label: Dict[str, int],
        window_size: int,
        stride: int,
        max_windows_per_file: int = None,
        max_complex_samples_per_file: int = None,
    ):
        self.records = records
        self.device_to_label = device_to_label
        self.window_size = window_size
        self.stride = stride
        self.max_windows_per_file = max_windows_per_file
        self.max_complex_samples_per_file = max_complex_samples_per_file

        self.index = []
        self.cache = {}

        for rec in self.records:
            file_path = rec["iq_file"]
            iq = load_cfile(file_path, max_complex_samples=self.max_complex_samples_per_file)
            starts = segment_indices(len(iq), self.window_size, self.stride)

            if self.max_windows_per_file is not None:
                starts = starts[:self.max_windows_per_file]

            for st in starts:
                self.index.append((file_path, st, self.device_to_label[rec["emitter_device_id"]]))

        if not self.index:
            raise RuntimeError("No training windows were generated. Check window_size, stride and capture duration")

    def __len__(self) -> int:
        return len(self.index)

    def __getitem__(self, idx: int):
        file_path, start, label = self.index[idx]

        if file_path not in self.cache:
            iq = load_cfile(file_path, max_complex_samples=self.max_complex_samples_per_file)
            self.cache[file_path] = iq

        iq = self.cache[file_path][start:start + self.window_size]
        iq = normalize_window(iq)

        x = np.stack([iq.real, iq.imag], axis=0).astype(np.float32)
        y = np.int64(label)
        return torch.from_numpy(x), torch.tensor(y, dtype=torch.long)


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


def build_model(num_classes: int, embedding_dim: int) -> RFClassifier:
    return RFClassifier(num_classes=num_classes, embedding_dim=embedding_dim)


def load_checkpoint_flex(model: RFClassifier, checkpoint: dict, device_to_label: Dict[str, int]) -> None:
    ckpt_state = checkpoint["model_state_dict"]
    ckpt_device_to_label = checkpoint["device_to_label"]
    current_state = model.state_dict()

    # Load all matching non-classifier weights
    filtered = {}
    for k, v in ckpt_state.items():
        if k.startswith("classifier."):
            continue
        if k in current_state and current_state[k].shape == v.shape:
            filtered[k] = v

    current_state.update(filtered)

    # Transfer classifier rows for shared devices
    old_w = ckpt_state.get("classifier.weight")
    old_b = ckpt_state.get("classifier.bias")
    new_w = current_state["classifier.weight"]
    new_b = current_state["classifier.bias"]

    for device_id, new_idx in device_to_label.items():
        if device_id in ckpt_device_to_label:
            old_idx = ckpt_device_to_label[device_id]
            if old_idx < old_w.shape[0] and new_idx < new_w.shape[0]:
                new_w[new_idx] = old_w[old_idx]
                new_b[new_idx] = old_b[old_idx]

    current_state["classifier.weight"] = new_w
    current_state["classifier.bias"] = new_b

    model.load_state_dict(current_state)


def train_one_epoch(model, loader, optimizer, device):
    model.train()
    total_loss = 0.0
    total_correct = 0
    total_items = 0

    for x, y in loader:
        x = x.to(device, non_blocking=True)
        y = y.to(device, non_blocking=True)

        optimizer.zero_grad(set_to_none=True)
        logits, z = model(x)

        ce_loss = F.cross_entropy(logits, y)

        center_terms = []
        for cls in torch.unique(y):
            mask = (y == cls)
            if mask.sum() > 1:
                center = z[mask].mean(dim=0, keepdim=True)
                center_terms.append(((z[mask] - center) ** 2).sum(dim=1).mean())

        center_loss = torch.stack(center_terms).mean() if center_terms else torch.tensor(0.0, device=device)
        loss = ce_loss + 0.05 * center_loss

        loss.backward()
        optimizer.step()

        preds = logits.argmax(dim=1)
        total_correct += (preds == y).sum().item()
        total_items += x.size(0)
        total_loss += loss.item() * x.size(0)

    return total_loss / max(1, total_items), total_correct / max(1, total_items)


@torch.no_grad()
def evaluate(model, loader, device):
    model.eval()
    total_loss = 0.0
    total_correct = 0
    total_items = 0

    for x, y in loader:
        x = x.to(device, non_blocking=True)
        y = y.to(device, non_blocking=True)

        logits, _ = model(x)
        loss = F.cross_entropy(logits, y)

        preds = logits.argmax(dim=1)
        total_correct += (preds == y).sum().item()
        total_items += x.size(0)
        total_loss += loss.item() * x.size(0)

    return total_loss / max(1, total_items), total_correct / max(1, total_items)


@torch.no_grad()
def build_enrollment_profiles(model, records, device_to_label, window_size, stride, max_windows_per_file, max_complex_samples_per_file, device):
    model.eval()

    per_dev_vectors = {}
    ds = CFileWindowDataset(
        records=records,
        device_to_label=device_to_label,
        window_size=window_size,
        stride=stride,
        max_windows_per_file=max_windows_per_file,
        max_complex_samples_per_file=max_complex_samples_per_file,
    )
    loader = DataLoader(ds, batch_size=256, shuffle=False, num_workers=0, pin_memory=torch.cuda.is_available())

    inv_map = {v: k for k, v in device_to_label.items()}

    for x, y in loader:
        x = x.to(device, non_blocking=True)
        _, z = model(x)
        z = z.cpu().numpy()
        y = y.numpy()

        for emb, cls in zip(z, y):
            per_dev_vectors.setdefault(inv_map[int(cls)], []).append(emb)

    profiles = {}
    for dev_id, vectors in per_dev_vectors.items():
        vectors = np.asarray(vectors, dtype=np.float32)
        centroid = vectors.mean(axis=0)
        centroid = centroid / (np.linalg.norm(centroid) + 1e-12)
        dists = np.linalg.norm(vectors - centroid[None, :], axis=1)

        profiles[dev_id] = {
            "centroid": centroid.tolist(),
            "mean_distance": float(dists.mean()),
            "std_distance": float(dists.std()),
            "accept_threshold": float(dists.mean() + 3.0 * max(dists.std(), 1e-6)),
            "num_embeddings": int(len(vectors)),
        }

    return profiles


def main():
    parser = argparse.ArgumentParser(description="Train or automatically resume RF fingerprint model from CFILE plus JSON dataset")
    parser.add_argument("--data-root", type=str, default="rf_dataset", help="Dataset root directory")
    parser.add_argument("--model-root", type=str, default="rf_model_store", help="Directory where checkpoints and manifests are stored")
    parser.add_argument("--window-size", type=int, default=1024, help="Window size in complex samples")
    parser.add_argument("--stride", type=int, default=1024, help="Stride in complex samples")
    parser.add_argument("--max-windows-per-file", type=int, default=3000, help="Cap windows per file for training")
    parser.add_argument("--max-complex-samples-per-file", type=int, default=None, help="Optional cap on complex samples loaded per file")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--embedding-dim", type=int, default=128)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--target-center-frequency-hz", type=float, default=None, help="Optional filter to keep only records near this center frequency")
    parser.add_argument("--center-frequency-tolerance-hz", type=float, default=1.0, help="Tolerance for target center frequency filter")
    parser.add_argument("--force-cpu", action="store_true")
    parser.add_argument("--allow-no-change-retrain", action="store_true", help="Retrain even if manifest has not changed")
    args = parser.parse_args()

    set_seed(args.seed)
    device = get_best_device(force_cpu=args.force_cpu)

    data_root = Path(args.data_root).resolve()
    model_root = Path(args.model_root).resolve()
    model_root.mkdir(parents=True, exist_ok=True)

    records = discover_records(data_root)
    if args.target_center_frequency_hz is not None:
        before = len(records)
        records = filter_records_by_center_frequency(
            records,
            target_center_frequency_hz=args.target_center_frequency_hz,
            tolerance_hz=args.center_frequency_tolerance_hz,
        )
        print("[INFO] Applied center frequency filter: target={}Hz tol={}Hz kept={}/{}".format(
            args.target_center_frequency_hz,
            args.center_frequency_tolerance_hz,
            len(records),
            before,
        ))
    validate_records(records)
    current_manifest_hash = manifest_hash(records)

    manifest_path = model_root / "dataset_manifest.json"
    split_path = model_root / "split_definition.json"
    best_model_path = model_root / "best_model.pt"
    history_path = model_root / "training_history.json"
    profiles_path = model_root / "enrollment_profiles.json"
    label_map_path = model_root / "label_map.json"
    train_config_path = model_root / "train_config.json"

    existing_manifest_hash = None
    if manifest_path.exists():
        old_manifest = load_json(manifest_path)
        existing_manifest_hash = old_manifest.get("manifest_hash")

    print("[INFO] Device: {}".format(device))
    print("[INFO] Records discovered: {}".format(len(records)))
    print("[INFO] Current manifest hash: {}".format(current_manifest_hash))

    if existing_manifest_hash == current_manifest_hash and best_model_path.exists() and not args.allow_no_change_retrain:
        print("[INFO] No dataset changes detected. Existing model is up to date.")
        print("[INFO] Model path: {}".format(best_model_path))
        return

    if split_path.exists():
        split = load_json(split_path)
    else:
        split = build_split(records, seed=args.seed, train_ratio=0.8)
        save_json(split_path, split)

    train_records = split_records(records, split, "train")
    test_records = split_records(records, split, "test")

    device_to_label, label_to_device = build_label_maps(records)

    print("[INFO] Devices: {}".format(len(device_to_label)))
    print("[INFO] Train captures: {}".format(len(train_records)))
    print("[INFO] Test captures: {}".format(len(test_records)))

    train_ds = CFileWindowDataset(
        records=train_records,
        device_to_label=device_to_label,
        window_size=args.window_size,
        stride=args.stride,
        max_windows_per_file=args.max_windows_per_file,
        max_complex_samples_per_file=args.max_complex_samples_per_file,
    )
    test_ds = CFileWindowDataset(
        records=test_records,
        device_to_label=device_to_label,
        window_size=args.window_size,
        stride=args.stride,
        max_windows_per_file=max(256, min(args.max_windows_per_file, 1000)),
        max_complex_samples_per_file=args.max_complex_samples_per_file,
    )

    train_loader = DataLoader(
        train_ds,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=0,
        pin_memory=torch.cuda.is_available(),
    )
    test_loader = DataLoader(
        test_ds,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=0,
        pin_memory=torch.cuda.is_available(),
    )

    model = build_model(num_classes=len(device_to_label), embedding_dim=args.embedding_dim).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)

    history = []
    best_acc = -1.0
    start_mode = "from_scratch"

    if best_model_path.exists():
        checkpoint = torch.load(best_model_path, map_location=device)
        load_checkpoint_flex(model, checkpoint, device_to_label)
        start_mode = "resumed_or_expanded"
        print("[INFO] Previous model found. Resuming and adapting classifier if needed.")

        if history_path.exists():
            try:
                history = load_json(history_path)
                if not isinstance(history, list):
                    history = []
            except Exception:
                history = []

    best_state = copy.deepcopy(model.state_dict())

    for epoch in range(1, args.epochs + 1):
        train_loss, train_acc = train_one_epoch(model, train_loader, optimizer, device)
        test_loss, test_acc = evaluate(model, test_loader, device)

        row = {
            "epoch": epoch,
            "train_loss": train_loss,
            "train_acc": train_acc,
            "test_loss": test_loss,
            "test_acc": test_acc,
            "mode": start_mode,
            "manifest_hash": current_manifest_hash,
        }
        history.append(row)

        print("[EPOCH {:03d}] train_loss={:.6f} train_acc={:.4f} test_loss={:.6f} test_acc={:.4f}".format(
            epoch, train_loss, train_acc, test_loss, test_acc
        ))

        if test_acc > best_acc:
            best_acc = test_acc
            best_state = copy.deepcopy(model.state_dict())

    model.load_state_dict(best_state)

    checkpoint = {
        "model_state_dict": model.state_dict(),
        "device_to_label": device_to_label,
        "label_to_device": label_to_device,
        "window_size": args.window_size,
        "stride": args.stride,
        "embedding_dim": args.embedding_dim,
        "manifest_hash": current_manifest_hash,
        "sample_rate_hz": records[0]["sample_rate_hz"],
        "center_frequency_hz": records[0]["center_frequency_hz"],
        "original_center_frequencies_hz": sorted({round(r["original_center_frequency_hz"], 3) for r in records}),
        "canonicalized": True,
        "canonical_center_hz": records[0]["canonical_center_hz"],
        "canonical_sample_rate_hz": records[0]["canonical_sample_rate_hz"],
        "canonical_bandwidth_hz": records[0]["canonical_bandwidth_hz"],
        "canonical_segment_length_samples": records[0]["canonical_segment_length_samples"],
        "preprocessing_profile_id": records[0]["preprocessing_profile_id"],
    }
    torch.save(checkpoint, best_model_path)

    profiles = build_enrollment_profiles(
        model=model,
        records=train_records,
        device_to_label=device_to_label,
        window_size=args.window_size,
        stride=args.stride,
        max_windows_per_file=max(512, min(args.max_windows_per_file, 1500)),
        max_complex_samples_per_file=args.max_complex_samples_per_file,
        device=device,
    )

    manifest_payload = {
        "manifest_hash": current_manifest_hash,
        "num_records": len(records),
        "records": records,
    }
    save_json(manifest_path, manifest_payload)
    save_json(history_path, history)
    save_json(profiles_path, profiles)
    save_json(label_map_path, {
        "device_to_label": device_to_label,
        "label_to_device": {str(k): v for k, v in label_to_device.items()}
    })
    save_json(train_config_path, {
        "window_size": args.window_size,
        "stride": args.stride,
        "batch_size": args.batch_size,
        "epochs": args.epochs,
        "lr": args.lr,
        "embedding_dim": args.embedding_dim,
        "max_windows_per_file": args.max_windows_per_file,
        "max_complex_samples_per_file": args.max_complex_samples_per_file,
        "seed": args.seed,
        "start_mode": start_mode,
        "device_used": str(device),
        "sample_rate_hz": records[0]["sample_rate_hz"],
        "center_frequency_hz": records[0]["center_frequency_hz"],
        "original_center_frequencies_hz": sorted({round(r["original_center_frequency_hz"], 3) for r in records}),
        "canonicalized": True,
        "canonical_center_hz": records[0]["canonical_center_hz"],
        "canonical_sample_rate_hz": records[0]["canonical_sample_rate_hz"],
        "canonical_bandwidth_hz": records[0]["canonical_bandwidth_hz"],
        "canonical_segment_length_samples": records[0]["canonical_segment_length_samples"],
        "preprocessing_profile_id": records[0]["preprocessing_profile_id"],
    })

    print("[OK] Training complete")
    print("[OK] Best model: {}".format(best_model_path))
    print("[OK] Enrollment profiles: {}".format(profiles_path))
    print("[OK] Manifest: {}".format(manifest_path))
    print("[OK] Start mode: {}".format(start_mode))


if __name__ == "__main__":
    main()
