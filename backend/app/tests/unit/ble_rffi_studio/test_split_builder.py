from __future__ import annotations

import pytest

from app.modules.ble_rffi_studio.dataset import DatasetBuilder
from app.modules.ble_rffi_studio.quality import SplitBuilder

from ._helpers import make_example, make_multi_unit_multi_session_examples


@pytest.fixture
def split_builder():
    return SplitBuilder()


def _frozen_dataset(tmp_path, examples, dataset_id="DS1"):
    builder = DatasetBuilder(tmp_path / "datasets")
    draft = builder.build_draft(dataset_id=dataset_id, dataset_version="1.0.0", project_id="P1", campaign_id="C1", examples=examples, data_origin="REAL_B200", creation_policy={}, created_at="2026-07-26T00:00:00Z")
    return builder.freeze(draft)


def test_same_model_unit_identification_not_feasible_with_a_single_unit(split_builder, tmp_path):
    examples = make_multi_unit_multi_session_examples(units=1, sessions_per_unit=3)
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")
    assert manifest.split_status == "NOT_FEASIBLE"
    assert "physical unit" in manifest.infeasibility_reason.lower()
    assert manifest.assignments == []


def test_same_model_unit_identification_not_feasible_with_too_few_sessions(split_builder, tmp_path):
    examples = make_multi_unit_multi_session_examples(units=2, sessions_per_unit=2)
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")
    assert manifest.split_status == "NOT_FEASIBLE"


def test_same_model_unit_identification_is_ready_with_enough_sessions(split_builder, tmp_path):
    examples = make_multi_unit_multi_session_examples(units=2, sessions_per_unit=3, examples_per_session=4)
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")

    assert manifest.split_status == "READY"
    assert manifest.leakage_check.status == "PASSED"
    assert manifest.split_manifest_sha256 is not None
    splits_used = {a.split for a in manifest.assignments}
    assert splits_used == {"TRAIN", "VALIDATION", "TEST"}
    # Both units appear in all three splits -- physical_unit_id repeating
    # across splits is correct, not leakage.
    for unit in ("SYN-UNIT-00", "SYN-UNIT-01"):
        unit_splits = {a.split for a in manifest.assignments if a.physical_unit_id == unit}
        assert unit_splits == {"TRAIN", "VALIDATION", "TEST"}


def test_same_model_unit_identification_grows_validation_and_test_with_more_sessions(split_builder, tmp_path):
    # Real bug found and fixed: VALIDATION/TEST used to get exactly 1
    # session each no matter how many sessions a unit had, so 10x the real
    # captures never made the held-out evaluation any more statistically
    # robust -- it only grew TRAIN. With 10 sessions/unit and a 0.2
    # fraction, VALIDATION and TEST must each get 2 sessions (round(10*0.2)),
    # not the old fixed 1.
    examples = make_multi_unit_multi_session_examples(units=2, sessions_per_unit=10, examples_per_session=2)
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")
    assert manifest.split_status == "READY"
    assert manifest.leakage_check.status == "PASSED"
    for unit in ("SYN-UNIT-00", "SYN-UNIT-01"):
        sessions_by_split: dict[str, set[str]] = {"TRAIN": set(), "VALIDATION": set(), "TEST": set()}
        for a in manifest.assignments:
            if a.physical_unit_id == unit:
                sessions_by_split[a.split].add(a.session_id)
        assert len(sessions_by_split["VALIDATION"]) == 2
        assert len(sessions_by_split["TEST"]) == 2
        assert len(sessions_by_split["TRAIN"]) == 6
        # Still session-disjoint: no session shared between splits.
        assert not (sessions_by_split["TRAIN"] & sessions_by_split["VALIDATION"])
        assert not (sessions_by_split["TRAIN"] & sessions_by_split["TEST"])
        assert not (sessions_by_split["VALIDATION"] & sessions_by_split["TEST"])


def test_same_model_unit_identification_never_splits_a_session_across_two_splits(split_builder, tmp_path):
    examples = make_multi_unit_multi_session_examples(units=2, sessions_per_unit=3, examples_per_session=4)
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")
    session_to_splits: dict[str, set[str]] = {}
    for a in manifest.assignments:
        session_to_splits.setdefault(a.session_id, set()).add(a.split)
    assert all(len(splits) == 1 for splits in session_to_splits.values())


