"""Runs scientific preflight against the ACTUAL, real ble_rffi_studio
storage already on disk in this repository -- not a synthetic fixture. Two
real, already-known outcomes are used as ground truth:

- CC2650-UNIT-01-AUTO-TVB is a real, frozen, READY, ACCEPTED_FOR_TRAINING
  dataset -- preflight should PASS.
- SHELLY-PLUG-01-ORIGINAL-BG-TVB is a real dataset whose split is already
  NOT_FEASIBLE on disk (genuine leakage on capture_id/execution_id/
  session_id, documented in docs/ble/SCIENTIFIC_STATUS.md) -- preflight
  should BLOCK with that exact leakage finding.

Writes only under tmp_path (this module's own run directory); never touches
storage/ble_rffi_studio/. Skipped automatically on any machine where this
specific real data isn't present (e.g. a fresh clone with no captured BLE
data yet), since it is real, machine-specific evidence, not a fixture this
repository can regenerate.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config.settings import settings
from app.modules.ble_scientific_results.api import ScientificResultsRepository

_REAL_BLE_ROOT = settings.storage.storage_root / "ble_rffi_studio"
_CC2650_DATASET_ID = "CC2650-UNIT-01-AUTO-TVB"
_CC2650_DATASET_VERSION = "20260801T185545.809291Z"
_SHELLY_DATASET_ID = "SHELLY-PLUG-01-ORIGINAL-BG-TVB"
_SHELLY_DATASET_VERSION = "20260803T115411.439792Z"
_TASK = "TARGET_VS_BACKGROUND"


def _dataset_exists(dataset_id: str, dataset_version: str) -> bool:
    return (_REAL_BLE_ROOT / "datasets" / f"{dataset_id}__{dataset_version}.json").is_file()


def _freeze_and_run(tmp_path: Path, *, dataset_id: str, dataset_version: str):
    repository = ScientificResultsRepository(tmp_path / "sci_results", _REAL_BLE_ROOT)
    contract = repository.freeze_protocol({
        "hardware_profile_id": "usrp-b200-e3r04z1b2", "receiver_profile_hash": "rx-hash", "interpretation_matrix_hash": "interp-hash-real-data-check",
    })
    run = repository.create_run(
        protocol_id=contract.protocol_id, protocol_version=contract.protocol_version, campaign_id="REAL-DATA-CHECK",
        dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=_TASK,
    )
    return repository, repository.run_preflight(run.paper_run_id)


@pytest.mark.skipif(not _dataset_exists(_CC2650_DATASET_ID, _CC2650_DATASET_VERSION), reason="Real CC2650-UNIT-01-AUTO-TVB dataset not present on this machine")
def test_real_cc2650_dataset_passes_preflight(tmp_path):
    _, report = _freeze_and_run(tmp_path, dataset_id=_CC2650_DATASET_ID, dataset_version=_CC2650_DATASET_VERSION)
    assert report.leakage.status == "PASSED", report.leakage.findings
    assert report.quality.status == "PASSED", report.quality.findings
    assert report.integrity.status == "PASSED", report.integrity.findings
    # Tier 2 (paper-campaign) is always BLOCKED against every real dataset
    # in this repository today -- no capture campaign here has ever
    # recorded day/pre-post/intervention/content-variant metadata (see
    # docs/ble/SCIENTIFIC_STATUS.md). Overall caps at the structural tier.
    assert report.overall_status == "DATASET_STRUCTURAL_PREFLIGHT_PASSED"
    assert report.paper_campaign_completeness.status == "BLOCKED"
    assert any("days" in finding for finding in report.paper_campaign_completeness.findings)


@pytest.mark.skipif(not _dataset_exists(_SHELLY_DATASET_ID, _SHELLY_DATASET_VERSION), reason="Real SHELLY-PLUG-01-ORIGINAL-BG-TVB dataset not present on this machine")
def test_real_shelly_original_background_blocks_on_real_leakage(tmp_path):
    _, report = _freeze_and_run(tmp_path, dataset_id=_SHELLY_DATASET_ID, dataset_version=_SHELLY_DATASET_VERSION)
    assert report.leakage.status == "BLOCKED"
    assert any("NOT_FEASIBLE" in finding for finding in report.leakage.findings)
    assert report.overall_status == "PREFLIGHT_BLOCKED"


@pytest.mark.skipif(not _dataset_exists(_CC2650_DATASET_ID, _CC2650_DATASET_VERSION), reason="Real CC2650-UNIT-01-AUTO-TVB dataset not present on this machine")
def test_real_cc2650_dataset_builds_canonical_records_and_accounting(tmp_path):
    """I.5: canonical records/accounting build against real data, and the
    resulting counts are genuinely reconstructed from the real replay
    artifacts on disk -- not hardcoded. 30 real captures are known (from
    docs/ble/SCIENTIFIC_STATUS.md research this session) to exist for this
    dataset, each with a real offline_replays/ directory."""
    repository, report = _freeze_and_run(tmp_path, dataset_id=_CC2650_DATASET_ID, dataset_version=_CC2650_DATASET_VERSION)
    run = repository.list_runs()[0]

    result = repository.build_records(run.paper_run_id)
    assert result.capture_record_count == 30
    assert result.burst_record_count > 0  # real candidates exist for every one of these real captures
    assert result.captures_without_replay == []  # every real capture here has a completed offline replay

    accounting = repository.build_campaign_accounting(run.paper_run_id)
    counters = accounting["counters"]
    assert counters["observed_captures"] == 30
    # Reconstructed from real records, not hardcoded: captures_with_bursts
    # can never exceed observed_captures, and eligible_captures is bounded
    # by the same real capture set.
    assert 0 <= counters["captures_with_bursts"] <= counters["observed_captures"]
    assert 0 <= counters["eligible_captures"] <= counters["observed_captures"]

    quality = repository.build_quality_summary(run.paper_run_id)
    assert quality["association_summary"]

    figures = repository.build_campaign_figures(run.paper_run_id)
    assert len(figures) == 16
