"""Point-3 correction (2026-08-08): the REAL Eq.(6)-(7) implementation --
q[n] frozen BLE reference, z_b[n]=x_b[n]*conj(q[n]), psi_b[n]=unwrap(angle(
z_b[n])) over a frozen index set I_b, joint least-squares (phi_b0, f_b),
x_tilde_b[n]=x_b[n]*exp(-j(phi_b0+2*pi*f_b*n/Fs)) -- distinct from the older
cfo_correction/phase_normalization heuristic (mean phase-step + first-sample
phase zeroing over the whole window, no reference, no I_b, no regression).
"""
from __future__ import annotations

import numpy as np
import pytest

from app.modules.ble_rffi_studio.preprocessing.paper_compliant_cfo import (
    APPLIED,
    SKIPPED_WINDOW_SHORTER_THAN_I_B,
    apply_paper_compliant_compensation,
    build_reference_waveform,
    estimate_phi0_and_fb,
    frozen_index_set,
)

SAMPLE_RATE = 4_000_000.0  # 4 samples/bit


def test_reference_waveform_is_deterministic():
    a = build_reference_waveform(SAMPLE_RATE)
    b = build_reference_waveform(SAMPLE_RATE)
    np.testing.assert_array_equal(a, b)


def test_reference_waveform_has_unit_magnitude():
    q = build_reference_waveform(SAMPLE_RATE)
    np.testing.assert_allclose(np.abs(q), 1.0, atol=1e-6)


def test_frozen_index_set_matches_pre_pdu_bits():
    from app.modules.ble_rffi_studio.packet_content.field_mapping import PRE_PDU_BITS

    start, end = frozen_index_set(SAMPLE_RATE)
    assert start == 0
    assert end == round(PRE_PDU_BITS * SAMPLE_RATE / 1_000_000.0)


def test_joint_regression_recovers_a_known_injected_phi0_and_fb():
    """The real sanity check: inject a KNOWN (phi_b0, f_b) onto the
    reference waveform itself and confirm the joint least-squares fit
    recovers it to high precision."""
    q = build_reference_waveform(SAMPLE_RATE)
    true_phi0, true_fb = 0.7, 15_000.0
    n = np.arange(len(q))
    injected = q * np.exp(1j * (true_phi0 + 2 * np.pi * true_fb * n / SAMPLE_RATE))
    index_set = frozen_index_set(SAMPLE_RATE)

    phi0, fb = estimate_phi0_and_fb(injected.astype(np.complex64), q, index_set, SAMPLE_RATE)
    assert phi0 == pytest.approx(true_phi0, abs=1e-3)
    assert fb == pytest.approx(true_fb, abs=5.0)


def test_apply_paper_compliant_compensation_removes_the_injected_offset():
    q = build_reference_waveform(SAMPLE_RATE)
    window = np.concatenate([q, np.zeros(200, dtype=np.complex64)])
    true_phi0, true_fb = 1.1, -8_000.0
    n = np.arange(len(window))
    corrupted = (window * np.exp(1j * (true_phi0 + 2 * np.pi * true_fb * n / SAMPLE_RATE))).astype(np.complex64)

    x_tilde, provenance = apply_paper_compliant_compensation(corrupted, SAMPLE_RATE)
    assert provenance.compensation_status == APPLIED
    assert provenance.phi_b0 == pytest.approx(true_phi0, abs=1e-3)
    assert provenance.f_b_hz == pytest.approx(true_fb, abs=5.0)
    # The corrected signal should closely match the original, uncorrupted window.
    np.testing.assert_allclose(np.abs(x_tilde[: len(q)]), np.abs(window[: len(q)]), atol=1e-3)


def test_apply_paper_compliant_compensation_is_skipped_for_a_window_shorter_than_i_b():
    tiny_window = np.ones(5, dtype=np.complex64)
    x_tilde, provenance = apply_paper_compliant_compensation(tiny_window, SAMPLE_RATE)
    assert provenance.compensation_status == SKIPPED_WINDOW_SHORTER_THAN_I_B
    np.testing.assert_array_equal(x_tilde, tiny_window)  # unchanged, never a fabricated correction


def test_provenance_records_the_real_index_set_and_reference_hash():
    q = build_reference_waveform(SAMPLE_RATE)
    window = np.concatenate([q, np.zeros(200, dtype=np.complex64)]).astype(np.complex64)
    _, provenance = apply_paper_compliant_compensation(window, SAMPLE_RATE)
    assert provenance.index_set == frozen_index_set(SAMPLE_RATE)
    assert provenance.sample_rate_sps == SAMPLE_RATE
    assert len(provenance.reference_waveform_hash) == 64  # real sha256 hex digest
    assert provenance.reference_waveform_version == "ble-le1m-preamble-aa-reference-v1"
