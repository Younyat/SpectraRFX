from __future__ import annotations

from app.modules.ai_research_plugin.compatibility import check_compatibility
from app.modules.ai_research_plugin.contracts import (
    CompatibilityVerdict,
    InputRepresentation,
    ModelFramework,
    RFModelInputFields,
    RFModelManifest,
)


def _manifest(**input_overrides) -> RFModelManifest:
    return RFModelManifest(
        model_id="AI-MODEL-test",
        model_name="test",
        framework=ModelFramework.ONNX,
        model_file="test.onnx",
        model_sha256="a" * 64,
        imported_at_utc="2026-01-01T00:00:00Z",
        input_discovered=RFModelInputFields(**input_overrides),
    )


def test_fully_compatible_when_every_declared_field_matches():
    manifest = _manifest(
        representation=InputRepresentation.IQ_TENSOR,
        tensor_shape=[1, 2, 4096],
        sample_rate_hz=2_000_000.0,
    )
    result = check_compatibility(
        capture_metadata={"sample_rate_sps": 2_000_000.0},
        manifest=manifest,
        chosen_representation=InputRepresentation.IQ_TENSOR,
        adapted_tensor_shape=[1, 2, 4096],
    )
    assert result.verdict == CompatibilityVerdict.COMPATIBLE


def test_unknown_when_the_manifest_declares_nothing_at_all():
    manifest = _manifest()
    result = check_compatibility(
        capture_metadata={},
        manifest=manifest,
        chosen_representation=InputRepresentation.IQ_TENSOR,
        adapted_tensor_shape=[1, 2, 4096],
    )
    assert result.verdict == CompatibilityVerdict.UNKNOWN
    assert all(check.matched is None for check in result.checks)


def test_incompatible_when_the_declared_representation_and_shape_both_mismatch():
    manifest = _manifest(representation=InputRepresentation.SPECTROGRAM, tensor_shape=[1, 1, 256, 32])
    result = check_compatibility(
        capture_metadata={},
        manifest=manifest,
        chosen_representation=InputRepresentation.IQ_TENSOR,
        adapted_tensor_shape=[1, 2, 4096],
    )
    assert result.verdict == CompatibilityVerdict.INCOMPATIBLE


def test_partially_compatible_when_only_some_declared_fields_match():
    manifest = _manifest(
        representation=InputRepresentation.IQ_TENSOR,  # matches
        sample_rate_hz=8_000_000.0,  # will NOT match the capture's real rate
    )
    result = check_compatibility(
        capture_metadata={"sample_rate_sps": 2_000_000.0},
        manifest=manifest,
        chosen_representation=InputRepresentation.IQ_TENSOR,
        adapted_tensor_shape=[1, 2, 4096],
    )
    assert result.verdict == CompatibilityVerdict.PARTIALLY_COMPATIBLE
    sample_rate_check = next(c for c in result.checks if c.field == "sample_rate_hz")
    assert sample_rate_check.matched is False


def test_dynamic_batch_dimension_is_treated_as_a_wildcard_not_a_mismatch():
    manifest = _manifest(tensor_shape=[None, 2, 4096])  # None = dynamic dim, a real ONNX concept
    result = check_compatibility(
        capture_metadata={},
        manifest=manifest,
        chosen_representation=InputRepresentation.UNKNOWN,
        adapted_tensor_shape=[1, 2, 4096],
    )
    shape_check = next(c for c in result.checks if c.field == "tensor_shape")
    assert shape_check.matched is True


def test_sample_rate_within_tolerance_counts_as_a_match():
    manifest = _manifest(sample_rate_hz=2_000_000.0)
    result = check_compatibility(
        capture_metadata={"sample_rate_sps": 2_000_100.0},  # 0.005% off
        manifest=manifest,
        chosen_representation=InputRepresentation.UNKNOWN,
        adapted_tensor_shape=[1, 2, 4096],
    )
    sample_rate_check = next(c for c in result.checks if c.field == "sample_rate_hz")
    assert sample_rate_check.matched is True


def test_every_check_carries_the_real_capture_and_model_values_for_display():
    manifest = _manifest(representation=InputRepresentation.SPECTROGRAM)
    result = check_compatibility(
        capture_metadata={"sample_rate_sps": 2_000_000.0},
        manifest=manifest,
        chosen_representation=InputRepresentation.IQ_TENSOR,
        adapted_tensor_shape=[1, 2, 4096],
    )
    representation_check = next(c for c in result.checks if c.field == "representation")
    assert representation_check.capture_value == "iq_tensor"
    assert representation_check.model_value == "spectrogram"
