from __future__ import annotations

import numpy as np


def find_stf_candidates(iq: np.ndarray, absolute_offset: int = 0, threshold: float = 0.75, window: int = 64, minimum_plateau: int = 24) -> list[dict]:
    """Find L-STF periodicity candidates; this is evidence, not frame decoding."""
    if iq.size < window + 16:
        return []
    products = iq[:-16] * np.conj(iq[16:])
    energy = np.abs(iq[16:]) ** 2
    kernel = np.ones(window, dtype=np.float32)
    p = np.convolve(products, kernel, mode="valid")
    r = np.convolve(energy, kernel, mode="valid")
    metric = np.abs(p) ** 2 / (r ** 2 + 1e-20)
    mask = metric >= threshold
    edges = np.diff(np.pad(mask.astype(np.int8), (1, 1)))
    starts, stops = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    candidates = []
    for start, stop in zip(starts, stops):
        if stop - start < minimum_plateau:
            continue
        peak_at = start + int(np.argmax(metric[start:stop]))
        candidates.append({"sample_start": absolute_offset + int(start), "correlation_peak": float(metric[peak_at]), "plateau_length": int(stop - start), "threshold": threshold, "evidence_level": "preamble_candidate"})
    return candidates
