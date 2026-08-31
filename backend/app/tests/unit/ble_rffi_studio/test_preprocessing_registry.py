"""Preprocessing-registry correction (2026-08-08): base_preprocessing_profile_id
used to be a bare label everywhere it was actually applied (training AND
inference always silently constructed BasePreprocessingProfile(profile_id=X)
with every flag False, regardless of X). These tests exercise the real fix:
resolve_preprocessing_profile() is the one place a profile_id becomes real
flags, and the two new profiles (cfo-compensated-v1, offset-retaining-v1) are
real, distinct, and either genuinely justified or genuinely not.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.ble_rffi_studio.preprocessing import PREPROCESSING_PROFILE_REGISTRY, resolve_preprocessing_profile

_SCIENTIFIC_BASIS_DIR = Path(__file__).resolve().parents[3] / "modules" / "ble_rffi_studio" / "scientific_basis"


def test_base_v1_resolves_to_identity_unchanged():
    profile = resolve_preprocessing_profile("base-v1")
    assert profile.cfo_correction is False
    assert profile.phase_normalization is False
    assert profile.temporal_alignment is False


def test_cfo_compensated_v1_resolves_to_the_papers_affine_phase_frequency_compensation():
    profile = resolve_preprocessing_profile("cfo-compensated-v1")
    assert profile.cfo_correction is True
    assert profile.phase_normalization is True
    # Never silently enabled without literature justification on file.
    assert profile.temporal_alignment is False
    assert profile.amplitude_normalization is False
    assert profile.justification_technique_ids["cfo_correction"] == "ble-rffi-industry5-2026"
    assert profile.justification_technique_ids["phase_normalization"] == "ble-rffi-industry5-2026"


def test_offset_retaining_v1_is_a_distinct_id_from_base_v1_despite_identical_flags():
    base = resolve_preprocessing_profile("base-v1")
    offset_retaining = resolve_preprocessing_profile("offset-retaining-v1")
    assert offset_retaining.profile_id != base.profile_id
    assert offset_retaining.cfo_correction == base.cfo_correction == False
    assert offset_retaining.phase_normalization == base.phase_normalization == False


def test_unknown_profile_id_raises_instead_of_silently_defaulting_to_identity():
    with pytest.raises(ValueError, match="UNKNOWN_PREPROCESSING_PROFILE_ID"):
        resolve_preprocessing_profile("not-a-real-profile")


def test_cfo_compensated_v1_passes_real_justification_validation_against_the_real_evidence_file():
    profile = resolve_preprocessing_profile("cfo-compensated-v1")
    profile.validate_justifications(_SCIENTIFIC_BASIS_DIR / "preprocessing_evidence.json")  # must not raise


def test_every_registered_profile_passes_real_justification_validation():
    for profile in PREPROCESSING_PROFILE_REGISTRY.values():
        profile.validate_justifications(_SCIENTIFIC_BASIS_DIR / "preprocessing_evidence.json")  # must not raise for any registered profile
