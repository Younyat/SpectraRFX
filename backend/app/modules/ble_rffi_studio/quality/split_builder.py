"""Builds TRAIN/VALIDATION/TEST splits by whole session, never by window
within a session, and never assumes 3 splits are always possible -- each
scientific_task has its own minimum-evidence rule (design correction #7).
When a task's requirement isn't met, split_status=NOT_FEASIBLE with an exact
reason, never an artificial split.

physical_unit_id repeating across splits is correct here (needed to evaluate
that class); what must never repeat is capture_id/execution_id/session_id/
candidate_id/packet_id/sample-range -- computed and checked for real via
_compute_leakage, never assumed from the construction method alone.

TARGET_VS_BACKGROUND's "background" side is real negative evidence ONLY when
it comes from an example whose OWN capture was declared
capture_purpose=BACKGROUND_TARGET_OFF or BACKGROUND_GENERAL (operator
explicitly confirmed the target was off/removed, or recorded ambient
environment with no target in question) -- never from a
TARGET_DEVICE_ON-declared capture whose evidence merely failed to match a
registered address (association_status NONE/CONFLICT), and never from
UNKNOWN_DEVICE_COLLECTION (that purpose exists only to feed
UNKNOWN_DEVICE_REJECTION, never TARGET_VS_BACKGROUND's negative class).
"No address match" is not "confirmed absent"; treating it as background
contaminates the negative class with inconclusive data (a real, observed
failure mode: two TARGET_DEVICE_ON captures with no address match were
silently counted as background sessions, driving a whole TRAIN split down to
one class).

A supervised classifier trained on a single label is never scientifically
meaningful regardless of which scientific_task asked for it -- _finalize()
enforces this as one common, task-agnostic gate before a split can ever be
marked READY, so it blocks every model type training_service.py can train
(logistic_regression, svm_rbf, random_forest, cnn1d, cnn2d) uniformly,
rather than relying on each model's own library to notice (sklearn's
LogisticRegression/SVC raise on a single class; RandomForestClassifier and
the CNN trainers do not, and will silently "succeed" with a meaningless
model otherwise).

Split-policy correction (2026-08-08): _LEAKAGE_FIELDS deliberately stays
identity-only (capture/execution/session/candidate/packet/sample-range).
day_id and receiver_epoch are NOT added here, on purpose -- this study runs
on a single B200 receiver (a receiver-disjoint requirement would be
impossible to satisfy by construction), and a day-disjoint requirement was
never part of any of the four scientific_task designs below; adding either
indiscriminately would either make every split NOT_FEASIBLE for a reason
nothing in the paper actually asks for, or silently encode a requirement
nobody reviewed. Each RQ that DOES need a real cross-day or cross-epoch
disjointness (device-day PRE/POST pairing, receiver-epoch invalidation) gets
its own explicit, separately-implemented policy instead of a blanket rule
here (see decision_window_records.py / paper_campaign_runner.py).

BLE channel is handled the same way, but the current four scientific_tasks
DO have a real, paper-driven constraint on it: the main benchmark trains and
evaluates on channel 37 only. Channels 38/39 are real, already-decoded data
(9350 real examples on channel 38 exist on disk) reserved for a distinct,
not-yet-implemented post-freeze transport-domain analysis -- never silently
mixed into TRAIN/VALIDATION/TEST for identity/TVB/unknown-rejection here.
_MAIN_BENCHMARK_CHANNEL enforces this by excluding non-37 examples before
any split is built, and every excluded example_id is recorded on the
resulting SplitManifest (channel_scope_excluded_example_ids) so the
exclusion is auditable, not silent.
"""
from __future__ import annotations

from ..contracts import DatasetManifest, ExampleRecord, LeakageCheckResult, SplitAssignment, SplitManifest
from ..contracts.split import SplitPurpose

# split_purpose/non_confirmatory (2026-08-09 addition) are deliberately
# excluded from the frozen hash: every real historical SplitManifest was
# hashed before these fields existed, and re-including them would make
# scientific_results_repository.py's integrity check report a hash
# mismatch for every one of them, purely because of an additive metadata
# tag -- never a real content change. The hash-protected content (leakage
# check, assignments, channel exclusions) is unaffected.
_HASH_EXCLUDED_FIELDS = {"split_manifest_sha256", "split_purpose", "non_confirmatory"}

