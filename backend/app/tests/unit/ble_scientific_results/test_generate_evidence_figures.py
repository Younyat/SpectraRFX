"""Figure/artifact sync closure (2026-08-18): docs/ble/generate_evidence_
figures.py is a standalone script (not part of the `app` package -- it
inserts `backend/` onto sys.path itself, the same trick reused here in
reverse to import IT from a backend test). RQ1/RQ2 are no longer rendered
by a second, independently-coded function here (fig_rq1_domains/
fig_rq2_branches were deleted) -- readme_img/'s copies are now always the
exact same PDF/PNG paper_export.py already rendered (see
figures/paper_figures.py::bar_with_ci_figure, multi-format). What remains
real to test in this module is `verify_figures()` -- the read-only
cross-check against `paper_exports/figure_manifest.json` -- since it is
this script's own logic, not a re-test of paper_export.py (tested
separately in test_paper_export_generation.py).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

DOCS_BLE_DIR = Path(__file__).resolve().parents[5] / "docs" / "ble"
sys.path.insert(0, str(DOCS_BLE_DIR))

import generate_evidence_figures as gef  # noqa: E402


def _repo(tmp_path):
    root = tmp_path / "sci_results"
    root.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(root=root)


def _write_rq1_artifact(repo, *, paper_run_id="RUN-1", evaluation_unit="EXAMPLE_RECORD", evidence_status="DEVELOPMENT", with_ci=True, ba_future=None) -> Path:
    path = repo.root / paper_run_id / "06_statistics" / "rq1_acquisition_dependence_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "evaluation_unit": evaluation_unit, "evidence_status": evidence_status,
        "ba_window": 0.968, "ba_capture": 0.749, "ba_future": ba_future, "ba_future_status": "NOT_YET_AVAILABLE" if ba_future is None else "EXECUTED",
        "delta_dependence": 0.219,
        "uncertainty_ci": {"ba_capture_ci": {"ci_low": 0.544, "ci_high": 0.884}} if with_ci else {},
    }
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _write_manifest(repo, entries: list[dict]) -> None:
    exports_dir = repo.root / "paper_exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    (exports_dir / "figure_manifest.json").write_text(json.dumps({"figures": entries}), encoding="utf-8")


def _write_rq1_svg(repo, *, include_ba_window_label=False, future_status_text=None, filename="rq1_acquisition_dependence.svg") -> None:
    """A minimal, real (parseable) SVG standing in for what `_save_figure()`
    actually writes -- exercises the same rendered-text checks
    verify_figures() runs against a real one. Default content is
    pass-safe: real capture-dependent/capture-disjoint labels, no
    'BA_window', no protected-FUTURE status text."""
    figures_dir = repo.root / "paper_exports" / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    labels = ["BA_window (intra-session)" if include_ba_window_label else "Capture-dependent (same capture)", "Capture-disjoint (VALIDATION)"]
    if future_status_text:
        labels.append(f"protected FUTURE ({future_status_text})")
    body = "".join(f"<text>{label}</text>" for label in labels)
    (figures_dir / filename).write_text(f"<svg>{body}</svg>", encoding="utf-8")


def _write_rq4_artifact(repo, *, paper_run_id="RUN-1", evidence_status="DEVELOPMENT_EXPLORATORY") -> Path:
    path = repo.root / paper_run_id / "06_statistics" / "rq4_full_burst_vs_pre_pdu_exploratory_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "evidence_status": evidence_status,
        "full_burst": {"balanced_accuracy": 0.634}, "pre_pdu": {"balanced_accuracy": 0.556},
        "delta": {"point_estimate": 0.078, "ci_low": 0.046, "ci_high": 0.100},
    }
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _write_rq4_svg(repo) -> None:
    """Pass-safe stand-in for the RQ4 figure's rendered SVG -- human-readable
    title/labels (no internal evidence_status/evaluation_unit enum text),
    includes the real delta CI text, contains no forbidden hardware-
    fingerprint phrasing."""
    figures_dir = repo.root / "paper_exports" / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    (figures_dir / "rq4_full_burst_vs_pre_pdu.svg").write_text(
        "<svg><text>Exploratory VALIDATION comparison: FULL_BURST vs PRE_PDU</text>"
        "<text>FULL_BURST</text><text>PRE_PDU</text><text>[0.046, 0.100]</text></svg>",
        encoding="utf-8",
    )


def _write_feature_group_ablation_artifact(repo, *, paper_run_id="RUN-1") -> Path:
    path = repo.root / paper_run_id / "06_statistics" / "feature_group_ablation_exploratory_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "evidence_status": "DEVELOPMENT_EXPLORATORY",
        "results": {
            "FULL": {"balanced_accuracy": 0.634}, "POWER_AMPLITUDE_LEVEL": {"balanced_accuracy": 0.238}, "REMAINING_SIX": {"balanced_accuracy": 0.787},
        },
        "contrasts": {"FULL_minus_POWER_AMPLITUDE_LEVEL": {"point_estimate": 0.396, "ci_low": 0.276, "ci_high": 0.508}},
    }
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _write_feature_group_ablation_svg(repo) -> None:
    figures_dir = repo.root / "paper_exports" / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    (figures_dir / "feature_group_ablation.svg").write_text(
        "<svg><text>Exploratory VALIDATION comparison: feature-group ablation</text>"
        "<text>Full 10 descriptors</text><text>Power/amplitude level (4)</text><text>Remaining descriptors (6)</text>"
        "<text>0.396, 95% CI [0.276, 0.508]</text></svg>",
        encoding="utf-8",
    )


def _write_session_stability_artifact(repo, *, paper_run_id="RUN-1") -> Path:
    path = repo.root / paper_run_id / "06_statistics" / "session_stability_analysis_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"evidence_status": "DEVELOPMENT_EXPLORATORY", "sessions": [{"physical_unit_pseudonym": "TX-01", "session_id": "S1", "recall": 0.9}]}
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _write_session_stability_svg(repo) -> None:
    figures_dir = repo.root / "paper_exports" / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    (figures_dir / "session_stability.svg").write_text(
        "<svg><text>Exploratory session-level recall by enrolled transmitter</text><text>TX-01</text></svg>", encoding="utf-8",
    )


def _write_rq2_publication_svg(repo) -> None:
    """Pass-safe stand-in for the publication RQ2 figure's rendered SVG --
    human-readable label, no internal snake_case branch key, no analysis-
    role text suffix."""
    figures_dir = repo.root / "paper_exports" / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    (figures_dir / "rq2_representation_comparison_publication.svg").write_text("<svg><text>Engineered RF</text></svg>", encoding="utf-8")


def _manifest_entry_for(source_path: Path, *, paper_run_id="RUN-1", evaluation_unit="EXAMPLE_RECORD", evidence_status="DEVELOPMENT", figure_path="figures/rq1_acquisition_dependence.png", source_artifact_relpath=None) -> dict:
    return {
        "figure_path": figure_path,
        "source_artifact": source_artifact_relpath or f"{paper_run_id}/06_statistics/rq1_acquisition_dependence_report.json",
        "source_artifact_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "paper_run_id": paper_run_id, "evaluation_unit": evaluation_unit, "evidence_status": evidence_status,
        "generator_commit": "deadbeef", "generated_at": "2026-08-18T00:00:00Z",
    }


def test_verify_fails_when_manifest_missing(tmp_path):
    repo = _repo(tmp_path)
    failures = gef.verify_figures(repo, None)
    assert len(failures) == 1
    assert "figure_manifest.json does not exist" in failures[0]


def test_verify_fails_when_a_required_figure_has_no_entry(tmp_path):
    repo = _repo(tmp_path)
    _write_manifest(repo, [])
    failures = gef.verify_figures(repo, None)
    assert any("MISSING_REQUIRED_SOURCE" in f and "rq1_acquisition_dependence" in f for f in failures)
    assert any("MISSING_REQUIRED_SOURCE" in f and "rq2_representation_comparison" in f for f in failures)
    assert any("MISSING_REQUIRED_SOURCE" in f and "rq4_full_burst_vs_pre_pdu" in f for f in failures)
    assert any("MISSING_REQUIRED_SOURCE" in f and "feature_group_ablation" in f for f in failures)
    assert any("MISSING_REQUIRED_SOURCE" in f and "session_stability" in f for f in failures)


def test_verify_passes_when_manifest_matches_real_artifact(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(gef, "OUT_DIR", tmp_path / "readme_img")
    rq1_path = _write_rq1_artifact(repo)
    _write_rq1_svg(repo)
    _write_rq1_svg(repo, filename="rq1_acquisition_dependence_publication.svg")
    _write_rq2_publication_svg(repo)
    rq2_path = repo.root / "RUN-1" / "06_statistics" / "rq2_representation_comparison_report.json"
    rq2_path.write_text(json.dumps({"evaluation_unit": "EXAMPLE_RECORD", "evidence_status": "DEVELOPMENT"}), encoding="utf-8")
    rq4_path = _write_rq4_artifact(repo)
    _write_rq4_svg(repo)
    ablation_path = _write_feature_group_ablation_artifact(repo)
    _write_feature_group_ablation_svg(repo)
    stability_path = _write_session_stability_artifact(repo)
    _write_session_stability_svg(repo)
    entries = [
        _manifest_entry_for(rq1_path, figure_path="figures/rq1_acquisition_dependence.png"),
        _manifest_entry_for(rq2_path, figure_path="figures/rq2_representation_comparison.png", source_artifact_relpath="RUN-1/06_statistics/rq2_representation_comparison_report.json"),
        _manifest_entry_for(rq1_path, figure_path="figures/rq1_acquisition_dependence_publication.png"),
        _manifest_entry_for(rq2_path, figure_path="figures/rq2_representation_comparison_publication.png", source_artifact_relpath="RUN-1/06_statistics/rq2_representation_comparison_report.json"),
        _manifest_entry_for(
            rq4_path, figure_path="figures/rq4_full_burst_vs_pre_pdu.png", evidence_status="DEVELOPMENT_EXPLORATORY",
            source_artifact_relpath="RUN-1/06_statistics/rq4_full_burst_vs_pre_pdu_exploratory_report.json",
        ),
        _manifest_entry_for(
            ablation_path, figure_path="figures/feature_group_ablation.png", evidence_status="DEVELOPMENT_EXPLORATORY",
            source_artifact_relpath="RUN-1/06_statistics/feature_group_ablation_exploratory_report.json",
        ),
        _manifest_entry_for(
            stability_path, figure_path="figures/session_stability.png", evidence_status="DEVELOPMENT_EXPLORATORY",
            source_artifact_relpath="RUN-1/06_statistics/session_stability_analysis_report.json",
        ),
    ]
    _write_manifest(repo, entries)
    assert gef.verify_figures(repo, None) == []
    assert gef.verify_figures(repo, "RUN-1") == []


def test_verify_fails_on_stale_artifact_hash(tmp_path, monkeypatch):
    # The classic desync this whole mechanism exists to catch: the artifact
    # changed on disk (regenerated) but the figure/manifest were not.
    repo = _repo(tmp_path)
    monkeypatch.setattr(gef, "OUT_DIR", tmp_path / "readme_img")
    rq1_path = _write_rq1_artifact(repo)
    rq2_path = repo.root / "RUN-1" / "06_statistics" / "rq2_representation_comparison_report.json"
    rq2_path.write_text(json.dumps({"evaluation_unit": "EXAMPLE_RECORD", "evidence_status": "DEVELOPMENT"}), encoding="utf-8")
    entries = [
        _manifest_entry_for(rq1_path),
        _manifest_entry_for(rq2_path, figure_path="figures/rq2_representation_comparison.png", source_artifact_relpath="RUN-1/06_statistics/rq2_representation_comparison_report.json"),
    ]
    _write_manifest(repo, entries)
    # Real artifact changes (e.g. re-run of RQ1) -- manifest's recorded
    # sha256 is now stale.
    rq1_path.write_text(json.dumps({"evaluation_unit": "EXAMPLE_RECORD", "evidence_status": "DEVELOPMENT", "ba_window": 0.5, "ba_capture": 0.4, "uncertainty_ci": {"ba_capture_ci": {"ci_low": 0.3, "ci_high": 0.5}}}), encoding="utf-8")
    failures = gef.verify_figures(repo, None)
    assert any("STALE_ARTIFACT" in f and "rq1_acquisition_dependence" in f for f in failures)


def test_verify_fails_when_evaluation_unit_mismatches(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(gef, "OUT_DIR", tmp_path / "readme_img")
    rq1_path = _write_rq1_artifact(repo, evaluation_unit="EXAMPLE_RECORD")
    entry = _manifest_entry_for(rq1_path, evaluation_unit="DECISION_WINDOW")  # manifest disagrees with the real artifact
    _write_manifest(repo, [entry])
    failures = gef.verify_figures(repo, None)
    assert any("EVALUATION_UNIT_MISMATCH" in f for f in failures)


def test_verify_fails_when_paper_run_id_does_not_match(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(gef, "OUT_DIR", tmp_path / "readme_img")
    rq1_path = _write_rq1_artifact(repo, paper_run_id="RUN-1")
    entry = _manifest_entry_for(rq1_path, paper_run_id="RUN-1")
    _write_manifest(repo, [entry])
    failures = gef.verify_figures(repo, "RUN-DIFFERENT")
    assert any("PAPER_RUN_ID_MISMATCH" in f for f in failures)


def test_verify_fails_when_required_ci_missing(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(gef, "OUT_DIR", tmp_path / "readme_img")
    rq1_path = _write_rq1_artifact(repo, with_ci=False)
    entry = _manifest_entry_for(rq1_path)
    _write_manifest(repo, [entry])
    failures = gef.verify_figures(repo, None)
    assert any("MISSING_REQUIRED_CI" in f for f in failures)


def test_verify_fails_when_test_labeled_as_future(tmp_path, monkeypatch):
    # ba_future is still None (protected FUTURE not executed) but the
    # manifest claims evidence_status=PROTECTED_FUTURE -- exactly the
    # TEST != FUTURE conflation this whole pass exists to prevent.
    repo = _repo(tmp_path)
    monkeypatch.setattr(gef, "OUT_DIR", tmp_path / "readme_img")
    rq1_path = _write_rq1_artifact(repo, ba_future=None)
    entry = _manifest_entry_for(rq1_path, evidence_status="PROTECTED_FUTURE")
    _write_manifest(repo, [entry])
    failures = gef.verify_figures(repo, None)
    assert any("TEST_LABELED_AS_FUTURE" in f for f in failures)


def test_verify_fails_when_ba_window_label_found_in_svg(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(gef, "OUT_DIR", tmp_path / "readme_img")
    rq1_path = _write_rq1_artifact(repo)
    _write_rq1_svg(repo, include_ba_window_label=True)
    _write_manifest(repo, [_manifest_entry_for(rq1_path)])
    failures = gef.verify_figures(repo, None)
    assert any("BA_WINDOW_LABEL_FOUND" in f for f in failures)


def test_verify_fails_when_ci_not_in_svg_text(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    monkeypatch.setattr(gef, "OUT_DIR", tmp_path / "readme_img")
    path = repo.root / "RUN-1" / "06_statistics" / "rq1_acquisition_dependence_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "evaluation_unit": "EXAMPLE_RECORD", "evidence_status": "DEVELOPMENT",
        "ba_window": 0.968, "ba_capture": 0.749, "ba_future": None, "ba_future_status": "NOT_YET_AVAILABLE",
        "delta_dependence": 0.219,
        "uncertainty_ci": {"ba_capture_ci": {"ci_low": 0.544, "ci_high": 0.884}, "delta_dependence_ci": {"ci_low": 0.077, "ci_high": 0.414}},
    }), encoding="utf-8")
    _write_rq1_svg(repo)  # does NOT contain the real delta_dependence_ci text
    _write_manifest(repo, [_manifest_entry_for(path)])
    failures = gef.verify_figures(repo, None)
    assert any("CI_NOT_IN_FIGURE" in f for f in failures)


def test_verify_fails_when_future_status_text_rendered_while_ba_future_none(tmp_path, monkeypatch):
    # Stronger than the entry-level TEST_LABELED_AS_FUTURE check: this reads
    # the ACTUAL rendered SVG text, not just the manifest's own claim.
    repo = _repo(tmp_path)
    monkeypatch.setattr(gef, "OUT_DIR", tmp_path / "readme_img")
    rq1_path = _write_rq1_artifact(repo, ba_future=None)
    _write_rq1_svg(repo, future_status_text="NOT_YET_AVAILABLE")
    _write_manifest(repo, [_manifest_entry_for(rq1_path)])
    failures = gef.verify_figures(repo, None)
    assert any(f.startswith("figures/rq1_acquisition_dependence.png: TEST_LABELED_AS_FUTURE -- rendered SVG contains ba_future_status") for f in failures)


def test_verify_fails_when_readme_copy_diverges_from_paper_export(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    out_dir = tmp_path / "readme_img"
    out_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(gef, "OUT_DIR", out_dir)
    rq1_path = _write_rq1_artifact(repo)
    rq2_path = repo.root / "RUN-1" / "06_statistics" / "rq2_representation_comparison_report.json"
    rq2_path.write_text(json.dumps({"evaluation_unit": "EXAMPLE_RECORD", "evidence_status": "DEVELOPMENT"}), encoding="utf-8")
    entries = [
        _manifest_entry_for(rq1_path),
        _manifest_entry_for(rq2_path, figure_path="figures/rq2_representation_comparison.png", source_artifact_relpath="RUN-1/06_statistics/rq2_representation_comparison_report.json"),
    ]
    _write_manifest(repo, entries)
    figures_dir = repo.root / "paper_exports" / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    (figures_dir / "rq1_acquisition_dependence_publication.png").write_bytes(b"real-png-bytes")
    (out_dir / "evidence_rq1_domains.png").write_bytes(b"DIFFERENT-bytes-someone-hand-edited-this")
    failures = gef.verify_figures(repo, None)
    assert any("DIVERGED_FROM_PAPER_EXPORT" in f for f in failures)


# --- verify_documentation_matches_artifacts(): README/SCIENTIFIC_STATUS.md cross-checks ---

def _doc_check_repo(tmp_path):
    root = tmp_path / "sci_results"
    exports_dir = root / "paper_exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    (exports_dir / "development_decision_window_summary.csv").write_text(
        "partition,n_windows,balanced_accuracy,accuracy\n"
        "TRAIN,34,1.0,1.0\n"
        "VALIDATION,12,0.75,0.8333333333333334\n"
        "TEST,12,0.875,0.9166666666666666\n",
        encoding="utf-8",
    )
    dashboard = {"closed_set": {
        "rq1": {"ba_window": 0.9682, "ba_capture": 0.7494, "delta_dependence": 0.2187, "uncertainty_ci": {}},
        "primary_test": {"balanced_accuracy": 0.7666},
    }}
    return SimpleNamespace(
        root=root,
        get_evidence_dashboard_summary=lambda: dashboard,
        get_latest_association_calibration_summary=lambda: {"status": "NO_THRESHOLD_SATISFIES_CRITERIA"},
    )


def _write_doc_fixtures(repo_root: Path, *, capture_dependent_ba="0.968") -> None:
    """Real regex patterns verify_documentation_matches_artifacts() searches
    for -- this fixture text intentionally mirrors the exact wording this
    project's own README.md/SCIENTIFIC_STATUS.md use, so the test exercises
    the SAME patterns the real files are checked against."""
    (repo_root / "README.md").write_text(
        "| Capture-dependent (same capture, intentionally leakage-optimistic diagnostic) "
        f"| {capture_dependent_ba} | n/a | 1,790 |\n"
        "| Capture-disjoint (VALIDATION) | 0.749 | [0.544, 0.884] | 2,203 |\n"
        "| Held-out TEST (PRIMARY branch, not protected FUTURE) | 0.767 | -- | 2,464 |\n\n"
        "delta_dependence = capture-dependent - capture-disjoint = +0.219, 95% CI [0.077, 0.414]\n\n"
        "- `TRAIN=34`, `VALIDATION=12`, `TEST=12` real windows\n"
        "- `VALIDATION`: `BA=0.750`, `accuracy=0.833`\n"
        "- `TEST`: `BA=0.875`, `accuracy=0.917`\n",
        encoding="utf-8",
    )
    status_dir = repo_root / "docs" / "ble"
    status_dir.mkdir(parents=True, exist_ok=True)
    (status_dir / "SCIENTIFIC_STATUS.md").write_text(
        "| RQ1 capture-dependent BA / 95% CI / n | `0.968` / n/a / `1790` |\n"
        "| RQ1 capture-disjoint (VALIDATION) BA / 95% CI / n | `0.749` / `[0.544, 0.884]` / `2203` |\n"
        "| RQ1 `delta_dependence` / 95% CI | `0.219` / `[0.077, 0.414]` |\n"
        "| RQ1 held-out TEST BA (not protected FUTURE) | `0.767` |\n"
        "| 10-second decision windows | `TRAIN=34`, `VALIDATION=12`, `TEST=12` -- all 4/4 classes |\n"
        "| VALIDATION window-level BA / argmax accuracy / operational coverage | `0.750` / `0.833` (10/12) / `0.833` |\n"
        "| TEST window-level BA / argmax accuracy / operational coverage | `0.875` / `0.917` (11/12) / `0.833` |\n"
        "| Association calibration | `NO_THRESHOLD_SATISFIES_CRITERIA` |\n",
        encoding="utf-8",
    )


def test_verify_documentation_passes_when_readme_and_status_match_real_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(gef, "REPO_ROOT", tmp_path)
    _write_doc_fixtures(tmp_path)
    assert gef.verify_documentation_matches_artifacts(_doc_check_repo(tmp_path)) == []


def test_verify_documentation_fails_when_readme_number_drifts_from_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(gef, "REPO_ROOT", tmp_path)
    _write_doc_fixtures(tmp_path, capture_dependent_ba="0.500")  # real artifact says ~0.968
    failures = gef.verify_documentation_matches_artifacts(_doc_check_repo(tmp_path))
    assert any(f.startswith("README: rq1_ba_window claims 0.5") for f in failures)
