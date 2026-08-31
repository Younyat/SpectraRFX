"""Ties every Fase 0-5 service together behind persistent storage so stateless
HTTP requests can drive the pipeline. The stage/service classes themselves
stay pure (as already unit-tested) -- this repository owns ONLY the
disk-persistence and cross-stage lookups the API layer needs.
"""
from __future__ import annotations

import dataclasses
import hashlib
import shutil
import uuid
from pathlib import Path
from typing import Any, Callable

import joblib
import numpy as np
import torch

from app.infrastructure.ble.capture.ble_offline_replay import BleOfflineReplayService, read_json, read_jsonl, sha256_file, utc_now, write_json, write_jsonl
from app.infrastructure.ble.packet_analysis.ble_capture_locator import BleCaptureLocator

from ..acquisition.capture_stage import CaptureStage
from ..acquisition.receiver_epoch_assignment import ReceiverEpochInput, assign_receiver_epochs, derive_effective_receiver_session_id
from ..campaign.paper_campaign_runner import PaperCampaignRunner
from ..contracts import (
    BackgroundKind,
    CapturePurpose,
    CaptureRecord,
    DatasetManifest,
    DatasetQualityReport,
    DatasetRole,
    ExampleAnnotation,
    ExampleRecord,
    LabelEvidenceItem,
    ModelBundleManifest,
    PhysicalUnitRecord,
    SplitManifest,
    TargetPresenceStatus,
    TargetState,
    TrainingRun,
)
from ..evaluation import Evaluator
from ..evidence.evidence_stage import EvidenceStage
from ..export import BundleBuilder
from ..dataset import DatasetBuilder
from ..demo import SyntheticDemoSeeder
from ..inference import OfflineInferenceService
from ..preprocessing import resolve_preprocessing_profile
from ..quality import DatasetAnalyzer, SplitBuilder, TASK_DISPLAY_NAMES, explain_feasibility, repair_guidance, train_label_for
from ..registry import PhysicalDeviceRegistry
from ..scrubbing import derive_scrubbed_capture, load_iq, scrub_device_windows
from ..training import TrainingArtifacts, TrainingService, cnn_feasibility, model_file_size_bytes, score_model

# Candidate model types tried by the "prepare dataset and train" auto
# orchestration, in the order the guided UI reports progress for them.
_QUICK_PILOT_MODEL_TYPES = ("logistic_regression", "svm_rbf", "random_forest")
# frozen_morphological_baseline (RQ2's 4th branch) is in the "normal" profile
# only -- quick_pilot exists for fast iteration over the 3 classical models,
# not for exercising the full model-comparison scope.
_NORMAL_MODEL_TYPES = ("logistic_regression", "svm_rbf", "random_forest", "cnn1d", "cnn2d", "frozen_morphological_baseline")

_TORCH_MODEL_TYPES = {"cnn1d", "cnn2d"}

# Fixed seed set correction (2026-08-08): a real, explicit, frozen SET (not
# one arbitrary hardcoded 42) for the paper's optimization-variability
# analysis -- how much a candidate's VALIDATION performance moves across
# independent training runs of the SAME configuration. FROZEN_TRAINING_SEEDS[0]
# is still what every normal training run (prepare_and_train,
# scrub_device_from_background) uses -- unchanged behavior, now a named
# constant instead of a bare literal. The remaining seeds exist only for
# train_seed_variability_analysis (VALIDATION-only, see that method) --
# never used to pick or evaluate the recommended candidate itself. This set
# must never be edited after any real campaign has used it (same
# immutability invariant as base_preprocessing_registry.py's profile_ids) --
# a different set is a new, separately-named constant.
FROZEN_TRAINING_SEEDS: tuple[int, ...] = (42, 137, 2024)

# Caps how much of a device list ends up inside a training_run_id/bundle_id
# (both become real directory names on disk). Joining every device name
# unabbreviated (e.g. 5 devices with names like "keyfobdemo 01") produced a
# path that exceeded Windows' ~260-char MAX_PATH once nested under
# training_runs/<id>/..., failing every single candidate with a bare
# FileNotFoundError/WinError 206 that looked like "training didn't really
# run" (it didn't -- this is why). Falls back to a short, still-unique
# "<n>DEVICES-<hash>" form rather than silently truncating to something
# ambiguous; the full device list always remains recoverable from the
# dataset's own physical_units field, never only from this slug.
_DEVICE_SLUG_MAX_LEN = 40


def _device_slug(physical_units: list[str]) -> str:
    joined = "+".join(physical_units) if physical_units else "GENERAL"
    if len(joined) <= _DEVICE_SLUG_MAX_LEN:
        return joined
    digest = hashlib.sha1(joined.encode("utf-8")).hexdigest()[:8]
    return f"{len(physical_units)}DEVICES-{digest}"

# Minimum VALIDATION-only bar a candidate must clear to be selectable at all.
# Deliberately conservative (better than a coin flip on macro-averaged
# per-class metrics) rather than tuned to any specific dataset; if no
# candidate clears it, prepare_and_train reports NO_MODEL_ACCEPTED instead of
# recommending the least-bad option. Operational parameter, not a universal
# scientific threshold -- revisit once real campaigns provide more evidence.
ACCEPTANCE_MIN_MACRO_F1 = 0.5
ACCEPTANCE_MIN_BALANCED_ACCURACY = 0.5

_CAPTURE_TYPE_UNCLASSIFIED = "Sin clasificar"
_CAPTURE_TYPE_DISCARDED_RF_FAILURE = "Descartada (fallo de adquisicion RF)"

# Same BLE advertising-channel mapping used throughout the capture/decode
# tools (e.g. ble_capture_job_manager.py's CHANNELS, ble_decode_burst_directory.py) --
# duplicated here rather than imported to avoid a cross-module dependency for
# three well-known, effectively-frozen constants.
_BLE_CHANNEL_FREQUENCIES_HZ = {37: 2_402_000_000, 38: 2_426_000_000, 39: 2_480_000_000}


