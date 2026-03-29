import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.analyzer import analyze_text
from trennkost.models import Verdict


def _analyze_single(text: str):
    results = analyze_text(text, llm_fn=None, mode="strict", evaluation_mode="strict")
    assert len(results) == 1
    return results[0]


def _problem_ids(result) -> set[str]:
    return {problem.rule_id for problem in result.problems}


def test_realworld_jar_breakfast_is_not_falsely_ok():
    result = _analyze_single("Jar breakfast: fried chicken, poached egg and pickle")

    assert result.active_mode_verdict == Verdict.NOT_OK
    assert "R018" in _problem_ids(result)
    assert result.debug["unknown_items"] == []
    assert result.required_questions == []


def test_realworld_spaghetti_bolognese_keeps_dish_identity_without_hallucination():
    result = _analyze_single("Spaghetti Bolognese")

    assert result.dish_name == "Spaghetti Bolognese"
    assert result.active_mode_verdict == Verdict.NOT_OK
    assert "R001" in _problem_ids(result)
    assert result.debug["unknown_items"] == []


def test_realworld_avocadotoast_breakfast_stable_compound_equivalent():
    result = _analyze_single("Ist Avocadotoast zum Frühstück ok?")

    assert result.dish_name == "Avocadotoast"
    assert result.active_mode_verdict == Verdict.CONDITIONAL
    assert result.required_questions
    assert result.debug["unknown_items"] == []


@pytest.mark.xfail(
    strict=False,
    reason="Characterization: hyphenated Avocado-Toast alias is not yet resolved to Avocadotoast compound semantics",
)
def test_realworld_hyphenated_avocado_toast_should_not_fall_back_to_false_ok():
    result = _analyze_single("Ist Avocado-Toast zum Frühstück ok?")

    assert result.active_mode_verdict != Verdict.OK


def test_realworld_vegan_burger_keeps_clarification_scoped_to_unknown_patty_basis():
    result = _analyze_single("Veganer Burger mit Patty, Salat, Gurke und Ketchup")
    unknowns = set(result.debug["unknown_items"])

    assert unknowns == {"Veganes Patty", "Patty"}
    assert result.required_questions
    assert all(set(question.affects_items).issubset(unknowns) for question in result.required_questions)


def test_realworld_unknown_ingredient_stays_unknown_instead_of_hallucinated():
    result = _analyze_single("Unknown-Zutat mit Reis")

    assert result.active_mode_verdict == Verdict.CONDITIONAL
    assert result.debug["unknown_items"] == ["Unknown-Zutat"]
    assert len(result.required_questions) == 1
    assert result.required_questions[0].affects_items == ["Unknown-Zutat"]


def test_realworld_lentil_soup_with_vegetables_keeps_known_dish_without_inventing_unknowns():
    result = _analyze_single("Linsensuppe mit Gemüse")

    assert result.dish_name == "Linsensuppe"
    assert result.active_mode_verdict in {Verdict.NOT_OK, Verdict.CONDITIONAL}
    assert result.debug["unknown_items"] == []


def test_realworld_pad_thai_with_tofu_and_peanuts_is_not_falsely_ok():
    result = _analyze_single("Pad Thai mit Tofu und Erdnüssen")

    assert result.dish_name == "Pad Thai"
    assert result.active_mode_verdict != Verdict.OK
    assert result.debug["unknown_items"] == []
    assert {"R001", "R018"} & _problem_ids(result)
