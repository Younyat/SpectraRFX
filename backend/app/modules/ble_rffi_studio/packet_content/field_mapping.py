"""RQ4 packet-content artifacts (2026-08-08, corrected at point 4):
reproducible BLE-field-to-sample mapping for a LE 1M PHY legacy advertising
PDU, derived from the SAME original IQ a burst's ExampleRecord already
points to -- FULL_BURST (the original window, unchanged), ADVA_EXCLUDED (the
AdvA sample range genuinely REMOVED from the analytical region, never
zero-filled), PRE_PDU (only the preamble+access-address portion, matching
scientific_basis/technique_registry.json's own "ble-rffi-industry5-2026"
entry, whose protocol input_type is literally "raw_iq_pre_pdu"). The
original window is never mutated in place and is always one of the returned
variants -- these are ADDITIONAL derived views, never a replacement.

Correction (point 4): the previous ADVA_MASKED variant zeroed the AdvA
sample range in place, leaving a fixed-size, fixed-position, exactly-zero
block in every masked burst -- an artificial, trivially learnable digital
pattern unrelated to any RF fingerprint, and itself a new spurious feature.
ADVA_EXCLUDED instead SPLICES the AdvA range OUT of the window entirely
(np.concatenate of the samples before and after it), producing a SHORTER
array with no synthetic content standing in for the removed span. Recovering
the fixed input length each representation needs is NOT special-cased here
-- it reuses the SAME zero-pad-at-end convention raw_iq_representation/
spectrogram_representation already apply to any window shorter than their
target length (see representation_profiles.py), so nothing marks WHERE the
exclusion happened; a short window looks identical whether it came from a
genuinely short burst or from an AdvA exclusion.

Field layout (Bluetooth Core Spec, Vol 6, Part B, 2.3 -- legacy advertising
PDU on LE 1M PHY, 1 bit == 1 microsecond):
    preamble        8 bits   (bits   0- 8)
    access_address 32 bits   (bits   8-40)
    pdu_header     16 bits   (bits  40-56)
    adv_address    48 bits   (bits  56-104)  -- ONLY for the PDU types below

adv_address is the PDU's first 48 payload bits ONLY for PDU types whose
layout puts AdvA immediately after the header (ADV_IND, ADV_NONCONN_IND,
ADV_SCAN_IND, ADV_DIRECT_IND, SCAN_RSP). CONNECT_IND/AUX_CONNECT_REQ put
InitA first and AdvA second (a different offset) and are deliberately
excluded here rather than guessed at the wrong offset.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_SYMBOL_RATE_HZ = 1_000_000.0  # BLE LE 1M PHY -- same constant evidence_stage.py/ble_offline_replay.py use.
_PREAMBLE_BITS = 8
_ACCESS_ADDRESS_BITS = 32
_PDU_HEADER_BITS = 16
_ADV_ADDRESS_BITS = 48

PRE_PDU_BITS = _PREAMBLE_BITS + _ACCESS_ADDRESS_BITS  # 40 -- where the PDU header starts
_ADV_ADDRESS_START_BITS = PRE_PDU_BITS + _PDU_HEADER_BITS  # 56
_ADV_ADDRESS_END_BITS = _ADV_ADDRESS_START_BITS + _ADV_ADDRESS_BITS  # 104

# PDU types where AdvA is the leading 48 payload bits right after the header.
PDU_TYPES_WITH_LEADING_ADVA = {"ADV_IND", "ADV_NONCONN_IND", "ADV_SCAN_IND", "ADV_DIRECT_IND", "SCAN_RSP"}

# Which derived sample region of an already-captured burst is analyzed --
# deliberately a DIFFERENT concept from CaptureRecord.packet_condition
# (ORIGINAL/CONTROLLED_VARIANT, what was physically transmitted). Renamed
# from PacketVariant (2026-08-09) because that name collided with
# packet_condition's old name (packet_variant) despite meaning something else.
AnalyticalRegion = str  # "FULL_BURST" | "ADVA_EXCLUDED" | "PRE_PDU"
LENGTH_RECOVERY_RULE = "REPRESENTATION_OWN_ZERO_PAD_AT_END"


def _bits_to_samples(bits: int, sample_rate_sps: float) -> int:
    return round(bits * sample_rate_sps / _SYMBOL_RATE_HZ)


@dataclass(frozen=True)
class FieldSampleRange:
    start_sample: int  # absolute, same coordinate space as ExampleRecord.iq_start_sample
    end_sample: int


def pdu_field_sample_ranges(*, packet_start_sample: int, sample_rate_sps: float, pdu_type_name: str | None) -> dict[str, FieldSampleRange | None]:
    """Reproducible: same (packet_start_sample, sample_rate_sps, pdu_type_name)
    always yields the same ranges -- pure arithmetic on the standard BLE
    field layout, no decoding or randomness involved. adv_address is None
    when pdu_type_name is not one of PDU_TYPES_WITH_LEADING_ADVA (including
    None/unknown) -- never a guessed offset for a PDU type this mapping does
    not have a verified layout for."""
    preamble_end = packet_start_sample + _bits_to_samples(_PREAMBLE_BITS, sample_rate_sps)
    access_address_end = packet_start_sample + _bits_to_samples(_PREAMBLE_BITS + _ACCESS_ADDRESS_BITS, sample_rate_sps)
    pdu_header_end = packet_start_sample + _bits_to_samples(PRE_PDU_BITS + _PDU_HEADER_BITS, sample_rate_sps)
    adv_address = None
    if pdu_type_name in PDU_TYPES_WITH_LEADING_ADVA:
        adv_address = FieldSampleRange(
            start_sample=packet_start_sample + _bits_to_samples(_ADV_ADDRESS_START_BITS, sample_rate_sps),
            end_sample=packet_start_sample + _bits_to_samples(_ADV_ADDRESS_END_BITS, sample_rate_sps),
        )
    return {
        "preamble": FieldSampleRange(packet_start_sample, preamble_end),
        "access_address": FieldSampleRange(preamble_end, access_address_end),
        "pdu_header": FieldSampleRange(access_address_end, pdu_header_end),
        "adv_address": adv_address,
    }


@dataclass(frozen=True)
class AdvaExcludedArtifact:
    """The real provenance chain point 4 requires: original capture/sample
    range -> derived analytical region -> excluded AdvA sample range ->
    (preprocessing/representation are applied downstream by the caller,
    exactly as for FULL_BURST/PRE_PDU -- this artifact only records what was
    excluded and how the resulting shorter length gets recovered)."""
    window: np.ndarray
    original_sample_range: tuple[int, int]  # absolute (iq_start_sample, iq_end_sample) -- the untouched original
    excluded_adva_sample_range: tuple[int, int]  # absolute -- the real, decoded-PDU-derived AdvA span that was removed
    derived_analytical_region_length: int  # len(window) after exclusion -- never the original length
    length_recovery_rule: str


def derive_packet_content_variants(
    *, iq_window: np.ndarray, iq_start_sample: int, sample_rate_sps: float, pdu_type_name: str | None,
) -> dict[AnalyticalRegion, np.ndarray | AdvaExcludedArtifact | None]:
    """FULL_BURST is always the original window, byte-for-byte, never
    mutated. ADVA_EXCLUDED is None when this PDU type's AdvA offset is not
    known (see PDU_TYPES_WITH_LEADING_ADVA) -- never a guessed exclusion
    range. PRE_PDU truncates to the preamble+access-address samples only,
    clipped to the window's own real length (a very short window may not
    even reach the full 40-bit pre-PDU span) -- unchanged from before."""
    ranges = pdu_field_sample_ranges(packet_start_sample=iq_start_sample, sample_rate_sps=sample_rate_sps, pdu_type_name=pdu_type_name)

    full_burst = iq_window
    iq_end_sample = iq_start_sample + len(iq_window)

    adva_excluded: AdvaExcludedArtifact | None = None
    adv_range = ranges["adv_address"]
    if adv_range is not None:
        local_start = max(0, adv_range.start_sample - iq_start_sample)
        local_end = min(len(iq_window), adv_range.end_sample - iq_start_sample)
        if local_start < local_end:
            spliced = np.concatenate([iq_window[:local_start], iq_window[local_end:]])
            adva_excluded = AdvaExcludedArtifact(
                window=spliced,
                original_sample_range=(iq_start_sample, iq_end_sample),
                excluded_adva_sample_range=(iq_start_sample + local_start, iq_start_sample + local_end),
                derived_analytical_region_length=len(spliced),
                length_recovery_rule=LENGTH_RECOVERY_RULE,
            )

    pre_pdu_local_end = min(len(iq_window), max(0, _bits_to_samples(PRE_PDU_BITS, sample_rate_sps)))
    pre_pdu = iq_window[:pre_pdu_local_end]

    return {"FULL_BURST": full_burst, "ADVA_EXCLUDED": adva_excluded, "PRE_PDU": pre_pdu}
