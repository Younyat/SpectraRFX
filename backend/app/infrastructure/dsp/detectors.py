from __future__ import annotations
import numpy as np

class PeakDetector:
    def __init__(self, threshold_db: float = -60.0):
        self.threshold = threshold_db
    
    def detect_peaks(self, spectrum_db: np.ndarray, min_separation: int = 10) -> np.ndarray:
        if len(spectrum_db) < min_separation:
            return np.array([])
        
        peaks = np.where(spectrum_db > self.threshold)[0]
        if len(peaks) == 0:
            return np.array([])
        
        filtered_peaks = [peaks[0]]
        for peak in peaks[1:]:
            if peak - filtered_peaks[-1] >= min_separation:
                filtered_peaks.append(peak)
        
        return np.array(filtered_peaks)

class MinMaxDetector:
    def __init__(self):
        self.max_trace = None
        self.min_trace = None
    
    def update(self, spectrum: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if self.max_trace is None:
            self.max_trace = spectrum.copy()
            self.min_trace = spectrum.copy()
        else:
            self.max_trace = np.maximum(self.max_trace, spectrum)
            self.min_trace = np.minimum(self.min_trace, spectrum)
        
        return self.max_trace, self.min_trace
    
    def reset(self) -> None:
        self.max_trace = None
        self.min_trace = None