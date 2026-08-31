"""Single command to rebuild every canonical artifact/figure/table the
current DEVELOPMENT-phase paper draft cites -- see
docs/ble/PAPER_EVIDENCE_MAP.md for the full report <-> artifact <-> figure
map this script's requirements mirror.

Pure orchestrator: calls the two existing, already-real generators
unchanged (`ScientificResultsRepository.run_paper_export()` via
`docs/ble/generate_evidence_figures.py`) and computes no science of its own
-- it only verifies, afterward, that every artifact this paper draft cites
actually exists. Fails loudly (non-zero exit, no partial-success message)
when a required artifact is still missing, rather than silently reporting
success on an incomplete rebuild.

Run from the repo root:
    backend/.venv-validation/Scripts/python.exe scripts/rebuild_development_paper_evidence.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "docs" / "ble"))

import generate_evidence_figures  # noqa: E402  (docs/ble/generate_evidence_figures.py)

# Every README figure this DEVELOPMENT phase's paper draft currently cites.
REQUIRED_README_FIGURES = [
    "evidence_rq1_domains.png",
    "evidence_rq2_branches.png",
    "evidence_confusion_validation.png",
    "evidence_confusion_test.png",
]

# paper_exports/*.csv entries (keyed by filename in export_manifest.json)
# that must be GENERATED, not SKIPPED_NO_DATA, for this paper draft.
REQUIRED_PAPER_EXPORT_ENTRIES = [
    "rq1_results.csv",
    "rq2_results.csv",
    "closed_set_partition_composition.csv",
    "closed_set_per_transmitter.csv",
    "closed_set_decision_windows.csv",
    "closed_set_risk_coverage_window_level.csv",
    "development_decision_window_summary.csv",
    "development_test_window_confusion_matrix.csv",
]


def main() -> int:
    repo = generate_evidence_figures.load_repository()
    generate_evidence_figures.main()  # regenerates readme_img/*.png and paper_exports/* (run_paper_export() internally)

    missing: list[str] = []

    for name in REQUIRED_README_FIGURES:
        if not (REPO_ROOT / "readme_img" / name).is_file():
            missing.append(f"readme_img/{name}")

    manifest_path = repo.root / "paper_exports" / "export_manifest.json"
    if not manifest_path.is_file():
        missing.append("paper_exports/export_manifest.json (never written)")
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        status_by_file = {e["file"]: e["status"] for e in manifest["entries"]}
        for name in REQUIRED_PAPER_EXPORT_ENTRIES:
            status = status_by_file.get(name)
            if status != "GENERATED":
                detail = next((e.get("detail") for e in manifest["entries"] if e["file"] == name), "not in manifest")
                missing.append(f"paper_exports/{name} (status={status!r}: {detail})")

    # sensitivity_report.json -- no CSV export convention exists for this
    # one (the dashboard's SensitivityTab.tsx reads it directly; the paper
    # cites LODO/offset-retaining/seed-variability from the same artifact +
    # that dashboard view, per docs/ble/PAPER_EVIDENCE_MAP.md).
    runs = [r for r in repo.list_runs() if r.scientific_task == "MULTI_DEVICE_CLASSIFICATION"]
    if not runs:
        missing.append("06_statistics/sensitivity_report.json (no MULTI_DEVICE_CLASSIFICATION paper run exists)")
    else:
        paper_run_id = runs[0].paper_run_id
        if repo.get_sensitivity_report(paper_run_id) is None:
            missing.append(f"{paper_run_id}/06_statistics/sensitivity_report.json")

    if missing:
        print("REBUILD_INCOMPLETE -- required artifact(s) missing or not real yet:")
        for item in missing:
            print(" -", item)
        print("\nRegenerate the missing source report(s) first (Study Control Center / Coverage tab -- see docs/ble/SCIENTIFIC_STATUS.md §18), then re-run this script.")
        return 1

    print(f"OK -- {len(REQUIRED_README_FIGURES)} figure(s) and {len(REQUIRED_PAPER_EXPORT_ENTRIES)} paper_exports entr(y/ies) present and real.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
