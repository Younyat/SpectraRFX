#!/usr/bin/env python3
"""External P0 worker entry point. Fails closed until reference blocks exist."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import sys
from pathlib import Path

PINNED = {
    "gnuradio": {"version": "3.10.12.0", "commit": "522b220f24cbf0df9789a2d8eff57ee3d3f58f52"},
    "gr_ieee802_11": {"branch": "maint-3.10", "commit": "ad0598e4a874f4b8e1f391a1e0323e80df2b34ff"},
    "gr_foo": {"branch": "maint-3.10", "commit": "4c2a471b0453b9dca669b2d9dfcbfba6278741d7"},
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True); parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(); manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8")); output = Path(args.output_dir); output.mkdir(parents=True, exist_ok=True)
    actual = {}
    distributions = {"gnuradio": "gnuradio", "ieee802_11": "gnuradio-ieee802_11", "foo": "gnuradio-foo"}
    for package, distribution in distributions.items():
        try: actual[package] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError: actual[package] = None
    versions = {"pinned": PINNED, "detected": actual}
    (output / "software_versions.json").write_text(json.dumps(versions, indent=2), encoding="utf-8")
    errors = []
    if float(manifest.get("decoder_sample_rate_hz") or 0) != 20_000_000.0: errors.append("decoder_sample_rate_hz_must_equal_20000000")
    if actual["gnuradio"] != PINNED["gnuradio"]["version"]: errors.append("pinned_gnuradio_not_available")
    if actual["ieee802_11"] is None: errors.append("gr_ieee802_11_not_available")
    elif "g" + PINNED["gr_ieee802_11"]["commit"][:7] not in actual["ieee802_11"]: errors.append("pinned_gr_ieee802_11_commit_not_available")
    if actual["foo"] is None: errors.append("gr_foo_not_available")
    elif "g" + PINNED["gr_foo"]["commit"][:7] not in actual["foo"]: errors.append("pinned_gr_foo_commit_not_available")
    result = {"status": "worker_unavailable" if errors else "reference_decoder_adapter_not_configured", "errors": errors, "frames": [], "failed_candidates": [], "versions": versions}
    (output / "worker_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(output / "worker_result.json")}))
    return 78 if errors else 69


if __name__ == "__main__":
    sys.exit(main())
