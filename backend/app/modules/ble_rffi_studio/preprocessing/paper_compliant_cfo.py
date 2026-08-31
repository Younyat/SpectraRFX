"""Paper-compliant CFO/phase compensation -- Eq. (6)-(7) (2026-08-08,
point 3): the real q[n]/z_b[n]/psi_b[n]/I_b/joint-least-squares-regression
pipeline, distinct from and NOT to be confused with the older, heuristic
cfo_correction/phase_normalization steps in base_preprocessing.py (mean
phase-step CFO + first-sample phase zeroing, computed over the WHOLE window,
with no reference waveform, no frozen index set, and nothing persisted per
burst -- kept under its own name for historical/ablation utility, never
presented as an implementation of this profile).

    q[n]          -- frozen BLE reference: the ideal GFSK-modulated
                     preamble+access-address waveform (LE 1M PHY, BT=0.5,
                     modulation index h=0.5), built once from KNOWN, FIXED
                     bits -- the advertising-channel access address is fixed
                     at 0x8E89BED6 for every real advertising packet
                     (Bluetooth Core Spec Vol 6 Part B 1.4.1); the preamble
                     is the fixed 0xAA/0x55 byte implied by the access
                     address's first-transmitted bit (Vol 6 Part B 2.1.2).
    I_b           -- frozen index set: the burst's own PRE_PDU sample range
                     (packet_content/field_mapping.py's PRE_PDU_BITS=40,
                     preamble+access address) -- the ONLY portion of a real
                     advertising burst whose bit content is known and fixed,
                     so it is the only span a KNOWN reference q[n] can be
                     correlated against.
    z_b[n]        -- x_b[n] * conj(q[n]), evaluated over I_b only.
    psi_b[n]      -- unwrap(angle(z_b[n])).
    (phi_b0, f_b) -- joint least-squares fit of
                     psi_b[n] = phi_b0 + 2*pi*f_b*n/Fs over I_b (numpy
                     lstsq, not a mean-slope/single-sample approximation).
    x_tilde_b[n]  -- x_b[n] * exp(-j*(phi_b0 + 2*pi*f_b*n/Fs)), one
                     combined correction applied to the FULL window (not
                     just I_b).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from ..packet_content.field_mapping import PRE_PDU_BITS

_SYMBOL_RATE_HZ = 1_000_000.0  # BLE LE 1M PHY -- same constant used throughout this module.
_MODULATION_INDEX = 0.5  # BLE LE 1M PHY nominal GFSK modulation index (Bluetooth Core Spec Vol 6 Part A 5.2).
_GAUSSIAN_BT = 0.5  # BLE LE 1M PHY Gaussian pulse-shaping filter's bandwidth-time product.
_ACCESS_ADDRESS_HEX = "8E89BED6"  # fixed advertising-channel access address -- same constant ble_offline_replay.py uses.

REFERENCE_WAVEFORM_VERSION = "ble-le1m-preamble-aa-reference-v1"

APPLIED = "APPLIED"
SKIPPED_WINDOW_SHORTER_THAN_I_B = "SKIPPED_WINDOW_SHORTER_THAN_I_B"


def _access_address_bits() -> list[int]:
    """On-air (LSB-first per octet) bit order of the fixed advertising
    access address -- matches how the real decoder transmits/interprets it."""
    raw = bytes.fromhex(_ACCESS_ADDRESS_HEX)
    bits: list[int] = []
    for byte in raw:
        for i in range(8):
            bits.append((byte >> i) & 1)
    return bits


def _preamble_bits() -> list[int]:
    """0xAA if the access address's first-transmitted bit is 0, else 0x55
    (Bluetooth Core Spec Vol 6 Part B 2.1.2) -- deterministic from the fixed
    access address above, never a free parameter."""
    first_bit = _access_address_bits()[0]
    pattern = 0xAA if first_bit == 0 else 0x55
    return [(pattern >> i) & 1 for i in range(8)]


def _known_bits() -> list[int]:
    return _preamble_bits() + _access_address_bits()


def _gaussian_pulse(samples_per_symbol: int, bt: float, span_symbols: int = 4) -> np.ndarray:
    """Normalized (unit-sum) Gaussian pulse-shaping filter -- the standard
    GFSK pulse shape (Bluetooth Core Spec Vol 6 Part A 5.2)."""
    t = np.arange(-span_symbols * samples_per_symbol / 2.0, span_symbols * samples_per_symbol / 2.0) / samples_per_symbol
    alpha = np.sqrt(np.log(2)) / bt
    pulse = np.exp(-((np.pi * alpha * t) ** 2) / (2 * np.log(2)))
    return pulse / np.sum(pulse)


def build_reference_waveform(sample_rate_sps: float) -> np.ndarray:
    """q[n]: the ideal GFSK-modulated preamble+access-address waveform at
    sample_rate_sps, built ONLY from the fixed, known bit pattern above --
    frozen and deterministic (the same sample_rate_sps always yields the
    same q[n]; never re-derived from any observed burst)."""
    samples_per_symbol = max(1, int(round(sample_rate_sps / _SYMBOL_RATE_HZ)))
    symbols = np.array([1.0 if bit else -1.0 for bit in _known_bits()])
    upsampled = np.repeat(symbols, samples_per_symbol)
    pulse = _gaussian_pulse(samples_per_symbol, _GAUSSIAN_BT)
    shaped = np.convolve(upsampled, pulse, mode="same")
    instantaneous_freq_hz = _MODULATION_INDEX * shaped * (_SYMBOL_RATE_HZ / 2.0)
    phase = 2 * np.pi * np.cumsum(instantaneous_freq_hz) / sample_rate_sps
    return np.exp(1j * phase).astype(np.complex64)


def frozen_index_set(sample_rate_sps: float) -> tuple[int, int]:
    """I_b: the burst's own PRE_PDU sample range, relative to the window's
    own start (0-based) -- reuses packet_content/field_mapping.py's
    PRE_PDU_BITS, the SAME 40-bit preamble+access-address span RQ4's
    PRE_PDU artifact already uses (connecting the two rather than defining
    a second, separate notion of "the known part of a burst")."""
    return (0, round(PRE_PDU_BITS * sample_rate_sps / _SYMBOL_RATE_HZ))


def estimate_phi0_and_fb(window: np.ndarray, reference: np.ndarray, index_set: tuple[int, int], sample_rate_sps: float) -> tuple[float, float]:
    """Joint least-squares fit of psi_b[n] = phi_b0 + 2*pi*f_b*n/Fs over
    I_b -- np.linalg.lstsq, never a mean-slope or single-sample shortcut.
    Returns (phi_b0, f_b_hz)."""
    start, end = index_set
    z_b = window[start:end] * np.conj(reference[start:end])
    psi_b = np.unwrap(np.angle(z_b))
    n = np.arange(start, end, dtype=np.float64)
    design = np.stack([np.ones_like(n), n], axis=1)
    coefficients, *_ = np.linalg.lstsq(design, psi_b, rcond=None)
    phi_b0, slope_rad_per_sample = coefficients
    f_b_hz = slope_rad_per_sample * sample_rate_sps / (2 * np.pi)
    return float(phi_b0), float(f_b_hz)


@dataclass(frozen=True)
class PaperCompliantCompensation:
    phi_b0: float
    f_b_hz: float
    index_set: tuple[int, int]
    sample_rate_sps: float
    reference_waveform_version: str
    reference_waveform_hash: str
    compensation_status: str  # APPLIED | SKIPPED_WINDOW_SHORTER_THAN_I_B


def apply_paper_compliant_compensation(window: np.ndarray, sample_rate_sps: float) -> tuple[np.ndarray, PaperCompliantCompensation]:
    """The full Eq.(6)-(7) pipeline: builds q[n], estimates (phi_b0, f_b)
    over the frozen I_b via joint least squares, applies ONE combined
    correction to the whole window, and returns complete, real per-burst
    provenance. A window shorter than I_b cannot be corrected (there is no
    known-content span to correlate against) -- returns the window
    UNCHANGED with compensation_status=SKIPPED_WINDOW_SHORTER_THAN_I_B,
    never a fabricated (phi_b0, f_b)."""
    index_set = frozen_index_set(sample_rate_sps)
    reference = build_reference_waveform(sample_rate_sps)
    reference_hash = hashlib.sha256(reference.tobytes()).hexdigest()

    if len(window) < index_set[1] or len(reference) < index_set[1]:
        provenance = PaperCompliantCompensation(
            phi_b0=0.0, f_b_hz=0.0, index_set=index_set, sample_rate_sps=sample_rate_sps,
            reference_waveform_version=REFERENCE_WAVEFORM_VERSION, reference_waveform_hash=reference_hash,
            compensation_status=SKIPPED_WINDOW_SHORTER_THAN_I_B,
        )
        return window, provenance

    phi_b0, f_b_hz = estimate_phi0_and_fb(window, reference, index_set, sample_rate_sps)
    n = np.arange(len(window), dtype=np.float64)
    x_tilde_b = window * np.exp(-1j * (phi_b0 + 2 * np.pi * f_b_hz * n / sample_rate_sps))
    provenance = PaperCompliantCompensation(
        phi_b0=phi_b0, f_b_hz=f_b_hz, index_set=index_set, sample_rate_sps=sample_rate_sps,
        reference_waveform_version=REFERENCE_WAVEFORM_VERSION, reference_waveform_hash=reference_hash,
        compensation_status=APPLIED,
    )
    return x_tilde_b.astype(window.dtype), provenance
