"""ScientificResultsRepository.run_coverage_analysis (2026-08-12,
Scientific Closure pass) -- real orchestration over a stub
`offline_inference_service` (never a real trained model in CI), mirroring
test_rq3_frr_analysis.py's dependency-injection pattern.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from app.modules.ble_rffi_studio.contracts import CaptureRecord
from app.modules.ble_scientific_results.api.scientific_results_repository import ScientificResultsRepository
from ._helpers import make_example, write_examples


def _repo(tmp_path):
    return ScientificResultsRepository(tmp_path / "sci_results", tmp_path / "ble_rffi_studio")


def _make_capture(capture_id: str, *, target_reference_id: str = "UNIT-A") -> CaptureRecord:
    return CaptureRecord(
        project_id="P1", campaign_id="C1", capture_id=capture_id, session_id=f"S-{capture_id}",
        execution_id=f"EXEC-{capture_id}", data_origin="REAL_B200", target_reference_id=target_reference_id,
        capture_purpose="TARGET_DEVICE_ON", target_state="POWERED_ON",
        receiver_device_id="dev-1", sdr_model="B200", rx_channel="RX2", antenna_port="RX2",
        sample_rate_sps=4_000_000, sample_dtype="cf32_le", byte_order="little_endian", sample_count=1000, channel_count=1,
        center_frequency_hz=2_402_000_000, frontend_bandwidth_hz=2_000_000, effective_bandwidth_hz=2_000_000, gain_db=20.0, gain_mode="manual",
        capture_duration_s=1.0, capture_tool="real", iq_path="iq.cf32", iq_size_bytes=1, iq_sha256=hashlib.sha256(capture_id.encode()).hexdigest(),
        acquisition_quality="PASSED", discontinuities=0, replay_status="FULLY_PROCESSED", created_at="2026-08-01T00:00:00Z",
    )


class _StubOfflineInferenceService:
    def __init__(self, windows_by_bundle_and_capture: dict[tuple[str, str], list[dict]], bundle_root=None) -> None:
        self.windows_by_bundle_and_capture = windows_by_bundle_and_capture
        self.calls: list[dict] = []
        self.bundle_root = bundle_root

    def run_decision_windows(self, *, bundle_id, examples, window_duration_s, minimum_eligible_bursts, base_profile=None):
        self.calls.append({"bundle_id": bundle_id, "n_examples": len(examples)})
        if not examples:
            return []
        capture_id = examples[0].capture_id
        registered = self.windows_by_bundle_and_capture.get((bundle_id, capture_id), [])
        # Real scoping fix (2026-08-18) calls this once per real split-domain
        # subset of a capture's examples -- so this stub must intersect a
        # registered window's burst_example_ids with the examples ACTUALLY
        # passed this call, exactly like the real run_decision_windows()
        # would only ever score the bursts it was given. A window with no
        # burst_example_ids declared (older, burst-set-agnostic fixtures)
        # passes through unfiltered.
        passed_ids = {e.example_id for e in examples}
        filtered = []
        for window in registered:
            burst_ids = window.get("burst_example_ids") or []
            if not burst_ids:
                filtered.append(window)
                continue
            surviving = [bid for bid in burst_ids if bid in passed_ids]
            if surviving:
                filtered.append({**window, "burst_example_ids": surviving, "burst_count": len(surviving)})
        return filtered


def _window(window_id: str, *, final_decision: str, predicted_class: str | None, physical_unit_id: str | None, abstention_reason: str | None = None, burst_example_ids: list[str] | None = None) -> dict:
    return {
        "decision_window_id": window_id, "final_decision": final_decision, "predicted_class": predicted_class,
        "physical_unit_id": physical_unit_id, "abstention_reason": abstention_reason, "burst_example_ids": burst_example_ids or [],
    }


def _write_run_and_rq2_report(tmp_path, *, dataset_id="DS1", dataset_version="1.0.0", scientific_task="SAME_MODEL_UNIT_IDENTIFICATION") -> None:
    run_dir = tmp_path / "sci_results" / "RUN-1"
    (run_dir / "06_statistics").mkdir(parents=True)
    (run_dir / "06_statistics" / "rq2_representation_comparison_report.json").write_text(json.dumps({
        "branches": [
            {"branch": "raw_iq", "analysis_role": "PRIMARY", "evaluation_domain": "VALIDATION", "model_bundle_id": "BUNDLE-RAW-IQ"},
            {"branch": "stft", "analysis_role": "UNSELECTED", "evaluation_domain": "VALIDATION", "model_bundle_id": "BUNDLE-STFT"},
        ],
    }), encoding="utf-8")
    (run_dir / "run.json").write_text(json.dumps({
        "schema_version": "ble-scientific-results-paper-run-v1", "paper_run_id": "RUN-1", "campaign_id": "C1",
        "protocol_id": "PROTO-1", "protocol_version": 1, "dataset_id": dataset_id, "dataset_version": dataset_version,
        "scientific_task": scientific_task, "analysis_code_commit": "abc", "analysis_environment_hash": "def",
        "storage_path": str(run_dir), "created_at": "2026-08-01T00:00:00Z",
    }), encoding="utf-8")


def test_run_coverage_analysis_aggregates_across_branches_and_units(tmp_path):
    repo = _repo(tmp_path)
    captures_dir = tmp_path / "ble_rffi_studio" / "captures"
    captures_dir.mkdir(parents=True)
    cap_a = _make_capture("CAP-A", target_reference_id="UNIT-A")
    cap_b = _make_capture("CAP-B", target_reference_id="UNIT-B")
    (captures_dir / "CAP-A.json").write_text(json.dumps(cap_a.model_dump(mode="json")), encoding="utf-8")
    (captures_dir / "CAP-B.json").write_text(json.dumps(cap_b.model_dump(mode="json")), encoding="utf-8")
    write_examples(tmp_path / "ble_rffi_studio", cap_a, [make_example(capture=cap_a, index=0, physical_unit_id="UNIT-A")])
    write_examples(tmp_path / "ble_rffi_studio", cap_b, [make_example(capture=cap_b, index=0, physical_unit_id="UNIT-B")])
    _write_run_and_rq2_report(tmp_path)

    service = _StubOfflineInferenceService({
        ("BUNDLE-RAW-IQ", "CAP-A"): [_window("w1", final_decision="IDENTIFIED", predicted_class="UNIT-A", physical_unit_id="UNIT-A")],
        ("BUNDLE-RAW-IQ", "CAP-B"): [_window("w2", final_decision="INSUFFICIENT_EVIDENCE", predicted_class=None, physical_unit_id="UNIT-B", abstention_reason="BELOW_MINIMUM_ELIGIBLE_BURSTS:1<2")],
        ("BUNDLE-STFT", "CAP-A"): [_window("w3", final_decision="UNKNOWN", predicted_class=None, physical_unit_id="UNIT-A")],
        ("BUNDLE-STFT", "CAP-B"): [_window("w4", final_decision="IDENTIFIED", predicted_class="UNIT-B", physical_unit_id="UNIT-B")],
    })

    as_dict = repo.run_coverage_analysis(paper_run_id="RUN-1", offline_inference_service=service)

    assert as_dict["overall"]["eligible_windows"] == 4
    assert as_dict["overall"]["decided_windows"] == 3
    assert as_dict["overall"]["abstained_windows"] == 1
    assert as_dict["by_branch"]["raw_iq"]["eligible_windows"] == 2
    assert as_dict["by_branch"]["stft"]["eligible_windows"] == 2
    assert as_dict["by_physical_unit"]["UNIT-A"]["decided_windows"] == 2
    assert as_dict["by_physical_unit"]["UNIT-B"]["abstained_windows"] == 1
    assert as_dict["abstention_reason_counts"] == {"BELOW_MINIMUM_ELIGIBLE_BURSTS:1<2": 1}
    assert set(as_dict["bundle_ids"].keys()) == {"raw_iq", "stft"}

    reloaded = repo.get_coverage_analysis_report("RUN-1")
    assert reloaded == as_dict


def test_run_coverage_analysis_raises_without_any_frozen_rq2_branch(tmp_path):
    repo = _repo(tmp_path)
    (tmp_path / "sci_results" / "RUN-1").mkdir(parents=True)
    (tmp_path / "sci_results" / "RUN-1" / "run.json").write_text(json.dumps({
        "schema_version": "ble-scientific-results-paper-run-v1", "paper_run_id": "RUN-1", "campaign_id": "C1",
        "protocol_id": "PROTO-1", "protocol_version": 1, "dataset_id": "DS1", "dataset_version": "1.0.0",
        "scientific_task": "SAME_MODEL_UNIT_IDENTIFICATION", "analysis_code_commit": "abc", "analysis_environment_hash": "def",
        "storage_path": str(tmp_path / "sci_results" / "RUN-1"), "created_at": "2026-08-01T00:00:00Z",
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="NO_FROZEN_RQ2_BRANCHES_WITH_A_MODEL_BUNDLE_ID"):
        repo.run_coverage_analysis(paper_run_id="RUN-1", offline_inference_service=_StubOfflineInferenceService({}))


def test_get_coverage_analysis_report_returns_none_when_not_built(tmp_path):
    repo = _repo(tmp_path)
    assert repo.get_coverage_analysis_report("RUN-1") is None


def test_run_coverage_analysis_with_evaluate_window_level_adds_real_ba_confusion_and_risk_coverage(tmp_path):
    # Closed-set decision-window BA/confusion/risk-coverage (2026-08-17):
    # reuses Evaluator.evaluate_split() on real decision-window predictions,
    # kept separate from `by_evaluation_domain` (which pools every branch)
    # to never mix two classifiers' predictions in one bucket.
    repo = _repo(tmp_path)
    ble_root = tmp_path / "ble_rffi_studio"
    captures_dir = ble_root / "captures"
    captures_dir.mkdir(parents=True)
    cap_a = _make_capture("CAP-A", target_reference_id="UNIT-A")
    cap_b = _make_capture("CAP-B", target_reference_id="UNIT-B")
    (captures_dir / "CAP-A.json").write_text(json.dumps(cap_a.model_dump(mode="json")), encoding="utf-8")
    (captures_dir / "CAP-B.json").write_text(json.dumps(cap_b.model_dump(mode="json")), encoding="utf-8")
    example_a = make_example(capture=cap_a, index=0, physical_unit_id="UNIT-A")
    example_b = make_example(capture=cap_b, index=0, physical_unit_id="UNIT-B")
    write_examples(ble_root, cap_a, [example_a])
    write_examples(ble_root, cap_b, [example_b])
    _write_run_and_rq2_report(tmp_path)

    # A real split so each window's burst_example_ids resolve to a real
    # evaluation_domain -- without this, domain stays None and the new
    # per-domain window-level block (which explicitly skips unresolved
    # domains, exactly like the rest of this module already does) has
    # nothing to report.
    (ble_root / "splits").mkdir(parents=True, exist_ok=True)
    (ble_root / "splits" / "DS1__1.0.0__SAME_MODEL_UNIT_IDENTIFICATION.json").write_text(json.dumps({
        "schema_version": "ble-rffi-studio-split-v1", "dataset_id": "DS1", "dataset_version": "1.0.0",
        "scientific_task": "SAME_MODEL_UNIT_IDENTIFICATION", "policy": "test", "split_status": "READY",
        "assignments": [
            {"example_id": example_a.example_id, "physical_unit_id": "UNIT-A", "capture_id": "CAP-A", "session_id": "S-CAP-A", "split": "TEST", "split_reason": "t"},
            {"example_id": example_b.example_id, "physical_unit_id": "UNIT-B", "capture_id": "CAP-B", "session_id": "S-CAP-B", "split": "TEST", "split_reason": "t"},
        ],
        "leakage_check": {"status": "PASSED"}, "created_at": "2026-08-01T00:00:00Z", "split_manifest_sha256": "hash",
    }), encoding="utf-8")

    bundle_root = tmp_path / "bundles"
    (bundle_root / "BUNDLE-RAW-IQ").mkdir(parents=True)
    (bundle_root / "BUNDLE-RAW-IQ" / "model_manifest.json").write_text(json.dumps({"label_classes": ["UNIT-A", "UNIT-B"]}), encoding="utf-8")
    (bundle_root / "BUNDLE-RAW-IQ" / "thresholds.json").write_text(json.dumps({"acceptance_threshold": 0.66, "calibrated_on": "VALIDATION"}), encoding="utf-8")

    def _w(window_id, *, final_decision, predicted_class, physical_unit_id, burst_example_ids, probs=None):
        w = _window(window_id, final_decision=final_decision, predicted_class=predicted_class, physical_unit_id=physical_unit_id, burst_example_ids=burst_example_ids)
        w["aggregated_probabilities"] = probs
        return w

    service = _StubOfflineInferenceService({
        ("BUNDLE-RAW-IQ", "CAP-A"): [_w("w1", final_decision="IDENTIFIED", predicted_class="UNIT-A", physical_unit_id="UNIT-A", burst_example_ids=[example_a.example_id], probs={"UNIT-A": 0.9, "UNIT-B": 0.1})],
        ("BUNDLE-RAW-IQ", "CAP-B"): [_w("w2", final_decision="IDENTIFIED", predicted_class="UNIT-A", physical_unit_id="UNIT-B", burst_example_ids=[example_b.example_id], probs={"UNIT-A": 0.7, "UNIT-B": 0.3})],
    }, bundle_root=bundle_root)

    as_dict = repo.run_coverage_analysis(paper_run_id="RUN-1", offline_inference_service=service, bundle_ids={"raw_iq": "BUNDLE-RAW-IQ"}, evaluate_window_level=True)

    wle = as_dict["window_level_evaluation"]["raw_iq"]
    # Two DIFFERENT real thresholds, unambiguously named (2026-08-17
    # investigation): classifier_acceptance_threshold is real (0.66,
    # VALIDATION-calibrated); association_time_threshold_ms stays null since
    # no AssociationPolicy was frozen in this fixture (fail-closed, real).
    assert wle["classifier_acceptance_threshold"] == 0.66
    assert wle["classifier_acceptance_threshold_calibrated_on"] == "VALIDATION"
    assert wle["association_time_threshold_ms"] is None
    test_domain = wle["by_evaluation_domain"]["TEST"]
    assert test_domain["evidence_maturity"] == "CURRENT_TEST"
    assert test_domain["confusion_matrix"]["UNIT-A"]["UNIT-A"] == 1
    assert test_domain["confusion_matrix"]["UNIT-B"]["UNIT-A"] == 1
    assert test_domain["balanced_accuracy"] == pytest.approx(0.5)
    assert test_domain["risk_coverage"]
    # PAPER_READY gate (2026-08-17): n_comparable=2 < 10 AND both real true
    # units (UNIT-A, UNIT-B) ARE distinct here -- still not ready on the
    # n<10 criterion alone.
    assert test_domain["distinct_physical_units"] == ["UNIT-A", "UNIT-B"]
    assert test_domain["paper_ready"] is False
    assert "n<10" in test_domain["paper_ready_reason"]
    # n_decided/n_abstained (2026-08-17): exact integer counts derived from
    # the same coverage ratio, real for every point on the curve.
    for point in test_domain["risk_coverage"]:
        assert point["n_decided"] + point["n_abstained"] == test_domain["n_comparable"]
        assert point["n_decided"] == pytest.approx(point["coverage"] * test_domain["n_comparable"], abs=1e-9)

    # Domain-resolution diagnostic (2026-08-17): both real windows resolved
    # to TEST here (real split above), so unresolved stays 0 -- see the
    # dedicated unresolved-reason tests below for the 3 failure classes.
    diagnostic = as_dict["domain_resolution_diagnostic"]
    assert diagnostic == {"total_windows": 2, "assigned_train": 0, "assigned_validation": 0, "assigned_test": 2, "unresolved": 0, "unresolved_by_reason": {}}

    # Real per-window record -- true TX/predicted TX/score/decision, one row
    # per real decision window, never only an aggregated confusion matrix.
    decision_windows = wle["decision_windows"]
    assert {(r["decision_window_id"], r["true_physical_unit_id"], r["predicted_class"], r["final_decision"]) for r in decision_windows} == {
        ("w1", "UNIT-A", "UNIT-A", "IDENTIFIED"),
        ("w2", "UNIT-B", "UNIT-A", "IDENTIFIED"),
    }
    assert all(r["evaluation_domain"] == "TEST" for r in decision_windows)

    reloaded = repo.get_coverage_analysis_report("RUN-1")
    assert reloaded == as_dict


def test_domain_resolution_diagnostic_classifies_the_two_real_unresolved_reasons(tmp_path):
    # Investigation finding (2026-08-17) + scoping fix (2026-08-18): only
    # 12/138 real decision windows in the real closed-set corpus resolved to
    # a TRAIN/VALIDATION/TEST domain, mostly because run_decision_windows()
    # used to be called on a capture's FULL raw burst set, so one
    # non-admitted or cross-domain burst poisoned the whole window. Now that
    # examples are partitioned by real split-domain BEFORE windowing,
    # MIXED_SPLIT_ASSIGNMENT_WITHIN_WINDOW is structurally impossible -- a
    # capture whose bursts really do belong to two different real domains
    # (CAP-MIXED below) now correctly resolves as TWO separate, correctly-
    # domained windows, not one poisoned, unresolved one. Only two real
    # reasons remain for a genuinely unresolved window.
    repo = _repo(tmp_path)
    ble_root = tmp_path / "ble_rffi_studio"
    captures_dir = ble_root / "captures"
    captures_dir.mkdir(parents=True)

    cap_resolved = _make_capture("CAP-RESOLVED", target_reference_id="UNIT-A")
    cap_outside = _make_capture("CAP-OUTSIDE", target_reference_id="UNIT-OUTSIDE")
    cap_missing = _make_capture("CAP-MISSING", target_reference_id="UNIT-A")
    cap_mixed = _make_capture("CAP-MIXED", target_reference_id="UNIT-A")
    for cap in (cap_resolved, cap_outside, cap_missing, cap_mixed):
        (captures_dir / f"{cap.capture_id}.json").write_text(json.dumps(cap.model_dump(mode="json")), encoding="utf-8")

    ex_resolved = make_example(capture=cap_resolved, index=0, physical_unit_id="UNIT-A")
    ex_outside = make_example(capture=cap_outside, index=0, physical_unit_id="UNIT-OUTSIDE")
    ex_missing = make_example(capture=cap_missing, index=0, physical_unit_id="UNIT-A")  # real example, but NOT in the split's assignments below
    ex_mixed_1 = make_example(capture=cap_mixed, index=0, physical_unit_id="UNIT-A")
    ex_mixed_2 = make_example(capture=cap_mixed, index=1, physical_unit_id="UNIT-A")
    write_examples(ble_root, cap_resolved, [ex_resolved])
    write_examples(ble_root, cap_outside, [ex_outside])
    write_examples(ble_root, cap_missing, [ex_missing])
    write_examples(ble_root, cap_mixed, [ex_mixed_1, ex_mixed_2])
    _write_run_and_rq2_report(tmp_path)

    (ble_root / "splits").mkdir(parents=True, exist_ok=True)
    (ble_root / "splits" / "DS1__1.0.0__SAME_MODEL_UNIT_IDENTIFICATION.json").write_text(json.dumps({
        "schema_version": "ble-rffi-studio-split-v1", "dataset_id": "DS1", "dataset_version": "1.0.0",
        "scientific_task": "SAME_MODEL_UNIT_IDENTIFICATION", "policy": "test", "split_status": "READY",
        "assignments": [
            {"example_id": ex_resolved.example_id, "physical_unit_id": "UNIT-A", "capture_id": "CAP-RESOLVED", "session_id": "S1", "split": "TEST", "split_reason": "t"},
            # ex_missing deliberately absent -- UNIT-A IS a real closed-set
            # unit (present via ex_resolved above), but THIS example was
            # never split-assigned (e.g. excluded post-freeze).
            {"example_id": ex_mixed_1.example_id, "physical_unit_id": "UNIT-A", "capture_id": "CAP-MIXED", "session_id": "S2", "split": "TRAIN", "split_reason": "t"},
            {"example_id": ex_mixed_2.example_id, "physical_unit_id": "UNIT-A", "capture_id": "CAP-MIXED", "session_id": "S2", "split": "VALIDATION", "split_reason": "t"},
        ],
        "leakage_check": {"status": "PASSED"}, "created_at": "2026-08-01T00:00:00Z", "split_manifest_sha256": "hash",
    }), encoding="utf-8")

    bundle_root = tmp_path / "bundles"
    (bundle_root / "BUNDLE-RAW-IQ").mkdir(parents=True)
    (bundle_root / "BUNDLE-RAW-IQ" / "model_manifest.json").write_text(json.dumps({"label_classes": ["UNIT-A", "UNIT-OUTSIDE"]}), encoding="utf-8")
    (bundle_root / "BUNDLE-RAW-IQ" / "thresholds.json").write_text(json.dumps({"acceptance_threshold": 0.5, "calibrated_on": "VALIDATION"}), encoding="utf-8")

    service = _StubOfflineInferenceService({
        ("BUNDLE-RAW-IQ", "CAP-RESOLVED"): [_window("w-resolved", final_decision="IDENTIFIED", predicted_class="UNIT-A", physical_unit_id="UNIT-A", burst_example_ids=[ex_resolved.example_id])],
        ("BUNDLE-RAW-IQ", "CAP-OUTSIDE"): [_window("w-outside", final_decision="IDENTIFIED", predicted_class="UNIT-OUTSIDE", physical_unit_id="UNIT-OUTSIDE", burst_example_ids=[ex_outside.example_id])],
        ("BUNDLE-RAW-IQ", "CAP-MISSING"): [_window("w-missing", final_decision="IDENTIFIED", predicted_class="UNIT-A", physical_unit_id="UNIT-A", burst_example_ids=[ex_missing.example_id])],
        ("BUNDLE-RAW-IQ", "CAP-MIXED"): [_window("w-mixed", final_decision="IDENTIFIED", predicted_class="UNIT-A", physical_unit_id="UNIT-A", burst_example_ids=[ex_mixed_1.example_id, ex_mixed_2.example_id])],
    }, bundle_root=bundle_root)

    as_dict = repo.run_coverage_analysis(paper_run_id="RUN-1", offline_inference_service=service, bundle_ids={"raw_iq": "BUNDLE-RAW-IQ"}, evaluate_window_level=True)

    diagnostic = as_dict["domain_resolution_diagnostic"]
    # 5 total: w-resolved (TEST) + w-outside (unresolved) + w-missing
    # (unresolved) + CAP-MIXED's two bursts, now cleanly split into their
    # OWN real TRAIN window and real VALIDATION window (the fix) instead of
    # one poisoned, unresolved MIXED window (the old, wrong behavior).
    assert diagnostic["total_windows"] == 5
    assert diagnostic["assigned_test"] == 1  # w-resolved
    assert diagnostic["assigned_train"] == 1  # CAP-MIXED's real TRAIN-admitted burst, now resolved
    assert diagnostic["assigned_validation"] == 1  # CAP-MIXED's real VALIDATION-admitted burst, now resolved
    assert diagnostic["unresolved"] == 2
    assert diagnostic["unresolved_by_reason"] == {
        "PHYSICAL_UNIT_NOT_IN_CLOSED_SET_SPLIT": 1,
        "EXAMPLE_ID_NOT_IN_SPLIT_ASSIGNMENTS": 1,
    }


def test_run_coverage_analysis_without_evaluate_window_level_never_adds_the_new_key(tmp_path):
    repo = _repo(tmp_path)
    captures_dir = tmp_path / "ble_rffi_studio" / "captures"
    captures_dir.mkdir(parents=True)
    cap_a = _make_capture("CAP-A", target_reference_id="UNIT-A")
    (captures_dir / "CAP-A.json").write_text(json.dumps(cap_a.model_dump(mode="json")), encoding="utf-8")
    write_examples(tmp_path / "ble_rffi_studio", cap_a, [make_example(capture=cap_a, index=0, physical_unit_id="UNIT-A")])
    _write_run_and_rq2_report(tmp_path)

    service = _StubOfflineInferenceService({
        ("BUNDLE-RAW-IQ", "CAP-A"): [_window("w1", final_decision="IDENTIFIED", predicted_class="UNIT-A", physical_unit_id="UNIT-A")],
    })
    as_dict = repo.run_coverage_analysis(paper_run_id="RUN-1", offline_inference_service=service, bundle_ids={"raw_iq": "BUNDLE-RAW-IQ"})
    assert "window_level_evaluation" not in as_dict
