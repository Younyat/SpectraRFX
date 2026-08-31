from __future__ import annotations
import logging
from pathlib import Path
import numpy as np

logger = logging.getLogger(__name__)

class IQRecorder:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.file = None
        self.filepath = None
    
    def start_recording(self, filename: str) -> str:
        self.filepath = self.output_dir / filename
        try:
            self.file = open(self.filepath, "wb")
            logger.info(f"IQ recording started: {self.filepath}")
            return str(self.filepath)
        except Exception as e:
            logger.error(f"Failed to start IQ recording: {e}")
            return ""
    
    def write_samples(self, samples: np.ndarray) -> None:
        if self.file is None:
            return
        try:
            data = samples.astype(np.complex64).tobytes()
            self.file.write(data)
        except Exception as e:
            logger.error(f"Error writing IQ samples: {e}")
    
    def stop_recording(self) -> str:
        if self.file is None:
            return ""
        try:
            self.file.close()
            logger.info(f"IQ recording stopped: {self.filepath}")
            return str(self.filepath)
        except Exception as e:
            logger.error(f"Error stopping IQ recording: {e}")
            return ""
        finally:
            self.file = None