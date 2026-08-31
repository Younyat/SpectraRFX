"""Study Control Center, Phase 1 (2026-08-11): SCIENTIFIC_REAL_CAMPAIGN_MODE
must forbid synthetic/demo data generation. Uses monkeypatch.setenv (never
writes to the real, shared runtime_settings.json) so this test cannot leak
state into other tests or the real environment.
"""
from __future__ import annotations

import pytest

from app.modules.ble_rffi_studio.api import StudioRepository
from app.modules.ble_rffi_studio.demo.synthetic_demo_seeder import RealCampaignModeError


@pytest.fixture
def repository(tmp_path):
    return StudioRepository(tmp_path / "studio", legacy_capture_root=tmp_path / "legacy_captures", legacy_session_root=tmp_path / "legacy_sessions")


def test_seed_synthetic_demo_succeeds_when_real_campaign_mode_is_off(repository, monkeypatch):
    monkeypatch.delenv("SCIENTIFIC_REAL_CAMPAIGN_MODE", raising=False)
    result = repository.seed_synthetic_demo()
    assert result["project_id"] == "SYNTHETIC_DEMO"


def test_seed_synthetic_demo_raises_when_real_campaign_mode_is_on(repository, monkeypatch):
    monkeypatch.setenv("SCIENTIFIC_REAL_CAMPAIGN_MODE", "true")
    with pytest.raises(RealCampaignModeError, match="SCIENTIFIC_REAL_CAMPAIGN_MODE"):
        repository.seed_synthetic_demo()
