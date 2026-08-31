from __future__ import annotations

import numpy as np
import pytest

from app.modules.ble_rffi_studio.contracts import ExampleRecord
from app.modules.ble_rffi_studio.dataset import DatasetBuilder
from app.modules.ble_rffi_studio.quality import DatasetAnalyzer

from ._helpers import make_example


@pytest.fixture
def analyzer():
    return DatasetAnalyzer()


def test_no_duplicates_or_overlap_passes_both_checks(analyzer):
    examples = [
        make_example(example_index=1, physical_unit_id="U1", session_id="S1", iq_start_sample=0, iq_end_sample=100),
        make_example(example_index=2, physical_unit_id="U1", session_id="S1", iq_start_sample=200, iq_end_sample=300),
    ]
    assert analyzer.check_exact_duplicates(examples).status == "PASSED"
    assert analyzer.check_sample_overlap(examples).status == "PASSED"


def test_exact_duplicate_is_detected_by_identical_evidence_identity(analyzer):
    a = make_example(example_index=1, physical_unit_id="U1", session_id="S1", iq_start_sample=0, iq_end_sample=100, candidate_id="cand-x", packet_id="pkt-x", source_iq_sha256="sha-a")
    # Same identity fields -> same example_id -> a real exact duplicate.
    b = make_example(example_index=1, physical_unit_id="U1", session_id="S1", iq_start_sample=0, iq_end_sample=100, candidate_id="cand-x", packet_id="pkt-x", source_iq_sha256="sha-a")
    assert a.example_id == b.example_id

    result = analyzer.check_exact_duplicates([a, b])
    assert result.status == "FAILED"
    assert sorted(result.duplicate_groups[0]) == sorted([a.example_id, b.example_id])


def test_sample_overlap_is_detected_for_non_identical_overlapping_ranges(analyzer):
    a = make_example(example_index=1, physical_unit_id="U1", session_id="S1", iq_start_sample=0, iq_end_sample=100, source_iq_sha256="sha-a")
    b = make_example(example_index=2, physical_unit_id="U1", session_id="S1", iq_start_sample=50, iq_end_sample=150, source_iq_sha256="sha-a")
    result = analyzer.check_sample_overlap([a, b])
    assert result.status == "FAILED"
    assert sorted([a.example_id, b.example_id]) in [sorted(pair) for pair in result.overlapping_pairs]


def test_sample_overlap_ignores_different_source_files(analyzer):
    a = make_example(example_index=1, physical_unit_id="U1", session_id="S1", iq_start_sample=0, iq_end_sample=100, source_iq_sha256="sha-a")
    b = make_example(example_index=2, physical_unit_id="U1", session_id="S1", iq_start_sample=50, iq_end_sample=150, source_iq_sha256="sha-b")
    assert analyzer.check_sample_overlap([a, b]).status == "PASSED"


def test_near_duplicates_without_iq_paths_is_not_executed(analyzer):
    examples = [make_example(example_index=1, physical_unit_id="U1", session_id="S1")]
    result = analyzer.check_near_duplicates(examples)
    assert result.status == "NOT_EXECUTED"


def test_near_duplicates_flags_identical_synthetic_iq_windows(analyzer, tmp_path):
    # Two examples pointing at overlapping-but-not-identical ranges of a
    # synthetic complex64 file where the underlying samples are IDENTICAL --
    # a strong near-duplicate signal the diagnostic should catch.
    rng = np.random.default_rng(42)
    samples = (rng.standard_normal(4000) + 1j * rng.standard_normal(4000)).astype(np.complex64)
    iq_path = tmp_path / "synthetic.cf32"
    samples.tofile(iq_path)

    a = make_example(example_index=1, physical_unit_id="U1", session_id="S1", capture_id="CAP-1", iq_start_sample=0, iq_end_sample=1000, source_iq_sha256="sha-synth")
    b = make_example(example_index=2, physical_unit_id="U1", session_id="S1", capture_id="CAP-1", iq_start_sample=2000, iq_end_sample=3000, source_iq_sha256="sha-synth")
    # Force b's window to be a byte-identical copy of a's window by writing
    # the same slice at both offsets.
    samples[2000:3000] = samples[0:1000]
    samples.tofile(iq_path)

    result = analyzer.check_near_duplicates([a, b], capture_iq_paths={"CAP-1": iq_path})
    assert result.status == "DIAGNOSTIC_CHECK"
    assert sorted([a.example_id, b.example_id]) in [sorted(pair) for pair in result.flagged_pairs]


def test_near_duplicates_never_reports_failed_status(analyzer, tmp_path):
    rng = np.random.default_rng(7)
    samples = (rng.standard_normal(2000) + 1j * rng.standard_normal(2000)).astype(np.complex64)
    iq_path = tmp_path / "synthetic.cf32"
    samples.tofile(iq_path)
    a = make_example(example_index=1, physical_unit_id="U1", session_id="S1", capture_id="CAP-1", iq_start_sample=0, iq_end_sample=500, source_iq_sha256="sha-synth")
    b = make_example(example_index=2, physical_unit_id="U1", session_id="S1", capture_id="CAP-1", iq_start_sample=1000, iq_end_sample=1500, source_iq_sha256="sha-synth")
    result = analyzer.check_near_duplicates([a, b], capture_iq_paths={"CAP-1": iq_path})
    assert result.status in ("DIAGNOSTIC_CHECK", "NOT_EXECUTED")  # structurally cannot be FAILED


