"""explain_feasibility()'s next_steps and recommend_scientific_task() exist
because an operator with no RF-fingerprinting background cannot infer "add 3
more target sessions" from a bare have/need number dump, and has no way to
know which of the three scientific tasks even fits their current data
without checking each one by hand -- this is exactly the real confusion
reported in session (one physical unit + environment captures, but the
default task, SAME_MODEL_UNIT_IDENTIFICATION, needs two units of the same
model and can never become feasible with only one).
"""
from __future__ import annotations

from app.modules.ble_rffi_studio.quality.feasibility_explainer import explain_feasibility, recommend_scientific_task

from ._helpers import make_example


def _one_unit_plus_environment_examples() -> list:
    """Exactly the real scenario reported: one physical unit (Shelly, one
    isolation-declared session) plus three environment-only sessions, each
    from a capture the operator explicitly declared BACKGROUND_ENVIRONMENT
    (never just "no address match" -- see split_builder.py's module
    docstring for why that distinction matters)."""
    examples = []
    counter = 0
    for session_index in range(3):
        session_id = f"ENV-SESSION-{session_index:02d}"
        examples.append(make_example(example_index=counter, physical_unit_id=None, session_id=session_id, capture_purpose="BACKGROUND_TARGET_OFF"))
        counter += 1
    examples.append(make_example(example_index=counter, physical_unit_id="SHELLY-PLUG-01", session_id="SHELLY-SESSION-00"))
    return examples


def test_same_model_unit_identification_next_steps_names_the_missing_unit_count():
    examples = _one_unit_plus_environment_examples()
    result = explain_feasibility(examples, "SAME_MODEL_UNIT_IDENTIFICATION")
    assert result["feasible"] is False
    assert any("1 unidad" in step and "mismo modelo" in step for step in result["next_steps"])


def test_target_vs_background_next_steps_names_missing_target_sessions():
    examples = _one_unit_plus_environment_examples()
    result = explain_feasibility(examples, "TARGET_VS_BACKGROUND")
    assert result["feasible"] is False
    # 1 target session so far, needs 3 -- next_steps must say exactly 2 more.
    assert any("2 sesion" in step and "objetivo" in step for step in result["next_steps"])


def test_feasible_task_reports_no_next_steps():
    examples = _one_unit_plus_environment_examples()
    # Pad up to 3 independent target sessions and >=1 background session --
    # matches TARGET_VS_BACKGROUND's real minimums.
    examples += [make_example(example_index=100 + i, physical_unit_id="SHELLY-PLUG-01", session_id=f"SHELLY-SESSION-{i:02d}") for i in range(1, 3)]
    result = explain_feasibility(examples, "TARGET_VS_BACKGROUND")
    assert result["feasible"] is True
    assert result["next_steps"] == []


def test_recommend_scientific_task_prefers_target_vs_background_for_a_single_unit():
    """The exact real confusion this exists to prevent: with only one
    physical unit registered, SAME_MODEL_UNIT_IDENTIFICATION can never be
    feasible (it structurally needs two units of the same model) --
    TARGET_VS_BACKGROUND is the task that actually fits this data."""
    examples = _one_unit_plus_environment_examples()
    recommendation = recommend_scientific_task(examples)
    assert recommendation["recommended_task"] == "TARGET_VS_BACKGROUND"
    assert len(recommendation["candidates"]) == 3
    same_model = next(c for c in recommendation["candidates"] if c["scientific_task"] == "SAME_MODEL_UNIT_IDENTIFICATION")
    assert same_model["feasible"] is False


def test_recommend_scientific_task_prefers_an_already_feasible_task_over_a_partially_ready_one():
    examples = _one_unit_plus_environment_examples()
    examples += [make_example(example_index=100 + i, physical_unit_id="SHELLY-PLUG-01", session_id=f"SHELLY-SESSION-{i:02d}") for i in range(1, 3)]
    recommendation = recommend_scientific_task(examples)
    assert recommendation["recommended_task"] == "TARGET_VS_BACKGROUND"
    recommended_candidate = next(c for c in recommendation["candidates"] if c["scientific_task"] == "TARGET_VS_BACKGROUND")
    assert recommended_candidate["feasible"] is True
    assert "suficientes datos" in recommendation["reason"]


def test_target_vs_background_ignores_no_match_examples_from_a_target_device_capture():
    """The exact real bug this fix targets: two TARGET_DEVICE-declared
    captures whose evidence never matched a registered address (quarantined/
    no-match, physical_unit_id=None) were silently counted as "2 sesiones
    ambientales" by the old code, recommending TARGET_VS_BACKGROUND as
    feasible when there was no real background evidence at all."""
    examples = [
        make_example(example_index=i, physical_unit_id="TARGET-UNIT", session_id=f"TARGET-S-{i}", capture_purpose="TARGET_DEVICE_ON")
        for i in range(3)
    ] + [
        make_example(example_index=100 + i, physical_unit_id=None, session_id=f"UNMATCHED-S-{i}", capture_purpose="TARGET_DEVICE_ON", association_status="NONE")
        for i in range(3)
    ]
    result = explain_feasibility(examples, "TARGET_VS_BACKGROUND")
    assert result["have"]["background_sessions"] == 0
    assert result["feasible"] is False
    assert any("apagado o retirado" in step for step in result["next_steps"])


def test_recommend_scientific_task_with_no_data_at_all_still_returns_a_best_guess():
    recommendation = recommend_scientific_task([])
    assert recommendation["recommended_task"] in {"TARGET_VS_BACKGROUND", "SAME_MODEL_UNIT_IDENTIFICATION", "UNKNOWN_DEVICE_REJECTION"}
    assert len(recommendation["candidates"]) == 3
    assert all(c["feasible"] is False for c in recommendation["candidates"])
