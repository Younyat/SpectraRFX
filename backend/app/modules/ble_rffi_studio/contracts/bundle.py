from __future__ import annotations

from typing import Literal

from .capture import DataOrigin
from .common import StudioContract
from .training import OperationalUse

BUNDLE_SCHEMA_VERSION = "ble-rffi-studio-bundle-v1"

# SYNTHETIC_PIPELINE_VERIFIED is a hard ceiling, not a step on the way to
# APPROVED_FOR_LIVE_PILOT: BundleBuilder never assigns EVALUATED to a
# synthetic-origin bundle, and approve_for_live_pilot only accepts EVALUATED,
# so a synthetic bundle structurally cannot reach APPROVED_FOR_LIVE_PILOT.
#
# TEST_NOT_EXECUTED is deliberately distinct from REJECTED: it means every
# real acceptance gate (frozen dataset, split READY, leakage PASSED, >=2
# TRAIN classes, VALIDATION threshold, ...) passed, and the ONLY reason this
# bundle isn't EVALUATED is that min_test_accuracy couldn't be checked
# because this training_run_id was never TEST-evaluated (the normal case for
# every non-recommended candidate from prepare_and_train -- TEST stays
# reserved for the one selected model). REJECTED means a gate was actually
# checked and failed (including TEST accuracy below the floor, once TEST WAS
# run). Conflating the two made a merely-not-yet-tested candidate read as
# "invalid" or "training failed", which it never was.
ApprovalStatus = Literal["DRAFT", "EVALUATED", "SYNTHETIC_PIPELINE_VERIFIED", "APPROVED_FOR_LIVE_PILOT", "REJECTED", "TEST_NOT_EXECUTED"]

# NOT_EVALUATED: this training_run_id never had a TEST evaluation (the
# common case for non-recommended candidates) -- min_test_accuracy cannot be
# checked, so build() rejects it. SINGLE_SELECTION_GUARANTEE: the one model
# prepare_and_train() itself picked from VALIDATION, TEST-evaluated exactly
# once. OPT_IN_MULTI_CANDIDATE_COMPARISON: an operator explicitly chose to
# evaluate this NON-recommended candidate on TEST anyway (see
# StudioRepository.evaluate_training_run_on_test_opt_in), to compare several
# exported models live -- a real, permanent, visible caveat on the bundle,
# never silently indistinguishable from the single-selection guarantee.
TestEvaluationProvenance = Literal["NOT_EVALUATED", "SINGLE_SELECTION_GUARANTEE", "OPT_IN_MULTI_CANDIDATE_COMPARISON"]

# P0 correction (2026-08-08): a bundle is only fit to stand as the paper's
# confirmatory result for its device/task if its TEST number came from the
# single-selection guarantee. OPT_IN_MULTI_CANDIDATE_COMPARISON bundles are
# real, real captures, real TEST accuracy -- but the multiple-comparison
# risk means that number cannot be reported as a confirmatory result, only
# as exploratory. Stored explicitly (not left implicit in
# test_evaluation_provenance) so any future paper-reporting code can filter
# on one obvious boolean without re-deriving the provenance mapping.
CONFIRMATORY_PROVENANCE = "SINGLE_SELECTION_GUARANTEE"

# Every one of these files must exist inside a bundle directory and have an
# entry in artifact_hashes before approval_status can move past DRAFT.
REQUIRED_BUNDLE_FILES = (
    "model_file",
    "model_manifest.json",
    "preprocessing_config.json",
    "feature_config.json",
    "label_map.json",
    "thresholds.json",
    "dataset_reference.json",
    "split_reference.json",
    "evaluation_report.json",
    "runtime_requirements.json",
    "input_contract.json",
    "model_card.md",
    "scientific_basis.json",
    "calibration_report.json",
    "acceptance_criteria.json",
    "code_reference.json",
)


class ModelBundleManifest(StudioContract):
    schema_version: Literal["ble-rffi-studio-bundle-v1"] = BUNDLE_SCHEMA_VERSION
    bundle_id: str
    training_run_id: str
    data_origin: DataOrigin
    operational_use: OperationalUse

    artifact_hashes: dict[str, str] = {}  # filename -> sha256, one entry per REQUIRED_BUNDLE_FILES
    bundle_sha256: str | None = None
    approval_status: ApprovalStatus = "DRAFT"
    test_evaluation_provenance: TestEvaluationProvenance = "NOT_EVALUATED"
    # Derived from test_evaluation_provenance at build time (see
    # CONFIRMATORY_PROVENANCE) -- never approve_for_live_pilot a bundle
    # where this is False (see bundle_builder.py::approve_for_live_pilot).
    confirmatory_eligible: bool = False
    created_at: str
