"""Physical Device Registry: physical_unit_id is always operator-declared,
never derived from a BLE address; an address binds to 0-or-1 unit; an unseen
address never auto-creates a unit; conflicting rebinds are recorded in
history and require a reason, never silently overwritten.
"""
from __future__ import annotations

import pytest

from app.modules.ble_rffi_studio.contracts import LabelEvidenceItem
from app.modules.ble_rffi_studio.registry import PhysicalDeviceRegistry


@pytest.fixture
def registry(tmp_path):
    return PhysicalDeviceRegistry(tmp_path / "registry")


def _evidence(strength="DOCUMENTARY"):
    return LabelEvidenceItem(
        source_type="OPERATOR_DECLARATION", artifact_id="decl-1",
        timestamp="2026-07-24T00:00:00Z", strength=strength, description="test evidence",
    )


def test_register_physical_unit_is_operator_declared(registry):
    unit = registry.register_physical_unit(
        physical_unit_id="CC2650-UNIT-01", project_id="BLE-RFFI-CC2650", device_family="TI_SENSOR_TAG",
        operator_declaration_id="decl-2026-07-24-001", first_registered_at="2026-07-24T00:00:00Z",
    )
    assert unit.physical_unit_id == "CC2650-UNIT-01"
    assert registry.get_physical_unit("CC2650-UNIT-01") == unit


def test_register_physical_unit_is_idempotent(registry):
    first = registry.register_physical_unit(physical_unit_id="U1", project_id="P1", device_family="F", operator_declaration_id="d1", first_registered_at="2026-07-24T00:00:00Z")
    second = registry.register_physical_unit(physical_unit_id="U1", project_id="P1", device_family="F", operator_declaration_id="d1", first_registered_at="2026-07-24T00:00:00Z")
    assert first == second


def test_observe_address_never_creates_a_physical_unit(registry):
    binding = registry.observe_address(project_id="P1", address="AA:BB:CC:DD:EE:FF", address_type="random", evidence=_evidence(), observed_at="2026-07-24T00:00:00Z")
    assert binding.binding_status == "UNBOUND"
    assert binding.bound_physical_unit_id is None
    assert registry.list_physical_units() == []


def test_declare_binding_requires_the_unit_to_already_exist(registry):
    with pytest.raises(ValueError):
        registry.declare_binding(
            project_id="P1", address="B0:B4:48:C0:36:06", address_type="public", physical_unit_id="CC2650-UNIT-01",
            evidence=_evidence(), decided_at="2026-07-24T00:00:00Z",
        )


def test_declare_binding_binds_the_address_to_the_unit(registry):
    registry.register_physical_unit(physical_unit_id="CC2650-UNIT-01", project_id="P1", device_family="TI", operator_declaration_id="d1", first_registered_at="2026-07-24T00:00:00Z")
    binding = registry.declare_binding(
        project_id="P1", address="B0:B4:48:C0:36:06", address_type="public", physical_unit_id="CC2650-UNIT-01",
        evidence=_evidence(), decided_at="2026-07-24T00:00:00Z",
    )
    assert binding.binding_status == "BOUND"
    assert binding.bound_physical_unit_id == "CC2650-UNIT-01"
    assert len(binding.binding_evidence) == 1


def test_one_unit_can_have_multiple_addresses(registry):
    registry.register_physical_unit(physical_unit_id="U1", project_id="P1", device_family="TI", operator_declaration_id="d1", first_registered_at="2026-07-24T00:00:00Z")
    b1 = registry.declare_binding(project_id="P1", address="AA:AA:AA:AA:AA:01", address_type="random", physical_unit_id="U1", evidence=_evidence(), decided_at="2026-07-24T00:00:00Z")
    b2 = registry.declare_binding(project_id="P1", address="AA:AA:AA:AA:AA:02", address_type="random", physical_unit_id="U1", evidence=_evidence(), decided_at="2026-07-24T00:00:01Z")
    assert b1.bound_physical_unit_id == b2.bound_physical_unit_id == "U1"
    assert b1.binding_id != b2.binding_id


def test_rebinding_an_address_to_a_different_unit_requires_a_reason(registry):
    registry.register_physical_unit(physical_unit_id="U1", project_id="P1", device_family="TI", operator_declaration_id="d1", first_registered_at="2026-07-24T00:00:00Z")
    registry.register_physical_unit(physical_unit_id="U2", project_id="P1", device_family="TI", operator_declaration_id="d2", first_registered_at="2026-07-24T00:00:00Z")
    registry.declare_binding(project_id="P1", address="AA:AA:AA:AA:AA:01", address_type="random", physical_unit_id="U1", evidence=_evidence(), decided_at="2026-07-24T00:00:00Z")

    with pytest.raises(ValueError):
        registry.declare_binding(project_id="P1", address="AA:AA:AA:AA:AA:01", address_type="random", physical_unit_id="U2", evidence=_evidence(), decided_at="2026-07-24T00:01:00Z", reason="")


