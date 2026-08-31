from __future__ import annotations
import json
from pathlib import Path
from typing import Dict, Any

class MetadataWriter:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
    
    def write_metadata(self, filename: str, metadata: Dict[str, Any]) -> None:
        metadata_path = self.output_dir / f"{Path(filename).stem}.json"
        try:
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=2)
        except Exception as e:
            print(f"Error writing metadata: {e}")