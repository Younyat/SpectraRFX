from __future__ import annotations

from pathlib import Path

from app.modules.ai_research_plugin.onnx_inspection import (
    infer_output_type_from_shape,
    infer_representation_from_shape,
    inspect_onnx_model,
)
from app.modules.ai_research_plugin.contracts import InputRepresentation, OutputType
from app.tests.unit.ai_research_plugin.onnx_fixtures import (
    N_CLASSES,
    N_SAMPLES,
    build_invalid_onnx_bytes,
    build_toy_amc_onnx_bytes,
)


def test_inspects_real_input_and_output_tensor_shapes_from_the_graph(tmp_path: Path):
    model_path = tmp_path / "toy.onnx"
    model_path.write_bytes(build_toy_amc_onnx_bytes())

    result = inspect_onnx_model(model_path)

    assert result.valid is True
    assert result.error is None
    assert len(result.inputs) == 1
    assert result.inputs[0].name == "iq_input"
    assert result.inputs[0].shape == [1, 2, N_SAMPLES]
    assert result.inputs[0].dtype == "float32"
    assert len(result.outputs) == 1
    assert result.outputs[0].shape == [1, N_CLASSES]


def test_excludes_initializers_weights_from_the_reported_inputs(tmp_path: Path):
    model_path = tmp_path / "toy.onnx"
    model_path.write_bytes(build_toy_amc_onnx_bytes())
    result = inspect_onnx_model(model_path)
    input_names = {tensor.name for tensor in result.inputs}
    assert "W" not in input_names
    assert "b" not in input_names


def test_fails_closed_on_a_malformed_file_instead_of_fabricating_a_result(tmp_path: Path):
    model_path = tmp_path / "bad.onnx"
    model_path.write_bytes(build_invalid_onnx_bytes())

    result = inspect_onnx_model(model_path)

    assert result.valid is False
    assert result.error is not None
    assert result.inputs == []
    assert result.outputs == []


def test_representation_heuristic_flags_a_2_channel_axis_as_iq_tensor():
    assert infer_representation_from_shape([1, 2, 128]) == InputRepresentation.IQ_TENSOR


def test_representation_heuristic_is_honestly_unknown_for_an_ambiguous_shape():
    assert infer_representation_from_shape([1, 64, 64, 3]) == InputRepresentation.UNKNOWN


def test_output_heuristic_flags_a_flat_vector_as_class_logits():
    assert infer_output_type_from_shape([1, 5]) == OutputType.CLASS_LOGITS


def test_output_heuristic_is_honestly_unknown_for_a_multi_dim_output():
    assert infer_output_type_from_shape([1, 8, 8, 3]) == OutputType.UNKNOWN
