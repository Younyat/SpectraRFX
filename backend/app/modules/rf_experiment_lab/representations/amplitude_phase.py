from __future__ import annotations

import numpy as np


def amplitude_phase(iq: np.ndarray) -> dict[str, np.ndarray]:
    values = np.asarray(iq, dtype=np.complex64)
    return {"amplitude": np.abs(values).astype(np.float32), "phase": np.angle(values).astype(np.float32)}