def test_target_vs_background_not_feasible_without_background_sessions(split_builder, tmp_path):
    examples = [
        make_example(example_index=i, physical_unit_id="TARGET-UNIT", session_id=f"S-{i}", source_iq_sha256=f"sha-{i}")
        for i in range(3)
    ]
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="TARGET_VS_BACKGROUND", created_at="2026-07-26T00:00:00Z")
    assert manifest.split_status == "NOT_FEASIBLE"
    assert "background" in manifest.infeasibility_reason.lower()


def test_target_vs_background_requires_declared_background_environment_captures(split_builder, tmp_path):
    """3 target sessions + 3 physical_unit_id=None sessions is not enough on
    its own -- an example with no address match is only trustworthy negative
    evidence when its OWN capture was declared BACKGROUND_ENVIRONMENT (see
    module docstring). Undeclared "no match" examples (e.g. from a
    TARGET_DEVICE capture whose address just never resolved) must never
    silently count as background."""
    examples = [
        make_example(example_index=i, physical_unit_id="TARGET-UNIT", session_id=f"TARGET-S-{i}", source_iq_sha256=f"sha-t{i}")
        for i in range(3)
    ] + [
        make_example(example_index=100 + i, physical_unit_id=None, session_id=f"BG-S-{i}", source_iq_sha256=f"sha-bg{i}", capture_purpose=None)
        for i in range(3)
    ]
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="TARGET_VS_BACKGROUND", created_at="2026-07-26T00:00:00Z")

    assert manifest.split_status == "NOT_FEASIBLE"
    assert "background" in manifest.infeasibility_reason.lower()


def test_target_vs_background_is_ready_and_distributes_both_classes_across_all_splits(split_builder, tmp_path):
    examples = [
        make_example(example_index=i, physical_unit_id="TARGET-UNIT", session_id=f"TARGET-S-{i}", source_iq_sha256=f"sha-t{i}", capture_purpose="TARGET_DEVICE_ON")
        for i in range(3)
    ] + [
        make_example(example_index=100 + i, physical_unit_id=None, session_id=f"BG-S-{i}", source_iq_sha256=f"sha-bg{i}", capture_purpose="BACKGROUND_TARGET_OFF")
        for i in range(3)
    ]
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="TARGET_VS_BACKGROUND", created_at="2026-07-26T00:00:00Z")

    assert manifest.split_status == "READY"
    assert manifest.leakage_check.status == "PASSED"
    background_assignments = [a for a in manifest.assignments if a.physical_unit_id is None]
    target_assignments = [a for a in manifest.assignments if a.physical_unit_id is not None]
    assert background_assignments and target_assignments
    # Both classes are now genuinely present in ALL three splits -- the
    # previous design kept negatives out of TRAIN entirely, which left every
    # classifier trained on a single class (a real, observed failure).
    assert {a.split for a in background_assignments} == {"TRAIN", "VALIDATION", "TEST"}
    assert {a.split for a in target_assignments} == {"TRAIN", "VALIDATION", "TEST"}
    train_labels = {"TARGET_DEVICE" if a.physical_unit_id else "BACKGROUND_ENVIRONMENT" for a in manifest.assignments if a.split == "TRAIN"}
    assert train_labels == {"TARGET_DEVICE", "BACKGROUND_ENVIRONMENT"}


def test_target_vs_background_ignores_a_no_match_example_from_a_target_device_capture_as_background(split_builder, tmp_path):
    """The exact real failure mode this fix targets: a TARGET_DEVICE-declared
    capture whose evidence never matched a registered address must never be
    silently counted as background, even if it has plenty of sessions and
    physical_unit_id=None examples."""
    examples = [
        make_example(example_index=i, physical_unit_id="TARGET-UNIT", session_id=f"TARGET-S-{i}", source_iq_sha256=f"sha-t{i}", capture_purpose="TARGET_DEVICE_ON")
        for i in range(3)
    ] + [
        # Declared TARGET_DEVICE (operator meant to capture the device on),
        # but the address never matched -- association_status NONE/CONFLICT,
        # physical_unit_id=None. NOT legitimate background evidence.
        make_example(example_index=200 + i, physical_unit_id=None, session_id=f"UNMATCHED-S-{i}", source_iq_sha256=f"sha-unm{i}", capture_purpose="TARGET_DEVICE_ON", association_status="NONE")
        for i in range(5)
    ]
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="TARGET_VS_BACKGROUND", created_at="2026-07-26T00:00:00Z")

    assert manifest.split_status == "NOT_FEASIBLE"
    assert "background" in manifest.infeasibility_reason.lower()


