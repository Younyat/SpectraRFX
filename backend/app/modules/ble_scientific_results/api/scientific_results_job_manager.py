"""Background jobs for BLE Scientific Results Studio. Same job.json /
background-thread pattern as ble_rffi_studio's StudioJobManager (stage,
progress, elapsed time via started_at/updated_at, cancel state), reused here
independently since this module runs its own, unrelated jobs (preflight
scans tens of thousands of ExampleRecords -- slow enough to need progress
reporting, but it never touches the B200 or any other exclusive hardware
resource ble_rffi_studio's own jobs serialize on).

Cancellation never deletes partial artifacts: run_preflight() writes its
report only once fully computed, so a cancelled job simply leaves no
02_integrity/scientific_preflight_report.json behind, never a half-written
one.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.infrastructure.ble.capture.ble_capture_metadata import atomic_json

from ..hardware_qualification import run_real_hardware_qualification
from ..module_logging import build_module_logger
from ..rq1_runner import run_rq1_acquisition_dependence
from ..rq2_benchmark import run_rq2_benchmark
from .scientific_results_repository import ScientificResultsRepository

TERMINAL = {"completed", "failed", "cancelled"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ScientificResultsJobManager:
    def __init__(self, repository: ScientificResultsRepository, jobs_root: Path, campaign_orchestrator: Any | None = None, studio_repository: Any | None = None) -> None:
        self.repository = repository
        self.jobs_root = jobs_root
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self.logger = build_module_logger(jobs_root.parent)
        self._cancel_flags: dict[str, threading.Event] = {}
        # Deferred import -- guided_validation/service.py imports
        # ScientificResultsRepository from THIS package, so a module-level
        # import here would be circular. Reuses repository.freeze_protocol/
        # create_run/build_records and calibration.select_association_policy
        # unchanged -- see guided_validation/service.py's own docstring.
        # Never a second records builder or decoder. `campaign_orchestrator`
        # is the SAME real CampaignOrchestrator ble_rffi_studio's own module
        # wiring constructs (hybrid_manager/capture_manager/arbiter shared,
        # never a second competing instance) -- None when ble_lab's shared
        # managers are unavailable, in which case the two hardware actions
        # fail closed with a clear error instead of touching hardware.
        from ..guided_validation import GuidedBleScientificValidationService
        self._guided_validation_service = GuidedBleScientificValidationService(repository, campaign_orchestrator=campaign_orchestrator)
        # Same real CampaignOrchestrator as above, stored directly too --
        # the HARDWARE_QUALIFICATION job (Study Control Center, Phase 1)
        # drives it straight via hardware_qualification.py rather than
        # through GuidedBleScientificValidationService, since it isn't a
        # guided-validation action.
        self._campaign_orchestrator = campaign_orchestrator
        # Study Control Center, phase 08 (2026-08-11): RQ2_BENCHMARK drives
        # StudioRepository.train_selected_models() -- real training, no
        # hardware -- so this is a SEPARATE dependency from
        # campaign_orchestrator (which is only ever non-None when real
        # ble_lab hardware managers exist). None when the caller does not
        # wire one, in which case RQ2_BENCHMARK fails closed with a clear
        # error instead of silently doing nothing.
        self._studio_repository = studio_repository

    def _job_dir(self, job_id: str) -> Path:
        if not job_id.startswith("BLE-SCI-RESULTS-JOB-") or any(part in job_id for part in ("/", "\\", "..")):
            raise ValueError("INVALID_JOB_ID")
        return self.jobs_root / job_id

    def _new_job_id(self) -> str:
        return "BLE-SCI-RESULTS-JOB-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]

    def _write(self, job_dir: Path, state: str, **fields: Any) -> None:
        path = job_dir / "job.json"
        previous = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        merged = {**previous, **fields, "state": state, "updated_at": utc_now()}
        atomic_json(path, merged)
        job_id = merged.get("job_id") or job_dir.name
        job_type = merged.get("job_type", "UNKNOWN")
        if state == "failed":
            self.logger.error("[%s] job=%s state=%s error=%s", job_type, job_id, state, merged.get("error"))
        else:
            self.logger.info("[%s] job=%s state=%s stage=%s progress=%s message=%s", job_type, job_id, state, merged.get("stage"), merged.get("overall_progress"), merged.get("message"))

    def get_job(self, job_id: str) -> dict[str, Any]:
        path = self._job_dir(job_id) / "job.json"
        if not path.is_file():
            raise FileNotFoundError("SCIENTIFIC_RESULTS_JOB_NOT_FOUND")
        return json.loads(path.read_text(encoding="utf-8"))

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        if job.get("state") not in TERMINAL:
            self._cancel_flags.setdefault(job_id, threading.Event()).set()
        return self.get_job(job_id)

    # ------------------------------------------------------------------
    # Preflight
    # ------------------------------------------------------------------

    def start_preflight_job(self, *, paper_run_id: str) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        cancel_event = threading.Event()
        self._cancel_flags[job_id] = cancel_event
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-scientific-results-job-v1", "job_id": job_id, "job_type": "PREFLIGHT",
            "paper_run_id": paper_run_id, "state": "queued", "stage": None, "overall_progress": 0.0,
            "message": None, "warnings": [], "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_preflight_job, args=(job_id, paper_run_id, cancel_event), daemon=True).start()
        return self.get_job(job_id)

    def _run_preflight_job(self, job_id: str, paper_run_id: str, cancel_event: threading.Event) -> None:
        job_dir = self._job_dir(job_id)
        self._write(job_dir, "running", job_type="PREFLIGHT", paper_run_id=paper_run_id, stage="starting", overall_progress=0.0, message="Starting scientific preflight")
        try:
            def progress(stage: str, fraction: float, message: str) -> None:
                if cancel_event.is_set():
                    raise RuntimeError("PREFLIGHT_CANCELLED")
                self._write(job_dir, "running", job_type="PREFLIGHT", paper_run_id=paper_run_id, stage=stage, overall_progress=fraction, message=str(message))

            report = self.repository.run_preflight(paper_run_id, progress=progress)
            self._write(job_dir, "completed", job_type="PREFLIGHT", paper_run_id=paper_run_id, stage="done", overall_progress=1.0, message=report.overall_status, overall_status=report.overall_status)
        except RuntimeError as error:
            if str(error) == "PREFLIGHT_CANCELLED":
                self._write(job_dir, "cancelled", job_type="PREFLIGHT", paper_run_id=paper_run_id, message="Cancelled by operator")
            else:
                self._write(job_dir, "failed", job_type="PREFLIGHT", paper_run_id=paper_run_id, error=str(error))
        except Exception as error:  # noqa: BLE001 -- job failure must always be recorded, never silently swallowed
            self._write(job_dir, "failed", job_type="PREFLIGHT", paper_run_id=paper_run_id, error=str(error))
        finally:
            self._cancel_flags.pop(job_id, None)

    # ------------------------------------------------------------------
    # Fase 2: build-records (canonical records + campaign accounting +
    # quality summary + figures, in that order -- the one async job the
    # Fase 2 endpoint surface (Section H) exposes; every downstream GET
    # endpoint just reads what this job already wrote to disk)
    # ------------------------------------------------------------------

    def start_build_records_job(self, *, paper_run_id: str) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        cancel_event = threading.Event()
        self._cancel_flags[job_id] = cancel_event
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-scientific-results-job-v1", "job_id": job_id, "job_type": "BUILD_RECORDS",
            "paper_run_id": paper_run_id, "state": "queued", "stage": None, "overall_progress": 0.0,
            "message": None, "warnings": [], "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_build_records_job, args=(job_id, paper_run_id, cancel_event), daemon=True).start()
        return self.get_job(job_id)

    def _run_build_records_job(self, job_id: str, paper_run_id: str, cancel_event: threading.Event) -> None:
        job_dir = self._job_dir(job_id)
        self._write(job_dir, "running", job_type="BUILD_RECORDS", paper_run_id=paper_run_id, stage="records", overall_progress=0.0, message="Building canonical records")
        try:
            def progress(stage: str, fraction: float, message: str) -> None:
                if cancel_event.is_set():
                    raise RuntimeError("BUILD_RECORDS_CANCELLED")
                # Records is stage 1 of 4 (0.0-0.6), accounting/quality/figures share the rest.
                overall = 0.6 * fraction
                self._write(job_dir, "running", job_type="BUILD_RECORDS", paper_run_id=paper_run_id, stage=f"records:{stage}", overall_progress=overall, message=str(message))

            result = self.repository.build_records(paper_run_id, progress=progress)

            if cancel_event.is_set():
                raise RuntimeError("BUILD_RECORDS_CANCELLED")
            self._write(job_dir, "running", job_type="BUILD_RECORDS", paper_run_id=paper_run_id, stage="campaign_accounting", overall_progress=0.7, message="Building campaign accounting")
            self.repository.build_campaign_accounting(paper_run_id)

            if cancel_event.is_set():
                raise RuntimeError("BUILD_RECORDS_CANCELLED")
            self._write(job_dir, "running", job_type="BUILD_RECORDS", paper_run_id=paper_run_id, stage="quality_summary", overall_progress=0.85, message="Building descriptive quality summary")
            self.repository.build_quality_summary(paper_run_id)

            if cancel_event.is_set():
                raise RuntimeError("BUILD_RECORDS_CANCELLED")
            self._write(job_dir, "running", job_type="BUILD_RECORDS", paper_run_id=paper_run_id, stage="figures", overall_progress=0.95, message="Generating descriptive figures")
            self.repository.build_campaign_figures(paper_run_id)

            self._write(
                job_dir, "completed", job_type="BUILD_RECORDS", paper_run_id=paper_run_id, stage="done", overall_progress=1.0,
                message="Canonical records, campaign accounting, quality summary, and figures built",
                capture_record_count=result.capture_record_count, burst_record_count=result.burst_record_count,
                decision_window_record_count=result.decision_window_record_count, campaign_deviation_count=result.campaign_deviation_count,
            )
        except RuntimeError as error:
            if str(error) == "BUILD_RECORDS_CANCELLED":
                self._write(job_dir, "cancelled", job_type="BUILD_RECORDS", paper_run_id=paper_run_id, message="Cancelled by operator")
            else:
                self._write(job_dir, "failed", job_type="BUILD_RECORDS", paper_run_id=paper_run_id, error=str(error))
        except Exception as error:  # noqa: BLE001
            self._write(job_dir, "failed", job_type="BUILD_RECORDS", paper_run_id=paper_run_id, error=str(error))
        finally:
            self._cancel_flags.pop(job_id, None)

    # ------------------------------------------------------------------
    # Guided BLE Scientific Validation -- spans every enrolled device's
    # existing dataset (not one paper_run_id), so it gets its own job type
    # rather than reusing BUILD_RECORDS's paper_run_id-keyed shape.
    # ------------------------------------------------------------------

    def list_capturable_devices(self) -> list[dict[str, Any]]:
        return self._guided_validation_service.list_enrolled_devices_for_capture()

    def new_capture_session(self) -> dict[str, Any]:
        return {"run_id": self._guided_validation_service.new_capture_session()}

    def list_guided_validation_runs_for_cleanup(self) -> list[dict[str, Any]]:
        return self._guided_validation_service.list_runs_for_cleanup()

    def delete_guided_validation_run(self, run_id: str) -> dict[str, Any]:
        return self._guided_validation_service.delete_run(run_id)

    def run_source_admission_v2(self) -> dict[str, Any]:
        return self._guided_validation_service.run_source_admission_v2()

    def start_guided_validation_job(self) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        cancel_event = threading.Event()
        self._cancel_flags[job_id] = cancel_event
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-scientific-results-job-v1", "job_id": job_id, "job_type": "GUIDED_VALIDATION",
            "state": "queued", "stage": None, "overall_progress": 0.0, "message": None, "warnings": [],
            "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_guided_validation_job, args=(job_id, cancel_event), daemon=True).start()
        return self.get_job(job_id)

    def _run_guided_validation_job(self, job_id: str, cancel_event: threading.Event) -> None:
        job_dir = self._job_dir(job_id)
        self._write(job_dir, "running", job_type="GUIDED_VALIDATION", stage="discover", overall_progress=0.0, message="Starting guided BLE scientific validation")
        try:
            def progress(stage: str, fraction: float, message: str) -> None:
                if cancel_event.is_set():
                    raise RuntimeError("GUIDED_VALIDATION_CANCELLED")
                self._write(job_dir, "running", job_type="GUIDED_VALIDATION", stage=stage, overall_progress=fraction, message=str(message))

            summary = self._guided_validation_service.run(progress=progress)
            self._write(
                job_dir, "completed", job_type="GUIDED_VALIDATION", stage="done", overall_progress=1.0,
                message=summary.overall_status, result=summary.model_dump(mode="json"),
            )
        except RuntimeError as error:
            if str(error) == "GUIDED_VALIDATION_CANCELLED":
                self._write(job_dir, "cancelled", job_type="GUIDED_VALIDATION", message="Cancelled by operator")
            else:
                self._write(job_dir, "failed", job_type="GUIDED_VALIDATION", error=str(error))
        except Exception as error:  # noqa: BLE001
            self._write(job_dir, "failed", job_type="GUIDED_VALIDATION", error=str(error))
        finally:
            self._cancel_flags.pop(job_id, None)

    # ------------------------------------------------------------------
    # Guided Validation hardware actions -- Live Timing Diagnostic and
    # Reinforced Target-Absence Control. Both run a REAL, short, supervised
    # capture (see guided_validation/service.py's run_timing_diagnostic/
    # run_target_absence_control -- neither talks to the SDR/native
    # scanner/arbiter directly, only CampaignOrchestrator.run_session()
    # does). Same job.json/background-thread pattern as every other job
    # here. cancel_job() (the same generic method used for preflight/
    # build-records/guided-validation above) now also works for these two:
    # CampaignOrchestrator checks the shared cancel_event during both the
    # RF-acquisition and replay/decode polling loops and stops the real
    # session via hybrid_manager.stop()/capture_manager.cancel_offline_replay()
    # rather than abandoning it -- see campaign_orchestrator.py.
    # ------------------------------------------------------------------

    def start_timing_diagnostic_job(self, *, run_id: str, physical_unit_id: str, capture_duration_s: float, channel: int, receiver_profile: str | None, operator_id: str | None) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        cancel_event = threading.Event()
        self._cancel_flags[job_id] = cancel_event
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-scientific-results-job-v1", "job_id": job_id, "job_type": "TIMING_DIAGNOSTIC",
            "run_id": run_id, "physical_unit_id": physical_unit_id, "state": "queued", "stage": None, "overall_progress": 0.0,
            "message": None, "warnings": [], "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_timing_diagnostic_job, args=(job_id, run_id, physical_unit_id, capture_duration_s, channel, receiver_profile, operator_id, cancel_event), daemon=True).start()
        return self.get_job(job_id)

    def _run_timing_diagnostic_job(self, job_id: str, run_id: str, physical_unit_id: str, capture_duration_s: float, channel: int, receiver_profile: str | None, operator_id: str | None, cancel_event: threading.Event) -> None:
        job_dir = self._job_dir(job_id)
        self._write(job_dir, "running", job_type="TIMING_DIAGNOSTIC", run_id=run_id, stage="capture", overall_progress=0.0, message="Starting live timing diagnostic")
        try:
            def progress(stage: str, fraction: float, message: str) -> None:
                self._write(job_dir, "running", job_type="TIMING_DIAGNOSTIC", run_id=run_id, stage=stage, overall_progress=fraction, message=str(message))

            result = self._guided_validation_service.run_timing_diagnostic(
                run_id=run_id, physical_unit_id=physical_unit_id, capture_duration_s=capture_duration_s, channel=channel,
                receiver_profile=receiver_profile, operator_id=operator_id, progress=progress, cancel_event=cancel_event,
            )
            self._write(job_dir, "completed", job_type="TIMING_DIAGNOSTIC", run_id=run_id, stage="done", overall_progress=1.0, message=result["diagnosis_code"], result=result)
        except Exception as error:  # noqa: BLE001 -- includes HardwareActionError (B200_BUSY, missing address, operator-requested cancel, etc.)
            if "CANCELLED_BY_OPERATOR" in str(error):
                self._write(job_dir, "cancelled", job_type="TIMING_DIAGNOSTIC", run_id=run_id, message="Cancelled by operator")
            else:
                self._write(job_dir, "failed", job_type="TIMING_DIAGNOSTIC", run_id=run_id, error=str(error))
        finally:
            self._cancel_flags.pop(job_id, None)

    def start_target_absence_control_job(self, *, run_id: str, confirmed_devices_off: dict[str, bool], capture_duration_s: float, channel: int, operator_id: str | None) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        cancel_event = threading.Event()
        self._cancel_flags[job_id] = cancel_event
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-scientific-results-job-v1", "job_id": job_id, "job_type": "TARGET_ABSENCE_CONTROL",
            "run_id": run_id, "state": "queued", "stage": None, "overall_progress": 0.0, "message": None, "warnings": [],
            "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_target_absence_control_job, args=(job_id, run_id, confirmed_devices_off, capture_duration_s, channel, operator_id, cancel_event), daemon=True).start()
        return self.get_job(job_id)

    def _run_target_absence_control_job(self, job_id: str, run_id: str, confirmed_devices_off: dict[str, bool], capture_duration_s: float, channel: int, operator_id: str | None, cancel_event: threading.Event) -> None:
        job_dir = self._job_dir(job_id)
        self._write(job_dir, "running", job_type="TARGET_ABSENCE_CONTROL", run_id=run_id, stage="capture", overall_progress=0.0, message="Starting reinforced target-absence control")
        try:
            def progress(stage: str, fraction: float, message: str) -> None:
                self._write(job_dir, "running", job_type="TARGET_ABSENCE_CONTROL", run_id=run_id, stage=stage, overall_progress=fraction, message=str(message))

            result = self._guided_validation_service.run_target_absence_control(
                run_id=run_id, confirmed_devices_off=confirmed_devices_off, capture_duration_s=capture_duration_s,
                channel=channel, operator_id=operator_id, progress=progress, cancel_event=cancel_event,
            )
            self._write(job_dir, "completed", job_type="TARGET_ABSENCE_CONTROL", run_id=run_id, stage="done", overall_progress=1.0, message=result["status"], result=result)
        except Exception as error:  # noqa: BLE001
            if "CANCELLED_BY_OPERATOR" in str(error):
                self._write(job_dir, "cancelled", job_type="TARGET_ABSENCE_CONTROL", run_id=run_id, message="Cancelled by operator")
            else:
                self._write(job_dir, "failed", job_type="TARGET_ABSENCE_CONTROL", run_id=run_id, error=str(error))
        finally:
            self._cancel_flags.pop(job_id, None)

    # ------------------------------------------------------------------
    # Study Control Center, Phase 1 (2026-08-11): RUN REAL HARDWARE
    # QUALIFICATION. Same job.json/background-thread pattern as every job
    # above; drives the SAME real CampaignOrchestrator (never a second
    # competing instance) via hardware_qualification.py, which computes no
    # new science -- only real hardware/decode/preprocessing calls feeding
    # the untouched run_campaign_qualification_preflight() classifier.
    # ------------------------------------------------------------------

    def start_hardware_qualification_job(self, *, physical_unit_id: str, channel: int, duration_seconds: float) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        cancel_event = threading.Event()
        self._cancel_flags[job_id] = cancel_event
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-scientific-results-job-v1", "job_id": job_id, "job_type": "HARDWARE_QUALIFICATION",
            "physical_unit_id": physical_unit_id, "channel": channel, "duration_seconds": duration_seconds,
            "state": "queued", "stage": None, "overall_progress": 0.0, "message": None, "warnings": [],
            "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_hardware_qualification_job, args=(job_id, physical_unit_id, channel, duration_seconds, cancel_event), daemon=True).start()
        return self.get_job(job_id)

    def _run_hardware_qualification_job(self, job_id: str, physical_unit_id: str, channel: int, duration_seconds: float, cancel_event: threading.Event) -> None:
        job_dir = self._job_dir(job_id)
        self._write(job_dir, "running", job_type="HARDWARE_QUALIFICATION", physical_unit_id=physical_unit_id, stage="starting", overall_progress=0.0, message="Starting real hardware qualification")
        try:
            def progress(stage: str, fraction: float, message: str) -> None:
                self._write(job_dir, "running", job_type="HARDWARE_QUALIFICATION", physical_unit_id=physical_unit_id, stage=stage, overall_progress=fraction, message=str(message))

            result = run_real_hardware_qualification(
                sci_repository=self.repository, campaign_orchestrator=self._campaign_orchestrator,
                physical_unit_id=physical_unit_id, channel=channel, duration_seconds=duration_seconds,
                progress=progress, cancel_event=cancel_event,
            )
            overall_status = result["preflight_report"]["overall_status"]
            self._write(
                job_dir, "completed", job_type="HARDWARE_QUALIFICATION", physical_unit_id=physical_unit_id, stage="done",
                overall_progress=1.0, message=overall_status, result=result,
            )
        except Exception as error:  # noqa: BLE001 -- includes HardwareQualificationError (no orchestrator configured, missing capture record)
            if "CANCELLED_BY_OPERATOR" in str(error):
                self._write(job_dir, "cancelled", job_type="HARDWARE_QUALIFICATION", physical_unit_id=physical_unit_id, message="Cancelled by operator")
            else:
                self._write(job_dir, "failed", job_type="HARDWARE_QUALIFICATION", physical_unit_id=physical_unit_id, error=str(error))
        finally:
            self._cancel_flags.pop(job_id, None)

    # ------------------------------------------------------------------
    # Study Control Center, phase 08 (2026-08-11): RUN RQ2 VALIDATION
    # BENCHMARK. Drives the SAME real StudioRepository.train_selected_models()
    # every other training UI already uses (VALIDATION-only, TEST never
    # opened); rq2_benchmark.py computes no new science, only maps the real
    # per-model result onto the 4 real RQ2 branches.
    # ------------------------------------------------------------------

    def start_rq2_benchmark_job(self, *, paper_run_id: str, dataset_id: str, dataset_version: str, scientific_task: str, model_types: list[str] | None) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-scientific-results-job-v1", "job_id": job_id, "job_type": "RQ2_BENCHMARK",
            "paper_run_id": paper_run_id, "dataset_id": dataset_id, "dataset_version": dataset_version,
            "state": "queued", "stage": None, "overall_progress": 0.0, "message": None, "warnings": [],
            "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_rq2_benchmark_job, args=(job_id, paper_run_id, dataset_id, dataset_version, scientific_task, model_types), daemon=True).start()
        return self.get_job(job_id)

    def _run_rq2_benchmark_job(self, job_id: str, paper_run_id: str, dataset_id: str, dataset_version: str, scientific_task: str, model_types: list[str] | None) -> None:
        job_dir = self._job_dir(job_id)
        self._write(job_dir, "running", job_type="RQ2_BENCHMARK", paper_run_id=paper_run_id, stage="starting", overall_progress=0.0, message="Starting RQ2 validation benchmark")
        try:
            def progress(stage: str, fraction: float, message: str) -> None:
                self._write(job_dir, "running", job_type="RQ2_BENCHMARK", paper_run_id=paper_run_id, stage=stage, overall_progress=fraction, message=str(message))

            result = run_rq2_benchmark(
                studio_repository=self._studio_repository, sci_repository=self.repository, paper_run_id=paper_run_id,
                dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=scientific_task, model_types=model_types, progress=progress,
            )
            message = result["stopped_reason"] or (f"overall READY -- {len(result['rq2_report']['branches'])} branch(es)" if result["rq2_report"] else "done")
            self._write(job_dir, "completed", job_type="RQ2_BENCHMARK", paper_run_id=paper_run_id, stage="done", overall_progress=1.0, message=message, result=result)
        except Exception as error:  # noqa: BLE001 -- includes Rq2BenchmarkError (no studio repository configured)
            self._write(job_dir, "failed", job_type="RQ2_BENCHMARK", paper_run_id=paper_run_id, error=str(error))
        finally:
            self._cancel_flags.pop(job_id, None)

    def start_rq1_acquisition_dependence_job(
        self, *, paper_run_id: str, dataset_id: str, dataset_version: str, recommended_training_run_id: str, scientific_task: str,
    ) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-scientific-results-job-v1", "job_id": job_id, "job_type": "RQ1_ACQUISITION_DEPENDENCE",
            "paper_run_id": paper_run_id, "dataset_id": dataset_id, "dataset_version": dataset_version,
            "state": "queued", "stage": None, "overall_progress": 0.0, "message": None, "warnings": [],
            "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(
            target=self._run_rq1_acquisition_dependence_job,
            args=(job_id, paper_run_id, dataset_id, dataset_version, recommended_training_run_id, scientific_task), daemon=True,
        ).start()
        return self.get_job(job_id)

    def _run_rq1_acquisition_dependence_job(
        self, job_id: str, paper_run_id: str, dataset_id: str, dataset_version: str, recommended_training_run_id: str, scientific_task: str,
    ) -> None:
        job_dir = self._job_dir(job_id)
        self._write(job_dir, "running", job_type="RQ1_ACQUISITION_DEPENDENCE", paper_run_id=paper_run_id, stage="starting", overall_progress=0.0, message="Starting RQ1 acquisition-dependence diagnostic")
        try:
            def progress(stage: str, fraction: float, message: str) -> None:
                self._write(job_dir, "running", job_type="RQ1_ACQUISITION_DEPENDENCE", paper_run_id=paper_run_id, stage=stage, overall_progress=fraction, message=str(message))

            result = run_rq1_acquisition_dependence(
                studio_repository=self._studio_repository, sci_repository=self.repository, paper_run_id=paper_run_id,
                dataset_id=dataset_id, dataset_version=dataset_version, recommended_training_run_id=recommended_training_run_id,
                scientific_task=scientific_task, progress=progress,
            )
            self._write(job_dir, "completed", job_type="RQ1_ACQUISITION_DEPENDENCE", paper_run_id=paper_run_id, stage="done", overall_progress=1.0, message="RQ1 report persisted", result=result)
        except Exception as error:  # noqa: BLE001 -- includes Rq1RunnerError (no studio repository configured)
            self._write(job_dir, "failed", job_type="RQ1_ACQUISITION_DEPENDENCE", paper_run_id=paper_run_id, error=str(error))
        finally:
            self._cancel_flags.pop(job_id, None)

    # ------------------------------------------------------------------
    # Scientific Dashboard Closure audit finding (2026-08-11): RQ3's pair
    # CONSTRUCTION was real, but the real FRR_pre/FRR_post/D estimand had
    # zero real callers -- OfflineInferenceService.run_decision_windows()
    # (the frozen primary-branch bundle + preprocessing + decision-window
    # rule + calibrated threshold) was real and callable end-to-end, this
    # job is the missing real caller. Same real bundle_root/
    # capture_iq_paths_for() StudioRepository.run_inference() already uses
    # -- never a second bundle-loading path.
    # ------------------------------------------------------------------

    def start_rq3_frr_analysis_job(self, *, paper_run_id: str, bundle_id: str | None = None) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-scientific-results-job-v1", "job_id": job_id, "job_type": "RQ3_FRR_ANALYSIS",
            "paper_run_id": paper_run_id, "state": "queued", "stage": None, "overall_progress": 0.0, "message": None,
            "warnings": [], "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_rq3_frr_analysis_job, args=(job_id, paper_run_id, bundle_id), daemon=True).start()
        return self.get_job(job_id)

    def _run_rq3_frr_analysis_job(self, job_id: str, paper_run_id: str, bundle_id: str | None) -> None:
        job_dir = self._job_dir(job_id)
        self._write(job_dir, "running", job_type="RQ3_FRR_ANALYSIS", paper_run_id=paper_run_id, stage="starting", overall_progress=0.0, message="Starting RQ3 FRR pre/post analysis")
        try:
            if self._studio_repository is None:
                raise ValueError("NO_STUDIO_REPOSITORY_CONFIGURED:RQ3 FRR analysis needs a real StudioRepository to load bundles/IQ")
            from app.modules.ble_rffi_studio.inference.offline_inference import OfflineInferenceService  # deferred: ble_rffi_studio import from this package (fixed 2026-08-17: `..inference` was resolving inside ble_scientific_results, a package with no inference/ subpackage -- this import had never actually succeeded)

            self._write(job_dir, "running", job_type="RQ3_FRR_ANALYSIS", paper_run_id=paper_run_id, stage="resolving_bundle_and_iq", overall_progress=0.2, message="Resolving frozen bundle and real capture IQ paths")
            all_captures = self.repository._load_all_captures()
            capture_iq_paths = self._studio_repository.capture_iq_paths_for([c.capture_id for c in all_captures])
            offline_inference_service = OfflineInferenceService(self._studio_repository.bundle_builder.root, capture_iq_paths)

            self._write(job_dir, "running", job_type="RQ3_FRR_ANALYSIS", paper_run_id=paper_run_id, stage="scoring_pairs", overall_progress=0.5, message="Scoring PRE/POST decision windows with the frozen bundle")
            result = self.repository.run_rq3_frr_analysis(paper_run_id=paper_run_id, offline_inference_service=offline_inference_service, bundle_id=bundle_id)
            message = f"{len(result.get('rq3_pairs', []))} real PrePostPair(s) evaluated, bundle_id={result.get('rq3_bundle_id')}"
            self._write(job_dir, "completed", job_type="RQ3_FRR_ANALYSIS", paper_run_id=paper_run_id, stage="done", overall_progress=1.0, message=message, result=result)
        except Exception as error:  # noqa: BLE001 -- includes missing StudioRepository/no frozen PRIMARY branch
            self._write(job_dir, "failed", job_type="RQ3_FRR_ANALYSIS", paper_run_id=paper_run_id, error=str(error))
        finally:
            self._cancel_flags.pop(job_id, None)

    # ------------------------------------------------------------------
    # Coverage audit finding (2026-08-12): real decision records already
    # carry everything coverage needs -- nothing aggregated them by
    # evaluation_domain/branch/physical_unit. Same real bundle-loading path
    # as RQ3_FRR_ANALYSIS, just driven over EVERY frozen RQ2 branch.
    # ------------------------------------------------------------------

    def start_coverage_analysis_job(self, *, paper_run_id: str, bundle_ids: dict[str, str] | None = None, evaluate_window_level: bool = False) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-scientific-results-job-v1", "job_id": job_id, "job_type": "COVERAGE_ANALYSIS",
            "paper_run_id": paper_run_id, "state": "queued", "stage": None, "overall_progress": 0.0, "message": None,
            "warnings": [], "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_coverage_analysis_job, args=(job_id, paper_run_id, bundle_ids, evaluate_window_level), daemon=True).start()
        return self.get_job(job_id)

    def _run_coverage_analysis_job(self, job_id: str, paper_run_id: str, bundle_ids: dict[str, str] | None, evaluate_window_level: bool = False) -> None:
        job_dir = self._job_dir(job_id)
        self._write(job_dir, "running", job_type="COVERAGE_ANALYSIS", paper_run_id=paper_run_id, stage="starting", overall_progress=0.0, message="Starting coverage analysis")
        try:
            if self._studio_repository is None:
                raise ValueError("NO_STUDIO_REPOSITORY_CONFIGURED:Coverage analysis needs a real StudioRepository to load bundles/IQ")
            from app.modules.ble_rffi_studio.inference.offline_inference import OfflineInferenceService  # deferred: ble_rffi_studio import from this package (fixed 2026-08-17: `..inference` was resolving inside ble_scientific_results, a package with no inference/ subpackage -- this import had never actually succeeded)

            self._write(job_dir, "running", job_type="COVERAGE_ANALYSIS", paper_run_id=paper_run_id, stage="resolving_bundles_and_iq", overall_progress=0.2, message="Resolving frozen RQ2 branch bundles and real capture IQ paths")
            all_captures = self.repository._load_all_captures()
            capture_iq_paths = self._studio_repository.capture_iq_paths_for([c.capture_id for c in all_captures])
            offline_inference_service = OfflineInferenceService(self._studio_repository.bundle_builder.root, capture_iq_paths)

            self._write(job_dir, "running", job_type="COVERAGE_ANALYSIS", paper_run_id=paper_run_id, stage="scoring_windows", overall_progress=0.5, message="Scoring decision windows per branch")
            result = self.repository.run_coverage_analysis(
                paper_run_id=paper_run_id, offline_inference_service=offline_inference_service, bundle_ids=bundle_ids,
                evaluate_window_level=evaluate_window_level,
            )
            overall = result.get("overall") or {}
            message = f"coverage={overall.get('coverage')} across {len(result.get('bundle_ids', {}))} branch(es)"
            self._write(job_dir, "completed", job_type="COVERAGE_ANALYSIS", paper_run_id=paper_run_id, stage="done", overall_progress=1.0, message=message, result=result)
        except Exception as error:  # noqa: BLE001 -- includes missing StudioRepository/no frozen RQ2 branches
            self._write(job_dir, "failed", job_type="COVERAGE_ANALYSIS", paper_run_id=paper_run_id, error=str(error))
        finally:
            self._cancel_flags.pop(job_id, None)

    # ------------------------------------------------------------------
    # Sensitivity closure (2026-08-12): consolidates enrolled-population
    # class-exclusion metric sensitivity (already real; renamed 2026-08-22
    # from its original, overstated "LODO" name -- the model is never
    # retrained without the excluded class), offset-retaining preprocessing
    # (real, previously uncalled), and RQ2's own seed_variability (reused,
    # never recomputed) into one report.
    # ------------------------------------------------------------------

    def start_sensitivity_analysis_job(self, *, paper_run_id: str) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-scientific-results-job-v1", "job_id": job_id, "job_type": "SENSITIVITY_ANALYSIS",
            "paper_run_id": paper_run_id, "state": "queued", "stage": None, "overall_progress": 0.0, "message": None,
            "warnings": [], "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_sensitivity_analysis_job, args=(job_id, paper_run_id), daemon=True).start()
        return self.get_job(job_id)

    def _run_sensitivity_analysis_job(self, job_id: str, paper_run_id: str) -> None:
        job_dir = self._job_dir(job_id)
        self._write(job_dir, "running", job_type="SENSITIVITY_ANALYSIS", paper_run_id=paper_run_id, stage="starting", overall_progress=0.0, message="Starting sensitivity analysis (class-exclusion + offset-retaining)")
        try:
            def progress(stage: str, fraction: float, message: str) -> None:
                self._write(job_dir, "running", job_type="SENSITIVITY_ANALYSIS", paper_run_id=paper_run_id, stage=stage, overall_progress=fraction, message=str(message))

            result = self.repository.run_sensitivity_analysis(paper_run_id=paper_run_id, studio_repository=self._studio_repository)
            offset = result.get("offset_retaining") or {}
            message = f"class-exclusion sensitivity {len(result.get('enrolled_population_class_exclusion_sensitivity', {}).get('rows', []))} unit(s), offset-retaining delta_vs_primary={offset.get('delta_vs_primary')}"
            self._write(job_dir, "completed", job_type="SENSITIVITY_ANALYSIS", paper_run_id=paper_run_id, stage="done", overall_progress=1.0, message=message, result=result)
        except Exception as error:  # noqa: BLE001 -- includes missing StudioRepository/no frozen PRIMARY branch
            self._write(job_dir, "failed", job_type="SENSITIVITY_ANALYSIS", paper_run_id=paper_run_id, error=str(error))
        finally:
            self._cancel_flags.pop(job_id, None)

    # ------------------------------------------------------------------
    # RQ4 region-specific fitting closure (2026-08-12): rq4_primary_analysis=
    # REGION_SPECIFIC_FITTING_AND_EVALUATION. Same real bundle-loading path
    # as RQ3_FRR_ANALYSIS/COVERAGE_ANALYSIS for FULL_BURST; ADVA_EXCLUDED/
    # PRE_PDU are real-trained inside run_rq4_region_analysis itself via
    # self._studio_repository.train_region_specific_variant (never a second
    # training path here).
    # ------------------------------------------------------------------

    def start_rq4_region_analysis_job(self, *, paper_run_id: str, full_burst_bundle_id: str | None = None) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-scientific-results-job-v1", "job_id": job_id, "job_type": "RQ4_REGION_ANALYSIS",
            "paper_run_id": paper_run_id, "state": "queued", "stage": None, "overall_progress": 0.0, "message": None,
            "warnings": [], "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_rq4_region_analysis_job, args=(job_id, paper_run_id, full_burst_bundle_id), daemon=True).start()
        return self.get_job(job_id)

    def _run_rq4_region_analysis_job(self, job_id: str, paper_run_id: str, full_burst_bundle_id: str | None) -> None:
        job_dir = self._job_dir(job_id)
        self._write(job_dir, "running", job_type="RQ4_REGION_ANALYSIS", paper_run_id=paper_run_id, stage="starting", overall_progress=0.0, message="Starting RQ4 region-specific fitting analysis")
        try:
            if self._studio_repository is None:
                raise ValueError("NO_STUDIO_REPOSITORY_CONFIGURED:RQ4 region analysis needs a real StudioRepository to fit ADVA_EXCLUDED/PRE_PDU variants and load bundles/IQ")
            from app.modules.ble_rffi_studio.inference.offline_inference import OfflineInferenceService  # deferred: ble_rffi_studio import from this package (fixed 2026-08-17: `..inference` was resolving inside ble_scientific_results, a package with no inference/ subpackage -- this import had never actually succeeded)

            self._write(job_dir, "running", job_type="RQ4_REGION_ANALYSIS", paper_run_id=paper_run_id, stage="resolving_full_burst_bundle_and_iq", overall_progress=0.1, message="Resolving FULL_BURST bundle and real capture IQ paths")
            all_captures = self.repository._load_all_captures()
            capture_iq_paths = self._studio_repository.capture_iq_paths_for([c.capture_id for c in all_captures])
            offline_inference_service = OfflineInferenceService(self._studio_repository.bundle_builder.root, capture_iq_paths)

            self._write(job_dir, "running", job_type="RQ4_REGION_ANALYSIS", paper_run_id=paper_run_id, stage="fitting_adva_excluded_and_pre_pdu", overall_progress=0.3, message="Fitting ADVA_EXCLUDED/PRE_PDU region-specific variants (same frozen configuration, only the analytical_region changes)")
            result = self.repository.run_rq4_region_analysis(
                paper_run_id=paper_run_id, offline_inference_service=offline_inference_service, studio_repository=self._studio_repository,
                full_burst_bundle_id=full_burst_bundle_id,
            )
            report = result.get("rq4_region_report") or {}
            message = f"{len(report.get('matched_region_blocks', []))} matched region block(s), primary contrast n={report.get('primary_contrast', {}).get('n_matched_blocks')}"
            self._write(job_dir, "completed", job_type="RQ4_REGION_ANALYSIS", paper_run_id=paper_run_id, stage="done", overall_progress=1.0, message=message, result=result)
        except Exception as error:  # noqa: BLE001 -- includes missing StudioRepository/no frozen PRIMARY branch/no matched blocks
            self._write(job_dir, "failed", job_type="RQ4_REGION_ANALYSIS", paper_run_id=paper_run_id, error=str(error))
        finally:
            self._cancel_flags.pop(job_id, None)

    # ------------------------------------------------------------------
    # Fast-closure pass (2026-08-12), Phase 14 (S1): compute_channel_
    # transport_report was real and tested but had no real caller -- same
    # real bundle-loading path as RQ3_FRR_ANALYSIS/COVERAGE_ANALYSIS.
    # ------------------------------------------------------------------

    def start_channel_transport_analysis_job(self, *, paper_run_id: str, bundle_id: str | None = None) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-scientific-results-job-v1", "job_id": job_id, "job_type": "CHANNEL_TRANSPORT_ANALYSIS",
            "paper_run_id": paper_run_id, "state": "queued", "stage": None, "overall_progress": 0.0, "message": None,
            "warnings": [], "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_channel_transport_analysis_job, args=(job_id, paper_run_id, bundle_id), daemon=True).start()
        return self.get_job(job_id)

    def _run_channel_transport_analysis_job(self, job_id: str, paper_run_id: str, bundle_id: str | None) -> None:
        job_dir = self._job_dir(job_id)
        self._write(job_dir, "running", job_type="CHANNEL_TRANSPORT_ANALYSIS", paper_run_id=paper_run_id, stage="starting", overall_progress=0.0, message="Starting S1 channel transport analysis")
        try:
            if self._studio_repository is None:
                raise ValueError("NO_STUDIO_REPOSITORY_CONFIGURED:S1 channel transport analysis needs a real StudioRepository to load bundles/IQ")
            from app.modules.ble_rffi_studio.inference.offline_inference import OfflineInferenceService  # deferred: ble_rffi_studio import from this package (fixed 2026-08-17: `..inference` was resolving inside ble_scientific_results, a package with no inference/ subpackage -- this import had never actually succeeded)

            self._write(job_dir, "running", job_type="CHANNEL_TRANSPORT_ANALYSIS", paper_run_id=paper_run_id, stage="resolving_bundle_and_iq", overall_progress=0.2, message="Resolving frozen PRIMARY bundle and real capture IQ paths")
            all_captures = self.repository._load_all_captures()
            capture_iq_paths = self._studio_repository.capture_iq_paths_for([c.capture_id for c in all_captures])
            offline_inference_service = OfflineInferenceService(self._studio_repository.bundle_builder.root, capture_iq_paths)

            self._write(job_dir, "running", job_type="CHANNEL_TRANSPORT_ANALYSIS", paper_run_id=paper_run_id, stage="scoring_by_channel", overall_progress=0.5, message="Scoring every real capture's examples with the frozen bundle, grouped by channel")
            report = self.repository.run_channel_transport_analysis(paper_run_id=paper_run_id, offline_inference_service=offline_inference_service, bundle_id=bundle_id)
            message = f"{len(report.get('per_channel', []))} channel(s) scored"
            self._write(job_dir, "completed", job_type="CHANNEL_TRANSPORT_ANALYSIS", paper_run_id=paper_run_id, stage="done", overall_progress=1.0, message=message, result=report)
        except Exception as error:  # noqa: BLE001 -- includes missing StudioRepository/no frozen PRIMARY branch/no real examples
            self._write(job_dir, "failed", job_type="CHANNEL_TRANSPORT_ANALYSIS", paper_run_id=paper_run_id, error=str(error))
        finally:
            self._cancel_flags.pop(job_id, None)

    # ------------------------------------------------------------------
    # Fast-closure pass (2026-08-12), Phase 15 (S2): wraps compute_offline_
    # nearlive_report as a real, callable job -- never invents a near-live
    # prediction source. With no real predictions supplied yet, this
    # honestly persists a NO_DATA/NOT_MEASURED report, exactly the existing
    # behavior.
    # ------------------------------------------------------------------

    def start_offline_nearlive_analysis_job(self, *, paper_run_id: str) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-scientific-results-job-v1", "job_id": job_id, "job_type": "OFFLINE_NEARLIVE_ANALYSIS",
            "paper_run_id": paper_run_id, "state": "queued", "stage": None, "overall_progress": 0.0, "message": None,
            "warnings": [], "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_offline_nearlive_analysis_job, args=(job_id, paper_run_id), daemon=True).start()
        return self.get_job(job_id)

    def _run_offline_nearlive_analysis_job(self, job_id: str, paper_run_id: str) -> None:
        job_dir = self._job_dir(job_id)
        self._write(job_dir, "running", job_type="OFFLINE_NEARLIVE_ANALYSIS", paper_run_id=paper_run_id, stage="starting", overall_progress=0.0, message="Starting S2 offline/near-live analysis")
        try:
            report = self.repository.run_offline_nearlive_analysis(paper_run_id=paper_run_id)
            message = f"pairing_status={report.get('pairing_status')}"
            self._write(job_dir, "completed", job_type="OFFLINE_NEARLIVE_ANALYSIS", paper_run_id=paper_run_id, stage="done", overall_progress=1.0, message=message, result=report)
        except Exception as error:  # noqa: BLE001
            self._write(job_dir, "failed", job_type="OFFLINE_NEARLIVE_ANALYSIS", paper_run_id=paper_run_id, error=str(error))
        finally:
            self._cancel_flags.pop(job_id, None)

    # ------------------------------------------------------------------
    # Fast-closure pass (2026-08-12), Phase 13: run_confirmatory_future_
    # analysis already existed as the single real, gate-protected
    # CONFIRMATORY_FUTURE entrypoint (protocol-freeze close-out, 2026-08-10)
    # but had no route to trigger it -- only a read-only GET. This job is
    # exactly that missing trigger. Nothing here recalibrates, re-selects a
    # model, or touches thresholds/NI/hypotheses -- it only calls the
    # untouched engine with the caller's already-real inputs.
    # ------------------------------------------------------------------

    def start_confirmatory_future_analysis_job(
        self, *, paper_run_id: str, protocol_id: str, dataset_id: str, dataset_version: str, bundle_id: str,
        declared_contract_sha256: str | None = None, stats_kwargs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-scientific-results-job-v1", "job_id": job_id, "job_type": "CONFIRMATORY_FUTURE_ANALYSIS",
            "paper_run_id": paper_run_id, "state": "queued", "stage": None, "overall_progress": 0.0, "message": None,
            "warnings": [], "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(
            target=self._run_confirmatory_future_analysis_job,
            args=(job_id, paper_run_id, protocol_id, dataset_id, dataset_version, bundle_id, declared_contract_sha256, stats_kwargs or {}),
            daemon=True,
        ).start()
        return self.get_job(job_id)

    def _run_confirmatory_future_analysis_job(
        self, job_id: str, paper_run_id: str, protocol_id: str, dataset_id: str, dataset_version: str,
        bundle_id: str, declared_contract_sha256: str | None, stats_kwargs: dict[str, Any],
    ) -> None:
        job_dir = self._job_dir(job_id)
        self._write(job_dir, "running", job_type="CONFIRMATORY_FUTURE_ANALYSIS", paper_run_id=paper_run_id, stage="starting", overall_progress=0.0, message="Starting confirmatory FUTURE analysis")
        try:
            if self._studio_repository is None:
                raise ValueError("NO_STUDIO_REPOSITORY_CONFIGURED:confirmatory FUTURE analysis needs a real StudioRepository to resolve bundle confirmatory-eligibility")
            self._write(job_dir, "running", job_type="CONFIRMATORY_FUTURE_ANALYSIS", paper_run_id=paper_run_id, stage="checking_gates", overall_progress=0.3, message="Checking protocol freeze / FUTURE_TEST holdout / bundle confirmatory-eligibility gates")
            bundle = self._studio_repository.get_bundle(bundle_id)
            if bundle is None:
                raise ValueError(f"BUNDLE_NOT_FOUND:{bundle_id}")

            self._write(job_dir, "running", job_type="CONFIRMATORY_FUTURE_ANALYSIS", paper_run_id=paper_run_id, stage="running_confirmatory_engine", overall_progress=0.6, message="Running the untouched 11-method confirmatory statistical engine over FUTURE-scoped data")
            report = self.repository.run_confirmatory_future_analysis(
                paper_run_id=paper_run_id, protocol_id=protocol_id, dataset_id=dataset_id, dataset_version=dataset_version,
                bundle_confirmatory_eligible=bundle.confirmatory_eligible, declared_contract_sha256=declared_contract_sha256,
                **stats_kwargs,
            )
            self._write(job_dir, "completed", job_type="CONFIRMATORY_FUTURE_ANALYSIS", paper_run_id=paper_run_id, stage="done", overall_progress=1.0, message="Confirmatory FUTURE analysis report persisted", result=report)
        except Exception as error:  # noqa: BLE001 -- includes any of the 5 non-bypassable gates failing
            self._write(job_dir, "failed", job_type="CONFIRMATORY_FUTURE_ANALYSIS", paper_run_id=paper_run_id, error=str(error))
        finally:
            self._cancel_flags.pop(job_id, None)
