from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ResultRepository:
    def __init__(self, storage_root: Path) -> None:
        self.storage_root = storage_root

    def new_analysis_id(self, prefix: str = "rsu") -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        return f"{prefix}_{stamp}"

    def analysis_dir(self, analysis_id: str) -> Path:
        path = self.storage_root / "analyses" / analysis_id
        path.mkdir(parents=True, exist_ok=True)
        (path / "regions").mkdir(exist_ok=True)
        (path / "features").mkdir(exist_ok=True)
        return path

    def write_json(self, analysis_dir: Path, relative_path: str, data: Any) -> Path:
        path = analysis_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, ensure_ascii=False)
        return path

    def read_result(self, analysis_id: str) -> dict[str, Any]:
        path = self.storage_root / "analyses" / analysis_id / "results.json"
        if not path.exists():
            raise FileNotFoundError(f"Analysis result not found: {analysis_id}")
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
