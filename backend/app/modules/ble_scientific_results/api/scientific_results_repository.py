"""Fase 1: frozen protocol, holdout access log, scientific preflight.

Strictly read-only over ble_rffi_studio's storage root. Every method here
either writes under this module's own `storage/scientific_reports/ble/`
root or appends to its own audit log -- nothing under
`storage/ble_rffi_studio/` is ever opened for writing, only for reading
already-frozen manifests (captures, evidence, datasets, splits, quality
reports) that ble_rffi_studio itself produced and owns.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.infrastructure.ble.capture.ble_capture_metadata import atomic_json
from app.modules.ble_rffi_studio.contracts import CaptureRecord, DatasetManifest, DatasetQualityReport, ExampleRecord, SplitManifest
from app.modules.ble_rffi_studio.preprocessing.base_preprocessing_registry import resolve_preprocessing_profile
from app.modules.ble_rffi_studio.registry.physical_device_registry import PhysicalDeviceRegistry

from ..contracts import (
    AnalysisContract,
    AssociationPolicy,
    DesignCompletenessResult,
    GitDirtyState,
    HoldoutAccessLogEntry,
    HoldoutChainVerificationResult,
    HoldoutGroupAssignment,
    InputArtifactIndex,
    InputSnapshotEntry,
    IntegrityCheckResult,
    LeakageCheckResult,
    PaperCampaignCompletenessResult,
    PaperRunRecord,
    PopulationSeparationResult,
    QualityCheckResult,
    RecordBuildResult,
    ScientificPreflightReport,
)
from ..campaign import build_campaign_accounting as _build_campaign_accounting
from ..figures import build_campaign_figures as _build_campaign_figures
from ..module_logging import build_module_logger
from ..quality import build_quality_summary as _build_quality_summary
from ..records import build_records as _build_records
from ..records import resolve_iq_path
from ..engineering_reports import compute_channel_transport_report as _compute_channel_transport_report
from ..engineering_reports import compute_offline_nearlive_report as _compute_offline_nearlive_report
from .. import paper_figure_aggregations
from ..paper_export import generate_paper_exports
from ..provenance import list_inference_runs as _list_inference_runs
from ..provenance import reconstruct_decision_provenance
from ..statistics.confirmatory_analysis_runner import confirmatory_statistical_plan_to_dict
from ..statistics.confirmatory_analysis_runner import run_confirmatory_statistical_plan as _run_confirmatory_statistical_plan

RUN_SUBDIRS = [
    "00_contract", "01_inputs", "02_integrity", "03_campaign_accounting", "04_quality",
    "05_predictions", "06_statistics", "07_figures", "08_tables", "09_latex",
    "10_forensic_reporting", "11_reproducibility", "12_logs",
]

# RQ2 canonical persistence (2026-08-11) -- must stay in sync with the real
# branch identities training/model_selector.py's `_MODEL_TYPE_TO_RQ2_BRANCH`
# maps every ModelType onto.
_RQ2_KNOWN_BRANCHES = {"engineered_rf", "raw_iq", "stft", "coarse_morphology"}
_RQ2_ANALYSIS_ROLES = ("PRIMARY", "SENSITIVITY", "UNSELECTED")
_RQ2_REQUIRED_BRANCH_FIELDS = ("branch", "analysis_role", "evaluation_domain")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ScientificResultsRepository:
    def __init__(self, root: Path, ble_rffi_studio_root: Path, *, legacy_capture_root: Path | None = None) -> None:
        self.root = root
        self.ble_root = ble_rffi_studio_root
        # Same resolution rule as StudioRepository.resolve_iq_path():
        # CaptureRecord.iq_path is a bare filename (e.g.
        # "BLE-IQ-...sigmf-data"), not an absolute path -- the real
        # directory is legacy_capture_root/<capture_id>/<iq_path>. Defaults
        # to the same location ble_rffi_studio's own module.py wires up, so
        # a caller that only has the ble_rffi_studio storage root doesn't
        # need to know this detail.
        self.legacy_capture_root = legacy_capture_root or (ble_rffi_studio_root.parent / "ble" / "iq_captures")
        self.root.mkdir(parents=True, exist_ok=True)
        self.logger = build_module_logger(self.root)

    def _resolve_iq_path(self, capture: CaptureRecord) -> Path:
        return resolve_iq_path(self.legacy_capture_root, capture)

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    def _protocol_dir(self, protocol_id: str) -> Path:
        if any(part in protocol_id for part in ("/", "\\", "..")):
            raise ValueError("INVALID_PROTOCOL_ID")
        return self.root / "_protocols" / protocol_id

    def _protocol_path(self, protocol_id: str, version: int) -> Path:
        return self._protocol_dir(protocol_id) / f"{version}.json"

    def _run_dir(self, paper_run_id: str) -> Path:
        if any(part in paper_run_id for part in ("/", "\\", "..")):
            raise ValueError("INVALID_PAPER_RUN_ID")
        return self.root / paper_run_id

    def _holdout_log_path(self) -> Path:
        return self.root / "holdout_access_log.jsonl"

    # ------------------------------------------------------------------
    # Protocol freeze
    # ------------------------------------------------------------------

    def _existing_protocol_versions(self, protocol_id: str) -> list[int]:
        directory = self._protocol_dir(protocol_id)
        if not directory.is_dir():
            return []
        versions = []
        for path in directory.glob("*.json"):
            try:
                versions.append(int(path.stem))
            except ValueError:
                continue
        return versions

    def _git_provenance(self) -> tuple[str, GitDirtyState]:
        cwd = Path(__file__).resolve().parent
        try:
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True, timeout=10, check=True,
            ).stdout.strip()
            status = subprocess.run(
                ["git", "status", "--porcelain"], cwd=cwd, capture_output=True, text=True, timeout=10, check=True,
            ).stdout
            dirty: GitDirtyState = "DIRTY" if status.strip() else "CLEAN"
            return commit, dirty
        except Exception:
            # Fail closed: an environment where git provenance cannot be
            # determined is never reported as CLEAN.
            return "UNKNOWN", "DIRTY"

    def _software_environment_digest(self) -> str:
        packages = sorted(
            f"{dist.metadata['Name']}=={dist.version}" for dist in importlib.metadata.distributions() if dist.metadata.get("Name")
        )
        payload = "\n".join([f"python=={sys.version}"] + packages)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _policy_hash(self, module_path: Path) -> str:
        return hashlib.sha256(module_path.read_bytes()).hexdigest()

    def freeze_protocol(self, payload: dict[str, Any]) -> AnalysisContract:
        import app.modules.ble_rffi_studio.evidence.evidence_stage as evidence_stage_module
        import app.modules.ble_rffi_studio.quality.dataset_analyzer as dataset_analyzer_module
        import app.modules.ble_rffi_studio.dataset.dataset_builder as dataset_builder_module

        protocol_id = payload.get("protocol_id") or AnalysisContract.make_protocol_id(
            project_id=payload.get("project_id", "BLE-SCIENTIFIC-RESULTS"),
            seed_material=payload.get("protocol_name") or uuid.uuid4().hex,
        )
        existing_versions = self._existing_protocol_versions(protocol_id)
        next_version = (max(existing_versions) + 1) if existing_versions else 1

        git_commit, git_dirty = self._git_provenance()

        required = ["hardware_profile_id", "receiver_profile_hash", "interpretation_matrix_hash"]
        missing = [field for field in required if not payload.get(field)]
        if missing:
            raise ValueError(f"ANALYSIS_CONTRACT_MISSING_REQUIRED_FIELDS:{','.join(missing)}")

        # P0.4 correction (2026-08-08): this used to always be a hash of
        # evidence_stage.py's own SOURCE CODE -- identical whether the
        # association *threshold* changed or not, and identical whether any
        # calibration had ever succeeded. Now it identifies a real,
        # calibrated, frozen AssociationPolicy when one exists (see
        # find_frozen_association_policy); the NO_CALIBRATED_POLICY_YET:
        # prefix makes the absence of one self-evident from the hash string
        # itself, rather than silently indistinguishable from a real policy.
        frozen_policy = self.find_frozen_association_policy()
        association_policy_hash = (
            frozen_policy.policy_hash if frozen_policy is not None
            else f"NO_CALIBRATED_POLICY_YET:{self._policy_hash(Path(evidence_stage_module.__file__))}"
        )
        contract = AnalysisContract(
            protocol_id=protocol_id, protocol_version=next_version, creation_timestamp_utc=utc_now(),
            git_commit=git_commit, git_dirty_state=git_dirty, software_environment_digest=self._software_environment_digest(),
            hardware_profile_id=payload["hardware_profile_id"], receiver_profile_hash=payload["receiver_profile_hash"],
            device_population=payload.get("device_population", {}), device_ids=payload.get("device_ids", []),
            firmware_hashes=payload.get("firmware_hashes", {}), channels=payload.get("channels", []),
            campaign_schedule=payload.get("campaign_schedule", {}), intervention_schedule=payload.get("intervention_schedule", {}),
            content_variants=payload.get("content_variants", []),
            association_policy_hash=association_policy_hash,
            quality_policy_hash=self._policy_hash(Path(dataset_analyzer_module.__file__)),
            dataset_policy_hash=self._policy_hash(Path(dataset_builder_module.__file__)),
            # Empty unless the caller already commits this protocol to one
            # specific, already-frozen split -- otherwise the protocol fixes
            # the *policy*, and a concrete split is attached per paper_run_id
            # at create_run() time, verified against this field in
            # run_preflight() when it is non-empty.
            split_manifest_hash=payload.get("split_manifest_hash", ""),
            model_branch_definitions=payload.get("model_branch_definitions", []),
            feature_policy=payload.get("feature_policy", {}), signal_region_policy=payload.get("signal_region_policy", {}),
            phase_compensation_policy=payload.get("phase_compensation_policy", {}),
            hyperparameter_search_space=payload.get("hyperparameter_search_space", {}),
            model_selection_rule=payload.get("model_selection_rule", ""), random_seeds=payload.get("random_seeds", []),
            number_of_restarts=payload.get("number_of_restarts", 0),
            threshold_selection_rule=payload.get("threshold_selection_rule", ""), abstention_rule=payload.get("abstention_rule", ""),
            calibration_rule=payload.get("calibration_rule", ""), multiplicity_family=payload.get("multiplicity_family", {}),
            statistical_tests=payload.get("statistical_tests", []), effect_thresholds=payload.get("effect_thresholds", {}),
            non_inferiority_margins=payload.get("non_inferiority_margins", {}),
            minimum_independent_blocks=payload.get("minimum_independent_blocks", {}),
            interpretation_matrix_hash=payload["interpretation_matrix_hash"],
            rq2_primary_branch=payload.get("rq2_primary_branch"), rq2_branch_selection_rule=payload.get("rq2_branch_selection_rule"),
            rq3_primary_analysis=payload.get("rq3_primary_analysis"), rq4_primary_analysis=payload.get("rq4_primary_analysis"),
            sensitivity_analyses=payload.get("sensitivity_analyses", []),
            rq3_reset_control_definition=payload.get("rq3_reset_control_definition"),
            rq4_representation_definitions=payload.get("rq4_representation_definitions", {}),
            decision_window_duration_s=payload.get("decision_window_duration_s"), minimum_eligible_bursts=payload.get("minimum_eligible_bursts"),
            score_aggregation_rule=payload.get("score_aggregation_rule"), threshold_selection_procedure=payload.get("threshold_selection_procedure"),
            non_inferiority_margin=payload.get("non_inferiority_margin"), non_inferiority_direction=payload.get("non_inferiority_direction"),
            alpha=payload.get("alpha"), confirmatory_hypotheses=payload.get("confirmatory_hypotheses", []),
            holm_family=payload.get("holm_family", []), decision_rule=payload.get("decision_rule"),
            future_test_access_policy_ref=payload.get("future_test_access_policy_ref"),
        )
        contract = contract.model_copy(update={"contract_sha256": contract.content_hash(exclude={"contract_sha256"})})
        atomic_json(self._protocol_path(protocol_id, next_version), contract.model_dump(mode="json"))
        self.logger.info("protocol frozen protocol_id=%s version=%s", protocol_id, next_version)
        return contract

    def get_protocol(self, protocol_id: str, version: int | None = None) -> AnalysisContract:
        target_version = version or max(self._existing_protocol_versions(protocol_id), default=None)
        if target_version is None:
            raise FileNotFoundError(f"PROTOCOL_NOT_FOUND:{protocol_id}")
        path = self._protocol_path(protocol_id, target_version)
        if not path.is_file():
            raise FileNotFoundError(f"PROTOCOL_VERSION_NOT_FOUND:{protocol_id}:{target_version}")
        return AnalysisContract.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def list_protocol_versions(self, protocol_id: str) -> list[AnalysisContract]:
        return [self.get_protocol(protocol_id, version) for version in sorted(self._existing_protocol_versions(protocol_id))]

    # ------------------------------------------------------------------
    # Protocol freeze (explicit, ceremonial operation -- 2026-08-09)
    # ------------------------------------------------------------------
    #
    # Deliberately separate from freeze_protocol() above: that method is the
    # flexible, repeatedly-called mechanism every intermediate protocol
    # snapshot already uses (association calibration, guided validation,
    # ...), and real, passing tests rely on calling it twice for the same
    # protocol_id with no extra ceremony (test_protocol_freeze.py). This is
    # the "confirmatory readiness" ceremony the user's protocol-freeze
    # close-out explicitly asked for: it does not build a new AnalysisContract,
    # it VALIDATES an already-frozen one is complete enough to gate FUTURE
    # TEST behind, and records that validation, append-only, in
    # protocol_freeze_ledger.jsonl -- a real, immutable, hash-linked artifact.

    _CONFIRMATORY_READINESS_FIELDS = (
        "rq2_primary_branch", "rq2_branch_selection_rule", "rq3_primary_analysis", "rq4_primary_analysis",
        "rq3_reset_control_definition", "decision_window_duration_s", "minimum_eligible_bursts",
        "score_aggregation_rule", "threshold_selection_procedure", "non_inferiority_margin",
        "non_inferiority_direction", "alpha", "decision_rule", "future_test_access_policy_ref",
    )

    def _protocol_freeze_ledger_path(self) -> Path:
        return self.root / "protocol_freeze_ledger.jsonl"

    def list_protocol_freezes(self) -> list[dict[str, Any]]:
        path = self._protocol_freeze_ledger_path()
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def missing_confirmatory_readiness_fields(self, contract: AnalysisContract) -> list[str]:
        """Field names still None/empty on `contract` that
        execute_protocol_freeze() requires before it will accept this as the
        definitive, FUTURE-TEST-gating protocol. Never invents a value --
        only reports what is missing."""
        missing = []
        for field_name in self._CONFIRMATORY_READINESS_FIELDS:
            value = getattr(contract, field_name)
            if value is None or value == "":
                missing.append(field_name)
        if not contract.rq4_representation_definitions:
            missing.append("rq4_representation_definitions")
        if not contract.confirmatory_hypotheses:
            missing.append("confirmatory_hypotheses")
        if not contract.holm_family:
            missing.append("holm_family")
        return missing

    def execute_protocol_freeze(
        self, protocol_id: str, *, version: int | None = None, new_version_reason: str | None = None,
    ) -> dict[str, Any]:
        """The explicit protocol-freeze operation: validates confirmatory
        readiness (raises PROTOCOL_FREEZE_MISSING_REQUIRED_FIELDS if
        anything in _CONFIRMATORY_READINESS_FIELDS is still unset -- never
        fabricates a value to pass this check) and appends one immutable
        ledger entry hash-linked to the contract's own contract_sha256.
        Refusing to freeze this protocol_id again without an explicit
        new_version_reason is the whole point: any substantive change after
        the first successful freeze must be a NEW protocol_version with a
        stated reason, never a silent overwrite of what this ledger already
        recorded."""
        contract = self.get_protocol(protocol_id, version)
        missing = self.missing_confirmatory_readiness_fields(contract)
        if missing:
            raise ValueError(f"PROTOCOL_FREEZE_MISSING_REQUIRED_FIELDS:{','.join(missing)}")

        previous = [entry for entry in self.list_protocol_freezes() if entry["protocol_id"] == protocol_id]
        if previous and not new_version_reason:
            raise ValueError(
                f"PROTOCOL_VERSION_CONFLICT:protocol_id={protocol_id} was already frozen "
                f"(version {previous[-1]['protocol_version']}) -- pass new_version_reason to freeze a new version explicitly."
            )

        entry = {
            "protocol_id": protocol_id, "protocol_version": contract.protocol_version,
            "contract_sha256": contract.contract_sha256, "frozen_at": utc_now(),
            "new_version_reason": new_version_reason, "is_new_version_of": previous[-1]["protocol_version"] if previous else None,
        }
        path = self._protocol_freeze_ledger_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        self.logger.info("protocol freeze executed protocol_id=%s version=%s", protocol_id, contract.protocol_version)
        return entry

    # ------------------------------------------------------------------
    # Study status / paper readiness (2026-08-10) -- pure reporting, reads
    # only. Every field here is either a direct pass-through of an
    # already-real repository method, or a presence/absence check against a
    # real file on disk -- never a new scientific computation. This is what
    # the read-only paper-progress dashboard is built on.
    # ------------------------------------------------------------------

    def _list_all_protocol_ids(self) -> list[str]:
        protocols_dir = self.root / "_protocols"
        if not protocols_dir.is_dir():
            return []
        return sorted(p.name for p in protocols_dir.iterdir() if p.is_dir())

    def get_study_status(self, protocol_id: str | None = None) -> dict[str, Any]:
        """Aggregates real, already-implemented reads into one summary --
        never computes a new scientific value. `protocol_id` resolution:
        the caller's choice if given; otherwise the most-recently-modified
        protocol directory on disk if exactly one or more exist (documented
        heuristic, not a scientific selection), else None (no protocol
        frozen at all yet)."""
        git_sha, git_dirty = self._git_provenance()

        all_protocol_ids = self._list_all_protocol_ids()
        resolved_protocol_id = protocol_id
        if resolved_protocol_id is None and all_protocol_ids:
            protocols_dir = self.root / "_protocols"
            resolved_protocol_id = max(all_protocol_ids, key=lambda pid: (protocols_dir / pid).stat().st_mtime)

        contract: Any = None
        contract_status = "NO_DATA"
        missing_fields: list[str] = []
        if resolved_protocol_id is not None:
            try:
                contract = self.get_protocol(resolved_protocol_id)
            except FileNotFoundError:
                contract = None
        if contract is not None:
            missing_fields = self.missing_confirmatory_readiness_fields(contract)
            contract_status = "INCOMPLETE" if missing_fields else "COMPLETE"

        freezes = [e for e in self.list_protocol_freezes() if resolved_protocol_id is None or e["protocol_id"] == resolved_protocol_id]
        protocol_freeze_status = "COMPLETE" if freezes else "NOT_STARTED"
        if freezes:
            contract_status = "FROZEN"

        frozen_policy = self.find_frozen_association_policy()
        association_status = "FROZEN" if frozen_policy is not None else "NONE"

        future_test_accesses = [e for e in self.list_holdout_access_log() if "FUTURE_TEST" in (e.access_path or "")]
        holdout_status = "OPENED" if future_test_accesses else "UNTOUCHED"

        real_capture_count = len(list((self.ble_root / "captures").glob("*.json"))) if (self.ble_root / "captures").is_dir() else 0

        # Simple, documented phase label -- derived purely from which real
        # artifacts exist above, never a computed scientific milestone.
        if not freezes and contract_status in ("NO_DATA", "INCOMPLETE"):
            current_phase = "B. Real hardware qualification / early study (pre-AnalysisContract)"
        elif not freezes and contract_status == "COMPLETE":
            current_phase = "O. AnalysisContract complete, protocol freeze pending"
        elif freezes and holdout_status == "UNTOUCHED":
            current_phase = "Q-S. Protocol frozen, definitive/FUTURE acquisition pending"
        else:
            current_phase = "T+. FUTURE opened, confirmatory analysis phase"

        return {
            "git_sha": git_sha, "git_dirty_state": git_dirty,
            "protocol_id": resolved_protocol_id, "all_protocol_ids": all_protocol_ids,
            "protocol_version": contract.protocol_version if contract is not None else None,
            "contract_status": contract_status, "contract_sha256": contract.contract_sha256 if contract is not None and contract.contract_sha256 else None,
            "missing_confirmatory_readiness_fields": missing_fields,
            "association_policy_status": association_status,
            "protected_future_test_status": holdout_status,
            "protocol_freeze_status": protocol_freeze_status,
            "real_capture_count": real_capture_count,
            "current_phase": current_phase,
            "generated_at": utc_now(),
        }

    # Study Control Center (2026-08-11, normalized 2026-08-11): the 17-phase
    # workflow, in dependency order. `mechanism_state`/`launcher_state` are
    # STATIC facts about what code exists (never computed from runtime
    # data) -- READY means the real backend function/route (mechanism) or
    # the real Study Control Center UI (launcher) exists and is tested;
    # PARTIAL means it exists but is incomplete (e.g. a read-only view with
    # no launcher to compute new data); NOT_STARTED means neither exists.
    # `execution_state` (COMPLETE/IN_PROGRESS/NOT_RUN) is the only one
    # computed from real runtime artifacts below -- see `signals`.
    _STUDY_CONTROL_CENTER_PHASES: tuple[tuple[str, str, tuple[str, ...], str, str, str], ...] = (
        ("01", "Hardware Qualification", (), "Methods", "READY", "READY"),
        ("02", "Physical Unit Qualification", ("01",), "Methods/Qualification", "READY", "READY"),
        ("03", "Association Calibration", ("01",), "Methods/Association", "READY", "READY"),
        ("04", "Qualification Pilot", ("01", "02", "03"), "Methods", "READY", "READY"),
        ("05", "Study Sizing", ("04",), "Methods", "READY", "READY"),
        ("06", "DEVELOPMENT Campaign", ("04", "05"), "Methods", "READY", "READY"),
        ("07", "VALIDATION Campaign", ("06",), "Methods", "READY", "READY"),
        ("08", "RQ2 Benchmark", ("07",), "Results/RQ2", "READY", "READY"),
        ("09", "Analysis Contract", ("08",), "Methods", "READY", "READY"),
        ("10", "Protocol Freeze", ("09",), "Methods", "READY", "READY"),
        ("11", "Definitive Controlled Campaign", ("10",), "Methods", "READY", "READY"),
        ("12", "Protected FUTURE", ("10",), "Methods", "READY", "READY"),
        ("13", "Confirmatory Analysis", ("11", "12"), "Results", "READY", "READY"),
        ("14", "S1 Channel Transport", ("10",), "Engineering", "READY", "READY"),
        ("15", "S2 Offline/Near-Live", ("10",), "Engineering", "READY", "READY"),
        ("16", "Provenance Audit", ("13",), "Methods", "READY", "READY"),
        ("17", "Paper Export", ("13", "14", "15", "16"), "All", "READY", "READY"),
    )

    def get_study_control_center_status(self) -> dict[str, Any]:
        """Read-only aggregation of the 17-phase experimental workflow --
        computes no new science, only real gating logic over already-real
        getters (get_study_status/list_runs/list_protocol_freezes/
        find_frozen_association_policy/list_inference_runs/the per-run
        canonical report getters). A phase's `state` is BLOCKED (with real
        `blocking_reasons`) whenever it has not started and at least one of
        its prerequisites is not COMPLETE -- never a generic disabled
        button with no explanation."""
        git_sha, _ = self._git_provenance()
        study_status = self.get_study_status()
        runs = self.list_runs()
        latest_run = max(runs, key=lambda r: r.created_at) if runs else None

        qualification_report = None
        qualification_path = self.root / "campaign_qualification_preflight_report.json"
        if qualification_path.is_file():
            qualification_report = json.loads(qualification_path.read_text(encoding="utf-8"))

        registry = PhysicalDeviceRegistry(self.ble_root / "registry")
        units = registry.list_physical_units()
        confirmed_units = [u for u in units if u.same_model_confirmation == "CONFIRMED"]

        guided_validation_attempts = list((self.root / "guided_validation").glob("*/association_policy.json")) if (self.root / "guided_validation").is_dir() else []

        # Phase 04 (Qualification Pilot): a real PaperCampaignSchedule with
        # qualification_only=True. Reads the LATEST version of every
        # schedule found -- never guesses which one is "the" pilot when
        # several exist, just reports the most advanced real one.
        pilot_schedules: list[Any] = []
        schedules_dir = self.ble_root / "paper_campaign" / "schedules"
        if schedules_dir.is_dir():
            for schedule_dir in schedules_dir.iterdir():
                versions = sorted(int(p.stem) for p in schedule_dir.glob("*.json") if p.stem.isdigit())
                if not versions:
                    continue
                data = json.loads((schedule_dir / f"{versions[-1]}.json").read_text(encoding="utf-8"))
                if data.get("qualification_only"):
                    pilot_schedules.append(data)
        pilot_executed_counts = [(sum(1 for e in s["entries"] if e["executed"]), len(s["entries"])) for s in pilot_schedules]
        pilot_fully_executed = any(executed == total and total > 0 for executed, total in pilot_executed_counts)
        pilot_partially_executed = any(executed > 0 for executed, _ in pilot_executed_counts)

        sizing_decision = self.get_study_sizing_decision()
        rq2_report = self.get_rq2_representation_comparison_report(latest_run.paper_run_id) if latest_run else None
        # Phases 06/07 real completion signals (2026-08-17 -- previously
        # hardcoded False with no signal at all, confirmed by direct
        # inspection). 06 (Development): the dataset+split pair the latest
        # real run points at is actually built and READY -- proves the
        # development-stage artifact chain (dataset -> split) exists, not
        # just that captures exist. 07 (Validation): a real VALIDATION-
        # domain evaluation was produced for that run (RQ1 or RQ2, whichever
        # ran) -- a real precondition of phase 08's own RQ2-specific check,
        # kept as its own signal since a run can have RQ1 without RQ2 yet.
        development_split_ready = False
        if latest_run is not None:
            try:
                development_split_ready = self._load_split(latest_run.dataset_id, latest_run.dataset_version, latest_run.scientific_task).split_status == "READY"
            except FileNotFoundError:
                development_split_ready = False
        rq1_report_for_latest = self.get_rq1_acquisition_dependence_report(latest_run.paper_run_id) if latest_run else None
        validation_evaluated = bool(rq1_report_for_latest) or bool(rq2_report and rq2_report.get("branches"))
        confirmatory_future_report = self.get_confirmatory_future_analysis_report(latest_run.paper_run_id) if latest_run else None
        channel_transport_report = self.get_channel_transport_report(latest_run.paper_run_id) if latest_run else None
        offline_nearlive_report = self.get_offline_nearlive_report(latest_run.paper_run_id) if latest_run else None
        inference_runs = self.list_inference_runs()
        export_manifest = self.get_paper_export_manifest()

        signals: dict[str, dict[str, Any]] = {
            "01": {
                "completed": qualification_report is not None and qualification_report.get("overall_status") == "READY",
                "in_progress": qualification_report is not None and qualification_report.get("overall_status") in ("PRELIMINARY", "NOT_READY"),
                "real_data_available": qualification_report is not None,
                "artifacts": ["campaign_qualification_preflight_report.json"] if qualification_report else [],
            },
            "02": {
                "completed": bool(units) and len(confirmed_units) == len(units),
                "in_progress": bool(confirmed_units) and len(confirmed_units) < len(units),
                "real_data_available": bool(units),
                "artifacts": ["ble_rffi_studio/registry/physical_units"] if units else [],
            },
            "03": {
                "completed": study_status["association_policy_status"] == "FROZEN",
                "in_progress": bool(guided_validation_attempts) and study_status["association_policy_status"] != "FROZEN",
                "real_data_available": bool(guided_validation_attempts),
                "artifacts": ["guided_validation/*/association_policy.json"] if guided_validation_attempts else [],
            },
            "04": {
                "completed": pilot_fully_executed,
                "in_progress": pilot_partially_executed and not pilot_fully_executed,
                "real_data_available": bool(pilot_schedules),
                "artifacts": ["ble_rffi_studio/paper_campaign/schedules/*"] if pilot_schedules else [],
            },
            "05": {
                "completed": sizing_decision is not None,
                "in_progress": False, "real_data_available": sizing_decision is not None,
                "artifacts": ["study_sizing_decision.json"] if sizing_decision else [],
            },
            "06": {
                "completed": development_split_ready,
                "in_progress": bool(latest_run) and not development_split_ready,
                "real_data_available": study_status["real_capture_count"] > 0,
                "artifacts": [f"splits/{latest_run.dataset_id}__{latest_run.dataset_version}__{latest_run.scientific_task}.json"] if development_split_ready and latest_run else [],
            },
            "07": {
                "completed": validation_evaluated,
                "in_progress": development_split_ready and not validation_evaluated,
                "real_data_available": validation_evaluated,
                "artifacts": ["rq1_acquisition_dependence_report.json"] if rq1_report_for_latest else (["rq2_representation_comparison_report.json"] if validation_evaluated else []),
            },
            "08": {
                "completed": bool(rq2_report and rq2_report.get("branches")),
                "in_progress": False, "real_data_available": bool(rq2_report),
                "artifacts": ["rq2_representation_comparison_report.json"] if rq2_report else [],
            },
            "09": {
                "completed": study_status["contract_status"] in ("COMPLETE", "FROZEN"),
                "in_progress": study_status["contract_status"] == "INCOMPLETE",
                "real_data_available": study_status["contract_status"] != "NO_DATA",
                "artifacts": ["_protocols"] if study_status["contract_status"] != "NO_DATA" else [],
            },
            "10": {
                "completed": study_status["protocol_freeze_status"] == "COMPLETE",
                "in_progress": False, "real_data_available": study_status["protocol_freeze_status"] == "COMPLETE",
                "artifacts": ["protocol_freeze_ledger.jsonl"] if study_status["protocol_freeze_status"] == "COMPLETE" else [],
            },
            "11": {"completed": False, "in_progress": False, "real_data_available": False, "artifacts": []},
            "12": {
                "completed": study_status["protected_future_test_status"] == "OPENED",
                "in_progress": False, "real_data_available": study_status["protected_future_test_status"] == "OPENED",
                "artifacts": ["holdout_access_log.jsonl"] if study_status["protected_future_test_status"] == "OPENED" else [],
            },
            "13": {
                "completed": bool(confirmatory_future_report),
                "in_progress": False, "real_data_available": bool(confirmatory_future_report),
                "artifacts": ["confirmatory_future_analysis_report.json"] if confirmatory_future_report else [],
            },
            "14": {
                "completed": bool(channel_transport_report and channel_transport_report.get("per_channel")),
                "in_progress": False, "real_data_available": bool(channel_transport_report),
                "artifacts": ["channel_transport_report.json"] if channel_transport_report else [],
            },
            "15": {
                "completed": bool(offline_nearlive_report and offline_nearlive_report.get("analytical_agreement")),
                "in_progress": False, "real_data_available": bool(offline_nearlive_report),
                "artifacts": ["offline_nearlive_report.json"] if offline_nearlive_report else [],
            },
            "16": {
                "completed": bool(inference_runs),
                "in_progress": False, "real_data_available": bool(inference_runs),
                "artifacts": ["inference_runs/"] if inference_runs else [],
            },
            "17": {
                "completed": bool(export_manifest and export_manifest.get("generated_count")),
                "in_progress": False, "real_data_available": bool(export_manifest),
                "artifacts": ["paper_exports/export_manifest.json"] if export_manifest else [],
            },
        }

        # Phase-specific real next-action pointers -- overrides the generic
        # "RUN {label}" fallback whenever the real mechanism lives somewhere
        # else already (never implies a standalone action that doesn't
        # exist). "01" and "02" have real dedicated launchers in THIS tab.
        next_action_overrides = {
            "03": "Usar la pestana Guided Validation (POST /guided-validation) -- freezing de politica de asociacion es una etapa de ese job real, no una accion aislada",
        }
        labels_by_id = {phase_id: label for phase_id, label, _prereqs, _section, _mech, _launch in self._STUDY_CONTROL_CENTER_PHASES}
        phases: list[dict[str, Any]] = []
        for phase_id, label, prereq_ids, paper_section, mechanism_state, launcher_state in self._STUDY_CONTROL_CENTER_PHASES:
            signal = signals[phase_id]
            incomplete_prereqs = [labels_by_id[pid] for pid in prereq_ids if not signals[pid]["completed"]]
            # execution_state (2026-08-11 normalization): the ONLY one of the
            # three states computed from real runtime artifacts -- never
            # conflated with mechanism_state/launcher_state, which are
            # static facts about what code exists. Blocking is a property of
            # execution readiness, never of the mechanism/launcher
            # themselves (those either exist or don't).
            if signal["completed"]:
                execution_state = "COMPLETE"
            elif signal["in_progress"]:
                execution_state = "IN_PROGRESS" if phase_id != "01" else ("PRELIMINARY" if qualification_report and qualification_report.get("overall_status") == "PRELIMINARY" else "BLOCKED")
            elif incomplete_prereqs:
                execution_state = "BLOCKED"
            else:
                execution_state = "NOT_RUN" if launcher_state == "READY" else "BLOCKED"
            # `state` kept for backward compatibility with existing UI gating
            # logic (READY/BLOCKED drive next_allowed_operation) -- the 3
            # explicit fields below are the ones a caller should read to
            # avoid conflating mechanism/launcher/execution.
            state = "READY" if execution_state == "NOT_RUN" else execution_state
            phases.append({
                "phase_id": phase_id, "label": label, "state": state,
                "mechanism_state": mechanism_state, "launcher_state": launcher_state, "execution_state": execution_state,
                "prerequisites": [labels_by_id[pid] for pid in prereq_ids],
                "blocking_reasons": incomplete_prereqs if state == "BLOCKED" else [],
                "real_data_available": signal["real_data_available"],
                "run_id": latest_run.paper_run_id if latest_run else None,
                "git_sha": git_sha, "protocol_version": study_status["protocol_version"],
                "artifacts": signal["artifacts"], "paper_section": paper_section,
                "next_allowed_operation": (next_action_overrides.get(phase_id) or f"RUN {label.upper()}") if state == "READY" else None,
            })

        operationally_closed = sum(1 for p in phases if p["mechanism_state"] == "READY" and p["launcher_state"] == "READY")
        return {
            "schema_version": "ble-scientific-results-study-control-center-v2", "generated_at": utc_now(), "phases": phases,
            # "Operationally closed" = mechanism AND launcher are both real
            # (READY) -- i.e. runnable end-to-end from this UI with zero
            # hidden CLI step -- REGARDLESS of whether it has been run for
            # real yet (execution_state is reported separately per phase,
            # never folded into this count).
            "phases_with_mechanism_and_launcher_ready": operationally_closed,
            "phases_total": len(phases),
        }

    # ------------------------------------------------------------------
    # Phase 09: Analysis Contract Readiness (2026-08-11) -- NOT a generic
    # JSON editor. Every field the confirmatory contract needs is either
    # DERIVED (a real, already-frozen artifact or a real, frozen constant
    # elsewhere in the codebase -- this method only reads it, never invents
    # a value) or SCIENTIST_DECISION (a genuine judgment call that software
    # must never auto-decide -- see record_scientist_decision below).
    # ------------------------------------------------------------------

    _SCIENTIST_DECISION_FIELD_IDS: tuple[str, ...] = (
        "rq2_primary_branch", "rq3_primary_analysis", "rq4_primary_analysis", "sensitivity_analyses",
        "preprocessing_profile", "rq3_reset_control_definition", "rq3_sample_size", "non_inferiority_margin",
        "non_inferiority_direction", "alpha", "confirmatory_hypotheses", "holm_family",
    )

    def _scientist_decisions_path(self) -> Path:
        return self.root / "scientist_decisions.jsonl"

    def record_scientist_decision(
        self, *, field_id: str, selected_value: Any, rationale: str, evidence_used: str,
        decided_by: str | None = None, protocol_version_candidate: int | None = None,
    ) -> dict[str, Any]:
        """Append-only record of a genuine human scientific judgment call --
        never auto-derived, never overwritten in place (a later decision for
        the same field_id is a NEW entry; get_latest_scientist_decisions()
        resolves latest-per-field). Refuses a decision with no real
        rationale (same discipline as persist_study_sizing_decision), and
        refuses evidence_used that cites the protected FUTURE TEST holdout
        -- no scientific decision made before protocol freeze may be
        justified by data that must remain untouched until confirmatory
        analysis."""
        if field_id not in self._SCIENTIST_DECISION_FIELD_IDS:
            raise ValueError(f"UNKNOWN_SCIENTIST_DECISION_FIELD:{field_id}")
        if not rationale.strip():
            raise ValueError("RATIONALE_REQUIRED_TO_RECORD_A_SCIENTIST_DECISION")
        if evidence_used and "future" in evidence_used.lower():
            raise ValueError("SCIENTIST_DECISION_MUST_NOT_CITE_PROTECTED_FUTURE_TEST_AS_EVIDENCE")
        record = {
            "schema_version": "ble-scientific-results-scientist-decision-v1",
            "field_id": field_id, "selected_value": selected_value, "rationale": rationale,
            "evidence_used": evidence_used, "decided_by": decided_by,
            "protocol_version_candidate": protocol_version_candidate, "decided_at": utc_now(),
        }
        path = self._scientist_decisions_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        self.logger.info("scientist decision recorded field_id=%s decided_by=%s", field_id, decided_by)
        return record

    def list_scientist_decisions(self, field_id: str | None = None) -> list[dict[str, Any]]:
        path = self._scientist_decisions_path()
        if not path.is_file():
            return []
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [r for r in records if field_id is None or r["field_id"] == field_id]

    def get_latest_scientist_decisions(self) -> dict[str, dict[str, Any]]:
        """Append-only log, chronological write order -> later entries for
        the same field_id legitimately overwrite the dict entry here, which
        is exactly "latest wins" without needing a separate timestamp sort."""
        latest: dict[str, dict[str, Any]] = {}
        for record in self.list_scientist_decisions():
            latest[record["field_id"]] = record
        return latest

    def get_analysis_contract_readiness(self) -> dict[str, Any]:
        """Per-field readiness for the AnalysisContract (Phase 09). status is
        restricted to COMPLETE/INCOMPLETE/SCIENTIST_DECISION_REQUIRED --
        never a fabricated READY. DERIVED fields mirror a real, already-
        frozen artifact or a real, frozen constant elsewhere in the codebase
        (never a second, independently-chosen definition -- see
        contracts/protocol.py's own "mirrors ble_rffi_studio's real, frozen
        constants" comment for decision_window_duration_s/
        minimum_eligible_bursts/score_aggregation_rule/
        threshold_selection_procedure). SCIENTIST_DECISION fields are
        resolved only from record_scientist_decision()'s append-only log --
        this method never guesses one."""
        from app.modules.ble_rffi_studio.api.studio_repository import FROZEN_TRAINING_SEEDS
        from app.modules.ble_rffi_studio.inference.decision_windows import (
            AGGREGATION_RULE, DEFAULT_MINIMUM_ELIGIBLE_BURSTS, DEFAULT_WINDOW_DURATION_S,
        )

        study_status = self.get_study_status()
        control_center = self.get_study_control_center_status()
        phases_by_id = {p["phase_id"]: p for p in control_center["phases"]}
        frozen_policy = self.find_frozen_association_policy()
        decisions = self.get_latest_scientist_decisions()

        def _derived(field_id: str, label: str, value: Any, source: str, evidence_maturity: str | None, complete: bool) -> dict[str, Any]:
            return {
                "field_id": field_id, "label": label, "kind": "DERIVED",
                "value": value, "source": source, "evidence_maturity": evidence_maturity,
                "status": "COMPLETE" if complete else "INCOMPLETE", "rationale": None,
            }

        def _scientist(field_id: str, label: str) -> dict[str, Any]:
            decision = decisions.get(field_id)
            if decision is None:
                return {
                    "field_id": field_id, "label": label, "kind": "SCIENTIST_DECISION",
                    "value": None, "source": None, "evidence_maturity": None,
                    "status": "SCIENTIST_DECISION_REQUIRED", "rationale": None,
                }
            return {
                "field_id": field_id, "label": label, "kind": "SCIENTIST_DECISION",
                "value": decision["selected_value"],
                "source": f"scientist decision by {decision.get('decided_by') or 'UNKNOWN'} at {decision['decided_at']}",
                "evidence_maturity": decision.get("evidence_used"), "status": "COMPLETE",
                "rationale": decision["rationale"],
            }

        fields = [
            _derived(
                "stochastic_seeds", "Stochastic seeds", list(FROZEN_TRAINING_SEEDS),
                "ble_rffi_studio.api.studio_repository.FROZEN_TRAINING_SEEDS", "QUALIFICATION", True,
            ),
            _derived(
                "rq4_analytical_regions", "RQ4 analytical regions", ["FULL_BURST", "ADVA_EXCLUDED", "PRE_PDU"],
                "fixed convention already used by confirmatory_analysis_runner.py/paper_export.py", "QUALIFICATION", True,
            ),
            _derived(
                "packet_conditions", "Packet conditions", ["ORIGINAL", "CONTROLLED_VARIANT"],
                "ble_rffi_studio.contracts.capture.PacketCondition", "QUALIFICATION", True,
            ),
            _derived(
                "decision_window_duration_s", "Decision-window duration (s)", DEFAULT_WINDOW_DURATION_S,
                "ble_rffi_studio.inference.decision_windows.DEFAULT_WINDOW_DURATION_S", "QUALIFICATION", True,
            ),
            _derived(
                "minimum_eligible_bursts", "Minimum eligible bursts", DEFAULT_MINIMUM_ELIGIBLE_BURSTS,
                "ble_rffi_studio.inference.decision_windows.DEFAULT_MINIMUM_ELIGIBLE_BURSTS", "QUALIFICATION", True,
            ),
            _derived(
                "score_aggregation_rule", "Score aggregation rule", AGGREGATION_RULE,
                "ble_rffi_studio.inference.decision_windows.AGGREGATION_RULE", "QUALIFICATION", True,
            ),
            _derived(
                "threshold_selection_procedure", "Operating-threshold procedure",
                frozen_policy.selection_rule if frozen_policy else None,
                "AssociationPolicy.selection_rule (frozen calibration policy)",
                "VALIDATION" if frozen_policy else None, frozen_policy is not None,
            ),
            _derived(
                "operating_threshold_ms", "Operating threshold, ms (when available)",
                frozen_policy.threshold_ms if frozen_policy else None,
                "AssociationPolicy.threshold_ms (frozen calibration policy)",
                "VALIDATION" if frozen_policy else None, frozen_policy is not None,
            ),
            _scientist("rq2_primary_branch", "RQ2 primary branch"),
            _scientist("rq3_primary_analysis", "RQ3 primary analysis"),
            _scientist("rq4_primary_analysis", "RQ4 primary analysis"),
            _scientist("sensitivity_analyses", "Sensitivity analyses"),
            _scientist("preprocessing_profile", "Preprocessing profile"),
            _scientist("rq3_reset_control_definition", "RQ3 intervention (RESET/CONTROL) definition"),
            _scientist("non_inferiority_margin", "Non-inferiority margin"),
            _scientist("non_inferiority_direction", "Non-inferiority direction"),
            _scientist("alpha", "Alpha"),
            _scientist("confirmatory_hypotheses", "Confirmatory hypotheses"),
            _scientist("holm_family", "Holm family / multiplicity rule"),
        ]

        def _gate(gate_id: str, label: str, complete: bool) -> dict[str, Any]:
            return {"gate_id": gate_id, "label": label, "status": "COMPLETE" if complete else "INCOMPLETE"}

        readiness_gates = [
            _gate("qualification_state", "Hardware qualification (Phase 01)", phases_by_id["01"]["execution_state"] == "COMPLETE"),
            _gate("association_policy_state", "Association policy frozen (Phase 03)", study_status["association_policy_status"] == "FROZEN"),
            _gate("development_completion", "DEVELOPMENT campaign complete (Phase 06)", phases_by_id["06"]["execution_state"] == "COMPLETE"),
            _gate("validation_completion", "VALIDATION campaign complete (Phase 07)", phases_by_id["07"]["execution_state"] == "COMPLETE"),
            _gate("rq2_primary_selection", "RQ2 primary branch selected", "rq2_primary_branch" in decisions),
            _gate("protected_future_untouched", "Protected FUTURE untouched", study_status["protected_future_test_status"] == "UNTOUCHED"),
        ]

        missing = [f["field_id"] for f in fields if f["status"] != "COMPLETE"] + [g["gate_id"] for g in readiness_gates if g["status"] != "COMPLETE"]
        protocol_freeze_readiness = {"status": "READY" if not missing else "BLOCKED", "missing": missing}

        return {
            "schema_version": "ble-scientific-results-analysis-contract-readiness-v1",
            "generated_at": utc_now(),
            "fields": fields,
            "readiness_gates": readiness_gates,
            "protocol_freeze_readiness": protocol_freeze_readiness,
        }

    def _any_run_artifact_exists(self, relative_path: str) -> bool:
        return any((run_dir / relative_path).is_file() for run_dir in self.root.iterdir() if run_dir.is_dir() and not run_dir.name.startswith("_"))

    def _paper_readiness_row(
        self, *, element: str, mechanism: str, canonical_artifact: str, available: bool,
        maturity: str | None, requires_confirmatory: bool, confirmatory: bool,
        statistics_ready: bool, table_ready: bool, figure_ready: bool,
    ) -> dict[str, Any]:
        if not available:
            paper_evidence_status = "DATA_PENDING"
        elif requires_confirmatory and not confirmatory:
            paper_evidence_status = "PRELIMINARY"
        else:
            paper_evidence_status = "COMPLETE"
        return {
            "manuscript_element": element, "scientific_mechanism": mechanism, "evidence_maturity": maturity,
            "canonical_artifact": canonical_artifact, "available": available, "confirmatory": confirmatory,
            "statistics_ready": statistics_ready, "table_ready": table_ready, "figure_ready": figure_ready,
            "paper_evidence_status": paper_evidence_status,
        }

    # Fast-closure pass (2026-08-12): rewritten to the user's own exact
    # 8-column / 16-row taxonomy. `scientific_mechanism` is a static fact
    # (mirrors get_study_control_center_status's own mechanism_state
    # convention -- READY means the real backend producer exists and is
    # tested, never re-derived from live introspection). `evidence_maturity`
    # reuses the SAME QUALIFICATION/DEVELOPMENT/VALIDATION/CONFIRMATORY/
    # ENGINEERING taxonomy every per-RQ tab's own EvidenceMaturityBadge
    # already uses -- never a second taxonomy. `available`/`confirmatory`
    # are always computed from real, already-real artifacts on disk --
    # never fabricated for a row with no real data yet.
    def get_paper_readiness(self) -> list[dict[str, Any]]:
        has_protocol_freeze = bool(self.list_protocol_freezes())
        rows: list[dict[str, Any]] = []

        qualification_available = self._any_run_artifact_exists("campaign_qualification_preflight_report.json")
        rows.append(self._paper_readiness_row(
            element="Qualification", mechanism="run_campaign_qualification_preflight", canonical_artifact="campaign_qualification_preflight_report.json",
            available=qualification_available, maturity="QUALIFICATION", requires_confirmatory=False, confirmatory=False,
            statistics_ready=False, table_ready=qualification_available, figure_ready=False,
        ))

        association_policy = self.find_frozen_association_policy()
        rows.append(self._paper_readiness_row(
            element="Association", mechanism="find_frozen_association_policy", canonical_artifact="association_policy (frozen calibration policy)",
            available=association_policy is not None, maturity="VALIDATION", requires_confirmatory=False, confirmatory=False,
            statistics_ready=False, table_ready=association_policy is not None, figure_ready=False,
        ))

        sizing_decision = self.get_study_sizing_decision()
        rows.append(self._paper_readiness_row(
            element="Experimental Design", mechanism="get_study_sizing_decision", canonical_artifact="study_sizing_decision.json",
            available=sizing_decision is not None, maturity="QUALIFICATION", requires_confirmatory=False, confirmatory=False,
            statistics_ready=False, table_ready=sizing_decision is not None, figure_ready=False,
        ))

        dataset_ready = any(
            (self.ble_root / "quality_reports" / p.name).is_file()
            and json.loads((self.ble_root / "quality_reports" / p.name).read_text(encoding="utf-8")).get("gate_decision") == "ACCEPTED_FOR_TRAINING"
            for p in (self.ble_root / "datasets").glob("*.json")
        ) if (self.ble_root / "datasets").is_dir() else False
        rows.append(self._paper_readiness_row(
            element="Dataset", mechanism="DatasetBuilder + DatasetAnalyzer quality gate", canonical_artifact="datasets/*.json + quality_reports/*.json (gate_decision=ACCEPTED_FOR_TRAINING)",
            available=dataset_ready, maturity="DEVELOPMENT", requires_confirmatory=False, confirmatory=False,
            statistics_ready=False, table_ready=dataset_ready, figure_ready=False,
        ))

        for element, validation_artifact, future_artifact in (
            ("RQ1", "06_statistics/rq1_acquisition_dependence_report.json", "06_statistics/confirmatory_future_analysis_report.json"),
            ("RQ2", "06_statistics/rq2_representation_comparison_report.json", "06_statistics/confirmatory_future_analysis_report.json"),
            ("RQ3", "06_statistics/confirmatory_statistical_plan_report.json", "06_statistics/confirmatory_future_analysis_report.json"),
            ("RQ4", "06_statistics/confirmatory_statistical_plan_report.json", "06_statistics/confirmatory_future_analysis_report.json"),
            ("Coverage", "06_statistics/coverage_analysis_report.json", "06_statistics/confirmatory_future_analysis_report.json"),
        ):
            confirmatory = has_protocol_freeze and self._any_run_artifact_exists(future_artifact)
            available = confirmatory or self._any_run_artifact_exists(validation_artifact)
            rows.append(self._paper_readiness_row(
                element=element, mechanism=f"{element} canonical producer + confirmatory_future_analysis fallback", canonical_artifact=f"{future_artifact} (CONFIRMATORY) / {validation_artifact} (VALIDATION)",
                available=available, maturity=("CONFIRMATORY" if confirmatory else ("VALIDATION" if available else None)),
                requires_confirmatory=True, confirmatory=confirmatory,
                statistics_ready=available, table_ready=available, figure_ready=available,
            ))

        sensitivity_available = self._any_run_artifact_exists("06_statistics/sensitivity_report.json")
        rows.append(self._paper_readiness_row(
            element="Sensitivity", mechanism="run_sensitivity_analysis", canonical_artifact="06_statistics/sensitivity_report.json",
            available=sensitivity_available, maturity="VALIDATION", requires_confirmatory=False, confirmatory=False,
            statistics_ready=sensitivity_available, table_ready=sensitivity_available, figure_ready=sensitivity_available,
        ))

        s1_available = self._any_run_artifact_exists("06_statistics/channel_transport_report.json")
        rows.append(self._paper_readiness_row(
            element="S1", mechanism="compute_channel_transport_report", canonical_artifact="06_statistics/channel_transport_report.json",
            available=s1_available, maturity="ENGINEERING", requires_confirmatory=False, confirmatory=False,
            statistics_ready=s1_available, table_ready=s1_available, figure_ready=s1_available,
        ))

        runs = self.list_runs()
        s2_report = self.get_offline_nearlive_report(runs[0].paper_run_id) if runs else None
        s2_measured = bool(s2_report and s2_report.get("analytical_agreement") is not None)
        rows.append(self._paper_readiness_row(
            element="S2", mechanism="compute_offline_nearlive_report", canonical_artifact="06_statistics/offline_nearlive_report.json",
            available=s2_measured, maturity="ENGINEERING", requires_confirmatory=False, confirmatory=False,
            statistics_ready=s2_measured, table_ready=s2_measured, figure_ready=False,
        ))

        provenance_available = bool(self.list_inference_runs())
        rows.append(self._paper_readiness_row(
            element="Provenance", mechanism="reconstruct_decision_provenance", canonical_artifact="on-demand chain reconstruction over real inference_runs",
            available=provenance_available, maturity="VALIDATION", requires_confirmatory=False, confirmatory=False,
            statistics_ready=False, table_ready=provenance_available, figure_ready=False,
        ))

        rq_rows = {r["manuscript_element"]: r for r in rows if r["manuscript_element"] in ("RQ1", "RQ2", "RQ3", "RQ4", "Coverage")}
        results_available = all(r["available"] for r in rq_rows.values())
        results_confirmatory = all(r["confirmatory"] for r in rq_rows.values())
        rows.append(self._paper_readiness_row(
            element="Results", mechanism="aggregate: RQ1-4 + Coverage canonical producers", canonical_artifact="RQ1-4 + Coverage canonical reports (aggregate)",
            available=results_available, maturity=("CONFIRMATORY" if results_confirmatory else ("VALIDATION" if results_available else None)),
            requires_confirmatory=True, confirmatory=results_confirmatory,
            statistics_ready=results_available, table_ready=results_available, figure_ready=results_available,
        ))

        study_status_available = (self.root / "paper_exports" / "study_status.json").exists()
        for element in ("Discussion", "Conclusion"):
            rows.append(self._paper_readiness_row(
                element=element, mechanism="narrative section, written manually from the above rows", canonical_artifact="paper_exports/study_status.json",
                available=study_status_available, maturity=None, requires_confirmatory=False, confirmatory=False,
                statistics_ready=False, table_ready=False, figure_ready=False,
            ))
        return rows

    # ------------------------------------------------------------------
    # Campaign qualification preflight (2026-08-09) -- distinct from
    # run_preflight() above, which checks an already-frozen dataset/split
    # against disk. This checks whether the PLATFORM MECHANISM is ready for
    # a live definitive campaign: association state, RQ3/RQ4 readiness,
    # holdout integrity, and (where the caller supplies real evidence)
    # hardware/quality signals -- never fabricates a check it has no real
    # signal for, and never opens FUTURE TEST.
    # ------------------------------------------------------------------

    # The 11 gates the user's protocol-freeze close-out (point 2, 2026-08-10)
    # explicitly requires. A REQUIRED gate that is NOT_CHECKED must NEVER
    # let overall_status become READY -- only PRELIMINARY (nothing has
    # actively failed, but not everything has been verified) or NOT_READY
    # (something actively failed). Informational-only items (the granular
    # crc/eligible-bursts/abstention numbers) are reported but never gate
    # overall_status on their own -- they roll up into the required
    # "capture_continuity_and_quality_summary" gate instead.
    _REQUIRED_QUALIFICATION_GATES = (
        "b200_detected", "receiver_identity", "qualified_acquisition_profile", "channel_frequency_consistency",
        "capture_continuity_and_quality_summary", "source_iq_digest", "holdout_untouched", "association_state",
        "eq6_7_smoke_test_on_real_iq", "rq3_readiness", "rq4_eligibility",
    )

    def run_campaign_qualification_preflight(
        self, *,
        b200_detected: bool | None = None, receiver_identity_confirmed: bool | None = None,
        qualified_receiver_profile: dict[str, Any] | None = None,
        channel_frequency_integrity_ok: bool | None = None,
        capture_continuity_ok: bool | None = None, quality_summary_reviewed: bool | None = None,
        crc_valid_packet_yield: float | None = None, eligible_bursts_per_decision_window: float | None = None,
        abstention_rate: float | None = None,
        iq_digest_verified: bool | None = None,
        real_pre_post_pairs: list[Any] | None = None,
        rq4_eligible_device_count: int | None = None, rq4_total_device_count: int | None = None,
        paper_eq6_7_smoke_test_passed: bool | None = None,
    ) -> dict[str, Any]:
        items: dict[str, dict[str, Any]] = {}

        def _bool_item(name: str, value: bool | None, *, true_reason: str, false_reason: str) -> None:
            if value is None:
                items[name] = {"status": "NOT_CHECKED", "detail": "not supplied"}
            else:
                items[name] = {"status": "READY" if value else "NOT_READY", "detail": true_reason if value else false_reason}

        _bool_item("b200_detected", b200_detected, true_reason="real device detected", false_reason="no B200 detected")
        _bool_item(
            "receiver_identity", receiver_identity_confirmed,
            true_reason="receiver_identity_id resolved from a real device-queried serial", false_reason="receiver identity could not be confirmed",
        )
        items["qualified_acquisition_profile"] = (
            {"status": "READY", "detail": qualified_receiver_profile} if qualified_receiver_profile
            else {"status": "NOT_CHECKED", "detail": "not supplied"}
        )
        _bool_item(
            "channel_frequency_consistency", channel_frequency_integrity_ok,
            true_reason="channel<->frequency mapping verified", false_reason="channel<->frequency mismatch found",
        )

        # Informational sub-metrics, never gate overall_status by themselves
        # -- they roll up into the one required
        # capture_continuity_and_quality_summary gate below.
        if crc_valid_packet_yield is not None:
            items["crc_valid_packet_yield"] = {"status": "INFO", "detail": crc_valid_packet_yield}
        if eligible_bursts_per_decision_window is not None:
            items["eligible_bursts_per_decision_window"] = {"status": "INFO", "detail": eligible_bursts_per_decision_window}
        if abstention_rate is not None:
            items["abstention_insufficient_evidence_rate"] = {"status": "INFO", "detail": abstention_rate}

        if quality_summary_reviewed is None or capture_continuity_ok is None:
            items["capture_continuity_and_quality_summary"] = {"status": "NOT_CHECKED", "detail": "not supplied"}
        elif not capture_continuity_ok:
            items["capture_continuity_and_quality_summary"] = {"status": "NOT_READY", "detail": "discontinuities found"}
        elif not quality_summary_reviewed:
            items["capture_continuity_and_quality_summary"] = {"status": "NOT_READY", "detail": "quality summary not reviewed/accepted"}
        else:
            items["capture_continuity_and_quality_summary"] = {"status": "READY", "detail": "no unexpected discontinuities; quality summary reviewed"}

        _bool_item("source_iq_digest", iq_digest_verified, true_reason="iq_sha256 verified against real bytes", false_reason="iq_sha256 mismatch")

        frozen_policy = self.find_frozen_association_policy()
        items["association_state"] = (
            {"status": "READY", "detail": frozen_policy.policy_hash} if frozen_policy is not None
            else {"status": "NOT_READY", "detail": "find_frozen_association_policy() returned None -- real, current, not a bug"}
        )

        # RQ3 readiness requires the caller to actually have run
        # build_pre_post_pairs() and supplied the real result -- previously
        # this defaulted to "MECHANISM_READY" unconditionally, which could
        # never be blocking; that was itself the bug this correction closes.
        if real_pre_post_pairs is None:
            items["rq3_readiness"] = {"status": "NOT_CHECKED", "detail": "not supplied -- caller must run build_pre_post_pairs() first"}
        else:
            valid_pairs = [p for p in real_pre_post_pairs if getattr(p, "valid", False)]
            items["rq3_readiness"] = {
                "status": "READY",
                "detail": f"build_pre_post_pairs() executed: {len(valid_pairs)}/{len(real_pre_post_pairs)} real pair(s) valid (0 valid pairs is still a real, checked result, not a blocker by itself)",
            }

        if rq4_total_device_count is None:
            items["rq4_eligibility"] = {"status": "NOT_CHECKED", "detail": "not supplied"}
        else:
            items["rq4_eligibility"] = {
                "status": "READY" if (rq4_eligible_device_count or 0) > 0 else "NOT_READY",
                "detail": f"{rq4_eligible_device_count or 0}/{rq4_total_device_count} device(s) marked RQ4 ELIGIBLE",
            }

        future_test_accesses = [e for e in self.list_holdout_access_log() if "FUTURE_TEST" in (e.access_path or "")]
        items["holdout_untouched"] = (
            {"status": "READY", "detail": "0 FUTURE_TEST accesses logged"} if not future_test_accesses
            else {"status": "NOT_READY", "detail": f"{len(future_test_accesses)} FUTURE_TEST access(es) already logged"}
        )

        _bool_item(
            "eq6_7_smoke_test_on_real_iq", paper_eq6_7_smoke_test_passed,
            true_reason="apply_base_preprocessing_with_provenance smoke test APPLIED on a real burst",
            false_reason="smoke test did not reach APPLIED",
        )

        required_statuses = {name: items[name]["status"] for name in self._REQUIRED_QUALIFICATION_GATES}
        if any(status == "NOT_READY" for status in required_statuses.values()):
            overall = "NOT_READY"
        elif any(status == "NOT_CHECKED" for status in required_statuses.values()):
            overall = "PRELIMINARY"
        else:
            overall = "READY"
        reasons = [f"{name}: {status}" for name, status in required_statuses.items() if status != "READY"]

        report = {
            "schema_version": "ble-scientific-results-campaign-qualification-preflight-v2",
            "generated_at": utc_now(), "overall_status": overall, "required_gates": list(self._REQUIRED_QUALIFICATION_GATES),
            "reasons": reasons, "items": items,
        }
        atomic_json(self.root / "campaign_qualification_preflight_report.json", report)
        self.logger.info("campaign qualification preflight overall_status=%s", overall)
        return report

    # ------------------------------------------------------------------
    # Study Control Center, phase 05 (2026-08-11): Study Sizing. Wires the
    # already-real, previously-unwired statistics/power_simulation.py
    # (closed_form_power_two_proportions/evaluate_design_sufficiency/
    # find_minimum_sufficient_design) -- this repository computes nothing
    # new, it only calls those pure functions and persists the caller's
    # explicit sizing DECISION (never auto-selected).
    # ------------------------------------------------------------------

    @staticmethod
    def _design_evaluation_to_dict(evaluation: Any) -> dict[str, Any]:
        design = evaluation.design
        return {
            "design": {
                "n_units": design.n_units, "n_days": design.n_days, "n_captures_per_unit_day": design.n_captures_per_unit_day,
                "icc_unit": design.icc_unit, "icc_day": design.icc_day,
                "total_captures": design.total_captures, "design_effect": design.design_effect, "effective_captures": design.effective_captures,
            },
            "power": evaluation.power, "verdict": evaluation.verdict,
        }

    def evaluate_study_sizing_candidates(
        self, *, candidate_designs: list[dict[str, Any]], p1: float, p2: float, alpha: float = 0.05, target_power: float = 0.8,
    ) -> dict[str, Any]:
        from ..statistics.power_simulation import HierarchicalDesign, evaluate_design_sufficiency, find_minimum_sufficient_design
        designs = [HierarchicalDesign(**candidate) for candidate in candidate_designs]
        evaluations = [evaluate_design_sufficiency(d, p1=p1, p2=p2, alpha=alpha, target_power=target_power) for d in designs]
        minimum_sufficient = find_minimum_sufficient_design(designs, p1=p1, p2=p2, alpha=alpha, target_power=target_power)
        return {
            "p1": p1, "p2": p2, "alpha": alpha, "target_power": target_power,
            "evaluations": [self._design_evaluation_to_dict(e) for e in evaluations],
            "minimum_sufficient_design": self._design_evaluation_to_dict(minimum_sufficient) if minimum_sufficient else None,
        }

    def persist_study_sizing_decision(
        self, *, chosen_design: dict[str, Any], p1: float, p2: float, alpha: float = 0.05, target_power: float = 0.8,
        rationale: str, decided_by: str | None = None,
    ) -> dict[str, Any]:
        """The sizing DECISION is always an explicit, reasoned human choice
        -- this never auto-persists find_minimum_sufficient_design()'s
        answer, and refuses to record a decision with no real rationale."""
        if not rationale.strip():
            raise ValueError("RATIONALE_REQUIRED_TO_RECORD_A_STUDY_SIZING_DECISION")
        from ..statistics.power_simulation import HierarchicalDesign, evaluate_design_sufficiency
        design = HierarchicalDesign(**chosen_design)
        evaluation = evaluate_design_sufficiency(design, p1=p1, p2=p2, alpha=alpha, target_power=target_power)
        record = {
            "schema_version": "ble-scientific-results-study-sizing-decision-v1",
            **self._design_evaluation_to_dict(evaluation),
            "p1": p1, "p2": p2, "alpha": alpha, "target_power": target_power,
            "rationale": rationale, "decided_by": decided_by, "decided_at": utc_now(),
        }
        atomic_json(self.root / "study_sizing_decision.json", record)
        self.logger.info("study sizing decision recorded verdict=%s power=%.3f", evaluation.verdict, evaluation.power)
        return record

    def get_study_sizing_decision(self) -> dict[str, Any] | None:
        path = self.root / "study_sizing_decision.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    # ------------------------------------------------------------------
    # Holdout access log -- append-only, hash-chained, project-wide
    # ------------------------------------------------------------------

    def log_holdout_access(
        self, *, actor: str, process: str, access_type: str, access_path: str, resource_id: str,
        resource_hash: str | None, reason: str, paper_run_id: str | None, analysis_contract_hash: str | None,
    ) -> HoldoutAccessLogEntry:
        existing = self.list_holdout_access_log()
        previous_entry_hash = existing[-1].entry_hash if existing else None
        sequence_number = (existing[-1].sequence_number + 1) if existing else 1

        draft = HoldoutAccessLogEntry(
            sequence_number=sequence_number, previous_entry_hash=previous_entry_hash,
            entry_hash="", analysis_contract_hash=analysis_contract_hash, paper_run_id=paper_run_id,
            actor=actor, process=process, access_type=access_type, access_path=access_path,
            resource_id=resource_id, resource_hash=resource_hash, timestamp_utc=utc_now(), reason=reason,
        )
        entry = draft.model_copy(update={"entry_hash": draft.content_hash(exclude={"entry_hash"})})

        path = self._holdout_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.model_dump(mode="json"), sort_keys=True) + "\n")
        self.logger.info("holdout access logged seq=%s resource_id=%s actor=%s reason=%s", sequence_number, resource_id, actor, reason)
        return entry

    def list_holdout_access_log(self) -> list[HoldoutAccessLogEntry]:
        path = self._holdout_log_path()
        if not path.is_file():
            return []
        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                entries.append(HoldoutAccessLogEntry.model_validate(json.loads(line)))
        return entries

    def verify_holdout_access_chain(self) -> HoldoutChainVerificationResult:
        """Recomputes every entry_hash and re-checks every
        previous_entry_hash link against the entry that actually precedes
        it. Detects: deletion (a gap in sequence_number), modification (a
        stored entry_hash that no longer matches its own recomputed hash),
        and reordering/insertion (a previous_entry_hash that does not equal
        the real prior entry's entry_hash). See this module's docstring for
        the exact scope of what this chain does and does not prove."""
        entries = self.list_holdout_access_log()
        if not entries:
            return HoldoutChainVerificationResult(status="EMPTY", entry_count=0)

        findings: list[str] = []
        broken_at: int | None = None
        expected_sequence = 1
        expected_previous_hash: str | None = None
        for entry in entries:
            if entry.sequence_number != expected_sequence:
                findings.append(f"Expected sequence_number={expected_sequence}, found {entry.sequence_number} -- entry deleted, reordered, or inserted.")
                broken_at = broken_at or entry.sequence_number
            if entry.previous_entry_hash != expected_previous_hash:
                findings.append(f"sequence_number={entry.sequence_number}: previous_entry_hash={entry.previous_entry_hash!r} does not match the actual prior entry's hash {expected_previous_hash!r}.")
                broken_at = broken_at or entry.sequence_number
            recomputed = entry.content_hash(exclude={"entry_hash"})
            if entry.entry_hash != recomputed:
                findings.append(f"sequence_number={entry.sequence_number}: stored entry_hash does not match recomputed hash -- entry was modified after being written.")
                broken_at = broken_at or entry.sequence_number
            expected_sequence = entry.sequence_number + 1
            expected_previous_hash = entry.entry_hash

        status = "BROKEN" if findings else "VALID"
        return HoldoutChainVerificationResult(status=status, entry_count=len(entries), broken_at_sequence=broken_at, findings=findings)

    # ------------------------------------------------------------------
    # Fase 1 closure item 10: real holdout groups -- mechanism only, no
    # real 20-day campaign data exists yet to populate FUTURE_TEST with.
    # ------------------------------------------------------------------

    def _holdout_groups_dir(self, dataset_id: str, dataset_version: str) -> Path:
        if any(part in dataset_id or part in dataset_version for part in ("/", "\\", "..")):
            raise ValueError("INVALID_DATASET_IDENTITY")
        return self.root / "_holdout_groups" / f"{dataset_id}__{dataset_version}"

    def freeze_holdout_groups(
        self, *, dataset_id: str, dataset_version: str, group: str,
        physical_unit_ids: list[str] | None = None, day_ids: list[str] | None = None, session_ids: list[str] | None = None,
    ) -> HoldoutGroupAssignment:
        frozen_at = utc_now()
        draft = HoldoutGroupAssignment(
            assignment_id=HoldoutGroupAssignment.make_assignment_id(dataset_id=dataset_id, dataset_version=dataset_version, group=group, frozen_at=frozen_at),
            dataset_id=dataset_id, dataset_version=dataset_version, group=group,
            physical_unit_ids=physical_unit_ids or [], day_ids=day_ids or [], session_ids=session_ids or [],
            frozen_at=frozen_at, group_manifest_sha256="",
        )
        assignment = draft.model_copy(update={"group_manifest_sha256": draft.content_hash(exclude={"group_manifest_sha256"})})
        directory = self._holdout_groups_dir(dataset_id, dataset_version)
        atomic_json(directory / f"{assignment.assignment_id}.json", assignment.model_dump(mode="json"))
        self.logger.info("holdout group frozen dataset=%s/%s group=%s assignment_id=%s", dataset_id, dataset_version, group, assignment.assignment_id)
        return assignment

    def list_holdout_groups(self, dataset_id: str, dataset_version: str) -> list[HoldoutGroupAssignment]:
        directory = self._holdout_groups_dir(dataset_id, dataset_version)
        if not directory.is_dir():
            return []
        assignments = [HoldoutGroupAssignment.model_validate(json.loads(path.read_text(encoding="utf-8"))) for path in sorted(directory.glob("*.json"))]
        return sorted(assignments, key=lambda a: a.frozen_at, reverse=True)

    def read_group(
        self, dataset_id: str, dataset_version: str, group: str, *, actor: str, process: str, reason: str, paper_run_id: str | None = None,
    ) -> HoldoutGroupAssignment | None:
        """FUTURE_TEST reads are ALWAYS logged through the same chained
        holdout access log Fase 1 already built -- no other read path for
        FUTURE_TEST exists in this repository. TRAIN/VALIDATION reads are
        not gated (they are exactly what preprocessing/model selection is
        allowed to see)."""
        assignments = [a for a in self.list_holdout_groups(dataset_id, dataset_version) if a.group == group]
        if group == "FUTURE_TEST":
            self.log_holdout_access(
                actor=actor, process=process, access_type="READ_GROUP", access_path=f"holdout_groups/{dataset_id}/{dataset_version}/FUTURE_TEST",
                resource_id=f"{dataset_id}__{dataset_version}__FUTURE_TEST", resource_hash=assignments[0].group_manifest_sha256 if assignments else None,
                reason=reason, paper_run_id=paper_run_id, analysis_contract_hash=None,
            )
        return assignments[0] if assignments else None

    # ------------------------------------------------------------------
    # Paper runs
    # ------------------------------------------------------------------

    def create_run(self, *, protocol_id: str, protocol_version: int | None, campaign_id: str, dataset_id: str, dataset_version: str, scientific_task: str) -> PaperRunRecord:
        contract = self.get_protocol(protocol_id, protocol_version)  # raises if not frozen

        created_at = utc_now()
        paper_run_id = PaperRunRecord.make_paper_run_id(protocol_id=contract.protocol_id, created_at=created_at)
        run_dir = self._run_dir(paper_run_id)
        for subdir in RUN_SUBDIRS:
            (run_dir / subdir).mkdir(parents=True, exist_ok=True)

        # A read-only copy of the exact frozen contract this run is bound
        # to, so the run directory is self-contained and legible without
        # cross-referencing the _protocols/ index.
        atomic_json(run_dir / "00_contract" / "analysis_contract.json", contract.model_dump(mode="json"))

        dataset = self._load_dataset(dataset_id, dataset_version)
        split = self._load_split(dataset_id, dataset_version, scientific_task)
        quality_report = self._load_quality_report(dataset_id, dataset_version)

        git_commit, _ = self._git_provenance()
        run = PaperRunRecord(
            paper_run_id=paper_run_id, campaign_id=campaign_id, protocol_id=contract.protocol_id, protocol_version=contract.protocol_version,
            dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=scientific_task,
            dataset_fingerprint=dataset.dataset_manifest_sha256, split_fingerprint=split.split_manifest_sha256,
            analysis_code_commit=git_commit, analysis_environment_hash=self._software_environment_digest(),
            storage_path=str(run_dir), created_at=created_at,
        )
        atomic_json(run_dir / "run.json", run.model_dump(mode="json"))
        atomic_json(run_dir / "artifact_index.json", {"schema_version": "ble-scientific-results-artifact-index-v1", "paper_run_id": paper_run_id, "artifacts": {}})
        atomic_json(run_dir / "result_summary.json", {"schema_version": "ble-scientific-results-summary-v1", "paper_run_id": paper_run_id})
        self._snapshot_run_inputs(run_dir, paper_run_id=paper_run_id, dataset=dataset, split=split, quality_report=quality_report)
        self.logger.info("run created paper_run_id=%s protocol_id=%s dataset=%s/%s", paper_run_id, protocol_id, dataset_id, dataset_version)
        return run

    def _snapshot_run_inputs(
        self, run_dir: Path, *, paper_run_id: str, dataset: DatasetManifest, split: SplitManifest, quality_report: DatasetQualityReport | None,
    ) -> InputArtifactIndex:
        """Copies every small manifest this run's dataset/split reference
        into 01_inputs/input_snapshot/ (never a symlink, never a bare path
        reference) and references real I/Q by resolved path + size + sha256
        (never copied -- can be gigabytes). See contracts/input_snapshot.py
        for the rationale."""
        snapshot_dir = run_dir / "01_inputs" / "input_snapshot"
        entries: list[InputSnapshotEntry] = []

        def snapshot_json(source_path: Path, relative_dest: str, artifact_type: str, artifact_id: str, version: str | None) -> None:
            if not source_path.is_file():
                return
            payload = source_path.read_bytes()
            dest = snapshot_dir / relative_dest
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(payload)
            entries.append(InputSnapshotEntry(
                source_path=str(source_path), artifact_type=artifact_type, artifact_id=artifact_id, version=version,
                size_bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest(), snapshot_path=str(dest),
            ))

        snapshot_json(
            self.ble_root / "datasets" / f"{dataset.dataset_id}__{dataset.dataset_version}.json",
            "dataset_manifest.json", "dataset_manifest", dataset.dataset_id, dataset.dataset_version,
        )
        snapshot_json(
            self.ble_root / "splits" / f"{split.dataset_id}__{split.dataset_version}__{split.scientific_task}.json",
            "split_manifest.json", "split_manifest", f"{split.dataset_id}__{split.scientific_task}", split.dataset_version,
        )
        if quality_report is not None:
            snapshot_json(
                self.ble_root / "quality_reports" / f"{quality_report.dataset_id}__{quality_report.dataset_version}.json",
                "quality_manifest.json", "quality_manifest", quality_report.dataset_id, quality_report.dataset_version,
            )

        for capture_id in dataset.captures:
            snapshot_json(self.ble_root / "captures" / f"{capture_id}.json", f"captures/{capture_id}.json", "capture_manifest", capture_id, None)
            snapshot_json(self.ble_root / "evidence" / capture_id / "examples.jsonl", f"evidence/{capture_id}/examples.jsonl", "evidence_manifest", capture_id, None)
            snapshot_json(self.ble_root / "evidence" / capture_id / "annotations.jsonl", f"evidence/{capture_id}/annotations.jsonl", "evidence_manifest", capture_id, None)

            capture = self._load_capture(capture_id)
            if capture is not None:
                iq_path = self._resolve_iq_path(capture)
                entries.append(InputSnapshotEntry(
                    source_path=str(iq_path), artifact_type="iq_reference", artifact_id=capture_id, version=None,
                    size_bytes=capture.iq_size_bytes, sha256=capture.iq_sha256, snapshot_path=None,
                ))

        index = InputArtifactIndex(paper_run_id=paper_run_id, generated_at=utc_now(), entries=entries)
        atomic_json(snapshot_dir / "input_artifact_index.json", index.model_dump(mode="json"))
        return index

    def get_run(self, paper_run_id: str) -> PaperRunRecord:
        path = self._run_dir(paper_run_id) / "run.json"
        if not path.is_file():
            raise FileNotFoundError(f"PAPER_RUN_NOT_FOUND:{paper_run_id}")
        return PaperRunRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def list_runs(self) -> list[PaperRunRecord]:
        runs = []
        for path in sorted(self.root.glob("*/run.json")):
            runs.append(PaperRunRecord.model_validate(json.loads(path.read_text(encoding="utf-8"))))
        return runs

    # ------------------------------------------------------------------
    # ble_rffi_studio artifact loaders -- read-only
    # ------------------------------------------------------------------

    def _load_dataset(self, dataset_id: str, dataset_version: str) -> DatasetManifest:
        path = self.ble_root / "datasets" / f"{dataset_id}__{dataset_version}.json"
        if not path.is_file():
            raise FileNotFoundError(f"DATASET_NOT_FOUND:{dataset_id}:{dataset_version}")
        return DatasetManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def _load_split(self, dataset_id: str, dataset_version: str, scientific_task: str) -> SplitManifest:
        path = self.ble_root / "splits" / f"{dataset_id}__{dataset_version}__{scientific_task}.json"
        if not path.is_file():
            raise FileNotFoundError(f"SPLIT_NOT_FOUND:{dataset_id}:{dataset_version}:{scientific_task}")
        return SplitManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def _load_quality_report(self, dataset_id: str, dataset_version: str) -> DatasetQualityReport | None:
        path = self.ble_root / "quality_reports" / f"{dataset_id}__{dataset_version}.json"
        if not path.is_file():
            return None
        return DatasetQualityReport.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def _load_capture(self, capture_id: str) -> CaptureRecord | None:
        path = self.ble_root / "captures" / f"{capture_id}.json"
        if not path.is_file():
            return None
        return CaptureRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def _load_all_captures(self) -> list[CaptureRecord]:
        captures_dir = self.ble_root / "captures"
        if not captures_dir.is_dir():
            return []
        return [CaptureRecord.model_validate(json.loads(path.read_text(encoding="utf-8"))) for path in sorted(captures_dir.glob("*.json"))]

    def _find_bundle_for_training_run(self, training_run_id: str) -> dict[str, Any] | None:
        """Real, read-only lookup of an exported ModelBundleManifest by the
        training_run_id it was built from (bundle_manifest.json's own real
        `training_run_id` field -- bundle_id itself is not derivable from
        training_run_id, so this scans real bundles on disk rather than
        guessing a path). None when no bundle was ever exported for this
        training run (a real, honest state -- not every real training run
        this session went through export_and_approve_all_candidates)."""
        bundles_dir = self.ble_root / "bundles"
        if not bundles_dir.is_dir():
            return None
        for manifest_path in bundles_dir.glob("*/bundle_manifest.json"):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("training_run_id") == training_run_id:
                return {"bundle_id": manifest.get("bundle_id"), "bundle_sha256": manifest.get("bundle_sha256")}
        return None

    def _load_training_run_evaluation(self, training_run_id: str) -> dict[str, Any] | None:
        """RQ2's persisted representation-comparison report only carries
        VALIDATION-domain branch metrics (model selection is VALIDATION-only
        by design) -- the PRIMARY branch's real TEST confusion matrix lives
        on the training run itself, already computed and persisted by
        StudioRepository.evaluate_training_run(include_test=True). Read-only,
        same convention as the loaders above."""
        path = self.ble_root / "training_runs" / training_run_id / "evaluation_report.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _rq3_campaign_progress(self) -> dict[str, Any]:
        """Real count of how many captures on disk today actually carry the
        RQ3 metadata build_pre_post_pairs() requires (day_id/pre_or_post/
        intervention_arm), broken down per physical unit and arm -- no
        existing function computes this; every other RQ3 real number
        (build_pre_post_pairs, the crossover assignment) operates only once
        that metadata already exists. Unit identity follows
        pre_post_pairing.py's own _unit_id convention (target_reference_id,
        falling back to isolation_declared_physical_unit_id) -- never the
        address-resolved physical_unit_id, which CaptureRecord does not
        carry (see pre_post_pairing.py)."""
        captures = self._load_all_captures()
        declared_by_unit: dict[str, dict[str, int]] = {}
        declared_total = 0
        for capture in captures:
            if not (capture.day_id and capture.pre_or_post and capture.intervention_arm):
                continue
            declared_total += 1
            unit_id = capture.target_reference_id or capture.isolation_declared_physical_unit_id or "UNKNOWN"
            bucket = declared_by_unit.setdefault(unit_id, {"RESET": 0, "CONTROL": 0})
            if capture.intervention_arm in bucket:
                bucket[capture.intervention_arm] += 1
        return {
            "total_captures": len(captures), "captures_with_rq3_metadata": declared_total,
            "declared_by_unit": declared_by_unit,
        }

    def _load_examples(self, capture_id: str) -> list[ExampleRecord]:
        path = self.ble_root / "evidence" / capture_id / "examples.jsonl"
        if not path.is_file():
            return []
        examples = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                examples.append(ExampleRecord.model_validate(json.loads(line)))
        return examples

    # ------------------------------------------------------------------
    # Scientific preflight
    # ------------------------------------------------------------------

    def run_preflight(self, paper_run_id: str, *, progress=None) -> ScientificPreflightReport:
        run = self.get_run(paper_run_id)
        contract = self.get_protocol(run.protocol_id, run.protocol_version)
        dataset = self._load_dataset(run.dataset_id, run.dataset_version)
        split = self._load_split(run.dataset_id, run.dataset_version, run.scientific_task)
        quality_report = self._load_quality_report(run.dataset_id, run.dataset_version)

        if progress:
            progress("integrity", 0.1, "Checking manifest hashes and capture files")
        integrity = self._check_integrity(dataset, split, contract)

        if progress:
            progress("leakage", 0.3, "Checking split leakage status")
        leakage = self._check_leakage(split)

        examples_by_capture = {capture_id: self._load_examples(capture_id) for capture_id in dataset.captures}
        all_examples = [example for examples in examples_by_capture.values() for example in examples]

        if progress:
            progress("population_separation", 0.55, "Separating declared populations")
        population = self._check_population_separation(dataset, all_examples, contract)

        if progress:
            progress("quality", 0.75, "Checking dataset quality gate")
        quality = self._check_quality(quality_report)

        if progress:
            progress("design_completeness", 0.85, "Comparing declared design against observed campaign")
        design = self._check_design_completeness(dataset, all_examples, contract)

        if progress:
            progress("paper_campaign_completeness", 0.95, "Checking whole-paper campaign requirements declared by the protocol")
        campaign_completeness = self._check_paper_campaign_completeness(dataset, all_examples, contract, population)

        structural_categories = [integrity, leakage, population, quality, design]
        overall = ScientificPreflightReport.compute_overall_status(structural_categories, campaign_completeness)
        report = ScientificPreflightReport(
            paper_run_id=paper_run_id, protocol_id=run.protocol_id, protocol_version=run.protocol_version, generated_at=utc_now(),
            integrity=integrity, leakage=leakage, population_separation=population, quality=quality, design_completeness=design,
            paper_campaign_completeness=campaign_completeness, overall_status=overall,
        )
        atomic_json(self._run_dir(paper_run_id) / "02_integrity" / "scientific_preflight_report.json", report.model_dump(mode="json"))
        if progress:
            progress("done", 1.0, overall)
        self.logger.info("preflight paper_run_id=%s overall_status=%s", paper_run_id, overall)
        return report

    def get_preflight_report(self, paper_run_id: str) -> ScientificPreflightReport | None:
        path = self._run_dir(paper_run_id) / "02_integrity" / "scientific_preflight_report.json"
        if not path.is_file():
            return None
        return ScientificPreflightReport.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def _build_rq3_pair_registry(self) -> list[dict[str, Any]]:
        """Dashboard closure (2026-08-11), Case A per the RQ3 pairing
        research pass: real PrePostPair IDENTITY (unit/day/arm/capture ids/
        receiver epoch+session ids/validity/invalidation_reason) from the
        already-real, tested, production-called build_pre_post_pairs() --
        this was already computed in hardware_qualification.py's
        preflight gate but never persisted into a confirmatory report.
        Deliberately excludes any PRE/POST numeric value or D: no function
        anywhere in the codebase computes a per-capture score to feed one
        (Case B, confirmed by research) -- inventing one here to complete a
        chart would be exactly the "new metric to complete a graph" this
        pass is forbidden from doing. The frontend must keep showing
        MISSING_CANONICAL_METRIC for the paired-value plots themselves."""
        from app.modules.ble_rffi_studio.campaign.pre_post_pairing import build_pre_post_pairs
        pairs = build_pre_post_pairs(self._load_all_captures())
        return [
            {
                "physical_unit_id": p.physical_unit_id, "day_id": p.day_id, "intervention_arm": p.intervention_arm,
                "pre_capture_id": p.pre_capture_id, "post_capture_id": p.post_capture_id,
                "pre_receiver_epoch": p.pre_receiver_epoch, "post_receiver_epoch": p.post_receiver_epoch,
                "pre_receiver_session_id": p.pre_receiver_session_id, "post_receiver_session_id": p.post_receiver_session_id,
                "valid": p.valid, "invalidation_reason": p.invalidation_reason,
            }
            for p in pairs
        ]

    def run_confirmatory_statistical_plan(self, paper_run_id: str, **kwargs: Any) -> dict[str, Any]:
        """Real production caller for statistics/confirmatory_analysis_runner.py
        (2026-08-09 -- connects hierarchical_cluster_bootstrap, coverage,
        the RQ3 permutation test, the RQ4 paired comparison, non-inferiority,
        Holm, and leave-one-device-out to a real, reachable path, instead of
        only a unit test). `**kwargs` are the same VALIDATION-only,
        already-scored inputs run_confirmatory_statistical_plan() itself
        accepts -- this method never assembles TEST/FUTURE_TEST data and
        never opens a holdout group. Persisted to
        06_statistics/confirmatory_statistical_plan_report.json; every
        method not given real data is honestly SKIPPED_NO_DATA, never a
        fabricated number. `rq3_pairs` (2026-08-11) is real PrePostPair
        identity, computed independently of the stats kwargs above -- see
        _build_rq3_pair_registry."""
        report = _run_confirmatory_statistical_plan(**kwargs)
        as_dict = confirmatory_statistical_plan_to_dict(report)
        as_dict["rq3_pairs"] = self._build_rq3_pair_registry()
        atomic_json(self._run_dir(paper_run_id) / "06_statistics" / "confirmatory_statistical_plan_report.json", as_dict)
        self.logger.info("confirmatory_statistical_plan paper_run_id=%s", paper_run_id)
        return as_dict

    def get_confirmatory_statistical_plan_report(self, paper_run_id: str) -> dict[str, Any] | None:
        path = self._run_dir(paper_run_id) / "06_statistics" / "confirmatory_statistical_plan_report.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def run_rq3_frr_analysis(
        self, *, paper_run_id: str, offline_inference_service: Any, bundle_id: str | None = None,
        window_duration_s: float | None = None, minimum_eligible_bursts: int | None = None,
    ) -> dict[str, Any]:
        """Scientific Dashboard Closure audit finding (2026-08-11): RQ3's
        pair CONSTRUCTION (build_pre_post_pairs) was real, but the actual
        scientific estimand -- FRR_pre, FRR_post, D = FRR_post - FRR_pre --
        had no real producer, even though the frozen inference pipeline
        that computes it (offline_inference_service.run_decision_windows())
        was already real and callable end-to-end. This is the real
        orchestration that was missing -- see rq3_frr_analysis.py's own
        module docstring for the exact FRR/ground-truth definitions reused
        (never invented here). `bundle_id` defaults to the frozen PRIMARY
        RQ2 branch's model_bundle_id (the "frozen primary branch" per the
        confirmatory analysis plan) -- raises if none is recorded yet,
        never guesses a bundle. Reuses the untouched
        stratified_crossover_permutation_test via
        run_confirmatory_statistical_plan (never a second statistical
        implementation), then overwrites rq3_pairs with the FRR-enriched
        rows and adds rq3_per_unit_reset_mean_d/rq3_per_unit_control_mean_d
        -- same real identities, extra real fields."""
        from app.modules.ble_rffi_studio.campaign.pre_post_pairing import build_pre_post_pairs
        from app.modules.ble_rffi_studio.inference.decision_windows import DEFAULT_MINIMUM_ELIGIBLE_BURSTS, DEFAULT_WINDOW_DURATION_S
        from ..rq3_frr_analysis import compute_rq3_pair_frr, device_day_values_for_permutation_test, mean_d_with_ci, per_unit_mean_d

        run = self.get_run(paper_run_id)
        window_duration_s = window_duration_s if window_duration_s is not None else DEFAULT_WINDOW_DURATION_S
        minimum_eligible_bursts = minimum_eligible_bursts if minimum_eligible_bursts is not None else DEFAULT_MINIMUM_ELIGIBLE_BURSTS

        if bundle_id is None:
            rq2_report = self.get_rq2_representation_comparison_report(paper_run_id)
            primary = next((b for b in (rq2_report or {}).get("branches", []) if b.get("analysis_role") == "PRIMARY"), None)
            if primary is None or not primary.get("model_bundle_id"):
                raise ValueError("NO_FROZEN_PRIMARY_RQ2_BRANCH_WITH_A_MODEL_BUNDLE_ID:run RQ2 Benchmark first, or pass bundle_id explicitly")
            bundle_id = primary["model_bundle_id"]

        pairs = build_pre_post_pairs(self._load_all_captures())
        examples_by_capture_id: dict[str, list[Any]] = {}
        for pair in pairs:
            if pair.valid:
                examples_by_capture_id[pair.pre_capture_id] = self._load_examples(pair.pre_capture_id)
                examples_by_capture_id[pair.post_capture_id] = self._load_examples(pair.post_capture_id)

        enriched_pairs = compute_rq3_pair_frr(
            pairs, offline_inference_service=offline_inference_service, bundle_id=bundle_id, scientific_task=run.scientific_task,
            examples_by_capture_id=examples_by_capture_id, window_duration_s=window_duration_s, minimum_eligible_bursts=minimum_eligible_bursts,
        )
        device_day_values, device_day_is_reset = device_day_values_for_permutation_test(enriched_pairs)
        stats_kwargs: dict[str, Any] = {}
        if device_day_values:
            stats_kwargs = {"rq3_device_day_values": device_day_values, "rq3_device_day_is_reset": device_day_is_reset}

        as_dict = self.run_confirmatory_statistical_plan(paper_run_id, **stats_kwargs)
        as_dict["rq3_pairs"] = enriched_pairs
        as_dict["rq3_per_unit_mean_d"] = per_unit_mean_d(enriched_pairs)
        as_dict["rq3_reset_mean_d_ci"] = mean_d_with_ci(enriched_pairs, intervention_arm="RESET")
        as_dict["rq3_control_mean_d_ci"] = mean_d_with_ci(enriched_pairs, intervention_arm="CONTROL")
        as_dict["rq3_bundle_id"] = bundle_id
        atomic_json(self._run_dir(paper_run_id) / "06_statistics" / "confirmatory_statistical_plan_report.json", as_dict)
        self.logger.info("rq3 FRR analysis persisted paper_run_id=%s bundle_id=%s pairs=%s", paper_run_id, bundle_id, len(enriched_pairs))
        return as_dict

    def run_rq4_region_analysis(
        self, *, paper_run_id: str, offline_inference_service: Any, studio_repository: Any,
        full_burst_bundle_id: str | None = None, window_duration_s: float | None = None, minimum_eligible_bursts: int | None = None,
    ) -> dict[str, Any]:
        """RQ4 region-specific fitting closure (2026-08-12): rq4_primary_analysis=
        REGION_SPECIFIC_FITTING_AND_EVALUATION (recorded via
        record_scientist_decision -- see get_analysis_contract_readiness).
        Reuses RQ2's own frozen PRIMARY bundle+training_run_id directly for
        FULL_BURST (FULL_BURST already IS that run's own input -- retraining
        it again here would risk a nondeterministic duplicate of the exact
        same configuration, not a second real region), and trains
        ADVA_EXCLUDED/PRE_PDU as independent realizations of that SAME
        frozen configuration via studio_repository.train_region_specific_variant
        (never a new model selection per region -- see rq4_region_analysis.py's
        own module docstring). Scores every real matched_region_block
        (physical_unit_id, day_id, packet_condition) under all three regions
        via the SAME frozen decision-window pipeline RQ1-3 already use, and
        feeds ONLY the PRIMARY contrast (FULL_BURST vs PRE_PDU) into the
        untouched NI/Holm confirmatory pipeline via rq4_scores_a/
        rq4_scores_b -- FULL_BURST vs ADVA_EXCLUDED stays SECONDARY/
        diagnostic, reported but never Holm-corrected (adding it to the
        hypothesis family is a separate, explicit future decision, never
        made implicitly here). Raises rather than silently skipping when no
        frozen PRIMARY RQ2 branch or no real matched-region-block captures
        exist yet -- an empty/NO_DATA report from the caller's side, never
        a fabricated one from this method."""
        from app.modules.ble_rffi_studio.inference.decision_windows import DEFAULT_MINIMUM_ELIGIBLE_BURSTS, DEFAULT_WINDOW_DURATION_S
        from app.modules.ble_rffi_studio.inference.offline_inference import OfflineInferenceService
        from app.modules.ble_rffi_studio.packet_content import region_restricted_provider_and_eligible_ids
        from ..rq4_region_analysis import build_matched_region_blocks, compute_rq4_region_report, matched_region_block_id

        window_duration_s = window_duration_s if window_duration_s is not None else DEFAULT_WINDOW_DURATION_S
        minimum_eligible_bursts = minimum_eligible_bursts if minimum_eligible_bursts is not None else DEFAULT_MINIMUM_ELIGIBLE_BURSTS

        base_training_run_id = None
        if full_burst_bundle_id is None:
            rq2_report = self.get_rq2_representation_comparison_report(paper_run_id)
            primary = next((b for b in (rq2_report or {}).get("branches", []) if b.get("analysis_role") == "PRIMARY"), None)
            if primary is None or not primary.get("model_bundle_id") or not primary.get("training_run_id"):
                raise ValueError("NO_FROZEN_PRIMARY_RQ2_BRANCH_WITH_A_MODEL_BUNDLE_ID:run RQ2 Benchmark first, or pass full_burst_bundle_id explicitly")
            full_burst_bundle_id = primary["model_bundle_id"]
            base_training_run_id = primary["training_run_id"]

        captures = self._load_all_captures()
        blocks = build_matched_region_blocks(captures)
        if not blocks:
            raise ValueError(
                "NO_CAPTURES_WITH_A_REAL_MATCHED_REGION_BLOCK_IDENTITY:physical_unit_id/day_id/packet_condition "
                "must all be real on at least one capture -- 0 real region-specific captures exist yet"
            )

        relevant_captures = [c for c in captures if matched_region_block_id(c) is not None]
        examples_by_capture_id = {c.capture_id: self._load_examples(c.capture_id) for c in relevant_captures}
        all_examples = [e for exs in examples_by_capture_id.values() for e in exs]
        iq_paths = {c.capture_id: self._resolve_iq_path(c) for c in relevant_captures}

        bundle_ids: dict[str, str | None] = {"FULL_BURST": full_burst_bundle_id}
        inference_services: dict[str, Any] = {"FULL_BURST": offline_inference_service}
        eligible_example_ids_by_region: dict[str, set[str]] = {"FULL_BURST": {e.example_id for e in all_examples}}

        for region in ("ADVA_EXCLUDED", "PRE_PDU"):
            provider, eligible_ids = region_restricted_provider_and_eligible_ids(
                all_examples, analytical_region=region, legacy_capture_root=self.legacy_capture_root, capture_iq_paths=iq_paths,
            )
            eligible_example_ids_by_region[region] = eligible_ids
            if not eligible_ids or base_training_run_id is None:
                bundle_ids[region] = None
                inference_services[region] = None
                continue
            variant = studio_repository.train_region_specific_variant(training_run_id=base_training_run_id, analytical_region=region)
            bundle_ids[region] = variant["bundle_id"]
            inference_services[region] = OfflineInferenceService(offline_inference_service.bundle_root, iq_paths, iq_window_provider=provider)

        report = compute_rq4_region_report(
            blocks=blocks, examples_by_capture_id=examples_by_capture_id, eligible_example_ids_by_region=eligible_example_ids_by_region,
            inference_services=inference_services, bundle_ids=bundle_ids,
            window_duration_s=window_duration_s, minimum_eligible_bursts=minimum_eligible_bursts,
        )

        stats_kwargs: dict[str, Any] = {}
        if report["primary_contrast_scores_a"] and report["primary_contrast_scores_b"]:
            stats_kwargs = {"rq4_scores_a": report["primary_contrast_scores_a"], "rq4_scores_b": report["primary_contrast_scores_b"]}
        as_dict = self.run_confirmatory_statistical_plan(paper_run_id, **stats_kwargs)
        as_dict["rq4_region_report"] = report
        atomic_json(self._run_dir(paper_run_id) / "06_statistics" / "confirmatory_statistical_plan_report.json", as_dict)
        self.logger.info("rq4 region-specific analysis persisted paper_run_id=%s blocks=%s", paper_run_id, len(blocks))
        return as_dict

    def run_coverage_analysis(
        self, *, paper_run_id: str, offline_inference_service: Any, bundle_ids: dict[str, str] | None = None,
        window_duration_s: float | None = None, minimum_eligible_bursts: int | None = None,
        evaluate_window_level: bool = False,
    ) -> dict[str, Any]:
        """Coverage audit finding (2026-08-12): the real decision records
        (offline_inference_service.run_decision_windows(), the SAME frozen
        pipeline RQ3 already drives) already carry everything coverage
        needs -- nothing aggregated them by evaluation_domain/branch/
        physical_unit. This is the real orchestration that was missing --
        see coverage_analysis.py's own module docstring for the exact
        abstention/coverage definitions reused (never invented here).
        `bundle_ids` defaults to EVERY frozen RQ2 branch's model_bundle_id
        (coverage-by-branch needs all of them, unlike RQ3's single
        primary-branch scope) -- raises if none are recorded yet, never
        guesses. Real evaluation_domain comes from a real SplitManifest
        join (VALIDATION/TRAIN/TEST) when one exists for this run's
        dataset/scientific_task, else None (never guessed).

        `evaluate_window_level` (2026-08-17): when True, additionally
        computes real balanced-accuracy/confusion-matrix/risk-coverage per
        (branch, domain) by feeding the SAME real decision-window
        predictions into Evaluator.evaluate_split() -- never a second
        metric definition, never pooled across branches (kept in its own
        `window_level_evaluation[branch][domain]`, never merged into
        `by_evaluation_domain`, which pools every branch's rows together
        and would silently mix two different classifiers' predictions if
        this were written into the same bucket). Labeled `CURRENT_TEST`
        evidence_maturity -- never `PROTECTED_FUTURE`, since this always
        runs against TRAIN/VALIDATION/TEST, the study's current, non-FUTURE
        domains. `acceptance_threshold`/`calibrated_on` are read verbatim
        from the SAME bundle's real thresholds.json -- None only when the
        bundle genuinely has none (never fabricated as 'not frozen' when a
        real VALIDATION-calibrated one exists)."""
        from app.modules.ble_rffi_studio.inference.decision_windows import DEFAULT_MINIMUM_ELIGIBLE_BURSTS, DEFAULT_WINDOW_DURATION_S
        from ..coverage_analysis import CoverageRow, compute_coverage_summary, coverage_row_from_decision_window, operational_coverage_breakdown
        from ..coverage_analysis import evaluate_window_level as _evaluate_window_level

        window_duration_s = window_duration_s if window_duration_s is not None else DEFAULT_WINDOW_DURATION_S
        minimum_eligible_bursts = minimum_eligible_bursts if minimum_eligible_bursts is not None else DEFAULT_MINIMUM_ELIGIBLE_BURSTS

        if bundle_ids is None:
            rq2_report = self.get_rq2_representation_comparison_report(paper_run_id)
            bundle_ids = {b["branch"]: b["model_bundle_id"] for b in (rq2_report or {}).get("branches", []) if b.get("model_bundle_id")}
        if not bundle_ids:
            raise ValueError("NO_FROZEN_RQ2_BRANCHES_WITH_A_MODEL_BUNDLE_ID:run RQ2 Benchmark first, or pass bundle_ids explicitly")

        run = self.get_run(paper_run_id)
        captures = [c for c in self._load_all_captures() if (c.target_reference_id or c.isolation_declared_physical_unit_id)]
        examples_by_capture_id = {c.capture_id: self._load_examples(c.capture_id) for c in captures}

        try:
            split = self._load_split(run.dataset_id, run.dataset_version, run.scientific_task)
            domain_by_example_id = {a.example_id: a.split for a in split.assignments}
            split_physical_units = {a.physical_unit_id for a in split.assignments if a.physical_unit_id}
        except FileNotFoundError:
            domain_by_example_id = {}
            split_physical_units = set()

        rows: list[CoverageRow] = []
        # Real per-window record (2026-08-17, RQ1/per-TX/calibration/decision-
        # window demonstration pass): the SAME real run_decision_windows()
        # output already computed above, kept as one row per window when
        # evaluate_window_level=True -- true TX/predicted TX/score/decision-
        # abstention/burst_count were always real and already computed, just
        # never persisted as an inspectable table before this.
        decision_window_records: list[dict[str, Any]] = []
        # Domain-resolution diagnostic. Deduped by (decision_window_id,
        # domain) -- NOT decision_window_id alone: after the scoping fix
        # below, the SAME real (capture_id, window_index) key can legitimately
        # produce two separate window dicts (one per real admitted-example
        # subset, e.g. this split's real TRAIN bursts and this capture's
        # real non-admitted bursts) -- deduping on the bare id would silently
        # drop one of them.
        domain_resolution_by_key: dict[tuple[str, object], dict[str, Any]] = {}
        for branch, bundle_id in sorted(bundle_ids.items()):
            for capture in captures:
                examples = examples_by_capture_id[capture.capture_id]
                if not examples:
                    continue
                # Scoping fix (2026-08-18): partition this capture's REAL
                # examples by their real split domain BEFORE grouping into
                # decision windows -- a window must never be invalidated just
                # because some OTHER burst of the same real capture was never
                # admitted to this split (or belongs to a different real
                # domain). Each admitted subset (and the non-admitted
                # leftover, domain_key=None) is windowed independently, via
                # the exact same run_decision_windows() call as before --
                # never a second windowing formula. This also makes the
                # MIXED_SPLIT_ASSIGNMENT_WITHIN_WINDOW failure mode
                # structurally impossible: a single run_decision_windows()
                # call now only ever sees examples from one real domain.
                examples_by_domain: dict[str | None, list] = {}
                for example in examples:
                    examples_by_domain.setdefault(domain_by_example_id.get(example.example_id), []).append(example)
                for domain_key, domain_examples in examples_by_domain.items():
                    windows = offline_inference_service.run_decision_windows(
                        bundle_id=bundle_id, examples=domain_examples, window_duration_s=window_duration_s, minimum_eligible_bursts=minimum_eligible_bursts,
                    )
                    for window in windows:
                        if domain_key is not None:
                            resolved_domain, reason = domain_key, None
                        else:
                            resolved_domain = None
                            reason = "PHYSICAL_UNIT_NOT_IN_CLOSED_SET_SPLIT" if window.get("physical_unit_id") not in split_physical_units else "EXAMPLE_ID_NOT_IN_SPLIT_ASSIGNMENTS"
                        rows.append(coverage_row_from_decision_window(window, evaluation_domain=resolved_domain, branch=branch))
                        if evaluate_window_level:
                            decision_window_records.append({
                                "branch": branch, "evaluation_domain": resolved_domain,
                                "decision_window_id": window.get("decision_window_id"), "capture_id": window.get("capture_id"),
                                "window_duration_s": window.get("window_duration_s"), "burst_count": window.get("burst_count"),
                                "true_physical_unit_id": window.get("physical_unit_id"), "predicted_class": window.get("predicted_class"),
                                "class_probability": window.get("class_probability"), "final_decision": window.get("final_decision"),
                                "abstention_reason": window.get("abstention_reason"),
                            })
                            window_id = window.get("decision_window_id")
                            dedup_key = (window_id, domain_key)
                            if window_id is not None and dedup_key not in domain_resolution_by_key:
                                domain_resolution_by_key[dedup_key] = {"resolved_domain": resolved_domain, "reason": reason}

        summary = compute_coverage_summary(rows)
        as_dict = {
            "schema_version": "ble-scientific-results-coverage-analysis-v1", "generated_at": utc_now(),
            "paper_run_id": paper_run_id, "bundle_ids": bundle_ids,
            "window_duration_s": window_duration_s, "minimum_eligible_bursts": minimum_eligible_bursts,
            **summary,
        }

        if evaluate_window_level and domain_resolution_by_key:
            resolved = [w for w in domain_resolution_by_key.values() if w["resolved_domain"] is not None]
            unresolved = [w for w in domain_resolution_by_key.values() if w["resolved_domain"] is None]
            unresolved_by_reason: dict[str, int] = {}
            for w in unresolved:
                unresolved_by_reason[w["reason"]] = unresolved_by_reason.get(w["reason"], 0) + 1
            as_dict["domain_resolution_diagnostic"] = {
                "total_windows": len(domain_resolution_by_key),
                "assigned_train": sum(1 for w in resolved if w["resolved_domain"] == "TRAIN"),
                "assigned_validation": sum(1 for w in resolved if w["resolved_domain"] == "VALIDATION"),
                "assigned_test": sum(1 for w in resolved if w["resolved_domain"] == "TEST"),
                "unresolved": len(unresolved),
                "unresolved_by_reason": unresolved_by_reason,
            }

        if evaluate_window_level:
            from app.modules.ble_rffi_studio.evaluation import Evaluator
            evaluator = Evaluator()
            window_level_evaluation: dict[str, Any] = {}
            for branch, bundle_id in sorted(bundle_ids.items()):
                bundle_dir = offline_inference_service.bundle_root / bundle_id
                model_manifest_path = bundle_dir / "model_manifest.json"
                thresholds_path = bundle_dir / "thresholds.json"
                if not model_manifest_path.is_file():
                    continue
                known_classes = json.loads(model_manifest_path.read_text(encoding="utf-8"))["label_classes"]
                thresholds = json.loads(thresholds_path.read_text(encoding="utf-8")) if thresholds_path.is_file() else {}
                branch_rows = [r for r in rows if r.branch == branch]
                by_domain: dict[str, Any] = {}
                for domain in sorted({r.evaluation_domain for r in branch_rows if r.evaluation_domain is not None}):
                    domain_rows = [r for r in branch_rows if r.evaluation_domain == domain]
                    report = _evaluate_window_level(domain_rows, evaluator=evaluator, known_classes=known_classes, domain_label=domain)
                    if report is None:
                        continue
                    n_total = report.n_comparable_to_known_classes
                    # n_decided/n_abstained (2026-08-17): exact integer derivation
                    # from the SAME coverage ratio risk_coverage_curve() already
                    # computed (coverage = n_decided_at_threshold / n_total) --
                    # never a second selective-prediction implementation, just
                    # exposing the real counts behind the ratio already returned.
                    risk_coverage_with_counts = [
                        {**point, "n_decided": round(point["coverage"] * n_total), "n_abstained": n_total - round(point["coverage"] * n_total)}
                        for point in (report.risk_coverage or [])
                    ] if report.risk_coverage else report.risk_coverage
                    # PAPER_READY gate (2026-08-17): the risk-coverage curve above
                    # is kept as real, functional evidence regardless, but is
                    # never marked paper-ready when the real sample is too small
                    # or too homogeneous to support a citable claim -- both real,
                    # already-available facts about domain_rows, never a new
                    # metric.
                    distinct_units = {r.physical_unit_id for r in domain_rows if r.physical_unit_id is not None}
                    not_ready_reasons = []
                    if n_total < 10:
                        not_ready_reasons.append(f"only {n_total} decision windows (n<10)")
                    if len(distinct_units) < 2:
                        not_ready_reasons.append(f"all decision windows belong to a single physical unit ({next(iter(distinct_units), 'NONE')})")
                    by_domain[domain] = {
                        "evidence_maturity": "CURRENT_TEST",  # real, current TRAIN/VALIDATION/TEST -- never PROTECTED_FUTURE
                        "balanced_accuracy": report.balanced_accuracy, "macro_f1": report.macro_f1,
                        "confusion_matrix": report.confusion_matrix, "n_comparable": n_total,
                        "distinct_physical_units": sorted(distinct_units),
                        # Methodological-audit fix (2026-08-22, item 2): the
                        # balanced_accuracy/confusion_matrix/n_comparable
                        # fields above (like `decided` everywhere else in
                        # this module) intentionally treat UNKNOWN
                        # (threshold-rejected) windows as "decided, just
                        # wrong-class" -- real for their own purpose, but not
                        # what "coverage" means operationally. This is the
                        # explicit, additive breakdown that separates
                        # IDENTIFIED / UNKNOWN-below-threshold /
                        # INSUFFICIENT_EVIDENCE and reports operational
                        # coverage (IDENTIFIED / admissible), argmax accuracy
                        # ignoring the threshold, and accuracy restricted to
                        # accepted (IDENTIFIED) decisions only -- computed
                        # from the SAME domain_rows, never a second read.
                        "operational_breakdown": operational_coverage_breakdown(domain_rows),
                        # `risk` in each point below IS the selective_error (error
                        # rate among decided instances at that threshold) -- same
                        # El-Yaniv & Wiener (2010) definition used everywhere else
                        # in this codebase, not renamed to avoid a second field
                        # meaning the same thing.
                        "risk_coverage": risk_coverage_with_counts,
                        "paper_ready": len(not_ready_reasons) == 0,
                        "paper_ready_reason": "; ".join(not_ready_reasons) if not_ready_reasons else None,
                    }
                if by_domain:
                    frozen_policy = self.find_frozen_association_policy()
                    window_level_evaluation[branch] = {
                        "by_evaluation_domain": by_domain,
                        # Two DIFFERENT real thresholds, unambiguously named
                        # (2026-08-17) so they are never conflated again:
                        # classifier_acceptance_threshold is this bundle's own
                        # VALIDATION-only UNKNOWN-rejection threshold
                        # (Evaluator.calibrate_unknown_threshold);
                        # association_time_threshold_ms is the SEPARATE
                        # native<->SDR AssociationPolicy.threshold_ms, real null
                        # while association calibration stays fail-closed (never
                        # loosened here to force a value).
                        "classifier_acceptance_threshold": thresholds.get("acceptance_threshold"),
                        "classifier_acceptance_threshold_calibrated_on": thresholds.get("calibrated_on"),
                        "association_time_threshold_ms": frozen_policy.threshold_ms if frozen_policy else None,
                        # Real per-window record -- true TX/predicted TX/score/
                        # decision-abstention/burst_count, one row per real
                        # decision window (decided AND abstained), this branch only.
                        "decision_windows": [r for r in decision_window_records if r["branch"] == branch],
                    }
            if window_level_evaluation:
                as_dict["window_level_evaluation"] = window_level_evaluation

        atomic_json(self._run_dir(paper_run_id) / "06_statistics" / "coverage_analysis_report.json", as_dict)
        self.logger.info("coverage analysis persisted paper_run_id=%s branches=%s rows=%s", paper_run_id, list(bundle_ids), len(rows))
        return as_dict

    def get_coverage_analysis_report(self, paper_run_id: str) -> dict[str, Any] | None:
        path = self._run_dir(paper_run_id) / "06_statistics" / "coverage_analysis_report.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def run_sensitivity_analysis(self, *, paper_run_id: str, studio_repository: Any) -> dict[str, Any]:
        """Sensitivity closure (2026-08-12): consolidates the three real
        sensitivity mechanisms this study already defines -- enrolled-
        population class-exclusion metric sensitivity (already wired, real,
        tested since 2026-08-09; renamed 2026-08-22 from its original,
        overstated "LODO"/leave-one-device-out name -- see statistics/
        sensitivity.py's own docstring for why: the model is never
        retrained without the excluded class, only the aggregate metric is
        recomputed post-hoc), offset-retaining
        preprocessing (train_offset_retaining_sensitivity, closed this
        pass), and RQ2's seed_variability (REUSED verbatim from the RQ2
        report, never recomputed) -- into one report that explicitly
        separates PRIMARY from each SENSITIVITY variant. `studio_repository`
        is required (never optional): every real input here -- predictions,
        label_classes, the offset-retaining re-train -- lives in
        ble_rffi_studio's own storage. Raises rather than silently skipping
        when the PRIMARY branch or its predictions are not real yet --
        never persists a report built on missing pieces."""
        if studio_repository is None:
            raise ValueError("NO_STUDIO_REPOSITORY_CONFIGURED:sensitivity analysis needs a real StudioRepository to read predictions/re-train")
        from ..sensitivity_analysis import enrich_class_exclusion_with_delta_vs_full_set, full_set_balanced_accuracy
        from ..statistics.sensitivity import enrolled_population_class_exclusion_sensitivity

        rq2_report = self.get_rq2_representation_comparison_report(paper_run_id)
        primary = next((b for b in (rq2_report or {}).get("branches", []) if b.get("analysis_role") == "PRIMARY"), None)
        if primary is None:
            raise ValueError("NO_FROZEN_PRIMARY_RQ2_BRANCH:run RQ2 Benchmark first")
        training_run_id = primary.get("training_run_id")
        if not training_run_id:
            raise ValueError("PRIMARY_RQ2_BRANCH_HAS_NO_TRAINING_RUN_ID:cannot re-read its real predictions")

        predictions = studio_repository.get_training_run_predictions(training_run_id, "VALIDATION") or []
        label_classes = (studio_repository.get_training_run(training_run_id) or {}).get("label_classes") or []
        # Real device_id join reuses the SAME physical_unit_id every
        # prediction dict now carries (Scientific Closure pass point 7) --
        # never a second identity source.
        device_id_by_example_id = {p["example_id"]: p["physical_unit_id"] for p in predictions if p.get("physical_unit_id")}

        class_exclusion_raw = enrolled_population_class_exclusion_sensitivity(predictions, device_id_by_example_id, label_classes)
        baseline_ba = full_set_balanced_accuracy(predictions, label_classes)
        class_exclusion_rows = enrich_class_exclusion_with_delta_vs_full_set(class_exclusion_raw, full_set_ba=baseline_ba)

        offset_result = studio_repository.train_offset_retaining_sensitivity(training_run_id=training_run_id)
        primary_ba = primary.get("balanced_accuracy")
        offset_ba = offset_result.get("validation_balanced_accuracy")

        # Methodological-audit fix (2026-08-22, item 1): this comparison is
        # only a real CFO/phase-offset ablation when the PRIMARY run's own
        # base_preprocessing_profile_id resolves to DIFFERENT enabled steps
        # than "offset-retaining-v1" -- if PRIMARY already ran identity
        # preprocessing (base-v1, whose enabled_steps() is []), comparing it
        # against offset-retaining-v1 (also enabled_steps()==[]) compares
        # identity against a relabeled clone of itself, and any delta=0.000
        # reported is a trivial consequence of that, never evidence that
        # "retaining the offset" leaves the result unchanged. This is
        # detected here from the REAL resolved profile flags, never assumed.
        base_profile_id = (studio_repository.get_training_run(training_run_id) or {}).get("base_preprocessing_profile_id")
        primary_enabled_steps = resolve_preprocessing_profile(base_profile_id).enabled_steps() if base_profile_id else None
        offset_enabled_steps = resolve_preprocessing_profile("offset-retaining-v1").enabled_steps()
        profiles_behaviorally_identical = primary_enabled_steps is not None and primary_enabled_steps == offset_enabled_steps
        interpretive_validity = (
            "NOT_INFORMATIVE_IDENTICAL_PREPROCESSING_PROFILES" if profiles_behaviorally_identical
            else ("REAL_ABLATION_DIFFERENT_PREPROCESSING_PROFILES" if primary_enabled_steps is not None else "CANNOT_DETERMINE_PRIMARY_PROFILE")
        )
        interpretive_note = (
            f"PRIMARY's own base_preprocessing_profile_id={base_profile_id!r} resolves to the SAME enabled preprocessing "
            f"steps as offset-retaining-v1 ({offset_enabled_steps!r} both) -- this is NOT a real test of whether retaining "
            f"CFO/phase offset changes the result; PRIMARY never applied any CFO/phase compensation to begin with, so this "
            f"delta is trivially ~0 by construction, not evidence of CFO-compensation insensitivity."
            if profiles_behaviorally_identical else
            f"PRIMARY's base_preprocessing_profile_id={base_profile_id!r} (enabled steps: {primary_enabled_steps!r}) genuinely "
            f"differs from offset-retaining-v1 (enabled steps: {offset_enabled_steps!r}) -- this delta is a real ablation."
        )
        offset_retaining = {
            "analysis_role": "OFFSET_RETAINING_SENSITIVITY", "training_run_id": offset_result["training_run_id"],
            "base_run_training_run_id": training_run_id, "base_preprocessing_profile_id": offset_result["base_preprocessing_profile_id"],
            "primary_base_preprocessing_profile_id": base_profile_id,
            "estimate": offset_ba, "coverage": offset_result.get("coverage"),
            "delta_vs_primary": (offset_ba - primary_ba) if (offset_ba is not None and primary_ba is not None) else None,
            "profiles_behaviorally_identical": profiles_behaviorally_identical,
            "interpretive_validity": interpretive_validity,
            "interpretive_note": interpretive_note,
        }

        as_dict = {
            "schema_version": "ble-scientific-results-sensitivity-analysis-v1", "generated_at": utc_now(), "paper_run_id": paper_run_id,
            "primary": {"analysis_role": "PRIMARY", "branch": primary.get("branch"), "training_run_id": training_run_id, "balanced_accuracy": primary_ba},
            "enrolled_population_class_exclusion_sensitivity": {"analysis_role": "SENSITIVITY", "full_set_balanced_accuracy": baseline_ba, "rows": class_exclusion_rows},
            "offset_retaining": offset_retaining,
            "seed_variability": {"analysis_role": "SENSITIVITY", "rows": primary.get("seed_variability")} if primary.get("seed_variability") else None,
        }
        atomic_json(self._run_dir(paper_run_id) / "06_statistics" / "sensitivity_report.json", as_dict)
        self.logger.info("sensitivity analysis persisted paper_run_id=%s class_exclusion_rows=%s", paper_run_id, len(class_exclusion_rows))
        return as_dict

    def get_sensitivity_report(self, paper_run_id: str) -> dict[str, Any] | None:
        path = self._run_dir(paper_run_id) / "06_statistics" / "sensitivity_report.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    class ProtocolFreezeGateError(Exception):
        pass

    def run_confirmatory_future_analysis(
        self, *, paper_run_id: str, protocol_id: str, dataset_id: str, dataset_version: str,
        bundle_confirmatory_eligible: bool, declared_contract_sha256: str | None = None, **stats_kwargs: Any,
    ) -> dict[str, Any]:
        """Protocol-freeze close-out, point 3 (2026-08-10): the
        CONFIRMATORY_FUTURE role. run_confirmatory_statistical_plan() /
        ScientificResultsRepository.run_confirmatory_statistical_plan() above
        is the OTHER role -- VALIDATION_DRY_RUN -- and never touches
        FUTURE_TEST. This method is the only path allowed to run the SAME
        11-method statistical engine over FUTURE-scoped data, and it does so
        ONLY after every one of these real, non-bypassable gates passes (in
        order, first failure wins):
          1. a real protocol freeze exists for `protocol_id`
             (execute_protocol_freeze() must have been called for real --
             checked via list_protocol_freezes(), never freeze_protocol()
             alone, which has no confirmatory-readiness gate);
          2. the frozen AnalysisContract carries a real contract_sha256;
          3. the dataset has a real FUTURE_TEST holdout role assigned
             (list_holdout_groups());
          4. the bundle this analysis would score is confirmatory_eligible;
          5. the caller-declared contract_sha256 (if supplied) and the
             protocol_id/protocol_version match the real frozen ledger entry
             exactly -- never a stale or substituted contract.
        Only once all five pass does this call
        self.read_group(..., "FUTURE_TEST", ...) -- the ONLY real read path
        for FUTURE_TEST data anywhere in this repository -- which itself
        logs the access through the existing hash-chained holdout log."""
        freezes = [e for e in self.list_protocol_freezes() if e["protocol_id"] == protocol_id]
        if not freezes:
            raise self.ProtocolFreezeGateError(f"NO_REAL_PROTOCOL_FREEZE_EXECUTED:protocol_id={protocol_id}")
        latest_freeze = freezes[-1]

        contract = self.get_protocol(protocol_id, latest_freeze["protocol_version"])
        if not contract.contract_sha256:
            raise self.ProtocolFreezeGateError(f"MISSING_CONTRACT_SHA256:protocol_id={protocol_id}")

        holdout_groups = self.list_holdout_groups(dataset_id, dataset_version)
        if not any(g.group == "FUTURE_TEST" for g in holdout_groups):
            raise self.ProtocolFreezeGateError(f"DATASET_HAS_NO_FUTURE_TEST_HOLDOUT_ROLE:{dataset_id}__{dataset_version}")

        if not bundle_confirmatory_eligible:
            raise self.ProtocolFreezeGateError("BUNDLE_NOT_CONFIRMATORY_ELIGIBLE")

        if declared_contract_sha256 is not None and declared_contract_sha256 != contract.contract_sha256:
            raise self.ProtocolFreezeGateError(
                f"CONTRACT_HASH_MISMATCH:declared={declared_contract_sha256} frozen={contract.contract_sha256}"
            )
        if latest_freeze["protocol_version"] != contract.protocol_version:
            raise self.ProtocolFreezeGateError(
                f"PROTOCOL_VERSION_MISMATCH:freeze_ledger={latest_freeze['protocol_version']} loaded_contract={contract.protocol_version}"
            )

        # All five gates passed -- the ONLY real FUTURE_TEST read path,
        # already hash-chain-logged by read_group() itself.
        self.read_group(
            dataset_id, dataset_version, "FUTURE_TEST", actor="run_confirmatory_future_analysis",
            process="ScientificResultsRepository", reason="confirmatory future analysis", paper_run_id=paper_run_id,
        )
        report = _run_confirmatory_statistical_plan(**stats_kwargs)
        as_dict = confirmatory_statistical_plan_to_dict(report)
        atomic_json(self._run_dir(paper_run_id) / "06_statistics" / "confirmatory_future_analysis_report.json", as_dict)
        self.logger.info("confirmatory FUTURE analysis executed paper_run_id=%s protocol_id=%s", paper_run_id, protocol_id)
        return as_dict

    def get_confirmatory_future_analysis_report(self, paper_run_id: str) -> dict[str, Any] | None:
        path = self._run_dir(paper_run_id) / "06_statistics" / "confirmatory_future_analysis_report.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def persist_rq1_acquisition_dependence_report(
        self, *, paper_run_id: str, protocol_id: str, protocol_version: int, contract_sha256: str,
        rq1_report: Any, model_bundle_id: str | None, model_bundle_sha256: str | None,
        dataset_manifest_sha256: str | None = None,
        confirmatory_split_manifest_id: str, confirmatory_split_manifest_sha256: str,
        diagnostic_split_manifest_id: str, diagnostic_split_manifest_sha256: str,
        source_evaluation_domains: dict[str, Any], uncertainty_ci: dict[str, Any] | None = None,
        coverage: float | None = None,
        confusion_matrix_capture: dict[str, dict[str, int]] | None = None,
        confusion_matrix_future: dict[str, dict[str, int]] | None = None,
        per_unit_recall: dict[str, dict[str, float]] | None = None,
        evaluation_unit: str = "EXAMPLE_RECORD",
        evidence_status: str = "DEVELOPMENT",
        decision_window_cross_reference: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Protocol-freeze close-out, point 4 (2026-08-10): the canonical,
        persisted RQ1 artifact -- evaluate_rq1_acquisition_dependence()
        (ble_rffi_studio/evaluation/rq1_acquisition_dependence.py) computes
        BA_window/BA_capture/BA_future/delta_dependence/delta_future in
        memory only; this is the ONLY place that writes them to disk, and
        only ever with real, caller-supplied linking metadata -- there is no
        default that lets this method run with placeholder ids/hashes, and
        it computes no number of its own (uncertainty_ci/coverage/confusion
        matrices/per_unit_recall are all pass-through, never invented here
        -- confusion_matrix_* mirrors SplitEvaluationReport.confusion_matrix's
        own dict-of-dicts shape exactly, added 2026-08-11 so the paper
        export's confusion-matrix figures have a real source)."""
        git_sha, _ = self._git_provenance()
        artifact = {
            "schema_version": "ble-scientific-results-rq1-acquisition-dependence-v1",
            "protocol_id": protocol_id, "protocol_version": protocol_version, "contract_sha256": contract_sha256, "git_sha": git_sha,
            "model_bundle_id": model_bundle_id, "model_bundle_sha256": model_bundle_sha256,
            "dataset_manifest_sha256": dataset_manifest_sha256,
            "confirmatory_split_manifest_id": confirmatory_split_manifest_id, "confirmatory_split_manifest_sha256": confirmatory_split_manifest_sha256,
            "diagnostic_split_manifest_id": diagnostic_split_manifest_id, "diagnostic_split_manifest_sha256": diagnostic_split_manifest_sha256,
            "source_evaluation_domains": source_evaluation_domains,
            # Investigation finding (2026-08-17): RQ1's real evaluation unit
            # is the ExampleRecord (one burst/packet-level classification per
            # row of predictions.json, via Evaluator.evaluate_split()) --
            # "window" in BA_window/BA_capture is RQ1's own pre-existing
            # acquisition-provenance term (build_rq1_dependence_diagnostic:
            # "the SAME session as TRAIN" vs. capture-disjoint), unrelated to
            # the 10-second decision-window aggregation coverage_analysis.py
            # uses. This field makes that unambiguous, machine-readable, so
            # it is never conflated with a decision-window count again.
            "evaluation_unit": evaluation_unit,
            # Figure/artifact sync closure (2026-08-18): the SAME status
            # vocabulary docs/ble/SCIENTIFIC_STATUS.md's "Status categories"
            # defines (DEVELOPMENT / PROTECTED_FUTURE / PENDING), persisted
            # here so the figure generator and figure_manifest.json can read
            # it straight from the artifact instead of a caller re-deciding
            # it. Always "DEVELOPMENT" today -- this whole report (including
            # its ba_future arm, gated separately by ba_future_status) is
            # DEVELOPMENT evidence until the protocol is frozen and protected
            # FUTURE is actually executed.
            "evidence_status": evidence_status,
            "decision_window_cross_reference": decision_window_cross_reference,
            "ba_window": rq1_report.ba_window, "ba_window_n_comparable": rq1_report.ba_window_n_comparable,
            "ba_capture": rq1_report.ba_capture, "ba_capture_n_comparable": rq1_report.ba_capture_n_comparable,
            "ba_future": rq1_report.ba_future, "ba_future_status": rq1_report.ba_future_status, "ba_future_n_comparable": rq1_report.ba_future_n_comparable,
            "delta_dependence": rq1_report.delta_dependence, "delta_future": rq1_report.delta_future,
            "uncertainty_ci": uncertainty_ci, "coverage": coverage,
            "confusion_matrix_capture": confusion_matrix_capture, "confusion_matrix_future": confusion_matrix_future,
            "per_unit_recall": per_unit_recall,
            "generated_at": utc_now(),
        }
        atomic_json(self._run_dir(paper_run_id) / "06_statistics" / "rq1_acquisition_dependence_report.json", artifact)
        self.logger.info("rq1 acquisition-dependence report persisted paper_run_id=%s protocol_id=%s", paper_run_id, protocol_id)
        return artifact

    def get_rq1_acquisition_dependence_report(self, paper_run_id: str) -> dict[str, Any] | None:
        path = self._run_dir(paper_run_id) / "06_statistics" / "rq1_acquisition_dependence_report.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def persist_rq2_representation_comparison_report(
        self, *, paper_run_id: str, protocol_id: str | None = None, protocol_version: int | None = None, contract_sha256: str | None = None,
        dataset_id: str, dataset_version: str, split_manifest_id: str, split_manifest_sha256: str,
        branch_results: list[dict[str, Any]], selection_rule: str | None = None, selection_domain: str | None = None,
        evaluation_unit: str = "EXAMPLE_RECORD", evidence_status: str = "DEVELOPMENT",
    ) -> dict[str, Any]:
        """Reporting closure, point A (2026-08-11): the canonical, persisted
        RQ2 artifact. `select_primary_rq2_branch_from_validation()`
        (training/model_selector.py) already maps a `ModelType` to one of
        the 4 real RQ2 branches (`engineered_rf`/`raw_iq`/`stft`/
        `coarse_morphology`) and picks the primary by VALIDATION composite
        score; `Evaluator.evaluate_split()` already computes
        balanced_accuracy/macro_f1/coverage/classwise recall per model.
        This method computes NOTHING new -- it only persists, verbatim,
        whatever per-branch metrics the caller already computed elsewhere,
        so the dashboard/CSV/LaTeX/figures all read one canonical source.
        Every branch entry MUST declare its own real `branch` (one of the 4
        known RQ2 branches) and `analysis_role`
        (PRIMARY/SENSITIVITY/UNSELECTED) -- never inferred, never
        defaulted. All other per-branch fields (`balanced_accuracy`,
        `balanced_accuracy_ci`, `macro_f1`, `coverage`, `classwise_recall`,
        `serialized_model_size_bytes`, `inference_latency_ms`,
        `seed_variability`, `model_bundle_id`, `model_bundle_sha256`) are
        optional pass-through -- absent means not yet measured for that
        branch, never a fabricated 0."""
        validated: list[dict[str, Any]] = []
        for entry in branch_results:
            missing = [f for f in _RQ2_REQUIRED_BRANCH_FIELDS if not entry.get(f)]
            if missing:
                raise ValueError(f"RQ2_BRANCH_RESULT_MISSING_REQUIRED_FIELDS:{missing}")
            if entry["branch"] not in _RQ2_KNOWN_BRANCHES:
                raise ValueError(f"RQ2_UNKNOWN_BRANCH:{entry['branch']}")
            if entry["analysis_role"] not in _RQ2_ANALYSIS_ROLES:
                raise ValueError(f"RQ2_INVALID_ANALYSIS_ROLE:{entry['analysis_role']}")
            validated.append(entry)
        git_sha, _ = self._git_provenance()
        artifact = {
            "schema_version": "ble-scientific-results-rq2-representation-comparison-v1",
            "protocol_id": protocol_id, "protocol_version": protocol_version, "contract_sha256": contract_sha256, "git_sha": git_sha,
            "dataset_id": dataset_id, "dataset_version": dataset_version,
            "split_manifest_id": split_manifest_id, "split_manifest_sha256": split_manifest_sha256,
            # Figure/artifact sync closure (2026-08-18): a structural fact
            # about the mechanism, not a result -- every RQ2 branch is
            # trained/evaluated via Evaluator.evaluate_split() on
            # ExampleRecord-level predictions, never decision-window
            # aggregated, so this is always "EXAMPLE_RECORD" today. Same
            # DEVELOPMENT/PROTECTED_FUTURE/PENDING vocabulary as RQ1's own
            # evidence_status (see persist_rq1_acquisition_dependence_report).
            "evaluation_unit": evaluation_unit, "evidence_status": evidence_status,
            "branches": validated,
            # Real provenance for the PRIMARY branch's selection -- lets a
            # figure/table state, from the persisted artifact itself (never
            # from code/docstrings alone), that PRIMARY was chosen using
            # VALIDATION only. select_primary_rq2_branch_from_validation()
            # already returns this exact rule string; previously discarded
            # by its only real caller (rq2_benchmark.py).
            "selection_rule": selection_rule, "selection_domain": selection_domain,
            "generated_at": utc_now(),
        }
        atomic_json(self._run_dir(paper_run_id) / "06_statistics" / "rq2_representation_comparison_report.json", artifact)
        self.logger.info("rq2 representation-comparison report persisted paper_run_id=%s protocol_id=%s branches=%s", paper_run_id, protocol_id, len(validated))
        return artifact

    def get_rq2_representation_comparison_report(self, paper_run_id: str) -> dict[str, Any] | None:
        path = self._run_dir(paper_run_id) / "06_statistics" / "rq2_representation_comparison_report.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def get_rq4_full_burst_vs_pre_pdu_exploratory_report(self, paper_run_id: str) -> dict[str, Any] | None:
        """DEVELOPMENT_EXPLORATORY analytical-region control (FULL_BURST vs
        PRE_PDU) -- distinct from the still-not-executed RQ4 packet-condition
        intervention. Same read-only convention as the RQ1/RQ2 getters
        above."""
        path = self._run_dir(paper_run_id) / "06_statistics" / "rq4_full_burst_vs_pre_pdu_exploratory_report.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def get_session_stability_analysis_report(self, paper_run_id: str) -> dict[str, Any] | None:
        """DEVELOPMENT_EXPLORATORY, purely descriptive (2026-08-24):
        per-(physical_unit_id, session_id) recall/score/feature-median
        breakdown over PRIMARY's own real VALIDATION predictions -- no
        retraining, no causal model. Same read-only convention as the
        RQ1/RQ2/RQ4/feature-group-ablation getters above."""
        path = self._run_dir(paper_run_id) / "06_statistics" / "session_stability_analysis_report.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def get_feature_group_ablation_exploratory_report(self, paper_run_id: str) -> dict[str, Any] | None:
        """DEVELOPMENT_EXPLORATORY feature-group ablation (2026-08-24):
        FULL (10 engineered descriptors, reuses PRIMARY) vs.
        POWER_AMPLITUDE_LEVEL (4) vs. REMAINING_SIX (6), same VALIDATION
        population as PRIMARY throughout. Same read-only convention as the
        RQ1/RQ2/RQ4 getters above."""
        path = self._run_dir(paper_run_id) / "06_statistics" / "feature_group_ablation_exploratory_report.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def get_evidence_dashboard_summary(self) -> dict[str, Any]:
        """Real, in-platform paper-support dashboard: assembles ALREADY
        PERSISTED RQ1/RQ2 reports (closed-set MULTI_DEVICE_CLASSIFICATION
        run + the per-unit TARGET_VS_BACKGROUND auxiliary runs, discriminated
        via PaperRunRecord.scientific_task from list_runs() -- never a
        hardcoded paper_run_id), the frozen rq3_sample_size scientist
        decision plus real, live RQ3 campaign progress, RQ4 per-unit
        eligibility from PhysicalDeviceRegistry, and study-level provenance
        (protocol_id/contract_sha256/git_sha) from get_study_status().
        Computes NO new science and NO new statistic -- every number here
        already exists as a real, independently-generated artifact; this
        method only cross-references them, exactly like
        get_experiment_health_summary() does for Level A. Every section
        keeps its own source's real generated_at/git_sha/dataset_id so the
        caller can show provenance without any new tracking."""
        study_status = self.get_study_status()
        runs = self.list_runs()
        closed_set_run = next((r for r in runs if r.scientific_task == "MULTI_DEVICE_CLASSIFICATION"), None)
        per_unit_runs = [r for r in runs if r.scientific_task == "TARGET_VS_BACKGROUND"]

        closed_set: dict[str, Any] | None = None
        if closed_set_run is not None:
            rq1 = self.get_rq1_acquisition_dependence_report(closed_set_run.paper_run_id)
            rq2 = self.get_rq2_representation_comparison_report(closed_set_run.paper_run_id)
            primary = next((b for b in (rq2 or {}).get("branches", []) if b.get("analysis_role") == "PRIMARY"), None)
            primary_evaluation = self._load_training_run_evaluation(primary["training_run_id"]) if primary else None
            closed_set = {
                "paper_run_id": closed_set_run.paper_run_id, "dataset_id": closed_set_run.dataset_id,
                "dataset_version": closed_set_run.dataset_version, "rq1": rq1, "rq2": rq2,
                "primary_branch": primary.get("branch") if primary else None,
                "primary_training_run_id": primary.get("training_run_id") if primary else None,
                "primary_test": (primary_evaluation or {}).get("TEST"),
            }

        per_unit_auxiliary = []
        for run in per_unit_runs:
            rq1_report = self.get_rq1_acquisition_dependence_report(run.paper_run_id)
            rq2_report = self.get_rq2_representation_comparison_report(run.paper_run_id)
            # Many historical/exploratory TARGET_VS_BACKGROUND paper_runs
            # exist on disk with neither report ever computed -- excluded
            # here, not hidden: a run with zero real results contributes
            # nothing this paper's dashboard needs, and listing 20+ empty
            # rows next to the 4 real ones would bury them, not support them.
            if rq1_report is None and rq2_report is None:
                continue
            per_unit_auxiliary.append({
                "paper_run_id": run.paper_run_id, "dataset_id": run.dataset_id, "dataset_version": run.dataset_version,
                "rq1": rq1_report, "rq2": rq2_report,
            })

        decisions = self.get_latest_scientist_decisions()
        registry = PhysicalDeviceRegistry(self.ble_root / "registry")
        physical_units = [
            {
                "physical_unit_id": unit.physical_unit_id, "rq4_eligibility": unit.rq4_eligibility,
                "rq4_eligibility_reason": unit.rq4_eligibility_reason,
            }
            for unit in registry.list_physical_units()
        ]

        return {
            "schema_version": "ble-scientific-results-evidence-dashboard-v1",
            "generated_at": utc_now(), "git_sha": study_status.get("git_sha"),
            "protocol_id": study_status.get("protocol_id"), "protocol_version": study_status.get("protocol_version"),
            "contract_sha256": study_status.get("contract_sha256"),
            "closed_set": closed_set, "per_unit_auxiliary": per_unit_auxiliary,
            "rq3": {
                "sample_size_decision": decisions.get("rq3_sample_size"),
                "campaign_progress": self._rq3_campaign_progress(),
            },
            "rq4": {
                "physical_units": physical_units,
                "status": "ELIGIBLE_UNITS_PRESENT" if any(u["rq4_eligibility"] == "ELIGIBLE" for u in physical_units) else "DATA_NOT_AVAILABLE",
            },
        }

    # Same real, established BLE advertising channel <-> center-frequency
    # mapping already defined independently in ble_rffi_studio's
    # campaign_orchestrator.py/studio_repository.py/evidence_stage.py --
    # duplicated here (a plain physical constant, not a computation) rather
    # than adding a StudioRepository dependency to this class, which reads
    # ble_rffi_studio's real storage directly everywhere else in this file.
    _BLE_CHANNEL_FREQUENCIES_HZ = {37: 2_402_000_000, 38: 2_426_000_000, 39: 2_480_000_000}

    def _resolve_ble_channel(self, center_frequency_hz: float | None) -> int | None:
        if not center_frequency_hz:
            return None
        for channel, hz in self._BLE_CHANNEL_FREQUENCIES_HZ.items():
            if abs(hz - center_frequency_hz) < 1_000_000.0:
                return channel
        return None

    def build_tx_composition_table(self) -> list[dict[str, Any]]:
        """Real, per-unit composition table -- device identity from
        PhysicalDeviceRegistry, real capture count/day-range/channels from
        _load_all_captures(). Unit identity for capture attribution follows
        pre_post_pairing.py's own real convention (target_reference_id,
        falling back to isolation_declared_physical_unit_id) -- never the
        address-resolved physical_unit_id, which CaptureRecord does not
        carry. No such single table existed before this (confirmed:
        dataset_composition_report is scoped to one dataset, not the whole
        enrolled population)."""
        registry = PhysicalDeviceRegistry(self.ble_root / "registry")
        captures = self._load_all_captures()
        rows: list[dict[str, Any]] = []
        for unit in registry.list_physical_units():
            unit_captures = [c for c in captures if (c.target_reference_id or c.isolation_declared_physical_unit_id) == unit.physical_unit_id]
            channels = sorted({ch for c in unit_captures if (ch := self._resolve_ble_channel(c.center_frequency_hz)) is not None})
            day_ids = sorted({c.day_id for c in unit_captures if c.day_id})
            rows.append({
                "physical_unit_id": unit.physical_unit_id, "device_family": unit.device_family,
                "manufacturer": unit.manufacturer, "model": unit.model, "project_id": unit.project_id,
                "status": unit.status, "rq4_eligibility": unit.rq4_eligibility,
                "real_capture_count": len(unit_captures), "channels": channels,
                "day_range": {"first": day_ids[0], "last": day_ids[-1]} if day_ids else None,
            })
        return rows

    def build_partition_composition_table(self, dataset_id: str, dataset_version: str, scientific_task: str) -> dict[str, Any]:
        """Real captures/acquisition-groups/decision-windows per TRAIN/
        VALIDATION/TEST for one real split -- thin composition of already-
        real SplitManifest.assignments (via domain_group_counts, §B) over
        the same split the confirmatory analysis actually reads
        (_load_split, already used elsewhere in this file)."""
        split = self._load_split(dataset_id, dataset_version, scientific_task)
        return {
            "dataset_id": dataset_id, "dataset_version": dataset_version, "scientific_task": scientific_task,
            "split_status": split.split_status, "leakage_check_status": split.leakage_check.status,
            "domains": {domain: paper_figure_aggregations.domain_group_counts(split, domain) for domain in ("TRAIN", "VALIDATION", "TEST")},
        }

    def build_receiver_epoch_table(self) -> list[dict[str, Any]]:
        """Real table of distinct receiver_epoch values -- identity +
        qualified acquisition profile + session boundary, per
        receiver_epoch_assignment.py -- with their real boundary reason,
        captures, days, channels, and physical units. No aggregator over
        this already-real, already-persisted CaptureRecord field existed
        before this."""
        captures = self._load_all_captures()
        by_epoch: dict[str, dict[str, Any]] = {}
        for capture in captures:
            if not capture.receiver_epoch:
                continue
            bucket = by_epoch.setdefault(capture.receiver_epoch, {
                "boundary_reason": capture.receiver_epoch_boundary_reason,
                "capture_ids": [], "day_ids": set(), "channels": set(), "physical_units": set(),
            })
            bucket["capture_ids"].append(capture.capture_id)
            if capture.day_id:
                bucket["day_ids"].add(capture.day_id)
            channel = self._resolve_ble_channel(capture.center_frequency_hz)
            if channel is not None:
                bucket["channels"].add(channel)
            unit_id = capture.target_reference_id or capture.isolation_declared_physical_unit_id
            if unit_id:
                bucket["physical_units"].add(unit_id)
        return [
            {
                "receiver_epoch": epoch, "boundary_reason": bucket["boundary_reason"],
                "n_captures": len(bucket["capture_ids"]), "day_ids": sorted(bucket["day_ids"]),
                "channels": sorted(bucket["channels"]), "physical_units": sorted(bucket["physical_units"]),
            }
            for epoch, bucket in sorted(by_epoch.items())
        ]

    _COMPLETENESS_STATUS_MAP = {"COMPLETE": "AVAILABLE", "PRELIMINARY": "AVAILABLE", "DATA_PENDING": "PENDING_REAL_ACQUISITION"}

    def get_scientific_completeness_report(self) -> dict[str, Any]:
        """ONE artifact answering "what does the paper still need, and what
        is its real status" -- AVAILABLE / PENDING_REAL_ACQUISITION /
        BLOCKED / NOT_ELIGIBLE / PROTECTED, with a real reason and missing-
        evidence list per item. Composes get_paper_readiness() (per-
        manuscript-element) + get_analysis_contract_readiness() (the real
        16-field confirmatory-freeze gate) + RQ3 campaign progress + RQ4
        eligibility + association status into ONE vocabulary -- deliberately
        NOT an extension of get_paper_readiness()'s own DATA_PENDING/
        PRELIMINARY/COMPLETE enum in place, since other real consumers
        already depend on that exact vocabulary (confirmed via research
        before this pass); composing over it is the safe direction.
        Preserves this project's own "implemented vs experimentally
        validated" distinction -- nothing here is a mechanism-exists check,
        every status reflects real, current data."""
        readiness_rows = self.get_paper_readiness()
        contract_readiness = self.get_analysis_contract_readiness()
        study_status = self.get_study_status()
        rq3_progress = self._rq3_campaign_progress()
        rq3_target = (self.get_latest_scientist_decisions().get("rq3_sample_size") or {}).get("selected_value") or {}
        registry = PhysicalDeviceRegistry(self.ble_root / "registry")
        rq4_units = registry.list_physical_units()
        rq4_eligible = [u for u in rq4_units if u.rq4_eligibility == "ELIGIBLE"]

        items: list[dict[str, Any]] = []
        for row in readiness_rows:
            items.append({
                "item": row.get("manuscript_element"), "status": self._COMPLETENESS_STATUS_MAP.get(row.get("paper_evidence_status"), "PENDING_REAL_ACQUISITION"),
                "reason": f"evidence_maturity={row.get('evidence_maturity')}, mechanism={row.get('mechanism_state')}",
                "missing_evidence": [] if row.get("paper_evidence_status") == "COMPLETE" else [row.get("canonical_artifact") or "no canonical artifact yet"],
            })

        # Real, specific overrides -- more precise than the generic
        # paper_readiness row for items the user explicitly named.
        items.append({
            "item": "rq1_protected_future", "status": "PROTECTED",
            "reason": f"protected_future_test_status={study_status.get('protected_future_test_status')}",
            "missing_evidence": ["confirmatory readiness (protocol_freeze_readiness)", "a real, later acquisition period", "run_confirmatory_future_analysis"],
        })
        total_target_pairs = rq3_target.get("total_valid_pairs")
        items.append({
            "item": "rq3_reset_vs_continuous", "status": "AVAILABLE" if rq3_progress["captures_with_rq3_metadata"] >= (total_target_pairs or 1) * 2 else "PENDING_REAL_ACQUISITION",
            "reason": f"{rq3_progress['captures_with_rq3_metadata']} real captures with RQ3 metadata declared" + (f" of {total_target_pairs} valid pairs targeted ({(total_target_pairs or 0) * 2} captures)" if total_target_pairs else " -- no rq3_sample_size decision frozen yet"),
            "missing_evidence": [] if total_target_pairs and rq3_progress["captures_with_rq3_metadata"] >= total_target_pairs * 2 else ["real RESET/CONTROL PRE/POST captures (0 today)"],
        })
        items.append({
            "item": "rq4_packet_content_dependence", "status": "AVAILABLE" if rq4_eligible else "NOT_ELIGIBLE",
            "reason": f"{len(rq4_eligible)}/{len(rq4_units)} enrolled units eligible" if rq4_units else "no physical units registered",
            "missing_evidence": [] if rq4_eligible else [u.rq4_eligibility_reason or f"{u.physical_unit_id}: no reason recorded" for u in rq4_units],
        })
        items.append({
            "item": "strong_native_sdr_association", "status": "BLOCKED",
            "reason": f"association_policy_status={study_status.get('association_policy_status')}",
            "missing_evidence": ["a calibration campaign producing a policy that satisfies the real acceptance criteria (every real attempt today reports NO_THRESHOLD_SATISFIES_CRITERIA)"],
        })
        items.append({
            "item": "confirmatory_protocol_freeze", "status": "BLOCKED" if contract_readiness["protocol_freeze_readiness"]["status"] == "BLOCKED" else "AVAILABLE",
            "reason": f"{len(contract_readiness['protocol_freeze_readiness']['missing'])} required fields/gates still missing",
            "missing_evidence": contract_readiness["protocol_freeze_readiness"]["missing"],
        })

        return {
            "schema_version": "ble-scientific-results-scientific-completeness-v1", "generated_at": utc_now(),
            "git_sha": study_status.get("git_sha"), "items": items,
        }

    def regenerate_evidence_figures(self) -> dict[str, Any]:
        """UI-triggered equivalent of running, from a terminal:
            docs/ble/generate_evidence_figures.py
            docs/ble/build_evidence_notebook.py
        Loads and calls those two scripts' own real main() functions by file
        path (importlib, never a subprocess, never a second implementation
        of their plotting logic) -- the button and the documented CLI path
        run the exact same code. Writes real PNG/ipynb files into the repo
        working tree (readme_img/evidence_*.png, docs/ble/
        evidence_figures.ipynb), deliberately outside the usual storage
        root, since these files are meant to be reviewed and committed by
        the operator -- this method never runs git itself."""
        import importlib.util

        repo_root = Path(__file__).resolve().parents[5]
        figures_path = repo_root / "docs" / "ble" / "generate_evidence_figures.py"
        notebook_path = repo_root / "docs" / "ble" / "build_evidence_notebook.py"
        if not figures_path.is_file() or not notebook_path.is_file():
            raise FileNotFoundError(f"EVIDENCE_FIGURE_SCRIPTS_NOT_FOUND:{figures_path}:{notebook_path}")

        def _load_and_run(path: Path, module_name: str) -> None:
            spec = importlib.util.spec_from_file_location(module_name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)  # type: ignore[union-attr]
            module.main()

        started_at = utc_now()
        _load_and_run(figures_path, "_evidence_figures_regen")
        _load_and_run(notebook_path, "_evidence_notebook_regen")

        png_dir = repo_root / "readme_img"
        written = sorted(p.name for p in png_dir.glob("evidence_*.png"))
        notebook_written = (repo_root / "docs" / "ble" / "evidence_figures.ipynb").is_file()
        return {
            "started_at": started_at, "finished_at": utc_now(),
            "png_files": written, "notebook_written": notebook_written,
            "note": "Files written to the repo working tree -- review and commit/push separately; this action never runs git.",
        }

    def run_paper_export(self) -> dict[str, Any]:
        """Real production caller for paper_export.py -- writes
        `paper_exports/` for real (study_status.json/paper_readiness.json)
        and records every other planned export as SKIPPED_NO_DATA until a
        real campaign produces source data for it. Never mutates the
        protocol, never opens FUTURE_TEST."""
        manifest = generate_paper_exports(self)
        self.logger.info("paper export generated: %s produced, %s skipped_no_data", manifest["generated_count"], manifest["skipped_count"])
        return manifest

    def get_paper_export_manifest(self) -> dict[str, Any] | None:
        path = self.root / "paper_exports" / "export_manifest.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Provenance reconstruction (2026-08-11) -- strictly read-only.
    # ------------------------------------------------------------------

    def list_inference_runs(self) -> list[dict[str, Any]]:
        return _list_inference_runs(self)

    def get_decision_provenance(self, *, inference_run_id: str, example_id: str) -> dict[str, Any]:
        return reconstruct_decision_provenance(self, inference_run_id=inference_run_id, example_id=example_id)

    # ------------------------------------------------------------------
    # Engineering reports: S1 channel transport, S2 offline/near-live
    # (2026-08-11) -- pure aggregation over caller-supplied, already-scored
    # predictions; never retrains, never a new statistical test. NO_DATA
    # persisted-report reads mirror the RQ1/confirmatory-future pattern.
    # ------------------------------------------------------------------

    def compute_channel_transport_report(self, **kwargs: Any) -> dict[str, Any]:
        from dataclasses import asdict
        return asdict(_compute_channel_transport_report(**kwargs))

    def persist_channel_transport_report(self, paper_run_id: str, report: dict[str, Any]) -> dict[str, Any]:
        atomic_json(self._run_dir(paper_run_id) / "06_statistics" / "channel_transport_report.json", report)
        return report

    def get_channel_transport_report(self, paper_run_id: str) -> dict[str, Any] | None:
        path = self._run_dir(paper_run_id) / "06_statistics" / "channel_transport_report.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def compute_offline_nearlive_report(self, **kwargs: Any) -> dict[str, Any]:
        from dataclasses import asdict
        return asdict(_compute_offline_nearlive_report(**kwargs))

    def persist_offline_nearlive_report(self, paper_run_id: str, report: dict[str, Any]) -> dict[str, Any]:
        atomic_json(self._run_dir(paper_run_id) / "06_statistics" / "offline_nearlive_report.json", report)
        return report

    def get_offline_nearlive_report(self, paper_run_id: str) -> dict[str, Any] | None:
        path = self._run_dir(paper_run_id) / "06_statistics" / "offline_nearlive_report.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    def run_channel_transport_analysis(self, *, paper_run_id: str, offline_inference_service: Any, bundle_id: str | None = None) -> dict[str, Any]:
        """Phase 14 (S1) launcher backend (2026-08-12, fast-closure pass):
        compute_channel_transport_report was real and tested but had no
        real caller gathering real per-channel predictions -- this is that
        missing orchestration, structurally identical to run_rq3_frr_
        analysis/run_coverage_analysis's own pattern (never a second
        scoring path). Scores EVERY real capture's examples with the
        frozen PRIMARY RQ2 branch bundle (frozen on CH37 development data,
        never retrained per channel -- one bundle_id for every channel,
        matching "bounded channel transport", never "channel invariance"),
        groups by ExampleRecord.channel. Ground truth follows the SAME
        train_label_for() convention RQ3 uses, so this works correctly for
        both SAME_MODEL_UNIT_IDENTIFICATION and TARGET_VS_BACKGROUND."""
        from app.modules.ble_rffi_studio.quality.split_builder import train_label_for

        run = self.get_run(paper_run_id)
        if bundle_id is None:
            rq2_report = self.get_rq2_representation_comparison_report(paper_run_id)
            primary = next((b for b in (rq2_report or {}).get("branches", []) if b.get("analysis_role") == "PRIMARY"), None)
            if primary is None or not primary.get("model_bundle_id"):
                raise ValueError("NO_FROZEN_PRIMARY_RQ2_BRANCH_WITH_A_MODEL_BUNDLE_ID:run RQ2 Benchmark first, or pass bundle_id explicitly")
            bundle_id = primary["model_bundle_id"]

        captures = self._load_all_captures()
        known_classes = sorted({c.physical_unit_id for c in captures if c.physical_unit_id})
        center_frequency_hz_by_channel: dict[int, int] = {}
        predictions_by_channel: dict[int, list[dict[str, Any]]] = {}
        for capture in captures:
            examples = self._load_examples(capture.capture_id)
            if not examples:
                continue
            decisions = offline_inference_service.run(bundle_id=bundle_id, examples=examples)
            decisions_by_example_id = {d["example_id"]: d for d in decisions}
            for example in examples:
                decision = decisions_by_example_id.get(example.example_id)
                if decision is None:
                    continue
                channel = example.channel
                center_frequency_hz_by_channel.setdefault(channel, example.center_frequency_hz)
                predictions_by_channel.setdefault(channel, []).append({
                    "example_id": example.example_id, "true_label": train_label_for(run.scientific_task, example),
                    "predicted_label": decision["predicted_class"], "final_decision": decision["final_decision"],
                    "physical_unit_id": example.physical_unit_id,
                })
        if not predictions_by_channel:
            raise ValueError("NO_REAL_EXAMPLES_TO_SCORE:0 real captures with real examples exist yet")

        report = self.compute_channel_transport_report(
            frozen_bundle_id=bundle_id, predictions_by_channel=predictions_by_channel, known_classes=known_classes,
            center_frequency_hz_by_channel=center_frequency_hz_by_channel,
        )
        self.persist_channel_transport_report(paper_run_id, report)
        self.logger.info("channel transport analysis persisted paper_run_id=%s bundle_id=%s channels=%s", paper_run_id, bundle_id, sorted(predictions_by_channel))
        return report

    def run_offline_nearlive_analysis(
        self, *, paper_run_id: str, offline_predictions: list[dict[str, Any]] | None = None,
        nearlive_predictions: list[dict[str, Any]] | None = None, computational_metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Phase 15 (S2) launcher backend (2026-08-12, fast-closure pass):
        wraps the already-real compute_offline_nearlive_report as a real,
        callable orchestration -- never invents a near-live prediction
        source. No real near-live-inference gathering mechanism exists in
        this codebase yet (Live Monitor's streaming path is not wired to
        emit evidence_interval_id-tagged predictions), so calling this with
        no arguments honestly persists a NO_DATA/NOT_MEASURED report --
        exactly the existing honest behavior, never fabricated. When the
        caller DOES have real offline/near-live predictions (each carrying
        a real evidence_interval_id), this is the real path to persist
        them, unchanged from compute_offline_nearlive_report's own pure
        pairing logic."""
        report = self.compute_offline_nearlive_report(
            offline_predictions=offline_predictions, nearlive_predictions=nearlive_predictions, computational_metrics=computational_metrics,
        )
        self.persist_offline_nearlive_report(paper_run_id, report)
        self.logger.info("offline/near-live analysis persisted paper_run_id=%s pairing_status=%s", paper_run_id, report.get("pairing_status"))
        return report

    # ------------------------------------------------------------------
    # Fase 2: canonical records (Section B)
    # ------------------------------------------------------------------

    def _canonical_records_dir(self, paper_run_id: str) -> Path:
        return self._run_dir(paper_run_id) / "01_inputs" / "canonical_records"

    def find_frozen_association_policy(self) -> AssociationPolicy | None:
        """P0.4 correction (2026-08-08): scans every real calibration
        attempt's persisted result (written by Guided Validation's
        association-policy calibration -- see
        guided_validation/service.py::_attempt_policy) for the most
        recently frozen, real AssociationPolicy, so build_records() picks
        one up automatically the moment a real calibration campaign ever
        succeeds, with zero further code changes. Returns None when no
        calibration has ever succeeded -- the honest, current state of
        every real calibration attempt on disk as of 2026-08, all of which
        report NO_THRESHOLD_SATISFIES_CRITERIA. Deliberately does not
        consider FROZEN_STRATIFIED (per-device-family) policies here --
        build_records() applies one policy project-wide; stratified policy
        selection per device family is a documented future extension, not
        silently approximated by picking one family's policy for everyone."""
        candidates: list[AssociationPolicy] = []
        guided_validation_root = self.root / "guided_validation"
        if guided_validation_root.is_dir():
            for policy_path in guided_validation_root.glob("*/association_policy.json"):
                try:
                    data = json.loads(policy_path.read_text(encoding="utf-8-sig"))
                except (json.JSONDecodeError, OSError):
                    continue
                if data.get("status") == "FROZEN" and isinstance(data.get("policy"), dict):
                    try:
                        candidates.append(AssociationPolicy.model_validate(data["policy"]))
                    except Exception:
                        continue
        if not candidates:
            return None
        return max(candidates, key=lambda policy: policy.frozen_at)

    def get_latest_association_calibration_summary(self) -> dict[str, Any] | None:
        """Paper-representation pass (2026-08-17): the most recent real
        calibration attempt of ANY outcome -- FROZEN, FROZEN_STRATIFIED, or
        NO_THRESHOLD_SATISFIES_CRITERIA (today's real, current status) --
        for the Results Dashboard, so the real per-threshold sweep is
        visible even while every real attempt keeps failing to freeze a
        policy. Same real scan as find_frozen_association_policy(), just
        without its FROZEN-only filter. None only when no calibration has
        ever been attempted at all."""
        guided_validation_root = self.root / "guided_validation"
        if not guided_validation_root.is_dir():
            return None
        candidates: list[dict[str, Any]] = []
        for policy_path in guided_validation_root.glob("*/association_policy.json"):
            try:
                data = json.loads(policy_path.read_text(encoding="utf-8-sig"))
            except (json.JSONDecodeError, OSError):
                continue
            candidates.append(data)
        if not candidates:
            return None
        # evaluated_at is real on every attempt persisted after this pass;
        # older attempts (pre-2026-08-17) sort first, never crash the max().
        return max(candidates, key=lambda c: c.get("evaluated_at") or "")

    def build_records(self, paper_run_id: str, *, schedule_id: str | None = None, association_policy: AssociationPolicy | None = None, progress=None) -> RecordBuildResult:
        """`schedule_id`, when the campaign this run covers was executed
        through PaperCampaignRunner, pulls in that schedule's persisted
        pre-capture rejections (see records/build_records.py) as canonical
        PROTOCOL_DEVIATION rows -- optional because most runs today still
        predate the runner and have no schedule to check.

        `association_policy`: without a real, frozen policy (produced by a
        real calibration campaign -- see calibration/association_calibration.py),
        every burst's TARGET_ASSOCIATED_PACKET classification is disabled
        (STRONG_ASSOCIATION_DISABLED_UNTIL_POLICY_FROZEN) regardless of what
        the underlying ledger contains -- there is no default threshold.
        Callers normally leave this None and let it auto-resolve via
        find_frozen_association_policy() -- pass one explicitly only to
        pin a specific historical policy version."""
        if association_policy is None:
            association_policy = self.find_frozen_association_policy()
        run = self.get_run(paper_run_id)
        contract = self.get_protocol(run.protocol_id, run.protocol_version)
        dataset = self._load_dataset(run.dataset_id, run.dataset_version)
        split = self._load_split(run.dataset_id, run.dataset_version, run.scientific_task)
        return _build_records(
            paper_run_id=paper_run_id, protocol_id=run.protocol_id, campaign_id=run.campaign_id,
            association_policy_hash=contract.association_policy_hash, dataset=dataset, split=split,
            run_dir=self._run_dir(paper_run_id), ble_root=self.ble_root, legacy_capture_root=self.legacy_capture_root,
            load_capture=self._load_capture, load_examples=self._load_examples, schedule_id=schedule_id,
            association_policy=association_policy, progress=progress,
        )

    def get_records_status(self, paper_run_id: str) -> RecordBuildResult | None:
        path = self._canonical_records_dir(paper_run_id) / "build_result.json"
        if not path.is_file():
            return None
        return RecordBuildResult.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def _load_record_table(self, paper_run_id: str, table_name: str) -> list[dict[str, Any]]:
        path = self._canonical_records_dir(paper_run_id) / f"{table_name}.json"
        if not path.is_file():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    def list_capture_records(self, paper_run_id: str, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self._load_record_table(paper_run_id, "capture_records")[offset: offset + limit]

    def get_capture_record(self, paper_run_id: str, capture_id: str) -> dict[str, Any] | None:
        for row in self._load_record_table(paper_run_id, "capture_records"):
            if row.get("capture_id") == capture_id:
                return row
        return None

    def list_burst_records(self, paper_run_id: str, *, limit: int = 100, offset: int = 0, capture_id: str | None = None) -> list[dict[str, Any]]:
        rows = self._load_record_table(paper_run_id, "burst_records")
        if capture_id:
            rows = [row for row in rows if row.get("capture_id") == capture_id]
        return rows[offset: offset + limit]

    def list_window_records(self, paper_run_id: str, *, limit: int = 100, offset: int = 0, capture_id: str | None = None) -> list[dict[str, Any]]:
        rows = self._load_record_table(paper_run_id, "decision_window_records")
        if capture_id:
            rows = [row for row in rows if row.get("capture_id") == capture_id]
        return rows[offset: offset + limit]

    def list_deviation_records(self, paper_run_id: str, *, limit: int = 200, offset: int = 0) -> list[dict[str, Any]]:
        return self._load_record_table(paper_run_id, "campaign_deviations")[offset: offset + limit]

    # ------------------------------------------------------------------
    # Fase 2: campaign accounting (Sections C+D)
    # ------------------------------------------------------------------

    def build_campaign_accounting(self, paper_run_id: str) -> dict[str, Any]:
        run = self.get_run(paper_run_id)
        contract = self.get_protocol(run.protocol_id, run.protocol_version)
        return _build_campaign_accounting(run_dir=self._run_dir(paper_run_id), contract=contract)

    def get_campaign_accounting(self, paper_run_id: str) -> dict[str, Any] | None:
        path = self._run_dir(paper_run_id) / "03_campaign_accounting" / "campaign_accounting.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Fase 2: descriptive quality summary (Section E)
    # ------------------------------------------------------------------

    def build_quality_summary(self, paper_run_id: str) -> dict[str, Any]:
        return _build_quality_summary(run_dir=self._run_dir(paper_run_id))

    def get_quality_summary(self, paper_run_id: str) -> dict[str, Any] | None:
        path = self._run_dir(paper_run_id) / "04_quality" / "quality_summary.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # Scientific Dashboard closure, Level A: Experiment Health (2026-08-11)
    # ------------------------------------------------------------------

    def get_experiment_health_summary(self) -> dict[str, Any]:
        """Level A -- a single, real cross-reference of already-real
        getters (PaperCampaignSchedule entries/rejections on disk, real
        campaign_deviations canonical rows, already-real association/
        protocol/holdout status). Computes no new science: block counts are
        real len()/sum() over real entries, `rejected_attempt_count` is a
        real count of real rejections.jsonl lines keyed by
        `planned_capture_id` (there is no "retries" field anywhere in the
        codebase -- this is the closest real, honestly-named proxy, never
        invented as a literal retry counter). `deviation_type_distribution`
        uses the REAL deviation_type values `campaign_deviations.py`
        produces today (DUPLICATE_CAPTURE/CAPTURE_NOT_FOUND/OVERFLOW/
        DISCONTINUITY/METADATA_INCOMPLETE/SPLIT_CONFLICT/the 11 real
        CAPTURE_OUT_OF_SCHEDULE-family runner-rejection codes/
        NOT_DOCUMENTED_DESIGN_DIMENSION) -- never a renamed/invented
        category."""
        study_status = self.get_study_status()
        git_sha, _ = self._git_provenance()
        runs = self.list_runs()

        campaigns: list[dict[str, Any]] = []
        schedules_dir = self.ble_root / "paper_campaign" / "schedules"
        if schedules_dir.is_dir():
            for schedule_dir in sorted(p for p in schedules_dir.iterdir() if p.is_dir()):
                versions = sorted(int(p.stem) for p in schedule_dir.glob("*.json") if p.stem.isdigit())
                if not versions:
                    continue
                schedule = json.loads((schedule_dir / f"{versions[-1]}.json").read_text(encoding="utf-8"))
                entries = schedule.get("entries", [])

                rejected_by_planned_id: dict[str, int] = {}
                rejections_path = schedule_dir / "rejections.jsonl"
                if rejections_path.is_file():
                    for line in rejections_path.read_text(encoding="utf-8").splitlines():
                        if not line.strip():
                            continue
                        rejection = json.loads(line)
                        planned_id = rejection.get("planned_capture_id")
                        if planned_id:
                            rejected_by_planned_id[planned_id] = rejected_by_planned_id.get(planned_id, 0) + 1

                blocks_by_physical_unit: dict[str, dict[str, int]] = {}
                for entry in entries:
                    unit_id = entry.get("physical_unit_id") or "UNKNOWN"
                    bucket = blocks_by_physical_unit.setdefault(unit_id, {"scheduled_blocks": 0, "completed_blocks": 0, "rejected_attempt_count": 0})
                    bucket["scheduled_blocks"] += 1
                    if entry.get("executed"):
                        bucket["completed_blocks"] += 1
                    bucket["rejected_attempt_count"] += rejected_by_planned_id.get(entry.get("planned_capture_id"), 0)

                completed_blocks = sum(1 for e in entries if e.get("executed"))
                campaigns.append({
                    "schedule_id": schedule.get("schedule_id"), "schedule_version": versions[-1],
                    "protocol_id": schedule.get("protocol_id"),
                    "evidence_maturity": "QUALIFICATION" if schedule.get("qualification_only") else "DEVELOPMENT",
                    "scheduled_blocks": len(entries), "completed_blocks": completed_blocks,
                    "incomplete_blocks": len(entries) - completed_blocks,
                    "rejected_attempt_count": sum(rejected_by_planned_id.values()),
                    "physical_units": sorted(blocks_by_physical_unit.keys()),
                    "blocks_by_physical_unit": blocks_by_physical_unit,
                    "receiver_session_id": schedule.get("receiver_session_id"), "frozen_at": schedule.get("frozen_at"),
                    "paper_run_ids": [r.paper_run_id for r in runs if r.campaign_id == schedule.get("schedule_id")],
                })

        deviation_type_distribution: dict[str, int] = {}
        for run in runs:
            for deviation in self._load_record_table(run.paper_run_id, "campaign_deviations"):
                deviation_type = deviation.get("deviation_type") or "UNKNOWN"
                deviation_type_distribution[deviation_type] = deviation_type_distribution.get(deviation_type, 0) + 1

        return {
            "schema_version": "ble-scientific-results-experiment-health-v1",
            "generated_at": utc_now(), "git_sha": git_sha,
            "association_policy_status": study_status["association_policy_status"],
            "protocol_freeze_status": study_status["protocol_freeze_status"],
            "protected_future_test_status": study_status["protected_future_test_status"],
            "campaigns": campaigns,
            "deviation_type_distribution": deviation_type_distribution,
        }

    # ------------------------------------------------------------------
    # Scientific Dashboard closure, Level B: Data / Evidence Quality (2026-08-11)
    # ------------------------------------------------------------------

    def get_evidence_quality_summary(self, paper_run_id: str) -> dict[str, Any] | None:
        """Level B -- real per-capture/per-burst/per-window canonical rows
        (never re-aggregated science, only real counts/groupings over
        already-real canonical tables) plus the already-real
        campaign_accounting/quality_summary artifacts when they have been
        built for this run. Returns None (never a zeroed table) when the
        canonical record tables have not been built yet for this
        paper_run_id."""
        capture_rows = self._load_record_table(paper_run_id, "capture_records")
        if not capture_rows:
            return None
        burst_rows = self._load_record_table(paper_run_id, "burst_records")
        window_rows = self._load_record_table(paper_run_id, "decision_window_records")
        deviation_rows = self._load_record_table(paper_run_id, "campaign_deviations")

        candidate_bursts_per_capture: dict[str, int] = {}
        crc_valid_per_capture: dict[str, int] = {}
        admitted_per_capture: dict[str, int] = {}
        for burst in burst_rows:
            capture_id = burst.get("capture_id")
            if not capture_id:
                continue
            candidate_bursts_per_capture[capture_id] = candidate_bursts_per_capture.get(capture_id, 0) + 1
            if burst.get("crc_status") == "VALID":
                crc_valid_per_capture[capture_id] = crc_valid_per_capture.get(capture_id, 0) + 1
            if burst.get("packet_eligible") is True:
                admitted_per_capture[capture_id] = admitted_per_capture.get(capture_id, 0) + 1

        eligible_bursts_per_window: dict[str, int] = {}
        insufficient_evidence_windows = 0
        usable_windows = 0
        for window in window_rows:
            window_id = window.get("decision_window_id")
            eligible_count = window.get("eligible_count")
            if window_id is not None and isinstance(eligible_count, int):
                eligible_bursts_per_window[window_id] = eligible_count
            status = window.get("window_status")
            if status == "ACTIVE_ELIGIBLE":
                usable_windows += 1
            elif status == "ACTIVE_INSUFFICIENT_BURSTS":
                insufficient_evidence_windows += 1

        captures_per_physical_unit: dict[str, int] = {}
        captures_per_day: dict[str, int] = {}
        captures_per_role: dict[str, int] = {}
        exclusion_reason_counts: dict[str, int] = {}
        discontinuity_count = 0
        physical_unit_by_capture_id: dict[str, str] = {}
        for capture in capture_rows:
            unit_id = capture.get("physical_unit_id") or "UNKNOWN"
            captures_per_physical_unit[unit_id] = captures_per_physical_unit.get(unit_id, 0) + 1
            capture_id = capture.get("capture_id")
            if capture_id:
                physical_unit_by_capture_id[capture_id] = unit_id
            day_id = capture.get("day_id") or "UNKNOWN"
            captures_per_day[day_id] = captures_per_day.get(day_id, 0) + 1
            role = capture.get("experimental_role") or "UNKNOWN"
            captures_per_role[role] = captures_per_role.get(role, 0) + 1
            for reason in capture.get("blocking_reason_codes") or []:
                exclusion_reason_counts[reason] = exclusion_reason_counts.get(reason, 0) + 1
            if (capture.get("discontinuity_count") or 0) > 0:
                discontinuity_count += 1

        return {
            "schema_version": "ble-scientific-results-evidence-quality-v1",
            "generated_at": utc_now(), "paper_run_id": paper_run_id,
            "capture_count": len(capture_rows), "burst_count": len(burst_rows), "window_count": len(window_rows),
            "captures_per_physical_unit": captures_per_physical_unit,
            "captures_per_day": captures_per_day,
            "captures_per_experimental_role": captures_per_role,
            "candidate_bursts_per_capture": candidate_bursts_per_capture,
            "crc_valid_per_capture": crc_valid_per_capture,
            "admitted_per_capture": admitted_per_capture,
            "exclusion_reason_counts": exclusion_reason_counts,
            "eligible_bursts_per_window": eligible_bursts_per_window,
            "usable_windows": usable_windows,
            "insufficient_evidence_abstention_windows": insufficient_evidence_windows,
            "captures_with_discontinuities": discontinuity_count,
            "deviation_count": len(deviation_rows),
            # Scientific filtering (2026-08-11): a real capture_id -> unit_id
            # map so the dashboard can filter the per-capture breakdowns
            # above to one physical unit -- filtering already-real rows to a
            # real subset, never a new computation. The unfiltered
            # dictionaries above remain the canonical, official view.
            "physical_unit_by_capture_id": physical_unit_by_capture_id,
        }

    # ------------------------------------------------------------------
    # Fase 2: descriptive figures (Section F)
    # ------------------------------------------------------------------

    def build_campaign_figures(self, paper_run_id: str) -> list[str]:
        return _build_campaign_figures(run_dir=self._run_dir(paper_run_id))

    def list_run_artifacts(self, paper_run_id: str) -> list[str]:
        run_dir = self._run_dir(paper_run_id)
        if not run_dir.is_dir():
            raise FileNotFoundError(f"PAPER_RUN_NOT_FOUND:{paper_run_id}")
        return sorted(str(path.relative_to(run_dir)).replace("\\", "/") for path in run_dir.rglob("*") if path.is_file())

    # -- integrity -------------------------------------------------------

    def _check_integrity(self, dataset: DatasetManifest, split: SplitManifest, contract: AnalysisContract) -> IntegrityCheckResult:
        findings: list[str] = []

        recomputed_dataset_hash = dataset.content_hash(exclude={"frozen", "dataset_manifest_sha256"})
        if not dataset.frozen:
            findings.append(f"Dataset {dataset.dataset_id}/{dataset.dataset_version} is not frozen.")
        if dataset.dataset_manifest_sha256 != recomputed_dataset_hash:
            findings.append(
                f"Dataset manifest hash mismatch: stored={dataset.dataset_manifest_sha256} recomputed={recomputed_dataset_hash} "
                "(the on-disk file no longer matches its own recorded hash)."
            )

        if split.split_status == "READY":
            # split_purpose/non_confirmatory (2026-08-09) are excluded here
            # too -- must match split_builder.py's own _HASH_EXCLUDED_FIELDS
            # exactly, or every real historical split would report a false
            # hash mismatch purely from an additive metadata tag that
            # predates their existence.
            recomputed_split_hash = split.content_hash(exclude={"split_manifest_sha256", "split_purpose", "non_confirmatory"})
            if split.split_manifest_sha256 != recomputed_split_hash:
                findings.append(
                    f"Split manifest hash mismatch: stored={split.split_manifest_sha256} recomputed={recomputed_split_hash}."
                )

        if contract.split_manifest_hash and split.split_manifest_sha256 and contract.split_manifest_hash != split.split_manifest_sha256:
            findings.append(
                f"Frozen protocol commits to split_manifest_hash={contract.split_manifest_hash}, "
                f"but this run's split is {split.split_manifest_sha256}."
            )

        example_ids = dataset.example_ids
        if len(example_ids) != len(set(example_ids)):
            duplicates = sorted({example_id for example_id in example_ids if example_ids.count(example_id) > 1})
            findings.append(f"Duplicate example_id values in dataset.example_ids: {duplicates[:10]}")

        checked_captures = 0
        for capture_id in dataset.captures:
            capture = self._load_capture(capture_id)
            if capture is None:
                findings.append(f"Capture {capture_id} referenced by dataset but has no CaptureRecord on disk.")
                continue
            checked_captures += 1
            iq_path = self._resolve_iq_path(capture)
            if not iq_path.is_file():
                findings.append(f"Capture {capture_id}: resolved iq_path does not exist on disk ({iq_path}).")
            if not capture.iq_sha256:
                findings.append(f"Capture {capture_id}: missing iq_sha256.")
            for example in self._load_examples(capture_id):
                if not (0 <= example.iq_start_sample < example.iq_end_sample <= capture.sample_count):
                    findings.append(
                        f"Example {example.example_id}: sample range [{example.iq_start_sample},{example.iq_end_sample}) "
                        f"outside capture {capture_id}'s sample_count={capture.sample_count}."
                    )

        status = "BLOCKED" if findings else "PASSED"
        return IntegrityCheckResult(status=status, findings=findings, checked_capture_count=checked_captures)

    # -- leakage -----------------------------------------------------------

    def _check_leakage(self, split: SplitManifest) -> LeakageCheckResult:
        findings: list[str] = []
        if split.split_status != "READY":
            findings.append(f"Split status is {split.split_status} ({split.infeasibility_reason or 'no reason recorded'}); no leakage-safe partition exists to analyze on.")
        elif split.leakage_check.status != "PASSED":
            findings.append(
                f"Split leakage_check.status={split.leakage_check.status}; overlapping_keys={split.leakage_check.overlapping_keys}."
            )
        status = "BLOCKED" if findings else "PASSED"
        return LeakageCheckResult(status=status, findings=findings, checked_split_ids=[f"{split.dataset_id}__{split.dataset_version}__{split.scientific_task}"])

    # -- population separation ---------------------------------------------

    def _check_population_separation(self, dataset: DatasetManifest, examples: list[ExampleRecord], contract: AnalysisContract) -> PopulationSeparationResult:
        counts = {"same_model_enrolled": 0, "cross_model_ble": 0, "ambient_ble": 0, "target_absent_control": 0}
        for example in examples:
            if example.capture_purpose == "BACKGROUND_TARGET_OFF":
                counts["target_absent_control"] += 1
            elif example.physical_unit_id is not None and example.physical_unit_id in dataset.physical_units:
                counts["same_model_enrolled"] += 1
            elif example.physical_unit_id is not None:
                counts["cross_model_ble"] += 1
            else:
                counts["ambient_ble"] += 1

        findings: list[str] = []
        declared_population = contract.device_population or {}
        for population_name, declared in declared_population.items():
            if population_name in counts and declared and counts[population_name] == 0:
                findings.append(f"Protocol declares a non-empty '{population_name}' population, but 0 examples were observed for it in this dataset.")

        status = "BLOCKED" if findings else "PASSED"
        return PopulationSeparationResult(status=status, findings=findings, population_counts=counts)

    # -- quality -------------------------------------------------------------

    def _check_quality(self, quality_report: DatasetQualityReport | None) -> QualityCheckResult:
        findings: list[str] = []
        checked = []
        if quality_report is None:
            findings.append("No DatasetQualityReport found on disk for this dataset -- the quality gate was never run.")
        else:
            checked.append(f"{quality_report.dataset_id}__{quality_report.dataset_version}")
            if quality_report.gate_decision != "ACCEPTED_FOR_TRAINING":
                findings.append(f"gate_decision={quality_report.gate_decision}; gate_reasons={quality_report.gate_reasons}")
            if quality_report.exact_duplicates.status != "PASSED":
                findings.append(f"exact_duplicates.status={quality_report.exact_duplicates.status}")
            if quality_report.sample_overlap.status != "PASSED":
                findings.append(f"sample_overlap.status={quality_report.sample_overlap.status}")
        status = "BLOCKED" if findings else "PASSED"
        return QualityCheckResult(status=status, findings=findings, checked_dataset_ids=checked)

    # -- design completeness --------------------------------------------------

    def _check_design_completeness(self, dataset: DatasetManifest, examples: list[ExampleRecord], contract: AnalysisContract) -> DesignCompletenessResult:
        findings: list[str] = []

        declared_devices = set(contract.device_ids or [])
        observed_devices = set(dataset.physical_units)
        missing_devices = declared_devices - observed_devices
        if missing_devices:
            findings.append(f"Protocol declares device_ids not present in this dataset's physical_units: {sorted(missing_devices)}")

        declared_channels = set(contract.channels or [])
        observed_channels = {example.channel for example in examples}
        missing_channels = declared_channels - observed_channels
        if missing_channels:
            findings.append(f"Protocol declares channels with no observed examples in this dataset: {sorted(missing_channels)}")

        # Informational only, never blocking on its own in Fase 1: full
        # structured protocol_deviations.jsonl accounting arrives with
        # campaign accounting in a later phase.
        status = "BLOCKED" if findings else "PASSED"
        return DesignCompletenessResult(status=status, findings=findings)

    # -- paper campaign completeness (tier 2) --------------------------------

    def _check_paper_campaign_completeness(
        self, dataset: DatasetManifest, examples: list[ExampleRecord], contract: AnalysisContract, population: PopulationSeparationResult,
    ) -> PaperCampaignCompletenessResult:  # noqa: C901 -- see per-dimension comments; splitting further would scatter the shared checked/findings state
        holdout_groups = self.list_holdout_groups(dataset.dataset_id, dataset.dataset_version)
        """Whole-PAPER requirements, distinct from (and layered on top of)
        the dataset-structural checks above. Unlike design_completeness
        (tier 1, dataset-scoped), every dimension the user's specification
        lists for paper-campaign completeness is checked UNCONDITIONALLY --
        population, days, sessions, pre/post, reset/control, channels,
        content variants, independent blocks, groups/holdouts, receiver
        profile, negative controls -- never only "if the protocol happens
        to declare it". A protocol that declares nothing extra must not be
        able to trivially reach PAPER_CAMPAIGN_PREFLIGHT_PASSED by omission.

        Several of these dimensions have NO field anywhere in
        ble_rffi_studio's real capture/example schema today (verified
        directly against contracts/capture.py and contracts/example.py, not
        assumed): day identity, pre/post, intervention arm, content
        variant, and independent holdout groups. For those, this check
        always reports BLOCKED with an explicit NOT_DOCUMENTED finding --
        this is the expected, correct outcome against every real dataset in
        this repository today (see docs/ble/SCIENTIFIC_STATUS.md), not a
        bug: no capture campaign here has ever recorded a randomized
        intervention or content-variant design.
        """
        findings: list[str] = []
        checked = [
            "population", "days", "sessions", "pre_post", "reset_control", "channels",
            "content_variants", "independent_blocks", "groups_and_holdouts", "receiver_profile", "negative_controls",
        ]

        # Population.
        if not dataset.physical_units:
            findings.append("population: dataset declares 0 physical_units.")
        if contract.device_population:
            zero_populations = [name for name, declared in contract.device_population.items() if declared and population.population_counts.get(name, 0) == 0]
            if zero_populations:
                findings.append(f"population: protocol declares non-empty population(s) with 0 observed examples: {sorted(zero_populations)}.")

        # Days: NOT_DOCUMENTED -- no day_id field anywhere in ble_rffi_studio.
        findings.append("days: NOT_DOCUMENTED -- no day_id field exists anywhere in ble_rffi_studio's real capture/example schema; day-level independence cannot be verified from current artifacts.")

        # Sessions: real, checkable field (dataset.sessions).
        required_sessions = (contract.minimum_independent_blocks or {}).get("sessions")
        if required_sessions is not None and len(dataset.sessions) < required_sessions:
            findings.append(f"sessions: minimum_independent_blocks.sessions={required_sessions} declared, dataset has only {len(dataset.sessions)}.")
        elif not dataset.sessions:
            findings.append("sessions: dataset has 0 sessions.")

        # Pre/post and reset/control: NOT_DOCUMENTED -- no pre_or_post /
        # intervention_arm field anywhere.
        findings.append("pre_post: NOT_DOCUMENTED -- no pre_or_post field exists anywhere in ble_rffi_studio's real capture schema; pre/post pairing cannot be verified from current artifacts.")
        findings.append("reset_control: NOT_DOCUMENTED -- no intervention_arm field exists anywhere in ble_rffi_studio's real capture schema; reset/control balance cannot be verified from current artifacts.")

        # Channels: real, checkable field.
        declared_channels = set(contract.channels or [])
        if declared_channels:
            observed_channels = {example.channel for example in examples}
            missing = declared_channels - observed_channels
            if missing:
                findings.append(f"channels: protocol requires {sorted(declared_channels)}, but {sorted(missing)} have 0 observed examples.")
        else:
            findings.append("channels: protocol declares no channels for this paper campaign.")

        # Content variants: NOT_DOCUMENTED -- packet_condition field exists
        # (contracts/capture.py) but is never populated on any real capture.
        findings.append("content_variants: NOT_DOCUMENTED -- packet_condition field exists in ble_rffi_studio's real capture schema but is never populated on any real capture; content-variant coverage cannot be verified from current artifacts.")

        # Independent blocks: real, checkable (reuses the same session check
        # as above plus an explicit non-empty requirement).
        if not contract.minimum_independent_blocks:
            findings.append("independent_blocks: protocol declares no minimum_independent_blocks for this paper campaign.")

        # Groups / holdouts: now checkable for real once freeze_holdout_groups()
        # has actually been called for this dataset (Fase 1 closure item 10).
        groups_present = {a.group for a in holdout_groups}
        required_groups = {"TRAIN", "VALIDATION", "FUTURE_TEST"}
        missing_groups = required_groups - groups_present
        if missing_groups:
            findings.append(f"groups_and_holdouts: no real HoldoutGroupAssignment exists yet for group(s) {sorted(missing_groups)} on this dataset -- call freeze_holdout_groups() before this can pass.")

        # Receiver profile: real, checkable field.
        receiver_ids = set()
        for capture_id in dataset.captures:
            capture = self._load_capture(capture_id)
            if capture is not None:
                receiver_ids.add(capture.receiver_device_id)
        if len(receiver_ids) > 1:
            findings.append(f"receiver_profile: receiver_profile_hash={contract.receiver_profile_hash!r} is a single declared profile, but captures span {len(receiver_ids)} distinct receiver_device_id values: {sorted(receiver_ids)}.")
        elif not receiver_ids:
            findings.append("receiver_profile: no captures with a resolvable receiver_device_id were found.")

        # Negative controls: real, checkable field.
        if population.population_counts.get("target_absent_control", 0) == 0 and population.population_counts.get("ambient_ble", 0) == 0:
            findings.append("negative_controls: 0 target_absent_control and 0 ambient_ble examples observed in this dataset.")

        status = "BLOCKED" if findings else "PASSED"
        return PaperCampaignCompletenessResult(status=status, findings=findings, checked_requirements=checked)
