"""Shared (base) preprocessing: the one step every model family agrees on --
loading the exact evidence window an ExampleRecord points to -- plus a set of
OPT-IN, signal-altering steps that are OFF by default (design correction
#11). Enabling any of them requires a technique_id that scientific_basis/
preprocessing_evidence.json actually justifies; this is checked in code, not
just documented.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .paper_compliant_cfo import PaperCompliantCompensation, apply_paper_compliant_compensation

_STEP_NAMES = (
    "cfo_correction", "phase_normalization", "amplitude_normalization", "temporal_alignment", "transient_removal",
    "paper_eq6_7_compensation",
)


def load_iq_window(iq_path: Path, iq_start_sample: int, iq_end_sample: int) -> np.ndarray:
    data = np.memmap(iq_path, dtype=np.complex64, mode="r")
    return np.asarray(data[iq_start_sample:iq_end_sample])


@dataclass(frozen=True)
class BasePreprocessingProfile:
    profile_id: str
    # Heuristic CFO/phase steps (2026-08-08: renamed in spirit, not in field
    # name, to avoid an on-disk contract break -- these are NOT Eq.(6)-(7).
    # mean phase-step CFO + first-sample phase zeroing, over the whole
    # window, no reference waveform, no frozen index set, nothing persisted
    # per burst. Kept for historical/ablation utility; never presented as
    # the paper's primary preprocessing -- see paper_eq6_7_compensation
    # below for the real thing.
    cfo_correction: bool = False
    phase_normalization: bool = False
    amplitude_normalization: bool = False
    temporal_alignment: bool = False
    transient_removal: bool = False
    # Eq.(6)-(7) paper-compliant CFO/phase compensation (2026-08-08, point
    # 3): q[n]/z_b[n]/psi_b[n]/frozen I_b/joint least-squares (phi_b0, f_b)
    # -- see preprocessing/paper_compliant_cfo.py. Mutually meaningful on
    # its own; combining it with cfo_correction/phase_normalization in the
    # same profile would apply two independent, uncoordinated corrections
    # -- no registered profile does that (see base_preprocessing_registry.py).
    paper_eq6_7_compensation: bool = False
    # step_name -> technique_id from scientific_basis/technique_registry.json
    justification_technique_ids: dict[str, str] = field(default_factory=dict)

    def enabled_steps(self) -> list[str]:
        return [name for name in _STEP_NAMES if getattr(self, name)]

    def validate_justifications(self, preprocessing_evidence_path: Path) -> None:
        """Raises if any enabled step lacks a justification that
        preprocessing_evidence.json actually records for it. Never silently
        allows a signal-altering step to run unjustified."""
        evidence = json.loads(preprocessing_evidence_path.read_text(encoding="utf-8"))
        evidence_by_step = {item["step_id"]: item for item in evidence.get("steps", [])}
        for step in self.enabled_steps():
            technique_id = self.justification_technique_ids.get(step)
            if not technique_id:
                raise ValueError(f"PREPROCESSING_STEP_ENABLED_WITHOUT_JUSTIFICATION:{step}")
            record = evidence_by_step.get(step)
            if record is None or record.get("justified_by_technique_id") != technique_id:
                raise ValueError(f"PREPROCESSING_STEP_JUSTIFICATION_MISMATCH:{step}:{technique_id}")


# The only profile shipped so far: everything opt-in stays off. Any profile
# that turns a step on must be a NEW, separately versioned profile_id.
DEFAULT_BASE_PROFILE = BasePreprocessingProfile(profile_id="base-v1")


def estimate_cfo_hz(window: np.ndarray, sample_rate_sps: float) -> float:
    """Methodological-audit finding (2026-08-22, item 1): despite the name,
    this is NOT a validated carrier-frequency-offset (CFO) estimator. It is
    a mean-phase-rate / frequency-offset estimator: the mean of the
    sample-to-sample unwrapped phase increment over the WHOLE window, with
    no known-bit reference waveform, no frozen index set, no least-squares
    fit -- see paper_compliant_cfo.py::estimate_phi0_and_fb for the real,
    reference-correlated Eq.(6)-(7) estimator this is NOT. Two real
    consequences for any caller (including feature_vector_representation's
    cfo_estimate_hz, RQ2's engineered-RF feature #7): (1) it mixes GFSK
    modulation phase trajectory into the estimate, since it never isolates a
    known-content span; (2) whenever it is computed on a window this
    module's compensation steps have NOT already corrected (e.g. profile
    base-v1/offset-retaining-v1, both identity), the output is the
    UNCOMPENSATED, un-decomposed sum of transmitter frequency offset AND
    the B200 receiver's own local-oscillator offset -- the two are not
    separable from a single receiver without an independent reference tone.
    To defensibly call a value here "transmitter CFO," it would need: (a)
    reference correlation over a known-bit span (the preamble+access-address
    region already used by paper_eq6_7_compensation, not the whole burst),
    (b) an independently measured/calibrated B200 LO offset to subtract
    (e.g. a reference tone captured on the same receiver under the same
    session), and (c) validation that the resulting estimate is stable
    across repeated captures of the same transmitter under a fixed receiver
    state. None of that is done here; call this a mean phase-rate /
    frequency-offset estimate, not a CFO measurement, until it is."""
    if len(window) < 2:
        return 0.0
    phase = np.unwrap(np.angle(window))
    mean_phase_step = np.mean(np.diff(phase))
    return float(mean_phase_step * sample_rate_sps / (2 * np.pi))


def apply_base_preprocessing(window: np.ndarray, profile: BasePreprocessingProfile, sample_rate_sps: float) -> np.ndarray:
    """Thin wrapper over apply_base_preprocessing_with_provenance -- exactly
    ONE real implementation of every step; this discards the Eq.(6)-(7)
    provenance for callers that only need the transformed window."""
    result, _ = apply_base_preprocessing_with_provenance(window, profile, sample_rate_sps)
    return result


def apply_base_preprocessing_with_provenance(
    window: np.ndarray, profile: BasePreprocessingProfile, sample_rate_sps: float,
) -> tuple[np.ndarray, PaperCompliantCompensation | None]:
    """Same steps as apply_base_preprocessing, plus real per-burst
    provenance for the Eq.(6)-(7) step when profile.paper_eq6_7_compensation
    is enabled (None otherwise) -- TRAIN and inference both call this SAME
    function (never two separate implementations), so whatever provenance a
    burst was trained under is exactly what inference can reproduce."""
    result = window
    provenance: PaperCompliantCompensation | None = None
    if profile.cfo_correction:
        cfo_hz = estimate_cfo_hz(result, sample_rate_sps)
        n = np.arange(len(result))
        result = result * np.exp(-1j * 2 * np.pi * cfo_hz * n / sample_rate_sps)
    if profile.phase_normalization:
        if len(result) and result[0] != 0:
            result = result * np.exp(-1j * np.angle(result[0]))
    if profile.paper_eq6_7_compensation:
        result, provenance = apply_paper_compliant_compensation(result, sample_rate_sps)
    if profile.amplitude_normalization:
        rms = float(np.sqrt(np.mean(np.abs(result) ** 2))) if len(result) else 0.0
        if rms > 0:
            result = result / rms
    if profile.temporal_alignment:
        result = leading_edge_alignment(result)
    if profile.transient_removal:
        raise NotImplementedError("transient_removal has no validated implementation yet -- do not enable this step in any profile until one exists.")
    return result, provenance


_ALIGNMENT_THRESHOLD_FRACTION = 0.5
_ALIGNMENT_TARGET_INDEX = 0


def leading_edge_alignment(window: np.ndarray, *, threshold_fraction: float = _ALIGNMENT_THRESHOLD_FRACTION, target_index: int = _ALIGNMENT_TARGET_INDEX) -> np.ndarray:
    """Deterministic, parameter-free (no fitting/calibration) onset
    alignment: finds the first sample whose envelope crosses
    threshold_fraction of the window's own peak amplitude, then circularly
    shifts the window so that onset lands at target_index. Standard
    burst-mode RF preprocessing technique (envelope-threshold leading-edge
    detection); corrects residual sample-level jitter left over from the
    decoder's own bit-level sync (whose resolution is one symbol period, not
    one sample). Real implementation exists so this step can be exercised
    and tested -- see base_preprocessing_registry.py for why it is not yet
    enabled in any registered profile (no literature justification on file
    for it specifically, unlike cfo_correction/phase_normalization)."""
    envelope = np.abs(window)
    if len(envelope) == 0:
        return window
    peak = float(envelope.max())
    if peak <= 0:
        return window
    crossings = np.nonzero(envelope >= threshold_fraction * peak)[0]
    if len(crossings) == 0:
        return window
    onset = int(crossings[0])
    shift = target_index - onset
    return np.roll(window, shift)
