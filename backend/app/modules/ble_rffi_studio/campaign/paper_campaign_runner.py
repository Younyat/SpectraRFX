"""Minimal paper-campaign runner (user's explicit request: "no otra
interfaz compleja"). A script/service, not a new UI: reads a frozen
schedule, refuses to execute anything not on it, and links every real
capture back to the `planned_capture_id` that was declared before it ran.

Reuses `CampaignOrchestrator.run_session()` for the actual capture (real
hardware, real B200 lease, real Evidence Stage trigger) unchanged -- this
module never talks to the SDR/arbiter/capture worker directly, and never
duplicates that logic. The declared schedule metadata (day_id, pre_or_post,
intervention_arm, ...) is written onto the resulting capture's
`capture_manifest.json` immediately after the real capture completes, using
ONLY values already frozen in the schedule before the capture was issued --
never inferred, never reconstructed from anything observed after the fact.

Off-schedule attempts, and attempts whose declared parameters don't match
the frozen schedule entry (wrong unit/channel/pre-post/arm/variant/order/
epoch/firmware/configuration), are rejected BEFORE any real capture starts
and persisted to `<schedule_dir>/rejections.jsonl` -- the attempt itself is
never discarded, and there is no parameter that bypasses this check. The
canonical, schema-versioned PROTOCOL_DEVIATION record for each rejection is
produced later, at record-build time, by `ble_scientific_results` (see
records/campaign_deviations.py::build_runner_rejection_deviations), which
reads this log read-only -- this module deliberately never constructs a
ScientificCampaignDeviationRecord itself, to keep the dependency direction
one-way (ble_scientific_results depends on ble_rffi_studio, never the
reverse).
"""
from __future__ import annotations

import json
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from app.infrastructure.ble.capture.ble_capture_metadata import atomic_json

from ..contracts import CaptureRecord, PaperCampaignSchedule, PaperCampaignScheduleEntry

ProgressHook = Callable[[str, float, str], None] | None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class PaperCampaignSchedulingError(Exception):
    pass


# Maps an `attempted[...]` field the caller declares to the schedule-entry
# field it must match, and the protocol-deviation code raised on mismatch.
# Only fields actually present in `attempted` are checked -- absence is
# "not declared", never treated as a mismatch.
_ATTEMPTED_FIELD_TO_CODE: tuple[tuple[str, str], ...] = (
    ("physical_unit_id", "WRONG_UNIT"),
    ("channel", "WRONG_CHANNEL"),
    ("pre_or_post", "WRONG_PRE_POST_STATE"),
    ("intervention_arm", "WRONG_INTERVENTION_ARM"),
    ("packet_condition", "WRONG_PACKET_CONDITION"),
    ("receiver_epoch", "RECEIVER_EPOCH_MISMATCH"),
    ("receiver_session_id", "RECEIVER_SESSION_ID_MISMATCH"),
    ("firmware_hash", "FIRMWARE_MISMATCH"),
    ("configuration_hash", "CONFIGURATION_MISMATCH"),
)


