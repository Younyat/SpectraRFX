"""Export the preserved native-BLE registry as a reproducible inventory."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.infrastructure.ble.native import BleNativeJobManager


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    inventory = BleNativeJobManager(args.registry_root).inventory()
    inventory["generated_at_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    inventory["scan_duration_seconds"] = 30
    inventory["adapter_backend"] = "winrt"
    inventory["device_count"] = len(inventory["devices"])
    inventory["interpretation_policy"] = "Unknown manufacturer/service payloads remain raw and are never converted into sensor measurements."
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