def test_rebinding_with_a_reason_is_recorded_in_history_not_discarded(registry):
    registry.register_physical_unit(physical_unit_id="U1", project_id="P1", device_family="TI", operator_declaration_id="d1", first_registered_at="2026-07-24T00:00:00Z")
    registry.register_physical_unit(physical_unit_id="U2", project_id="P1", device_family="TI", operator_declaration_id="d2", first_registered_at="2026-07-24T00:00:00Z")
    registry.declare_binding(project_id="P1", address="AA:AA:AA:AA:AA:01", address_type="random", physical_unit_id="U1", evidence=_evidence(), decided_at="2026-07-24T00:00:00Z")

    rebound = registry.declare_binding(
        project_id="P1", address="AA:AA:AA:AA:AA:01", address_type="random", physical_unit_id="U2",
        evidence=_evidence(), decided_at="2026-07-24T00:01:00Z", reason="Random address rotated to a different confirmed unit under controlled test",
    )
    assert rebound.bound_physical_unit_id == "U2"
    assert len(rebound.history) == 1
    assert rebound.history[0].previous_physical_unit_id == "U1"


def test_flag_conflict_quarantines_without_deleting_evidence(registry):
    registry.register_physical_unit(physical_unit_id="U1", project_id="P1", device_family="TI", operator_declaration_id="d1", first_registered_at="2026-07-24T00:00:00Z")
    registry.declare_binding(project_id="P1", address="AA:AA:AA:AA:AA:01", address_type="random", physical_unit_id="U1", evidence=_evidence(), decided_at="2026-07-24T00:00:00Z")
    conflicted = registry.flag_conflict("P1", "AA:AA:AA:AA:AA:01", "random", _evidence(), observed_at="2026-07-24T00:02:00Z")
    assert conflicted.binding_status == "CONFLICTING"
    assert len(conflicted.binding_evidence) == 2


def test_find_binding_for_address_tries_both_address_types(registry):
    registry.register_physical_unit(physical_unit_id="U1", project_id="P1", device_family="TI", operator_declaration_id="d1", first_registered_at="2026-07-24T00:00:00Z")
    registry.declare_binding(project_id="P1", address="B0:B4:48:C0:36:06", address_type="public", physical_unit_id="U1", evidence=_evidence(), decided_at="2026-07-24T00:00:00Z")
    found = registry.find_binding_for_address("P1", "B0:B4:48:C0:36:06")
    assert found is not None
    assert found.bound_physical_unit_id == "U1"


def test_find_binding_for_unknown_address_is_none(registry):
    assert registry.find_binding_for_address("P1", "FF:FF:FF:FF:FF:FF") is None


def test_new_units_default_to_not_confirmed_and_not_eligible(registry):
    unit = registry.register_physical_unit(physical_unit_id="U1", project_id="P1", device_family="TI", operator_declaration_id="d1", first_registered_at="2026-07-24T00:00:00Z")
    assert unit.same_model_confirmation == "NOT_CONFIRMED"
    assert unit.rq4_eligibility == "NOT_ELIGIBLE"


def test_confirm_same_model_requires_a_real_basis(registry):
    registry.register_physical_unit(physical_unit_id="U1", project_id="P1", device_family="TI", operator_declaration_id="d1", first_registered_at="2026-07-24T00:00:00Z")
    with pytest.raises(ValueError):
        registry.confirm_same_model("U1", basis="   ")


def test_confirm_same_model_with_a_real_basis_persists(registry):
    registry.register_physical_unit(physical_unit_id="U1", project_id="P1", device_family="TI", operator_declaration_id="d1", first_registered_at="2026-07-24T00:00:00Z")
    updated = registry.confirm_same_model("U1", basis="internal_serial prefix match + operator physical inspection")
    assert updated.same_model_confirmation == "CONFIRMED"
    assert registry.get_physical_unit("U1").same_model_confirmation == "CONFIRMED"


def test_set_rq4_eligibility_requires_a_reason(registry):
    registry.register_physical_unit(physical_unit_id="U1", project_id="P1", device_family="TI", operator_declaration_id="d1", first_registered_at="2026-07-24T00:00:00Z")
    with pytest.raises(ValueError):
        registry.set_rq4_eligibility("U1", eligible=True, reason="")


def test_set_rq4_eligibility_true_and_false_both_persist_with_a_reason(registry):
    registry.register_physical_unit(physical_unit_id="U1", project_id="P1", device_family="TI", operator_declaration_id="d1", first_registered_at="2026-07-24T00:00:00Z")
    eligible = registry.set_rq4_eligibility("U1", eligible=True, reason="supports controlled AdvA content variants")
    assert eligible.rq4_eligibility == "ELIGIBLE"
    assert eligible.rq4_eligibility_reason == "supports controlled AdvA content variants"

    not_eligible = registry.set_rq4_eligibility("U1", eligible=False, reason="firmware does not allow content variant control")
    assert not_eligible.rq4_eligibility == "NOT_ELIGIBLE"


def test_eligibility_actions_never_deduce_from_device_family_or_model(registry):
    # Real, confirmed finding this correction protects against: a unit's
    # device_family/model string is operator-entered free text and can be
    # wrong (keyfobdemo 01's own device_family says "TI sensortag") --
    # neither eligibility action reads those fields at all.
    unit = registry.register_physical_unit(
        physical_unit_id="keyfobdemo-01", project_id="P1", device_family="TI sensortag",
        model="keyfobdemo", operator_declaration_id="d1", first_registered_at="2026-07-24T00:00:00Z",
    )
    assert unit.same_model_confirmation == "NOT_CONFIRMED"
    assert unit.rq4_eligibility == "NOT_ELIGIBLE"