_SPLIT_NAMES = ("TRAIN", "VALIDATION", "TEST")
_LEAKAGE_FIELDS = ["capture_id", "execution_id", "session_id", "candidate_id", "packet_id", "sample_range"]
_MAIN_BENCHMARK_CHANNEL = 37
_MIN_SESSIONS_PER_UNIT = 3
_MIN_TARGET_SESSIONS = 3
# One background session per split (TRAIN/VALIDATION/TEST) -- was 1 total
# (background reserved for VALIDATION/TEST only), which meant TRAIN never
# saw a background example and every classifier trained on one class alone.
# Symmetric with _MIN_TARGET_SESSIONS now that both classes are genuinely
# distributed across all three splits.
_MIN_BACKGROUND_SESSIONS = 3
_MIN_UNKNOWN_SESSIONS = 2
# Fraction of a unit's sessions allocated to VALIDATION and to TEST each in
# _closed_set_classification (SAME_MODEL_UNIT_IDENTIFICATION/MULTI_DEVICE_
# CLASSIFICATION) -- see that method's docstring for why a fixed count of 1
# regardless of how many sessions exist was a real, confirmed problem.
_VAL_TEST_SESSION_FRACTION = 0.2

TARGET_DEVICE_LABEL = "TARGET_DEVICE"
BACKGROUND_ENVIRONMENT_LABEL = "BACKGROUND_ENVIRONMENT"
UNKNOWN_CLASS_LABEL = "UNKNOWN"


def train_label_for(scientific_task: str, example: ExampleRecord) -> str:
    """The label training_service.py's own y_train will actually use for this
    example -- kept in exactly one place so SplitBuilder's own train-class
    gate can never silently disagree with what training actually sees."""
    if scientific_task == "TARGET_VS_BACKGROUND":
        return TARGET_DEVICE_LABEL if example.physical_unit_id else BACKGROUND_ENVIRONMENT_LABEL
    return example.physical_unit_id or UNKNOWN_CLASS_LABEL


