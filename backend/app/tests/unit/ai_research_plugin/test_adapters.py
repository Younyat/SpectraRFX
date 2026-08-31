from __future__ import annotations

import numpy as np
import pytest

from app.modules.ai_research_plugin.adapters import adapt, iq_adapter, psd_adapter, spectrogram_adapter
from app.modules.ai_research_plugin.contracts import InputRepresentation

SAMPLE_RATE_HZ = 2_000_000.0
N = 4096


def _tone(freq_hz: float) -> tuple[np.ndarray, np.ndarray]:
    n = np.arange(N)
    phase = 2 * np.pi * freq_hz * n / SAMPLE_RATE_HZ
    return np.cos(phase).astype(np.float32), np.sin(phase).astype(np.float32)


def test_iq_adapter_shape_is_batch_iq_samples():
    re, im = _tone(50_000)
    result = iq_adapter(re, im)
    assert result.tensor.shape == (1, 2, N)
    assert result.tensor.dtype == np.float32
    assert result.representation == InputRepresentation.IQ_TENSOR


def test_iq_adapter_preserves_the_real_i_and_q_values():
    re, im = _tone(50_000)
    result = iq_adapter(re, im)
    np.testing.assert_allclose(result.tensor[0, 0], re, atol=1e-6)
    np.testing.assert_allclose(result.tensor[0, 1], im, atol=1e-6)


def test_spectrogram_adapter_shape_and_axes_are_real_not_placeholders():
    re, im = _tone(50_000)
    result = spectrogram_adapter(re, im, SAMPLE_RATE_HZ, nperseg=256)
    assert result.tensor.ndim == 4  # [1, 1, F, T]
    assert result.tensor.shape[2] == len(result.frequency_axis_hz)
    assert result.tensor.shape[3] == len(result.time_axis_s)
    assert np.all(np.isfinite(result.tensor))  # no -inf from log(0)


def test_spectrogram_adapter_concentrates_energy_near_the_real_tone_frequency():
    tone_freq = 200_000.0
    re, im = _tone(tone_freq)
    result = spectrogram_adapter(re, im, SAMPLE_RATE_HZ, nperseg=512)
    mean_db_per_bin = result.tensor[0, 0].mean(axis=1)
    peak_freq = result.frequency_axis_hz[int(np.argmax(mean_db_per_bin))]
    assert abs(peak_freq - tone_freq) < (SAMPLE_RATE_HZ / 512) * 2


def test_psd_adapter_shape_matches_frequency_axis():
    re, im = _tone(50_000)
    result = psd_adapter(re, im, SAMPLE_RATE_HZ, nperseg=256)
    assert result.tensor.shape == (1, len(result.frequency_axis_hz))
    assert np.all(np.isfinite(result.tensor))


def test_psd_adapter_peak_lines_up_with_the_real_tone_frequency():
    tone_freq = 200_000.0
    re, im = _tone(tone_freq)
    result = psd_adapter(re, im, SAMPLE_RATE_HZ, nperseg=512)
    peak_freq = result.frequency_axis_hz[int(np.argmax(result.tensor[0]))]
    assert abs(peak_freq - tone_freq) < (SAMPLE_RATE_HZ / 512) * 2


def test_adapt_dispatches_to_the_matching_adapter():
    re, im = _tone(50_000)
    result = adapt(InputRepresentation.SPECTROGRAM, re, im, SAMPLE_RATE_HZ)
    assert result.representation == InputRepresentation.SPECTROGRAM


def test_adapt_fails_closed_for_a_representation_with_no_implemented_adapter():
    re, im = _tone(50_000)
    with pytest.raises(ValueError, match="FeatureVectorAdapter"):
        adapt(InputRepresentation.FEATURES, re, im, SAMPLE_RATE_HZ)
