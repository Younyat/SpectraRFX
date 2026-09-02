"""Representation Adapters (spec sections 6-7) -- pure functions over
already-read numpy I/Q arrays. Never read a file, never call a model,
never mutate the input arrays. Each adapter's job is only "turn real I/Q
samples into the tensor shape a model of that representation family
expects" -- the compatibility checker (compatibility.py) is what actually
decides whether a given model's declared expectation matches.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.signal import stft as scipy_stft
from scipy.signal import welch as scipy_welch

from app.modules.ai_research_plugin.contracts import InputRepresentation


@dataclass(frozen=True)
class AdaptedInput:
    representation: InputRepresentation
    tensor: np.ndarray  # always float32, batch dimension included (leading 1)
    # Real axis values for whichever adapter produced this -- empty where
    # not applicable (e.g. raw IQ has no frequency axis).
    frequency_axis_hz: np.ndarray
    time_axis_s: np.ndarray


def iq_adapter(re: np.ndarray, im: np.ndarray) -> AdaptedInput:
    """[1, 2, N] -- batch, (I, Q), samples. The one representation every
    real capture can always be adapted to without any extra parameters."""
    tensor = np.stack([re, im], axis=0).astype(np.float32)[np.newaxis, ...]
    return AdaptedInput(
        representation=InputRepresentation.IQ_TENSOR,
        tensor=tensor,
        frequency_axis_hz=np.array([]),
        time_axis_s=np.array([]),
    )


def flat_iq_adapter(re: np.ndarray, im: np.ndarray) -> AdaptedInput:
    """[1, 2N] -- N complex I/Q samples flattened into one interleaved
    real/imag vector (I0, Q0, I1, Q1, ...). A real, distinct, deterministic
    shape family from iq_adapter's channel-first [1,2,N] -- some published
    models (e.g. MT-PreamCNN, whose real documented input is exactly
    [None,1600] for 800 complex samples) expect flat-interleaved I/Q, not
    a channel-first tensor. No feature engineering happens here -- a plain
    reshape, never confused with a real FeatureVectorAdapter."""
    interleaved = np.empty(re.size * 2, dtype=np.float32)
    interleaved[0::2] = re.astype(np.float32)
    interleaved[1::2] = im.astype(np.float32)
    tensor = interleaved[np.newaxis, :]
    return AdaptedInput(
        representation=InputRepresentation.FLAT_IQ,
        tensor=tensor,
        frequency_axis_hz=np.array([]),
        time_axis_s=np.array([]),
    )


def spectrogram_adapter(
    re: np.ndarray,
    im: np.ndarray,
    sample_rate_hz: float,
    nperseg: int = 256,
    noverlap: int | None = None,
) -> AdaptedInput:
    """[1, 1, F, T] log-magnitude STFT -- a real `scipy.signal.stft`
    (two-sided, since I/Q is complex) rather than a hand-rolled FFT;
    scipy is already a real dependency of this backend. dB floor at
    -120 keeps log(0) from producing -inf."""
    complex_signal = re.astype(np.float64) + 1j * im.astype(np.float64)
    if noverlap is None:
        noverlap = nperseg // 2
    frequency_axis_hz, time_axis_s, stft_result = scipy_stft(
        complex_signal, fs=sample_rate_hz, nperseg=nperseg, noverlap=noverlap,
        return_onesided=False, boundary=None,
    )
    # scipy's raw bin order is [0, +df, ..., +Nyquist, -Nyquist, ..., -df] --
    # shift BOTH the frequency axis and the data along the same axis so
    # `tensor[..., i, :]` still corresponds to `frequency_axis_hz[i]` after
    # reordering into a monotonic -Nyquist..+Nyquist axis.
    frequency_axis_hz = np.fft.fftshift(frequency_axis_hz)
    stft_result = np.fft.fftshift(stft_result, axes=0)
    magnitude_db = 20 * np.log10(np.maximum(np.abs(stft_result), 1e-6))
    tensor = magnitude_db.astype(np.float32)[np.newaxis, np.newaxis, ...]
    return AdaptedInput(
        representation=InputRepresentation.SPECTROGRAM,
        tensor=tensor,
        frequency_axis_hz=frequency_axis_hz,
        time_axis_s=time_axis_s,
    )


def psd_adapter(re: np.ndarray, im: np.ndarray, sample_rate_hz: float, nperseg: int = 256) -> AdaptedInput:
    """[1, F] log-scaled power spectral density via `scipy.signal.welch`
    (two-sided, complex-valued input)."""
    complex_signal = re.astype(np.float64) + 1j * im.astype(np.float64)
    frequency_axis_hz, power = scipy_welch(complex_signal, fs=sample_rate_hz, nperseg=min(nperseg, len(complex_signal)), return_onesided=False)
    frequency_axis_hz = np.fft.fftshift(frequency_axis_hz)
    power = np.fft.fftshift(power)
    power_db = 10 * np.log10(np.maximum(power, 1e-12))
    tensor = power_db.astype(np.float32)[np.newaxis, ...]
    return AdaptedInput(
        representation=InputRepresentation.PSD,
        tensor=tensor,
        frequency_axis_hz=frequency_axis_hz,
        time_axis_s=np.array([]),
    )


ADAPTERS = {
    InputRepresentation.IQ_TENSOR: lambda re, im, fs: iq_adapter(re, im),
    InputRepresentation.RAW_IQ: lambda re, im, fs: iq_adapter(re, im),
    InputRepresentation.FLAT_IQ: lambda re, im, fs: flat_iq_adapter(re, im),
    InputRepresentation.SPECTROGRAM: lambda re, im, fs: spectrogram_adapter(re, im, fs),
    InputRepresentation.PSD: lambda re, im, fs: psd_adapter(re, im, fs),
}


def adapt(representation: InputRepresentation, re: np.ndarray, im: np.ndarray, sample_rate_hz: float) -> AdaptedInput:
    adapter_fn = ADAPTERS.get(representation)
    if adapter_fn is None:
        raise ValueError(
            f"No adapter implemented for representation={representation.value!r} -- "
            f"FeatureVectorAdapter (cyclostationary/kurtosis/spectral-moment features) "
            f"is a documented Phase-2 gap, not a silent fallback."
        )
    return adapter_fn(re, im, sample_rate_hz)
