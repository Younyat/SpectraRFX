"""One-time migration: rewrites existing CaptureRecord/ExampleRecord JSON on
disk from the old, too-coarse vocabulary to the new one --

    capture_purpose:      TARGET_DEVICE           -> TARGET_DEVICE_ON
                          BACKGROUND_ENVIRONMENT  -> BACKGROUND_TARGET_OFF
                                                      (if target_reference_id
                                                      was set) or
                                                      BACKGROUND_GENERAL
                                                      (otherwise)
    background_kind:      (new field) derived from the migrated capture_purpose
    dataset_eligibility:  PENDING_REVIEW -> PENDING_ANALYSIS
    target_presence_status: (new field) recomputed from the (now-migrated)
                             evidence via StudioRepository._capture_decision,
                             for every capture that already has evidence built

See the ble_rffi_studio module README's "TARGET_VS_BACKGROUND single-class
TRAIN bug" section for why this taxonomy changed. This exists because real
B200 campaign data was already on disk under the old vocabulary when the
contracts changed -- without this, StudioRepository would raise a pydantic
ValidationError reading any of it back (an old value is no longer a valid
CapturePurpose/DatasetEligibility literal).

Idempotent: safe to run more than once. Only rewrites a record whose
capture_purpose/dataset_eligibility is still one of the OLD literal values;
anything already migrated (or that never had the field set) is left
untouched.

Usage (from the backend/ directory, with a venv that has the module's deps):
    python -m app.modules.ble_rffi_studio.migrations.migrate_v2_capture_purpose_taxonomy [storage_root]

storage_root defaults to the real, running module's persisted storage
(app/infrastructure/persistence/storage/ble_rffi_studio).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_OLD_TO_NEW_PURPOSE = {
    "TARGET_DEVICE": "TARGET_DEVICE_ON",
}
_DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "infrastructure" / "persistence" / "storage" / "ble_rffi_studio"


def _migrate_capture_purpose(old_purpose: str, target_reference_id: str | None) -> tuple[str, str | None]:
    """Returns (new_capture_purpose, background_kind)."""
    if old_purpose == "TARGET_DEVICE":
        return "TARGET_DEVICE_ON", None
    if old_purpose == "BACKGROUND_ENVIRONMENT":
        if target_reference_id:
            return "BACKGROUND_TARGET_OFF", "TARGET_DECLARED_OFF_OR_REMOVED"
        return "BACKGROUND_GENERAL", "GENERAL_AMBIENT"
    raise ValueError(f"NOT_AN_OLD_CAPTURE_PURPOSE:{old_purpose}")


def migrate_captures(root: Path) -> list[str]:
    """Rewrites captures/*.json in place. Returns the migrated capture_ids."""
    changed: list[str] = []
    captures_dir = root / "captures"
    if not captures_dir.is_dir():
        return changed
    for path in sorted(captures_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        old_purpose = data.get("capture_purpose")
        if old_purpose not in ("TARGET_DEVICE", "BACKGROUND_ENVIRONMENT"):
            continue
        new_purpose, background_kind = _migrate_capture_purpose(old_purpose, data.get("target_reference_id"))
        data["capture_purpose"] = new_purpose
        data["background_kind"] = background_kind
        if new_purpose == "BACKGROUND_GENERAL":
            # No specific target in question at all -- never a fabricated
            # POWERED_ON/OFF value for a unit that was never really named.
            data["target_state"] = None
        data.setdefault("target_presence_status", None)
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        changed.append(path.stem)
    return changed


def migrate_examples(root: Path) -> list[str]:
    """Rewrites evidence/*/examples.jsonl in place. Returns the touched
    capture_ids (the evidence directory names)."""
    changed: list[str] = []
    evidence_dir = root / "evidence"
    captures_dir = root / "captures"
    if not evidence_dir.is_dir():
        return changed
    for examples_path in sorted(evidence_dir.glob("*/examples.jsonl")):
        raw_lines = [line for line in examples_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not raw_lines:
            continue
        new_lines: list[str] = []
        touched = False
        for line in raw_lines:
            row = json.loads(line)
            if row.get("dataset_eligibility") == "PENDING_REVIEW":
                row["dataset_eligibility"] = "PENDING_ANALYSIS"
                touched = True
            old_purpose = row.get("capture_purpose")
            if old_purpose in ("TARGET_DEVICE", "BACKGROUND_ENVIRONMENT"):
                # Examples don't carry target_reference_id themselves --
                # resolve it via the (already-migrated) owning CaptureRecord.
                capture_path = captures_dir / f"{row['capture_id']}.json"
                target_reference_id = None
                if capture_path.is_file():
                    target_reference_id = json.loads(capture_path.read_text(encoding="utf-8")).get("target_reference_id")
                new_purpose, background_kind = _migrate_capture_purpose(old_purpose, target_reference_id)
                row["capture_purpose"] = new_purpose
                row["background_kind"] = background_kind
                touched = True
            elif "background_kind" not in row:
                row["background_kind"] = None
                touched = True
            new_lines.append(json.dumps(row, sort_keys=True))
        if touched:
            examples_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
            changed.append(examples_path.parent.name)
    return changed


def recompute_target_presence_status(root: Path) -> list[str]:
    """For every capture that already has evidence, recomputes and persists
    target_presence_status using the real StudioRepository decision logic --
    must run AFTER migrate_captures/migrate_examples, since it reads the
    already-migrated capture_purpose/dataset_eligibility values."""
    # Imported lazily: this migration module must remain importable (for its
    # pure functions above, used by tests) even in an environment missing
    # this module's full dependency set (torch/scikit-learn) that
    # StudioRepository pulls in transitively.
    from app.modules.ble_rffi_studio.api import StudioRepository

    repository = StudioRepository(root, legacy_capture_root=root / "_migration_unused_legacy_captures", legacy_session_root=root / "_migration_unused_legacy_sessions")
    changed: list[str] = []
    for capture in repository.list_captures():
        if not repository.has_evidence(capture.capture_id):
            continue
        _, target_presence_status = repository._capture_decision(capture)  # noqa: SLF001 -- migration reuses the real decision logic on purpose, never reimplements it
        if capture.target_presence_status == target_presence_status:
            continue
        updated = capture.model_copy(update={"target_presence_status": target_presence_status})
        (repository.captures_dir / f"{capture.capture_id}.json").write_text(
            json.dumps(updated.model_dump(mode="json"), indent=2, sort_keys=True), encoding="utf-8",
        )
        changed.append(capture.capture_id)
    return changed


def main(root: Path | None = None) -> None:
    root = root or _DEFAULT_ROOT
    changed_captures = migrate_captures(root)
    changed_examples = migrate_examples(root)
    changed_presence = recompute_target_presence_status(root)
    print(
        f"Migrated {len(changed_captures)} capture(s), {len(changed_examples)} evidence director(y/ies), "
        f"recomputed target_presence_status for {len(changed_presence)} capture(s)."
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
