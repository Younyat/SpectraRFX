from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from .ble_capture_metadata import sha256_file


FORMAT_BYTES = {"cf32_le": 8, "ci16_le": 4, "ci8": 2}


def diagnostic_profiles() -> dict[str, Any]:
    return {
        "schema_version": "ble-rf-diagnostic-profile-v1",
        "profiles": [
            {
                "diagnostic_profile_id": "RFVIS-CH37-RX2-4M8M-BW4M-GAIN-SWEEP-v1",
                "execution_purpose": "RF_VISIBILITY_DIAGNOSTIC",
                "scientific_campaign_member": False,
                "dataset_eligible": False,
                "qualification_only": True,
                "does_not_replace_qualification": True,
                "requires_requalification_for_campaign_use": True,
                "center_frequency_hz": 2402000000,
                "antenna": "RX2",
                "sample_rate_sps": [4000000, 8000000],
                "bandwidth_hz": 4000000,
                "sample_format": "cf32_le",
                "gain_db": [10, 20, 30, 40],
                "duration_seconds": 10,
                "disk_persistence_enabled": True,
                "windows_ble_scan_enabled": True,
                "frontend_preview_enabled": False,
                "online_decoder_enabled": False,
                "online_correlation_enabled": False,
                "dataset_policy": "never_dataset_never_training",
                "decision_policy": (
                    "If energy exists but burst candidates remain zero, fix detector by replay. "
                    "If energy is absent, inspect antenna, RX port, tuning, gain, driver, and sample flow."
                ),
            }
        ],
    }


