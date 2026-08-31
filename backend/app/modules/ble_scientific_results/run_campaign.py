"""Minimal single-command executor for a frozen PaperCampaignSchedule
against REAL hardware (user's explicit "no otra interfaz compleja" applies
here exactly as it did to paper_campaign_runner.py itself). Never a new UI:
a terminal loop that shows one planned capture at a time, asks the operator
to confirm the physical action was done, and launches the existing capture
via CampaignOrchestrator -- nothing about capture/replay/evidence is
reimplemented here.

Usage:

    python -m app.modules.ble_scientific_results.run_campaign ^
        --protocol run_config.json --schedule pilot_schedule.json

`run_config.json` (the run's own identity/hardware defaults, NOT an
AnalysisContract -- that is frozen separately per PILOT_CHECKLIST.md):
    {
      "protocol_id": "...", "campaign_id": "...", "project_id": "...",
      "operator_id": "OP-1",                 # optional, linked into every
                                              # rejected attempt
      "duration_seconds": 120.0, "gain_db": 20.0, "device_id": null,
      "isolation_declared": true,            # see note below -- keep true
                                              # for a real controlled pilot
      "storage_root": null                   # optional override
    }

`pilot_schedule.json`:
    {
      "schedule_id": "PILOT-2026-08", "qualification_only": true,
      "entries": [ {..one dict per PaperCampaignScheduleEntry field..}, ... ]
    }
The schedule is frozen once (first invocation) and reused by schedule_id on
every later invocation -- entries already marked executed are skipped, so
re-running this command resumes exactly where the operator left off.

SAFETY: this script constructs the SAME real hybrid/capture managers
ble_lab's own module wiring constructs, by calling `ble_lab_module.
build_router(None)` unchanged (never re-implemented here) -- and the SAME
file-based SdrDeviceArbiter ble_rffi_studio already uses (safe across
separate processes: it is a lease file, not an in-process lock). The
underlying hybrid/capture managers themselves are NOT safe across separate
processes (see app/modules/ble_lab/shared_managers.py's own docstring) --
do not run this command while the spectrum-lab API server is also live
against the same physical B200.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.config.settings import settings
from app.modules.ble_lab.module import ble_lab_module
from app.modules.ble_lab.shared_managers import get_shared_managers
from app.modules.ble_rffi_studio.api import StudioRepository
from app.modules.ble_rffi_studio.campaign import CampaignOrchestrator, PaperCampaignRunner, PaperCampaignSchedulingError
from app.modules.ble_rffi_studio.contracts import CaptureRecord
from app.modules.ble_rffi_studio.hardware import SdrDeviceArbiter


def _confirm(prompt: str) -> bool:
    return input(prompt).strip().lower() in ("s", "si", "sí", "y", "yes")


def _describe(entry) -> str:
    return "\n".join([
        f"planned_capture_id:      {entry.planned_capture_id}",
        f"day_id:                  {entry.day_id}",
        f"unit (physical_unit_id): {entry.physical_unit_id}",
        f"channel:                 {entry.channel}",
        f"capture_order:           {entry.capture_order}",
        f"pre/post:                {entry.pre_or_post}",
        f"reset/control:           {entry.intervention_arm}",
        f"packet_condition:        {entry.packet_condition}",
        f"required waiting time:   time_since_power_on_s={entry.time_since_power_on_s}, "
        f"time_since_intervention_s={entry.time_since_intervention_s}",
        f"receiver_epoch:          {entry.receiver_epoch}",
    ])


def _load_schedule(runner: PaperCampaignRunner, *, schedule_id: str, protocol_id: str, schedule_input: dict[str, Any]):
    try:
        schedule = runner.load_schedule(schedule_id)
        print(f"Calendario '{schedule_id}' ya existe (versión {schedule.schedule_version}); se reutiliza sin volver a congelarlo.")
        return schedule
    except FileNotFoundError:
        pass
    entries = schedule_input["entries"]
    for entry in entries:
        entry.setdefault("protocol_id", protocol_id)
    schedule = runner.freeze_schedule(
        schedule_id=schedule_id, protocol_id=protocol_id, entries=entries,
        qualification_only=bool(schedule_input.get("qualification_only", False)),
        receiver_session_id=schedule_input.get("receiver_session_id"),
    )
    print(f"Calendario '{schedule_id}' congelado (versión {schedule.schedule_version}, {len(schedule.entries)} capturas planificadas).")
    return schedule


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Executes a frozen PaperCampaignSchedule, one real capture at a time.")
    parser.add_argument("--protocol", required=True, help="Path to a run-config JSON (protocol_id, campaign_id, project_id, ...).")
    parser.add_argument("--schedule", required=True, help="Path to the schedule JSON to freeze (first run) or reuse (by schedule_id).")
    args = parser.parse_args(argv)

    config: dict[str, Any] = json.loads(Path(args.protocol).read_text(encoding="utf-8"))
    schedule_input: dict[str, Any] = json.loads(Path(args.schedule).read_text(encoding="utf-8"))
    schedule_id = schedule_input["schedule_id"]
    root = Path(config["storage_root"]) if config.get("storage_root") else settings.storage.storage_root

    print("Arrancando los mismos gestores reales de hardware que usa el servidor de la API (ble_lab)...")
    print("ADVERTENCIA: no ejecutar el servidor FastAPI de spectrum-lab contra el mismo B200 mientras se usa este comando.")
    ble_lab_module.build_router(None)
    shared = get_shared_managers()
    if shared is None:
        print("ERROR: ble_lab no publicó sus gestores compartidos; no hay hardware disponible.", file=sys.stderr)
        return 1

    arbiter = SdrDeviceArbiter(root / "ble_rffi_studio" / "hardware_locks")
    orchestrator = CampaignOrchestrator(hybrid_manager=shared.hybrid_manager, capture_manager=shared.capture_manager, arbiter=arbiter, repository=None)
    repository = StudioRepository(
        root / "ble_rffi_studio", legacy_capture_root=root / "ble" / "iq_captures",
        legacy_session_root=root / "ble_lab" / "sessions", campaign_orchestrator=orchestrator,
    )
    orchestrator.repository = repository
    runner = PaperCampaignRunner(storage_root=root / "ble_rffi_studio", legacy_capture_root=root / "ble" / "iq_captures", campaign_orchestrator=orchestrator)

    schedule = _load_schedule(runner, schedule_id=schedule_id, protocol_id=config["protocol_id"], schedule_input=schedule_input)

    def build_capture_record(capture_id: str) -> CaptureRecord:
        # Re-reads the manifest AFTER the runner has just written the
        # schedule's declared metadata onto it -- reusing the identity
        # fields (execution_id, session_id, capture_purpose, ...) that
        # run_session()'s OWN first build_capture() call already resolved
        # correctly, so this second pass only refreshes the new fields
        # instead of silently regressing them to None.
        previous = repository.get_capture(capture_id)
        if previous is None:
            raise RuntimeError(f"CAPTURE_NOT_FOUND_AFTER_RUN_SESSION:{capture_id}")
        return repository.build_capture(
            capture_id=capture_id, project_id=previous.project_id, campaign_id=previous.campaign_id,
            execution_id=previous.execution_id, session_id=previous.session_id,
            isolation_declared_physical_unit_id=previous.isolation_declared_physical_unit_id,
            capture_purpose=previous.capture_purpose, target_state=previous.target_state,
            background_kind=previous.background_kind, target_reference_id=previous.target_reference_id,
            dataset_role=previous.dataset_role,
        )

    executed_count = 0
    while True:
        schedule = runner.load_schedule(schedule_id)
        entry = runner.next_planned_capture(schedule)
        if entry is None:
            print(f"\nNo quedan capturas planificadas pendientes en '{schedule_id}'. Ejecutadas en esta sesión: {executed_count}.")
            break

        print("\n" + "=" * 60)
        print(_describe(entry))
        print("=" * 60)
        if not _confirm("¿Confirmas que la acción física fue realizada tal como se declara arriba? [s/N] "):
            print("Cancelado por el operador. No se ejecuta ninguna captura más en esta sesión.")
            break

        try:
            capture_record = runner.execute(
                schedule, entry.planned_capture_id, build_capture_record=build_capture_record,
                operator_id=config.get("operator_id"),
                duration_seconds=float(config.get("duration_seconds", 120.0)), gain_db=float(config.get("gain_db", 20.0)),
                condition_label=f"{schedule_id}:{entry.planned_capture_id}",
                project_id=config["project_id"], campaign_id=config["campaign_id"],
                session_index=entry.capture_order, device_id=config.get("device_id"),
                # A schedule entry's physical_unit_id is a real, controlled
                # declaration by the operator (that is the entire point of
                # running through the frozen schedule) -- keep this true
                # unless the run_config explicitly opts out.
                isolation_declared=bool(config.get("isolation_declared", True)),
            )
        except PaperCampaignSchedulingError as exc:
            print(f"RECHAZADA antes de iniciar cualquier captura real (registrada en rejections.jsonl): {exc}", file=sys.stderr)
            break

        print(f"Captura real completada: capture_id={capture_record.capture_id}")
        executed_count += 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
