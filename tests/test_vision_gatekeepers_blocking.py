import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.analyzer import analyze_vision
from trennkost.models import Verdict


def test_vision_strict_uncertain_herb_does_not_trigger_unnecessary_clarification():
    result = analyze_vision(
        [{"name": "Vision Teller", "items": ["Reis"], "uncertain_items": ["Petersilie"]}],
        llm_fn=None,
        mode="strict",
        evaluation_mode="strict",
    )[0]

    assert result.strict_verdict == Verdict.OK
    assert result.active_mode_verdict == Verdict.OK
    assert result.required_questions == []
    assert result.debug["unknown_items"] == []


def test_vision_strict_uncertain_egg_becomes_conditional_with_required_question():
    result = analyze_vision(
        [{"name": "Vision Teller", "items": ["Reis"], "uncertain_items": ["Ei"]}],
        llm_fn=None,
        mode="strict",
        evaluation_mode="strict",
    )[0]

    assert result.strict_verdict == Verdict.OK
    assert result.active_mode_verdict == Verdict.CONDITIONAL
    assert len(result.required_questions) == 1
    assert result.required_questions[0].affects_items == ["Ei"]
    assert result.debug["unknown_items"] == []


def test_vision_unknown_uncertain_sauce_item_stays_unknown_without_duplicate_question():
    result = analyze_vision(
        [
            {
                "name": "Vision Teller",
                "items": ["Reis", "Brokkoli"],
                "uncertain_items": ["Fleisch in Sauce"],
            }
        ],
        llm_fn=None,
        mode="strict",
        evaluation_mode="strict",
    )[0]

    assert result.active_mode_verdict == Verdict.CONDITIONAL
    assert result.debug["unknown_items"] == ["Fleisch in Sauce"]
    assert len(result.required_questions) == 1
    assert result.required_questions[0].affects_items == ["Fleisch in Sauce"]
