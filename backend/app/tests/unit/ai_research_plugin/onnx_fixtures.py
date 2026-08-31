"""Builds a real, minimal, valid ONNX model in-memory for tests -- no
external model file, no network download, no torch->onnx export step.
Shape: input [1, 2, N_SAMPLES] (batch, I/Q, samples) -> Flatten -> Gemm ->
output [1, N_CLASSES] class logits. Passes `onnx.checker.check_model` for
real, exercising the exact code path `inspect_onnx_model` uses on a real
file, not a mock.
"""

from __future__ import annotations

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

N_SAMPLES = 128
N_CLASSES = 5


def build_toy_amc_onnx_bytes(n_samples: int = N_SAMPLES, n_classes: int = N_CLASSES) -> bytes:
    input_info = helper.make_tensor_value_info("iq_input", TensorProto.FLOAT, [1, 2, n_samples])
    output_info = helper.make_tensor_value_info("class_logits", TensorProto.FLOAT, [1, n_classes])

    flat_dim = 2 * n_samples
    rng = np.random.default_rng(seed=0)
    weight = numpy_helper.from_array(rng.standard_normal((n_classes, flat_dim)).astype(np.float32), name="W")
    bias = numpy_helper.from_array(rng.standard_normal((n_classes,)).astype(np.float32), name="b")

    flatten_node = helper.make_node("Flatten", inputs=["iq_input"], outputs=["flat"], axis=1)
    gemm_node = helper.make_node("Gemm", inputs=["flat", "W", "b"], outputs=["class_logits"], transB=1)

    graph = helper.make_graph(
        nodes=[flatten_node, gemm_node],
        name="toy_amc_classifier",
        inputs=[input_info],
        outputs=[output_info],
        initializer=[weight, bias],
    )
    model = helper.make_model(graph, producer_name="spectrum-lab-test-fixture")
    model.opset_import[0].version = 17
    onnx.checker.check_model(model)
    return model.SerializeToString()


def build_invalid_onnx_bytes() -> bytes:
    return b"not a real onnx file"
