from __future__ import annotations
import numpy as np
from pathlib import Path
from app.infrastructure.dsp.recorders.iq_recorder import IQRecorder
from app.infrastructure.dsp.recorders.audio_recorder import AudioRecorder

class RecordingPipeline:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.iq_recorder = IQRecorder(output_dir)
        self.audio_recorder = AudioRecorder(output_dir)
    
    def start_recording(self, filename: str) -> str:
        return self.iq_recorder.start_recording(filename)
    
    def write_iq(self, samples: np.ndarray) -> None:
        self.iq_recorder.write_samples(samples)
    
    def stop_recording(self) -> str:
        return self.iq_recorder.stop_recording()