"""REST surface for BLE Scientific Results Studio -- Fase 1 only (protocol
freeze, holdout access log, run creation, preflight). Thin by design, same
convention as ble_rffi_studio's studio_routes.py: every route calls straight
into ScientificResultsRepository/ScientificResultsJobManager and maps
exceptions to status codes.

The remaining endpoints from the full specification (power-simulation,
rq1-4, channel-transport, online-equivalence, forensic-calibration, export,
artifacts) are registered in later phases once the analysis code behind them
exists -- they are intentionally absent here rather than stubbed, so the
route surface never implies a capability that does not exist yet.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException


def build_ble_scientific_results_router(repository, job_manager) -> APIRouter:
    router = APIRouter(prefix="/ble-scientific-results", tags=["ble-scientific-results"])

    def call(fn):
        try:
            return fn()
        except FileNotFoundError as error:
            raise HTTPException(404, str(error) or "NOT_FOUND") from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        except RuntimeError as error:
            raise HTTPException(409, str(error)) from error

    def dump(obj):
        return obj.model_dump(mode="json") if hasattr(obj, "model_dump") else obj

    def dump_list(objs):
        return [dump(o) for o in objs]

    # ------------------------------------------------------------------
    # Protocol
    # ------------------------------------------------------------------

    @router.post("/protocols", status_code=201)
    def freeze_protocol(body: dict):
        return call(lambda: dump(repository.freeze_protocol(body)))

    @router.get("/protocols/{protocol_id}")
    def get_protocol(protocol_id: str, version: int | None = None):
        return call(lambda: dump(repository.get_protocol(protocol_id, version)))

    @router.get("/protocols/{protocol_id}/versions")
    def list_protocol_versions(protocol_id: str):
        return call(lambda: dump_list(repository.list_protocol_versions(protocol_id)))

    # ------------------------------------------------------------------
    # Holdout access log
    # ------------------------------------------------------------------

    @router.get("/holdout-access-log")
    def holdout_access_log():
        return call(lambda: dump_list(repository.list_holdout_access_log()))

    @router.post("/holdout-access-log", status_code=201)
    def log_holdout_access(body: dict):
        return call(lambda: dump(repository.log_holdout_access(
            actor=body["actor"], process=body["process"], access_type=body["access_type"], access_path=body["access_path"],
            resource_id=body["resource_id"], resource_hash=body.get("resource_hash"), reason=body["reason"],
            paper_run_id=body.get("paper_run_id"), analysis_contract_hash=body.get("analysis_contract_hash"),
        )))

    @router.get("/holdout-access-log/verify")
    def verify_holdout_access_chain():
        return call(lambda: dump(repository.verify_holdout_access_chain()))

    # ------------------------------------------------------------------
    # Holdout groups (2026-08-12, fast-closure pass, Phase 12): declares
    # which physical_unit_ids/day_ids/session_ids belong to a group
    # (FUTURE_TEST being the protected one) -- metadata-only, never
    # acquires data itself (real acquisition reuses the same generic
    # PaperCampaignRunner every other phase already uses). This is the
    # ONLY FUTURE-specific step in the whole pipeline.
    # ------------------------------------------------------------------

    @router.post("/holdout-groups", status_code=201)
    def freeze_holdout_groups(body: dict):
        return call(lambda: dump(repository.freeze_holdout_groups(
            dataset_id=body["dataset_id"], dataset_version=body["dataset_version"], group=body["group"],
            physical_unit_ids=body.get("physical_unit_ids"), day_ids=body.get("day_ids"), session_ids=body.get("session_ids"),
        )))

    @router.get("/holdout-groups/{dataset_id}/{dataset_version}")
    def list_holdout_groups(dataset_id: str, dataset_version: str):
        return call(lambda: dump_list(repository.list_holdout_groups(dataset_id, dataset_version)))

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    @router.post("/runs", status_code=201)
    def create_run(body: dict):
        return call(lambda: dump(repository.create_run(
            protocol_id=body["protocol_id"], protocol_version=body.get("protocol_version"), campaign_id=body["campaign_id"],
            dataset_id=body["dataset_id"], dataset_version=body["dataset_version"], scientific_task=body["scientific_task"],
        )))

    @router.get("/runs")
    def list_runs():
        return call(lambda: dump_list(repository.list_runs()))

    @router.get("/runs/{paper_run_id}")
    def get_run(paper_run_id: str):
        return call(lambda: dump(repository.get_run(paper_run_id)))

    # ------------------------------------------------------------------
    # Preflight / readiness
    # ------------------------------------------------------------------

    @router.post("/preflight", status_code=202)
    def start_preflight(body: dict):
        return call(lambda: job_manager.start_preflight_job(paper_run_id=body["paper_run_id"]))

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str):
        return call(lambda: job_manager.get_job(job_id))

    @router.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str):
        return call(lambda: job_manager.cancel_job(job_id))

    @router.get("/runs/{paper_run_id}/readiness")
    def readiness(paper_run_id: str):
        def resolve():
            report = repository.get_preflight_report(paper_run_id)
            if report is None:
                return {"paper_run_id": paper_run_id, "overall_status": None, "message": "Preflight has not run yet for this paper_run_id."}
            return dump(report)
        return call(resolve)

    # ------------------------------------------------------------------
    # Fase 2: canonical records, campaign accounting, quality, figures
    # ------------------------------------------------------------------

    @router.post("/runs/{paper_run_id}/build-records", status_code=202)
    def start_build_records(paper_run_id: str):
        return call(lambda: job_manager.start_build_records_job(paper_run_id=paper_run_id))

    @router.get("/runs/{paper_run_id}/records/status")
    def records_status(paper_run_id: str):
        def resolve():
            status = repository.get_records_status(paper_run_id)
            if status is None:
                return {"paper_run_id": paper_run_id, "built": False}
            return {"paper_run_id": paper_run_id, "built": True, **dump(status)}
        return call(resolve)

    @router.get("/runs/{paper_run_id}/campaign-accounting")
    def campaign_accounting(paper_run_id: str):
        def resolve():
            result = repository.get_campaign_accounting(paper_run_id)
            if result is None:
                raise FileNotFoundError(f"CAMPAIGN_ACCOUNTING_NOT_BUILT:{paper_run_id}")
            return result
        return call(resolve)

    @router.get("/runs/{paper_run_id}/deviations")
    def deviations(paper_run_id: str, limit: int = 200, offset: int = 0):
        return call(lambda: repository.list_deviation_records(paper_run_id, limit=limit, offset=offset))

    @router.get("/runs/{paper_run_id}/quality-summary")
    def quality_summary(paper_run_id: str):
        def resolve():
            result = repository.get_quality_summary(paper_run_id)
            if result is None:
                raise FileNotFoundError(f"QUALITY_SUMMARY_NOT_BUILT:{paper_run_id}")
            return result
        return call(resolve)

    # ------------------------------------------------------------------
    # Scientific Dashboard closure (2026-08-11): Level A (Experiment
    # Health, study-wide) and Level B (Data/Evidence Quality, per run) --
    # both real cross-references over already-real getters/canonical
    # tables, computing no new science.
    # ------------------------------------------------------------------

    @router.get("/experiment-health")
    def experiment_health():
        return call(lambda: repository.get_experiment_health_summary())

    # Real, in-platform paper-support dashboard (2026-08-16): cross-
    # references already-persisted RQ1/RQ2 reports (closed-set + per-unit
    # auxiliary runs), the frozen rq3_sample_size decision + live RQ3
    # campaign progress, and RQ4 per-unit eligibility -- same
    # zero-new-science convention as /experiment-health.
    @router.get("/evidence-dashboard")
    def evidence_dashboard():
        return call(lambda: repository.get_evidence_dashboard_summary())

    # UI-triggered equivalent of running generate_evidence_figures.py +
    # build_evidence_notebook.py from a terminal -- writes real PNG/ipynb
    # files into the repo working tree, never runs git itself.
    @router.post("/evidence-dashboard/regenerate-figures")
    def regenerate_evidence_figures():
        return call(lambda: repository.regenerate_evidence_figures())

    # Paper-representation pass (2026-08-17): real supporting tables + the
    # scientific completeness report -- same zero-new-science convention as
    # /evidence-dashboard and /experiment-health.
    @router.get("/tx-composition")
    def tx_composition():
        return call(lambda: repository.build_tx_composition_table())

    @router.get("/partition-composition")
    def partition_composition(dataset_id: str, dataset_version: str, scientific_task: str):
        return call(lambda: repository.build_partition_composition_table(dataset_id, dataset_version, scientific_task))

    @router.get("/receiver-epochs")
    def receiver_epochs():
        return call(lambda: repository.build_receiver_epoch_table())

    @router.get("/scientific-completeness")
    def scientific_completeness():
        return call(lambda: repository.get_scientific_completeness_report())

    @router.get("/runs/{paper_run_id}/evidence-quality-summary")
    def evidence_quality_summary(paper_run_id: str):
        def resolve():
            result = repository.get_evidence_quality_summary(paper_run_id)
            return result if result is not None else {"status": "NO_DATA"}
        return call(resolve)

    @router.get("/runs/{paper_run_id}/captures")
    def captures(paper_run_id: str, limit: int = 100, offset: int = 0):
        return call(lambda: repository.list_capture_records(paper_run_id, limit=limit, offset=offset))

    @router.get("/runs/{paper_run_id}/captures/{capture_id}")
    def capture_detail(paper_run_id: str, capture_id: str):
        def resolve():
            record = repository.get_capture_record(paper_run_id, capture_id)
            if record is None:
                raise FileNotFoundError(f"CAPTURE_RECORD_NOT_FOUND:{paper_run_id}:{capture_id}")
            return record
        return call(resolve)

    @router.get("/runs/{paper_run_id}/bursts")
    def bursts(paper_run_id: str, limit: int = 100, offset: int = 0, capture_id: str | None = None):
        return call(lambda: repository.list_burst_records(paper_run_id, limit=limit, offset=offset, capture_id=capture_id))

    @router.get("/runs/{paper_run_id}/windows")
    def windows(paper_run_id: str, limit: int = 100, offset: int = 0, capture_id: str | None = None):
        return call(lambda: repository.list_window_records(paper_run_id, limit=limit, offset=offset, capture_id=capture_id))

    @router.get("/runs/{paper_run_id}/artifacts")
    def artifacts(paper_run_id: str):
        return call(lambda: {"paper_run_id": paper_run_id, "files": repository.list_run_artifacts(paper_run_id)})

    # ------------------------------------------------------------------
    # Guided BLE Scientific Validation -- one orchestrator job spanning
    # every enrolled device's existing dataset. See guided_validation/
    # service.py: it only invokes repository.freeze_protocol/create_run/
    # build_records and calibration.select_association_policy, never a
    # second decoder or records builder.
    # ------------------------------------------------------------------

    @router.post("/guided-validation", status_code=202)
    def start_guided_validation():
        return call(lambda: job_manager.start_guided_validation_job())

    # ------------------------------------------------------------------
    # Capture-first entry point -- lets the UI offer "capture more data /
    # a new device" as its own option, independent of (and before) running
    # the full existing-data analysis above. Registered BEFORE
    # /guided-validation/{job_id} so these literal paths are never
    # swallowed by that path-parameter route.
    # ------------------------------------------------------------------

    @router.get("/guided-validation/capturable-devices")
    def capturable_devices():
        return call(lambda: job_manager.list_capturable_devices())

    @router.post("/guided-validation/new-capture-session", status_code=201)
    def new_capture_session():
        return call(lambda: job_manager.new_capture_session())

    # ------------------------------------------------------------------
    # Cleanup center -- lists/deletes guided-validation runs' own derived
    # artifacts (never the real I/Q captures they were built from). See
    # guided_validation/service.py::list_runs_for_cleanup/delete_run.
    # ------------------------------------------------------------------

    @router.get("/guided-validation/cleanup/runs")
    def list_cleanup_runs():
        return call(lambda: job_manager.list_guided_validation_runs_for_cleanup())

    @router.delete("/guided-validation/cleanup/runs/{run_id}")
    def delete_cleanup_run(run_id: str):
        return call(lambda: job_manager.delete_guided_validation_run(run_id))

    @router.get("/guided-validation/{job_id}")
    def get_guided_validation(job_id: str):
        return call(lambda: job_manager.get_job(job_id))

    # ------------------------------------------------------------------
    # SOURCE ADMISSION V2 -- read-only, synchronous (real data on disk,
    # seconds not minutes; no hardware involved). See guided_validation/
    # service.py::run_source_admission_v2 for the 8 admission conditions.
    # ------------------------------------------------------------------

    @router.get("/source-admission-v2")
    def source_admission_v2():
        return call(lambda: job_manager.run_source_admission_v2())

    # ------------------------------------------------------------------
    # Guided Validation hardware actions -- real, short, supervised
    # captures. See guided_validation/service.py: only CampaignOrchestrator.
    # run_session() ever touches the SDR/native scanner/arbiter.
    # ------------------------------------------------------------------

    @router.post("/guided-validation/{run_id}/timing-diagnostic", status_code=202)
    def start_timing_diagnostic(run_id: str, body: dict):
        return call(lambda: job_manager.start_timing_diagnostic_job(
            run_id=run_id, physical_unit_id=body["physical_unit_id"], capture_duration_s=float(body.get("capture_duration_s", 180.0)),
            channel=int(body.get("channel", 37)), receiver_profile=body.get("receiver_profile"), operator_id=body.get("operator_id"),
        ))

    @router.post("/guided-validation/{run_id}/target-absence-control", status_code=202)
    def start_target_absence_control(run_id: str, body: dict):
        return call(lambda: job_manager.start_target_absence_control_job(
            run_id=run_id, confirmed_devices_off=body["confirmed_devices_off"], capture_duration_s=float(body.get("capture_duration_s", 180.0)),
            channel=int(body.get("channel", 37)), operator_id=body.get("operator_id"),
        ))

    @router.get("/guided-validation/{run_id}/actions/{action_job_id}")
    def get_guided_validation_action(run_id: str, action_job_id: str):
        return call(lambda: job_manager.get_job(action_job_id))

    # ------------------------------------------------------------------
    # Paper progress dashboard (2026-08-10) -- read-only reporting. Every
    # route here either passes through an already-real repository read or
    # a presence/absence check; none computes a scientific value, none
    # mutates the protocol, and `/paper-exports` (the one POST) only writes
    # export files, never opens FUTURE_TEST or changes any contract.
    # ------------------------------------------------------------------

    @router.get("/study-status")
    def study_status(protocol_id: str | None = None):
        return call(lambda: repository.get_study_status(protocol_id))

    @router.get("/paper-readiness")
    def paper_readiness():
        return call(lambda: repository.get_paper_readiness())

    @router.get("/campaign-qualification-preflight/latest")
    def campaign_qualification_preflight_latest():
        path = repository.root / "campaign_qualification_preflight_report.json"
        if not path.is_file():
            return {"status": "NO_DATA"}
        return json.loads(path.read_text(encoding="utf-8"))

    @router.get("/association-policy-status")
    def association_policy_status():
        def _read():
            policy = repository.find_frozen_association_policy()
            if policy is None:
                return {"status": "NONE"}
            return {"status": "FROZEN", "policy": dump(policy)}
        return call(_read)

    # Paper-representation pass (2026-08-17): the most recent real
    # calibration attempt's full structured sweep, regardless of outcome --
    # shown on Results Dashboard even when no threshold has ever been
    # accepted, so the real diagnostic is visible, not just "NONE".
    @router.get("/association-calibration-summary")
    def association_calibration_summary():
        def resolve():
            summary = repository.get_latest_association_calibration_summary()
            return summary if summary is not None else {"status": "NO_DATA"}
        return call(resolve)

    @router.get("/protocol-freeze-status")
    def protocol_freeze_status(protocol_id: str | None = None):
        def _read():
            freezes = repository.list_protocol_freezes()
            if protocol_id is not None:
                freezes = [entry for entry in freezes if entry["protocol_id"] == protocol_id]
            if not freezes:
                return {"status": "NOT_STARTED", "entries": []}
            return {"status": "COMPLETE", "entries": freezes}
        return call(_read)

    @router.get("/runs/{paper_run_id}/confirmatory-statistical-plan")
    def get_confirmatory_statistical_plan(paper_run_id: str):
        def _read():
            report = repository.get_confirmatory_statistical_plan_report(paper_run_id)
            return report if report is not None else {"status": "NO_DATA"}
        return call(_read)

    @router.get("/runs/{paper_run_id}/confirmatory-future-analysis")
    def get_confirmatory_future_analysis(paper_run_id: str):
        def _read():
            report = repository.get_confirmatory_future_analysis_report(paper_run_id)
            return report if report is not None else {"status": "NO_DATA"}
        return call(_read)

    @router.get("/runs/{paper_run_id}/rq1-acquisition-dependence")
    def get_rq1_acquisition_dependence(paper_run_id: str):
        def _read():
            report = repository.get_rq1_acquisition_dependence_report(paper_run_id)
            return report if report is not None else {"status": "NO_DATA"}
        return call(_read)

    @router.get("/runs/{paper_run_id}/rq2-representation-comparison")
    def get_rq2_representation_comparison(paper_run_id: str):
        def _read():
            report = repository.get_rq2_representation_comparison_report(paper_run_id)
            return report if report is not None else {"status": "NO_DATA"}
        return call(_read)

    @router.post("/paper-exports", status_code=201)
    def run_paper_export():
        return call(lambda: repository.run_paper_export())

    @router.get("/paper-exports")
    def get_paper_export_manifest():
        def _read():
            manifest = repository.get_paper_export_manifest()
            return manifest if manifest is not None else {"status": "NO_DATA"}
        return call(_read)

    # ------------------------------------------------------------------
    # Provenance reconstruction (2026-08-11) -- strictly read-only.
    # ------------------------------------------------------------------

    @router.get("/inference-runs")
    def list_inference_runs():
        return call(lambda: repository.list_inference_runs())

    @router.get("/provenance/{inference_run_id}/{example_id}")
    def get_decision_provenance(inference_run_id: str, example_id: str):
        return call(lambda: repository.get_decision_provenance(inference_run_id=inference_run_id, example_id=example_id))

    # ------------------------------------------------------------------
    # Engineering reports: S1 channel transport, S2 offline/near-live
    # (2026-08-11) -- read-only; nothing here computes a real result in
    # this pass (no trained bundle/near-live instrumentation exists yet).
    # ------------------------------------------------------------------

    @router.get("/runs/{paper_run_id}/channel-transport")
    def get_channel_transport(paper_run_id: str):
        def _read():
            report = repository.get_channel_transport_report(paper_run_id)
            return report if report is not None else {"status": "NO_DATA"}
        return call(_read)

    @router.get("/runs/{paper_run_id}/offline-nearlive")
    def get_offline_nearlive(paper_run_id: str):
        def _read():
            report = repository.get_offline_nearlive_report(paper_run_id)
            return report if report is not None else {"status": "NO_DATA"}
        return call(_read)

    # ------------------------------------------------------------------
    # Study Control Center, Phase 1 (2026-08-11) -- the 17-phase workflow
    # status aggregator (read-only, computes no science, only real gating
    # over already-real getters) and the RUN REAL HARDWARE QUALIFICATION
    # launcher (the one job here that touches real hardware).
    # ------------------------------------------------------------------

    @router.get("/study-control-center")
    def study_control_center():
        return call(lambda: repository.get_study_control_center_status())

    # ------------------------------------------------------------------
    # Study Control Center, phase 05 (2026-08-11): Study Sizing. Wraps the
    # already-real statistics/power_simulation.py; the decision endpoint
    # never auto-selects a design, only persists the caller's explicit,
    # reasoned choice.
    # ------------------------------------------------------------------

    @router.post("/study-sizing/evaluate")
    def evaluate_study_sizing(body: dict):
        return call(lambda: repository.evaluate_study_sizing_candidates(
            candidate_designs=body["candidate_designs"], p1=float(body["p1"]), p2=float(body["p2"]),
            alpha=float(body.get("alpha", 0.05)), target_power=float(body.get("target_power", 0.8)),
        ))

    @router.post("/study-sizing/decision", status_code=201)
    def record_study_sizing_decision(body: dict):
        return call(lambda: repository.persist_study_sizing_decision(
            chosen_design=body["chosen_design"], p1=float(body["p1"]), p2=float(body["p2"]),
            alpha=float(body.get("alpha", 0.05)), target_power=float(body.get("target_power", 0.8)),
            rationale=body["rationale"], decided_by=body.get("decided_by"),
        ))

    @router.get("/study-sizing/decision")
    def get_study_sizing_decision():
        def _read():
            decision = repository.get_study_sizing_decision()
            return decision if decision is not None else {"status": "NO_DATA"}
        return call(_read)

    # ------------------------------------------------------------------
    # Study Control Center, phase 09 (2026-08-11): Analysis Contract
    # Readiness. Never a generic JSON editor -- the GET reports, per field,
    # DERIVED (real, already-frozen artifact/constant) vs SCIENTIST_DECISION
    # (only ever resolved from a real recorded decision). The POST records a
    # decision -- it never computes or suggests one.
    # ------------------------------------------------------------------

    @router.get("/analysis-contract-readiness")
    def analysis_contract_readiness():
        return call(lambda: repository.get_analysis_contract_readiness())

    @router.post("/scientist-decisions", status_code=201)
    def record_scientist_decision(body: dict):
        return call(lambda: repository.record_scientist_decision(
            field_id=body["field_id"], selected_value=body.get("selected_value"),
            rationale=body["rationale"], evidence_used=body.get("evidence_used", ""),
            decided_by=body.get("decided_by"), protocol_version_candidate=body.get("protocol_version_candidate"),
        ))

    @router.get("/scientist-decisions")
    def list_scientist_decisions(field_id: str | None = None):
        return call(lambda: repository.list_scientist_decisions(field_id))

    @router.post("/hardware-qualification", status_code=202)
    def start_hardware_qualification(body: dict):
        return call(lambda: job_manager.start_hardware_qualification_job(
            physical_unit_id=body["physical_unit_id"], channel=int(body.get("channel", 37)),
            duration_seconds=float(body.get("duration_seconds", 180.0)),
        ))

    @router.post("/rq2-benchmark", status_code=202)
    def start_rq2_benchmark(body: dict):
        return call(lambda: job_manager.start_rq2_benchmark_job(
            paper_run_id=body["paper_run_id"], dataset_id=body["dataset_id"], dataset_version=body["dataset_version"],
            scientific_task=body.get("scientific_task", "TARGET_VS_BACKGROUND"), model_types=body.get("model_types"),
        ))

    # RQ1 acquisition-dependence -- minimal orchestration runner (see
    # ../rq1_runner.py): the calculation already existed
    # (build_rq1_dependence_diagnostic / evaluate_rq1_acquisition_dependence
    # / persist_rq1_acquisition_dependence_report), this route is the
    # missing real caller wiring them together.
    @router.post("/rq1-acquisition-dependence", status_code=202)
    def start_rq1_acquisition_dependence(body: dict):
        return call(lambda: job_manager.start_rq1_acquisition_dependence_job(
            paper_run_id=body["paper_run_id"], dataset_id=body["dataset_id"], dataset_version=body["dataset_version"],
            recommended_training_run_id=body["recommended_training_run_id"],
            scientific_task=body.get("scientific_task", "TARGET_VS_BACKGROUND"),
        ))

    # Scientific Dashboard Closure audit finding (2026-08-11): RQ3's real
    # FRR_pre/FRR_post/D estimand had zero real callers even though the
    # frozen inference pipeline was already real -- this is the missing
    # real caller (see rq3_frr_analysis.py's own module docstring).
    @router.post("/rq3-frr-analysis", status_code=202)
    def start_rq3_frr_analysis(body: dict):
        return call(lambda: job_manager.start_rq3_frr_analysis_job(paper_run_id=body["paper_run_id"], bundle_id=body.get("bundle_id")))

    # Coverage audit finding (2026-08-12): real decision records already
    # carry everything coverage needs -- this is the missing aggregation.
    @router.post("/coverage-analysis", status_code=202)
    def start_coverage_analysis(body: dict):
        return call(lambda: job_manager.start_coverage_analysis_job(
            paper_run_id=body["paper_run_id"], bundle_ids=body.get("bundle_ids"),
            evaluate_window_level=bool(body.get("evaluate_window_level", False)),
        ))

    @router.get("/runs/{paper_run_id}/coverage-analysis")
    def get_coverage_analysis(paper_run_id: str):
        def resolve():
            result = repository.get_coverage_analysis_report(paper_run_id)
            return result if result is not None else {"status": "NO_DATA"}
        return call(resolve)

    # Sensitivity closure (2026-08-12): enrolled-population class-exclusion
    # metric sensitivity + offset-retaining + reused RQ2 seed_variability,
    # consolidated into one real report.
    @router.post("/sensitivity-analysis", status_code=202)
    def start_sensitivity_analysis(body: dict):
        return call(lambda: job_manager.start_sensitivity_analysis_job(paper_run_id=body["paper_run_id"]))

    @router.get("/runs/{paper_run_id}/sensitivity-analysis")
    def get_sensitivity_analysis(paper_run_id: str):
        def resolve():
            result = repository.get_sensitivity_report(paper_run_id)
            return result if result is not None else {"status": "NO_DATA"}
        return call(resolve)

    # RQ4 region-specific fitting closure (2026-08-12): rq4_primary_analysis=
    # REGION_SPECIFIC_FITTING_AND_EVALUATION. Persists into the SAME
    # confirmatory_statistical_plan_report.json RQ3 already writes to (under
    # rq4_region_report) -- read via the existing
    # /confirmatory-statistical-plan GET route above, same as rq3_pairs.
    @router.post("/rq4-region-analysis", status_code=202)
    def start_rq4_region_analysis(body: dict):
        return call(lambda: job_manager.start_rq4_region_analysis_job(paper_run_id=body["paper_run_id"], full_burst_bundle_id=body.get("full_burst_bundle_id")))

    # Fast-closure pass (2026-08-12), Phase 14 (S1) / Phase 15 (S2) launchers.
    @router.post("/channel-transport-analysis", status_code=202)
    def start_channel_transport_analysis(body: dict):
        return call(lambda: job_manager.start_channel_transport_analysis_job(paper_run_id=body["paper_run_id"], bundle_id=body.get("bundle_id")))

    @router.post("/offline-nearlive-analysis", status_code=202)
    def start_offline_nearlive_analysis(body: dict):
        return call(lambda: job_manager.start_offline_nearlive_analysis_job(paper_run_id=body["paper_run_id"]))

    # Fast-closure pass (2026-08-12), Phase 13: the single real
    # CONFIRMATORY_FUTURE trigger -- run_confirmatory_future_analysis
    # already existed (protocol-freeze close-out, 2026-08-10) but had no
    # route to call it, only a read-only GET (below).
    @router.post("/confirmatory-future-analysis", status_code=202)
    def start_confirmatory_future_analysis(body: dict):
        return call(lambda: job_manager.start_confirmatory_future_analysis_job(
            paper_run_id=body["paper_run_id"], protocol_id=body["protocol_id"], dataset_id=body["dataset_id"], dataset_version=body["dataset_version"],
            bundle_id=body["bundle_id"], declared_contract_sha256=body.get("declared_contract_sha256"), stats_kwargs=body.get("stats_kwargs"),
        ))

    return router
