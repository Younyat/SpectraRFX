"""Background jobs for the two Studio operations slow enough to need
progress reporting: Evidence Stage build (hundreds of packets) and model
training. Same job.json/background-thread pattern as BleCaptureJobManager
and BlePacketAnalysisJobManager, so the frontend's existing operationTelemetry
integration works unchanged.

Unlike BLE capture jobs, these never touch the B200 or any other exclusive
hardware resource (the IQ is already captured), so -- unlike those managers --
multiple Studio jobs are allowed to run concurrently; there is no shared
resource here to serialize.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.infrastructure.ble.capture.ble_capture_metadata import atomic_json

from ..contracts import TrainingRun
from ..module_logging import build_module_logger
from .studio_repository import StudioRepository

TERMINAL = {"completed", "failed", "cancelled"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class StudioJobManager:
    def __init__(self, repository: StudioRepository, jobs_root: Path) -> None:
        self.repository = repository
        self.jobs_root = jobs_root
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        # jobs_root is always <module_root>/jobs -- the log file lives as a
        # sibling of jobs/captures/evidence/etc under that same module root.
        self.logger = build_module_logger(jobs_root.parent)

    def _job_dir(self, job_id: str) -> Path:
        if not job_id.startswith("BLE-RFFI-STUDIO-JOB-") or any(part in job_id for part in ("/", "\\", "..")):
            raise ValueError("INVALID_JOB_ID")
        return self.jobs_root / job_id

    def _new_job_id(self) -> str:
        return "BLE-RFFI-STUDIO-JOB-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]

    def _write(self, job_dir: Path, state: str, **fields: Any) -> None:
        path = job_dir / "job.json"
        previous = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        merged = {**previous, **fields, "state": state, "updated_at": utc_now()}
        atomic_json(path, merged)
        # Every progress update from every job type funnels through this one
        # method -- logging here, rather than in each _run_*_job, covers all
        # of them (campaign session, capture-only, replay+evidence, evidence
        # build, training, prepare-and-train) from a single choke point.
        job_id = merged.get("job_id") or job_dir.name
        job_type = merged.get("job_type", "UNKNOWN")
        if state == "failed":
            self.logger.error("[%s] job=%s state=%s error=%s", job_type, job_id, state, merged.get("error"))
        else:
            self.logger.info(
                "[%s] job=%s state=%s phase=%s progress=%s message=%s",
                job_type, job_id, state, merged.get("phase"), merged.get("overall_progress"), merged.get("message"),
            )

    def get_job(self, job_id: str) -> dict[str, Any]:
        path = self._job_dir(job_id) / "job.json"
        if not path.is_file():
            raise FileNotFoundError("STUDIO_JOB_NOT_FOUND")
        return json.loads(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Evidence Build
    # ------------------------------------------------------------------

    def start_evidence_job(self, *, capture_id: str, project_id: str, ble_channel: int, replay_run_id: str | None = None) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-rffi-studio-job-v1", "job_id": job_id, "job_type": "EVIDENCE_BUILD",
            "capture_id": capture_id, "state": "queued", "phase": None, "phase_progress": 0.0,
            "overall_progress": 0.0, "message": None, "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_evidence_job, args=(job_id, capture_id, project_id, ble_channel, replay_run_id), daemon=True).start()
        return self.get_job(job_id)

    def _run_evidence_job(self, job_id: str, capture_id: str, project_id: str, ble_channel: int, replay_run_id: str | None) -> None:
        job_dir = self._job_dir(job_id)

        def progress(phase: str, phase_progress: float, message: str) -> None:
            self._write(job_dir, "running", phase=phase, phase_progress=phase_progress, overall_progress=round(phase_progress, 4), message=message)

        try:
            capture = self.repository.get_capture(capture_id)
            if capture is None:
                raise FileNotFoundError(f"CAPTURE_NOT_BUILT_YET:{capture_id}")
            summary = self.repository.build_evidence(capture=capture, project_id=project_id, ble_channel=ble_channel, replay_run_id=replay_run_id, progress=progress)
            self._write(job_dir, "completed", overall_progress=1.0, phase="COMPLETED", result_summary=summary)
        except Exception as error:
            # Full traceback goes to the log file (not just the short
            # str(error) job.json stores) -- that's the whole point of a
            # dedicated log: finding out WHERE a failure happened, not just
            # that it did.
            self.logger.exception("job %s raised an unhandled exception", job_id)
            self._write(job_dir, "failed", error=f"{type(error).__name__}: {error}")

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def start_training_job(self, *, training_run: TrainingRun) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-rffi-studio-job-v1", "job_id": job_id, "job_type": "TRAINING_RUN",
            "training_run_id": training_run.training_run_id, "state": "queued", "phase": None, "phase_progress": 0.0,
            "overall_progress": 0.0, "message": None, "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_training_job, args=(job_id, training_run), daemon=True).start()
        return self.get_job(job_id)

    def _run_training_job(self, job_id: str, training_run: TrainingRun) -> None:
        job_dir = self._job_dir(job_id)

        def progress(phase: str, phase_progress: float, message: str) -> None:
            self._write(job_dir, "running", phase=phase, phase_progress=phase_progress, overall_progress=round(phase_progress, 4), message=message)

        try:
            completed_run = self.repository.run_training(training_run=training_run, progress=progress)
            self._write(job_dir, "completed", overall_progress=1.0, phase="COMPLETED", training_run_id=completed_run.training_run_id)
        except Exception as error:
            # Full traceback goes to the log file (not just the short
            # str(error) job.json stores) -- that's the whole point of a
            # dedicated log: finding out WHERE a failure happened, not just
            # that it did.
            self.logger.exception("job %s raised an unhandled exception", job_id)
            self._write(job_dir, "failed", error=f"{type(error).__name__}: {error}")

    # ------------------------------------------------------------------
    # Guided orchestration: "Prepare dataset and train"
    # ------------------------------------------------------------------

    def start_prepare_and_train_job(self, **kwargs: Any) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-rffi-studio-job-v1", "job_id": job_id, "job_type": "PREPARE_AND_TRAIN",
            "state": "queued", "phase": None, "phase_progress": 0.0, "overall_progress": 0.0,
            "message": None, "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_prepare_and_train_job, args=(job_id,), kwargs=kwargs, daemon=True).start()
        return self.get_job(job_id)

    def _run_prepare_and_train_job(self, job_id: str, **kwargs: Any) -> None:
        job_dir = self._job_dir(job_id)
        # Popped, never forwarded to prepare_and_train() itself (which has no
        # such parameter) -- auto-train's one-click automation: every
        # candidate this run trains gets exported+approved automatically
        # instead of leaving that as a separate manual step. See
        # StudioRepository.export_and_approve_all_candidates().
        auto_export_physical_unit_id = kwargs.pop("auto_export_physical_unit_id", None)

        def progress(phase: str, phase_progress: float, message: str) -> None:
            self._write(job_dir, "running", phase=phase, phase_progress=phase_progress, overall_progress=round(phase_progress, 4), message=message)

        try:
            result = self.repository.prepare_and_train(progress=progress, **kwargs)
            if auto_export_physical_unit_id and result.get("split") is not None and getattr(result["split"], "split_status", None) == "READY":
                progress("PHASE_10", 0.95, "Exportando y aprobando todos los modelos candidatos")
                result["exported_bundles"] = self.repository.export_and_approve_all_candidates(
                    physical_unit_id=auto_export_physical_unit_id, prepare_and_train_result=result,
                )
            self._write(job_dir, "completed", overall_progress=1.0, phase="COMPLETED", result_summary=self._summarize_result(result))
        except Exception as error:
            # Full traceback goes to the log file (not just the short
            # str(error) job.json stores) -- that's the whole point of a
            # dedicated log: finding out WHERE a failure happened, not just
            # that it did.
            self.logger.exception("job %s raised an unhandled exception", job_id)
            self._write(job_dir, "failed", error=f"{type(error).__name__}: {error}")

    # ------------------------------------------------------------------
    # Device Scrubbing: one-click "detect contaminated backgrounds for this
    # always-on device, scrub+verify each, train+export original vs scrubbed"
    # -- see StudioRepository.scrub_device_from_background().
    # ------------------------------------------------------------------

    def start_device_scrub_job(self, *, physical_unit_id: str) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-rffi-studio-job-v1", "job_id": job_id, "job_type": "DEVICE_SCRUB",
            "state": "queued", "phase": None, "phase_progress": 0.0, "overall_progress": 0.0,
            "message": None, "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_device_scrub_job, args=(job_id, physical_unit_id), daemon=True).start()
        return self.get_job(job_id)

    def _run_device_scrub_job(self, job_id: str, physical_unit_id: str) -> None:
        job_dir = self._job_dir(job_id)

        def progress(phase: str, phase_progress: float, message: str) -> None:
            self._write(job_dir, "running", phase=phase, phase_progress=phase_progress, overall_progress=round(phase_progress, 4), message=message)

        try:
            result = self.repository.scrub_device_from_background(physical_unit_id=physical_unit_id, progress=progress)
            self._write(job_dir, "completed", overall_progress=1.0, phase="COMPLETED", result_summary=result)
        except Exception as error:
            self.logger.exception("job %s raised an unhandled exception", job_id)
            self._write(job_dir, "failed", error=f"{type(error).__name__}: {error}")

    # ------------------------------------------------------------------
    # Training Service: operator picks an ALREADY-frozen, already-labeled
    # dataset and exactly which model_type candidates to train against it --
    # see StudioRepository.train_selected_models(). Every candidate trained
    # gets exported+approved (export_and_approve_all_candidates()), same as
    # auto-train and device scrubbing already do.
    # ------------------------------------------------------------------

    def start_train_selected_models_job(
        self, *, dataset_keys: list[tuple[str, str]], model_types: list[str], background_dataset_key: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-rffi-studio-job-v1", "job_id": job_id, "job_type": "TRAIN_SELECTED_MODELS",
            "state": "queued", "phase": None, "phase_progress": 0.0, "overall_progress": 0.0,
            "message": None, "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_train_selected_models_job, args=(job_id, dataset_keys, model_types, background_dataset_key), daemon=True).start()
        return self.get_job(job_id)

    def _run_train_selected_models_job(
        self, job_id: str, dataset_keys: list[tuple[str, str]], model_types: list[str], background_dataset_key: tuple[str, str] | None,
    ) -> None:
        job_dir = self._job_dir(job_id)

        def progress(phase: str, phase_progress: float, message: str) -> None:
            self._write(job_dir, "running", phase=phase, phase_progress=phase_progress, overall_progress=round(phase_progress, 4), message=message)

        try:
            if len(dataset_keys) >= 2:
                # 2+ datasets selected: the operator wants ONE model that
                # tells apart WHICH of several devices is present -- combine
                # into a multi-class dataset and train SAME_MODEL_UNIT_
                # IDENTIFICATION, never a binary "any of these" family (see
                # combine_datasets_for_identification()'s docstring for why).
                # background_dataset_key, when given, replaces every device's
                # own (often much thinner) background pool with ONE shared,
                # verified source instead of pooling all of them together.
                progress("COMBINE", 0.0, f"Combinando {len(dataset_keys)} datasets para identificacion")
                combined = self.repository.combine_datasets_for_identification(dataset_keys, background_dataset_key)
                dataset_id, dataset_version = combined.dataset_id, combined.dataset_version
                scientific_task = "SAME_MODEL_UNIT_IDENTIFICATION"
            else:
                dataset_id, dataset_version = dataset_keys[0]
                # A single selected dataset is normally trained as
                # TARGET_VS_BACKGROUND -- EXCEPT if it IS itself a dataset
                # combine_datasets_for_identification() already produced
                # (dataset_id prefix "IDENTITY-", the one naming scheme this
                # job manager controls end to end). Re-selecting one of
                # those later as a lone entry must still train
                # SAME_MODEL_UNIT_IDENTIFICATION -- treating a 5-device
                # identity dataset as a binary "any of these" TARGET_VS_
                # BACKGROUND family (a real, observed failure: it silently
                # trained the wrong task against a much larger multi-device
                # example pool than TARGET_VS_BACKGROUND's own splitting
                # logic was ever exercised against, and hung for 8+ minutes
                # rather than the ~2 minutes the correct task takes).
                scientific_task = "SAME_MODEL_UNIT_IDENTIFICATION" if dataset_id.startswith("IDENTITY-") else "TARGET_VS_BACKGROUND"

            result = self.repository.train_selected_models(
                dataset_id=dataset_id, dataset_version=dataset_version, model_types=model_types,
                scientific_task=scientific_task, progress=progress,
            )
            if result.get("split") is not None and getattr(result["split"], "split_status", None) == "READY" and result.get("trained_models"):
                progress("EXPORT", 0.95, "Exportando y aprobando los modelos entrenados")
                result["exported_bundles"] = self.repository.export_and_approve_all_candidates(
                    physical_unit_id=result["run_name"], prepare_and_train_result=result,
                )
            self._write(job_dir, "completed", overall_progress=1.0, phase="COMPLETED", result_summary=self._summarize_result(result))
        except Exception as error:
            self.logger.exception("job %s raised an unhandled exception", job_id)
            self._write(job_dir, "failed", error=f"{type(error).__name__}: {error}")

    # ------------------------------------------------------------------
    # Real capture campaign session (B200 + native scan)
    # ------------------------------------------------------------------

    def start_campaign_session_job(self, **kwargs: Any) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-rffi-studio-job-v1", "job_id": job_id, "job_type": "CAMPAIGN_SESSION",
            "state": "queued", "phase": None, "phase_progress": 0.0, "overall_progress": 0.0,
            "message": None, "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_campaign_session_job, args=(job_id,), kwargs=kwargs, daemon=True).start()
        return self.get_job(job_id)

    def _run_campaign_session_job(self, job_id: str, **kwargs: Any) -> None:
        job_dir = self._job_dir(job_id)

        def progress(phase: str, phase_progress: float, message: str) -> None:
            self._write(job_dir, "running", phase=phase, phase_progress=phase_progress, overall_progress=round(phase_progress, 4), message=message)

        try:
            result = self.repository.run_campaign_session(progress=progress, **kwargs)
            self._write(job_dir, "completed", overall_progress=1.0, phase="COMPLETED", result_summary=result)
        except Exception as error:
            # Full traceback goes to the log file (not just the short
            # str(error) job.json stores) -- that's the whole point of a
            # dedicated log: finding out WHERE a failure happened, not just
            # that it did.
            self.logger.exception("job %s raised an unhandled exception", job_id)
            self._write(job_dir, "failed", error=f"{type(error).__name__}: {error}")

    # ------------------------------------------------------------------
    # Paper campaign schedule (Study Control Center, phases 04/06/07,
    # 2026-08-11): executes the NEXT planned entry of an already-frozen
    # schedule. Real B200 capture, same reject-out-of-schedule enforcement
    # PaperCampaignRunner already provides -- this job type never bypasses
    # it, only wraps it with progress reporting.
    # ------------------------------------------------------------------

    def start_campaign_schedule_execute_job(self, **kwargs: Any) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-rffi-studio-job-v1", "job_id": job_id, "job_type": "CAMPAIGN_SCHEDULE_EXECUTE",
            "schedule_id": kwargs.get("schedule_id"),
            "state": "queued", "phase": None, "phase_progress": 0.0, "overall_progress": 0.0,
            "message": None, "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_campaign_schedule_execute_job, args=(job_id,), kwargs=kwargs, daemon=True).start()
        return self.get_job(job_id)

    def _run_campaign_schedule_execute_job(self, job_id: str, **kwargs: Any) -> None:
        job_dir = self._job_dir(job_id)

        def progress(phase: str, phase_progress: float, message: str) -> None:
            self._write(job_dir, "running", phase=phase, phase_progress=phase_progress, overall_progress=round(phase_progress, 4), message=message)

        try:
            capture_record = self.repository.execute_next_campaign_schedule_capture(progress=progress, **kwargs)
            self._write(job_dir, "completed", overall_progress=1.0, phase="COMPLETED", result_summary={"capture_id": capture_record.capture_id})
        except Exception as error:
            self.logger.exception("job %s raised an unhandled exception", job_id)
            self._write(job_dir, "failed", error=f"{type(error).__name__}: {error}")

    # ------------------------------------------------------------------
    # Guided capture: probes for a real signal (TARGET_DEVICE_ON) or a clean
    # environment (BACKGROUND_*) with short throwaway B200 captures before
    # launching the real, saved capture -- see CampaignOrchestrator.run_guided_capture_only().
    # ------------------------------------------------------------------

    def start_guided_capture_job(self, **kwargs: Any) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-rffi-studio-job-v1", "job_id": job_id, "job_type": "GUIDED_CAPTURE",
            "state": "queued", "phase": None, "phase_progress": 0.0, "overall_progress": 0.0,
            "message": None, "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_guided_capture_job, args=(job_id,), kwargs=kwargs, daemon=True).start()
        return self.get_job(job_id)

    def _run_guided_capture_job(self, job_id: str, **kwargs: Any) -> None:
        job_dir = self._job_dir(job_id)

        def progress(phase: str, phase_progress: float, message: str) -> None:
            self._write(job_dir, "running", phase=phase, phase_progress=phase_progress, overall_progress=round(phase_progress, 4), message=message)

        try:
            result = self.repository.run_guided_capture(progress=progress, **kwargs)
            self._write(job_dir, "completed", overall_progress=1.0, phase="COMPLETED", result_summary=result)
        except Exception as error:
            self.logger.exception("job %s raised an unhandled exception", job_id)
            self._write(job_dir, "failed", error=f"{type(error).__name__}: {error}")

    # ------------------------------------------------------------------
    # Replay + Evidence for an already-built capture (the slow part,
    # deliberately separable from the real B200 acquisition -- see
    # CampaignOrchestrator.run_replay_and_evidence_for_capture)
    # ------------------------------------------------------------------

    def start_replay_and_evidence_job(self, *, capture_id: str, project_id: str, ble_channel: int, force: bool = False) -> dict[str, Any]:
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=False)
        atomic_json(job_dir / "job.json", {
            "schema_version": "ble-rffi-studio-job-v1", "job_id": job_id, "job_type": "REPLAY_AND_EVIDENCE",
            "capture_id": capture_id, "state": "queued", "phase": None, "phase_progress": 0.0,
            "overall_progress": 0.0, "message": None, "started_at": utc_now(), "updated_at": utc_now(),
        })
        threading.Thread(target=self._run_replay_and_evidence_job, args=(job_id, capture_id, project_id, ble_channel, force), daemon=True).start()
        return self.get_job(job_id)

    def _run_replay_and_evidence_job(self, job_id: str, capture_id: str, project_id: str, ble_channel: int, force: bool) -> None:
        job_dir = self._job_dir(job_id)

        def progress(phase: str, phase_progress: float, message: str) -> None:
            self._write(job_dir, "running", phase=phase, phase_progress=phase_progress, overall_progress=round(phase_progress, 4), message=message)

        try:
            result = self.repository.run_replay_and_evidence(capture_id=capture_id, project_id=project_id, ble_channel=ble_channel, force=force, progress=progress)
            phase = "SKIPPED_ALREADY_PROCESSED" if result.get("skipped") else "COMPLETED"
            self._write(job_dir, "completed", overall_progress=1.0, phase=phase, result_summary=result)
        except Exception as error:
            # Full traceback goes to the log file (not just the short
            # str(error) job.json stores) -- that's the whole point of a
            # dedicated log: finding out WHERE a failure happened, not just
            # that it did.
            self.logger.exception("job %s raised an unhandled exception", job_id)
            self._write(job_dir, "failed", error=f"{type(error).__name__}: {error}")

    def _summarize_result(self, result: dict[str, Any]) -> dict[str, Any]:
        dataset = result.get("dataset")
        split = result.get("split")
        return {
            "stopped_at": result.get("stopped_at"),
            "stopped_reason": result.get("stopped_reason"),
            "dataset_id": getattr(dataset, "dataset_id", None),
            "dataset_version": getattr(dataset, "dataset_version", None),
            "data_origin": getattr(dataset, "data_origin", None),
            "split_status": getattr(split, "split_status", None),
            "feasibility": result.get("feasibility"),
            "trained_models": [{"training_run_id": m["training_run_id"], "model_type": m["model_type"], "composite_score": m["score"]["composite_score"]} for m in result.get("trained_models", [])],
            "skipped_models": result.get("skipped_models", []),
            "recommended_training_run_id": result.get("recommended_training_run_id"),
            "recommended_reason": result.get("recommended_reason"),
            "final_test_evaluation": result.get("final_test_evaluation"),
            "exported_bundles": result.get("exported_bundles"),
            "run_name": result.get("run_name"),
        }