class StudioRepository:
    def __init__(self, root: Path, legacy_capture_root: Path, legacy_session_root: Path, campaign_orchestrator: Any | None = None) -> None:
        self.root = root
        self.legacy_capture_root = legacy_capture_root
        self.legacy_session_root = legacy_session_root
        # None when ble_lab's hybrid/capture managers weren't available at
        # startup (e.g. isolated tests) -- real-campaign endpoints raise a
        # clear error rather than silently no-op in that case.
        self.campaign_orchestrator = campaign_orchestrator
        # Study Control Center, phases 04/06/07 (2026-08-11): the SAME real
        # PaperCampaignRunner mechanism serves the Qualification Pilot
        # (qualification_only=True) and the real DEVELOPMENT/VALIDATION
        # campaigns (qualification_only=False) -- they differ only in which
        # schedule is frozen, never in the underlying enforcement (reject
        # out-of-schedule/out-of-order/mismatched captures).
        self.paper_campaign_runner = PaperCampaignRunner(storage_root=root, legacy_capture_root=legacy_capture_root, campaign_orchestrator=campaign_orchestrator)

        self.registry = PhysicalDeviceRegistry(root / "registry")
        self.capture_stage = CaptureStage(legacy_capture_root)
        # Read-only: only used for quick_presence_check's native-scan-log
        # triage below, never to launch/continue an actual replay from here.
        self.offline_replay = BleOfflineReplayService(legacy_capture_root, legacy_session_root)
        self.dataset_builder = DatasetBuilder(root / "datasets")
        self.analyzer = DatasetAnalyzer()
        self.split_builder = SplitBuilder()
        self.evaluator = Evaluator()
        self.bundle_builder = BundleBuilder(root / "bundles")
        self.synthetic_demo_seeder = SyntheticDemoSeeder(self)

        self.captures_dir = root / "captures"
        self.evidence_dir = root / "evidence"
        self.quality_dir = root / "quality_reports"
        self.splits_dir = root / "splits"
        self.training_dir = root / "training_runs"
        # Inference-provenance correction (2026-08-08): one persisted
        # manifest per real offline inference run -- see run_inference.
        self.inference_dir = root / "inference_runs"
        for directory in (self.captures_dir, self.evidence_dir, self.quality_dir, self.splits_dir, self.training_dir, self.inference_dir):
            directory.mkdir(parents=True, exist_ok=True)

        # P0.3 correction (2026-08-08): lazily constructed on first real
        # TEST access -- see _freeze_and_log_test_access. `root` here is
        # storage_root/ble_rffi_studio; ble_scientific_results' own root is
        # the sibling storage_root/scientific_reports/ble (same layout
        # app/modules/ble_scientific_results/module.py itself uses).
        self._scientific_results_repository_cache: Any | None = None

    # ------------------------------------------------------------------
    # Legacy capture listing (read-only, reuses the Phase 2 locator)
    # ------------------------------------------------------------------

    def list_legacy_captures(self) -> dict[str, Any]:
        locator = BleCaptureLocator(self.legacy_capture_root, self.legacy_session_root)
        rows = locator.list_captures()
        classification = locator.classify(rows)
        for row in rows:
            row.pop("_mtime", None)
            # Exposed so "Aplicar analisis" can send each capture's OWN
            # project_id back to /replay-and-evidence-jobs instead of
            # whatever the operator currently has typed into Step 1 --
            # sessions that mix project_id spellings across captures (e.g.
            # "BLE-RFFI-TI_SENSORTAG" vs "BLE-RFFI-TI_SENSOR_TAG") were
            # silently breaking AddressBinding lookups for every packet in
            # a batch-analyzed capture, even ones with no real ambiguity.
            capture_for_project_id = self.get_capture(row["capture_id"])
            row["project_id"] = capture_for_project_id.project_id if capture_for_project_id else None
            device_label, device_source = self._device_label_for_capture(row["capture_id"])
            row["device_label"] = device_label
            row["device_source"] = device_source
            capture_type_label, capture_decision, target_presence_status = self._capture_type_and_decision(row["capture_id"])
            if row.get("acquisition_quality") == "FAILED" and capture_type_label == _CAPTURE_TYPE_UNCLASSIFIED:
                # A capture attempt that overflowed/discontinued mid-acquisition
                # (the automatic retry mechanism's real, measured ~46% single-
                # attempt failure rate -- see CampaignOrchestrator) still
                # writes a complete manifest, so it shows up here even though
                # only the retry that finally succeeded ever got a
                # CaptureRecord built for it. Left as "Sin clasificar" this
                # was indistinguishable from a real, usable capture the
                # operator just hasn't gotten to yet -- mislabeling it that
                # way is what made the list look inconsistently mixed.
                capture_type_label = _CAPTURE_TYPE_DISCARDED_RF_FAILURE
            row["capture_type_label"] = capture_type_label
            row["capture_decision"] = capture_decision
            row["target_presence_status"] = target_presence_status
            if capture_decision in ("REPETITION_NEEDED", "CONTROL_ONLY", "QUARANTINED", "QUARANTINED_AMBIGUOUS"):
                row["repair_guidance"] = self.capture_repair_guidance(row["capture_id"])
        return {"captures": rows, "classification": classification}

    def capture_repair_guidance(self, capture_id: str) -> list[dict[str, str]]:
        """'Corregir y repetir': concrete, named causes for why this capture
        did not reach an ELIGIBLE_AS_* verdict, computed from the same
        CaptureRecord/ExampleRecord facts _capture_decision already reads.
        Empty (never an error) for a capture with no CaptureRecord/evidence
        yet -- there is nothing to diagnose before analysis has even run."""
        capture = self.get_capture(capture_id)
        if capture is None or not self.has_evidence(capture_id):
            return []
        decision_code, target_presence_status = self._capture_decision(capture)
        return repair_guidance(capture, self.list_examples(capture_id), target_presence_status, decision_code)

    def quick_presence_check(self, capture_id: str) -> dict[str, Any]:
        """Fast (no IQ decode) triage for a capture BEFORE spending minutes on
        "Aplicar analisis": was the target physically seen by the native
        Windows BLE scan at all during this capture's RF window? Only
        meaningful for TARGET_DEVICE_ON without isolation declared (isolation
        bypasses native correlation entirely -- see EvidenceStage; other
        capture_purpose values have no positive target to look for).

        target_observed=False here is a reliable early REPETITION_NEEDED
        signal -- no decode can recover a native corroboration that never
        happened. target_observed=True is NOT a guarantee of
        ELIGIBLE_AS_POSITIVE (MULTIPLE_NATIVE_CALLBACKS ambiguity is only
        resolved by full packet-level association, still done later by
        "Aplicar analisis")."""
        capture = self.get_capture(capture_id)
        if capture is None:
            return {"applicable": False, "reason": "CAPTURE_NOT_BUILT_YET"}
        if capture.capture_purpose != "TARGET_DEVICE_ON":
            return {"applicable": False, "reason": "NOT_A_TARGET_DEVICE_ON_CAPTURE"}
        if capture.isolation_declared_physical_unit_id:
            return {"applicable": False, "reason": "ISOLATION_DECLARED_NATIVE_CORRELATION_BYPASSED"}
        target_unit_id = capture.target_reference_id
        if not target_unit_id:
            return {"applicable": False, "reason": "NO_TARGET_UNIT_DECLARED_ON_CAPTURE"}
        # Same resolution path EvidenceStage itself uses (registry bindings),
        # never the hybrid session's own target_address -- ble_rffi_studio's
        # campaign orchestrator always launches the native scan in
        # any_device/exploratory mode, so that field is never populated here.
        bound_addresses = [
            binding.address for binding in self.registry.list_bindings()
            if binding.project_id == capture.project_id and binding.bound_physical_unit_id == target_unit_id and binding.binding_status == "BOUND"
        ]
        if not bound_addresses:
            return {"applicable": False, "reason": "NO_BOUND_ADDRESS_REGISTERED_YET_FOR_TARGET_UNIT"}
        try:
            result = self.offline_replay.quick_native_presence_check(capture_id, capture.execution_id, target_addresses=bound_addresses)
        except FileNotFoundError:
            return {"applicable": False, "reason": "CAPTURE_DIRECTORY_NOT_FOUND"}
        if result.get("applicable") and not result["target_observed"]:
            result["human_summary"] = (
                "Tu dispositivo NO fue visto por el escaneo Bluetooth nativo durante esta captura -- "
                "muy probablemente terminara en REPETICION NECESARIA. Puedes repetir la captura ahora "
                "en vez de esperar el analisis completo."
            )
        elif result.get("applicable"):
            result["human_summary"] = (
                f"Tu dispositivo SI fue visto {result['target_observation_count']} vez/veces por el escaneo "
                "nativo durante la captura. Esto no garantiza que sea aceptada (aun puede haber ambiguedad "
                "de correlacion), pero es una buena senal."
            )
        return result

    def delete_legacy_capture(self, capture_id: str) -> dict[str, Any]:
        """Deletes a raw B200 capture -- a real, irreversible removal of
        potentially hundreds of MB of IQ (mainly meant for the RF-overflow
        retry artifacts CampaignOrchestrator's retry loop leaves behind,
        never cleaned up automatically since only the successful attempt
        ever gets used). Also removes this module's own CaptureRecord/
        evidence for it, if any were built, so nothing dangling references a
        capture_id that no longer exists on disk.
        """
        # capture_id becomes a directory name below -- reject anything that
        # could escape legacy_capture_root (path traversal) before touching
        # the filesystem at all.
        if not capture_id or any(part in capture_id for part in ("/", "\\", "..")):
            raise ValueError(f"INVALID_CAPTURE_ID:{capture_id}")
        capture_dir = self.legacy_capture_root / capture_id
        if capture_dir.resolve().parent != self.legacy_capture_root.resolve() or not capture_dir.is_dir():
            raise FileNotFoundError(f"LEGACY_CAPTURE_NOT_FOUND:{capture_id}")

        shutil.rmtree(capture_dir)

        capture_json = self.captures_dir / f"{capture_id}.json"
        if capture_json.is_file():
            capture_json.unlink()
        evidence_dir = self.evidence_dir / capture_id
        if evidence_dir.is_dir():
            shutil.rmtree(evidence_dir)

        return {"deleted": True, "capture_id": capture_id}

    def _device_label_for_capture(self, capture_id: str) -> tuple[str, str]:
        """One glance answer to "whose recording is this" for the capture
        picker -- never leave an operator guessing between a real device's
        session and a pure-noise/no-match one from an opaque capture_id.

        Real gap found and fixed here: "Solo capturar ahora" is specifically
        meant to batch-capture several devices quickly, applying analysis to
        each one later -- but until this fix, EVERY not-yet-analyzed capture
        showed the exact same generic "Sin analizar aun" label regardless of
        which unit the operator selected in Step 2, so after capturing 3-4
        devices back to back there was no way to tell them apart again until
        every single one had been analyzed. capture.target_reference_id is
        already recorded at capture time (the operator's own Step 2
        selection) independent of isolation -- surfacing it now, clearly
        marked as DECLARED, never confused with a CONFIRMED post-analysis
        match."""
        capture = self.get_capture(capture_id)
        if capture and capture.isolation_declared_physical_unit_id:
            return f"{capture.isolation_declared_physical_unit_id} (aislamiento fisico declarado)", "ISOLATION_DECLARED"
        if not self.has_evidence(capture_id):
            if capture and capture.target_reference_id:
                return f"{capture.target_reference_id} (declarado, sin confirmar aun)", "DECLARED_NOT_CONFIRMED"
            return "Sin analizar aun (construye evidencia para identificarla)", "NOT_ANALYZED"
        unit_ids = {example.physical_unit_id for example in self.list_examples(capture_id) if example.physical_unit_id}
        if len(unit_ids) == 1:
            return f"{unit_ids.pop()} (direccion confirmada)", "ADDRESS_MATCH"
        if len(unit_ids) > 1:
            return f"Multiples dispositivos: {', '.join(sorted(unit_ids))}", "MULTIPLE_ADDRESS_MATCHES"
        return "Entorno / ruido ambiental (ningun dispositivo registrado coincidio)", "ENVIRONMENT_NO_MATCH"

    def _capture_type_and_decision(self, capture_id: str) -> tuple[str, str, str]:
        """Human-facing "Tipo de captura" + eligibility verdict + target
        presence status for the Guided UI's captures list -- separate from
        _device_label_for_capture, which answers WHICH device, not what the
        operator meant to capture or whether the evidence actually backs
        that intent up."""
        capture = self.get_capture(capture_id)
        if capture is None:
            return _CAPTURE_TYPE_UNCLASSIFIED, "NOT_ANALYZED_YET", "NOT_APPLICABLE"
        if capture.data_origin == "SYNTHETIC_TEST_ONLY":
            return ("Sintetica de pruebas", *self._capture_decision(capture))
        if capture.capture_purpose == "TARGET_DEVICE_ON":
            return ("Dispositivo encendido", *self._capture_decision(capture))
        if capture.capture_purpose == "BACKGROUND_TARGET_OFF":
            return ("Entorno -- dispositivo apagado", *self._capture_decision(capture))
        if capture.capture_purpose == "BACKGROUND_GENERAL":
            return ("Entorno general", *self._capture_decision(capture))
        if capture.capture_purpose == "UNKNOWN_DEVICE_COLLECTION":
            return ("Recoleccion de dispositivos desconocidos", *self._capture_decision(capture))
        return (_CAPTURE_TYPE_UNCLASSIFIED, *self._capture_decision(capture))

    def _capture_decision(self, capture: CaptureRecord) -> tuple[str, str]:
        """(decision_code, target_presence_status), computed fresh from the
        examples Evidence Stage produced, never stored/duplicated on the
        capture itself (examples are the source of truth, and can be
        rebuilt).

        decision_code is one of: ELIGIBLE_AS_POSITIVE / ELIGIBLE_AS_BACKGROUND
        / ELIGIBLE_AS_UNKNOWN / CONTROL_ONLY / REPETITION_NEEDED /
        QUARANTINED / QUARANTINED_AMBIGUOUS / NOT_ANALYZED_YET.

        QUARANTINED and QUARANTINED_AMBIGUOUS are deliberately two different
        codes, not one, even though both mean "some of this capture's
        evidence could not be trusted": QUARANTINED is reserved for the one
        specific, real declared-purpose CONTRADICTION this module can prove
        (a BACKGROUND_TARGET_OFF capture whose declared-off target was
        actually detected with strong evidence -- see
        _has_background_contradiction). QUARANTINED_AMBIGUOUS is everything
        else that lands an example in the same CONFLICT/QUARANTINED bucket
        at the evidence layer -- overwhelmingly MULTIPLE_NATIVE_CALLBACKS:
        more than one native Windows BLE observation fell inside the same
        B200-packet association time window (a busy RF environment with
        several BLE devices advertising close together in time), which has
        NOTHING to do with what the operator declared. Calling that a
        "contradiction" was a real, observed source of operator confusion --
        the operator did not declare anything false; the system just
        couldn't disambiguate two near-simultaneous native observations.
        QUARANTINED_AMBIGUOUS is NOT fixed by reapplying analysis on the
        same capture (the native scan log and B200 packets are already
        fixed, recorded facts -- the ambiguity is deterministic, not a
        decode flake); it needs either a real repeat capture in a less
        crowded RF environment, or physical isolation
        (isolation_declared_physical_unit_id) declared for TARGET_DEVICE_ON,
        which bypasses Windows-correlation entirely (see EvidenceStage).

        The critical rule this encodes (the actual root cause of the
        original bug this section fixes): the SAME raw fact -- "no eligible
        positive match in this capture's evidence" -- means opposite things
        depending on capture_purpose. For TARGET_DEVICE_ON it means the
        capture failed its purpose (REPETITION_NEEDED). For
        BACKGROUND_TARGET_OFF/BACKGROUND_GENERAL it is the EXPECTED, correct
        outcome -- never penalized, never quarantined for that reason alone.

        Evidence Stage never itself promotes an example all the way to
        dataset_eligibility=ELIGIBLE (that's the Fase 2 Dataset
        Builder/Analyzer gate's call, made per-dataset, not per-capture) --
        so "eligible so far" here means the same includable set
        DatasetBuilder.select_examples() itself uses: quality PASSED and
        dataset_eligibility in {PENDING_ANALYSIS, ELIGIBLE}, i.e. not already
        excluded outright.
        """
        if not self.has_evidence(capture.capture_id):
            return "NOT_ANALYZED_YET", "NOT_APPLICABLE"
        examples = self.list_examples(capture.capture_id)
        eligible = [
            example for example in examples
            if example.quality_status == "PASSED" and example.dataset_eligibility in ("PENDING_ANALYSIS", "ELIGIBLE")
        ]
        quarantined_or_conflict = [
            example for example in examples
            if example.dataset_eligibility == "QUARANTINED" or example.association_status == "CONFLICT"
        ]
        has_positive_match = any(example.physical_unit_id for example in eligible)
        has_any_eligible = bool(eligible)

        if capture.capture_purpose == "TARGET_DEVICE_ON":
            if has_positive_match:
                return "ELIGIBLE_AS_POSITIVE", "DETECTED"
            if quarantined_or_conflict:
                # Never "contradiction" here -- TARGET_DEVICE_ON has no
                # declared-absence claim to contradict at all. This is
                # generic native-correlation ambiguity (see docstring).
                return "QUARANTINED_AMBIGUOUS", "INCONCLUSIVE"
            # The target simply never appeared -- a real, actionable problem
            # for THIS purpose (never silently reinterpreted as a background
            # capture just because no positive match was found).
            return "REPETITION_NEEDED", "NOT_DETECTED"

        if capture.capture_purpose in ("BACKGROUND_TARGET_OFF", "BACKGROUND_GENERAL"):
            not_applicable_or_not_detected = "NOT_APPLICABLE" if capture.capture_purpose == "BACKGROUND_GENERAL" else "NOT_DETECTED"
            if self._has_background_contradiction(capture):
                # The declared-off target actually showed up with strong
                # evidence -- this specific claim ("the target was off") is
                # broken, so the whole capture's provenance is untrustworthy
                # even if other, genuinely unrelated background traffic also
                # exists in the same recording. Never papered over just
                # because there is other good data alongside it.
                return "QUARANTINED", "DETECTED"
            if has_any_eligible:
                # The target's absence is the EXPECTED result here, and real
                # BLE fragments were recovered -- genuine negative evidence.
                # Ordinary association ambiguity elsewhere (unrelated to the
                # target-off claim, e.g. MULTIPLE_NATIVE_CALLBACKS) does not
                # override this.
                return "ELIGIBLE_AS_BACKGROUND", not_applicable_or_not_detected
            if quarantined_or_conflict:
                # Nothing usable recovered, and what little there is is
                # ambiguous -- provenance cannot be determined either way.
                # Still not the specific declared-off contradiction (that
                # was already ruled out above), so not "QUARANTINED" either.
                return "QUARANTINED_AMBIGUOUS", "INCONCLUSIVE"
            # Technically clean capture (no contradiction, no ambiguity),
            # just not enough ambient BLE traffic recovered to be useful on
            # its own -- never REPETITION_NEEDED/QUARANTINED for the
            # target's ordinary, intended absence.
            return "CONTROL_ONLY", not_applicable_or_not_detected

        if capture.capture_purpose == "UNKNOWN_DEVICE_COLLECTION":
            if any(not example.physical_unit_id for example in eligible):
                return "ELIGIBLE_AS_UNKNOWN", "NOT_APPLICABLE"
            if quarantined_or_conflict:
                return "QUARANTINED_AMBIGUOUS", "NOT_APPLICABLE"
            return "CONTROL_ONLY", "NOT_APPLICABLE"

        # Legacy/unclassified capture (predates capture_purpose) -- best
        # generic verdict from the evidence alone, never a fabricated intent.
        if has_positive_match:
            return "ELIGIBLE_AS_POSITIVE", "NOT_APPLICABLE"
        if has_any_eligible:
            return "ELIGIBLE_AS_BACKGROUND", "NOT_APPLICABLE"
        return ("QUARANTINED_AMBIGUOUS" if quarantined_or_conflict else "CONTROL_ONLY"), "NOT_APPLICABLE"

    def _has_background_contradiction(self, capture: CaptureRecord) -> bool:
        """True only for the specific "declared-off target actually detected"
        contradiction EvidenceStage._build_annotation flags -- never for
        ordinary association ambiguity (MULTIPLE_NATIVE_CALLBACKS) unrelated
        to the target-off claim. Only possible when a specific unit was
        actually named (target_reference_id set); BACKGROUND_GENERAL never
        has one, so this is always False for it. association_status alone
        cannot distinguish the two (EvidenceStage deliberately puts both in
        the same CONFLICT bucket), so this reads the annotation's own
        decision_reason text, which the background-contradiction override
        always mentions explicitly (see EvidenceStage._build_annotation)."""
        if capture.capture_purpose != "BACKGROUND_TARGET_OFF" or not capture.target_reference_id:
            return False
        return any(
            "contradiction" in annotation.label_decision.decision_reason.lower()
            for annotation in self.list_annotations(capture.capture_id)
        )

    # ------------------------------------------------------------------
    # Physical Device Registry
    # ------------------------------------------------------------------

    def register_physical_unit(self, *, physical_unit_id: str, project_id: str, device_family: str, operator_declaration_id: str, manufacturer: str | None = None, model: str | None = None) -> PhysicalUnitRecord:
        return self.registry.register_physical_unit(
            physical_unit_id=physical_unit_id, project_id=project_id, device_family=device_family,
            manufacturer=manufacturer, model=model, operator_declaration_id=operator_declaration_id, first_registered_at=utc_now(),
        )

    def list_physical_units(self) -> list[PhysicalUnitRecord]:
        return self.registry.list_physical_units()

    # Study Control Center, phase 02 (2026-08-11): thin wrappers, same
    # convention as register_physical_unit/list_physical_units above --
    # confirm_same_model()/set_rq4_eligibility() already existed on
    # PhysicalDeviceRegistry (with real, required basis/reason validation)
    # but had no route until now.
    def confirm_same_model(self, physical_unit_id: str, *, basis: str) -> PhysicalUnitRecord:
        return self.registry.confirm_same_model(physical_unit_id, basis=basis)

    def set_rq4_eligibility(self, physical_unit_id: str, *, eligible: bool, reason: str) -> PhysicalUnitRecord:
        return self.registry.set_rq4_eligibility(physical_unit_id, eligible=eligible, reason=reason)

    # ------------------------------------------------------------------
    # Auto-train: turns "which captures for which device" (the manual
    # bookkeeping an operator otherwise has to do by hand before every
    # prepare-and-train call) into a single per-device readiness check +
    # capture_ids resolution, so the frontend can offer "Entrenar" as one
    # click per registered device instead of requiring capture_id lists.
    # ------------------------------------------------------------------

    def _auto_train_capture_pools(self, project_id: str, physical_unit_id: str) -> tuple[list[CaptureRecord], list[CaptureRecord]]:
        captures = self.list_captures()
        target_captures = [
            c for c in captures
            if c.project_id == project_id and c.capture_purpose == "TARGET_DEVICE_ON"
            and (c.target_reference_id == physical_unit_id or c.isolation_declared_physical_unit_id == physical_unit_id)
        ]
        # BACKGROUND_TARGET_OFF/BACKGROUND_GENERAL captures are never
        # device-specific (see split_builder.py's TARGET_VS_BACKGROUND
        # docstring) -- any capture with no target bound, declared under
        # either purpose, is valid negative evidence for EVERY device in the
        # same project, not just the one it happened to be recorded for.
        background_captures = [
            c for c in captures
            if c.project_id == project_id and c.capture_purpose in ("BACKGROUND_TARGET_OFF", "BACKGROUND_GENERAL")
        ]
        return target_captures, background_captures

    def auto_train_candidates(self) -> list[dict[str, Any]]:
        """Per registered physical unit: how many of its own target sessions
        and how many project-shared background sessions are available -- the
        exact two counts TARGET_VS_BACKGROUND's feasibility gate requires
        (>=3 independent sessions each). `ready=True` means auto_train() can
        be called right now without a NOT_FEASIBLE result."""
        results = []
        for unit in self.list_physical_units():
            target_captures, background_captures = self._auto_train_capture_pools(unit.project_id, unit.physical_unit_id)
            target_sessions = len({c.session_id for c in target_captures})
            background_sessions = len({c.session_id for c in background_captures})
            results.append({
                "physical_unit_id": unit.physical_unit_id, "project_id": unit.project_id,
                "target_captures": len(target_captures), "target_sessions": target_sessions,
                "background_captures": len(background_captures), "background_sessions": background_sessions,
                "ready": target_sessions >= 3 and background_sessions >= 3,
            })
        return results

    def resolve_auto_train_capture_ids(self, physical_unit_id: str) -> dict[str, Any]:
        unit = next((u for u in self.list_physical_units() if u.physical_unit_id == physical_unit_id), None)
        if unit is None:
            raise FileNotFoundError(f"PHYSICAL_UNIT_NOT_FOUND:{physical_unit_id}")
        target_captures, background_captures = self._auto_train_capture_pools(unit.project_id, physical_unit_id)
        return {
            "project_id": unit.project_id,
            "capture_ids": [c.capture_id for c in target_captures] + [c.capture_id for c in background_captures],
        }

    def declare_binding(self, *, project_id: str, address: str, address_type: str, physical_unit_id: str, reason: str, decision_artifact_id: str):
        evidence = LabelEvidenceItem(source_type="OPERATOR_DECLARATION", artifact_id=decision_artifact_id, timestamp=utc_now(), strength="DOCUMENTARY", description=reason)
        return self.registry.declare_binding(project_id=project_id, address=address, address_type=address_type, physical_unit_id=physical_unit_id, evidence=evidence, decided_at=utc_now(), reason=reason)

    def list_bindings(self) -> list[Any]:
        return self.registry.list_bindings()

    # ------------------------------------------------------------------
    # Synthetic demo (no SDR hardware required)
    # ------------------------------------------------------------------

    def seed_synthetic_demo(self) -> dict[str, Any]:
        return self.synthetic_demo_seeder.seed()

    # ------------------------------------------------------------------
    # Capture Stage
    # ------------------------------------------------------------------

    def build_capture(
        self, *, capture_id: str, project_id: str, campaign_id: str, execution_id: str | None = None,
        session_id: str | None = None, isolation_declared_physical_unit_id: str | None = None,
        capture_purpose: CapturePurpose | None = None, target_state: TargetState | None = None,
        background_kind: BackgroundKind | None = None,
        target_reference_id: str | None = None, dataset_role: DatasetRole | None = None,
    ) -> CaptureRecord:
        capture = self.capture_stage.build_capture_record(
            capture_id=capture_id, project_id=project_id, campaign_id=campaign_id, execution_id=execution_id,
            session_id=session_id, isolation_declared_physical_unit_id=isolation_declared_physical_unit_id,
            capture_purpose=capture_purpose, target_state=target_state, background_kind=background_kind,
            target_reference_id=target_reference_id, dataset_role=dataset_role,
        )
        capture = self._assign_receiver_epoch_if_needed(capture)
        write_json(self.captures_dir / f"{capture_id}.json", capture.model_dump(mode="json"))
        return capture

    def _assign_receiver_epoch_if_needed(self, capture: CaptureRecord) -> CaptureRecord:
        """Point-1 correction (2026-08-08): receiver_epoch requires
        sequential knowledge across every OTHER real capture of the same
        receiver_identity_id -- capture_stage.py's single-manifest builder
        cannot see that, so this repository-level step runs the same
        assign_receiver_epochs() the historical migration uses, over every
        already-persisted capture of this identity plus the new one. A
        capture whose manifest already declared receiver_epoch explicitly
        is left untouched (capture_stage.py already set
        receiver_epoch_boundary_reason=MANIFEST_DECLARED for it).

        Point-1 correction (2026-08-10): regardless of which branch resolves
        receiver_epoch, this method ALWAYS derives the EFFECTIVE
        receiver_session_id from it afterward (derive_effective_receiver_
        session_id) -- the runtime/capture path, never the bare schedule
        label, is what RQ3 pairing actually trusts. See contracts/capture.py
        for the full rationale."""
        if capture.receiver_epoch is not None or capture.receiver_identity_id is None:
            return capture.model_copy(update={
                "receiver_session_id": derive_effective_receiver_session_id(capture.receiver_session_id_declared, capture.receiver_epoch),
            })
        siblings = [c for c in self.list_captures() if c.receiver_identity_id == capture.receiver_identity_id]
        inputs = [
            ReceiverEpochInput(
                capture_id=c.capture_id, receiver_identity_id=c.receiver_identity_id,
                qualified_acquisition_profile_hash=c.qualified_acquisition_profile_hash,
                acquisition_started_at=c.created_at,
                # Only a GENUINELY manifest-declared sibling epoch is passed
                # through as an override -- an already-persisted but
                # auto-assigned epoch (boundary_reason != MANIFEST_DECLARED)
                # must be re-derived here like any other capture, or
                # assign_receiver_epochs' sequential epoch_index desyncs
                # (a real bug found and fixed while testing this: passing
                # every sibling's already-assigned epoch as "declared" made
                # the function skip incrementing its own running index for
                # them, so the NEXT real boundary collided with the
                # previous epoch's id instead of getting a new one).
                declared_receiver_epoch=(c.receiver_epoch if c.receiver_epoch_boundary_reason == "MANIFEST_DECLARED" else None),
            )
            for c in siblings
        ]
        inputs.append(ReceiverEpochInput(
            capture_id=capture.capture_id, receiver_identity_id=capture.receiver_identity_id,
            qualified_acquisition_profile_hash=capture.qualified_acquisition_profile_hash,
            acquisition_started_at=capture.created_at, declared_receiver_epoch=None,
        ))
        assignment = next(a for a in assign_receiver_epochs(inputs) if a.capture_id == capture.capture_id)
        return capture.model_copy(update={
            "receiver_epoch": assignment.receiver_epoch, "receiver_epoch_boundary_reason": assignment.receiver_epoch_boundary_reason,
            "receiver_session_id": derive_effective_receiver_session_id(capture.receiver_session_id_declared, assignment.receiver_epoch),
        })

    def list_captures(self) -> list[CaptureRecord]:
        return [CaptureRecord.model_validate(read_json(p)) for p in sorted(self.captures_dir.glob("*.json"))]

    def get_capture(self, capture_id: str) -> CaptureRecord | None:
        path = self.captures_dir / f"{capture_id}.json"
        return CaptureRecord.model_validate(read_json(path)) if path.is_file() else None

    def resolve_iq_path(self, capture: CaptureRecord) -> Path:
        return self.legacy_capture_root / capture.capture_id / capture.iq_path

    # ------------------------------------------------------------------
    # Real capture campaign (B200 + native scan, wrapping the existing
    # BleHybridCampaignManager mechanism -- see campaign_orchestrator.py)
    # ------------------------------------------------------------------

    def run_campaign_session(self, *, progress=None, capture_only: bool = False, **kwargs: Any) -> dict[str, Any]:
        if self.campaign_orchestrator is None:
            raise RuntimeError(
                "REAL_CAMPAIGN_NOT_AVAILABLE: ble_lab's capture/hybrid managers were not available when this "
                "module started (BLE_IQ_CAPTURE_EXPERIMENTAL_ENABLED or hardware probing may be disabled)."
            )
        # capture_only=True stops right after the real B200 acquisition
        # (CaptureRecord built, B200 arbiter lease released) -- OFFLINE_REPLAY
        # and Evidence Stage are the slow part and can be applied later, for
        # any number of captures, via run_replay_and_evidence(). Lets an
        # operator capture several devices in a hurry without waiting on
        # decode between each one.
        if capture_only:
            return self.campaign_orchestrator.run_capture_only(progress=progress, **kwargs)
        return self.campaign_orchestrator.run_session(progress=progress, **kwargs)

    def run_guided_capture(self, *, progress=None, **kwargs: Any) -> dict[str, Any]:
        if self.campaign_orchestrator is None:
            raise RuntimeError(
                "REAL_CAMPAIGN_NOT_AVAILABLE: ble_lab's capture/hybrid managers were not available when this "
                "module started (BLE_IQ_CAPTURE_EXPERIMENTAL_ENABLED or hardware probing may be disabled)."
            )
        return self.campaign_orchestrator.run_guided_capture_only(progress=progress, **kwargs)

    def run_replay_and_evidence(self, *, capture_id: str, project_id: str, ble_channel: int, force: bool = False, progress=None) -> dict[str, Any]:
        if self.campaign_orchestrator is None:
            raise RuntimeError(
                "REAL_CAMPAIGN_NOT_AVAILABLE: ble_lab's capture/hybrid managers were not available when this "
                "module started (BLE_IQ_CAPTURE_EXPERIMENTAL_ENABLED or hardware probing may be disabled)."
            )
        # Idempotent by default: a capture that already has evidence (from an
        # earlier run_session/run_replay_and_evidence call) is never silently
        # re-decoded just because the operator clicked "aplicar analisis"
        # again -- that would burn minutes of real decode time for no new
        # information. force=True is the explicit, deliberate opt-in to redo
        # it anyway (e.g. after fixing an AddressBinding).
        if not force and self.has_evidence(capture_id):
            return {"skipped": True, "reason": "ALREADY_HAS_EVIDENCE", "capture_id": capture_id}
        result = self.campaign_orchestrator.run_replay_and_evidence_for_capture(
            capture_id=capture_id, project_id=project_id, ble_channel=ble_channel, progress=progress,
        )
        return {"skipped": False, **result}

    # ------------------------------------------------------------------
    # Paper campaign schedule (Study Control Center, phases 04/06/07,
    # 2026-08-11) -- thin wrappers over PaperCampaignRunner (see
    # campaign/paper_campaign_runner.py, previously only invoked as a
    # script/library, never through a route).
    # ------------------------------------------------------------------

    def freeze_campaign_schedule(self, *, schedule_id: str, protocol_id: str, entries: list[dict], qualification_only: bool = False, receiver_session_id: str | None = None):
        return self.paper_campaign_runner.freeze_schedule(
            schedule_id=schedule_id, protocol_id=protocol_id, entries=entries,
            qualification_only=qualification_only, receiver_session_id=receiver_session_id,
        )

    def get_campaign_schedule(self, schedule_id: str, version: int | None = None):
        return self.paper_campaign_runner.load_schedule(schedule_id, version)

    def list_campaign_schedule_rejections(self, schedule_id: str) -> list[dict[str, Any]]:
        return self.paper_campaign_runner.list_rejections(schedule_id)

    def _rebuild_capture_record_with_schedule_metadata(self, capture_id: str) -> CaptureRecord:
        """PaperCampaignRunner.execute() calls this AFTER writing the
        schedule's declared day_id/pre_or_post/intervention_arm/etc onto
        capture_manifest.json -- re-running build_capture() with the SAME
        identity fields the first (pre-schedule-metadata) build already
        established re-reads the now-updated manifest, so the CaptureRecord
        this returns carries the real schedule metadata. Never guesses a
        new identity field -- reuses exactly what the first build already
        recorded for this capture."""
        existing = self.get_capture(capture_id)
        if existing is None:
            raise FileNotFoundError(f"CAPTURE_RECORD_NOT_FOUND_BEFORE_SCHEDULE_METADATA_REBUILD:{capture_id}")
        return self.build_capture(
            capture_id=capture_id, project_id=existing.project_id, campaign_id=existing.campaign_id,
            execution_id=existing.execution_id, session_id=existing.session_id,
            isolation_declared_physical_unit_id=existing.isolation_declared_physical_unit_id,
            capture_purpose=existing.capture_purpose, target_state=existing.target_state,
            background_kind=existing.background_kind, target_reference_id=existing.target_reference_id,
            dataset_role=existing.dataset_role,
        )

    def execute_next_campaign_schedule_capture(
        self, *, schedule_id: str, duration_seconds: float, gain_db: float = 20.0,
        operator_id: str | None = None, operator_confirmed_target_absent: bool = False, progress=None,
    ) -> CaptureRecord:
        if self.campaign_orchestrator is None:
            raise RuntimeError(
                "REAL_CAMPAIGN_NOT_AVAILABLE: ble_lab's capture/hybrid managers were not available when this "
                "module started (BLE_IQ_CAPTURE_EXPERIMENTAL_ENABLED or hardware probing may be disabled)."
            )
        schedule = self.paper_campaign_runner.load_schedule(schedule_id)
        next_entry = self.paper_campaign_runner.next_planned_capture(schedule)
        if next_entry is None:
            raise ValueError(f"CAMPAIGN_SCHEDULE_FULLY_EXECUTED:{schedule_id}")
        return self.paper_campaign_runner.execute(
            schedule, next_entry.planned_capture_id, build_capture_record=self._rebuild_capture_record_with_schedule_metadata,
            operator_id=operator_id, progress=progress, duration_seconds=duration_seconds, gain_db=gain_db,
            condition_label=f"paper-campaign-{schedule_id}-{next_entry.planned_capture_id}",
            project_id=schedule.protocol_id, campaign_id=schedule_id, session_index=next_entry.capture_order,
            isolation_declared=True, operator_confirmed_target_absent=operator_confirmed_target_absent,
        )

    def campaign_device_status(self) -> dict[str, Any]:
        if self.campaign_orchestrator is None:
            raise RuntimeError("REAL_CAMPAIGN_NOT_AVAILABLE")
        device_id = self.campaign_orchestrator.resolve_device_id(None)
        return {"device_id": device_id, **self.campaign_orchestrator.arbiter.get_status(device_id)}

    # ------------------------------------------------------------------
    # Device Scrubbing: for an "always-on" device (never genuinely off, so
    # TARGET_VS_BACKGROUND has no real "absent" evidence to draw from -- see
    # backend/README.md), algorithmically remove that device's own decoded
    # packets from its declared-background captures, producing a genuine,
    # verifiable "environment without this device" real capture. See
    # scrubbing/device_scrubber.py for the DSP technique and its rationale.
    # ------------------------------------------------------------------

    def find_contaminated_background_captures(self, physical_unit_id: str) -> list[CaptureRecord]:
        """Every background-purpose capture in this device's project that
        genuinely still contains it. Covers both real ways this shows up:
        (1) an ordinary BACKGROUND_GENERAL (or a BACKGROUND_TARGET_OFF
        declared for a DIFFERENT device) capture where the address binding
        resolves uncontested -- physical_unit_id is simply set on the
        example; (2) a BACKGROUND_TARGET_OFF capture declared off for THIS
        exact device, where EvidenceStage already detected the contradiction
        and nulled physical_unit_id -- caught instead via
        _has_background_contradiction(), the existing mechanism for that
        specific case."""
        unit = next((u for u in self.list_physical_units() if u.physical_unit_id == physical_unit_id), None)
        if unit is None:
            raise FileNotFoundError(f"PHYSICAL_UNIT_NOT_FOUND:{physical_unit_id}")
        result = []
        for capture in self.list_captures():
            if capture.project_id != unit.project_id or capture.capture_purpose not in ("BACKGROUND_TARGET_OFF", "BACKGROUND_GENERAL"):
                continue
            if not self.has_evidence(capture.capture_id):
                continue
            examples = self.list_examples(capture.capture_id)
            directly_contaminated = any(example.physical_unit_id == physical_unit_id for example in examples)
            contradiction = capture.target_reference_id == physical_unit_id and self._has_background_contradiction(capture)
            if directly_contaminated or contradiction:
                result.append(capture)
        return result

    def scrub_capture(self, *, capture_id: str, physical_unit_id: str, campaign_id: str, progress=None) -> dict[str, Any]:
        """Produces a NEW capture: the same real recording as capture_id,
        minus every window physical_unit_id was decoded in, each replaced
        with real quiet material borrowed from elsewhere in the same file.
        Runs the new capture through the SAME replay+evidence pipeline as
        any other capture (real decode, not a shortcut), then VERIFIES --
        never assumes -- that zero examples in the result still resolve to
        physical_unit_id."""
        capture = self.get_capture(capture_id)
        if capture is None:
            raise FileNotFoundError(f"CAPTURE_NOT_BUILT_YET:{capture_id}")
        if not self.has_evidence(capture_id):
            raise ValueError(f"CAPTURE_HAS_NO_EVIDENCE_YET:{capture_id}")

        examples = self.list_examples(capture_id)
        removal_windows = [(e.iq_start_sample, e.iq_end_sample) for e in examples if e.physical_unit_id == physical_unit_id]
        occupied_windows = [(e.iq_start_sample, e.iq_end_sample) for e in examples]
        if not removal_windows:
            return {"skipped": True, "reason": "CAPTURE_NOT_CONTAMINATED", "source_capture_id": capture_id}

        if progress:
            progress("SCRUB_READ", 0.0, f"Leyendo IQ real de {capture_id}")
        iq = load_iq(self.resolve_iq_path(capture), capture.sample_dtype)
        scrub_report = scrub_device_windows(iq, removal_windows, occupied_windows)

        if progress:
            progress("SCRUB_WRITE", 0.3, f"Escribiendo captura depurada ({scrub_report['windows_removed']}/{len(removal_windows)} ventanas)")
        derived = derive_scrubbed_capture(
            legacy_capture_root=self.legacy_capture_root, legacy_session_root=self.legacy_session_root,
            source_capture_id=capture_id, edited_iq=scrub_report["iq"], sample_format=capture.sample_dtype,
            scrub_report=scrub_report, excised_physical_unit_id=physical_unit_id,
        )

        new_capture = self.build_capture(
            capture_id=derived["capture_id"], project_id=capture.project_id, campaign_id=campaign_id,
            execution_id=derived["execution_id"], session_id=derived["session_id"],
            capture_purpose="BACKGROUND_TARGET_OFF", target_state="OPERATOR_DECLARED_POWERED_OFF_OR_REMOVED",
            background_kind="TARGET_DECLARED_OFF_OR_REMOVED", target_reference_id=physical_unit_id,
        )

        ble_channel = self._resolve_ble_channel(capture.center_frequency_hz)
        if progress:
            progress("SCRUB_REPLAY", 0.5, f"Decodificando {new_capture.capture_id} (replay real, no atajos)")
        self.run_replay_and_evidence(capture_id=new_capture.capture_id, project_id=capture.project_id, ble_channel=ble_channel, progress=progress)

        residual_examples = [e for e in self.list_examples(new_capture.capture_id) if e.physical_unit_id == physical_unit_id]
        return {
            "skipped": False,
            "source_capture_id": capture_id,
            "new_capture_id": new_capture.capture_id,
            "windows_removed": scrub_report["windows_removed"],
            "windows_without_donor": scrub_report["windows_without_donor"],
            "samples_replaced": scrub_report["samples_replaced"],
            "residual_examples": len(residual_examples),
            "verified": len(residual_examples) == 0,
        }

    def scrub_device_from_background(self, *, physical_unit_id: str, progress=None) -> dict[str, Any]:
        """The one-button flow: auto-detects every contaminated background
        capture for physical_unit_id, scrubs+verifies each, then trains AND
        exports two full sets of 5 candidates -- one using the ORIGINAL
        (contaminated) background captures unchanged, one substituting their
        scrubbed counterparts -- so the real TEST metrics of both are
        directly comparable. The TARGET_DEVICE_ON captures are identical in
        both; only the background side of the comparison changes, isolating
        exactly the variable being tested."""
        unit = next((u for u in self.list_physical_units() if u.physical_unit_id == physical_unit_id), None)
        if unit is None:
            raise FileNotFoundError(f"PHYSICAL_UNIT_NOT_FOUND:{physical_unit_id}")
        campaign_id = f"{unit.project_id}-DEVICE-SCRUB-CAMPAIGN"

        contaminated = self.find_contaminated_background_captures(physical_unit_id)
        if not contaminated:
            return {
                "stopped_at": "detection",
                "stopped_reason": f"No se encontraron capturas de fondo contaminadas por {physical_unit_id} en el proyecto {unit.project_id}.",
                "scrubbed_captures": [],
            }

        scrub_results = []
        for index, capture in enumerate(contaminated):
            if progress:
                progress("SCRUBBING", index / len(contaminated), f"Depurando {index + 1}/{len(contaminated)}: {capture.capture_id}")
            scrub_results.append(self.scrub_capture(capture_id=capture.capture_id, physical_unit_id=physical_unit_id, campaign_id=campaign_id, progress=progress))

        verified = [r for r in scrub_results if not r["skipped"] and r["verified"]]
        if not verified:
            return {
                "stopped_at": "scrub_verification",
                "stopped_reason": "Ninguna captura depurada pudo verificarse sin ejemplos residuales del dispositivo -- no se entrena nada sobre un resultado no confirmado.",
                "scrubbed_captures": scrub_results,
            }

        target_ids = [
            c.capture_id for c in self.list_captures()
            if c.project_id == unit.project_id and c.capture_purpose == "TARGET_DEVICE_ON"
            and (c.target_reference_id == physical_unit_id or c.isolation_declared_physical_unit_id == physical_unit_id)
        ]
        original_background_ids = [c.capture_id for c in contaminated]
        scrubbed_background_ids = [r["new_capture_id"] for r in verified]
        stamp = utc_now().replace(":", "").replace("-", "")

        if progress:
            progress("TRAIN_ORIGINAL", 0.5, "Entrenando con el fondo original (contaminado)")
        original_result = self.prepare_and_train(
            capture_ids=target_ids + original_background_ids, project_id=unit.project_id, campaign_id=campaign_id,
            scientific_task="TARGET_VS_BACKGROUND", dataset_id=f"{physical_unit_id}-ORIGINAL-BG-TVB",
            dataset_version=stamp, target_physical_unit_ids={physical_unit_id}, progress=progress,
        )
        original_exported = (
            self.export_and_approve_all_candidates(physical_unit_id=f"{physical_unit_id}-ORIGINAL-BG", prepare_and_train_result=original_result)
            if original_result.get("split") is not None and original_result["split"].split_status == "READY" else None
        )

        if progress:
            progress("TRAIN_SCRUBBED", 0.75, "Entrenando con el fondo depurado")
        scrubbed_result = self.prepare_and_train(
            capture_ids=target_ids + scrubbed_background_ids, project_id=unit.project_id, campaign_id=campaign_id,
            scientific_task="TARGET_VS_BACKGROUND", dataset_id=f"{physical_unit_id}-SCRUBBED-BG-TVB",
            dataset_version=stamp, target_physical_unit_ids={physical_unit_id}, progress=progress,
        )
        scrubbed_exported = (
            self.export_and_approve_all_candidates(physical_unit_id=f"{physical_unit_id}-SCRUBBED-BG", prepare_and_train_result=scrubbed_result)
            if scrubbed_result.get("split") is not None and scrubbed_result["split"].split_status == "READY" else None
        )

        return {
            "physical_unit_id": physical_unit_id,
            "scrubbed_captures": scrub_results,
            "original": {
                "dataset_id": original_result["dataset"].dataset_id if original_result.get("dataset") else None,
                "final_test_evaluation": original_result.get("final_test_evaluation"),
                "exported_bundles": original_exported,
                "stopped_at": original_result.get("stopped_at"),
                "stopped_reason": original_result.get("stopped_reason"),
            },
            "scrubbed": {
                "dataset_id": scrubbed_result["dataset"].dataset_id if scrubbed_result.get("dataset") else None,
                "final_test_evaluation": scrubbed_result.get("final_test_evaluation"),
                "exported_bundles": scrubbed_exported,
                "stopped_at": scrubbed_result.get("stopped_at"),
                "stopped_reason": scrubbed_result.get("stopped_reason"),
            },
        }

    # ------------------------------------------------------------------
    # Evidence Stage
    # ------------------------------------------------------------------

    def build_evidence(self, *, capture: CaptureRecord, project_id: str, ble_channel: int, replay_run_id: str | None = None, progress=None) -> dict[str, Any]:
        stage = EvidenceStage(self.legacy_capture_root, self.legacy_session_root, self.root / "packet_analysis_cache", self.registry)
        if progress:
            progress("BUILD_EXAMPLES", 0.0, "Construyendo ExampleRecord + ExampleAnnotation desde el replay validado")
        pairs = stage.build_examples(capture=capture, project_id=project_id, ble_channel=ble_channel, replay_run_id=replay_run_id)
        capture_evidence_dir = self.evidence_dir / capture.capture_id
        capture_evidence_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(capture_evidence_dir / "examples.jsonl", [example.model_dump(mode="json") for example, _ in pairs])
        write_jsonl(capture_evidence_dir / "annotations.jsonl", [annotation.model_dump(mode="json") for _, annotation in pairs])
        if progress:
            progress("BUILD_EXAMPLES", 1.0, f"{len(pairs)} ejemplos construidos")
        counts: dict[str, int] = {}
        for example, _ in pairs:
            counts[example.association_status] = counts.get(example.association_status, 0) + 1

        # target_presence_status is the one decision-derived fact this module
        # persists back onto the CaptureRecord itself (everything else --
        # capture_type_label/capture_decision -- stays computed fresh, never
        # stored, per _capture_decision's own docstring). It is written once,
        # right after Evidence Stage actually runs, so any consumer reading
        # just the CaptureRecord (without a separate examples fetch) sees
        # what the evidence showed for this capture's declared purpose.
        _, target_presence_status = self._capture_decision(capture)
        updated_capture = capture.model_copy(update={"target_presence_status": target_presence_status})
        write_json(self.captures_dir / f"{capture.capture_id}.json", updated_capture.model_dump(mode="json"))

        return {"capture_id": capture.capture_id, "n_examples": len(pairs), "association_status_counts": counts, "target_presence_status": target_presence_status}

    def list_examples(self, capture_id: str) -> list[ExampleRecord]:
        path = self.evidence_dir / capture_id / "examples.jsonl"
        return [ExampleRecord.model_validate(row) for row in read_jsonl(path)]

    def list_annotations(self, capture_id: str) -> list[ExampleAnnotation]:
        path = self.evidence_dir / capture_id / "annotations.jsonl"
        return [ExampleAnnotation.model_validate(row) for row in read_jsonl(path)]

    def has_evidence(self, capture_id: str) -> bool:
        return (self.evidence_dir / capture_id / "examples.jsonl").is_file()

    # ------------------------------------------------------------------
    # Dataset Builder
    # ------------------------------------------------------------------

    def build_dataset(
        self, *, dataset_id: str, dataset_version: str, project_id: str, campaign_id: str, capture_ids: list[str],
        derived_from: str | None = None, target_physical_unit_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        # De-duplicated here, defensively, regardless of what the caller
        # passed in: the same capture_id appearing twice in this list would
        # otherwise mean list_examples(capture_id) gets called twice and its
        # examples get appended twice into all_examples, so every one of
        # that capture's examples becomes its own "exact duplicate" group --
        # a real, observed failure mode (a frontend selection bug fed the
        # same capture_id into this list multiple times, producing hundreds
        # of exact-duplicate groups and a NOT_ACCEPTED_FOR_TRAINING gate that
        # looked like a data problem but was actually just double-counting).
        capture_ids = list(dict.fromkeys(capture_ids))
        data_origin = self._require_homogeneous_data_origin(capture_ids)
        self._require_captures_belong_to_project(capture_ids, project_id)
        all_examples: list[ExampleRecord] = []
        for capture_id in capture_ids:
            all_examples.extend(self.list_examples(capture_id))
        # target_physical_unit_ids restricts which bound device(s) are valid
        # TARGET evidence for THIS dataset. Without it, TARGET_VS_BACKGROUND's
        # "any physical_unit_id = target" rule (split_builder.py) treats a
        # packet from ANY registered device as target evidence -- correct
        # when deliberately building a multi-device family dataset, but wrong
        # for a single-device dataset: if a different registered device was
        # physically nearby during this device's TARGET_DEVICE_ON sessions,
        # its packets get folded into "target" too, silently turning a
        # single-device detector into an unintended cross-device one. A real
        # case found in production: CC2541SensorTag's auto-trained dataset
        # was 1199 genuine CC2541SensorTag examples vs 2614 CC2650-UNIT-01
        # examples that had leaked in this way. Excluded here (not
        # relabeled as background -- a foreign device's real packet is not
        # valid "environment absent" evidence either).
        if target_physical_unit_ids is not None:
            in_scope, out_of_scope = [], []
            for example in all_examples:
                if example.physical_unit_id and example.physical_unit_id not in target_physical_unit_ids:
                    out_of_scope.append(example)
                else:
                    in_scope.append(example)
            all_examples = in_scope
        else:
            out_of_scope = []
        selected, excluded = self.dataset_builder.select_examples(all_examples)
        for example in out_of_scope:
            excluded[example.example_id] = f"PHYSICAL_UNIT_OUT_OF_SCOPE:{example.physical_unit_id}"
        draft = self.dataset_builder.build_draft(
            dataset_id=dataset_id, dataset_version=dataset_version, project_id=project_id, campaign_id=campaign_id,
            examples=selected, data_origin=data_origin, creation_policy={"source_captures": capture_ids}, created_at=utc_now(), derived_from=derived_from,
        )
        frozen = self.dataset_builder.freeze(draft)
        return {"dataset": frozen, "n_selected": len(selected), "n_excluded": len(excluded), "excluded_reasons": excluded}

    def _require_homogeneous_data_origin(self, capture_ids: list[str]) -> str:
        origins = set()
        for capture_id in capture_ids:
            capture = self.get_capture(capture_id)
            if capture is None:
                raise FileNotFoundError(f"CAPTURE_NOT_BUILT_YET:{capture_id}")
            origins.add(capture.data_origin)
        if len(origins) > 1:
            raise ValueError(f"CANNOT_MIX_DATA_ORIGINS_IN_ONE_DATASET:{sorted(origins)}. A dataset must be entirely REAL_B200 or entirely SYNTHETIC_TEST_ONLY, never a mix.")
        if not origins:
            raise ValueError("NO_CAPTURES_SUPPLIED")
        return origins.pop()

    def _require_captures_belong_to_project(self, capture_ids: list[str], project_id: str) -> None:
        """A dataset frozen under project_id=X must never silently include a
        capture actually recorded under a different project -- the reviewer's
        explicit "no debe utilizar capturas... de otro proyecto" requirement.
        Checked against the declared project_id, not just mutual consistency
        across capture_ids, so a caller cannot accidentally widen a dataset's
        scope by passing in one stray capture from another project."""
        mismatched = {
            capture_id: capture.project_id
            for capture_id in capture_ids
            if (capture := self.get_capture(capture_id)) is not None and capture.project_id != project_id
        }
        if mismatched:
            raise ValueError(f"CAPTURE_PROJECT_MISMATCH: dataset declared project_id={project_id!r} but these captures belong to a different project: {mismatched}")

    def list_datasets(self) -> list[DatasetManifest]:
        return [DatasetManifest.model_validate(read_json(p)) for p in sorted(self.dataset_builder.root.glob("*.json"))]

    def combine_datasets_for_identification(
        self, dataset_keys: list[tuple[str, str]], background_dataset_key: tuple[str, str] | None = None,
        include_background: bool = True,
    ) -> DatasetManifest:
        """Merges 2+ ALREADY-frozen, single-device datasets into one new
        dataset spanning every one of their physical_units, for
        SAME_MODEL_UNIT_IDENTIFICATION training (a real, pre-existing
        scientific_task -- see split_builder.py's _closed_set_classification
        -- that trains ONE model to say WHICH of several devices is present,
        never lumping them into one "any of these" class the way a
        TARGET_VS_BACKGROUND family dataset would). This is why the
        Training Service uses this path for 2+ selected datasets instead of
        silently building a TARGET_VS_BACKGROUND family: combining unrelated
        devices into one binary "target" class would recreate the exact
        cross-device contamination this project already had to fix once (see
        backend/README.md, CC2541SensorTag/CC2650-UNIT-01).

        background_dataset_key (optional): use ONE dataset's background-only
        examples (physical_unit_id is None) as the SOLE "environment absent"
        evidence for every device, instead of pooling whatever background
        each per-device dataset happens to carry on its own (real, observed
        problem: most per-device datasets only ever needed a THIN background
        pool to pass TARGET_VS_BACKGROUND's own 3-session minimum, while
        SHELLY-PLUG-01-SCRUBBED-BG-TVB has real, verified, 8-session
        background evidence -- see backend/README.md's device-scrubbing
        section). When given, each device dataset in dataset_keys
        contributes ONLY its own target examples (physical_unit_id set to
        that device), never its own background -- avoiding the accidental
        dilution/duplication of mixing several different background pools
        of very different real quality into one class.

        Examples are otherwise reused exactly as already selected by each
        source dataset (select_examples() eligibility was already decided
        when each one was built) -- never re-derived, never re-filtered.

        include_background=False (2026-08-15, closed-set 4-unit paper
        realignment): drop every physical_unit_id=None example from every
        source dataset, from ALL of them, not just relabel them -- for a
        pure N-way closed-set comparison where BACKGROUND must never become
        an implicit 5th class. Mutually exclusive with background_dataset_key
        (which exists to ADD one shared background pool, the opposite of
        this)."""
        if len(dataset_keys) < 2:
            raise ValueError("COMBINE_REQUIRES_AT_LEAST_TWO_DATASETS")
        if not include_background and background_dataset_key is not None:
            raise ValueError("BACKGROUND_DATASET_KEY_REQUIRES_INCLUDE_BACKGROUND")
        datasets = []
        for dataset_id, dataset_version in dataset_keys:
            dataset = self._require_dataset(dataset_id, dataset_version)
            datasets.append(dataset)

        background_dataset = self._require_dataset(*background_dataset_key) if background_dataset_key else None
        origins = {d.data_origin for d in datasets} | ({background_dataset.data_origin} if background_dataset else set())
        if len(origins) > 1:
            raise ValueError(f"CANNOT_COMBINE_MIXED_DATA_ORIGINS:{sorted(origins)}")

        all_examples: dict[str, ExampleRecord] = {}
        if not include_background:
            for dataset in datasets:
                for example in self._dataset_examples(dataset):
                    if example.physical_unit_id is not None:
                        all_examples[example.example_id] = example
        elif background_dataset is not None:
            for example in self._dataset_examples(background_dataset):
                if example.physical_unit_id is None:
                    all_examples[example.example_id] = example
            for dataset in datasets:
                for example in self._dataset_examples(dataset):
                    if example.physical_unit_id is not None:
                        all_examples[example.example_id] = example
        else:
            for dataset in datasets:
                for example in self._dataset_examples(dataset):
                    all_examples[example.example_id] = example
        examples = list(all_examples.values())

        # Short and unique, never a concatenation of every source dataset_id:
        # chaining them here (as a first version of this did) produced a
        # filename that exceeded Windows' ~260-char path limit once combined
        # with the split file's own long suffix
        # (__{version}__SAME_MODEL_UNIT_IDENTIFICATION.json), failing with a
        # bare FileNotFoundError. Full traceability is still real -- it lives
        # in physical_units (below) and creation_policy.combined_from, not
        # in the filename.
        combined_id = f"IDENTITY-{uuid.uuid4().hex[:10]}"
        combined_version = utc_now().replace(":", "").replace("-", "")
        project_id = "+".join(sorted({d.project_id for d in datasets}))
        campaign_id = f"{project_id}-IDENTITY-COMBINE-CAMPAIGN"

        creation_policy: dict[str, Any] = {"combined_from": [{"dataset_id": d.dataset_id, "dataset_version": d.dataset_version} for d in datasets]}
        if background_dataset is not None:
            creation_policy["shared_background_from"] = {"dataset_id": background_dataset.dataset_id, "dataset_version": background_dataset.dataset_version}
        draft = self.dataset_builder.build_draft(
            dataset_id=combined_id, dataset_version=combined_version, project_id=project_id, campaign_id=campaign_id,
            examples=examples, data_origin=origins.pop(),
            creation_policy=creation_policy,
            created_at=utc_now(),
        )
        return self.dataset_builder.freeze(draft)

    def delete_dataset(self, dataset_id: str, dataset_version: str) -> dict[str, Any]:
        """Deletes a frozen dataset manifest and every split built from it.
        Never touches the underlying captures/evidence -- a dataset is just a
        frozen selection over those, so removing it only removes the
        selection, not the source evidence a new dataset could still be
        built from. Does not check whether a TrainingRun still references
        this dataset_id/version (existing training runs and exported bundles
        keep their own copy of the manifest hash and stay valid as a
        historical record either way -- consistent with delete_legacy_capture
        not blocking on datasets that still reference that capture)."""
        if not dataset_id or any(part in dataset_id for part in ("/", "\\", "..")):
            raise ValueError(f"INVALID_DATASET_ID:{dataset_id}")
        if not dataset_version or any(part in dataset_version for part in ("/", "\\", "..")):
            raise ValueError(f"INVALID_DATASET_VERSION:{dataset_version}")
        dataset_path = self.dataset_builder._path(dataset_id, dataset_version)
        if not dataset_path.is_file():
            raise FileNotFoundError(f"DATASET_NOT_FOUND:{dataset_id}:{dataset_version}")
        dataset_path.unlink()

        deleted_splits: list[str] = []
        prefix = f"{dataset_id}__{dataset_version}__"
        for split_path in self.splits_dir.glob(f"{prefix}*.json"):
            deleted_splits.append(split_path.stem)
            split_path.unlink()

        return {"deleted": True, "dataset_id": dataset_id, "dataset_version": dataset_version, "deleted_splits": deleted_splits}

    def get_dataset(self, dataset_id: str, dataset_version: str) -> DatasetManifest | None:
        return self.dataset_builder.load(dataset_id, dataset_version)

    def _dataset_examples(self, dataset: DatasetManifest) -> list[ExampleRecord]:
        by_id: dict[str, ExampleRecord] = {}
        for capture_id in dataset.captures:
            for example in self.list_examples(capture_id):
                by_id[example.example_id] = example
        return [by_id[eid] for eid in dataset.example_ids if eid in by_id]

    def label_provenance_report(self, dataset_id: str, dataset_version: str) -> dict[str, Any]:
        """What fraction of a dataset's examples rest on genuinely
        independent ground truth (STRONG: address + native Windows
        association) versus weaker or contested evidence
        (PHYSICAL_ISOLATION_DECLARED: trusts the operator's own physical
        setup, never independently corroborated; AMBIGUOUS/CONFLICT/NONE).
        A dataset can pass every duplicate/leakage/single-class gate and
        still rest almost entirely on the operator's own declaration --
        this was previously only discoverable by reading raw evidence
        JSONL by hand (see the professional inspection report's finding:
        72 STRONG vs 12,092 PHYSICAL_ISOLATION_DECLARED associations across
        this project's real evidence). Never a gate by itself -- purely
        informational, for the benchmark/comparison view to show alongside
        each model's accuracy so a high score backed mostly by declared
        isolation is never presented as equivalent to one backed by strong
        independent association."""
        dataset = self._require_dataset(dataset_id, dataset_version)
        examples = self._dataset_examples(dataset)
        counts: dict[str, int] = {}
        for example in examples:
            counts[example.association_status] = counts.get(example.association_status, 0) + 1
        total = len(examples)
        return {
            "dataset_id": dataset_id, "dataset_version": dataset_version, "total_examples": total,
            "counts": counts,
            "fractions": {status: round(count / total, 4) for status, count in counts.items()} if total else {},
            "strong_fraction": round(counts.get("STRONG", 0) / total, 4) if total else 0.0,
        }

    def dataset_composition_report(self, dataset_id: str, dataset_version: str) -> dict[str, Any]:
        """Purely informational, never a gate: how a dataset's examples are
        distributed across BLE channel, real capture day, session, and
        physical unit -- a lopsided capture protocol (everything on one
        channel, all captured in one afternoon, one unit far outweighing the
        others) is invisible in an aggregate accuracy number, and was
        previously only discoverable by reading raw evidence by hand. Day is
        the referenced CaptureRecord's own created_at (the real acquisition
        moment), never the example's own created_at (which is evidence-build
        time -- a capture can be re-analyzed long after it was recorded, and
        that must never be confused with when the RF was actually captured).
        """
        dataset = self._require_dataset(dataset_id, dataset_version)
        examples = self._dataset_examples(dataset)
        capture_day_by_id: dict[str, str] = {}
        channel_counts: dict[str, int] = {}
        session_ids: set[str] = set()
        day_counts: dict[str, int] = {}
        physical_unit_counts: dict[str, int] = {}
        for example in examples:
            channel_counts[str(example.channel)] = channel_counts.get(str(example.channel), 0) + 1
            session_ids.add(example.session_id)
            if example.capture_id not in capture_day_by_id:
                capture = self.get_capture(example.capture_id)
                capture_day_by_id[example.capture_id] = (capture.created_at[:10] if capture and capture.created_at else "UNKNOWN")
            day = capture_day_by_id[example.capture_id]
            day_counts[day] = day_counts.get(day, 0) + 1
            unit_key = example.physical_unit_id or "UNKNOWN"
            physical_unit_counts[unit_key] = physical_unit_counts.get(unit_key, 0) + 1
        return {
            "dataset_id": dataset_id, "dataset_version": dataset_version, "total_examples": len(examples),
            "channel_counts": channel_counts, "session_count": len(session_ids), "day_counts": day_counts,
            "physical_unit_counts": physical_unit_counts,
        }

    def capture_iq_paths_for(self, capture_ids: list[str]) -> dict[str, Path]:
        paths: dict[str, Path] = {}
        for capture_id in capture_ids:
            capture = self.get_capture(capture_id)
            if capture is not None:
                paths[capture_id] = self.resolve_iq_path(capture)
        return paths

    # ------------------------------------------------------------------
    # Dataset Analyzer (quality gate)
    # ------------------------------------------------------------------

    def build_quality_report(self, *, dataset_id: str, dataset_version: str, run_near_duplicates: bool = False) -> DatasetQualityReport:
        dataset = self._require_dataset(dataset_id, dataset_version)
        examples = self._dataset_examples(dataset)
        exact = self.analyzer.check_exact_duplicates(examples)
        overlap = self.analyzer.check_sample_overlap(examples)
        if run_near_duplicates:
            iq_paths = self.capture_iq_paths_for(dataset.captures)
            near = self.analyzer.check_near_duplicates(examples, capture_iq_paths=iq_paths)
        else:
            near = self.analyzer.check_near_duplicates(examples)
        report = self.analyzer.build_gate(dataset, exact, overlap, near, created_at=utc_now())
        write_json(self.quality_dir / f"{dataset_id}__{dataset_version}.json", report.model_dump(mode="json"))
        return report

    def get_quality_report(self, dataset_id: str, dataset_version: str) -> DatasetQualityReport | None:
        path = self.quality_dir / f"{dataset_id}__{dataset_version}.json"
        return DatasetQualityReport.model_validate(read_json(path)) if path.is_file() else None

    def resolve_dataset_duplicates(self, *, capture_ids: list[str]) -> dict[str, Any]:
        """The UI-reachable fix for a quality gate blocked on exact
        duplicates or sample overlap (see DatasetAnalyzer.resolve_overlaps
        for the resolution rule itself). Operates directly on capture
        evidence (examples.jsonl per capture_id), not on any particular
        dataset draft -- the preview dataset used by "Revisar datos" is
        rebuilt fresh from capture evidence on every review, so fixing the
        underlying examples here is what makes the NEXT review pass clean,
        with no dataset-version bookkeeping needed. Idempotent: re-running
        against an already-resolved set finds nothing left to exclude.
        """
        examples_by_capture: dict[str, list[ExampleRecord]] = {}
        all_examples: list[ExampleRecord] = []
        for capture_id in dict.fromkeys(capture_ids):  # de-duplicate, preserve order
            examples = self.list_examples(capture_id)
            examples_by_capture[capture_id] = examples
            all_examples.extend(examples)

        excluded = self.analyzer.resolve_overlaps(all_examples)
        if not excluded:
            return {"quarantined_example_ids": [], "details": {}, "captures_updated": []}

        captures_updated: list[str] = []
        for capture_id, examples in examples_by_capture.items():
            if not any(e.example_id in excluded for e in examples):
                continue
            updated = [
                e.model_copy(update={"dataset_eligibility": "QUARANTINED"}) if e.example_id in excluded else e
                for e in examples
            ]
            write_jsonl(self.evidence_dir / capture_id / "examples.jsonl", [e.model_dump(mode="json") for e in updated])
            captures_updated.append(capture_id)

        return {"quarantined_example_ids": sorted(excluded), "details": excluded, "captures_updated": captures_updated}

    # ------------------------------------------------------------------
    # Split Builder
    # ------------------------------------------------------------------

    def build_split(self, *, dataset_id: str, dataset_version: str, scientific_task: str) -> SplitManifest:
        dataset = self._require_dataset(dataset_id, dataset_version)
        examples = self._dataset_examples(dataset)
        split = self.split_builder.build(dataset=dataset, examples=examples, scientific_task=scientific_task, created_at=utc_now())
        write_json(self._split_path(dataset_id, dataset_version, scientific_task), split.model_dump(mode="json"))
        return split

    def get_split(self, dataset_id: str, dataset_version: str, scientific_task: str) -> SplitManifest | None:
        path = self._split_path(dataset_id, dataset_version, scientific_task)
        return SplitManifest.model_validate(read_json(path)) if path.is_file() else None

    def _split_path(self, dataset_id: str, dataset_version: str, scientific_task: str) -> Path:
        return self.splits_dir / f"{dataset_id}__{dataset_version}__{scientific_task}.json"

    def dataset_training_preview(self, *, dataset_id: str, dataset_version: str, scientific_task: str) -> dict[str, Any]:
        """The reviewer's explicit "pantalla de revision antes de entrenar":
        TRAIN/VALIDATION/TEST classes, sessions per class, examples per class
        and capture_ids actually used -- computed strictly from the frozen
        DatasetManifest's own example_ids and the already-built SplitManifest's
        own assignments, never recomputed independently, so these numbers can
        never drift from what training itself will actually consume. Also
        surfaces which captures were quarantined/excluded so the operator can
        see why they are absent, instead of the interface silently showing 0
        while training uses hundreds of examples (the exact original bug)."""
        dataset = self._require_dataset(dataset_id, dataset_version)
        split = self.get_split(dataset_id, dataset_version, scientific_task)
        if split is None:
            raise FileNotFoundError(f"SPLIT_NOT_BUILT_YET:{dataset_id}:{dataset_version}:{scientific_task}")

        frozen_ids = set(dataset.example_ids)
        by_id = {e.example_id: e for e in self._dataset_examples(dataset) if e.example_id in frozen_ids}

        splits: dict[str, Any] = {}
        for split_name in ("TRAIN", "VALIDATION", "TEST"):
            sessions_by_class: dict[str, set[str]] = {}
            examples_by_class: dict[str, int] = {}
            capture_ids: set[str] = set()
            for assignment in split.assignments:
                if assignment.split != split_name or assignment.example_id not in by_id:
                    continue
                example = by_id[assignment.example_id]
                label = train_label_for(scientific_task, example)
                sessions_by_class.setdefault(label, set()).add(example.session_id)
                examples_by_class[label] = examples_by_class.get(label, 0) + 1
                capture_ids.add(example.capture_id)
            splits[split_name] = {
                "classes": sorted(sessions_by_class),
                "sessions_by_class": {label: sorted(sessions) for label, sessions in sessions_by_class.items()},
                "examples_by_class": examples_by_class,
                "capture_ids": sorted(capture_ids),
            }

        # Informational only, recomputed fresh from every example the source
        # captures actually produced (not just the frozen selection) -- shows
        # WHY an example never made it into the frozen dataset in the first
        # place. Never affects training, which only ever reads dataset.example_ids.
        all_examples = self._dataset_examples(dataset)
        _, excluded_reasons = self.dataset_builder.select_examples(all_examples)
        quarantined_capture_ids = sorted({
            capture_id for capture_id in dataset.captures
            if (capture := self.get_capture(capture_id)) is not None and self._capture_decision(capture)[0] in ("QUARANTINED", "QUARANTINED_AMBIGUOUS")
        })

        # The review must never say "ready" while the real quality gate
        # (build_quality_report, run right before training) would reject the
        # same frozen examples -- that exact contradiction was a real, observed
        # bug (a capture_id repeated in the input list produced hundreds of
        # exact-duplicate groups the review never checked for). Checked fresh
        # here over the frozen dataset.example_ids, the same set training uses.
        frozen_examples = self._dataset_examples(dataset)
        exact_duplicates = self.analyzer.check_exact_duplicates(frozen_examples)
        sample_overlap = self.analyzer.check_sample_overlap(frozen_examples)
        quality_gate_ok = exact_duplicates.status != "FAILED" and sample_overlap.status != "FAILED"
        quality_gate_reasons: list[str] = []
        if exact_duplicates.status == "FAILED":
            quality_gate_reasons.append(f"{len(exact_duplicates.duplicate_groups)} exact-duplicate group(s) found.")
        if sample_overlap.status == "FAILED":
            quality_gate_reasons.append(f"{len(sample_overlap.overlapping_pairs)} overlapping (non-identical) sample-range pair(s) found.")

        # Never just a count -- name the exact example_id/capture_id/sample
        # range pair a FAILED sample_overlap is about, and which split each
        # side landed in. Splits are built session-disjoint (SplitBuilder:
        # a whole capture/session belongs to exactly one split), so an
        # overlap inside one capture (source_iq_sha256) structurally cannot
        # cross TRAIN/VALIDATION/TEST -- and even if that invariant were ever
        # violated, SplitBuilder._compute_leakage already checks sample_range
        # as one of its own leakage fields and would mark the whole split
        # NOT_FEASIBLE before training could ever see it. cross_partition is
        # computed for real here, never assumed, precisely to make that
        # guarantee visible instead of taken on faith.
        example_id_to_split = {assignment.example_id: assignment.split for assignment in split.assignments}
        sample_overlap_pairs = [
            detail.model_copy(update={
                "split_a": example_id_to_split.get(detail.example_id_a),
                "split_b": example_id_to_split.get(detail.example_id_b),
                "cross_partition": example_id_to_split.get(detail.example_id_a) != example_id_to_split.get(detail.example_id_b),
            }).model_dump(mode="json")
            for detail in sample_overlap.pair_details
        ]

        return {
            "dataset_id": dataset_id, "dataset_version": dataset_version, "scientific_task": scientific_task,
            "split_status": split.split_status, "infeasibility_reason": split.infeasibility_reason,
            "quality_gate_ok": quality_gate_ok, "quality_gate_reasons": quality_gate_reasons,
            "sample_overlap_pairs": sample_overlap_pairs,
            "ready_to_train": split.split_status == "READY" and quality_gate_ok,
            "splits": splits,
            "eligible_examples_total": len(dataset.example_ids),
            "excluded_examples_total": len(excluded_reasons),
            "excluded_reasons": excluded_reasons,
            "quarantined_capture_ids": quarantined_capture_ids,
        }

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def run_training(
        self, *, training_run: TrainingRun, progress=None,
        iq_window_provider: Callable[[ExampleRecord], np.ndarray] | None = None,
        eligible_example_ids: set[str] | None = None,
        feature_indices: list[int] | None = None,
    ) -> TrainingRun:
        dataset = self._require_dataset(training_run.dataset_id, training_run.dataset_version)
        if training_run.data_origin != dataset.data_origin:
            raise ValueError(
                f"TRAINING_RUN_DATA_ORIGIN_MISMATCH:declared={training_run.data_origin}:dataset={dataset.data_origin}. "
                "A TrainingRun's data_origin must always match the dataset it trains on -- never declared independently."
            )

        run_dir = self.training_dir / training_run.training_run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        write_json(run_dir / "training_run.json", training_run.model_dump(mode="json"))

        split = self.get_split(training_run.dataset_id, training_run.dataset_version, training_run.scientific_task)
        if split is None:
            raise FileNotFoundError(f"SPLIT_NOT_BUILT_YET:{training_run.dataset_id}:{training_run.dataset_version}:{training_run.scientific_task}")
        # RQ4 region-specific fitting (2026-08-12): a block available in
        # FULL_BURST but not validly available in the target analytical
        # region (e.g. no known AdvA offset for ADVA_EXCLUDED) must never
        # contribute to that region's fit -- filtering assignments here
        # (never examples_by_id, which every split.assignments lookup below
        # still indexes into) keeps TRAIN/VALIDATION/TEST membership
        # otherwise identical to the base run's own split, restricted only
        # to examples this region actually has a real derived window for.
        if eligible_example_ids is not None:
            split = split.model_copy(update={"assignments": [a for a in split.assignments if a.example_id in eligible_example_ids]})
        examples_by_id = {e.example_id: e for e in self._dataset_examples(dataset)}
        iq_paths = self.capture_iq_paths_for(dataset.captures)

        if progress:
            progress("TRAIN", 0.1, f"Entrenando {training_run.model_type}")
        # Preprocessing-registry correction (2026-08-08): resolve the REAL
        # flags a declared profile_id means, never a bare, flag-less
        # placeholder -- previously this always trained with identity
        # preprocessing regardless of what base_preprocessing_profile_id said.
        service = TrainingService(
            iq_paths, resolve_preprocessing_profile(training_run.base_preprocessing_profile_id), iq_window_provider=iq_window_provider,
        )
        try:
            if training_run.model_type in _TORCH_MODEL_TYPES:
                artifacts = service.run_cnn(training_run=training_run, split=split, examples_by_id=examples_by_id)
            elif training_run.model_type == "frozen_morphological_baseline":
                artifacts = service.run_frozen_reference_baseline(training_run=training_run, split=split, examples_by_id=examples_by_id)
            else:
                artifacts = service.run_baseline(training_run=training_run, split=split, examples_by_id=examples_by_id, feature_indices=feature_indices)
        except Exception as error:
            failed = training_run.model_copy(update={"status": "FAILED"})
            write_json(run_dir / "training_run.json", failed.model_dump(mode="json"))
            write_json(run_dir / "error.json", {"error": f"{type(error).__name__}: {error}"})
            raise

        if progress:
            progress("TRAIN", 0.9, "Persistiendo artefactos del modelo")
        self._persist_training_artifacts(run_dir, artifacts)
        if progress:
            progress("TRAIN", 1.0, "Entrenamiento completado")
        return artifacts.training_run

    def _persist_training_artifacts(self, run_dir: Path, artifacts: TrainingArtifacts) -> None:
        write_json(run_dir / "training_run.json", artifacts.training_run.model_dump(mode="json"))
        if artifacts.training_run.model_type in _TORCH_MODEL_TYPES:
            torch.save(artifacts.model, run_dir / "model.pt")
        else:
            joblib.dump(artifacts.model, run_dir / "model.joblib")
        if artifacts.scaler is not None:
            joblib.dump(artifacts.scaler, run_dir / "scaler.joblib")
        write_json(run_dir / "label_classes.json", {"classes": artifacts.label_classes})
        write_json(run_dir / "feature_names.json", {"names": artifacts.feature_names})
        write_json(run_dir / "metrics.json", artifacts.metrics)
        write_json(run_dir / "predictions.json", artifacts.predictions)
        write_json(run_dir / "latency.json", {"validation_latency_ms": artifacts.validation_latency_ms})
        # Eq.(6)-(7) per-burst provenance (2026-08-08, point 3): only written
        # when the base_profile actually ran paper_eq6_7_compensation --
        # empty for every other profile, never a fabricated file.
        if artifacts.preprocessing_provenance:
            write_jsonl(run_dir / "preprocessing_provenance.jsonl", [
                {"example_id": example_id, **provenance} for example_id, provenance in artifacts.preprocessing_provenance.items()
            ])

    def list_training_runs(self) -> list[dict[str, Any]]:
        runs = []
        for path in sorted(self.training_dir.glob("*/training_run.json")):
            run = read_json(path)
            metrics_path = path.parent / "metrics.json"
            runs.append({**run, "metrics": read_json(metrics_path) if metrics_path.is_file() else None})
        return runs

    def get_training_run(self, training_run_id: str) -> dict[str, Any] | None:
        run_dir = self.training_dir / training_run_id
        path = run_dir / "training_run.json"
        if not path.is_file():
            return None
        run = read_json(path)
        metrics_path = run_dir / "metrics.json"
        label_classes_path = run_dir / "label_classes.json"
        error_path = run_dir / "error.json"
        return {
            **run,
            "metrics": read_json(metrics_path) if metrics_path.is_file() else None,
            "label_classes": read_json(label_classes_path)["classes"] if label_classes_path.is_file() else None,
            "error": read_json(error_path) if error_path.is_file() else None,
        }

    def get_training_run_predictions(self, training_run_id: str, split: str) -> list[dict[str, Any]] | None:
        """Real, already-persisted per-example predictions for one split of
        one training run (predictions.json, written by run_training()) --
        the SAME shape Evaluator.evaluate_split()/
        enrolled_population_class_exclusion_sensitivity() already consume.
        Returns None (never []) when the run has no predictions yet or
        never had that split."""
        predictions_path = self.training_dir / training_run_id / "predictions.json"
        if not predictions_path.is_file():
            return None
        return read_json(predictions_path).get(split)

    def bootstrap_accuracy_ci(self, training_run_id: str, *, split: str = "VALIDATION", n_resamples: int = 2000, confidence_level: float = 0.95) -> dict[str, Any] | None:
        """Bootstrap correction (2026-08-08): a real session-clustered
        percentile CI on a training run's own already-computed predictions
        -- wires hierarchical_cluster_bootstrap (real, tested, previously
        production-unused) to real results, never a second scoring path.
        split="TEST" is allowed (this only reads predictions.json, it never
        opens TEST itself) but the caller is responsible for having already
        gone through evaluate_training_run(include_test=True) if TEST access
        needs to be logged -- this method does not gate that on its own."""
        run_dir = self.training_dir / training_run_id
        predictions_path = run_dir / "predictions.json"
        label_classes_path = run_dir / "label_classes.json"
        run_path = run_dir / "training_run.json"
        if not (predictions_path.is_file() and run_path.is_file()):
            raise FileNotFoundError(f"TRAINING_RUN_HAS_NO_PREDICTIONS_YET:{training_run_id}")
        predictions_by_split = read_json(predictions_path)
        if split not in predictions_by_split:
            return None
        label_classes = read_json(label_classes_path)["classes"]
        training_run = TrainingRun.model_validate(read_json(run_path))
        dataset = self._require_dataset(training_run.dataset_id, training_run.dataset_version)
        session_id_by_example_id = {e.example_id: e.session_id for e in self._dataset_examples(dataset)}

        result = self.evaluator.bootstrap_accuracy_ci(
            predictions_by_split[split], label_classes, session_id_by_example_id, n_resamples=n_resamples, confidence_level=confidence_level,
        )
        if result is None:
            return None
        return {"split": split, **dataclasses.asdict(result)}

    def bootstrap_balanced_accuracy_ci(self, training_run_id: str, *, split: str = "VALIDATION", n_resamples: int = 2000, confidence_level: float = 0.95) -> dict[str, Any] | None:
        """Same real, already-persisted-predictions read path as
        bootstrap_accuracy_ci() above, wired to Evaluator.
        bootstrap_balanced_accuracy_ci() instead -- a CI on the SAME metric
        (balanced accuracy) RQ1/RQ2 report as their headline number, not on
        raw accuracy."""
        run_dir = self.training_dir / training_run_id
        predictions_path = run_dir / "predictions.json"
        label_classes_path = run_dir / "label_classes.json"
        run_path = run_dir / "training_run.json"
        if not (predictions_path.is_file() and run_path.is_file()):
            raise FileNotFoundError(f"TRAINING_RUN_HAS_NO_PREDICTIONS_YET:{training_run_id}")
        predictions_by_split = read_json(predictions_path)
        if split not in predictions_by_split:
            return None
        label_classes = read_json(label_classes_path)["classes"]
        training_run = TrainingRun.model_validate(read_json(run_path))
        dataset = self._require_dataset(training_run.dataset_id, training_run.dataset_version)
        session_id_by_example_id = {e.example_id: e.session_id for e in self._dataset_examples(dataset)}

        result = self.evaluator.bootstrap_balanced_accuracy_ci(
            predictions_by_split[split], label_classes, session_id_by_example_id, n_resamples=n_resamples, confidence_level=confidence_level,
        )
        if result is None:
            return None
        return {"split": split, **dataclasses.asdict(result)}

    def _load_predictions_for_bootstrap(self, training_run_id: str, split: str) -> tuple[list[dict[str, Any]], list[str], dict[str, str]] | None:
        """Shared file-read step behind bootstrap_balanced_accuracy_ci() and
        bootstrap_balanced_accuracy_delta_ci() -- real predictions.json/
        label_classes.json/session_id join, never a second read path."""
        run_dir = self.training_dir / training_run_id
        predictions_path = run_dir / "predictions.json"
        label_classes_path = run_dir / "label_classes.json"
        run_path = run_dir / "training_run.json"
        if not (predictions_path.is_file() and run_path.is_file()):
            raise FileNotFoundError(f"TRAINING_RUN_HAS_NO_PREDICTIONS_YET:{training_run_id}")
        predictions_by_split = read_json(predictions_path)
        if split not in predictions_by_split:
            return None
        label_classes = read_json(label_classes_path)["classes"]
        training_run = TrainingRun.model_validate(read_json(run_path))
        dataset = self._require_dataset(training_run.dataset_id, training_run.dataset_version)
        session_id_by_example_id = {e.example_id: e.session_id for e in self._dataset_examples(dataset)}
        return predictions_by_split[split], label_classes, session_id_by_example_id

    def bootstrap_balanced_accuracy_delta_ci(
        self, training_run_id_a: str, training_run_id_b: str, *, split_a: str = "VALIDATION", split_b: str = "VALIDATION",
        n_resamples: int = 2000, confidence_level: float = 0.95,
    ) -> dict[str, Any] | None:
        """RQ1's real delta_dependence CI (2026-08-17 completion pass): joint
        bootstrap over BA_window's own diagnostic-run predictions (a) and
        BA_capture's confirmatory-run predictions (b) -- two independent,
        session-disjoint populations by RQ1's own design. `label_classes`
        must agree between the two runs (same closed-set task); raises if
        they genuinely differ rather than silently picking one."""
        loaded_a = self._load_predictions_for_bootstrap(training_run_id_a, split_a)
        loaded_b = self._load_predictions_for_bootstrap(training_run_id_b, split_b)
        if loaded_a is None or loaded_b is None:
            return None
        predictions_a, label_classes_a, session_ids_a = loaded_a
        predictions_b, label_classes_b, session_ids_b = loaded_b
        if sorted(label_classes_a) != sorted(label_classes_b):
            raise ValueError(f"LABEL_CLASSES_MISMATCH_BETWEEN_RUNS:{training_run_id_a}={label_classes_a}:{training_run_id_b}={label_classes_b}")

        result = self.evaluator.bootstrap_balanced_accuracy_delta_ci(
            predictions_a, predictions_b, label_classes_a, session_ids_a, session_ids_b,
            n_resamples=n_resamples, confidence_level=confidence_level,
        )
        if result is None:
            return None
        return {"split_a": split_a, "split_b": split_b, **dataclasses.asdict(result)}

    def bootstrap_balanced_accuracy_ci_stratified_by_class(
        self, training_run_id: str, *, split: str = "VALIDATION", n_resamples: int = 2000, confidence_level: float = 0.95,
    ) -> dict[str, Any] | None:
        """Methodological-audit fix (2026-08-22, item 3): class-preserving
        sibling of bootstrap_balanced_accuracy_ci() -- same real predictions/
        session read path, resamples within each true class independently
        so no resample can silently drop a class from the mean-per-class-
        recall statistic. See Evaluator.bootstrap_balanced_accuracy_ci_
        stratified_by_class's own docstring."""
        loaded = self._load_predictions_for_bootstrap(training_run_id, split)
        if loaded is None:
            return None
        predictions, label_classes, session_id_by_example_id = loaded
        result = self.evaluator.bootstrap_balanced_accuracy_ci_stratified_by_class(
            predictions, label_classes, session_id_by_example_id, n_resamples=n_resamples, confidence_level=confidence_level,
        )
        if result is None:
            return None
        return {"split": split, **dataclasses.asdict(result)}

    def bootstrap_balanced_accuracy_delta_ci_stratified_by_class(
        self, training_run_id_a: str, training_run_id_b: str, *, split_a: str = "VALIDATION", split_b: str = "VALIDATION",
        n_resamples: int = 2000, confidence_level: float = 0.95,
    ) -> dict[str, Any] | None:
        """Methodological-audit fix (2026-08-22, item 3): RQ1's real
        delta_dependence CI, class-stratified on both sides, terminology
        that does not claim a "paired" bootstrap (there is no physical
        pairing between the two domains' sessions). See
        Evaluator.bootstrap_balanced_accuracy_delta_ci_stratified_by_class's
        own docstring."""
        loaded_a = self._load_predictions_for_bootstrap(training_run_id_a, split_a)
        loaded_b = self._load_predictions_for_bootstrap(training_run_id_b, split_b)
        if loaded_a is None or loaded_b is None:
            return None
        predictions_a, label_classes_a, session_ids_a = loaded_a
        predictions_b, label_classes_b, session_ids_b = loaded_b
        if sorted(label_classes_a) != sorted(label_classes_b):
            raise ValueError(f"LABEL_CLASSES_MISMATCH_BETWEEN_RUNS:{training_run_id_a}={label_classes_a}:{training_run_id_b}={label_classes_b}")

        result = self.evaluator.bootstrap_balanced_accuracy_delta_ci_stratified_by_class(
            predictions_a, predictions_b, label_classes_a, session_ids_a, session_ids_b,
            n_resamples=n_resamples, confidence_level=confidence_level,
        )
        if result is None:
            return None
        return {"split_a": split_a, "split_b": split_b, **dataclasses.asdict(result)}

    def train_seed_variability_analysis(self, *, training_run_id: str, seeds: tuple[int, ...] | None = None, progress=None) -> list[dict[str, Any]]:
        """Fixed seed-set correction (2026-08-08): how much a candidate's
        VALIDATION performance moves across independent training runs of the
        EXACT SAME configuration (dataset/split/model_type/preprocessing/
        representation), varying only random_seed. VALIDATION-only, on
        purpose, matching P0.1's discipline -- this is a model-selection-
        adjacent diagnostic, never a confirmatory analysis, so it must never
        open TEST for any of the re-trained runs. seeds defaults to
        FROZEN_TRAINING_SEEDS[1:] (every seed in the frozen set other than
        the one the original run already used) -- a caller-supplied seeds
        tuple must itself be a subset of FROZEN_TRAINING_SEEDS: this is a
        frozen set, not an open-ended parameter."""
        base_run_dict = self.get_training_run(training_run_id)
        if base_run_dict is None:
            raise FileNotFoundError(f"TRAINING_RUN_NOT_FOUND:{training_run_id}")
        if base_run_dict["status"] != "COMPLETED":
            raise ValueError(f"CANNOT_RUN_SEED_VARIABILITY_ON_AN_INCOMPLETE_TRAINING_RUN:{training_run_id}:{base_run_dict['status']}")
        base_run = TrainingRun.model_validate({k: v for k, v in base_run_dict.items() if k not in ("metrics", "label_classes", "error")})

        candidate_seeds = seeds if seeds is not None else tuple(s for s in FROZEN_TRAINING_SEEDS if s != base_run.random_seed)
        unknown_seeds = set(candidate_seeds) - set(FROZEN_TRAINING_SEEDS)
        if unknown_seeds:
            raise ValueError(f"SEEDS_MUST_BE_FROM_THE_FROZEN_SET:{sorted(unknown_seeds)} not in FROZEN_TRAINING_SEEDS={FROZEN_TRAINING_SEEDS}")

        results: list[dict[str, Any]] = []
        for index, seed in enumerate(candidate_seeds):
            if progress:
                progress("SEED_VARIABILITY", index / max(1, len(candidate_seeds)), f"seed {seed} ({index + 1}/{len(candidate_seeds)})")
            variant_run = base_run.model_copy(update={
                "training_run_id": f"{training_run_id}-seed-{seed}",
                "random_seed": seed, "status": "QUEUED", "started_at": None, "completed_at": None,
                "analysis_contract_protocol_id": None, "analysis_contract_protocol_version": None, "analysis_contract_hash": None,
            })
            completed = self.run_training(training_run=variant_run)
            # include_test=False here is load-bearing, not a default left
            # alone: a seed-variability run must never open TEST.
            evaluation = self.evaluate_training_run(completed.training_run_id, include_test=False)
            validation_report = evaluation["evaluation_report"].get("VALIDATION")
            results.append({
                "seed": seed, "training_run_id": completed.training_run_id,
                "validation_accuracy": (validation_report or {}).get("accuracy"),
                "validation_balanced_accuracy": (validation_report or {}).get("balanced_accuracy"),
            })
        return results

    def train_offset_retaining_sensitivity(self, *, training_run_id: str, progress=None) -> dict[str, Any]:
        """Sensitivity closure (2026-08-12): the offset-retaining-v1
        preprocessing profile (base_preprocessing_registry.py) already
        existed as "the deliberate sensitivity-analysis counterpart to"
        the paper's real Eq.(6)-(7) offset compensation, but had zero real
        callers. Structurally identical to train_seed_variability_analysis
        above -- re-trains the EXACT SAME configuration (dataset/split/
        model_type/hyperparameters/representation/random_seed) of an
        already-completed run, varying ONLY base_preprocessing_profile_id
        -- never a new model selection, never a new threshold choice.
        VALIDATION-only (include_test=False), matching every other
        sensitivity diagnostic's own discipline: TEST is never opened for
        a sensitivity re-run."""
        base_run_dict = self.get_training_run(training_run_id)
        if base_run_dict is None:
            raise FileNotFoundError(f"TRAINING_RUN_NOT_FOUND:{training_run_id}")
        if base_run_dict["status"] != "COMPLETED":
            raise ValueError(f"CANNOT_RUN_OFFSET_RETAINING_SENSITIVITY_ON_AN_INCOMPLETE_TRAINING_RUN:{training_run_id}:{base_run_dict['status']}")
        base_run = TrainingRun.model_validate({k: v for k, v in base_run_dict.items() if k not in ("metrics", "label_classes", "error")})

        if progress:
            progress("OFFSET_RETAINING_SENSITIVITY", 0.0, f"Re-training {training_run_id} with offset-retaining-v1")
        variant_run = base_run.model_copy(update={
            "training_run_id": f"{training_run_id}-offset-retaining", "base_preprocessing_profile_id": "offset-retaining-v1",
            "status": "QUEUED", "started_at": None, "completed_at": None,
            "analysis_contract_protocol_id": None, "analysis_contract_protocol_version": None, "analysis_contract_hash": None,
        })
        completed = self.run_training(training_run=variant_run)
        # include_test=False here is load-bearing, not a default left alone
        # -- a sensitivity run must never open TEST.
        evaluation = self.evaluate_training_run(completed.training_run_id, include_test=False)
        validation_report = evaluation["evaluation_report"].get("VALIDATION")
        return {
            "training_run_id": completed.training_run_id, "base_run_training_run_id": training_run_id,
            "base_preprocessing_profile_id": "offset-retaining-v1",
            "validation_accuracy": (validation_report or {}).get("accuracy"),
            "validation_balanced_accuracy": (validation_report or {}).get("balanced_accuracy"),
            # A real, single scalar operating-point "coverage" is not
            # available from this VALIDATION-accuracy evaluation path (it
            # never applies the calibrated acceptance_threshold/abstention
            # rule -- that only happens in the decision-window inference
            # path, see coverage_analysis.py) -- reported honestly as None,
            # never approximated from the risk_coverage curve below.
            "coverage": None,
            "validation_risk_coverage": (validation_report or {}).get("risk_coverage"),
        }

    def train_region_specific_variant(self, *, training_run_id: str, analytical_region: str, progress=None) -> dict[str, Any]:
        """RQ4 region-specific fitting (2026-08-12): rq4_primary_analysis=
        REGION_SPECIFIC_FITTING_AND_EVALUATION (recorded via
        record_scientist_decision). Re-fits the EXACT SAME frozen
        configuration (dataset/split/model_type/hyperparameters/
        representation/random_seed) of an already-completed training run
        -- structurally identical to train_offset_retaining_sensitivity
        above -- restricting BOTH the raw IQ source AND example eligibility
        to one analytical_region (ADVA_EXCLUDED/PRE_PDU) via
        packet_content.region_restricted_provider_and_eligible_ids. Never a
        new model selection, never a new hyperparameter search: this is one
        of the three realizations point 4 of the RQ4 closure describes, not
        a second training pipeline. FULL_BURST is deliberately NOT trained
        through this path -- FULL_BURST already IS the base run's own
        input, so the caller should reuse the base run's own bundle_id
        directly rather than risk a nondeterministic duplicate of the same
        configuration. VALIDATION-only (include_test=False), matching every
        other RQ4/sensitivity diagnostic: TEST is never opened for a
        region-specific re-fit. Exports a real bundle immediately
        (acceptance_criteria={}, the same non-blocking, informational-only
        value export_and_approve_all_candidates already uses) so the
        caller can score decision windows for this region via
        OfflineInferenceService -- this is what makes the region's own
        independently-calibrated acceptance_threshold
        (evaluate_training_run's calibrate_unknown_threshold call, VALIDATION-
        only) usable downstream, matching the SAME real per-run calibration
        mechanism every other bundle in this system already gets, with no
        new threshold policy invented for RQ4."""
        if analytical_region not in ("ADVA_EXCLUDED", "PRE_PDU"):
            raise ValueError(f"REGION_SPECIFIC_FITTING_ONLY_SUPPORTS_ADVA_EXCLUDED_OR_PRE_PDU:got {analytical_region}")
        base_run_dict = self.get_training_run(training_run_id)
        if base_run_dict is None:
            raise FileNotFoundError(f"TRAINING_RUN_NOT_FOUND:{training_run_id}")
        if base_run_dict["status"] != "COMPLETED":
            raise ValueError(f"CANNOT_RUN_REGION_SPECIFIC_FITTING_ON_AN_INCOMPLETE_TRAINING_RUN:{training_run_id}:{base_run_dict['status']}")
        base_run = TrainingRun.model_validate({k: v for k, v in base_run_dict.items() if k not in ("metrics", "label_classes", "error")})

        dataset = self._require_dataset(base_run.dataset_id, base_run.dataset_version)
        examples = self._dataset_examples(dataset)
        iq_paths = self.capture_iq_paths_for(dataset.captures)

        if progress:
            progress("REGION_SPECIFIC_FITTING", 0.0, f"Deriving {analytical_region} variants for {training_run_id}")
        from ..packet_content import region_restricted_provider_and_eligible_ids
        provider, eligible_ids = region_restricted_provider_and_eligible_ids(
            examples, analytical_region=analytical_region, legacy_capture_root=self.legacy_capture_root, capture_iq_paths=iq_paths,
        )
        if not eligible_ids:
            raise ValueError(f"NO_EXAMPLES_ELIGIBLE_FOR_ANALYTICAL_REGION:{analytical_region}")

        variant_run = base_run.model_copy(update={
            "training_run_id": f"{training_run_id}-region-{analytical_region.lower().replace('_', '-')}",
            "status": "QUEUED", "started_at": None, "completed_at": None,
            "analysis_contract_protocol_id": None, "analysis_contract_protocol_version": None, "analysis_contract_hash": None,
        })
        if progress:
            progress("REGION_SPECIFIC_FITTING", 0.2, f"Training {variant_run.training_run_id}")
        completed = self.run_training(training_run=variant_run, iq_window_provider=provider, eligible_example_ids=eligible_ids)
        if progress:
            progress("REGION_SPECIFIC_FITTING", 0.7, "Evaluating VALIDATION")
        evaluation = self.evaluate_training_run(completed.training_run_id, include_test=False)
        validation_report = evaluation["evaluation_report"].get("VALIDATION")

        bundle_id = f"{completed.training_run_id}-bundle"
        if progress:
            progress("REGION_SPECIFIC_FITTING", 0.85, f"Exporting bundle {bundle_id}")
        manifest, gate_reasons = self.export_bundle(
            training_run_id=completed.training_run_id, bundle_id=bundle_id, acceptance_criteria={},
            model_card_text=f"# {bundle_id}\nRQ4 region-specific variant ({analytical_region}) of base run {training_run_id}.",
        )
        if progress:
            progress("REGION_SPECIFIC_FITTING", 1.0, "Region-specific fitting completed")

        return {
            "training_run_id": completed.training_run_id, "base_run_training_run_id": training_run_id,
            "analytical_region": analytical_region, "bundle_id": bundle_id, "approval_status": manifest.approval_status,
            "gate_reasons": gate_reasons, "n_eligible_examples": len(eligible_ids),
            "validation_accuracy": (validation_report or {}).get("accuracy"),
            "validation_balanced_accuracy": (validation_report or {}).get("balanced_accuracy"),
        }

    def train_feature_subset_variant(
        self, *, training_run_id: str, feature_group: str, feature_indices: list[int], progress=None,
    ) -> dict[str, Any]:
        """Feature-group ablation (exploratory, 2026-08-24): re-fits the
        EXACT SAME frozen configuration (dataset/split/model_type/
        hyperparameters/representation/random_seed/base_preprocessing_profile_id)
        of an already-completed training run, restricting the engineered
        feature matrix to `feature_indices` (columns into FEATURE_NAMES).
        Structurally identical to train_region_specific_variant/
        train_offset_retaining_sensitivity above -- one of the same family
        of "re-fit the frozen config, restrict one input dimension" variants
        -- never a new model selection, never a new hyperparameter search,
        never a new TRAIN/VALIDATION population (the split itself is never
        filtered here, unlike the region-restricted variant -- every TRAIN/
        VALIDATION example still participates, just with fewer feature
        columns). VALIDATION-only (include_test=False): TEST is never opened
        for a feature-subset re-fit. Exports a real bundle immediately
        (acceptance_criteria={}, same non-blocking convention as the other
        exploratory variants) so downstream consumers can read a real,
        frozen artifact rather than an in-memory-only result."""
        feature_group_codes = {"POWER_AMPLITUDE_LEVEL": "power-amp", "REMAINING_SIX": "remaining6"}
        if feature_group not in feature_group_codes:
            raise ValueError(f"FEATURE_SUBSET_ABLATION_ONLY_SUPPORTS_POWER_AMPLITUDE_LEVEL_OR_REMAINING_SIX:got {feature_group}")
        base_run_dict = self.get_training_run(training_run_id)
        if base_run_dict is None:
            raise FileNotFoundError(f"TRAINING_RUN_NOT_FOUND:{training_run_id}")
        if base_run_dict["status"] != "COMPLETED":
            raise ValueError(f"CANNOT_RUN_FEATURE_SUBSET_ABLATION_ON_AN_INCOMPLETE_TRAINING_RUN:{training_run_id}:{base_run_dict['status']}")
        base_run = TrainingRun.model_validate({k: v for k, v in base_run_dict.items() if k not in ("metrics", "label_classes", "error")})
        if base_run.model_type != "random_forest":
            raise ValueError(f"FEATURE_SUBSET_ABLATION_ONLY_SUPPORTS_RANDOM_FOREST_TODAY:got {base_run.model_type}")

        # Short, deterministic run id (2026-08-24): the base run's own
        # training_run_id is already long; appending a further descriptive
        # suffix to it for BOTH the training-run directory AND the exported
        # bundle directory routinely exceeded Windows' 260-char MAX_PATH for
        # nested artifact filenames (confirmed by a real FileNotFoundError
        # during this exploratory ablation) -- so this variant's id is built
        # from only the base run's own short random suffix (its last
        # dash-separated segment, e.g. "a598bd"), never the full base id.
        base_short_suffix = training_run_id.rsplit("-", 1)[-1]
        variant_run = base_run.model_copy(update={
            "training_run_id": f"FEATGRP-{base_short_suffix}-{feature_group_codes[feature_group]}",
            "status": "QUEUED", "started_at": None, "completed_at": None,
            "analysis_contract_protocol_id": None, "analysis_contract_protocol_version": None, "analysis_contract_hash": None,
        })
        if progress:
            progress("FEATURE_SUBSET_ABLATION", 0.2, f"Training {variant_run.training_run_id}")
        completed = self.run_training(training_run=variant_run, feature_indices=feature_indices)
        if progress:
            progress("FEATURE_SUBSET_ABLATION", 0.7, "Evaluating VALIDATION")
        evaluation = self.evaluate_training_run(completed.training_run_id, include_test=False)
        validation_report = evaluation["evaluation_report"].get("VALIDATION")

        bundle_id = f"{completed.training_run_id}-bundle"
        if progress:
            progress("FEATURE_SUBSET_ABLATION", 0.85, f"Exporting bundle {bundle_id}")
        manifest, gate_reasons = self.export_bundle(
            training_run_id=completed.training_run_id, bundle_id=bundle_id, acceptance_criteria={},
            model_card_text=f"# {bundle_id}\nFeature-group ablation variant ({feature_group}) of base run {training_run_id}. DEVELOPMENT_EXPLORATORY.",
        )
        if progress:
            progress("FEATURE_SUBSET_ABLATION", 1.0, "Feature-subset ablation completed")

        return {
            "training_run_id": completed.training_run_id, "base_run_training_run_id": training_run_id,
            "feature_group": feature_group, "feature_indices": feature_indices, "bundle_id": bundle_id,
            "approval_status": manifest.approval_status, "gate_reasons": gate_reasons,
            "validation_accuracy": (validation_report or {}).get("accuracy"),
            "validation_balanced_accuracy": (validation_report or {}).get("balanced_accuracy"),
        }

    # ------------------------------------------------------------------
    # P0.3 correction (2026-08-08): connecting ble_scientific_results'
    # AnalysisContract freeze + hash-chained holdout access log to the
    # ONE moment that actually matters -- TEST being opened for a training
    # run. Deferred import: ble_scientific_results/module.py itself imports
    # StudioRepository from this package, so a module-level import here
    # would be circular (same reasoning documented in
    # scientific_results_job_manager.py). This never duplicates a second
    # training/split system -- ble_rffi_studio's own pipeline stays the one
    # real training engine; ble_scientific_results is used here purely for
    # its protocol-freeze and audit-log machinery.
    # ------------------------------------------------------------------

    def _scientific_results_repository(self):
        if self._scientific_results_repository_cache is None:
            from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository
            self._scientific_results_repository_cache = ScientificResultsRepository(
                self.root.parent / "scientific_reports" / "ble", ble_rffi_studio_root=self.root,
            )
        return self._scientific_results_repository_cache

    def _freeze_and_log_test_access(self, training_run: TrainingRun, *, reason: str) -> dict[str, Any]:
        """Called exactly once per training_run_id, the first time TEST is
        ever evaluated for it (see evaluate_training_run below). Freezes a
        real AnalysisContract capturing this run's actual frozen
        configuration (never a placeholder), then logs the TEST access
        against ble_scientific_results' real, hash-chained holdout access
        log -- the same mechanism the 2026-08 audit found fully real but
        completely unused. If a contract was already frozen for this exact
        training_run_id (re-evaluation after a restart, say), reuses it
        instead of minting a new version every time."""
        sci = self._scientific_results_repository()
        existing_protocol_id = training_run.analysis_contract_protocol_id
        if existing_protocol_id:
            contract = sci.get_protocol(existing_protocol_id, training_run.analysis_contract_protocol_version)
        else:
            contract = sci.freeze_protocol({
                "protocol_id": f"ble-rffi-studio-{training_run.training_run_id}",
                "project_id": training_run.project_id,
                "hardware_profile_id": "usrp-b200-ble-rffi-studio",
                "receiver_profile_hash": training_run.base_preprocessing_profile_id,
                "interpretation_matrix_hash": training_run.representation_profile_id,
                "device_population": {"scientific_task": training_run.scientific_task},
                "split_manifest_hash": training_run.split_manifest_sha256,
                "random_seeds": [training_run.random_seed],
                "model_branch_definitions": [{"model_type": training_run.model_type}],
            })
        contract_hash = contract.content_hash()
        sci.log_holdout_access(
            actor="ble_rffi_studio", process="StudioRepository.evaluate_training_run",
            access_type="OPEN_TEST", access_path=f"training_runs/{training_run.training_run_id}/predictions.json",
            resource_id=training_run.training_run_id, resource_hash=training_run.dataset_manifest_sha256,
            reason=reason, paper_run_id=None, analysis_contract_hash=contract_hash,
        )
        return {
            "analysis_contract_protocol_id": contract.protocol_id,
            "analysis_contract_protocol_version": contract.protocol_version,
            "analysis_contract_hash": contract_hash,
        }

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate_training_run(
        self, training_run_id: str, min_identified_precision: float = 0.9, include_test: bool = False,
        test_evaluation_provenance: str | None = None,
    ) -> dict[str, Any]:
        """Model-selection comparisons must never touch TEST (see
        prepare_and_train): include_test defaults to False so evaluating N
        candidates during selection reports TRAIN/VALIDATION only. TEST is
        evaluated by passing include_test=True -- by default that happens
        exactly once, for the single model already chosen via VALIDATION
        (test_evaluation_provenance defaults to SINGLE_SELECTION_GUARANTEE
        in that case). evaluate_training_run_on_test_opt_in() below is the
        ONLY other caller that ever passes include_test=True, always with
        test_evaluation_provenance="OPT_IN_MULTI_CANDIDATE_COMPARISON" --
        the provenance is persisted alongside the evaluation report so
        export_bundle() can carry it, permanently, onto the bundle manifest.
        """
        run_dir = self.training_dir / training_run_id
        predictions_path = run_dir / "predictions.json"
        label_classes_path = run_dir / "label_classes.json"
        if not predictions_path.is_file():
            raise FileNotFoundError(f"TRAINING_RUN_HAS_NO_PREDICTIONS_YET:{training_run_id}")
        predictions = read_json(predictions_path)
        label_classes = read_json(label_classes_path)["classes"]

        if include_test:
            # P0.3: TEST is being opened for this run -- freeze/reuse a real
            # AnalysisContract and log this access on ble_scientific_results'
            # real holdout audit chain before evaluating anything, never
            # after (a log entry written after the fact would not be an
            # access log). Runs once per training_run_id: re-evaluating an
            # already-TEST-opened run (e.g. after a service restart) reuses
            # the contract already on file rather than minting a new one.
            run_path = run_dir / "training_run.json"
            training_run = TrainingRun.model_validate(read_json(run_path))
            contract_ids = self._freeze_and_log_test_access(
                training_run, reason=test_evaluation_provenance or "SINGLE_SELECTION_GUARANTEE",
            )
            if training_run.analysis_contract_protocol_id != contract_ids["analysis_contract_protocol_id"]:
                write_json(run_path, training_run.model_copy(update=contract_ids).model_dump(mode="json"))

        splits_to_evaluate = predictions if include_test else {name: preds for name, preds in predictions.items() if name != "TEST"}
        reports = {name: self.evaluator.evaluate_split(name, preds, label_classes) for name, preds in splits_to_evaluate.items()}
        threshold = None
        if "VALIDATION" in predictions:
            threshold = self.evaluator.calibrate_unknown_threshold(predictions["VALIDATION"], label_classes, min_identified_precision=min_identified_precision)
        calibration = {"acceptance_threshold": threshold, "calibrated_on": "VALIDATION", "min_identified_precision": min_identified_precision}

        report_dict = {name: dataclasses.asdict(report) for name, report in reports.items()}
        if not include_test:
            # Never silently discard a TEST evaluation that already exists on
            # disk just because THIS call only asked to refresh VALIDATION --
            # a real, observed bug: the Benchmark panel's "Reverificar
            # (VALIDATION)" / bulk "Comparar" actions (deliberately
            # VALIDATION-only, meant for quick candidate re-scoring) were
            # silently wiping out the recommended model's real, once-only
            # TEST evaluation (or an opted-in candidate's) from
            # evaluation_report.json just by being clicked, even though
            # nothing about TEST was re-requested. The exported bundle's OWN
            # copy of evaluation_report.json is a frozen snapshot and was
            # never affected -- but the training run's live file, which the
            # Benchmark/Acceso Directo panels read from, was losing real data.
            existing_path = run_dir / "evaluation_report.json"
            if existing_path.is_file():
                existing_test = read_json(existing_path).get("TEST")
                if existing_test is not None:
                    report_dict["TEST"] = existing_test
        write_json(run_dir / "evaluation_report.json", report_dict)
        write_json(run_dir / "calibration.json", calibration)
        if include_test:
            write_json(run_dir / "evaluation_provenance.json", {"test_evaluation_provenance": test_evaluation_provenance or "SINGLE_SELECTION_GUARANTEE"})
        return {"evaluation_report": report_dict, "calibration": calibration}

    def evaluate_training_run_on_test_opt_in(self, training_run_id: str, *, acknowledge_multiple_comparison_risk: bool) -> dict[str, Any]:
        """Explicit, audited opt-in to evaluate a NON-recommended candidate
        against TEST anyway, so an operator can compare several exported
        models side by side in Live Monitor instead of only ever being able
        to trust the one automatically recommended from VALIDATION. This
        deliberately breaks the "TEST evaluated exactly once" guarantee
        prepare_and_train() otherwise enforces: comparing multiple
        candidates against the same held-out split means the choice of
        which one to trust is no longer purely VALIDATION-driven -- a real
        statistical caveat (multiple-comparison risk), not a formality.
        Every bundle exported from a training_run_id evaluated this way
        carries test_evaluation_provenance=OPT_IN_MULTI_CANDIDATE_COMPARISON
        permanently on its manifest, never silently indistinguishable from
        the single-selection guarantee.
        """
        if not acknowledge_multiple_comparison_risk:
            raise ValueError(
                "ACKNOWLEDGEMENT_REQUIRED: must explicitly confirm acknowledge_multiple_comparison_risk=true -- "
                "this evaluates a non-recommended candidate against the held-out TEST split, which breaks the "
                "single-comparison guarantee prepare_and_train() otherwise enforces for the recommended model."
            )
        run_dir = self.training_dir / training_run_id
        if not (run_dir / "training_run.json").is_file():
            raise FileNotFoundError(f"TRAINING_RUN_NOT_FOUND:{training_run_id}")
        return self.evaluate_training_run(
            training_run_id, min_identified_precision=0.9, include_test=True,
            test_evaluation_provenance="OPT_IN_MULTI_CANDIDATE_COMPARISON",
        )

    def get_evaluation(self, training_run_id: str) -> dict[str, Any] | None:
        run_dir = self.training_dir / training_run_id
        eval_path = run_dir / "evaluation_report.json"
        calibration_path = run_dir / "calibration.json"
        provenance_path = run_dir / "evaluation_provenance.json"
        if not eval_path.is_file():
            return None
        return {
            "evaluation_report": read_json(eval_path),
            "calibration": read_json(calibration_path) if calibration_path.is_file() else None,
            "test_evaluation_provenance": read_json(provenance_path)["test_evaluation_provenance"] if provenance_path.is_file() else "NOT_EVALUATED",
        }

    # ------------------------------------------------------------------
    # Guided orchestration: "Prepare dataset and train"
    #
    # Chains evidence -> dataset -> quality gate -> split -> every feasible
    # candidate model -> evaluation -> comparison, stopping cleanly (with a
    # human explanation) the moment a real gate fails, instead of pushing an
    # operator through nine manual button presses. Nothing here bypasses any
    # gate; it only calls the same stage methods above in sequence.
    # ------------------------------------------------------------------

    PHASE_LABELS = [
        "Analizando capturas",
        "Construyendo ejemplos de evidencia",
        "Revisando el dataset",
        "Creando particiones",
        "Entrenando modelos candidatos",
        "Validando modelos",
        "Calibrando deteccion de desconocidos",
        "Comparando modelos",
        "Preparando resumen para exportacion",
    ]

    def prepare_and_train(
        self,
        *,
        capture_ids: list[str],
        project_id: str,
        campaign_id: str,
        scientific_task: str,
        ble_channel: int = 37,
        dataset_id: str | None = None,
        dataset_version: str = "1.0.0",
        speed_profile: str = "normal",
        target_physical_unit_ids: set[str] | None = None,
        progress=None,
    ) -> dict[str, Any]:
        total = len(self.PHASE_LABELS)

        def report(index: int, detail: str = "") -> None:
            if progress:
                message = f"{index}/{total} {self.PHASE_LABELS[index - 1]}" + (f": {detail}" if detail else "")
                progress(f"PHASE_{index}", (index - 1) / total, message)

        dataset_id = dataset_id or f"{project_id}-AUTO-DS"

        report(1, f"{len(capture_ids)} captura(s)")
        captures = []
        for capture_id in capture_ids:
            capture = self.get_capture(capture_id)
            if capture is None:
                raise FileNotFoundError(f"CAPTURE_NOT_BUILT_YET:{capture_id}")
            captures.append(capture)

        report(2)
        for capture in captures:
            if not self.has_evidence(capture.capture_id):
                self.build_evidence(capture=capture, project_id=project_id, ble_channel=ble_channel)

        report(3)
        build_result = self.build_dataset(
            dataset_id=dataset_id, dataset_version=dataset_version, project_id=project_id, campaign_id=campaign_id,
            capture_ids=capture_ids, target_physical_unit_ids=target_physical_unit_ids,
        )
        dataset = build_result["dataset"]
        quality = self.build_quality_report(dataset_id=dataset_id, dataset_version=dataset_version)
        if quality.gate_decision == "NOT_ACCEPTED_FOR_TRAINING":
            return {
                "stopped_at": "quality_gate",
                "stopped_reason": "El dataset no supero el control de calidad: " + "; ".join(quality.gate_reasons),
                "dataset": dataset, "quality_report": quality, "split": None, "feasibility": None,
                "trained_models": [], "skipped_models": [], "recommended_training_run_id": None, "recommended_reason": None,
            }

        report(4)
        examples = self._dataset_examples(dataset)
        feasibility = explain_feasibility(examples, scientific_task)
        split = self.build_split(dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=scientific_task)
        if split.split_status != "READY":
            return {
                "stopped_at": "split", "stopped_reason": feasibility["human_summary"],
                "dataset": dataset, "quality_report": quality, "split": split, "feasibility": feasibility,
                "trained_models": [], "skipped_models": [], "recommended_training_run_id": None, "recommended_reason": None,
            }

        candidate_types = list(_QUICK_PILOT_MODEL_TYPES if speed_profile == "quick_pilot" else _NORMAL_MODEL_TYPES)
        cnn_ok, cnn_reason = cnn_feasibility([a.model_dump(mode="json") for a in split.assignments])
        skipped_models: list[dict[str, str]] = []
        if not cnn_ok:
            for cnn_type in ("cnn1d", "cnn2d"):
                if cnn_type in candidate_types:
                    candidate_types.remove(cnn_type)
                    skipped_models.append({"model_type": cnn_type, "reason": cnn_reason})

        representation_by_model = {
            "logistic_regression": "feature_vector-v1", "svm_rbf": "feature_vector-v1", "random_forest": "feature_vector-v1",
            "cnn1d": "raw_iq-v1", "cnn2d": "spectrogram-v1", "frozen_morphological_baseline": "morphological_coarse_tf-v1",
        }

        report(5, f"{len(candidate_types)} candidato(s): {', '.join(candidate_types)}")
        trained_run_ids = []
        for model_type in candidate_types:
            training_run_id = f"AUTO-{model_type}-{uuid.uuid4().hex[:10]}"
            training_run = TrainingRun(
                training_run_id=training_run_id, project_id=project_id, campaign_id=campaign_id,
                dataset_id=dataset_id, dataset_version=dataset_version, dataset_manifest_sha256=dataset.dataset_manifest_sha256 or "",
                split_manifest_sha256=split.split_manifest_sha256 or "", scientific_task=scientific_task, model_type=model_type,
                data_origin=dataset.data_origin, operational_use="FORBIDDEN" if dataset.data_origin == "SYNTHETIC_TEST_ONLY" else "ALLOWED",
                base_preprocessing_profile_id="base-v1", representation_profile_id=representation_by_model[model_type], random_seed=FROZEN_TRAINING_SEEDS[0],
            )
            try:
                completed = self.run_training(training_run=training_run)
                trained_run_ids.append(completed.training_run_id)
            except Exception as error:
                skipped_models.append({"model_type": model_type, "reason": f"{type(error).__name__}: {error}"})

        report(6, f"{len(trained_run_ids)} modelo(s) entrenado(s)")
        report(7)
        # VALIDATION only -- include_test=False means TEST is not even read
        # here, let alone used to score or compare candidates.
        scored = []
        for training_run_id in trained_run_ids:
            evaluation = self.evaluate_training_run(training_run_id, min_identified_precision=0.9, include_test=False)
            run_dir = self.training_dir / training_run_id
            latency_path = run_dir / "latency.json"
            latency_ms = read_json(latency_path).get("validation_latency_ms") if latency_path.is_file() else None
            run_info = read_json(run_dir / "training_run.json")
            size_bytes = model_file_size_bytes(run_dir, run_info["model_type"])
            score = score_model(evaluation["evaluation_report"], evaluation["calibration"], latency_ms or 0.0, size_bytes)
            scored.append({"training_run_id": training_run_id, "model_type": run_info["model_type"], "evaluation": evaluation, "score": score})

        report(8)
        accepted = [s for s in scored if self._meets_acceptance_criteria(s["score"])]
        if not accepted:
            report(9)
            return {
                "stopped_at": "model_selection",
                "stopped_reason": (
                    "NO_MODEL_ACCEPTED: ninguno de los "
                    f"{len(scored)} modelo(s) candidato(s) alcanzo el criterio minimo de aceptacion en VALIDATION "
                    f"(macro_f1 >= {ACCEPTANCE_MIN_MACRO_F1}, balanced_accuracy >= {ACCEPTANCE_MIN_BALANCED_ACCURACY}). "
                    "No se exporta automaticamente el modelo menos malo."
                ) if scored else "Ningun modelo completo el entrenamiento.",
                "dataset": dataset, "quality_report": quality, "split": split, "feasibility": feasibility,
                "trained_models": scored, "skipped_models": skipped_models,
                "recommended_training_run_id": None, "recommended_reason": None, "final_test_evaluation": None,
            }

        # Selection is frozen the moment we pick `recommended`: model type,
        # hyperparameters, preprocessing and (via its calibration.json)
        # UNKNOWN threshold are all already on disk for this training_run_id.
        # TEST is evaluated exactly once, only now, only for this one model.
        recommended = max(accepted, key=lambda s: s["score"]["composite_score"])
        final_evaluation = self.evaluate_training_run(recommended["training_run_id"], min_identified_precision=0.9, include_test=True)
        recommended["evaluation"] = final_evaluation

        report(9)
        return {
            "stopped_at": None, "dataset": dataset, "quality_report": quality, "split": split, "feasibility": feasibility,
            "trained_models": scored, "skipped_models": skipped_models,
            "recommended_training_run_id": recommended["training_run_id"],
            "recommended_reason": self._recommendation_reason(recommended, scored),
            "final_test_evaluation": final_evaluation["evaluation_report"].get("TEST"),
        }

    _TRAIN_SELECTED_PHASE_LABELS = [
        "Revisando el dataset",
        "Creando particiones",
        "Entrenando modelos seleccionados",
        "Validando modelos",
        "Comparando modelos",
        "Preparando resumen para exportacion",
    ]

    def train_selected_models(
        self, *, dataset_id: str, dataset_version: str, model_types: list[str],
        scientific_task: str = "TARGET_VS_BACKGROUND", progress=None,
    ) -> dict[str, Any]:
        """Trains an operator-chosen subset of model_type candidates against
        an ALREADY-frozen, already-labeled dataset -- never builds a new one,
        never touches capture_ids. Reuses every real gate/algorithm
        prepare_and_train() uses (build_quality_report, build_split,
        cnn_feasibility, run_training, evaluate_training_run, score_model,
        _meets_acceptance_criteria, _recommendation_reason); only the
        orchestration shell is separate, deliberately -- prepare_and_train()
        is already relied on by three real flows (guided manual, auto-train,
        device scrubbing) and sharing this thin a wrapper was not worth the
        regression risk of restructuring it.

        scientific_task defaults to TARGET_VS_BACKGROUND (every single-device
        dataset in this project was built for it); the Training Service
        passes SAME_MODEL_UNIT_IDENTIFICATION instead when the operator
        combined 2+ datasets via combine_datasets_for_identification() --
        multi-class, "which of these devices", never a binary family.

        Generates run_name (date + time + the dataset's own physical_units,
        e.g. "TRAIN-20260803-143022-SHELLY-PLUG-01") used as every resulting
        TrainingRun's campaign_id and training_run_id prefix -- how the "que
        dispositivos y modelos se usaron" catalog groups its rows, with zero
        extra bookkeeping.

        Returns the exact same dict shape prepare_and_train() returns (plus
        run_name), so export_and_approve_all_candidates() and every UI
        renderer already built for that shape work here unchanged."""
        labels = self._TRAIN_SELECTED_PHASE_LABELS
        total = len(labels)

        def report(index: int, detail: str = "") -> None:
            if progress:
                message = f"{index}/{total} {labels[index - 1]}" + (f": {detail}" if detail else "")
                progress(f"PHASE_{index}", (index - 1) / total, message)

        dataset = self._require_dataset(dataset_id, dataset_version)
        project_id = dataset.project_id
        run_name = f"TRAIN-{utc_now().replace('-', '').replace(':', '')[:15]}-{_device_slug(dataset.physical_units)}"

        report(1)
        quality = self.get_quality_report(dataset_id, dataset_version) or self.build_quality_report(dataset_id=dataset_id, dataset_version=dataset_version)
        if quality.gate_decision == "NOT_ACCEPTED_FOR_TRAINING":
            return {
                "stopped_at": "quality_gate",
                "stopped_reason": "El dataset no supero el control de calidad: " + "; ".join(quality.gate_reasons),
                "dataset": dataset, "quality_report": quality, "split": None, "feasibility": None,
                "trained_models": [], "skipped_models": [], "recommended_training_run_id": None, "recommended_reason": None,
                "run_name": run_name,
            }

        report(2)
        # Reusing the already-built split when present avoids recomputing it
        # needlessly (idempotent either way).
        examples = self._dataset_examples(dataset)
        feasibility = explain_feasibility(examples, scientific_task)
        split = self.get_split(dataset_id, dataset_version, scientific_task) or self.build_split(
            dataset_id=dataset_id, dataset_version=dataset_version, scientific_task=scientific_task,
        )
        if split.split_status != "READY":
            return {
                "stopped_at": "split", "stopped_reason": feasibility["human_summary"],
                "dataset": dataset, "quality_report": quality, "split": split, "feasibility": feasibility,
                "trained_models": [], "skipped_models": [], "recommended_training_run_id": None, "recommended_reason": None,
                "run_name": run_name,
            }

        candidate_types = list(dict.fromkeys(model_types))
        cnn_ok, cnn_reason = cnn_feasibility([a.model_dump(mode="json") for a in split.assignments])
        skipped_models: list[dict[str, str]] = []
        if not cnn_ok:
            for cnn_type in ("cnn1d", "cnn2d"):
                if cnn_type in candidate_types:
                    candidate_types.remove(cnn_type)
                    skipped_models.append({"model_type": cnn_type, "reason": cnn_reason})

        representation_by_model = {
            "logistic_regression": "feature_vector-v1", "svm_rbf": "feature_vector-v1", "random_forest": "feature_vector-v1",
            "cnn1d": "raw_iq-v1", "cnn2d": "spectrogram-v1", "frozen_morphological_baseline": "morphological_coarse_tf-v1",
        }

        report(3, f"{len(candidate_types)} candidato(s): {', '.join(candidate_types)}")
        trained_run_ids = []
        for model_type in candidate_types:
            training_run_id = f"{run_name}-{model_type}-{uuid.uuid4().hex[:6]}"
            training_run = TrainingRun(
                training_run_id=training_run_id, project_id=project_id, campaign_id=run_name,
                dataset_id=dataset_id, dataset_version=dataset_version, dataset_manifest_sha256=dataset.dataset_manifest_sha256 or "",
                split_manifest_sha256=split.split_manifest_sha256 or "", scientific_task=scientific_task, model_type=model_type,
                data_origin=dataset.data_origin, operational_use="FORBIDDEN" if dataset.data_origin == "SYNTHETIC_TEST_ONLY" else "ALLOWED",
                base_preprocessing_profile_id="base-v1", representation_profile_id=representation_by_model[model_type], random_seed=FROZEN_TRAINING_SEEDS[0],
            )
            try:
                completed = self.run_training(training_run=training_run)
                trained_run_ids.append(completed.training_run_id)
            except Exception as error:
                skipped_models.append({"model_type": model_type, "reason": f"{type(error).__name__}: {error}"})

        report(4, f"{len(trained_run_ids)} modelo(s) entrenado(s)")
        scored = []
        for training_run_id in trained_run_ids:
            evaluation = self.evaluate_training_run(training_run_id, min_identified_precision=0.9, include_test=False)
            run_dir = self.training_dir / training_run_id
            latency_path = run_dir / "latency.json"
            latency_ms = read_json(latency_path).get("validation_latency_ms") if latency_path.is_file() else None
            run_info = read_json(run_dir / "training_run.json")
            size_bytes = model_file_size_bytes(run_dir, run_info["model_type"])
            score = score_model(evaluation["evaluation_report"], evaluation["calibration"], latency_ms or 0.0, size_bytes)
            scored.append({"training_run_id": training_run_id, "model_type": run_info["model_type"], "evaluation": evaluation, "score": score})

        report(5)
        accepted = [s for s in scored if self._meets_acceptance_criteria(s["score"])]
        if not accepted:
            report(6)
            return {
                "stopped_at": "model_selection",
                "stopped_reason": (
                    "NO_MODEL_ACCEPTED: ninguno de los "
                    f"{len(scored)} modelo(s) candidato(s) alcanzo el criterio minimo de aceptacion en VALIDATION "
                    f"(macro_f1 >= {ACCEPTANCE_MIN_MACRO_F1}, balanced_accuracy >= {ACCEPTANCE_MIN_BALANCED_ACCURACY}). "
                    "No se exporta automaticamente el modelo menos malo."
                ) if scored else "Ningun modelo completo el entrenamiento.",
                "dataset": dataset, "quality_report": quality, "split": split, "feasibility": feasibility,
                "trained_models": scored, "skipped_models": skipped_models,
                "recommended_training_run_id": None, "recommended_reason": None, "final_test_evaluation": None,
                "run_name": run_name,
            }

        recommended = max(accepted, key=lambda s: s["score"]["composite_score"])
        final_evaluation = self.evaluate_training_run(recommended["training_run_id"], min_identified_precision=0.9, include_test=True)
        recommended["evaluation"] = final_evaluation

        report(6)
        return {
            "stopped_at": None, "dataset": dataset, "quality_report": quality, "split": split, "feasibility": feasibility,
            "trained_models": scored, "skipped_models": skipped_models,
            "recommended_training_run_id": recommended["training_run_id"],
            "recommended_reason": self._recommendation_reason(recommended, scored),
            "final_test_evaluation": final_evaluation["evaluation_report"].get("TEST"),
            "run_name": run_name,
        }

    def _meets_acceptance_criteria(self, score: dict[str, Any]) -> bool:
        return score["macro_f1"] >= ACCEPTANCE_MIN_MACRO_F1 and score["balanced_accuracy_proxy"] >= ACCEPTANCE_MIN_BALANCED_ACCURACY

    def _recommendation_reason(self, recommended: dict[str, Any], scored: list[dict[str, Any]]) -> str:
        others = [s for s in scored if s is not recommended]
        parts = [f"mejor puntuacion compuesta en VALIDATION ({recommended['score']['composite_score']:.3f})"]
        if others and all(recommended["score"]["unknown_capability_penalty"] <= o["score"]["unknown_capability_penalty"] for o in others):
            parts.append("mejor o igual capacidad de deteccion de desconocidos")
        parts.append(f"latencia {recommended['score']['latency_ms']:.2f} ms por ejemplo")
        return "; ".join(parts)

    def scientific_task_display_names(self) -> dict[str, str]:
        return dict(TASK_DISPLAY_NAMES)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_bundle(self, *, training_run_id: str, bundle_id: str, acceptance_criteria: dict[str, Any], model_card_text: str) -> tuple[ModelBundleManifest, list[str]]:
        run_dir = self.training_dir / training_run_id
        run_path = run_dir / "training_run.json"
        if not run_path.is_file():
            raise FileNotFoundError(f"TRAINING_RUN_NOT_FOUND:{training_run_id}")
        evaluation = self.get_evaluation(training_run_id)
        if evaluation is None:
            raise FileNotFoundError(f"TRAINING_RUN_NOT_EVALUATED_YET:{training_run_id}")

        training_run = TrainingRun.model_validate(read_json(run_path))
        dataset = self._require_dataset(training_run.dataset_id, training_run.dataset_version)
        split = self.get_split(training_run.dataset_id, training_run.dataset_version, training_run.scientific_task)
        if split is None:
            raise FileNotFoundError("SPLIT_NOT_FOUND_FOR_THIS_TRAINING_RUN")

        model = torch.load(run_dir / "model.pt", weights_only=False) if training_run.model_type in _TORCH_MODEL_TYPES else joblib.load(run_dir / "model.joblib")
        scaler_path = run_dir / "scaler.joblib"
        scaler = joblib.load(scaler_path) if scaler_path.is_file() else None
        label_classes = read_json(run_dir / "label_classes.json")["classes"]
        feature_names = read_json(run_dir / "feature_names.json")["names"]

        from ..evaluation import SplitEvaluationReport
        evaluation_reports = {name: SplitEvaluationReport(**data) for name, data in evaluation["evaluation_report"].items()}

        manifest, reasons = self.bundle_builder.build(
            bundle_id=bundle_id, training_run=training_run, model=model, label_classes=label_classes,
            feature_names=feature_names, scaler=scaler, dataset=dataset, split=split,
            evaluation_reports=evaluation_reports, calibration=evaluation["calibration"], acceptance_criteria=acceptance_criteria,
            model_card_text=model_card_text, code_reference={"module": "app.modules.ble_rffi_studio", "training_run_id": training_run_id},
            test_evaluation_provenance=evaluation["test_evaluation_provenance"],
            created_at=utc_now(),
        )
        return manifest, reasons

    def export_and_approve_all_candidates(self, *, physical_unit_id: str, prepare_and_train_result: dict[str, Any]) -> list[dict[str, Any]]:
        """auto_train()'s full-automation step. P0 correction (2026-08-08):
        this used to call evaluate_training_run_on_test_opt_in for every
        NON-recommended candidate and then auto-approve it -- meaning
        "normal", fully-automated approval silently exposed every candidate
        to TEST, not just the one VALIDATION recommended. TEST must open
        exactly once, for the confirmatory model only.

        Now: every candidate is still exported (real, inspectable record of
        what was tried, VALIDATION-only evaluation), but ONLY the
        recommended candidate -- which already carries a real TEST
        evaluation with SINGLE_SELECTION_GUARANTEE provenance from
        prepare_and_train()/train_selected_models() itself -- is ever
        auto-approved. Every other candidate lands at TEST_NOT_EXECUTED
        (bundle_builder._evaluate_acceptance) and stays there; nothing here
        calls evaluate_training_run_on_test_opt_in anymore. An operator who
        deliberately wants to compare a non-recommended candidate against
        TEST can still do so, but only via that endpoint directly, as an
        explicit, separate, acknowledged action -- and the resulting bundle
        can never reach APPROVED_FOR_LIVE_PILOT
        (bundle_builder.approve_for_live_pilot refuses non-confirmatory_eligible
        bundles). A candidate that fails its own acceptance_criteria
        (REJECTED) or was never evaluated (TRAINING_RUN_FAILED, no
        predictions.json) is reported as such, not silently skipped or
        force-approved.
        """
        recommended_id = prepare_and_train_result.get("recommended_training_run_id")
        trained_models = prepare_and_train_result.get("trained_models") or []
        slug = physical_unit_id.replace(" ", "")
        results: list[dict[str, Any]] = []
        for candidate in trained_models:
            training_run_id = candidate["training_run_id"]
            model_type = candidate["model_type"]
            bundle_id = f"{slug}-{model_type}-bundle"
            entry: dict[str, Any] = {"training_run_id": training_run_id, "model_type": model_type, "bundle_id": bundle_id}
            try:
                manifest, gate_reasons = self.export_bundle(
                    training_run_id=training_run_id, bundle_id=bundle_id, acceptance_criteria={},
                    model_card_text=f"# {bundle_id}\nExportado automaticamente por auto-train para {physical_unit_id}.",
                )
                entry["gate_reasons"] = gate_reasons
                if training_run_id == recommended_id and manifest.approval_status == "EVALUATED":
                    manifest = self.approve_bundle(bundle_id)
                entry["approval_status"] = manifest.approval_status
            except Exception as error:
                entry["approval_status"] = None
                entry["error"] = f"{type(error).__name__}: {error}"
            results.append(entry)
        return results

    def list_bundles(self) -> list[ModelBundleManifest]:
        return [ModelBundleManifest.model_validate(read_json(p)) for p in sorted(self.bundle_builder.root.glob("*/bundle_manifest.json"))]

    def get_bundle(self, bundle_id: str) -> ModelBundleManifest | None:
        return self.bundle_builder.load_manifest(bundle_id)

    def delete_bundle(self, bundle_id: str) -> dict[str, Any]:
        """Deletes an exported model bundle -- the deployable artifact Live
        Monitor's model selector lists. Never touches the TrainingRun/dataset
        it was exported from, so `retrain_reference_from_training_run` can
        still rebuild an identical bundle from the same data. If this bundle
        was APPROVED_FOR_LIVE_PILOT and currently active in Live Monitor,
        the live-check keeps running against its already-loaded in-memory
        copy until disabled -- deleting the bundle does not reach into a live
        session."""
        if not bundle_id or any(part in bundle_id for part in ("/", "\\", "..")):
            raise ValueError(f"INVALID_BUNDLE_ID:{bundle_id}")
        bundle_dir = self.bundle_builder.root / bundle_id
        if bundle_dir.resolve().parent != self.bundle_builder.root.resolve() or not bundle_dir.is_dir():
            raise FileNotFoundError(f"BUNDLE_NOT_FOUND:{bundle_id}")
        shutil.rmtree(bundle_dir)
        return {"deleted": True, "bundle_id": bundle_id}

    def delete_training_run(self, training_run_id: str) -> dict[str, Any]:
        """Deletes a TrainingRun's fitted artifact + evaluation history.
        Does NOT check whether an exported bundle still references it --
        exported bundles keep their own copy of every artifact (model file,
        preprocessing config, evaluation report) inside the bundle directory,
        so they stay fully usable even after their source TrainingRun is
        gone; only `retrain_reference_from_training_run` for THIS specific
        run stops working."""
        if not training_run_id or any(part in training_run_id for part in ("/", "\\", "..")):
            raise ValueError(f"INVALID_TRAINING_RUN_ID:{training_run_id}")
        run_dir = self.training_dir / training_run_id
        if run_dir.resolve().parent != self.training_dir.resolve() or not run_dir.is_dir():
            raise FileNotFoundError(f"TRAINING_RUN_NOT_FOUND:{training_run_id}")
        shutil.rmtree(run_dir)
        return {"deleted": True, "training_run_id": training_run_id}

    def retrain_reference(self, bundle_id: str) -> dict[str, Any]:
        """Resolves everything /prepare-and-train needs to redo this bundle's
        training run, for the Live Monitor "Reentrenar" button -- reuses that
        EXACT existing endpoint/job, no separate retrain pipeline. capture_ids
        is every capture currently registered under the bundle's own
        project_id (not just the frozen dataset's original list), so any
        REAL session the operator captured since this bundle was trained
        (e.g. after a failed live detectability check told them to record
        more) is automatically picked up -- prepare_and_train's own quality
        gates decide what is actually usable, same as the Guided flow."""
        manifest = self.get_bundle(bundle_id)
        if manifest is None:
            raise FileNotFoundError(f"BUNDLE_NOT_FOUND:{bundle_id}")
        run_path = self.training_dir / manifest.training_run_id / "training_run.json"
        if not run_path.is_file():
            raise FileNotFoundError(f"TRAINING_RUN_NOT_FOUND:{manifest.training_run_id}")
        training_run = TrainingRun.model_validate(read_json(run_path))
        acquisition = self.resolve_bundle_acquisition_reference(bundle_id)
        capture_ids = [c.capture_id for c in self.list_captures() if c.project_id == training_run.project_id]
        return {
            "project_id": training_run.project_id,
            "campaign_id": training_run.campaign_id,
            "scientific_task": training_run.scientific_task,
            "ble_channel": acquisition.get("ble_channel") or 37,
            "capture_ids": capture_ids,
        }

    def retrain_reference_from_training_run(self, training_run_id: str) -> dict[str, Any]:
        """Same idea as retrain_reference() above, but starting from a
        training_run_id directly instead of requiring an exported bundle --
        for the Benchmark panel's "Reentrenar (mismas capturas)" action,
        which must work for a candidate that was never exported at all, not
        only for one that already has a bundle. Resolves ble_channel from
        the training run's OWN frozen dataset (its first capture) rather
        than a bundle's dataset_reference.json. Real request: "poder
        entrenar y lanzar un reentreno de nuevo... sin tener que pasar por
        etapas anteriores" -- capture_ids is every capture currently
        registered under the run's project_id (not just the original frozen
        dataset's list), so anything captured since is picked up too,
        exactly like retrain_reference()."""
        run_path = self.training_dir / training_run_id / "training_run.json"
        if not run_path.is_file():
            raise FileNotFoundError(f"TRAINING_RUN_NOT_FOUND:{training_run_id}")
        training_run = TrainingRun.model_validate(read_json(run_path))
        dataset = self.get_dataset(training_run.dataset_id, training_run.dataset_version)
        ble_channel = None
        if dataset is not None:
            for capture_id in dataset.captures:
                capture = self.get_capture(capture_id)
                if capture is not None:
                    ble_channel = self._resolve_ble_channel(capture.center_frequency_hz)
                    if ble_channel is not None:
                        break
        capture_ids = [c.capture_id for c in self.list_captures() if c.project_id == training_run.project_id]
        return {
            "project_id": training_run.project_id,
            "campaign_id": training_run.campaign_id,
            "scientific_task": training_run.scientific_task,
            "ble_channel": ble_channel or 37,
            "capture_ids": capture_ids,
        }

    def approve_bundle(self, bundle_id: str) -> ModelBundleManifest:
        manifest = self.bundle_builder.load_manifest(bundle_id)
        if manifest is None:
            raise FileNotFoundError(f"BUNDLE_NOT_FOUND:{bundle_id}")
        return self.bundle_builder.approve_for_live_pilot(manifest)

    # ------------------------------------------------------------------
    # Offline inference
    # ------------------------------------------------------------------

    def run_inference(self, *, bundle_id: str, capture_id: str) -> list[dict[str, Any]]:
        examples = self.list_examples(capture_id)
        if not examples:
            raise FileNotFoundError(f"NO_EVIDENCE_BUILT_YET_FOR_CAPTURE:{capture_id}")
        iq_paths = self.capture_iq_paths_for([capture_id])
        service = OfflineInferenceService(self.bundle_builder.root, iq_paths)
        # Inference-provenance correction (2026-08-08): every real offline
        # inference run is now bound, on disk, to the exact bundle content
        # hash and source IQ hash that produced it -- see
        # OfflineInferenceService.run_with_provenance and the audit's own
        # "provenance chain terminates at the model" finding. The public
        # return shape (a bare list of decisions) is unchanged -- every
        # existing caller keeps working exactly as before.
        capture = self.get_capture(capture_id)
        capture_iq_sha256_by_id = {capture_id: capture.iq_sha256} if capture is not None else {}
        inference_run_id = f"INFER-{bundle_id}-{capture_id}-{uuid.uuid4().hex[:10]}"
        manifest = service.run_with_provenance(
            bundle_id=bundle_id, examples=examples, inference_run_id=inference_run_id, capture_iq_sha256_by_id=capture_iq_sha256_by_id,
        )
        write_json(self.inference_dir / f"{inference_run_id}.json", manifest)
        return manifest["decisions"]

    def get_inference_run(self, inference_run_id: str) -> dict[str, Any] | None:
        path = self.inference_dir / f"{inference_run_id}.json"
        return read_json(path) if path.is_file() else None

    def list_inference_runs(self) -> list[dict[str, Any]]:
        return [read_json(p) for p in sorted(self.inference_dir.glob("*.json"))]

    # ------------------------------------------------------------------
    # Live Monitor: on-demand model check over a freshly-captured IQ burst
    # (never touches dataset/evidence/training -- see inference/offline_inference.py's
    # run_live() docstring for why this is a deliberately separate, minimal path).
    # ------------------------------------------------------------------

    def list_live_selectable_bundles(self) -> list[dict[str, Any]]:
        """One entry per bundle the operator can ACTUALLY activate right now --
        never a "not approved" or "broken reference" placeholder. Only
        APPROVED_FOR_LIVE_PILOT bundles whose training-time acquisition
        reference still resolves are included; everything else (draft,
        rejected, evaluated-but-not-approved, or missing its reference
        capture) is silently excluded rather than shown as a disabled row --
        a real operator has no use for a list of models that don't work.

        Grouped by physical_unit (device) on the frontend, using
        dataset_reference.json's own physical_units -- the actual device(s)
        this model was trained to recognize, not the raw label strings
        (which for TARGET_VS_BACKGROUND are TARGET_DEVICE/BACKGROUND_ENVIRONMENT,
        meaningless to an operator without knowing WHICH device was the target)."""
        result = []
        for manifest in self.list_bundles():
            if manifest.approval_status != "APPROVED_FOR_LIVE_PILOT":
                continue
            bundle_dir = self.bundle_builder.root / manifest.bundle_id
            try:
                acquisition = self.resolve_bundle_acquisition_reference(manifest.bundle_id)
            except Exception:
                continue
            label_map = read_json(bundle_dir / "label_map.json")
            model_manifest = read_json(bundle_dir / "model_manifest.json")
            dataset_reference = read_json(bundle_dir / "dataset_reference.json")
            split_reference = read_json(bundle_dir / "split_reference.json")
            task = split_reference.get("scientific_task")
            result.append({
                "bundle_id": manifest.bundle_id,
                "physical_units": dataset_reference.get("physical_units") or [],
                "task": task,
                "task_display": TASK_DISPLAY_NAMES.get(task, task),
                "model_type": model_manifest.get("model_type"),
                "label_classes": label_map.get("classes", []),
                "acquisition_reference": acquisition,
                "reliability": self._bundle_reliability_summary(manifest.bundle_id, task),
            })
        return result

    def _bundle_reliability_summary(self, bundle_id: str, task: str | None) -> dict[str, Any] | None:
        """Real TEST-split false-positive rate for this bundle, surfaced so an
        operator can see it in the model picker instead of discovering it live.
        Only meaningful for TARGET_VS_BACKGROUND (BACKGROUND_ENVIRONMENT recall
        IS "how often the model correctly says the device is absent" -- for
        other scientific_task label sets there is no single "false alarm"
        class, so this deliberately returns None rather than guessing).
        Real case this exists for: keyfobdemo01's non-recommended candidates
        (logistic_regression/svm_rbf/cnn1d) say TARGET_DEVICE present 70-92%
        of the time even when the TEST examples were genuinely background."""
        if task != "TARGET_VS_BACKGROUND":
            return None
        report_path = self.bundle_builder.root / bundle_id / "evaluation_report.json"
        if not report_path.is_file():
            return None
        test = read_json(report_path).get("TEST") or {}
        recall = test.get("recall_per_class") or {}
        precision = test.get("precision_per_class") or {}
        background_recall = recall.get("BACKGROUND_ENVIRONMENT")
        target_precision = precision.get("TARGET_DEVICE")
        if background_recall is None or target_precision is None:
            return None
        return {
            "false_positive_rate_on_background": round(1.0 - background_recall, 4),
            "target_device_precision": round(target_precision, 4),
        }

    def resolve_bundle_acquisition_reference(self, bundle_id: str) -> dict[str, Any]:
        dataset_reference_path = self.bundle_builder.root / bundle_id / "dataset_reference.json"
        if not dataset_reference_path.is_file():
            raise FileNotFoundError(f"BUNDLE_NOT_FOUND:{bundle_id}")
        capture_ids = read_json(dataset_reference_path).get("captures") or []
        if not capture_ids:
            raise ValueError(f"BUNDLE_HAS_NO_REFERENCED_CAPTURES:{bundle_id}")
        # Every capture in one training campaign was acquired under the same
        # Step 3 RF settings (see BleRffiStudioGuided.tsx) -- the first
        # reference capture is representative of all of them.
        capture = self.get_capture(capture_ids[0])
        if capture is None:
            raise FileNotFoundError(f"REFERENCED_CAPTURE_NOT_FOUND:{capture_ids[0]}")
        ble_channel = next((ch for ch, hz in _BLE_CHANNEL_FREQUENCIES_HZ.items() if hz == capture.center_frequency_hz), None)
        return {
            "center_frequency_hz": capture.center_frequency_hz,
            "ble_channel": ble_channel,
            "sample_rate_sps": capture.sample_rate_sps,
            "bandwidth_hz": capture.frontend_bandwidth_hz,
            "sample_dtype": capture.sample_dtype,
        }

    # Live Monitor's spectrum_stream_worker.py only ever configures
    # center_freq_hz/sample_rate_hz on the UHD source (see uhd.usrp_source
    # calls there) -- there is no independently-tracked analog "bandwidth"
    # setting to compare against a bundle's frontend_bandwidth_hz (an RF
    # capture request field this worker never receives at all). Requiring
    # exact bandwidth equality would reject every live check even when
    # frequency/sample rate genuinely match, so it is reported but not gated.
    #
    # What actually MUST match is which BLE advertising channel (37/38/39)
    # the burst was captured on -- that determines the physical RF the
    # device transmitted on, which the feature extractor's Hz-based features
    # (cfo_estimate_hz, spectral_centroid_hz, etc. -- see
    # representation_profiles.py) already compute correctly for whatever
    # real sample_rate_sps is passed in. A real, observed bug: gating on
    # EXACT center_frequency_hz (1 kHz tolerance) AND exact sample_rate_sps
    # meant nudging Live Monitor's span/gain by even a little silently
    # disabled the whole feature, even while still tuned to the same BLE
    # channel. Channel-bucket matching (half a channel's spacing either way)
    # fixes that without weakening the one thing that actually matters.
    _BLE_CHANNEL_MATCH_TOLERANCE_HZ = 10_000_000.0

    def _resolve_ble_channel(self, center_frequency_hz: float) -> int | None:
        nearest_channel = min(_BLE_CHANNEL_FREQUENCIES_HZ, key=lambda ch: abs(_BLE_CHANNEL_FREQUENCIES_HZ[ch] - center_frequency_hz))
        if abs(_BLE_CHANNEL_FREQUENCIES_HZ[nearest_channel] - center_frequency_hz) > self._BLE_CHANNEL_MATCH_TOLERANCE_HZ:
            return None
        return nearest_channel

    def live_check(
        self, *, bundle_id: str, iq_window: Any, sample_rate_sps: float, center_frequency_hz: float,
        bandwidth_hz: float | None = None, sample_format: str,
    ) -> dict[str, Any]:
        """Compatibility-gated live_check: refuses to score a burst whose
        acquisition parameters do not match what the bundle was trained on,
        instead of silently producing a meaningless prediction. This is the
        ONLY place that check happens -- OfflineInferenceService.run_live()
        itself has no notion of "current live tuning" to compare against."""
        reference = self.resolve_bundle_acquisition_reference(bundle_id)
        expected_channel = reference.get("ble_channel")
        live_channel = self._resolve_ble_channel(center_frequency_hz)
        if expected_channel is not None and live_channel != expected_channel:
            raise ValueError(
                f"LIVE_ACQUISITION_INCOMPATIBLE_WITH_BUNDLE:ble_channel: bundle trained on channel {expected_channel} "
                f"({_BLE_CHANNEL_FREQUENCIES_HZ.get(expected_channel)} Hz), current tuning resolves to channel {live_channel} ({center_frequency_hz} Hz)"
            )
        if reference.get("sample_dtype") not in (None, sample_format):
            raise ValueError(f"LIVE_ACQUISITION_INCOMPATIBLE_WITH_BUNDLE:sample_format: bundle expects {reference.get('sample_dtype')}, got {sample_format}")

        service = OfflineInferenceService(self.bundle_builder.root, {})
        result = service.run_live(bundle_id=bundle_id, iq_window=iq_window, sample_rate_sps=sample_rate_sps)
        result["identified_device"] = self._describe_predicted_class(bundle_id, result.get("predicted_class"))
        return result

    def _describe_predicted_class(self, bundle_id: str, predicted_class: str | None) -> str | None:
        """Maps a raw predicted label back to a name an operator recognizes.
        TARGET_VS_BACKGROUND's classes (TARGET_DEVICE/BACKGROUND_ENVIRONMENT)
        are meaningless without knowing WHICH physical unit was the target;
        other tasks (SAME_MODEL_UNIT_IDENTIFICATION etc.) already predict a
        real physical_unit_id, so it is returned unchanged."""
        if predicted_class is None:
            return None
        if predicted_class == "BACKGROUND_ENVIRONMENT":
            return "Entorno (sin el dispositivo objetivo)"
        if predicted_class == "TARGET_DEVICE":
            physical_units = read_json(self.bundle_builder.root / bundle_id / "dataset_reference.json").get("physical_units") or []
            return physical_units[0] if physical_units else "Dispositivo objetivo"
        return predicted_class

    # ------------------------------------------------------------------

    def _require_dataset(self, dataset_id: str, dataset_version: str) -> DatasetManifest:
        dataset = self.get_dataset(dataset_id, dataset_version)
        if dataset is None:
            raise FileNotFoundError(f"DATASET_NOT_FOUND:{dataset_id}:{dataset_version}")
        return dataset
