"""Result Interpreter (spec sections 12, 18, 20) -- turns a raw model
output array into an interpretation, keeping three concepts explicitly
separate (spec section 12): the raw numeric output, what it is
interpreted to mean, and (built by the caller, not here) the RF visual
evidence it was computed from.

Two disclosed limitations, both intentional:
- Only CLASS_LOGITS / CLASS_PROBABILITIES / EMBEDDING output types are
  interpreted. RECONSTRUCTION (anomaly detection reconstruction error)
  and DETECTOR (t0,t1,f0,f1,c,s tuples) are real, documented Phase-2 gaps
  (spec section 18) -- their raw output is still returned untouched, just
  not further interpreted.
- This module NEVER runs a softmax over logits to manufacture a
  "probability" that the model itself did not produce. If the manifest
  declares the output is already CLASS_PROBABILITIES, the raw value is
  reported with score_type="probability"; if it declares CLASS_LOGITS,
  the raw value is reported with score_type="logit" -- exactly the
  distinction spec section 15 asks for ("nunca 91% de certeza física").
"""

from __future__ import annotations

from typing import Any

import numpy as np

from app.modules.ai_research_plugin.contracts import OutputType, RFModelManifest

# A STATIC disclaimer (spec section 20's own worked example is exactly
# this sentence, not a computed anomaly score) -- this plugin does not
# implement real out-of-distribution detection, so it never claims to.
# Always shown alongside a classification interpretation, not
# conditionally, since there is no real signal here to condition on.
DOMAIN_WARNING = (
    "This prediction reflects only the model's own known class list and training "
    "distribution. It should not be interpreted as confirmed protocol/device "
    "identification, especially if the observed signal may fall outside the "
    "model's documented training domain."
)


def interpret_output(raw_output: np.ndarray, manifest: RFModelManifest) -> dict[str, Any]:
    output_spec = manifest.effective_output()
    flat = raw_output.reshape(-1)

    if output_spec.output_type in (OutputType.CLASS_LOGITS, OutputType.CLASS_PROBABILITIES):
        classes = output_spec.classes
        if classes and len(classes) == flat.shape[0]:
            top_index = int(np.argmax(flat))
            score_type = "probability" if output_spec.output_type == OutputType.CLASS_PROBABILITIES else "logit"
            return {
                "kind": "classification",
                "predicted_class": classes[top_index],
                "score": float(flat[top_index]),
                "score_type": score_type,
                "class_scores": {cls: float(flat[i]) for i, cls in enumerate(classes)},
                "known_classes": list(classes),
                "warning": DOMAIN_WARNING,
            }
        return {
            "kind": "not_automatically_interpretable",
            "warning": (
                "Manifest declares a classification output_type but no class list of the "
                "matching length is set -- supply `output.classes` (manifest override) to enable interpretation."
            ),
        }

    if output_spec.output_type == OutputType.EMBEDDING:
        return {
            "kind": "embedding",
            "dimensionality": int(flat.shape[0]),
            "l2_norm": float(np.linalg.norm(flat)),
            "warning": "Embeddings are only directly comparable to other embeddings from the SAME model.",
        }

    return {
        "kind": "not_automatically_interpretable",
        "warning": (
            f"output_type={output_spec.output_type.value if output_spec.output_type else 'unset'} has no "
            f"implemented interpretation path in this phase -- raw output only."
        ),
    }
