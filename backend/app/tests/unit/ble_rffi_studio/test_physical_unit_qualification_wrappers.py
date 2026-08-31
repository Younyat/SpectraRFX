"""Study Control Center, phase 02 (2026-08-11): StudioRepository.confirm_same_model/
set_rq4_eligibility are thin wrappers over the already-tested
PhysicalDeviceRegistry methods (see test_physical_device_registry.py) --
these tests only prove the wrapper delegates correctly, since that's the
new surface a route now depends on.
"""
from __future__ import annotations

import pytest

from app.modules.ble_rffi_studio.api import StudioRepository


@pytest.fixture
def repository(tmp_path):
    return StudioRepository(tmp_path / "studio", legacy_capture_root=tmp_path / "legacy_captures", legacy_session_root=tmp_path / "legacy_sessions")


def test_confirm_same_model_delegates_to_the_registry(repository):
    repository.register_physical_unit(physical_unit_id="U1", project_id="P1", device_family="F", operator_declaration_id="d1")
    updated = repository.confirm_same_model("U1", basis="internal_serial prefix match + operator physical inspection")
    assert updated.same_model_confirmation == "CONFIRMED"
    assert updated.same_model_confirmation_basis == "internal_serial prefix match + operator physical inspection"


def test_confirm_same_model_requires_a_real_basis(repository):
    repository.register_physical_unit(physical_unit_id="U1", project_id="P1", device_family="F", operator_declaration_id="d1")
    with pytest.raises(ValueError, match="BASIS_REQUIRED_TO_CONFIRM_SAME_MODEL"):
        repository.confirm_same_model("U1", basis="")


def test_set_rq4_eligibility_delegates_to_the_registry(repository):
    repository.register_physical_unit(physical_unit_id="U1", project_id="P1", device_family="F", operator_declaration_id="d1")
    updated = repository.set_rq4_eligibility("U1", eligible=True, reason="same-model group confirmed, packet-content variation captured for this unit")
    assert updated.rq4_eligibility == "ELIGIBLE"
    assert updated.rq4_eligibility_reason


def test_set_rq4_eligibility_requires_a_real_reason(repository):
    repository.register_physical_unit(physical_unit_id="U1", project_id="P1", device_family="F", operator_declaration_id="d1")
    with pytest.raises(ValueError, match="REASON_REQUIRED_TO_SET_RQ4_ELIGIBILITY"):
        repository.set_rq4_eligibility("U1", eligible=False, reason="")