def test_unknown_device_rejection_with_only_one_known_unit_is_blocked_by_the_common_single_class_gate(split_builder, tmp_path):
    """UNKNOWN_DEVICE_REJECTION's own feasibility check only requires >=1
    known unit (unknowns are never assigned to TRAIN by design) -- with
    exactly 1 known unit, TRAIN ends up with a single label ("that one
    unit"), the same fundamental problem TARGET_VS_BACKGROUND had. The
    common _finalize gate catches this even though this task's own
    task-specific check does not."""
    known = make_multi_unit_multi_session_examples(units=1, sessions_per_unit=3, examples_per_session=4)
    unknown = [
        make_example(example_index=200 + i, physical_unit_id=None, session_id=f"UNK-S-{i}", source_iq_sha256=f"sha-unk{i}")
        for i in range(2)
    ]
    examples = known + unknown
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="UNKNOWN_DEVICE_REJECTION", created_at="2026-07-26T00:00:00Z")

    assert manifest.split_status == "NOT_FEASIBLE"
    assert "TRAINING_REQUIRES_AT_LEAST_TWO_CLASSES" in manifest.infeasibility_reason


def test_unknown_device_rejection_not_feasible_without_enough_unknown_sessions(split_builder, tmp_path):
    examples = make_multi_unit_multi_session_examples(units=1, sessions_per_unit=3)
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="UNKNOWN_DEVICE_REJECTION", created_at="2026-07-26T00:00:00Z")
    assert manifest.split_status == "NOT_FEASIBLE"


def test_unknown_device_rejection_is_ready_and_keeps_unknowns_out_of_train(split_builder, tmp_path):
    # 2 known units, not 1 -- a "known-vs-unknown" classifier needs >=2 real
    # classes in TRAIN to be meaningful (the same principle
    # TARGET_VS_BACKGROUND's redesign enforces), matching
    # write_unknown_device_rejection_fixture's own default elsewhere in this
    # test suite.
    known = make_multi_unit_multi_session_examples(units=2, sessions_per_unit=3, examples_per_session=4)
    unknown = [
        make_example(example_index=200 + i, physical_unit_id=None, session_id=f"UNK-S-{i}", source_iq_sha256=f"sha-unk{i}")
        for i in range(2)
    ]
    examples = known + unknown
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="UNKNOWN_DEVICE_REJECTION", created_at="2026-07-26T00:00:00Z")

    assert manifest.split_status == "READY"
    unknown_assignments = [a for a in manifest.assignments if a.physical_unit_id is None]
    assert unknown_assignments
    assert all(a.split != "TRAIN" for a in unknown_assignments)
    assert {a.split for a in unknown_assignments} <= {"VALIDATION", "TEST"}


def test_unknown_scientific_task_raises(split_builder, tmp_path):
    examples = [make_example(example_index=1, physical_unit_id="U1", session_id="S1")]
    dataset = _frozen_dataset(tmp_path, examples)
    with pytest.raises(ValueError):
        split_builder.build(dataset=dataset, examples=examples, scientific_task="NOT_A_REAL_TASK", created_at="2026-07-26T00:00:00Z")


def test_channel_38_examples_are_excluded_from_the_main_benchmark_and_recorded(split_builder, tmp_path):
    """Split-policy correction (2026-08-08): the main benchmark trains and
    evaluates on channel 37 only. Real channel-38 examples exist on disk
    (transport-domain data reserved for a separate, not-yet-implemented
    analysis) -- they must never be silently mixed into TRAIN/VALIDATION/
    TEST here, and their exclusion must be auditable from the manifest."""
    channel_37 = make_multi_unit_multi_session_examples(units=2, sessions_per_unit=3, examples_per_session=4)
    channel_38 = [
        make_example(example_index=900 + i, physical_unit_id="SYN-UNIT-00", session_id=f"CH38-SESSION-{i}", source_iq_sha256=f"sha-ch38-{i}").model_copy(
            update={"channel": 38, "center_frequency_hz": 2_426_000_000}
        )
        for i in range(3)
    ]
    examples = channel_37 + channel_38
    dataset = _frozen_dataset(tmp_path, examples, dataset_id="DS-MIXED-CHANNEL")
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")

    assert manifest.split_status == "READY"
    assert set(manifest.channel_scope_excluded_example_ids) == {e.example_id for e in channel_38}
    assigned_ids = {a.example_id for a in manifest.assignments}
    assert assigned_ids.isdisjoint(manifest.channel_scope_excluded_example_ids)
    assert "channel_37_only" in manifest.policy