class SplitBuilder:
    def build(self, *, dataset: DatasetManifest, examples: list[ExampleRecord], scientific_task: str, created_at: str) -> SplitManifest:
        by_id = {e.example_id: e for e in examples}
        selected = [by_id[eid] for eid in dataset.example_ids if eid in by_id]

        # Main benchmark is channel-37-only for every currently-implemented
        # scientific_task -- see module docstring. channel_excluded_ids is
        # threaded through and recorded on the manifest even on a
        # NOT_FEASIBLE outcome, so "why did this dataset lose N examples" is
        # always answerable from the manifest alone -- never instance state
        # on this (shared, StudioRepository-owned) builder.
        in_scope = [e for e in selected if e.channel == _MAIN_BENCHMARK_CHANNEL]
        channel_excluded_ids = sorted(e.example_id for e in selected if e.channel != _MAIN_BENCHMARK_CHANNEL)
        selected = in_scope

        if scientific_task in ("SAME_MODEL_UNIT_IDENTIFICATION", "MULTI_DEVICE_CLASSIFICATION"):
            return self._closed_set_classification(dataset, selected, scientific_task, created_at, channel_excluded_ids)
        if scientific_task == "TARGET_VS_BACKGROUND":
            return self._target_vs_background(dataset, selected, created_at, channel_excluded_ids)
        if scientific_task == "UNKNOWN_DEVICE_REJECTION":
            return self._unknown_device_rejection(dataset, selected, created_at, channel_excluded_ids)
        raise ValueError(f"UNKNOWN_SCIENTIFIC_TASK:{scientific_task}")

    def build_rq1_dependence_diagnostic(
        self, *, dataset: DatasetManifest, examples: list[ExampleRecord], scientific_task: str,
        confirmatory_split: SplitManifest, created_at: str,
    ) -> SplitManifest:
        """RQ1-only, NON-CONFIRMATORY (split_purpose=
        RQ1_ACQUISITION_DEPENDENCE_DIAGNOSTIC): deliberately violates
        capture-disjointness to measure acquisition-dependence optimism
        (this is what produces RQ1's BA_window number -- see
        evaluation/rq1_acquisition_dependence.py). NEVER reachable from
        build(); build() itself is untouched by this method and stays
        strictly capture-disjoint.

        Takes an already-built CONFIRMATORY split (`confirmatory_split`,
        from build()) and, for each of its TRAIN sessions with >=2 examples,
        deterministically holds out the second half of that SAME session's
        examples as a "VALIDATION" role -- i.e. the held-out examples come
        from the identical capture/session as TRAIN, on purpose. The normal
        leakage check still runs and is still recorded on the resulting
        manifest (never hidden), it is simply not allowed to block this one
        path (enforce_leakage_gate=False) -- a FAILED leakage status here is
        the expected, intended signal, not a bug."""
        by_id = {e.example_id: e for e in examples}
        train_example_ids = {a.example_id for a in confirmatory_split.assignments if a.split == "TRAIN"}
        by_session: dict[str, list[ExampleRecord]] = {}
        for example_id in train_example_ids:
            example = by_id.get(example_id)
            if example is not None:
                by_session.setdefault(example.session_id, []).append(example)

        policy = "rq1_window_diagnostic:same_capture_held_out_examples"
        eligible_sessions = {sid: exs for sid, exs in by_session.items() if len(exs) >= 2}
        if not eligible_sessions:
            reason = (
                "RQ1_ACQUISITION_DEPENDENCE_DIAGNOSTIC requires >=1 CONFIRMATORY-TRAIN session with >=2 examples "
                f"to hold out a within-session window; found 0 (of {len(by_session)} TRAIN session(s) total)."
            )
            return self._not_feasible(dataset, scientific_task, policy, reason, created_at, [], split_purpose="RQ1_ACQUISITION_DEPENDENCE_DIAGNOSTIC")

        assignments: list[SplitAssignment] = []
        for session_id, session_examples in eligible_sessions.items():
            ordered = sorted(session_examples, key=lambda e: e.example_id)
            midpoint = len(ordered) // 2
            for example in ordered[:midpoint]:
                assignments.append(SplitAssignment(
                    example_id=example.example_id, physical_unit_id=example.physical_unit_id, capture_id=example.capture_id,
                    session_id=session_id, split="TRAIN", split_reason=f"{policy}:first_half",
                ))
            for example in ordered[midpoint:]:
                assignments.append(SplitAssignment(
                    example_id=example.example_id, physical_unit_id=example.physical_unit_id, capture_id=example.capture_id,
                    session_id=session_id, split="VALIDATION", split_reason=f"{policy}:second_half",
                ))

        leakage = self._compute_leakage(assignments, by_id)
        return self._finalize(
            dataset, scientific_task, policy, assignments, leakage, created_at, by_id, [],
            enforce_leakage_gate=False, split_purpose="RQ1_ACQUISITION_DEPENDENCE_DIAGNOSTIC",
        )

    def build_rq1_window_level_dependence_diagnostic(
        self, *, dataset: DatasetManifest, examples: list[ExampleRecord], scientific_task: str,
        confirmatory_split: SplitManifest, created_at: str,
        window_duration_s: float | None = None, minimum_eligible_bursts: int | None = None,
    ) -> SplitManifest:
        """RQ1's window-level acquisition-dependence diagnostic (2026-08-18
        correction, split_purpose=RQ1_WINDOW_LEVEL_ACQUISITION_DEPENDENCE_
        DIAGNOSTIC): unlike build_rq1_dependence_diagnostic() above (which
        splits by ExampleRecord hash-order and can place fitting-role and
        diagnostic-role bursts inside the exact SAME real 10-second decision
        window -- confirmed a real problem, not scientifically valid at
        decision-window granularity), this reserves WHOLE, non-overlapping
        real decision windows:

            same capture             = YES (the whole point of the diagnostic)
            same real decision window = NO
            shared bursts             = NO

        For each real capture with >=2 real decision windows (computed via
        the SAME group_examples_into_windows() run_decision_windows() itself
        uses -- never a second windowing formula), the FIRST half of its
        window indexes (deterministic, ascending order -- never chosen by
        any result) is reserved for fitting (split="TRAIN"), the SECOND half
        for the diagnostic role (split="VALIDATION"). A capture contributing to
        one role always contributes to the other too (grouped and split
        per-capture, never per-session), so capture_ids_train ==
        capture_ids_diagnostic holds by construction, and the two window-id
        sets are disjoint by construction.

        Today's real closed-set corpus captures are short enough that every
        one produces at most 1 complete window -- this NEVER fabricates a
        result for that case: split_status becomes NOT_FEASIBLE with
        infeasibility_reason starting 'NOT_AVAILABLE_FOR_WINDOW_LEVEL_
        DEPENDENT_DIAGNOSTIC' when no real capture has 2 real windows. The
        definitive campaign's real 120-second/12-window captures are exactly
        what this is built for -- no new window duration or decision unit is
        introduced, reuses the study's own already-frozen 10-second rule."""
        # Imported lazily (not at module level) to avoid a circular import:
        # ..inference imports ..training, which imports this module.
        from ..inference.decision_windows import (
            DEFAULT_MINIMUM_ELIGIBLE_BURSTS,
            DEFAULT_WINDOW_DURATION_S,
            group_examples_into_windows,
        )
        if window_duration_s is None:
            window_duration_s = DEFAULT_WINDOW_DURATION_S
        if minimum_eligible_bursts is None:
            minimum_eligible_bursts = DEFAULT_MINIMUM_ELIGIBLE_BURSTS
        by_id = {e.example_id: e for e in examples}
        train_example_ids = {a.example_id for a in confirmatory_split.assignments if a.split == "TRAIN"}
        by_capture: dict[str, list[ExampleRecord]] = {}
        for example_id in train_example_ids:
            example = by_id.get(example_id)
            if example is not None:
                by_capture.setdefault(example.capture_id, []).append(example)

        policy = "rq1_window_level_diagnostic:same_capture_disjoint_windows"
        assignments: list[SplitAssignment] = []
        for capture_id, capture_examples in by_capture.items():
            windows = group_examples_into_windows(capture_examples, window_duration_s)
            eligible = {key: exs for key, exs in windows.items() if len(exs) >= minimum_eligible_bursts}
            if len(eligible) < 2:
                continue  # this real capture cannot support BOTH roles without overlap -- skipped, never forced
            # Deterministic, real, never result-dependent: ascending window_index order.
            ordered_keys = sorted(eligible.keys(), key=lambda key: key[1])
            midpoint = len(ordered_keys) // 2
            for key in ordered_keys[:midpoint]:
                window_id = f"{key[0]}-decision-win-{key[1]:05d}"
                for example in eligible[key]:
                    assignments.append(SplitAssignment(
                        example_id=example.example_id, physical_unit_id=example.physical_unit_id, capture_id=example.capture_id,
                        session_id=example.session_id, split="TRAIN", split_reason=f"{policy}:window={window_id}:fitting",
                    ))
            for key in ordered_keys[midpoint:]:
                window_id = f"{key[0]}-decision-win-{key[1]:05d}"
                for example in eligible[key]:
                    assignments.append(SplitAssignment(
                        example_id=example.example_id, physical_unit_id=example.physical_unit_id, capture_id=example.capture_id,
                        session_id=example.session_id, split="VALIDATION", split_reason=f"{policy}:window={window_id}:diagnostic",
                    ))

        if not assignments:
            reason = (
                "NOT_AVAILABLE_FOR_WINDOW_LEVEL_DEPENDENT_DIAGNOSTIC: no real capture in the CONFIRMATORY-TRAIN "
                f"population has >=2 real, non-overlapping {window_duration_s:.0f}-second decision windows "
                f"(>={minimum_eligible_bursts} eligible burst(s) each) to reserve separately for fitting and "
                "diagnostic roles without overlap or shared bursts -- every real capture in the current corpus "
                "produces at most 1 complete decision window. Requires the definitive campaign's longer real "
                "captures (e.g. 120s/12 real 10s windows); never fabricated from the current short captures."
            )
            return self._not_feasible(dataset, scientific_task, policy, reason, created_at, [], split_purpose="RQ1_WINDOW_LEVEL_ACQUISITION_DEPENDENCE_DIAGNOSTIC")

        leakage = self._compute_leakage(assignments, by_id)
        return self._finalize(
            dataset, scientific_task, policy, assignments, leakage, created_at, by_id, [],
            enforce_leakage_gate=False, split_purpose="RQ1_WINDOW_LEVEL_ACQUISITION_DEPENDENCE_DIAGNOSTIC",
        )

    # ------------------------------------------------------------------

    def _sessions_by_unit(self, examples: list[ExampleRecord]) -> dict[str, dict[str, list[ExampleRecord]]]:
        result: dict[str, dict[str, list[ExampleRecord]]] = {}
        for example in examples:
            if not example.physical_unit_id:
                continue
            result.setdefault(example.physical_unit_id, {}).setdefault(example.session_id, []).append(example)
        return result

    def _closed_set_classification(
        self, dataset: DatasetManifest, examples: list[ExampleRecord], scientific_task: str, created_at: str, channel_excluded_ids: list[str],
    ) -> SplitManifest:
        policy = "session_disjoint_per_unit:channel_37_only"
        sessions_by_unit = self._sessions_by_unit(examples)
        ready_units = {unit: sessions for unit, sessions in sessions_by_unit.items() if len(sessions) >= _MIN_SESSIONS_PER_UNIT}
        if len(sessions_by_unit) < 2 or len(ready_units) < 2:
            reason = (
                f"{scientific_task} requires >=2 physical units, each with >={_MIN_SESSIONS_PER_UNIT} independent "
                f"sessions (one per split); found {len(sessions_by_unit)} unit(s) total, {len(ready_units)} with enough sessions."
            )
            return self._not_feasible(dataset, scientific_task, policy, reason, created_at, channel_excluded_ids)

        # Real gap found and fixed here: this used to always send exactly the
        # FIRST sorted session to TRAIN, the SECOND to VALIDATION, the THIRD
        # to TEST, and every remaining session (4th onward) to TRAIN too --
        # so a unit with 30 real sessions still got a VALIDATION/TEST
        # evaluation resting on exactly one session each, identical to a unit
        # with the bare minimum of 3. More captured sessions only ever grew
        # TRAIN, never made the held-out evaluation more statistically
        # robust -- confirmed the hard way: a real identity-training run
        # collapsed to 0.0 recall on VALIDATION for classes with few
        # sessions while hitting 1.0 on TRAIN, and adding sessions elsewhere
        # in the same run did nothing to fix that because those splits
        # never grew. Now VALIDATION and TEST each get a session count
        # proportional to how many sessions this unit actually has
        # (_VAL_TEST_SESSION_FRACTION each, rounded, minimum 1), so five
        # times more data means a five-times-more-independent evaluation,
        # not just a bigger TRAIN. At the minimum feasible count (3
        # sessions) this still resolves to exactly 1/1/1, unchanged from
        # before.
        assignments: list[SplitAssignment] = []
        for unit, sessions in ready_units.items():
            session_ids = sorted(sessions.keys())
            n = len(session_ids)
            n_val = max(1, round(n * _VAL_TEST_SESSION_FRACTION))
            n_test = max(1, round(n * _VAL_TEST_SESSION_FRACTION))
            if n - n_val - n_test < 1:
                n_val = n_test = 1
            val_ids = session_ids[:n_val]
            test_ids = session_ids[n_val:n_val + n_test]
            train_ids = session_ids[n_val + n_test:]
            for split_name, split_session_ids in (("TRAIN", train_ids), ("VALIDATION", val_ids), ("TEST", test_ids)):
                for session_id in split_session_ids:
                    for example in sessions[session_id]:
                        assignments.append(SplitAssignment(example_id=example.example_id, physical_unit_id=unit, capture_id=example.capture_id, session_id=session_id, split=split_name, split_reason=policy))

        leakage = self._compute_leakage(assignments, {e.example_id: e for e in examples})
        return self._finalize(dataset, scientific_task, policy, assignments, leakage, created_at, {e.example_id: e for e in examples}, channel_excluded_ids)

    def _target_vs_background(
        self, dataset: DatasetManifest, examples: list[ExampleRecord], created_at: str, channel_excluded_ids: list[str],
    ) -> SplitManifest:
        scientific_task, policy = "TARGET_VS_BACKGROUND", "target_background_session_disjoint:channel_37_only"
        target_examples = [e for e in examples if e.physical_unit_id]
        # A background example is only trustworthy negative evidence when its
        # OWN capture was declared BACKGROUND_TARGET_OFF or BACKGROUND_GENERAL
        # (denormalized onto the example itself at evidence-build time,
        # EvidenceStage) -- an example with no physical_unit_id from a
        # TARGET_DEVICE_ON capture just means the address never matched THAT
        # session, never that the device was confirmed absent. See module
        # docstring.
        background_examples = [e for e in examples if not e.physical_unit_id and e.capture_purpose in ("BACKGROUND_TARGET_OFF", "BACKGROUND_GENERAL")]
        target_sessions = sorted({e.session_id for e in target_examples})
        background_sessions = sorted({e.session_id for e in background_examples})

        if len(target_sessions) < _MIN_TARGET_SESSIONS:
            reason = f"{scientific_task} requires >={_MIN_TARGET_SESSIONS} independent target sessions (one per split); found {len(target_sessions)}."
            return self._not_feasible(dataset, scientific_task, policy, reason, created_at, channel_excluded_ids)
        if len(background_sessions) < _MIN_BACKGROUND_SESSIONS:
            reason = (
                f"{scientific_task} requires >={_MIN_BACKGROUND_SESSIONS} independent BACKGROUND_ENVIRONMENT-declared "
                f"session(s) (one per split -- TRAIN/VALIDATION/TEST all need a real background example, never just "
                f"VALIDATION/TEST); found {len(background_sessions)}. Captures whose evidence simply did not match a "
                "registered address do not count -- only a capture where the operator explicitly confirmed the "
                "target was off/removed does."
            )
            return self._not_feasible(dataset, scientific_task, policy, reason, created_at, channel_excluded_ids)

        assignments: list[SplitAssignment] = []
        for idx, session_id in enumerate(target_sessions):
            split = _SPLIT_NAMES[idx] if idx < 3 else "TRAIN"
            for example in target_examples:
                if example.session_id == session_id:
                    assignments.append(SplitAssignment(example_id=example.example_id, physical_unit_id=example.physical_unit_id, capture_id=example.capture_id, session_id=session_id, split=split, split_reason=policy))

        # Both classes are now genuinely distributed across all three splits
        # -- a real, deliberate change from the previous "negatives never in
        # TRAIN" design, which left every classifier trained on one class
        # alone (see module docstring).
        for idx, session_id in enumerate(background_sessions):
            split = _SPLIT_NAMES[idx] if idx < 3 else "TRAIN"
            for example in background_examples:
                if example.session_id == session_id:
                    assignments.append(SplitAssignment(example_id=example.example_id, physical_unit_id=None, capture_id=example.capture_id, session_id=session_id, split=split, split_reason=f"{policy}:background_environment_declared"))

        leakage = self._compute_leakage(assignments, {e.example_id: e for e in examples})
        return self._finalize(dataset, scientific_task, policy, assignments, leakage, created_at, {e.example_id: e for e in examples}, channel_excluded_ids)

    def _unknown_device_rejection(
        self, dataset: DatasetManifest, examples: list[ExampleRecord], created_at: str, channel_excluded_ids: list[str],
    ) -> SplitManifest:
        scientific_task, policy = "UNKNOWN_DEVICE_REJECTION", "known_vs_unknown_session_disjoint:channel_37_only"
        known_examples = [e for e in examples if e.physical_unit_id]
        unknown_examples = [e for e in examples if not e.physical_unit_id]
        sessions_by_unit = self._sessions_by_unit(known_examples)
        ready_units = {unit: sessions for unit, sessions in sessions_by_unit.items() if len(sessions) >= _MIN_SESSIONS_PER_UNIT}
        unknown_sessions = sorted({e.session_id for e in unknown_examples})

        if not ready_units:
            reason = f"{scientific_task} requires >=1 known physical unit with >={_MIN_SESSIONS_PER_UNIT} independent sessions; none found."
            return self._not_feasible(dataset, scientific_task, policy, reason, created_at, channel_excluded_ids)
        if len(unknown_sessions) < _MIN_UNKNOWN_SESSIONS:
            reason = f"{scientific_task} requires >={_MIN_UNKNOWN_SESSIONS} independent 'unknown device' sessions (split across VALIDATION/TEST only, never TRAIN); found {len(unknown_sessions)}."
            return self._not_feasible(dataset, scientific_task, policy, reason, created_at, channel_excluded_ids)

        assignments: list[SplitAssignment] = []
        for unit, sessions in ready_units.items():
            for idx, session_id in enumerate(sorted(sessions.keys())):
                split = _SPLIT_NAMES[idx] if idx < 3 else "TRAIN"
                for example in sessions[session_id]:
                    assignments.append(SplitAssignment(example_id=example.example_id, physical_unit_id=unit, capture_id=example.capture_id, session_id=session_id, split=split, split_reason=policy))

        non_train = ("VALIDATION", "TEST")
        for idx, session_id in enumerate(unknown_sessions):
            split = non_train[idx % 2]
            for example in unknown_examples:
                if example.session_id == session_id:
                    assignments.append(SplitAssignment(example_id=example.example_id, physical_unit_id=None, capture_id=example.capture_id, session_id=session_id, split=split, split_reason=f"{policy}:unknowns_never_in_train"))

        leakage = self._compute_leakage(assignments, {e.example_id: e for e in examples})
        return self._finalize(dataset, scientific_task, policy, assignments, leakage, created_at, {e.example_id: e for e in examples}, channel_excluded_ids)

    # ------------------------------------------------------------------

    def _leakage_value(self, example: ExampleRecord, field: str) -> str:
        if field == "sample_range":
            return f"{example.source_iq_sha256}:{example.iq_start_sample}:{example.iq_end_sample}"
        return str(getattr(example, field))

    def _compute_leakage(self, assignments: list[SplitAssignment], examples_by_id: dict[str, ExampleRecord]) -> LeakageCheckResult:
        value_to_splits: dict[str, dict[str, set[str]]] = {field: {} for field in _LEAKAGE_FIELDS}
        for assignment in assignments:
            example = examples_by_id[assignment.example_id]
            for field in _LEAKAGE_FIELDS:
                value = self._leakage_value(example, field)
                value_to_splits[field].setdefault(value, set()).add(assignment.split)

        overlapping: dict[str, list[str]] = {}
        for field, mapping in value_to_splits.items():
            bad = sorted(value for value, splits in mapping.items() if len(splits) > 1)
            if bad:
                overlapping[field] = bad

        return LeakageCheckResult(
            status="FAILED" if overlapping else "PASSED",
            checked_group_fields=_LEAKAGE_FIELDS,
            overlapping_keys=overlapping,
            evidence=f"Checked {len(assignments)} assignment(s) across {len(examples_by_id)} example(s).",
        )

    def _not_feasible(
        self, dataset: DatasetManifest, scientific_task: str, policy: str, reason: str, created_at: str, channel_excluded_ids: list[str],
        *, split_purpose: SplitPurpose = "CONFIRMATORY",
    ) -> SplitManifest:
        manifest = SplitManifest(
            dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version, scientific_task=scientific_task, policy=policy,
            split_status="NOT_FEASIBLE", infeasibility_reason=reason, assignments=[],
            leakage_check=LeakageCheckResult(status="NOT_EXECUTED"), created_at=created_at,
            channel_scope_excluded_example_ids=channel_excluded_ids,
            split_purpose=split_purpose, non_confirmatory=(split_purpose != "CONFIRMATORY"),
        )
        sha256 = manifest.content_hash(exclude=_HASH_EXCLUDED_FIELDS)
        return manifest.model_copy(update={"split_manifest_sha256": sha256})

    def _finalize(
        self, dataset: DatasetManifest, scientific_task: str, policy: str, assignments: list[SplitAssignment],
        leakage: LeakageCheckResult, created_at: str, examples_by_id: dict[str, ExampleRecord], channel_excluded_ids: list[str],
        *, enforce_leakage_gate: bool = True, split_purpose: SplitPurpose = "CONFIRMATORY",
    ) -> SplitManifest:
        if leakage.status == "FAILED" and enforce_leakage_gate:
            split_status, infeasibility_reason = "NOT_FEASIBLE", f"Leakage check failed on field(s): {sorted(leakage.overlapping_keys.keys())}"
        else:
            # One common, task-agnostic gate: no classifier training is ever
            # scientifically meaningful with a single label in TRAIN,
            # regardless of which scientific_task asked for it or which
            # model library happens to tolerate a single class silently
            # (sklearn's LogisticRegression/SVC raise; RandomForestClassifier
            # and the CNN trainers do not -- this must not depend on that).
            train_labels = {train_label_for(scientific_task, examples_by_id[a.example_id]) for a in assignments if a.split == "TRAIN"}
            if len(train_labels) < 2:
                split_status, infeasibility_reason = "NOT_FEASIBLE", (
                    f"TRAINING_REQUIRES_AT_LEAST_TWO_CLASSES: TRAIN contains only {sorted(train_labels)}. "
                    "A model trained on a single class cannot be scientifically evaluated -- this blocks every "
                    "candidate model type uniformly, not just the ones whose library happens to raise on its own."
                )
            else:
                # Split-completeness correction (2026-08-08): a VALIDATION/TEST
                # missing real support for a class TRAIN has makes
                # balanced_accuracy/macro_f1 silently biased for that split
                # (a class with zero true instances there still enters the
                # macro-average as recall=0, per evaluator.py's own
                # documented, deliberately-unchanged definition) -- the fix
                # belongs here, at split-completeness gating, never by
                # excluding no-support classes from the metric formula
                # itself (that would hide the real gap instead of blocking
                # on it). UNKNOWN_DEVICE_REJECTION's "UNKNOWN" pseudo-label
                # is fine appearing in VALIDATION/TEST only -- this checks
                # the TRAIN-to-VALIDATION/TEST direction alone, never the
                # reverse.
                val_labels = {train_label_for(scientific_task, examples_by_id[a.example_id]) for a in assignments if a.split == "VALIDATION"}
                missing_in_val = train_labels - val_labels
                # A non-CONFIRMATORY split (e.g. RQ1's dependence diagnostic)
                # never populates a TEST role by design -- it is TRAIN/
                # VALIDATION only and is never eligible for TEST/FUTURE_TEST
                # regardless, so checking TEST completeness on it would
                # reject it for a role it was never supposed to have.
                if split_purpose == "CONFIRMATORY":
                    test_labels = {train_label_for(scientific_task, examples_by_id[a.example_id]) for a in assignments if a.split == "TEST"}
                    missing_in_test = train_labels - test_labels
                else:
                    missing_in_test = set()
                if missing_in_val or missing_in_test:
                    split_status, infeasibility_reason = "NOT_FEASIBLE", (
                        f"SPLIT_INCOMPLETE_MISSING_CLASS_SUPPORT: VALIDATION missing {sorted(missing_in_val)}, "
                        f"TEST missing {sorted(missing_in_test)}. A class with zero true instances in a split "
                        "cannot be scientifically evaluated there -- balanced_accuracy/macro_f1 are only "
                        "meaningful when every TRAIN class also has real support in VALIDATION and TEST."
                    )
                else:
                    split_status, infeasibility_reason = "READY", None
        manifest = SplitManifest(
            dataset_id=dataset.dataset_id, dataset_version=dataset.dataset_version, scientific_task=scientific_task, policy=policy,
            split_status=split_status, infeasibility_reason=infeasibility_reason, assignments=assignments, leakage_check=leakage, created_at=created_at,
            channel_scope_excluded_example_ids=channel_excluded_ids,
            split_purpose=split_purpose, non_confirmatory=(split_purpose != "CONFIRMATORY"),
        )
        sha256 = manifest.content_hash(exclude=_HASH_EXCLUDED_FIELDS)
        return manifest.model_copy(update={"split_manifest_sha256": sha256})