class PaperCampaignRunner:
    def __init__(self, *, storage_root: Path, legacy_capture_root: Path, campaign_orchestrator: Any = None) -> None:
        self.storage_root = storage_root
        self.legacy_capture_root = legacy_capture_root
        self.campaign_orchestrator = campaign_orchestrator
        self.storage_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Schedule freeze / load
    # ------------------------------------------------------------------

    def _schedule_dir(self, schedule_id: str) -> Path:
        if any(part in schedule_id for part in ("/", "\\", "..")):
            raise ValueError("INVALID_SCHEDULE_ID")
        return self.storage_root / "paper_campaign" / "schedules" / schedule_id

    def _existing_versions(self, schedule_id: str) -> list[int]:
        directory = self._schedule_dir(schedule_id)
        if not directory.is_dir():
            return []
        versions = []
        for path in directory.glob("*.json"):
            try:
                versions.append(int(path.stem))
            except ValueError:
                continue
        return versions

    def freeze_schedule(
        self, *, schedule_id: str, protocol_id: str, entries: list[dict], qualification_only: bool = False,
        receiver_session_id: str | None = None,
    ) -> PaperCampaignSchedule:
        """`receiver_session_id` is the operator's real-world attestation that
        the B200 stayed connected/powered for this whole schedule (see
        contracts/paper_campaign.py -- there is no software signal for
        connection continuity, so this is never auto-detected). Defaults to a
        freshly generated id when the operator doesn't supply their own; every
        entry in this schedule shares the SAME id, since a schedule is one
        continuous attestation by construction. A genuine reconnect/power-
        cycle mid-campaign means freezing a NEW schedule, never editing this
        one."""
        resolved_session_id = receiver_session_id or f"session-{uuid.uuid4().hex[:16]}"
        entry_models = [
            PaperCampaignScheduleEntry(**{**entry, "receiver_session_id": entry.get("receiver_session_id") or resolved_session_id})
            for entry in entries
        ]
        planned_ids = [entry.planned_capture_id for entry in entry_models]
        if len(planned_ids) != len(set(planned_ids)):
            raise PaperCampaignSchedulingError(f"DUPLICATE_PLANNED_CAPTURE_ID_IN_SCHEDULE:{schedule_id}")

        next_version = (max(self._existing_versions(schedule_id), default=0)) + 1
        schedule = PaperCampaignSchedule(
            schedule_id=schedule_id, schedule_version=next_version, protocol_id=protocol_id,
            entries=entry_models, qualification_only=qualification_only, frozen_at=utc_now(),
            receiver_session_id=resolved_session_id,
        )
        atomic_json(self._schedule_dir(schedule_id) / f"{next_version}.json", schedule.model_dump(mode="json"))
        return schedule

    def load_schedule(self, schedule_id: str, version: int | None = None) -> PaperCampaignSchedule:
        target_version = version or max(self._existing_versions(schedule_id), default=None)
        if target_version is None:
            raise FileNotFoundError(f"SCHEDULE_NOT_FOUND:{schedule_id}")
        path = self._schedule_dir(schedule_id) / f"{target_version}.json"
        return PaperCampaignSchedule.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def _save_schedule(self, schedule: PaperCampaignSchedule) -> None:
        # A schedule's own per-entry `executed`/`executed_capture_id` is the
        # one exception to "never edit a frozen object" -- it is bookkeeping
        # about what has run, not a redeclaration of the plan itself. Still
        # written to the SAME version file (never a silent new schedule
        # version) so "what was planned" and "what has run against it" stay
        # visibly the same document.
        atomic_json(self._schedule_dir(schedule.schedule_id) / f"{schedule.schedule_version}.json", schedule.model_dump(mode="json"))

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def next_planned_capture(self, schedule: PaperCampaignSchedule) -> PaperCampaignScheduleEntry | None:
        for entry in schedule.entries:
            if not entry.executed:
                return entry
        return None

    def find_entry(self, schedule: PaperCampaignSchedule, planned_capture_id: str) -> PaperCampaignScheduleEntry | None:
        for entry in schedule.entries:
            if entry.planned_capture_id == planned_capture_id:
                return entry
        return None

    def _capture_metadata_payload(self, entry: PaperCampaignScheduleEntry) -> dict[str, Any]:
        return {
            "day_id": entry.day_id, "campaign_period": entry.campaign_period,
            "pre_or_post": None if entry.pre_or_post == "NOT_APPLICABLE" else entry.pre_or_post,
            "intervention_arm": None if entry.intervention_arm == "NOT_APPLICABLE" else entry.intervention_arm,
            "packet_condition": entry.packet_condition, "receiver_epoch": entry.receiver_epoch,
            "receiver_session_id": entry.receiver_session_id,
            "firmware_hash": entry.firmware_hash, "configuration_hash": entry.configuration_hash,
            "time_since_power_on_s": entry.time_since_power_on_s, "time_since_intervention_s": entry.time_since_intervention_s,
            "capture_order": entry.capture_order, "planned_capture_id": entry.planned_capture_id,
        }

    def _apply_declared_metadata_to_manifest(self, capture_id: str, entry: PaperCampaignScheduleEntry) -> None:
        manifest_path = self.legacy_capture_root / capture_id / "capture_manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"CAPTURE_MANIFEST_NOT_FOUND_AFTER_CAPTURE:{capture_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        # Every value here was already frozen in the schedule BEFORE this
        # capture was issued -- this is the "write it down" step, not a
        # reconstruction of anything observed after the fact.
        manifest.update(self._capture_metadata_payload(entry))
        atomic_json(manifest_path, manifest)

    def _violations_for_attempt(self, entry: PaperCampaignScheduleEntry, attempted: dict[str, Any]) -> list[str]:
        return [code for field, code in _ATTEMPTED_FIELD_TO_CODE if field in attempted and attempted[field] != getattr(entry, field)]

    def execute(
        self, schedule: PaperCampaignSchedule, planned_capture_id: str, *, build_capture_record: Callable[[str], CaptureRecord],
        attempted: dict[str, Any] | None = None, operator_id: str | None = None, progress: ProgressHook = None, **run_session_kwargs: Any,
    ) -> CaptureRecord:
        """`build_capture_record` re-reads the just-updated manifest into a
        real CaptureRecord (e.g. StudioRepository/CaptureStage's own
        build_capture, injected so this runner never re-implements that
        parsing).

        `attempted` is what the caller (CLI operator or an automated
        cross-check) declares it is ABOUT to run -- any field present there
        that disagrees with the frozen schedule entry rejects the capture
        before it starts (see _ATTEMPTED_FIELD_TO_CODE). A capture requested
        out of the schedule's own execution order is rejected the same way,
        with no `attempted` declaration required to detect it. There is no
        parameter that overrides either check."""
        if self.campaign_orchestrator is None:
            raise PaperCampaignSchedulingError("NO_CAMPAIGN_ORCHESTRATOR_CONFIGURED:cannot execute a real capture without one")
        entry = self.find_entry(schedule, planned_capture_id)
        if entry is None:
            self.reject_out_of_schedule(
                schedule=schedule, attempted={"planned_capture_id": planned_capture_id, **(attempted or {})},
                reason="CAPTURE_OUT_OF_SCHEDULE", planned_capture_id=planned_capture_id, operator_id=operator_id,
            )
            raise PaperCampaignSchedulingError(f"PLANNED_CAPTURE_ID_NOT_IN_SCHEDULE:{planned_capture_id}")
        if entry.executed:
            raise PaperCampaignSchedulingError(f"PLANNED_CAPTURE_ALREADY_EXECUTED:{planned_capture_id}")

        violations: list[str] = []
        next_entry = self.next_planned_capture(schedule)
        if next_entry is not None and next_entry.planned_capture_id != planned_capture_id:
            violations.append("WRONG_CAPTURE_ORDER")
        if attempted:
            violations.extend(self._violations_for_attempt(entry, attempted))

        if violations:
            self.reject_out_of_schedule(
                schedule=schedule, attempted=attempted or {}, reason=",".join(violations),
                planned_capture_id=planned_capture_id, operator_id=operator_id,
            )
            raise PaperCampaignSchedulingError(f"PROTOCOL_DEVIATION_DETECTED:{planned_capture_id}:{','.join(violations)}")

        result = self.campaign_orchestrator.run_session(
            ble_channel=entry.channel, physical_unit_id=entry.physical_unit_id, capture_purpose=entry.capture_purpose,
            progress=progress, **run_session_kwargs,
        )
        capture_id = result["capture_id"] if isinstance(result, dict) else result.capture_id

        self._apply_declared_metadata_to_manifest(capture_id, entry)
        capture_record = build_capture_record(capture_id)

        updated_entries = [
            e.model_copy(update={"executed": True, "executed_capture_id": capture_id}) if e.planned_capture_id == planned_capture_id else e
            for e in schedule.entries
        ]
        updated_schedule = schedule.model_copy(update={"entries": updated_entries})
        self._save_schedule(updated_schedule)
        return capture_record

    def reject_out_of_schedule(
        self, *, schedule: PaperCampaignSchedule, attempted: dict[str, Any], reason: str,
        planned_capture_id: str | None = None, operator_id: str | None = None,
    ) -> dict[str, Any]:
        """Refuses execution (the real enforcement lives in execute() itself,
        which calls this on every rejection path) and PERSISTS the rejection
        to `<schedule_dir>/rejections.jsonl` -- appended, never overwritten,
        so every real attempt (including malformed ones) stays on record.
        `reason` may be a single code or a comma-joined list of codes (see
        _ATTEMPTED_FIELD_TO_CODE / the WRONG_CAPTURE_ORDER / CAPTURE_OUT_OF_
        SCHEDULE codes execute() detects). ble_scientific_results reads this
        log read-only to build the canonical PROTOCOL_DEVIATION records --
        see records/campaign_deviations.py::build_runner_rejection_deviations."""
        record = {
            "schedule_id": schedule.schedule_id, "protocol_id": schedule.protocol_id, "planned_capture_id": planned_capture_id,
            "reason": reason, "attempted": attempted, "operator_id": operator_id, "rejected_at": utc_now(),
        }
        path = self._rejections_path(schedule.schedule_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        return record

    def _rejections_path(self, schedule_id: str) -> Path:
        return self._schedule_dir(schedule_id) / "rejections.jsonl"

    def list_rejections(self, schedule_id: str) -> list[dict[str, Any]]:
        path = self._rejections_path(schedule_id)
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_balanced_crossover_assignment(*, device_ids: Sequence[str], n_days: int, seed: int = 20260806) -> dict[str, list[str]]:
    """The frozen calendar for H2's within-device crossover (see
    statistics/hypothesis_power.py's H2 docstring): every device in
    `device_ids` gets exactly n_days//2 RESET days and n_days//2 CONTROL
    days (CONTROL here means CONTINUOUS_POWER -- the schedule keeps
    PaperCampaignScheduleEntry.intervention_arm's existing "RESET"/"CONTROL"
    vocabulary unchanged rather than adding a third literal, since the
    crossover design only changes WHO gets which arm and WHEN, not the arm
    vocabulary itself), independently shuffled per device -- no device is
    ever permanently assigned one arm, and no day is ever split between
    devices. Returns {device_id: [arm_for_day_0, arm_for_day_1, ...]},
    ready for the caller to attach day_id/capture_order/etc. onto each
    PaperCampaignScheduleEntry pair (one PRE + one POST) before freezing
    the real schedule via freeze_schedule()."""
    if n_days % 2 != 0:
        raise ValueError("N_DAYS_MUST_BE_EVEN_FOR_A_BALANCED_CROSSOVER")
    half = n_days // 2
    rng = random.Random(seed)
    assignment: dict[str, list[str]] = {}
    for device_id in device_ids:
        labels = ["RESET"] * half + ["CONTROL"] * half
        rng.shuffle(labels)
        assignment[device_id] = labels
    return assignment
