"""Fase 4: CNN1D over raw I/Q [2,N] and CNN2D over a numeric spectrogram
[1,H,W] -- never a pre-rendered PNG, per design. Both use adaptive pooling so
a fixed-size fully-connected head works regardless of the exact window
length / spectrogram frame count a given representation profile produces.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

SUPPORTED_CNN_MODEL_TYPES = ("cnn1d", "cnn2d")


class CNN1D(nn.Module):
    def __init__(self, num_classes: int) -> None:
        super().__init__()
        self.conv1 = nn.Conv1d(2, 16, kernel_size=7, padding=3)
        self.conv2 = nn.Conv1d(16, 32, kernel_size=5, padding=2)
        self.pool = nn.AdaptiveAvgPool1d(1)
        self.fc = nn.Linear(32, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = torch.relu(self.conv1(x))
        x = torch.max_pool1d(x, 2)
        x = torch.relu(self.conv2(x))
        x = self.pool(x).squeeze(-1)
        return self.fc(x)


class CNN2D(nn.Module):
    def __init__(self, num_classes: int) -> None:
        super().__init__()
        self.conv1 = nn.Conv2d(1, 8, kernel_size=3, padding=1)
        self.conv2 = nn.Conv2d(8, 16, kernel_size=3, padding=1)
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.fc = nn.Linear(16, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = torch.relu(self.conv1(x))
        x = torch.max_pool2d(x, 2)
        x = torch.relu(self.conv2(x))
        x = self.pool(x).view(x.size(0), -1)
        return self.fc(x)


class CnnTrainer:
    def build(self, model_type: str, num_classes: int) -> nn.Module:
        if model_type == "cnn1d":
            return CNN1D(num_classes)
        if model_type == "cnn2d":
            return CNN2D(num_classes)
        raise ValueError(f"UNSUPPORTED_CNN_MODEL_TYPE:{model_type}")

    def fit(
        self,
        model: nn.Module,
        X_train: np.ndarray,
        y_train_idx: np.ndarray,
        *,
        random_seed: int,
        epochs: int = 30,
        batch_size: int = 16,
        learning_rate: float = 1e-3,
    ) -> list[float]:
        torch.manual_seed(random_seed)
        dataset = TensorDataset(torch.from_numpy(X_train.astype(np.float32)), torch.from_numpy(y_train_idx.astype(np.int64)))
        loader = DataLoader(dataset, batch_size=batch_size, shuffle=True, generator=torch.Generator().manual_seed(random_seed))
        optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
        loss_fn = nn.CrossEntropyLoss()

        loss_history: list[float] = []
        model.train()
        for _ in range(epochs):
            epoch_loss = 0.0
            for batch_X, batch_y in loader:
                optimizer.zero_grad()
                logits = model(batch_X)
                loss = loss_fn(logits, batch_y)
                loss.backward()
                optimizer.step()
                epoch_loss += float(loss.item()) * len(batch_y)
            loss_history.append(epoch_loss / len(dataset))
        return loss_history

    def predict_proba(self, model: nn.Module, X: np.ndarray) -> np.ndarray:
        model.eval()
        with torch.no_grad():
            logits = model(torch.from_numpy(X.astype(np.float32)))
            return torch.softmax(logits, dim=1).numpy()
