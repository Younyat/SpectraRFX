from __future__ import annotations

from typing import Any

import numpy as np
from scipy import ndimage

from app.modules.rf_signal_understanding.domain.entities import TimeFrequencyRegion


class MorphologicalRegionDetector:
    def detect(
        self,
        waterfall_matrix: np.ndarray,
        time_axis_s: list[float],
        freq_axis_hz: list[float],
        threshold_percentile: float = 88.0,
        min_pixels: int = 16,
        max_regions: int = 32,
    ) -> list[dict[str, Any]]:
        matrix = np.asarray(waterfall_matrix, dtype=np.float32)
        if matrix.size == 0 or matrix.ndim != 2:
            return []
        low = float(np.percentile(matrix, 5))
        high = float(np.percentile(matrix, 99))
        normalized = (np.clip(matrix, low, high) - low) / max(high - low, 1e-9)
        threshold = float(np.percentile(normalized, threshold_percentile))
        mask = normalized >= threshold
        mask = ndimage.binary_closing(mask, structure=np.ones((3, 3), dtype=bool))
        labels, count = ndimage.label(mask)
        slices = ndimage.find_objects(labels)
        regions: list[dict[str, Any]] = []

        for index in range(count):
            region_slice = slices[index]
            if region_slice is None:
                continue
            time_slice, freq_slice = region_slice
            area = int(np.sum(labels[region_slice] == index + 1))
            if area < min_pixels:
                continue
            t0 = max(0, time_slice.start)
            t1 = min(matrix.shape[0] - 1, time_slice.stop - 1)
            f0 = max(0, freq_slice.start)
            f1 = min(matrix.shape[1] - 1, freq_slice.stop - 1)
            time_start = float(time_axis_s[t0]) if time_axis_s else 0.0
            time_end = float(time_axis_s[t1]) if time_axis_s else 0.0
            freq_start = float(freq_axis_hz[f0]) if freq_axis_hz else 0.0
            freq_end = float(freq_axis_hz[f1]) if freq_axis_hz else 0.0
            if freq_end < freq_start:
                freq_start, freq_end = freq_end, freq_start
            confidence = float(np.clip(np.mean(normalized[region_slice]) * min(area / 64.0, 1.0), 0.05, 0.95))
            region = TimeFrequencyRegion(
                bbox_id=f"box_{len(regions) + 1:03d}",
                time_start_s=time_start,
                time_end_s=max(time_end, time_start),
                freq_start_hz=freq_start,
                freq_end_hz=freq_end,
                center_frequency_hz=(freq_start + freq_end) / 2.0,
                occupied_bandwidth_hz=max(freq_end - freq_start, 0.0),
                detector="morphological",
                confidence=confidence,
                pixel_bounds={"time_start": t0, "time_end": t1, "freq_start": f0, "freq_end": f1},
            )
            regions.append(region.to_result())
        return sorted(regions, key=lambda item: item["confidence"], reverse=True)[:max_regions]
