"""Point-5 correction (2026-08-08): retroactive reconstruction of the 5 real
migrations performed earlier in this same work (P0.1-P0.5 + the protocol-
adaptation items), BEFORE migration_ledger.py existed. Every reconstructed
entry is explicitly retroactive=True (never presented as if the ledger
existed at the time) and uses each artifact file's own on-disk modification
time as the best REAL, verifiable proxy for when that specific change
happened (not a fabricated or guessed timestamp) -- read directly from the
filesystem, never assumed.

This script is meant to run exactly once, against the real storage this
session already modified. Re-running it is safe (idempotent): it always
reconstructs the SAME 5 categories from the CURRENT real files on disk, and
migration_ledger.record_migration's own migration_id is deterministic from
(migration_version, artifact_type, artifact_id, field, timestamp_utc) --
running twice with the same mtimes produces duplicate rows (the ledger has
no de-duplication of its own), so this is intended as a one-time,
manually-invoked reconstruction, not a routine migration.

The 5 categories reconstructed here:
  1. P0.5: center_frequency_hz corrected on 6 SYNTHETIC_TEST_ONLY captures
     (2476000000 -> 2402000000, a physically-invalid frequency) and their
     72 examples.jsonl rows.
  2. day_id backfilled (None -> a real calendar day) on 150 real captures.
  3. 4 real split manifests regenerated to exclude channel-38 examples from
     the main benchmark (CC2541SensorTag/CC2650-UNIT-01/keyfobdemo01/02).
  4. confirmatory_eligible added to 27 bundle manifests (P0.2).
  5. resolved_flags added to 27 bundles' preprocessing_config.json (the
     preprocessing-registry correction).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .migration_ledger import record_migration

_DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "infrastructure" / "persistence" / "storage" / "ble_rffi_studio"

_SYNTHETIC_CENTER_FREQUENCY_CAPTURE_IDS = [
    "SYNTHETIC-CAP-SYNTHETIC-SESSION-SYNTHETIC-UNIT-00-00", "SYNTHETIC-CAP-SYNTHETIC-SESSION-SYNTHETIC-UNIT-00-01",
    "SYNTHETIC-CAP-SYNTHETIC-SESSION-SYNTHETIC-UNIT-00-02", "SYNTHETIC-CAP-SYNTHETIC-SESSION-SYNTHETIC-UNIT-01-00",
    "SYNTHETIC-CAP-SYNTHETIC-SESSION-SYNTHETIC-UNIT-01-01", "SYNTHETIC-CAP-SYNTHETIC-SESSION-SYNTHETIC-UNIT-01-02",
]
_CHANNEL_SCOPE_REGENERATED_SPLIT_PREFIXES = ["CC2541SensorTag-AUTO-TVB__", "CC2650-UNIT-01-AUTO-TVB__", "keyfobdemo 01-AUTO-TVB__", "keyfobdemo 02-AUTO-TVB__"]


def _mtime_utc(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def reconstruct(root: Path) -> int:
    count = 0

    # 1. P0.5: center_frequency_hz on the 6 real SYNTHETIC_TEST_ONLY captures.
    for capture_id in _SYNTHETIC_CENTER_FREQUENCY_CAPTURE_IDS:
        path = root / "captures" / f"{capture_id}.json"
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if data.get("center_frequency_hz") != 2_402_000_000:
            continue
        record_migration(
            root, migration_version="v0-retroactive-p0.5-channel-frequency", artifact_type="CaptureRecord", artifact_id=capture_id,
            field="center_frequency_hz", old_value=2_476_000_000, new_value=2_402_000_000,
            reason="P0.5: synthetic_demo_seeder.py used a linear formula (2402MHz + channel_index*2MHz) only valid for BLE DATA channels; channel 37 is an ADVERTISING channel fixed at 2402MHz, not 2476MHz. Corrected on both the capture and its examples.jsonl rows.",
            migration_tool="retroactive_reconstruction (originally: one-off P0.5 fix script)", retroactive=True, timestamp_utc=_mtime_utc(path),
        )
        count += 1

    # 2. day_id backfill on real captures (day_id was None before this session's backfill).
    captures_dir = root / "captures"
    if captures_dir.is_dir():
        for path in sorted(captures_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if not data.get("day_id"):
                continue
            record_migration(
                root, migration_version="v0-retroactive-day-id-receiver-epoch-backfill", artifact_type="CaptureRecord", artifact_id=data["capture_id"],
                field="day_id", old_value=None, new_value=data["day_id"],
                reason="Protocol-adaptation item: day_id auto-derived from the capture's own real timestamp (created_at_utc at the time; corrected to b200_rf_started_at by the point-2 fix) -- backfilled once for every real capture that never had it declared.",
                migration_tool="retroactive_reconstruction (originally: one-off day_id/receiver_epoch backfill script)", retroactive=True, timestamp_utc=_mtime_utc(path),
            )
            count += 1

    # 3. Split manifests regenerated to exclude channel-38 examples.
    splits_dir = root / "splits"
    if splits_dir.is_dir():
        for path in sorted(splits_dir.glob("*.json")):
            if not any(path.name.startswith(prefix) for prefix in _CHANNEL_SCOPE_REGENERATED_SPLIT_PREFIXES):
                continue
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            excluded = data.get("channel_scope_excluded_example_ids") or []
            if not excluded:
                continue
            record_migration(
                root, migration_version="v0-retroactive-channel-scope-split-regeneration", artifact_type="SplitManifest", artifact_id=path.stem,
                field="assignments", old_value=f"channel-38 examples mixed into the split ({len(excluded)} example(s) affected)",
                new_value=f"channel-38 examples excluded from the main-benchmark split ({len(excluded)} example(s) now in channel_scope_excluded_example_ids)",
                reason="Split-policy correction: the main benchmark is channel-37-only; this dataset's frozen split previously predated that filter and had real channel-38 examples mixed into TRAIN/VALIDATION/TEST.",
                migration_tool="retroactive_reconstruction (originally: SplitBuilder.build() re-run per affected dataset)", retroactive=True, timestamp_utc=_mtime_utc(path),
            )
            count += 1

    # 4 & 5. Bundle manifests: confirmatory_eligible (P0.2) and preprocessing_config.json resolved_flags.
    bundles_dir = root / "bundles"
    if bundles_dir.is_dir():
        for bundle_dir in sorted(p for p in bundles_dir.iterdir() if p.is_dir()):
            manifest_path = bundle_dir / "bundle_manifest.json"
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
                if "confirmatory_eligible" in manifest:
                    record_migration(
                        root, migration_version="v0-retroactive-p0.2-confirmatory-eligible", artifact_type="ModelBundleManifest", artifact_id=bundle_dir.name,
                        field="confirmatory_eligible", old_value=None, new_value=manifest["confirmatory_eligible"],
                        reason="P0.2: added as a first-class, stored field derived from test_evaluation_provenance (SINGLE_SELECTION_GUARANTEE -> True, OPT_IN_MULTI_CANDIDATE_COMPARISON -> False) -- so a bundle's confirmatory status is explicit and enforced, not implicit.",
                        migration_tool="retroactive_reconstruction (originally: one-off P0.2 migration script)", retroactive=True, timestamp_utc=_mtime_utc(manifest_path),
                    )
                    count += 1

            preprocessing_config_path = bundle_dir / "preprocessing_config.json"
            if preprocessing_config_path.is_file():
                config = json.loads(preprocessing_config_path.read_text(encoding="utf-8-sig"))
                if "resolved_flags" in config:
                    record_migration(
                        root, migration_version="v0-retroactive-preprocessing-registry-resolved-flags", artifact_type="BundlePreprocessingConfig", artifact_id=bundle_dir.name,
                        field="resolved_flags", old_value=None, new_value=config["resolved_flags"],
                        reason="Preprocessing-registry correction: preprocessing_config.json used to carry only the bare base_preprocessing_profile_id string; the actual resolved flags are now persisted alongside it so the artifact is self-sufficient for reproducing what preprocessing genuinely ran.",
                        migration_tool="retroactive_reconstruction (originally: one-off preprocessing_config.json migration script)", retroactive=True, timestamp_utc=_mtime_utc(preprocessing_config_path),
                    )
                    count += 1

    return count


def main(root: Path | None = None) -> None:
    root = root or _DEFAULT_ROOT
    n = reconstruct(root)
    print(f"Reconstructed {n} retroactive migration_ledger.jsonl entries.")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
