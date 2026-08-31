from __future__ import annotations

import numpy as np

from app.modules.ai_research_plugin.contracts import (
    ModelFramework,
    OutputType,
    RFModelManifest,
    RFModelOutputFields,
)
from app.modules.ai_research_plugin.interpretation import interpret_output


def _manifest(output_type: OutputType | None, classes: list[str] | None = None) -> RFModelManifest:
    return RFModelManifest(
        model_id="AI-MODEL-test",
        model_name="test",
        framework=ModelFramework.ONNX,
        model_file="test.onnx",
        model_sha256="a" * 64,
        imported_at_utc="2026-01-01T00:00:00Z",
        output_discovered=RFModelOutputFields(output_type=output_type, classes=classes),
    )


def test_classifies_using_the_real_argmax_and_never_fabricates_a_probability_from_logits():
    manifest = _manifest(OutputType.CLASS_LOGITS, classes=["BPSK", "QPSK", "8PSK"])
    raw = np.array([0.5, 3.2, -1.0])

    result = interpret_output(raw, manifest)

    assert result["kind"] == "classification"
    assert result["predicted_class"] == "QPSK"
    assert result["score"] == 3.2
    assert result["score_type"] == "logit"  # never silently relabeled as "probability"


def test_reports_probability_score_type_only_when_the_manifest_says_the_output_already_is_one():
    manifest = _manifest(OutputType.CLASS_PROBABILITIES, classes=["BPSK", "QPSK"])
    raw = np.array([0.1, 0.9])
    result = interpret_output(raw, manifest)
    assert result["score_type"] == "probability"
    assert result["predicted_class"] == "QPSK"


def test_class_scores_dict_has_every_real_class_with_its_real_score():
    manifest = _manifest(OutputType.CLASS_LOGITS, classes=["A", "B", "C"])
    raw = np.array([1.0, 2.0, 3.0])
    result = interpret_output(raw, manifest)
    assert result["class_scores"] == {"A": 1.0, "B": 2.0, "C": 3.0}


def test_always_carries_the_static_domain_disclaimer_on_a_classification_result():
    manifest = _manifest(OutputType.CLASS_LOGITS, classes=["A", "B"])
    result = interpret_output(np.array([0.1, 0.2]), manifest)
    assert "should not be interpreted as confirmed" in result["warning"]


def test_declared_classification_without_a_matching_class_list_is_not_interpretable():
    manifest = _manifest(OutputType.CLASS_LOGITS, classes=None)
    result = interpret_output(np.array([0.1, 0.2, 0.3]), manifest)
    assert result["kind"] == "not_automatically_interpretable"


def test_declared_classification_with_a_mismatched_class_count_is_not_interpretable():
    manifest = _manifest(OutputType.CLASS_LOGITS, classes=["A", "B"])  # only 2, output has 3
    result = interpret_output(np.array([0.1, 0.2, 0.3]), manifest)
    assert result["kind"] == "not_automatically_interpretable"


def test_embedding_output_reports_real_dimensionality_and_norm_not_a_class():
    manifest = _manifest(OutputType.EMBEDDING)
    raw = np.array([3.0, 4.0])  # norm = 5, exactly
    result = interpret_output(raw, manifest)
    assert result["kind"] == "embedding"
    assert result["dimensionality"] == 2
    assert result["l2_norm"] == 5.0


def test_unknown_output_type_is_honestly_not_interpretable_rather_than_guessed():
    manifest = _manifest(OutputType.UNKNOWN)
    result = interpret_output(np.array([1.0, 2.0]), manifest)
    assert result["kind"] == "not_automatically_interpretable"


def test_unset_output_type_is_also_honestly_not_interpretable():
    manifest = _manifest(None)
    result = interpret_output(np.array([1.0]), manifest)
    assert result["kind"] == "not_automatically_interpretable"
    assert "unset" in result["warning"]
