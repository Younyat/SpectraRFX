from __future__ import annotations

import numpy as np
import pytest

from app.modules.ble_rffi_studio.preprocessing import (
    BasePreprocessingProfile,
    TrainOnlyScaler,
    apply_base_preprocessing,
    feature_vector_representation,
    load_iq_window,
    raw_iq_representation,
    spectrogram_representation,
)
from app.modules.ble_rffi_studio.preprocessing.representation_profiles import FEATURE_NAMES

SAMPLE_RATE = 4_000_000.0


def _synthetic_window(n=2000, seed=0):
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)


def test_load_iq_window_reads_the_exact_requested_slice(tmp_path):
    samples = _synthetic_window(1000)
    path = tmp_path / "synthetic.cf32"
    samples.tofile(path)
    window = load_iq_window(path, 100, 200)
    assert len(window) == 100
    np.testing.assert_array_equal(window, samples[100:200])


def test_default_profile_applies_no_transformation():
    profile = BasePreprocessingProfile(profile_id="base-v1")
    window = _synthetic_window(500)
    result = apply_base_preprocessing(window, profile, SAMPLE_RATE)
    np.testing.assert_array_equal(result, window)


def test_cfo_correction_reduces_estimated_residual_offset():
    from app.modules.ble_rffi_studio.preprocessing.base_preprocessing import estimate_cfo_hz
    window = _synthetic_window(2000)
    injected_cfo_hz = 50_000.0
    n = np.arange(len(window))
    shifted = window * np.exp(1j * 2 * np.pi * injected_cfo_hz * n / SAMPLE_RATE)

    profile = BasePreprocessingProfile(profile_id="test-cfo", cfo_correction=True, justification_technique_ids={"cfo_correction": "test-technique"})
    corrected = apply_base_preprocessing(shifted, profile, SAMPLE_RATE)

    assert abs(estimate_cfo_hz(corrected, SAMPLE_RATE)) < abs(estimate_cfo_hz(shifted, SAMPLE_RATE))


def test_transient_removal_is_not_implemented():
    window = _synthetic_window(100)
    profile = BasePreprocessingProfile(profile_id="unsupported", transient_removal=True)
    with pytest.raises(NotImplementedError):
        apply_base_preprocessing(window, profile, SAMPLE_RATE)


def test_temporal_alignment_shifts_the_onset_to_the_target_index():
    from app.modules.ble_rffi_studio.preprocessing import leading_edge_alignment

    window = np.zeros(100, dtype=np.complex64)
    window[37:47] = 1.0 + 0j  # a burst starting at sample 37
    aligned = leading_edge_alignment(window, target_index=0)
    onset = int(np.nonzero(np.abs(aligned) >= 0.5)[0][0])
    assert onset == 0


def test_temporal_alignment_is_a_pure_circular_shift_no_samples_invented_or_dropped():
    window = _synthetic_window(200)
    window[50] += 10.0  # an artificial energy peak the threshold will latch onto
    from app.modules.ble_rffi_studio.preprocessing import leading_edge_alignment

    aligned = leading_edge_alignment(window, target_index=0)
    assert len(aligned) == len(window)
    assert sorted(np.abs(aligned)) == pytest.approx(sorted(np.abs(window)))


def test_profile_with_temporal_alignment_enabled_applies_it():
    window = np.zeros(100, dtype=np.complex64)
    window[10:20] = 1.0 + 0j
    profile = BasePreprocessingProfile(profile_id="test-alignment", temporal_alignment=True)
    result = apply_base_preprocessing(window, profile, SAMPLE_RATE)
    onset = int(np.nonzero(np.abs(result) >= 0.5)[0][0])
    assert onset == 0


def test_validate_justifications_rejects_an_enabled_step_without_justification(tmp_path):
    evidence_path = tmp_path / "preprocessing_evidence.json"
    evidence_path.write_text('{"steps":[{"step_id":"cfo_correction","justified_by_technique_id":"real-technique"}]}', encoding="utf-8")
    profile = BasePreprocessingProfile(profile_id="bad", cfo_correction=True)  # no justification supplied
    with pytest.raises(ValueError):
        profile.validate_justifications(evidence_path)


def test_validate_justifications_accepts_a_matching_justification(tmp_path):
    evidence_path = tmp_path / "preprocessing_evidence.json"
    evidence_path.write_text('{"steps":[{"step_id":"cfo_correction","justified_by_technique_id":"real-technique"}]}', encoding="utf-8")
    profile = BasePreprocessingProfile(profile_id="good", cfo_correction=True, justification_technique_ids={"cfo_correction": "real-technique"})
    profile.validate_justifications(evidence_path)  # must not raise


def test_raw_iq_representation_shape_and_padding():
    window = _synthetic_window(50)
    rep = raw_iq_representation(window, target_length=100)
    assert rep.shape == (2, 100)
    np.testing.assert_array_equal(rep[0, 50:], np.zeros(50, dtype=np.float32))


def test_raw_iq_representation_truncates_long_windows():
    window = _synthetic_window(200)
    rep = raw_iq_representation(window, target_length=100)
    assert rep.shape == (2, 100)
    np.testing.assert_allclose(rep[0], window[:100].real.astype(np.float32))


def test_spectrogram_representation_shape():
    window = _synthetic_window(1000)
    rep = spectrogram_representation(window, SAMPLE_RATE, n_fft=64, hop_length=16, target_frames=32)
    assert rep.shape == (1, 64, 32)
    assert np.isfinite(rep).all()


def test_feature_vector_representation_matches_declared_names():
    window = _synthetic_window(500)
    features = feature_vector_representation(window, SAMPLE_RATE)
    assert features.shape == (len(FEATURE_NAMES),)
    assert np.isfinite(features).all()


def test_feature_vector_distinguishes_different_cfo():
    # A steady unit-magnitude carrier (not noise) is what a phase-derivative
    # CFO estimator is actually meant to track -- white noise gives a noisy
    # phase slope regardless of any shift applied to it.
    n = np.arange(2000)
    carrier = np.exp(1j * 2 * np.pi * 1000.0 * n / SAMPLE_RATE).astype(np.complex64)
    shifted = (carrier * np.exp(1j * 2 * np.pi * 80_000.0 * n / SAMPLE_RATE)).astype(np.complex64)
    f1 = feature_vector_representation(carrier, SAMPLE_RATE)
    f2 = feature_vector_representation(shifted, SAMPLE_RATE)
    cfo_index = FEATURE_NAMES.index("cfo_estimate_hz")
    assert abs(f1[cfo_index] - f2[cfo_index]) > 10_000.0


def test_train_only_scaler_rejects_fitting_on_non_train_split():
    scaler = TrainOnlyScaler()
    X = np.random.default_rng(0).standard_normal((10, 3))
    with pytest.raises(ValueError):
        scaler.fit(X, split="VALIDATION")


def test_train_only_scaler_fits_on_train_and_transforms_others():
    rng = np.random.default_rng(0)
    X_train = rng.standard_normal((20, 3)) * 5 + 10
    X_val = rng.standard_normal((5, 3)) * 5 + 10
    scaler = TrainOnlyScaler()
    scaler.fit(X_train, split="TRAIN")
    transformed_train = scaler.transform(X_train)
    transformed_val = scaler.transform(X_val)
    assert abs(transformed_train.mean()) < 1e-6
    assert transformed_val.shape == X_val.shape


def test_scaler_transform_before_fit_raises():
    scaler = TrainOnlyScaler()
    with pytest.raises(ValueError):
        scaler.transform(np.zeros((1, 3)))