def test_build_gate_rejects_when_exact_duplicates_found(analyzer, tmp_path):
    a = make_example(example_index=1, physical_unit_id="U1", session_id="S1", candidate_id="c", packet_id="p", iq_start_sample=0, iq_end_sample=100, source_iq_sha256="sha")
    b = make_example(example_index=1, physical_unit_id="U1", session_id="S1", candidate_id="c", packet_id="p", iq_start_sample=0, iq_end_sample=100, source_iq_sha256="sha")
    builder = DatasetBuilder(tmp_path / "datasets")
    draft = builder.build_draft(dataset_id="DS1", dataset_version="1.0.0", project_id="P1", campaign_id="C1", examples=[a, b], data_origin="REAL_B200", creation_policy={}, created_at="2026-07-26T00:00:00Z")

    exact = analyzer.check_exact_duplicates([a, b])
    overlap = analyzer.check_sample_overlap([a, b])
    near = analyzer.check_near_duplicates([a, b])
    report = analyzer.build_gate(draft, exact, overlap, near, created_at="2026-07-26T00:00:00Z")

    assert report.gate_decision == "NOT_ACCEPTED_FOR_TRAINING"
    assert report.gate_reasons


def test_build_gate_accepts_a_clean_dataset(analyzer, tmp_path):
    examples = [make_example(example_index=i, physical_unit_id="U1", session_id="S1", iq_start_sample=i * 1000, iq_end_sample=i * 1000 + 500) for i in range(3)]
    builder = DatasetBuilder(tmp_path / "datasets")
    draft = builder.build_draft(dataset_id="DS1", dataset_version="1.0.0", project_id="P1", campaign_id="C1", examples=examples, data_origin="REAL_B200", creation_policy={}, created_at="2026-07-26T00:00:00Z")

    exact = analyzer.check_exact_duplicates(examples)
    overlap = analyzer.check_sample_overlap(examples)
    near = analyzer.check_near_duplicates(examples)
    report = analyzer.build_gate(draft, exact, overlap, near, created_at="2026-07-26T00:00:00Z")

    assert report.gate_decision == "ACCEPTED_FOR_TRAINING"


def test_resolve_overlaps_keeps_one_of_an_exact_duplicate_pair(analyzer):
    a = make_example(example_index=1, physical_unit_id="U1", session_id="S1", candidate_id="c", packet_id="p", iq_start_sample=0, iq_end_sample=100, source_iq_sha256="sha")
    b = make_example(example_index=1, physical_unit_id="U1", session_id="S1", candidate_id="c", packet_id="p", iq_start_sample=0, iq_end_sample=100, source_iq_sha256="sha")
    assert a.example_id == b.example_id  # a real exact duplicate by construction

    excluded = analyzer.resolve_overlaps([a, b])
    # Both ExampleRecords share the same example_id (that IS the duplicate),
    # so exactly one KEY is excluded regardless of how many rows produced it.
    assert set(excluded) == {a.example_id}
    assert "SUPERSEDED_BY_DUPLICATE_RESOLUTION" in excluded[a.example_id]


def test_resolve_overlaps_keeps_the_maximum_non_overlapping_subset(analyzer):
    # Real reported case: two independently decoded, non-identical packets
    # inside the same burst window overlap 95%+ -- resolve_overlaps must
    # exclude exactly one of them (never both, never neither) so the
    # remaining set passes check_sample_overlap().
    a = make_example(example_index=1, physical_unit_id="U1", session_id="S1", candidate_id="cand-1", packet_id="pkt-a", iq_start_sample=0, iq_end_sample=1000, source_iq_sha256="sha")
    b = make_example(example_index=2, physical_unit_id="U1", session_id="S1", candidate_id="cand-1", packet_id="pkt-b", iq_start_sample=50, iq_end_sample=1050, source_iq_sha256="sha")
    c = make_example(example_index=3, physical_unit_id="U1", session_id="S1", candidate_id="cand-2", packet_id="pkt-c", iq_start_sample=5000, iq_end_sample=6000, source_iq_sha256="sha")

    excluded = analyzer.resolve_overlaps([a, b, c])
    assert len(excluded) == 1
    assert c.example_id not in excluded  # never touches the independent, non-overlapping example
    assert set(excluded).issubset({a.example_id, b.example_id})

    remaining = [e for e in [a, b, c] if e.example_id not in excluded]
    assert analyzer.check_sample_overlap(remaining).status == "PASSED"


def test_resolve_overlaps_is_idempotent_and_finds_nothing_on_a_clean_set(analyzer):
    examples = [make_example(example_index=i, physical_unit_id="U1", session_id="S1", iq_start_sample=i * 1000, iq_end_sample=i * 1000 + 500) for i in range(3)]
    assert analyzer.resolve_overlaps(examples) == {}


def test_build_gate_rejects_an_empty_dataset(analyzer, tmp_path):
    builder = DatasetBuilder(tmp_path / "datasets")
    draft = builder.build_draft(dataset_id="DS1", dataset_version="1.0.0", project_id="P1", campaign_id="C1", examples=[], data_origin="REAL_B200", creation_policy={}, created_at="2026-07-26T00:00:00Z")
    exact = analyzer.check_exact_duplicates([])
    overlap = analyzer.check_sample_overlap([])
    near = analyzer.check_near_duplicates([])
    report = analyzer.build_gate(draft, exact, overlap, near, created_at="2026-07-26T00:00:00Z")
    assert report.gate_decision == "NOT_ACCEPTED_FOR_TRAINING"
