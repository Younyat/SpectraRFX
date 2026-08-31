"""REST surface for the BLE-RFFI End-to-End Studio. Thin by design: every
route calls straight into StudioRepository/StudioJobManager, which already
carry all the real logic and persistence -- this file only translates
HTTP <-> Python calls and maps exceptions to status codes, same convention
as ble_packet_analysis_routes.py.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.infrastructure.ble.capture.ble_offline_replay import utc_now

from ..contracts import TrainingRun


def build_ble_rffi_studio_router(repository, job_manager) -> APIRouter:
    router = APIRouter(prefix="/ble-rffi-studio", tags=["ble-rffi-studio"])

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
    # Legacy captures (read-only, reused from Phase 2)
    # ------------------------------------------------------------------

    @router.get("/legacy-captures")
    def legacy_captures():
        return call(repository.list_legacy_captures)

    # Deletes a raw B200 capture (real, irreversible IQ removal -- mainly
    # meant for the RF-overflow retry artifacts the campaign retry loop
    # leaves behind, never cleaned up automatically). Also removes this
    # module's own CaptureRecord/evidence for it, if any were built.
    @router.delete("/legacy-captures/{capture_id}")
    def delete_legacy_capture(capture_id: str):
        return call(lambda: repository.delete_legacy_capture(capture_id))

    # ------------------------------------------------------------------
    # Physical Device Registry
    # ------------------------------------------------------------------

    @router.get("/physical-units")
    def physical_units():
        return call(lambda: dump_list(repository.list_physical_units()))

    @router.post("/physical-units", status_code=201)
    def create_physical_unit(body: dict):
        return call(lambda: dump(repository.register_physical_unit(
            physical_unit_id=body["physical_unit_id"], project_id=body["project_id"], device_family=body["device_family"],
            manufacturer=body.get("manufacturer"), model=body.get("model"), operator_declaration_id=body["operator_declaration_id"],
        )))

    # Study Control Center, phase 02 (2026-08-11) -- explicit operator
    # decisions, never inferred from device_family/model.
    @router.post("/physical-units/{physical_unit_id}/confirm-same-model")
    def confirm_same_model(physical_unit_id: str, body: dict):
        return call(lambda: dump(repository.confirm_same_model(physical_unit_id, basis=body["basis"])))

    @router.post("/physical-units/{physical_unit_id}/rq4-eligibility")
    def set_rq4_eligibility(physical_unit_id: str, body: dict):
        return call(lambda: dump(repository.set_rq4_eligibility(physical_unit_id, eligible=bool(body["eligible"]), reason=body["reason"])))

    @router.get("/address-bindings")
    def address_bindings():
        return call(lambda: dump_list(repository.list_bindings()))

    @router.post("/address-bindings", status_code=201)
    def create_binding(body: dict):
        return call(lambda: dump(repository.declare_binding(
            project_id=body["project_id"], address=body["address"], address_type=body.get("address_type", "public"),
            physical_unit_id=body["physical_unit_id"], reason=body.get("reason", "Operator declaration"),
            decision_artifact_id=body.get("decision_artifact_id", "manual-declaration"),
        )))

    # ------------------------------------------------------------------
    # Synthetic demo (no SDR hardware required)
    # ------------------------------------------------------------------

    @router.post("/synthetic-demo/seed", status_code=201)
    def seed_synthetic_demo():
        return call(repository.seed_synthetic_demo)

    # ------------------------------------------------------------------
    # Real capture campaign (B200 + native scan)
    # ------------------------------------------------------------------

    @router.get("/campaign/device-status")
    def campaign_device_status():
        return call(repository.campaign_device_status)

    @router.post("/campaign/sessions", status_code=202)
    def start_campaign_session(body: dict):
        return call(lambda: job_manager.start_campaign_session_job(
            ble_channel=body.get("ble_channel", 37), duration_seconds=body.get("duration_seconds", 10.0),
            gain_db=body.get("gain_db", 20.0), condition_label=body["condition_label"],
            physical_unit_id=body.get("physical_unit_id"), project_id=body["project_id"], campaign_id=body["campaign_id"],
            session_index=body.get("session_index", 1), device_id=body.get("device_id"),
            isolation_declared=bool(body.get("isolation_declared", False)),
            capture_purpose=body.get("capture_purpose", "TARGET_DEVICE_ON"),
            operator_confirmed_target_absent=bool(body.get("operator_confirmed_target_absent", False)),
            # capture_only=True stops after the real B200 acquisition --
            # OFFLINE_REPLAY/evidence are applied later via the
            # replay-and-evidence-jobs endpoint below, for any number of
            # captures, whenever there's time for the slow decode.
            capture_only=bool(body.get("capture_only", False)),
        ))

    # Guided capture: probes with short, throwaway B200 captures for a real
    # signal (TARGET_DEVICE_ON) or a clean environment (BACKGROUND_*) BEFORE
    # launching the real, saved capture -- see CampaignOrchestrator.run_guided_capture_only().
    # Stops after the real B200 acquisition, same as capture_only above --
    # OFFLINE_REPLAY/evidence are applied later, never here.
    @router.post("/campaign/guided-sessions", status_code=202)
    def start_guided_capture_session(body: dict):
        return call(lambda: job_manager.start_guided_capture_job(
            ble_channel=body.get("ble_channel", 37), duration_seconds=body.get("duration_seconds", 10.0),
            gain_db=body.get("gain_db", 20.0), condition_label=body["condition_label"],
            physical_unit_id=body.get("physical_unit_id"), project_id=body["project_id"], campaign_id=body["campaign_id"],
            session_index=body.get("session_index", 1), device_id=body.get("device_id"),
            isolation_declared=bool(body.get("isolation_declared", False)),
            capture_purpose=body.get("capture_purpose", "TARGET_DEVICE_ON"),
            operator_confirmed_target_absent=bool(body.get("operator_confirmed_target_absent", False)),
            probe_duration_seconds=body.get("probe_duration_seconds", 1.0),
            probe_timeout_seconds=body.get("probe_timeout_seconds", 30.0),
        ))

    # ------------------------------------------------------------------
    # Paper campaign schedule (Study Control Center, phases 04/06/07,
    # 2026-08-11) -- the SAME real mechanism serves the Qualification Pilot
    # (qualification_only=true) and the real DEVELOPMENT/VALIDATION
    # campaigns (qualification_only=false); only the frozen schedule
    # differs. See campaign/paper_campaign_runner.py.
    # ------------------------------------------------------------------

    @router.post("/campaign/schedule", status_code=201)
    def freeze_campaign_schedule(body: dict):
        return call(lambda: dump(repository.freeze_campaign_schedule(
            schedule_id=body["schedule_id"], protocol_id=body["protocol_id"], entries=body["entries"],
            qualification_only=bool(body.get("qualification_only", False)), receiver_session_id=body.get("receiver_session_id"),
        )))

    @router.get("/campaign/schedule/{schedule_id}")
    def get_campaign_schedule(schedule_id: str, version: int | None = None):
        return call(lambda: dump(repository.get_campaign_schedule(schedule_id, version)))

    @router.get("/campaign/schedule/{schedule_id}/rejections")
    def campaign_schedule_rejections(schedule_id: str):
        return call(lambda: repository.list_campaign_schedule_rejections(schedule_id))

    @router.post("/campaign/schedule/{schedule_id}/execute-next", status_code=202)
    def execute_next_campaign_schedule_capture(schedule_id: str, body: dict):
        return call(lambda: job_manager.start_campaign_schedule_execute_job(
            schedule_id=schedule_id, duration_seconds=body.get("duration_seconds", 10.0), gain_db=body.get("gain_db", 20.0),
            operator_id=body.get("operator_id"), operator_confirmed_target_absent=bool(body.get("operator_confirmed_target_absent", False)),
        ))

    # ------------------------------------------------------------------
    # Capture Stage
    # ------------------------------------------------------------------

    @router.get("/captures")
    def captures():
        return call(lambda: dump_list(repository.list_captures()))

    @router.post("/captures", status_code=201)
    def create_capture(body: dict):
        return call(lambda: dump(repository.build_capture(
            capture_id=body["capture_id"], project_id=body["project_id"], campaign_id=body["campaign_id"],
            execution_id=body.get("execution_id"), session_id=body.get("session_id"),
            isolation_declared_physical_unit_id=body.get("isolation_declared_physical_unit_id"),
            capture_purpose=body.get("capture_purpose"), target_state=body.get("target_state"),
            background_kind=body.get("background_kind"),
            target_reference_id=body.get("target_reference_id"), dataset_role=body.get("dataset_role"),
        )))

    @router.get("/captures/{capture_id}")
    def get_capture(capture_id: str):
        def fn():
            capture = repository.get_capture(capture_id)
            if capture is None:
                raise FileNotFoundError(f"CAPTURE_NOT_BUILT_YET:{capture_id}")
            return dump(capture)
        return call(fn)

    # ------------------------------------------------------------------
    # Evidence Stage (background job -- can process hundreds of packets)
    # ------------------------------------------------------------------

    @router.post("/captures/{capture_id}/evidence-jobs", status_code=202)
    def start_evidence_job(capture_id: str, body: dict):
        return call(lambda: job_manager.start_evidence_job(
            capture_id=capture_id, project_id=body["project_id"], ble_channel=body["ble_channel"], replay_run_id=body.get("replay_run_id"),
        ))

    # Runs the resumable OFFLINE_REPLAY (decode) + Evidence Stage for a
    # CaptureRecord that already exists -- the deliberately separable "slow
    # part" a capture_only=True campaign session skips. Idempotent unless
    # force=True: a capture that already has evidence is reported as
    # skipped, never silently re-decoded (real decode time, not free).
    @router.post("/captures/{capture_id}/replay-and-evidence-jobs", status_code=202)
    def start_replay_and_evidence_job(capture_id: str, body: dict):
        return call(lambda: job_manager.start_replay_and_evidence_job(
            capture_id=capture_id, project_id=body["project_id"], ble_channel=body["ble_channel"],
            force=bool(body.get("force", False)),
        ))

    @router.get("/captures/{capture_id}/examples")
    def list_examples(capture_id: str):
        return call(lambda: dump_list(repository.list_examples(capture_id)))

    @router.get("/captures/{capture_id}/repair-guidance")
    def capture_repair_guidance(capture_id: str):
        return call(lambda: repository.capture_repair_guidance(capture_id))

    # Fast (no IQ decode) native-scan-only triage -- lets the operator learn
    # a capture is doomed (target never seen natively) in ~1s instead of
    # waiting through the full "Aplicar analisis" decode.
    @router.get("/captures/{capture_id}/quick-presence-check")
    def quick_presence_check(capture_id: str):
        return call(lambda: repository.quick_presence_check(capture_id))

    @router.get("/captures/{capture_id}/annotations")
    def list_annotations(capture_id: str):
        return call(lambda: dump_list(repository.list_annotations(capture_id)))

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str):
        return call(lambda: job_manager.get_job(job_id))

    # ------------------------------------------------------------------
    # Dataset Builder + Dataset Analyzer
    # ------------------------------------------------------------------

    @router.get("/datasets")
    def datasets():
        return call(lambda: dump_list(repository.list_datasets()))

    @router.delete("/datasets/{dataset_id}/{dataset_version}")
    def delete_dataset(dataset_id: str, dataset_version: str):
        return call(lambda: repository.delete_dataset(dataset_id, dataset_version))

    @router.post("/datasets", status_code=201)
    def create_dataset(body: dict):
        def fn():
            result = repository.build_dataset(
                dataset_id=body["dataset_id"], dataset_version=body["dataset_version"], project_id=body["project_id"],
                campaign_id=body["campaign_id"], capture_ids=body["capture_ids"], derived_from=body.get("derived_from"),
            )
            return {"dataset": dump(result["dataset"]), "n_selected": result["n_selected"], "n_excluded": result["n_excluded"], "excluded_reasons": result["excluded_reasons"]}
        return call(fn)

    @router.get("/datasets/{dataset_id}/{dataset_version}")
    def get_dataset(dataset_id: str, dataset_version: str):
        def fn():
            dataset = repository.get_dataset(dataset_id, dataset_version)
            if dataset is None:
                raise FileNotFoundError("DATASET_NOT_FOUND")
            return dump(dataset)
        return call(fn)

    @router.get("/datasets/{dataset_id}/{dataset_version}/label-provenance")
    def label_provenance(dataset_id: str, dataset_version: str):
        return call(lambda: repository.label_provenance_report(dataset_id, dataset_version))

    @router.get("/datasets/{dataset_id}/{dataset_version}/composition-report")
    def dataset_composition(dataset_id: str, dataset_version: str):
        return call(lambda: repository.dataset_composition_report(dataset_id, dataset_version))

    @router.post("/datasets/{dataset_id}/{dataset_version}/quality-report")
    def build_quality_report(dataset_id: str, dataset_version: str, body: dict | None = None):
        run_near_duplicates = bool((body or {}).get("run_near_duplicates", False))
        return call(lambda: dump(repository.build_quality_report(dataset_id=dataset_id, dataset_version=dataset_version, run_near_duplicates=run_near_duplicates)))

    @router.get("/datasets/{dataset_id}/{dataset_version}/quality-report")
    def get_quality_report(dataset_id: str, dataset_version: str):
        def fn():
            report = repository.get_quality_report(dataset_id, dataset_version)
            if report is None:
                raise FileNotFoundError("QUALITY_REPORT_NOT_BUILT_YET")
            return dump(report)
        return call(fn)

    # UI-reachable fix for a quality gate blocked on exact duplicates or
    # sample overlap: quarantines exactly the examples DatasetAnalyzer.
    # resolve_overlaps() determines are redundant/overlapping, directly on
    # each capture's evidence -- the next "Revisar datos"/quality-report
    # rebuilds its dataset draft fresh from that evidence, so no separate
    # re-freeze step is needed here.
    @router.post("/datasets/resolve-duplicates", status_code=200)
    def resolve_dataset_duplicates(body: dict):
        return call(lambda: repository.resolve_dataset_duplicates(capture_ids=body["capture_ids"]))
        return call(fn)

    # ------------------------------------------------------------------
    # Split Builder
    # ------------------------------------------------------------------

    @router.post("/datasets/{dataset_id}/{dataset_version}/splits/{scientific_task}")
    def build_split(dataset_id: str, dataset_version: str, scientific_task: str):
        return call(lambda: dump(repository.build_split(dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=scientific_task)))

    @router.get("/datasets/{dataset_id}/{dataset_version}/splits/{scientific_task}")
    def get_split(dataset_id: str, dataset_version: str, scientific_task: str):
        def fn():
            split = repository.get_split(dataset_id, dataset_version, scientific_task)
            if split is None:
                raise FileNotFoundError("SPLIT_NOT_BUILT_YET")
            return dump(split)
        return call(fn)

    @router.get("/datasets/{dataset_id}/{dataset_version}/splits/{scientific_task}/training-preview")
    def split_training_preview(dataset_id: str, dataset_version: str, scientific_task: str):
        return call(lambda: repository.dataset_training_preview(dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=scientific_task))

    # ------------------------------------------------------------------
    # Guided mode helpers
    # ------------------------------------------------------------------

    @router.get("/scientific-tasks")
    def scientific_tasks():
        return call(repository.scientific_task_display_names)

    @router.get("/datasets/{dataset_id}/{dataset_version}/feasibility")
    def feasibility(dataset_id: str, dataset_version: str, scientific_task: str):
        def fn():
            dataset = repository.get_dataset(dataset_id, dataset_version)
            if dataset is None:
                raise FileNotFoundError("DATASET_NOT_FOUND")
            examples = repository._dataset_examples(dataset)  # noqa: SLF001 -- read-only helper, no separate public API needed yet
            from ..quality import explain_feasibility
            return explain_feasibility(examples, scientific_task)
        return call(fn)

    @router.get("/datasets/{dataset_id}/{dataset_version}/task-recommendation")
    def task_recommendation(dataset_id: str, dataset_version: str):
        def fn():
            dataset = repository.get_dataset(dataset_id, dataset_version)
            if dataset is None:
                raise FileNotFoundError("DATASET_NOT_FOUND")
            examples = repository._dataset_examples(dataset)  # noqa: SLF001 -- read-only helper, no separate public API needed yet
            from ..quality import recommend_scientific_task
            return recommend_scientific_task(examples)
        return call(fn)

    # Auto-train: one call per registered device instead of an operator
    # manually enumerating capture_ids before every prepare-and-train --
    # resolves "this device's own TARGET_DEVICE_ON captures + every
    # project-shared BACKGROUND_* capture" the same way a careful operator
    # would by hand, then launches the exact same PREPARE_AND_TRAIN job.
    @router.get("/auto-train/candidates")
    def auto_train_candidates():
        return call(repository.auto_train_candidates)

    @router.post("/auto-train/{physical_unit_id}", status_code=202)
    def auto_train(physical_unit_id: str, body: dict | None = None):
        def fn():
            resolved = repository.resolve_auto_train_capture_ids(physical_unit_id)
            body_ = body or {}
            return job_manager.start_prepare_and_train_job(
                capture_ids=resolved["capture_ids"], project_id=resolved["project_id"],
                campaign_id=body_.get("campaign_id") or f"{resolved['project_id']}-AUTO-TRAIN-CAMPAIGN",
                scientific_task="TARGET_VS_BACKGROUND", ble_channel=body_.get("ble_channel", 37),
                dataset_id=body_.get("dataset_id") or f"{physical_unit_id}-AUTO-TVB",
                dataset_version=body_.get("dataset_version") or utc_now().replace(":", "").replace("-", ""),
                # Single-device auto-train must never let a different
                # registered device's packets (incidentally captured nearby)
                # count as TARGET evidence for this one -- see build_dataset()
                # docstring comment for the real CC2541SensorTag/CC2650-UNIT-01
                # contamination this prevents.
                target_physical_unit_ids={physical_unit_id},
                # One click, fully automatic: every candidate model this run
                # trains gets exported + approved for Live Monitor too,
                # never a separate manual step (see
                # StudioRepository.export_and_approve_all_candidates()).
                auto_export_physical_unit_id=physical_unit_id,
            )
        return call(fn)

    # One-click: detect every background capture still contaminated by an
    # "always-on" device (never genuinely off, so it always leaks into its
    # own declared-background evidence), scrub+verify each, then train and
    # export both an ORIGINAL-background and a SCRUBBED-background model set
    # for direct comparison. See StudioRepository.scrub_device_from_background().
    @router.post("/scrub-background/{physical_unit_id}", status_code=202)
    def scrub_background(physical_unit_id: str):
        return call(lambda: job_manager.start_device_scrub_job(physical_unit_id=physical_unit_id))

    @router.get("/scrub-background/{physical_unit_id}/candidates")
    def scrub_background_candidates(physical_unit_id: str):
        return call(lambda: dump_list(repository.find_contaminated_background_captures(physical_unit_id)))

    # Training Service: pick 1+ ALREADY-frozen, already-labeled dataset(s) +
    # exactly which model_type candidates to train. One dataset trains a
    # normal TARGET_VS_BACKGROUND detector (never builds a new dataset,
    # never touches capture_ids -- StudioRepository.train_selected_models()).
    # 2+ datasets combine into a multi-class SAME_MODEL_UNIT_IDENTIFICATION
    # model that says WHICH device is present, never a binary "any of these"
    # family (StudioRepository.combine_datasets_for_identification()).
    @router.post("/training-service/run", status_code=202)
    def training_service_run(body: dict):
        dataset_keys = [(d["dataset_id"], d["dataset_version"]) for d in body["dataset_keys"]]
        background = body.get("background_dataset")
        background_dataset_key = (background["dataset_id"], background["dataset_version"]) if background else None
        return call(lambda: job_manager.start_train_selected_models_job(
            dataset_keys=dataset_keys, model_types=body["model_types"], background_dataset_key=background_dataset_key,
        ))

    # Explicit, operator-visible export button for the Training Service
    # results panel -- export already happens automatically right after
    # training (see _run_train_selected_models_job), but re-running this is
    # always safe (export_bundle/approve_bundle are themselves idempotent)
    # and gives the operator a real, clickable action rather than only a
    # silent background step.
    @router.post("/training-service/export")
    def training_service_export(body: dict):
        return call(lambda: repository.export_and_approve_all_candidates(
            physical_unit_id=body["run_name"],
            prepare_and_train_result={"trained_models": body["trained_models"], "recommended_training_run_id": body.get("recommended_training_run_id")},
        ))

    @router.post("/prepare-and-train", status_code=202)
    def prepare_and_train(body: dict):
        return call(lambda: job_manager.start_prepare_and_train_job(
            capture_ids=body["capture_ids"], project_id=body["project_id"], campaign_id=body["campaign_id"],
            scientific_task=body["scientific_task"], ble_channel=body.get("ble_channel", 37),
            dataset_id=body.get("dataset_id"), dataset_version=body.get("dataset_version", "1.0.0"),
            speed_profile=body.get("speed_profile", "normal"),
            # Already-implemented in StudioRepository.prepare_and_train()/
            # build_dataset() (the same real CC2541SensorTag/CC2650-UNIT-01
            # cross-contamination fix /auto-train/{unit} already relies on)
            # -- exposed here too so a caller assembling a specific, curated
            # capture_ids list (not the auto-resolved set) can still opt into
            # the same protection instead of only getting it via auto-train.
            target_physical_unit_ids=set(body["target_physical_unit_ids"]) if body.get("target_physical_unit_ids") else None,
        ))

    # ------------------------------------------------------------------
    # Training (background job)
    # ------------------------------------------------------------------

    @router.post("/training-runs", status_code=202)
    def start_training(body: dict):
        def fn():
            dataset = repository.get_dataset(body["dataset_id"], body["dataset_version"])
            if dataset is None:
                raise FileNotFoundError(f"DATASET_NOT_FOUND:{body['dataset_id']}:{body['dataset_version']}")
            training_run = TrainingRun(
                training_run_id=body["training_run_id"], project_id=body["project_id"], campaign_id=body["campaign_id"],
                dataset_id=body["dataset_id"], dataset_version=body["dataset_version"], dataset_manifest_sha256=body["dataset_manifest_sha256"],
                split_manifest_sha256=body["split_manifest_sha256"], scientific_task=body["scientific_task"], model_type=body["model_type"],
                data_origin=dataset.data_origin, operational_use="FORBIDDEN" if dataset.data_origin == "SYNTHETIC_TEST_ONLY" else "ALLOWED",
                base_preprocessing_profile_id=body.get("base_preprocessing_profile_id", "base-v1"),
                representation_profile_id=body["representation_profile_id"], hyperparameters=body.get("hyperparameters", {}),
                random_seed=body.get("random_seed", 42),
            )
            return job_manager.start_training_job(training_run=training_run)
        return call(fn)

    @router.get("/training-runs")
    def training_runs():
        return call(repository.list_training_runs)

    @router.get("/training-runs/{training_run_id}")
    def get_training_run(training_run_id: str):
        def fn():
            run = repository.get_training_run(training_run_id)
            if run is None:
                raise FileNotFoundError("TRAINING_RUN_NOT_FOUND")
            return run
        return call(fn)

    @router.delete("/training-runs/{training_run_id}")
    def delete_training_run(training_run_id: str):
        return call(lambda: repository.delete_training_run(training_run_id))

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    @router.post("/training-runs/{training_run_id}/evaluation")
    def evaluate(training_run_id: str, body: dict | None = None):
        min_precision = (body or {}).get("min_identified_precision", 0.9)
        # Advanced mode's manual per-stage button: TEST is only included when
        # the operator explicitly asks for it (e.g. the single model already
        # chosen), never by default -- comparing several candidates this way
        # must stay VALIDATION-only, same as the automatic orchestration.
        # Any include_test=True through this generic, manual route is -- by
        # construction -- never the one automatic single-selection call
        # prepare_and_train() makes internally, so it is always tagged
        # OPT_IN_MULTI_CANDIDATE_COMPARISON, never SINGLE_SELECTION_GUARANTEE.
        include_test = bool((body or {}).get("include_test", False))
        return call(lambda: repository.evaluate_training_run(
            training_run_id, min_identified_precision=min_precision, include_test=include_test,
            test_evaluation_provenance="OPT_IN_MULTI_CANDIDATE_COMPARISON" if include_test else None,
        ))

    # Guided mode's gated entry point for the same action: requires an
    # explicit acknowledge_multiple_comparison_risk=true rather than a bare
    # include_test flag, since Guided mode is meant for an operator who may
    # not already know why comparing several candidates against TEST is a
    # real statistical caveat, not a formality (see StudioRepository's
    # evaluate_training_run_on_test_opt_in docstring).
    @router.post("/training-runs/{training_run_id}/evaluate-on-test-opt-in")
    def evaluate_training_run_on_test_opt_in(training_run_id: str, body: dict | None = None):
        return call(lambda: repository.evaluate_training_run_on_test_opt_in(
            training_run_id, acknowledge_multiple_comparison_risk=bool((body or {}).get("acknowledge_multiple_comparison_risk", False)),
        ))

    @router.get("/training-runs/{training_run_id}/evaluation")
    def get_evaluation(training_run_id: str):
        def fn():
            evaluation = repository.get_evaluation(training_run_id)
            if evaluation is None:
                raise FileNotFoundError("EVALUATION_NOT_RUN_YET")
            return evaluation
        return call(fn)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    @router.post("/training-runs/{training_run_id}/export", status_code=201)
    def export_bundle(training_run_id: str, body: dict):
        def fn():
            manifest, reasons = repository.export_bundle(
                training_run_id=training_run_id, bundle_id=body["bundle_id"], acceptance_criteria=body.get("acceptance_criteria", {}),
                model_card_text=body.get("model_card_text", f"# Model bundle {body['bundle_id']}\n"),
            )
            return {"bundle": dump(manifest), "gate_reasons": reasons}
        return call(fn)

    @router.get("/bundles")
    def bundles():
        return call(lambda: dump_list(repository.list_bundles()))

    @router.get("/bundles/{bundle_id}")
    def get_bundle(bundle_id: str):
        def fn():
            bundle = repository.get_bundle(bundle_id)
            if bundle is None:
                raise FileNotFoundError("BUNDLE_NOT_FOUND")
            return dump(bundle)
        return call(fn)

    @router.delete("/bundles/{bundle_id}")
    def delete_bundle(bundle_id: str):
        return call(lambda: repository.delete_bundle(bundle_id))

    @router.post("/bundles/{bundle_id}/approve")
    def approve_bundle(bundle_id: str):
        return call(lambda: dump(repository.approve_bundle(bundle_id)))

    # Resolution only -- the actual retrain runs through the EXISTING
    # POST /prepare-and-train job (see retrain_reference()'s docstring).
    @router.get("/bundles/{bundle_id}/retrain-reference")
    def retrain_reference(bundle_id: str):
        return call(lambda: repository.retrain_reference(bundle_id))

    # Same idea, but for the Benchmark panel's "Reentrenar (mismas capturas)"
    # action -- works even for a candidate that was never exported to a
    # bundle at all.
    @router.get("/training-runs/{training_run_id}/retrain-reference")
    def retrain_reference_from_training_run(training_run_id: str):
        return call(lambda: repository.retrain_reference_from_training_run(training_run_id))

    # ------------------------------------------------------------------
    # Offline inference
    # ------------------------------------------------------------------

    @router.post("/bundles/{bundle_id}/inference")
    def run_inference(bundle_id: str, body: dict):
        return call(lambda: repository.run_inference(bundle_id=bundle_id, capture_id=body["capture_id"]))

    # ------------------------------------------------------------------
    # Live Monitor: on-demand model check over a short live IQ burst.
    # Deliberately a separate URL namespace from /bundles/{bundle_id} (never
    # /bundles/live-selectable) to avoid any path-matching ambiguity with the
    # existing {bundle_id} route above.
    # ------------------------------------------------------------------

    @router.get("/live-monitor/models")
    def live_selectable_models():
        return call(repository.list_live_selectable_bundles)

    @router.post("/live-monitor/live-check")
    def live_check(body: dict):
        import base64
        import numpy as np

        def fn():
            iq_bytes = base64.b64decode(body["iq_window_base64"])
            iq_window = np.frombuffer(iq_bytes, dtype=np.complex64)
            result = repository.live_check(
                bundle_id=body["bundle_id"], iq_window=iq_window, sample_rate_sps=float(body["sample_rate_sps"]),
                center_frequency_hz=float(body["center_frequency_hz"]), bandwidth_hz=float(body["bandwidth_hz"]),
                sample_format=body["sample_format"],
            )
            return result
        return call(fn)

    # Continuous on-demand live check, wired through the SAME B200 session
    # Live Monitor's own spectrum stream already owns (real_spectrum_stream) --
    # never opens a second SDR session. See real_spectrum_stream.py's
    # enable_ble_live_check/_live_check_worker_loop and
    # spectrum_stream_worker.py's ble_live_check_enabled for the full path.
    # Deliberately imported here (not in spectrum_controller.py) so Live
    # Monitor's own spectrum routes/DI wiring stay completely untouched --
    # this module is the only one with both the repository AND a reason to
    # know about bundles.
    @router.post("/live-monitor/enable/{bundle_id}")
    def enable_live_monitor_check(bundle_id: str):
        from app.infrastructure.sdr.real_spectrum_stream import real_spectrum_stream

        def fn():
            bundle = repository.get_bundle(bundle_id)
            if bundle is None:
                raise FileNotFoundError(f"BUNDLE_NOT_FOUND:{bundle_id}")
            if bundle.approval_status != "APPROVED_FOR_LIVE_PILOT":
                raise ValueError(f"BUNDLE_NOT_APPROVED_FOR_LIVE_PILOT:{bundle_id}")
            real_spectrum_stream.enable_ble_live_check(bundle_id, repository)
            return {"status": "enabled", "bundle_id": bundle_id}
        return call(fn)

    # No bundle_id: full teardown (every currently-watched bundle) --
    # reserved for the panel's own unmount cleanup. A single row's own
    # toggle-off must use the per-bundle route below instead, or it would
    # silently stop every OTHER bundle a different row (or the multi-device
    # watch list) had going.
    @router.post("/live-monitor/disable")
    def disable_live_monitor_check():
        from app.infrastructure.sdr.real_spectrum_stream import real_spectrum_stream
        real_spectrum_stream.disable_ble_live_check()
        return {"status": "disabled"}

    @router.post("/live-monitor/disable/{bundle_id}")
    def disable_live_monitor_check_one(bundle_id: str):
        from app.infrastructure.sdr.real_spectrum_stream import real_spectrum_stream
        real_spectrum_stream.disable_ble_live_check(bundle_id)
        return {"status": "disabled", "bundle_id": bundle_id}

    # Keyed by bundle_id -- every currently-watched bundle's latest result,
    # scored against the same shared burst (see real_spectrum_stream.py's
    # _live_check_worker_loop). Was a single flat result before multi-device
    # watching existed; this is a breaking response-shape change consumed by
    # BleRffiLiveModelPanel.tsx only.
    @router.get("/live-monitor/result")
    def live_monitor_result():
        from app.infrastructure.sdr.real_spectrum_stream import real_spectrum_stream
        return real_spectrum_stream.get_latest_live_check_results()

    return router