class BleRfDiagnosticService:
    def analyze(self, capture_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
        capture_id = str(manifest["capture_id"])
        sample_format = str(manifest.get("sample_format") or manifest.get("file_format") or "cf32_le")
        if sample_format not in FORMAT_BYTES:
            raise ValueError("UNSUPPORTED_RF_DIAGNOSTIC_SAMPLE_FORMAT")
        data_path = capture_dir / manifest["data_path"]
        meta_path = capture_dir / manifest["metadata_path"]
        if not data_path.is_file() or not meta_path.is_file():
            raise FileNotFoundError(capture_id)

        sample_rate = int(manifest["sample_rate_sps"])
        center = int(manifest["center_frequency_hz"])
        bytes_per_sample = FORMAT_BYTES[sample_format]
        actual_bytes = data_path.stat().st_size
        actual_samples = actual_bytes // bytes_per_sample
        expected_bytes = int(manifest.get("expected_file_size_bytes") or manifest.get("expected_size_bytes") or 0)
        expected_samples = int(manifest.get("expected_samples") or int(float(manifest.get("requested_duration_seconds") or 0) * sample_rate))
        data_sha = sha256_file(data_path)
        meta_sha = sha256_file(meta_path)
        integrity = {
            "data_sha256": data_sha,
            "metadata_sha256": meta_sha,
            "data_hash_status": "VERIFIED" if data_sha == manifest.get("data_sha256") else "MISMATCH",
            "metadata_hash_status": "VERIFIED" if meta_sha == manifest.get("metadata_sha256") else "MISMATCH",
            "size_status": "PASSED" if not expected_bytes or actual_bytes == expected_bytes else "FAILED",
            "sample_status": "PASSED" if not expected_samples or actual_samples == expected_samples else "FAILED",
        }

        values = self._load_values(data_path, sample_format)
        power_block_samples = max(64, int(sample_rate / 100_000))
        powers, max_amplitudes, clipping_samples, total_seen = self._block_statistics(values, power_block_samples, sample_format)
        if powers.size == 0:
            raise ValueError("RF_DIAGNOSTIC_EMPTY_CAPTURE")
        mean_power = float(np.mean(powers))
        median_power = float(np.median(powers))
        noise_floor = median_power
        mad = float(np.median(np.abs(powers - median_power)))
        threshold = max(noise_floor * 4.0, noise_floor + 8.0 * mad, 1e-12)
        active = np.flatnonzero(powers > threshold)
        groups = np.split(active, np.where(np.diff(active) > 2)[0] + 1) if active.size else []
        candidates = self._candidate_preview(groups, powers, threshold, power_block_samples, actual_samples, sample_rate)

        psd = self._psd(values, center, sample_rate)
        energy = self._energy_series(powers, power_block_samples, sample_rate, max_points=1200)
        max_power = float(np.max(powers))
        max_amp = float(np.max(max_amplitudes)) if max_amplitudes.size else 0.0
        clipping_ratio = float(clipping_samples / max(total_seen, 1))
        energy_exists = bool(active.size)
        burst_candidates_exist = bool(candidates["candidate_count"])
        layer = "DETECTION_REPLAY_REQUIRED" if energy_exists and not burst_candidates_exist else "RF_VISIBILITY_REVIEW_REQUIRED" if not energy_exists else "CANDIDATES_AVAILABLE_FOR_DECODER_REPLAY"

        return {
            "schema_version": "ble-rf-diagnostic-v1",
            "capture_id": capture_id,
            "execution_purpose": "RF_RECEPTION_VS_DETECTION_DIAGNOSTIC",
            "scientific_campaign_member": False,
            "dataset_eligible": False,
            "qualification_only": True,
            "does_not_replace_qualification": True,
            "source_capture_preserved": True,
            "capture": {
                "center_frequency_hz": center,
                "sample_rate_sps": sample_rate,
                "bandwidth_hz": manifest.get("bandwidth_hz"),
                "sample_format": sample_format,
                "antenna": manifest.get("antenna"),
                "gain_db": (manifest.get("gain_configuration") or {}).get("gain_db"),
                "actual_samples": actual_samples,
                "actual_file_size_bytes": actual_bytes,
                "expected_samples": expected_samples,
                "expected_file_size_bytes": expected_bytes,
            },
            "integrity": integrity,
            "power": {
                "mean_power_linear": mean_power,
                "mean_power_dbfs": self._db(mean_power),
                "median_power_linear": median_power,
                "noise_floor_linear": noise_floor,
                "noise_floor_dbfs": self._db(noise_floor),
                "maximum_block_power_linear": max_power,
                "maximum_block_power_dbfs": self._db(max_power),
                "maximum_amplitude": max_amp,
            },
            "clipping": {
                "threshold_amplitude": 0.98,
                "clipped_samples": int(clipping_samples),
                "total_samples_checked": int(total_seen),
                "clipping_ratio": clipping_ratio,
                "clipping_percent": clipping_ratio * 100.0,
                "status": "PASSED" if clipping_ratio == 0.0 else "REVIEW",
            },
            "burst_detection_replay": {
                "algorithm": "same_energy_gate_as_ble_sdr_capture_worker",
                "block_samples": power_block_samples,
                "noise_power_dbfs": self._db(noise_floor),
                "mad_power_linear": mad,
                "threshold_linear": threshold,
                "threshold_dbfs": self._db(threshold),
                "active_blocks": int(active.size),
                "energy_excursion_count": int(len(groups)),
                "candidate_count": candidates["candidate_count"],
                "candidate_preview": candidates["preview"],
            },
            "psd": psd,
            "energy_time_series": energy,
            "diagnostic_conclusion": {
                "energy_observed": energy_exists,
                "burst_candidates_before_decoder": burst_candidates_exist,
                "layer": layer,
                "recommended_next_action": (
                    "Run offline detector/decoder replay on the preserved I/Q before repeating hardware."
                    if energy_exists
                    else "Inspect antenna, RX2 port, tuning, gain, UHD/driver, and sample flow before repeating S001-POS."
                ),
            },
        }

    def _load_values(self, path: Path, sample_format: str) -> np.ndarray:
        dtype = {"cf32_le": "<c8", "ci16_le": "<i2", "ci8": "i1"}[sample_format]
        raw = np.memmap(path, dtype=dtype, mode="r")
        if sample_format == "cf32_le":
            return raw
        scale = 32768.0 if sample_format == "ci16_le" else 128.0
        return (raw[0::2].astype(np.float32) + 1j * raw[1::2].astype(np.float32)) / scale

    def _block_statistics(self, values: np.ndarray, block: int, sample_format: str) -> tuple[np.ndarray, np.ndarray, int, int]:
        powers: list[np.ndarray] = []
        maxamps: list[np.ndarray] = []
        clipped = 0
        total = 0
        blocks_per_chunk = 8192
        chunk = block * blocks_per_chunk
        for start in range(0, len(values) - block + 1, chunk):
            stop = min(len(values), start + chunk)
            usable = ((stop - start) // block) * block
            if usable <= 0:
                continue
            data = np.asarray(values[start:start + usable]).reshape(-1, block)
            amp = np.abs(data)
            pwr = amp * amp
            powers.append(np.mean(pwr, axis=1))
            maxamps.append(np.max(amp, axis=1))
            clipped += int(np.count_nonzero(amp >= 0.98))
            total += int(amp.size)
        return np.concatenate(powers), np.concatenate(maxamps), clipped, total

    def _candidate_preview(self, groups: list[np.ndarray], powers: np.ndarray, threshold: float, block: int, total_samples: int, sample_rate: int) -> dict[str, Any]:
        preview = []
        for index, group in enumerate(groups, 1):
            if not len(group):
                continue
            start = max(0, (int(group[0]) - 2) * block)
            end = min(total_samples, (int(group[-1]) + 3) * block)
            if len(preview) < 50:
                preview.append({
                    "candidate_id": f"rfdiag-burst-{index:06d}",
                    "sample_start": int(start),
                    "sample_end": int(end),
                    "sample_count": int(end - start),
                    "time_start_seconds": start / sample_rate,
                    "duration_seconds": (end - start) / sample_rate,
                    "power_dbfs": self._db(float(np.max(powers[group]))),
                    "threshold_dbfs": self._db(threshold),
                })
        return {"candidate_count": int(sum(1 for group in groups if len(group))), "preview": preview}

    def _psd(self, values: np.ndarray, center: int, sample_rate: int) -> dict[str, Any]:
        fft_size = 4096
        windows = min(96, max(1, len(values) // fft_size))
        starts = np.linspace(0, max(0, len(values) - fft_size), windows, dtype=np.int64)
        taper = np.hanning(fft_size).astype(np.float32)
        acc = np.zeros(fft_size, dtype=np.float64)
        for start in starts:
            frame = np.asarray(values[int(start):int(start) + fft_size])
            if frame.size < fft_size:
                continue
            spec = np.fft.fftshift(np.fft.fft(frame * taper))
            acc += np.abs(spec) ** 2 / fft_size
        acc /= max(1, len(starts))
        freqs = center + np.fft.fftshift(np.fft.fftfreq(fft_size, d=1.0 / sample_rate))
        target_bins = 257
        stride = max(1, fft_size // target_bins)
        points = [{"frequency_hz": int(freqs[i]), "psd_dbfs": self._db(float(acc[i]))} for i in range(0, fft_size, stride)][:target_bins]
        peak_index = int(np.argmax(acc))
        return {
            "center_frequency_hz": center,
            "sample_rate_sps": sample_rate,
            "fft_size": fft_size,
            "averaged_windows": int(len(starts)),
            "peak_frequency_hz": int(freqs[peak_index]),
            "peak_psd_dbfs": self._db(float(acc[peak_index])),
            "points": points,
        }

    def _energy_series(self, powers: np.ndarray, block: int, sample_rate: int, max_points: int) -> list[dict[str, float]]:
        if powers.size <= max_points:
            reduced = powers
            factor = 1
        else:
            factor = int(np.ceil(powers.size / max_points))
            usable = (powers.size // factor) * factor
            reduced = np.max(powers[:usable].reshape(-1, factor), axis=1)
        return [{"time_seconds": float(i * factor * block / sample_rate), "power_dbfs": self._db(float(value))} for i, value in enumerate(reduced)]

    @staticmethod
    def _db(value: float) -> float:
        return float(10.0 * np.log10(max(float(value), 1e-20)))
