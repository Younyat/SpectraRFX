"""RQ4 packet-content artifacts (2026-08-08, corrected at point 4):
reproducible BLE-field-to-sample mapping and the three derived variants
(FULL_BURST/ADVA_EXCLUDED/PRE_PDU), all built from the same original IQ,
original always preserved. ADVA_EXCLUDED genuinely splices the AdvA range
OUT (a shorter array), never zero-fills it in place -- a fixed-position,
fixed-size zero block would itself be a trivially learnable artificial
feature.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.infrastructure.ble.capture.ble_offline_replay import write_jsonl
from app.modules.ble_rffi_studio.packet_content import build_packet_content_variants_for_examples, region_restricted_provider_and_eligible_ids
from app.modules.ble_rffi_studio.packet_content.field_mapping import (
    PRE_PDU_BITS,
    derive_packet_content_variants,
    pdu_field_sample_ranges,
)

from ._helpers import make_example

SAMPLE_RATE = 4_000_000.0  # 4 samples/bit at 1 Mbit/s BLE LE 1M PHY


def test_pdu_field_sample_ranges_are_reproducible_pure_arithmetic():
    a = pdu_field_sample_ranges(packet_start_sample=1000, sample_rate_sps=SAMPLE_RATE, pdu_type_name="ADV_IND")
    b = pdu_field_sample_ranges(packet_start_sample=1000, sample_rate_sps=SAMPLE_RATE, pdu_type_name="ADV_IND")
    assert a == b


def test_pdu_field_sample_ranges_layout_matches_the_ble_spec_bit_widths():
    ranges = pdu_field_sample_ranges(packet_start_sample=0, sample_rate_sps=SAMPLE_RATE, pdu_type_name="ADV_IND")
    # 4 samples/bit: preamble=8 bits=32 samples, access_address=32 bits=128 samples,
    # pdu_header=16 bits=64 samples, adv_address=48 bits=192 samples.
    assert (ranges["preamble"].start_sample, ranges["preamble"].end_sample) == (0, 32)
    assert (ranges["access_address"].start_sample, ranges["access_address"].end_sample) == (32, 160)
    assert (ranges["pdu_header"].start_sample, ranges["pdu_header"].end_sample) == (160, 224)
    assert (ranges["adv_address"].start_sample, ranges["adv_address"].end_sample) == (224, 416)
    # pre-PDU is exactly preamble+access_address, matching the paper's own
    # "raw_iq_pre_pdu" input_type (scientific_basis/technique_registry.json).
    assert PRE_PDU_BITS == 40


def test_pdu_field_sample_ranges_offsets_by_packet_start_sample():
    ranges = pdu_field_sample_ranges(packet_start_sample=5000, sample_rate_sps=SAMPLE_RATE, pdu_type_name="ADV_IND")
    assert ranges["preamble"].start_sample == 5000
    assert ranges["adv_address"].start_sample == 5000 + 224


@pytest.mark.parametrize("pdu_type", ["CONNECT_IND", "AUX_CONNECT_REQ", None, "SOME_UNKNOWN_TYPE"])
def test_adv_address_is_none_for_pdu_types_without_a_verified_leading_offset(pdu_type):
    ranges = pdu_field_sample_ranges(packet_start_sample=0, sample_rate_sps=SAMPLE_RATE, pdu_type_name=pdu_type)
    assert ranges["adv_address"] is None


def test_derive_packet_content_variants_full_burst_is_always_the_original_untouched():
    window = np.arange(400, dtype=np.complex64) + 1j
    variants = derive_packet_content_variants(iq_window=window, iq_start_sample=0, sample_rate_sps=SAMPLE_RATE, pdu_type_name="ADV_IND")
    np.testing.assert_array_equal(variants["FULL_BURST"], window)
    assert variants["FULL_BURST"] is window  # not even a copy -- the original, unmodified


def test_derive_packet_content_variants_excludes_the_adv_address_samples_by_splicing_them_out():
    window = np.arange(400, dtype=np.complex64) + 1j
    variants = derive_packet_content_variants(iq_window=window, iq_start_sample=0, sample_rate_sps=SAMPLE_RATE, pdu_type_name="ADV_IND")
    artifact = variants["ADVA_EXCLUDED"]
    assert artifact is not None
    # 192 samples (224:416, clipped to the 400-sample window -> 224:400 = 176
    # samples) genuinely removed -- the result is SHORTER, never zero-filled.
    assert artifact.derived_analytical_region_length == 400 - 176
    assert len(artifact.window) == artifact.derived_analytical_region_length
    # No exact-zero block anywhere -- nothing stands in for the removed span.
    assert not np.any(artifact.window == 0)
    # Everything before the exclusion is untouched and in the same order.
    np.testing.assert_array_equal(artifact.window[:224], window[:224])
    # The original window passed in must never be mutated.
    np.testing.assert_array_equal(window, np.arange(400, dtype=np.complex64) + 1j)


def test_adva_excluded_records_the_real_provenance_chain():
    window = np.ones(400, dtype=np.complex64)
    variants = derive_packet_content_variants(iq_window=window, iq_start_sample=5000, sample_rate_sps=SAMPLE_RATE, pdu_type_name="ADV_IND")
    artifact = variants["ADVA_EXCLUDED"]
    assert artifact.original_sample_range == (5000, 5400)
    assert artifact.excluded_adva_sample_range == (5224, 5400)  # clipped to the window's real end
    assert artifact.length_recovery_rule == "REPRESENTATION_OWN_ZERO_PAD_AT_END"


def test_derive_packet_content_variants_adva_excluded_is_none_for_unmapped_pdu_types():
    window = np.ones(400, dtype=np.complex64)
    variants = derive_packet_content_variants(iq_window=window, iq_start_sample=0, sample_rate_sps=SAMPLE_RATE, pdu_type_name="CONNECT_IND")
    assert variants["ADVA_EXCLUDED"] is None
    # FULL_BURST and PRE_PDU are still real even when ADVA_EXCLUDED is not.
    assert variants["FULL_BURST"] is window
    assert len(variants["PRE_PDU"]) == 160  # 40 bits * 4 samples/bit


def test_adva_excluded_recovers_representation_length_via_the_same_zero_pad_convention():
    """The deterministic length-recovery rule in practice: applying the
    SAME representation function used for FULL_BURST to the shorter
    ADVA_EXCLUDED window hits its own pre-existing zero-pad-at-end path --
    no special-casing, no marker of where the exclusion happened."""
    from app.modules.ble_rffi_studio.preprocessing.representation_profiles import raw_iq_representation

    window = np.ones(400, dtype=np.complex64)
    variants = derive_packet_content_variants(iq_window=window, iq_start_sample=0, sample_rate_sps=SAMPLE_RATE, pdu_type_name="ADV_IND")
    artifact = variants["ADVA_EXCLUDED"]

    target_length = 500  # longer than either variant, forcing zero-pad on both
    full_burst_repr = raw_iq_representation(variants["FULL_BURST"], target_length)
    excluded_repr = raw_iq_representation(artifact.window, target_length)
    assert full_burst_repr.shape == excluded_repr.shape == (2, target_length)


def test_derive_packet_content_variants_pre_pdu_is_clipped_to_a_short_window():
    window = np.ones(50, dtype=np.complex64)  # shorter than the 160-sample pre-PDU span
    variants = derive_packet_content_variants(iq_window=window, iq_start_sample=0, sample_rate_sps=SAMPLE_RATE, pdu_type_name="ADV_IND")
    assert len(variants["PRE_PDU"]) == 50  # clipped, never padded/fabricated


def test_build_packet_content_variants_for_examples_reads_the_real_ledgers_pdu_type(tmp_path):
    """End-to-end orchestration check: pdu_type comes from the SAME
    packet_association_ledger.jsonl EvidenceStage reads, never guessed or
    hardcoded, and a capture with no resolvable replay/ledger degrades to
    ADVA_EXCLUDED=None rather than raising."""
    legacy_capture_root = tmp_path / "captures"
    capture_dir = legacy_capture_root / "CAP-1"
    capture_dir.mkdir(parents=True)
    iq_path = capture_dir / "iq.cf32"
    (np.ones(400, dtype=np.complex64)).tofile(iq_path)

    ledger_dir = capture_dir / "offline_replays" / "run-1"
    ledger_dir.mkdir(parents=True)
    example = make_example(example_index=0, physical_unit_id="U1", session_id="S1", capture_id="CAP-1", candidate_id="cand-0", packet_id="pkt-0", iq_start_sample=0, iq_end_sample=400)
    write_jsonl(ledger_dir / "packet_association_ledger.jsonl", [{"packet_id": "pkt-0", "pdu_type": "ADV_IND"}])

    unresolvable_example = make_example(example_index=1, physical_unit_id="U1", session_id="S1", capture_id="CAP-NO-LEDGER", candidate_id="cand-1", packet_id="pkt-1", source_iq_sha256="sha-2", iq_start_sample=0, iq_end_sample=400)
    (legacy_capture_root / "CAP-NO-LEDGER").mkdir(parents=True)
    (np.ones(400, dtype=np.complex64)).tofile(legacy_capture_root / "CAP-NO-LEDGER" / "iq.cf32")

    capture_iq_paths = {"CAP-1": iq_path, "CAP-NO-LEDGER": legacy_capture_root / "CAP-NO-LEDGER" / "iq.cf32"}
    results = build_packet_content_variants_for_examples(
        [example, unresolvable_example], legacy_capture_root=legacy_capture_root, capture_iq_paths=capture_iq_paths,
    )

    assert results[example.example_id]["ADVA_EXCLUDED"] is not None
    assert results[example.example_id]["FULL_BURST"] is not None
    assert results[unresolvable_example.example_id]["ADVA_EXCLUDED"] is None
    assert results[unresolvable_example.example_id]["FULL_BURST"] is not None


def test_region_restricted_provider_and_eligible_ids_pre_pdu_is_real_for_every_example(tmp_path):
    """RQ4 region-specific fitting (2026-08-12): PRE_PDU never depends on a
    resolvable pdu_type -- both examples (one with a ledger, one without)
    must be eligible, and the provider must return the SAME real PRE_PDU
    array derive_packet_content_variants would."""
    legacy_capture_root = tmp_path / "captures"
    capture_dir = legacy_capture_root / "CAP-1"
    capture_dir.mkdir(parents=True)
    iq_path = capture_dir / "iq.cf32"
    (np.ones(400, dtype=np.complex64)).tofile(iq_path)

    example = make_example(example_index=0, physical_unit_id="U1", session_id="S1", capture_id="CAP-1", candidate_id="cand-0", packet_id="pkt-0", iq_start_sample=0, iq_end_sample=400)
    provider, eligible_ids = region_restricted_provider_and_eligible_ids(
        [example], analytical_region="PRE_PDU", legacy_capture_root=legacy_capture_root, capture_iq_paths={"CAP-1": iq_path},
    )
    assert eligible_ids == {example.example_id}
    window = provider(example)
    assert len(window) == 160  # 40 bits * 4 samples/bit, same as derive_packet_content_variants


def test_region_restricted_provider_and_eligible_ids_adva_excluded_excludes_unmapped_pdu_types(tmp_path):
    """A capture whose real ledger has no leading-AdvA PDU type yields
    ADVA_EXCLUDED=None for that example -- region_restricted_provider_and_eligible_ids
    must leave it out of BOTH the provider and the eligible set, never
    substitute a fallback window."""
    legacy_capture_root = tmp_path / "captures"
    capture_dir = legacy_capture_root / "CAP-1"
    capture_dir.mkdir(parents=True)
    iq_path = capture_dir / "iq.cf32"
    (np.ones(400, dtype=np.complex64)).tofile(iq_path)
    ledger_dir = capture_dir / "offline_replays" / "run-1"
    ledger_dir.mkdir(parents=True)
    write_jsonl(ledger_dir / "packet_association_ledger.jsonl", [
        {"packet_id": "pkt-adv", "pdu_type": "ADV_IND"}, {"packet_id": "pkt-connect", "pdu_type": "CONNECT_IND"},
    ])

    example_adv = make_example(example_index=0, physical_unit_id="U1", session_id="S1", capture_id="CAP-1", candidate_id="cand-0", packet_id="pkt-adv", iq_start_sample=0, iq_end_sample=400)
    example_connect = make_example(example_index=1, physical_unit_id="U1", session_id="S1", capture_id="CAP-1", candidate_id="cand-1", packet_id="pkt-connect", source_iq_sha256="sha-2", iq_start_sample=0, iq_end_sample=400)

    provider, eligible_ids = region_restricted_provider_and_eligible_ids(
        [example_adv, example_connect], analytical_region="ADVA_EXCLUDED", legacy_capture_root=legacy_capture_root, capture_iq_paths={"CAP-1": iq_path},
    )
    assert eligible_ids == {example_adv.example_id}
    assert len(provider(example_adv)) == 400 - 176  # spliced, matches derive_packet_content_variants' own math
