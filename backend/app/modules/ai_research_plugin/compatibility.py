"""Compatibility check (spec section 11) -- compares REAL capture
metadata and a REAL adapted-tensor shape against what the model manifest
actually declares (discovered from real inspection, or asserted by the
operator via an override -- `effective_input()` already picked the right
one). Every individual check is either a real True/False comparison or an
honest `None` ("could not be checked" -- the model manifest never
declared this field), never silently skipped.
"""

from __future__ import annotations

from app.modules.ai_research_plugin.contracts import (
    CompatibilityCheck,
    CompatibilityResult,
    CompatibilityVerdict,
    InputRepresentation,
    RFModelManifest,
)

_RELATIVE_TOLERANCE = 0.01


def _shape_matches(expected: list[int | None] | None, actual: list[int]) -> bool | None:
    if expected is None:
        return None
    if len(expected) != len(actual):
        return False
    return all(exp is None or exp == act for exp, act in zip(expected, actual))


def _relative_match(expected: float | None, actual: float) -> bool | None:
    if expected is None:
        return None
    if expected == 0:
        return actual == 0
    return abs(actual - expected) / abs(expected) <= _RELATIVE_TOLERANCE


def check_compatibility(
    capture_metadata: dict,
    manifest: RFModelManifest,
    chosen_representation: InputRepresentation,
    adapted_tensor_shape: list[int],
) -> CompatibilityResult:
    model_input = manifest.effective_input()
    checks: list[CompatibilityCheck] = []

    representation_matched = (
        None if model_input.representation is None
        else model_input.representation == chosen_representation
    )
    checks.append(CompatibilityCheck(
        field="representation",
        capture_value=chosen_representation.value,
        model_value=model_input.representation.value if model_input.representation else None,
        matched=representation_matched,
        note="" if model_input.representation else "Model manifest does not declare an expected representation",
    ))

    capture_sample_rate = capture_metadata.get("sample_rate_sps")
    sample_rate_matched = _relative_match(model_input.sample_rate_hz, capture_sample_rate) if capture_sample_rate else None
    checks.append(CompatibilityCheck(
        field="sample_rate_hz",
        capture_value=capture_sample_rate,
        model_value=model_input.sample_rate_hz,
        matched=sample_rate_matched,
        note="" if model_input.sample_rate_hz else "Model manifest does not declare an expected sample rate",
    ))

    capture_bandwidth = capture_metadata.get("bandwidth_hz")
    bandwidth_matched = _relative_match(model_input.bandwidth_hz, capture_bandwidth) if capture_bandwidth else None
    checks.append(CompatibilityCheck(
        field="bandwidth_hz",
        capture_value=capture_bandwidth,
        model_value=model_input.bandwidth_hz,
        matched=bandwidth_matched,
        note="" if model_input.bandwidth_hz else "Model manifest does not declare an expected bandwidth",
    ))

    shape_matched = _shape_matches(model_input.tensor_shape, adapted_tensor_shape)
    checks.append(CompatibilityCheck(
        field="tensor_shape",
        capture_value=adapted_tensor_shape,
        model_value=model_input.tensor_shape,
        matched=shape_matched,
        note="" if model_input.tensor_shape else "Model manifest does not declare an expected tensor shape",
    ))

    dtype_matched = None if model_input.dtype is None else model_input.dtype == "float32"
    checks.append(CompatibilityCheck(
        field="dtype",
        capture_value="float32",
        model_value=model_input.dtype,
        matched=dtype_matched,
        note="" if model_input.dtype else "Model manifest does not declare an expected dtype",
    ))

    evaluated = [c.matched for c in checks if c.matched is not None]
    if not evaluated:
        verdict = CompatibilityVerdict.UNKNOWN
    elif all(evaluated):
        verdict = CompatibilityVerdict.COMPATIBLE
    elif any(evaluated):
        verdict = CompatibilityVerdict.PARTIALLY_COMPATIBLE
    else:
        verdict = CompatibilityVerdict.INCOMPATIBLE

    return CompatibilityResult(verdict=verdict, checks=checks)
