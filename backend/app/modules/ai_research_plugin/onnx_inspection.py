"""Real ONNX Model Inspection (spec section 4) -- extracts exactly what
the ONNX graph itself declares (input/output tensor names, shapes,
element types). Never guesses a sample rate, task, or class list -- those
are not part of the ONNX graph format and stay unset (None) unless the
operator supplies them via a manifest override.

ONNX is the one framework in this plugin's Phase 1 scope where automatic
shape/dtype discovery is genuinely reliable: the graph format stores
`ValueInfoProto` for every input/output with a real `TensorShapeProto`,
so this is real inspection, not a heuristic guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import onnx

from app.modules.ai_research_plugin.contracts import InputRepresentation, OutputType


_ONNX_ELEM_TYPE_TO_NUMPY = {
    1: "float32", 2: "uint8", 3: "int8", 4: "uint16", 5: "int16",
    6: "int32", 7: "int64", 9: "bool", 10: "float16", 11: "float64",
    12: "uint32", 13: "uint64",
}


@dataclass(frozen=True)
class OnnxTensorInfo:
    name: str
    shape: list[int | None]  # None = a symbolic/dynamic dimension (e.g. batch size)
    dtype: str


@dataclass(frozen=True)
class OnnxInspectionResult:
    valid: bool
    error: str | None
    ir_version: int | None
    opset_version: int | None
    producer_name: str | None
    inputs: list[OnnxTensorInfo]
    outputs: list[OnnxTensorInfo]


def _tensor_info_from_value_info(value_info) -> OnnxTensorInfo:
    tensor_type = value_info.type.tensor_type
    shape: list[int | None] = []
    for dim in tensor_type.shape.dim:
        if dim.HasField("dim_value"):
            shape.append(dim.dim_value)
        else:
            shape.append(None)
    dtype = _ONNX_ELEM_TYPE_TO_NUMPY.get(tensor_type.elem_type, f"onnx_elem_type_{tensor_type.elem_type}")
    return OnnxTensorInfo(name=value_info.name, shape=shape, dtype=dtype)


def inspect_onnx_model(model_path: Path) -> OnnxInspectionResult:
    """Loads and statically inspects an ONNX file. Never runs the model.
    Fails closed (valid=False, real error message) on anything malformed
    rather than returning a partially-fabricated result."""
    try:
        model = onnx.load(str(model_path))
        onnx.checker.check_model(model)
    except Exception as error:  # real, varied onnx/protobuf exception types
        return OnnxInspectionResult(
            valid=False, error=str(error), ir_version=None, opset_version=None,
            producer_name=None, inputs=[], outputs=[],
        )

    graph = model.graph
    initializer_names = {init.name for init in graph.initializer}
    # Real graph inputs exclude weights/initializers that ONNX also lists
    # under graph.input in some exporters -- only the tensors an actual
    # caller must supply.
    inputs = [
        _tensor_info_from_value_info(value_info)
        for value_info in graph.input
        if value_info.name not in initializer_names
    ]
    outputs = [_tensor_info_from_value_info(value_info) for value_info in graph.output]
    opset_version = model.opset_import[0].version if model.opset_import else None

    return OnnxInspectionResult(
        valid=True, error=None, ir_version=model.ir_version, opset_version=opset_version,
        producer_name=model.producer_name or None, inputs=inputs, outputs=outputs,
    )


def infer_representation_from_shape(shape: list[int | None]) -> InputRepresentation:
    """A best-effort, clearly-labeled HEURISTIC (never presented as a
    measured fact) -- a rank-3 tensor with a leading/second dim of 2 is
    very likely an [I,Q] pair; anything else is left UNKNOWN rather than
    guessed further. The manifest always keeps this separate from any
    operator override."""
    real_dims = [d for d in shape if d is not None]
    if len([d for d in shape if d is None]) <= 1 and 2 in shape:
        return InputRepresentation.IQ_TENSOR
    if len(real_dims) >= 2:
        return InputRepresentation.UNKNOWN
    return InputRepresentation.UNKNOWN


def infer_output_type_from_shape(shape: list[int | None]) -> OutputType:
    """Same heuristic-labeling discipline as above -- a rank-2
    [batch, N] float output is plausibly class logits/probabilities, but
    this is a shape-based guess, not a determination of what the model
    actually computes. Always shown to the operator as a suggestion to
    confirm, never as a discovered fact with the same weight as a real
    ONNX-graph shape."""
    if len(shape) == 2:
        return OutputType.CLASS_LOGITS
    return OutputType.UNKNOWN