def test_channel_scope_exclusion_is_recorded_even_on_a_not_feasible_outcome(split_builder, tmp_path):
    channel_38_only = [
        make_example(example_index=i, physical_unit_id="U1", session_id=f"S-{i}", source_iq_sha256=f"sha-{i}").model_copy(
            update={"channel": 38, "center_frequency_hz": 2_426_000_000}
        )
        for i in range(3)
    ]
    dataset = _frozen_dataset(tmp_path, channel_38_only, dataset_id="DS-CH38-ONLY")
    manifest = split_builder.build(dataset=dataset, examples=channel_38_only, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")

    assert manifest.split_status == "NOT_FEASIBLE"
    assert set(manifest.channel_scope_excluded_example_ids) == {e.example_id for e in channel_38_only}


def test_split_completeness_gate_rejects_a_split_where_validation_is_missing_a_train_class(split_builder, tmp_path):
    """Split-completeness correction (2026-08-08): a class with zero true
    instances in VALIDATION/TEST silently biases balanced_accuracy/macro_f1
    toward that split (evaluator.py's own definition deliberately keeps
    those formulas unchanged) -- the real fix belongs at split-completeness
    gating instead. Manually constructs an otherwise-valid split whose
    SplitBuilder-computed leakage/2-class checks would pass, but which is
    missing SYN-UNIT-01 from VALIDATION entirely."""
    examples = make_multi_unit_multi_session_examples(units=2, sessions_per_unit=3, examples_per_session=4)
    dataset = _frozen_dataset(tmp_path, examples, dataset_id="DS-INCOMPLETE")
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")
    assert manifest.split_status == "READY"  # sanity: the real builder produces a complete split on its own

    # Now simulate a hypothetical construction bug: reassign every
    # SYN-UNIT-01 VALIDATION assignment to TRAIN instead, so VALIDATION
    # loses that class entirely while TRAIN still has both.
    tampered_assignments = [
        (a.model_copy(update={"split": "TRAIN"}) if (a.split == "VALIDATION" and a.physical_unit_id == "SYN-UNIT-01") else a)
        for a in manifest.assignments
    ]
    examples_by_id = {e.example_id: e for e in examples}
    from app.modules.ble_rffi_studio.quality.split_builder import train_label_for
    tampered_report = split_builder._finalize(
        dataset, "SAME_MODEL_UNIT_IDENTIFICATION", manifest.policy, tampered_assignments,
        manifest.leakage_check, "2026-07-26T00:00:00Z", examples_by_id, manifest.channel_scope_excluded_example_ids,
    )
    assert tampered_report.split_status == "NOT_FEASIBLE"
    assert "SPLIT_INCOMPLETE_MISSING_CLASS_SUPPORT" in tampered_report.infeasibility_reason
    assert "SYN-UNIT-01" in tampered_report.infeasibility_reason


def test_build_rq1_dependence_diagnostic_is_non_confirmatory_and_bypasses_leakage(split_builder, tmp_path):
    # RQ1's whole point: deliberately hold out examples from the SAME
    # session/capture as TRAIN. The normal leakage check must still run and
    # be recorded (never hidden), but must NOT block this split -- unlike
    # every split build() itself produces.
    examples = make_multi_unit_multi_session_examples(units=2, sessions_per_unit=3, examples_per_session=4)
    dataset = _frozen_dataset(tmp_path, examples)
    confirmatory = split_builder.build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")
    assert confirmatory.split_purpose == "CONFIRMATORY"
    assert confirmatory.non_confirmatory is False

    diagnostic = split_builder.build_rq1_dependence_diagnostic(
        dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION",
        confirmatory_split=confirmatory, created_at="2026-07-26T00:00:00Z",
    )
    assert diagnostic.split_purpose == "RQ1_ACQUISITION_DEPENDENCE_DIAGNOSTIC"
    assert diagnostic.non_confirmatory is True
    assert diagnostic.split_status == "READY"
    # The held-out VALIDATION examples share a session_id (and therefore
    # capture identity) with TRAIN -- the leakage check must report this
    # honestly as FAILED, proving it wasn't silently skipped.
    assert diagnostic.leakage_check.status == "FAILED"
    assert "session_id" in diagnostic.leakage_check.overlapping_keys


def test_build_rq1_dependence_diagnostic_never_reachable_from_build(split_builder, tmp_path):
    examples = make_multi_unit_multi_session_examples(units=2, sessions_per_unit=3, examples_per_session=4)
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")
    # build() itself never produces anything but CONFIRMATORY, regardless of
    # leakage outcome -- confirmed here it stays strictly capture-disjoint.
    assert manifest.split_purpose == "CONFIRMATORY"
    assert manifest.leakage_check.status == "PASSED"


def test_build_rq1_dependence_diagnostic_not_feasible_with_single_example_sessions(split_builder, tmp_path):
    examples = make_multi_unit_multi_session_examples(units=2, sessions_per_unit=3, examples_per_session=1)
    dataset = _frozen_dataset(tmp_path, examples)
    confirmatory = split_builder.build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")

    diagnostic = split_builder.build_rq1_dependence_diagnostic(
        dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION",
        confirmatory_split=confirmatory, created_at="2026-07-26T00:00:00Z",
    )
    assert diagnostic.split_status == "NOT_FEASIBLE"
    assert diagnostic.split_purpose == "RQ1_ACQUISITION_DEPENDENCE_DIAGNOSTIC"


def _synthetic_confirmatory_split(dataset, examples, *, scientific_task="MULTI_DEVICE_CLASSIFICATION") -> "SplitManifest":
    """A minimal, directly-constructed CONFIRMATORY split with every real
    example assigned TRAIN -- build_rq1_window_level_dependence_diagnostic()
    only ever reads TRAIN assignments, so this is enough without running the
    full closed-set split-building machinery."""
    from app.modules.ble_rffi_studio.contracts import LeakageCheckResult, SplitAssignment, SplitManifest
    assignments = [
        SplitAssignment(example_id=e.example_id, physical_unit_id=e.physical_unit_id, capture_id=e.capture_id, session_id=e.session_id, split="TRAIN", split_reason="synthetic")
        for e in examples
    ]
    return SplitManifest(
        dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version, scientific_task=scientific_task, policy="synthetic",
        split_status="READY", assignments=assignments, leakage_check=LeakageCheckResult(status="PASSED"), created_at="2026-08-18T00:00:00Z",
    )


def _windowed_capture_examples(*, unit_id: str, capture_id: str, n_windows: int, bursts_per_window: int = 2) -> list[ExampleRecord]:
    """Real 10-second-window-spanning examples for ONE capture -- window
    boundaries follow the EXACT SAME formula group_examples_into_windows()
    uses (iq_start_sample // (window_duration_s * sample_rate_sps)), at
    sample_rate_sps=4_000_000 (make_example's fixed value)."""
    window_samples = int(10.0 * 4_000_000)
    session_id = f"SESSION-{capture_id}"
    examples = []
    counter = 0
    for window_index in range(n_windows):
        for burst_index in range(bursts_per_window):
            start = window_index * window_samples + burst_index * 1000
            examples.append(make_example(
                example_index=counter, physical_unit_id=unit_id, session_id=session_id, capture_id=capture_id,
                source_iq_sha256=f"synthetic-sha-{capture_id}", iq_start_sample=start, iq_end_sample=start + 500,
            ))
            counter += 1
    return examples


def test_build_rq1_window_level_dependence_diagnostic_reserves_disjoint_windows_same_capture(split_builder, tmp_path):
    # Future protocol rule (2026-08-18): same capture=YES, same real
    # decision window=NO, shared bursts=NO. Models the definitive campaign's
    # real 120s/12-window captures at a smaller scale (4 real 10s windows
    # per capture, 2 units) -- proves the two disjointness invariants the
    # protocol requires, re-derived independently via
    # group_examples_into_windows() (never trusting split_reason text alone).
    from app.modules.ble_rffi_studio.inference.decision_windows import group_examples_into_windows

    examples_unit_a = _windowed_capture_examples(unit_id="UNIT-A", capture_id="CAP-A", n_windows=4)
    examples_unit_b = _windowed_capture_examples(unit_id="UNIT-B", capture_id="CAP-B", n_windows=4)
    examples = examples_unit_a + examples_unit_b
    dataset = _frozen_dataset(tmp_path, examples, dataset_id="DS-WINDOW-LEVEL")
    confirmatory = _synthetic_confirmatory_split(dataset, examples)

    diagnostic = split_builder.build_rq1_window_level_dependence_diagnostic(
        dataset=dataset, examples=examples, scientific_task="MULTI_DEVICE_CLASSIFICATION",
        confirmatory_split=confirmatory, created_at="2026-08-18T00:00:00Z",
    )
    assert diagnostic.split_status == "READY"
    assert diagnostic.split_purpose == "RQ1_WINDOW_LEVEL_ACQUISITION_DEPENDENCE_DIAGNOSTIC"
    assert diagnostic.non_confirmatory is True
    # Deliberately capture-dependent by design -- leakage check must report
    # this honestly (capture_id/session_id real overlap), never hidden.
    assert diagnostic.leakage_check.status == "FAILED"
    assert "capture_id" in diagnostic.leakage_check.overlapping_keys
    # Shared bursts=NO: no individual burst identity fields should overlap
    # between the two roles (each real burst belongs to exactly one window,
    # each window to exactly one role).
    assert "candidate_id" not in diagnostic.leakage_check.overlapping_keys
    assert "packet_id" not in diagnostic.leakage_check.overlapping_keys

    fitting_examples = [e for e in examples if e.example_id in {a.example_id for a in diagnostic.assignments if a.split == "TRAIN"}]
    diagnostic_examples = [e for e in examples if e.example_id in {a.example_id for a in diagnostic.assignments if a.split == "VALIDATION"}]
    assert fitting_examples and diagnostic_examples  # both roles real and non-empty

    train_window_ids = set(group_examples_into_windows(fitting_examples, 10.0).keys())
    diagnostic_window_ids = set(group_examples_into_windows(diagnostic_examples, 10.0).keys())

    # The two required invariants, verified independently:
    assert train_window_ids.isdisjoint(diagnostic_window_ids)  # train_window_ids ∩ diagnostic_window_ids = ∅
    capture_ids_train = {a.capture_id for a in diagnostic.assignments if a.split == "TRAIN"}
    capture_ids_diagnostic = {a.capture_id for a in diagnostic.assignments if a.split == "VALIDATION"}
    assert capture_ids_train == capture_ids_diagnostic == {"CAP-A", "CAP-B"}


def test_build_rq1_window_level_dependence_diagnostic_not_available_with_single_window_captures(split_builder, tmp_path):
    # Today's real closed-set captures -- at most 1 complete real 10s window
    # each. Must NEVER be fabricated into a fake dependent diagnostic.
    examples = _windowed_capture_examples(unit_id="UNIT-A", capture_id="CAP-SHORT", n_windows=1) + \
        _windowed_capture_examples(unit_id="UNIT-B", capture_id="CAP-SHORT-2", n_windows=1)
    dataset = _frozen_dataset(tmp_path, examples, dataset_id="DS-SHORT")
    confirmatory = _synthetic_confirmatory_split(dataset, examples)

    diagnostic = split_builder.build_rq1_window_level_dependence_diagnostic(
        dataset=dataset, examples=examples, scientific_task="MULTI_DEVICE_CLASSIFICATION",
        confirmatory_split=confirmatory, created_at="2026-08-18T00:00:00Z",
    )
    assert diagnostic.split_status == "NOT_FEASIBLE"
    assert diagnostic.split_purpose == "RQ1_WINDOW_LEVEL_ACQUISITION_DEPENDENCE_DIAGNOSTIC"
    assert diagnostic.infeasibility_reason.startswith("NOT_AVAILABLE_FOR_WINDOW_LEVEL_DEPENDENT_DIAGNOSTIC")
    assert diagnostic.assignments == []


def test_split_manifest_round_trips_through_canonical_json(split_builder, tmp_path):
    import json

    from app.modules.ble_rffi_studio.contracts import SplitManifest

    examples = make_multi_unit_multi_session_examples(units=2, sessions_per_unit=3, examples_per_session=2)
    dataset = _frozen_dataset(tmp_path, examples)
    manifest = split_builder.build(dataset=dataset, examples=examples, scientific_task="SAME_MODEL_UNIT_IDENTIFICATION", created_at="2026-07-26T00:00:00Z")
    restored = SplitManifest.model_validate(json.loads(manifest.canonical_json()))
    assert restored == manifest
