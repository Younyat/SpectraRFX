"""Generate bounded visualization data from a preserved CF32 SigMF recording.

This is visualization only: it performs no BLE synchronization or decoding.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest_path = args.capture_dir / "capture_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("sample_format") != "cf32_le":
        raise ValueError("VISUALIZATION_REQUIRES_CF32_LE")
    samples = np.memmap(args.capture_dir / manifest["data_path"], dtype="<c8", mode="r")
    if samples.size == 0:
        raise ValueError("EMPTY_CAPTURE")

    nfft, row_count = 1024, 64
    starts = np.linspace(0, max(0, samples.size - nfft), row_count, dtype=np.int64)
    window = np.hanning(nfft).astype(np.float32)
    waterfall, power = [], []
    for start in starts:
        frame = np.asarray(samples[start:start + nfft], dtype=np.complex64)
        spectrum = 20 * np.log10(np.maximum(np.abs(np.fft.fftshift(np.fft.fft(frame * window))) / nfft, 1e-12))
        waterfall.append(spectrum[::4].astype(float).tolist())
        power.append(float(10 * np.log10(max(float(np.mean(np.abs(frame) ** 2)), 1e-12))))
    preview = np.asarray(samples[::max(1, samples.size // 512)][:512], dtype=np.complex64)
    result = {
        "schema_version": "1.0",
        "capture_id": manifest["capture_id"],
        "source_data_sha256": manifest["data_sha256"],
        "visualization_only": True,
        "ble_decode_attempted": False,
        "spectrum": {"generated": True, "dbfs": waterfall[-1]},
        "waterfall": {"generated": True, "rows": waterfall},
        "power_timeline": {"generated": True, "average_power_dbfs": power},
        "iq_preview": {"generated": True, "i": preview.real.astype(float).tolist(), "q": preview.imag.astype(float).tolist()},
    }
    atomic_json(args.capture_dir / "visualization.json", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
