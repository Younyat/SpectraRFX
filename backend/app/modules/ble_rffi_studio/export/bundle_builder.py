"""Fase 5 export: writes every file REQUIRED_BUNDLE_FILES demands, hashes
each one, and hashes the hash-set itself into bundle_sha256. Design
correction #17: a bundle is never auto-approved for the live pilot just
because it loads -- build() can only reach EVALUATED or REJECTED (a real,
computed comparison against frozen acceptance_criteria); moving to
APPROVED_FOR_LIVE_PILOT is a separate, explicit human sign-off step.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import scipy
import sklearn
import torch

from app.infrastructure.ble.capture.ble_offline_replay import read_json, sha256_file, write_json

from ..contracts import CONFIRMATORY_PROVENANCE, REQUIRED_BUNDLE_FILES, DatasetManifest, ModelBundleManifest, SplitManifest, TrainingRun
from ..evaluation import SplitEvaluationReport
from ..preprocessing import resolve_preprocessing_profile

_TORCH_MODEL_TYPES = {"cnn1d", "cnn2d"}


class BundleBuilder:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _save_model(self, bundle_dir: Path, model_type: str, model: Any) -> str:
        if model_type in _TORCH_MODEL_TYPES:
            filename = "model.pt"
            torch.save(model, bundle_dir / filename)
        else:
            filename = "model.joblib"
            joblib.dump(model, bundle_dir / filename)
        return filename

    def build(
        self,
        *,
        bundle_id: str,
        training_run: TrainingRun,
        model: Any,
        label_classes: list[str],
        feature_names: list[str] | None,
        scaler: Any | None = None,
        dataset: DatasetManifest,
        split: SplitManifest,
        evaluation_reports: dict[str, SplitEvaluationReport],
        calibration: dict[str, Any],
        acceptance_criteria: dict[str, Any],
        model_card_text: str,
        code_reference: dict[str, Any],
        created_at: str,
        test_evaluation_provenance: str = "NOT_EVALUATED",
    ) -> tuple[ModelBundleManifest, list[str]]:
        bundle_dir = self.root / bundle_id
        bundle_dir.mkdir(parents=True, exist_ok=True)

        model_filename = self._save_model(bundle_dir, training_run.model_type, model)
        scaler_filename = None
        if scaler is not None:
            scaler_filename = "scaler.joblib"
            joblib.dump(scaler, bundle_dir / scaler_filename)

        write_json(bundle_dir / "model_manifest.json", {
            "model_type": training_run.model_type, "label_classes": label_classes,
            "training_run_id": training_run.training_run_id, "random_seed": training_run.random_seed,
            "model_file": model_filename,
        })
        # Preprocessing-registry correction (2026-08-08): persist the actual
        # resolved flags, not just the bare profile_id string -- resolves
        # eagerly here (raises loudly at export time if training_run somehow
        # cites an unknown profile_id) so this artifact is self-sufficient
        # for reproducing what preprocessing genuinely ran, without a
        # consumer needing to re-read source code.
        resolved_profile = resolve_preprocessing_profile(training_run.base_preprocessing_profile_id)
        write_json(bundle_dir / "preprocessing_config.json", {
            "base_preprocessing_profile_id": training_run.base_preprocessing_profile_id,
            "resolved_flags": dataclasses.asdict(resolved_profile),
        })
        write_json(bundle_dir / "feature_config.json", {
            "representation_profile_id": training_run.representation_profile_id, "feature_names": feature_names or [],
            "scaler_file": scaler_filename,
        })
        write_json(bundle_dir / "label_map.json", {"classes": label_classes})
        write_json(bundle_dir / "thresholds.json", calibration)
        write_json(bundle_dir / "dataset_reference.json", {
            "dataset_id": dataset.dataset_id, "dataset_version": dataset.dataset_version, "dataset_manifest_sha256": dataset.dataset_manifest_sha256,
            "data_origin": dataset.data_origin, "captures": dataset.captures, "sessions": dataset.sessions, "physical_units": dataset.physical_units,
        })
        write_json(bundle_dir / "split_reference.json", {
            "scientific_task": split.scientific_task, "split_manifest_sha256": split.split_manifest_sha256,
            "split_status": split.split_status, "leakage_check_status": split.leakage_check.status,
        })
        write_json(bundle_dir / "evaluation_report.json", {name: dataclasses.asdict(report) for name, report in evaluation_reports.items()})
        write_json(bundle_dir / "runtime_requirements.json", {
            "numpy": np.__version__, "scikit_learn": sklearn.__version__, "scipy": scipy.__version__,
            "torch": torch.__version__ if training_run.model_type in _TORCH_MODEL_TYPES else None,
        })
        write_json(bundle_dir / "input_contract.json", {
            "representation_profile_id": training_run.representation_profile_id,
            "sample_rate_sps_required": True, "expects": "ExampleRecord evidence window (iq_start_sample:iq_end_sample) from the source capture IQ file",
        })
        (bundle_dir / "model_card.md").write_text(model_card_text, encoding="utf-8")
        write_json(bundle_dir / "scientific_basis.json", {"note": "See app/modules/ble_rffi_studio/scientific_basis/technique_registry.json for the full technique/paper registry."})
        write_json(bundle_dir / "calibration_report.json", calibration)
        write_json(bundle_dir / "acceptance_criteria.json", acceptance_criteria)
        write_json(bundle_dir / "code_reference.json", code_reference)

        artifact_hashes: dict[str, str] = {}
        for required_name in REQUIRED_BUNDLE_FILES:
            actual_name = model_filename if required_name == "model_file" else required_name
            artifact_hashes[required_name] = sha256_file(bundle_dir / actual_name)

        bundle_sha256 = hashlib.sha256(json.dumps(artifact_hashes, sort_keys=True).encode("utf-8")).hexdigest()
        approval_status, reasons = self._evaluate_acceptance(acceptance_criteria, evaluation_reports, dataset, split, label_classes, training_run.scientific_task)
        confirmatory_eligible = test_evaluation_provenance == CONFIRMATORY_PROVENANCE
        # Neither REJECTED nor TEST_NOT_EXECUTED may read as ALLOWED just
        # because the data_origin happens to be real -- operational_use is a
        # claim about whether this SPECIFIC bundle is fit to act on, not
        # just about where its data came from. A rejected bundle failed its
        # own frozen acceptance criteria; a TEST_NOT_EXECUTED bundle simply
        # hasn't been verified against TEST yet -- neither is safe to rely
        # on just because the IQ was real B200 (real, confirmed audit
        # finding). Only an explicit TEST evaluation (opt-in or the single
        # recommended-model guarantee) can move a bundle past this.
        operational_use = "FORBIDDEN" if dataset.data_origin == "SYNTHETIC_TEST_ONLY" or approval_status in ("REJECTED", "TEST_NOT_EXECUTED") else "ALLOWED"

        manifest = ModelBundleManifest(
            bundle_id=bundle_id, training_run_id=training_run.training_run_id,
            data_origin=dataset.data_origin, operational_use=operational_use,
            artifact_hashes=artifact_hashes, bundle_sha256=bundle_sha256, approval_status=approval_status, created_at=created_at,
            test_evaluation_provenance=test_evaluation_provenance, confirmatory_eligible=confirmatory_eligible,
        )
        write_json(bundle_dir / "bundle_manifest.json", manifest.model_dump(mode="json"))
        return manifest, reasons

    def _evaluate_acceptance(
        self, acceptance_criteria: dict[str, Any], evaluation_reports: dict[str, SplitEvaluationReport],
        dataset: DatasetManifest, split: SplitManifest, label_classes: list[str], scientific_task: str,
    ) -> tuple[str, list[str]]:
        # Two separate reason buckets on purpose: `reasons` are real, checked
        # gate failures (training/data actually broken -- REJECTED is
        # correct). `test_not_executed_reasons` means every other gate
        # passed and the ONLY open question is that this training_run_id was
        # never TEST-evaluated -- the normal, expected state for every
        # non-recommended prepare_and_train() candidate, not a failure. A
        # bundle with real gate failures is REJECTED even if TEST also
        # wasn't run; a bundle whose ONLY gap is a missing TEST evaluation is
        # TEST_NOT_EXECUTED, never REJECTED.
        reasons: list[str] = []
        test_not_executed_reasons: list[str] = []
        # Real gates, checked again here rather than only trusted from
        # upstream -- a bundle is the artifact someone could hand to a live
        # pilot, so it re-verifies rather than assumes.
        if not dataset.frozen:
            reasons.append("Dataset is not frozen.")
        if split.split_status != "READY":
            reasons.append(f"Split status is {split.split_status}, not READY.")
        if split.leakage_check.status != "PASSED":
            reasons.append(f"Leakage check is {split.leakage_check.status}, not PASSED.")

        # Defense in depth: SplitBuilder._finalize()'s own >=2-TRAIN-classes
        # gate should make this unreachable, but a bundle is the artifact
        # someone could hand to a live pilot -- it must never leave this
        # method un-rejected just because an earlier stage's gate was
        # bypassed or changed. label_classes is the actual set of classes
        # the model was trained on (label_classes.json), not recomputed.
        if len(set(label_classes)) < 2:
            reasons.append(f"TRAINING_DATA_SINGLE_CLASS: model was trained on only {sorted(set(label_classes))}.")
        if scientific_task == "TARGET_VS_BACKGROUND" and "BACKGROUND_ENVIRONMENT" not in label_classes:
            reasons.append("BACKGROUND_CLASS_MISSING: TARGET_VS_BACKGROUND model has no BACKGROUND_ENVIRONMENT class in TRAIN.")
        assignment_ids = {a.example_id for a in split.assignments}
        if not assignment_ids.issubset(set(dataset.example_ids)):
            reasons.append(
                "DATASET_COUNTER_MISMATCH: the split references example_ids not present in the frozen dataset "
                "-- the split was not built from this exact dataset."
            )

        # P0 correction (2026-08-08): this used to only fire when
        # min_test_accuracy was explicitly set in acceptance_criteria, which
        # meant a caller passing acceptance_criteria={} (export_and_approve_
        # all_candidates' automatic path, and the manual export route's own
        # default) could reach EVALUATED -- and then get auto-approved --
        # without TEST ever having been evaluated at all. A bundle with no
        # TEST report is ALWAYS TEST_NOT_EXECUTED now, regardless of whether
        # a minimum was declared; the minimum is only ever checked once a
        # real TEST report exists.
        min_test_accuracy = acceptance_criteria.get("min_test_accuracy")
        test_report = evaluation_reports.get("TEST")
        if test_report is None:
            test_not_executed_reasons.append(
                "TEST_NOT_EXECUTED: this training_run_id has no TEST evaluation yet. Not a failure -- opt in to a "
                "TEST evaluation (evaluate_training_run_on_test_opt_in) to make this bundle approvable, understanding "
                "that doing so permanently marks it OPT_IN_MULTI_CANDIDATE_COMPARISON / not confirmatory_eligible."
            )
        elif min_test_accuracy is not None and (test_report.accuracy is None or test_report.accuracy < min_test_accuracy):
            reasons.append(f"TEST accuracy {test_report.accuracy} below required minimum {min_test_accuracy}.")
        min_validation_accuracy = acceptance_criteria.get("min_validation_accuracy")
        if min_validation_accuracy is not None:
            validation_report = evaluation_reports.get("VALIDATION")
            validation_accuracy = validation_report.accuracy if validation_report else None
            if validation_accuracy is None or validation_accuracy < min_validation_accuracy:
                reasons.append(f"VALIDATION accuracy {validation_accuracy} below required minimum {min_validation_accuracy}.")

        if reasons:
            return "REJECTED", reasons
        if test_not_executed_reasons:
            return "TEST_NOT_EXECUTED", test_not_executed_reasons
        # A ceiling, not a step toward approval: SYNTHETIC_PIPELINE_VERIFIED
        # proves the software pipeline works end to end, nothing about a
        # physical device. approve_for_live_pilot only accepts EVALUATED, so
        # this status can never reach APPROVED_FOR_LIVE_PILOT.
        if dataset.data_origin == "SYNTHETIC_TEST_ONLY":
            return "SYNTHETIC_PIPELINE_VERIFIED", []
        return "EVALUATED", []

    def load_manifest(self, bundle_id: str) -> ModelBundleManifest | None:
        path = self.root / bundle_id / "bundle_manifest.json"
        if not path.is_file():
            return None
        return ModelBundleManifest.model_validate(read_json(path))

    def approve_for_live_pilot(self, manifest: ModelBundleManifest) -> ModelBundleManifest:
        """The explicit, separate human sign-off step. Never reachable from
        build() alone -- a bundle must already be EVALUATED (i.e. it met its
        own frozen acceptance_criteria) before this can run."""
        # Origin check first and alone: it used to also fold in
        # `operational_use == "FORBIDDEN"`, which made every REAL_B200
        # REJECTED/TEST_NOT_EXECUTED bundle (operational_use is FORBIDDEN for
        # those too, see build()) surface this SYNTHETIC-origin message
        # instead of its real, specific reason below -- confusing for a
        # bundle that has nothing to do with synthetic data.
        if manifest.data_origin != "REAL_B200":
            raise ValueError(
                f"CANNOT_APPROVE_A_SYNTHETIC_ORIGIN_BUNDLE_FOR_LIVE_PILOT:{manifest.bundle_id} "
                f"(data_origin={manifest.data_origin}). A model trained on any synthetic data can only ever "
                "reach SYNTHETIC_PIPELINE_VERIFIED -- it proves the software pipeline works, not physical RFFI capability."
            )
        if manifest.approval_status == "TEST_NOT_EXECUTED":
            raise ValueError(
                f"CANNOT_APPROVE_A_BUNDLE_WITH_NO_TEST_EVALUATION:{manifest.bundle_id}. This candidate was never "
                "TEST-evaluated (normal for a non-recommended model) -- opt in to a TEST evaluation for it first, "
                "then re-export, before it can be approved."
            )
        if manifest.approval_status != "EVALUATED":
            raise ValueError(f"CANNOT_APPROVE_A_BUNDLE_THAT_IS_NOT_EVALUATED:{manifest.approval_status}")
        if not manifest.confirmatory_eligible:
            raise ValueError(
                f"CANNOT_APPROVE_A_NON_CONFIRMATORY_BUNDLE_FOR_LIVE_PILOT:{manifest.bundle_id} "
                f"(test_evaluation_provenance={manifest.test_evaluation_provenance}). Its TEST result came from the "
                "opt-in multiple-candidate-comparison path, not the single-selection guarantee -- it is a real, "
                "exploratory result, never a confirmatory one, and can never be promoted to live-pilot approval."
            )
        approved = manifest.model_copy(update={"approval_status": "APPROVED_FOR_LIVE_PILOT"})
        write_json(self.root / manifest.bundle_id / "bundle_manifest.json", approved.model_dump(mode="json"))
        return approved
