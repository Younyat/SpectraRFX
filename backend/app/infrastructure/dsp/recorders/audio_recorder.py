from __future__ import annotations
import logging
from pathlib import Path
import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

class AudioRecorder:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.file = None
        self.filepath = None
    
    def start_recording(self, filename: str, sample_rate: int = 48000) -> str:
        self.filepath = self.output_dir / filename
        self.sample_rate = sample_rate
        try:
            logger.info(f"Audio recording started: {self.filepath}")
            return str(self.filepath)
        except Exception as e:
            logger.error(f"Failed to start audio recording: {e}")
            return ""
    
    def write_samples(self, samples: np.ndarray) -> None:
        if self.filepath is None:
            return
        try:
            sf.write(str(self.filepath), samples, self.sample_rate, subtype='PCM_16')
        except Exception as e:
            logger.error(f"Error writing audio samples: {e}")
    
    def stop_recording(self) -> str:
        if self.filepath is None:
            return ""
        logger.info(f"Audio recording stopped: {self.filepath}")
        return str(self.filepath)