"""Preprocessing-profile correction (2026-08-08): base_preprocessing_profile_id
used to be a bare label -- TrainingService/OfflineInferenceService always
constructed BasePreprocessingProfile(profile_id=<that string>) with every
flag defaulting to False, so no matter what a caller declared, training AND
inference silently ran identity preprocessing. This registry is the single
place a profile_id resolves to the actual, real flags that will run; every
frozen artifact that persists a profile_id (TrainingRun, bundle
preprocessing_config.json) must resolve through here, never construct a bare
BasePreprocessingProfile directly from a stored string again.

A profile_id in this registry is immutable once anything has trained against
it -- changing what "cfo-compensated-v1" means later would silently change
the meaning of every already-frozen artifact that cites it. A config change
always means a new profile_id, never editing an existing entry's flags.
"""
from __future__ import annotations

from .base_preprocessing import BasePreprocessingProfile

# base-v1: identity preprocessing. Predates this registry -- kept exactly as
# it always was (every flag False) so every already-frozen TrainingRun/bundle
# that cites it keeps meaning exactly what it always meant.
BASE_PROFILE = BasePreprocessingProfile(profile_id="base-v1")

# cfo-compensated-v1: a HEURISTIC CFO/phase correction (mean phase-step over
# the whole window + first-sample phase zeroing) -- 2026-08-08 correction
# (point 3): this profile is EXPLICITLY NOT the paper's Eq.(6)-(7)
# preprocessing and must never be presented as such (an earlier version of
# this comment claimed it was; that was wrong -- there is no q[n] reference,
# no frozen index set I_b, no joint least-squares fit, and (phi_b0, f_b) are
# never persisted per burst). Kept for historical/ablation utility only --
# see paper-eq6-7-v1 below for the real implementation. Still justified
# under "ble-rffi-industry5-2026" in preprocessing_evidence.json as a
# reasonable heuristic reading of "CFO-compensated", just not the paper's
# actual defined procedure.
CFO_COMPENSATED_PROFILE = BasePreprocessingProfile(
    profile_id="cfo-compensated-v1",
    cfo_correction=True,
    phase_normalization=True,
    justification_technique_ids={"cfo_correction": "ble-rffi-industry5-2026", "phase_normalization": "ble-rffi-industry5-2026"},
)

# paper-eq6-7-v1 (2026-08-08, point 3): the REAL Eq.(6)-(7) implementation --
# q[n] frozen BLE reference, z_b[n]=x_b[n]*conj(q[n]), psi_b[n]=unwrap(angle(
# z_b[n])) over the frozen index set I_b, joint least-squares (phi_b0, f_b),
# x_tilde_b[n]=x_b[n]*exp(-j(phi_b0+2*pi*f_b*n/Fs)) -- see
# preprocessing/paper_compliant_cfo.py for the full math and per-burst
# provenance (persisted by TrainingService/OfflineInferenceService, see
# preprocessing_provenance.jsonl). THIS is the paper's primary preprocessing
# profile, not cfo-compensated-v1.
PAPER_EQ6_7_PROFILE = BasePreprocessingProfile(
    profile_id="paper-eq6-7-v1",
    paper_eq6_7_compensation=True,
    justification_technique_ids={"paper_eq6_7_compensation": "ble-rffi-industry5-2026"},
)

# offset-retaining-v1: the deliberate sensitivity-analysis counterpart to
# paper-eq6-7-v1 -- same (identity) flags as base-v1, but a distinct,
# intentionally-declared profile_id, run through the exact same pipeline
# except the Eq.(6)-(7) compensation step. base-v1 predates any
# CFO-compensation profile and was never meant to represent "the sensitivity
# condition that deliberately retains raw offsets"; offset-retaining-v1
# exists so that choice is explicit and auditable in any artifact that cites
# it, never silently inferred from "well, it's the same flags as the old
# default".
OFFSET_RETAINING_PROFILE = BasePreprocessingProfile(profile_id="offset-retaining-v1")

# temporal_alignment has a real, tested implementation (leading_edge_alignment
# in base_preprocessing.py) but is NOT enabled in any profile below: no entry
# in scientific_basis/technique_registry.json justifies it specifically, and
# fabricating a citation is explicitly forbidden by that registry's own
# pending_research note. This is a genuine, deliberate limitation, not an
# oversight -- enabling it requires real literature research first.

PREPROCESSING_PROFILE_REGISTRY: dict[str, BasePreprocessingProfile] = {
    profile.profile_id: profile for profile in (BASE_PROFILE, CFO_COMPENSATED_PROFILE, PAPER_EQ6_7_PROFILE, OFFSET_RETAINING_PROFILE)
}


def resolve_preprocessing_profile(profile_id: str) -> BasePreprocessingProfile:
    """The one place a stored profile_id string becomes the real, actually-
    applied BasePreprocessingProfile. Raises on an unrecognized id instead of
    silently falling back to identity -- an unresolvable profile_id on a
    frozen artifact is a real integrity problem, never something to paper
    over with a default."""
    profile = PREPROCESSING_PROFILE_REGISTRY.get(profile_id)
    if profile is None:
        raise ValueError(f"UNKNOWN_PREPROCESSING_PROFILE_ID:{profile_id}. Known profiles: {sorted(PREPROCESSING_PROFILE_REGISTRY)}")
    return profile
