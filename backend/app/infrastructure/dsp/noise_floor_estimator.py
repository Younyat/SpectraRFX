from __future__ import annotations
import numpy as np

class NoiseFloorEstimator:
    def __init__(self, percentile: float = 20.0):
        self.percentile = percentile
        self.estimated_floor = -100.0
    
    def estimate(self, spectrum_db: np.ndarray) -> float:
        if len(spectrum_db) == 0:
            return self.estimated_floor
        
        valid = spectrum_db[~np.isnan(spectrum_db) & ~np.isinf(spectrum_db)]
        if len(valid) == 0:
            return self.estimated_floor
        
        self.estimated_floor = np.percentile(valid, self.percentile)
        return self.estimated_floor
    
    def get_snr(self, peak_db: float) -> float:
        return peak_db - self.estimated_floor