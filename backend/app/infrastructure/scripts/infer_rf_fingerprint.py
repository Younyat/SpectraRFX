#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from typing import Dict, List

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset


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


class InferenceWindowDataset(Dataset):
    def __init__(self, iq_data: np.ndarray, window_size: int, stride: int):
        self.iq_data = iq_data
        self.window_size = window_size
        self.starts = segment_indices(len(iq_data), window_size, stride)
        if not self.starts:
            raise RuntimeError("No inference windows generated")

    def __len__(self):
        return len(self.starts)

    def __getitem__(self, idx):
        st = self.starts[idx]
        iq = self.iq_data[st:st + self.window_size]
        iq = normalize_window(iq)
        x = np.stack([iq.real, iq.imag], axis=0).astype(np.float32)
        return torch.from_numpy(x)


def shannon_entropy(probabilities: np.ndarray) -> float:
    p = np.clip(probabilities, 1e-12, 1.0)
    return float(-np.sum(p * np.log2(p)))


@torch.no_grad()
def main():
    parser = argparse.ArgumentParser(description="RF fingerprint prediction on a single capture")
    parser.add_argument("--cfile-path", required=True, help="Path to .cfile")
    parser.add_argument("--model-dir", required=True, help="Directory with best_model.pt and enrollment_profiles.json")
    parser.add_argument("--metadata-path", default="", help="Optional metadata json to enrich report")
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--output-json", default="prediction_report.json")
    args = parser.parse_args()

    cfile_path = Path(args.cfile_path)
    if not cfile_path.exists():
        raise RuntimeError(f"CFILE not found: {cfile_path}")

    model_dir = Path(args.model_dir)
    ckpt = torch.load(model_dir / "best_model.pt", map_location="cpu")
    profiles = load_json(model_dir / "enrollment_profiles.json")

    device_to_label: Dict[str, int] = ckpt["device_to_label"]
    label_to_device: Dict[str, str] = ckpt["label_to_device"]
    window_size = int(ckpt["window_size"])
    stride = int(ckpt["stride"])
    embedding_dim = int(ckpt["embedding_dim"])

    iq = load_cfile(str(cfile_path))
    dataset = InferenceWindowDataset(iq_data=iq, window_size=window_size, stride=stride)
    loader = DataLoader(dataset, batch_size=args.batch_size, shuffle=False, num_workers=0)

    model = RFClassifier(num_classes=len(device_to_label), embedding_dim=embedding_dim)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()

    profile_centroids = {dev_id: np.asarray(p["centroid"], dtype=np.float32) for dev_id, p in profiles.items()}
    profile_thresholds = {dev_id: float(p["accept_threshold"]) for dev_id, p in profiles.items()}

    vote_distribution: Dict[str, int] = {}
    probabilities_accum = []
    embeddings = []

    def label_to_device_name(idx: int) -> str:
        if idx in label_to_device:
            return str(label_to_device[idx])
        return str(label_to_device.get(str(idx), f"label_{idx}"))

    for x in loader:
        logits, z = model(x)
        probs = torch.softmax(logits, dim=1).numpy()
        preds = torch.argmax(logits, dim=1).numpy()
        embeddings.extend(z.numpy().tolist())
        probabilities_accum.append(probs)

        for pred in preds:
            dev = label_to_device_name(int(pred))
            vote_distribution[dev] = vote_distribution.get(dev, 0) + 1

    all_probs = np.concatenate(probabilities_accum, axis=0)
    mean_probs = all_probs.mean(axis=0)
    pred_label = int(np.argmax(mean_probs))
    predicted_device = label_to_device_name(pred_label)
    predicted_probability_mean = float(mean_probs[pred_label])
    probability_entropy = shannon_entropy(mean_probs)
    probability_peak_to_second = float(
        np.sort(mean_probs)[-1] - (np.sort(mean_probs)[-2] if mean_probs.shape[0] > 1 else 0.0)
    )

    emb = np.asarray(embeddings, dtype=np.float32)
    emb_mean = emb.mean(axis=0)
    emb_mean = emb_mean / (np.linalg.norm(emb_mean) + 1e-12)

    distances_all = {dev_id: float(np.linalg.norm(emb_mean - c)) for dev_id, c in profile_centroids.items()}
    nearest_device = min(distances_all.items(), key=lambda kv: kv[1])[0]
    nearest_distance = float(distances_all[nearest_device])
    nearest_threshold = float(profile_thresholds.get(nearest_device, 0.0))
    is_known = bool(nearest_distance <= nearest_threshold) if nearest_threshold > 0 else False

    predicted_threshold = float(profile_thresholds.get(predicted_device, 0.0))
    distance_to_predicted_profile = float(distances_all.get(predicted_device, nearest_distance))
    is_verified_prediction = bool(distance_to_predicted_profile <= predicted_threshold) if predicted_threshold > 0 else False

    sorted_distances = sorted(distances_all.items(), key=lambda kv: kv[1])
    margin = 0.0
    if len(sorted_distances) > 1:
        margin = float(sorted_distances[1][1] - sorted_distances[0][1])

    metadata = {}
    true_device = ""
    if args.metadata_path:
        meta_path = Path(args.metadata_path)
        if meta_path.exists():
            metadata = load_json(meta_path)
            true_device = str(metadata.get("emitter_device_id", "")).strip()

    report = {
        "input": {
            "cfile_path": str(cfile_path.resolve()),
            "metadata_path": str(Path(args.metadata_path).resolve()) if args.metadata_path else "",
            "num_iq_samples": int(len(iq)),
            "window_size": window_size,
            "stride": stride,
            "num_windows": int(len(dataset)),
        },
        "prediction": {
            "predicted_device": predicted_device,
            "nearest_profile_device": nearest_device,
            "is_known": is_known,
            "is_verified_prediction": is_verified_prediction,
            "predicted_probability_mean": predicted_probability_mean,
            "probability_entropy": probability_entropy,
            "probability_peak_to_second": probability_peak_to_second,
            "distance_to_predicted_profile": distance_to_predicted_profile,
            "predicted_threshold": predicted_threshold,
            "nearest_profile_distance": nearest_distance,
            "nearest_profile_threshold": nearest_threshold,
            "distance_margin_to_second_profile": margin,
            "vote_distribution": vote_distribution,
            "class_probability_mean": {
                label_to_device_name(i): float(mean_probs[i]) for i in range(len(mean_probs))
            },
            "all_profile_distances": distances_all,
        },
        "scientific_interpretation": {
            "prediction_confidence_level": (
                "high" if predicted_probability_mean >= 0.9 and margin >= 0.05 else
                "medium" if predicted_probability_mean >= 0.7 else
                "low"
            ),
            "risk_flags": [
                flag
                for flag in [
                    "low_confidence_probability" if predicted_probability_mean < 0.6 else "",
                    "high_entropy_distribution" if probability_entropy > 1.2 else "",
                    "small_distance_margin" if margin < 0.02 else "",
                    "outside_nearest_threshold" if not is_known else "",
                ]
                if flag
            ],
        },
        "ground_truth_comparison": {
            "has_ground_truth": bool(true_device),
            "true_device": true_device,
            "closed_set_match": bool(true_device and predicted_device == true_device),
            "nearest_profile_match": bool(true_device and nearest_device == true_device),
        },
        "metadata": metadata,
    }

    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    save_json(output_path, report)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
