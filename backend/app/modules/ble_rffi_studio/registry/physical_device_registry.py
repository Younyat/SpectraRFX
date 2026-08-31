"""Physical Device Registry: the only place physical_unit_id is created.

Structural rules enforced here (not just documented):
  - physical_unit_id is always operator-declared (register_physical_unit);
    nothing in this file derives one from a BLE address.
  - An address is bound to at most one physical_unit_id at a time
    (AddressBinding), but a unit may have many addresses over time.
  - observe_address() is the passive path: it records that an address was
    seen, and creates an UNBOUND binding if the address is new, but NEVER
    creates or infers a physical unit.
  - declare_binding() is the only path that sets bound_physical_unit_id, and
    it is always an explicit operator/evidence-backed action. Rebinding an
    address already bound to a DIFFERENT unit requires a non-empty reason and
    is recorded in history -- never silently overwritten.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.infrastructure.ble.capture.ble_offline_replay import read_json, write_json

from ..contracts import (
    AddressBinding,
    AddressBindingHistoryItem,
    LabelEvidenceItem,
    PhysicalUnitRecord,
)


class PhysicalDeviceRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.units_dir = root / "physical_units"
        self.bindings_dir = root / "address_bindings"
        self.units_dir.mkdir(parents=True, exist_ok=True)
        self.bindings_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Physical units
    # ------------------------------------------------------------------

    def _unit_path(self, physical_unit_id: str) -> Path:
        return self.units_dir / f"{physical_unit_id}.json"

    def register_physical_unit(
        self,
        *,
        physical_unit_id: str,
        project_id: str,
        device_family: str,
        operator_declaration_id: str,
        first_registered_at: str,
        manufacturer: str | None = None,
        model: str | None = None,
        internal_serial: str | None = None,
    ) -> PhysicalUnitRecord:
        path = self._unit_path(physical_unit_id)
        if path.is_file():
            existing = PhysicalUnitRecord.model_validate(read_json(path))
            if existing.project_id != project_id:
                raise ValueError(f"PHYSICAL_UNIT_ALREADY_REGISTERED_UNDER_DIFFERENT_PROJECT:{physical_unit_id}")
            return existing  # idempotent re-registration
        record = PhysicalUnitRecord(
            physical_unit_id=physical_unit_id,
            project_id=project_id,
            device_family=device_family,
            manufacturer=manufacturer,
            model=model,
            internal_serial=internal_serial,
            operator_declaration_id=operator_declaration_id,
            first_registered_at=first_registered_at,
        )
        write_json(path, record.model_dump(mode="json"))
        return record

    def get_physical_unit(self, physical_unit_id: str) -> PhysicalUnitRecord | None:
        path = self._unit_path(physical_unit_id)
        if not path.is_file():
            return None
        return PhysicalUnitRecord.model_validate(read_json(path))

    def list_physical_units(self) -> list[PhysicalUnitRecord]:
        return [PhysicalUnitRecord.model_validate(read_json(p)) for p in sorted(self.units_dir.glob("*.json"))]

    def confirm_same_model(self, physical_unit_id: str, *, basis: str) -> PhysicalUnitRecord:
        """The ONLY way same_model_confirmation becomes CONFIRMED -- never
        inferred from device_family/model/commercial name (see
        PhysicalUnitRecord's own docstring on this field for the real,
        confirmed reason why name-based inference is unsafe here).
        `basis` must be real, non-empty evidence (e.g. "internal_serial
        prefix match + operator physical inspection"), never a placeholder."""
        if not basis.strip():
            raise ValueError("BASIS_REQUIRED_TO_CONFIRM_SAME_MODEL")
        unit = self.get_physical_unit(physical_unit_id)
        if unit is None:
            raise ValueError(f"UNKNOWN_PHYSICAL_UNIT_ID:{physical_unit_id}")
        updated = unit.model_copy(update={"same_model_confirmation": "CONFIRMED", "same_model_confirmation_basis": basis})
        write_json(self._unit_path(physical_unit_id), updated.model_dump(mode="json"))
        return updated

    def set_rq4_eligibility(self, physical_unit_id: str, *, eligible: bool, reason: str) -> PhysicalUnitRecord:
        """RQ4 (packet-content-dependence) eligibility -- always an explicit
        operator decision with a stated reason, in either direction (marking
        NOT_ELIGIBLE with a reason is just as real a decision as ELIGIBLE)."""
        if not reason.strip():
            raise ValueError("REASON_REQUIRED_TO_SET_RQ4_ELIGIBILITY")
        unit = self.get_physical_unit(physical_unit_id)
        if unit is None:
            raise ValueError(f"UNKNOWN_PHYSICAL_UNIT_ID:{physical_unit_id}")
        updated = unit.model_copy(update={
            "rq4_eligibility": "ELIGIBLE" if eligible else "NOT_ELIGIBLE", "rq4_eligibility_reason": reason,
        })
        write_json(self._unit_path(physical_unit_id), updated.model_dump(mode="json"))
        return updated

    # ------------------------------------------------------------------
    # Address bindings
    # ------------------------------------------------------------------

    def _binding_path(self, binding_id: str) -> Path:
        return self.bindings_dir / f"{binding_id}.json"

    def get_binding(self, project_id: str, address: str, address_type: str) -> AddressBinding | None:
        binding_id = AddressBinding.make_binding_id(project_id, address, address_type)
        path = self._binding_path(binding_id)
        if not path.is_file():
            return None
        return AddressBinding.model_validate(read_json(path))

    def list_bindings(self) -> list[AddressBinding]:
        return [AddressBinding.model_validate(read_json(p)) for p in sorted(self.bindings_dir.glob("*.json"))]

    def find_binding_for_address(self, project_id: str, address: str) -> AddressBinding | None:
        """Looks up a binding by address alone (address_type unknown to the
        caller, e.g. Evidence Stage joining from a decoded packet)."""
        for candidate_type in ("public", "random"):
            binding = self.get_binding(project_id, address, candidate_type)
            if binding is not None:
                return binding
        return None

    def observe_address(
        self,
        *,
        project_id: str,
        address: str,
        address_type: str,
        evidence: LabelEvidenceItem,
        observed_at: str,
    ) -> AddressBinding:
        existing = self.get_binding(project_id, address, address_type)
        if existing is None:
            binding = AddressBinding(
                binding_id=AddressBinding.make_binding_id(project_id, address, address_type),
                project_id=project_id,
                address=address,
                address_type=address_type,
                bound_physical_unit_id=None,
                binding_status="UNBOUND",
                binding_evidence=[evidence],
                first_seen=observed_at,
                last_seen=observed_at,
                history=[],
            )
            write_json(self._binding_path(binding.binding_id), binding.model_dump(mode="json"))
            return binding
        updated = existing.model_copy(update={
            "binding_evidence": [*existing.binding_evidence, evidence],
            "last_seen": observed_at,
        })
        write_json(self._binding_path(updated.binding_id), updated.model_dump(mode="json"))
        return updated

    def declare_binding(
        self,
        *,
        project_id: str,
        address: str,
        address_type: str,
        physical_unit_id: str,
        evidence: LabelEvidenceItem,
        decided_at: str,
        reason: str = "initial operator declaration",
    ) -> AddressBinding:
        if self.get_physical_unit(physical_unit_id) is None:
            raise ValueError(f"UNKNOWN_PHYSICAL_UNIT_ID:{physical_unit_id}. Register it first -- a binding never creates a unit.")

        existing = self.get_binding(project_id, address, address_type)
        binding_id = AddressBinding.make_binding_id(project_id, address, address_type)

        if existing is None:
            binding = AddressBinding(
                binding_id=binding_id, project_id=project_id, address=address, address_type=address_type,
                bound_physical_unit_id=physical_unit_id, binding_status="BOUND",
                binding_evidence=[evidence], first_seen=decided_at, last_seen=decided_at, history=[],
            )
            write_json(self._binding_path(binding_id), binding.model_dump(mode="json"))
            return binding

        if existing.bound_physical_unit_id == physical_unit_id:
            updated = existing.model_copy(update={
                "binding_evidence": [*existing.binding_evidence, evidence],
                "last_seen": decided_at,
                "binding_status": "BOUND",
            })
            write_json(self._binding_path(binding_id), updated.model_dump(mode="json"))
            return updated

        if not reason.strip():
            raise ValueError("REASON_REQUIRED_TO_REBIND_ADDRESS_ALREADY_BOUND_TO_A_DIFFERENT_UNIT")
        history_item = AddressBindingHistoryItem(
            previous_physical_unit_id=existing.bound_physical_unit_id,
            changed_at=decided_at,
            reason=reason,
        )
        updated = existing.model_copy(update={
            "bound_physical_unit_id": physical_unit_id,
            "binding_status": "BOUND",
            "binding_evidence": [*existing.binding_evidence, evidence],
            "last_seen": decided_at,
            "history": [*existing.history, history_item],
        })
        write_json(self._binding_path(binding_id), updated.model_dump(mode="json"))
        return updated

    def flag_conflict(self, project_id: str, address: str, address_type: str, evidence: LabelEvidenceItem, observed_at: str) -> AddressBinding:
        """An address observed with evidence pointing at two units at once.
        Never resolved automatically -- quarantined until an operator
        investigates (see declare_binding for the only way out)."""
        existing = self.get_binding(project_id, address, address_type)
        if existing is None:
            raise ValueError(f"CANNOT_FLAG_CONFLICT_FOR_UNKNOWN_BINDING:{address}")
        updated = existing.model_copy(update={
            "binding_status": "CONFLICTING",
            "binding_evidence": [*existing.binding_evidence, evidence],
            "last_seen": observed_at,
        })
        write_json(self._binding_path(updated.binding_id), updated.model_dump(mode="json"))
        return updated
