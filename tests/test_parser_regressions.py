import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.analyzer import _parse_text_input, analyze_text
from trennkost.normalizer import normalize_dish


PARSER_REGRESSION_CASES = [
    {
        "id": "plus_separator_pommes_mayo",
        "input_text": "Pommes + Mayo",
        "expected_raw_items": ["Pommes", "Mayo"],
        "expected_canonicals_subset": {"Pommes", "Mayonnaise"},
    },
    {
        "id": "plus_separator_bratkartoffeln_ei",
        "input_text": "Bratkartoffeln + Ei",
        "expected_raw_items": ["Bratkartoffeln", "Ei"],
        "expected_canonicals_subset": {"Bratkartoffeln", "Ei"},
    },
    {
        "id": "plus_separator_tofu_reis",
        "input_text": "Tofu + Reis",
        "expected_raw_items": ["Tofu", "Reis"],
        "expected_canonicals_subset": {"Tofu", "Reis"},
    },
    {
        "id": "gekochte_kartoffeln_brokkoli_preserves_prep",
        "input_text": "gekochte Kartoffeln mit Brokkoli",
        "expected_raw_items": ["gekochte Kartoffeln", "Brokkoli"],
        "expected_canonicals_subset": {"Brokkoli"},
        "require_any_potato_form": {"Kartoffel", "Kartoffel gekocht"},
        "needs_prep_soft_check": True,
    },
    {
        "id": "bratkartoffeln_mit_ei_preserves_fried_variant",
        "input_text": "Bratkartoffeln mit Ei",
        "expected_raw_items": None,
        "expected_canonicals_subset": {"Kartoffel", "Ei"},
        "require_any_potato_form": set(),
        "needs_prep_soft_check": False,
    },
]


@pytest.mark.parametrize("case", PARSER_REGRESSION_CASES, ids=lambda c: c["id"])
def test_parse_text_input_regressions(case):
    parsed = _parse_text_input(case["input_text"])

    assert len(parsed) == 1
    assert parsed[0]["items"] == case["expected_raw_items"]

    analysis = normalize_dish(
        dish_name=parsed[0]["name"],
        raw_items=parsed[0]["items"],
    )

    canonicals = {item.canonical for item in analysis.items}
    assert case["expected_canonicals_subset"].issubset(canonicals)

    if case.get("require_any_potato_form"):
        assert canonicals.intersection(case["require_any_potato_form"])

    if case.get("needs_prep_soft_check"):
        assert any(
            item.canonical in {"Kartoffel", "Kartoffel gekocht"}
            and "gekocht" in item.raw_name.lower()
            for item in analysis.items
        )


MODIFIER_AWARE_ANALYZER_CASES = [
    {
        "id": "normaler_burger_stays_open",
        "input_text": "Ist ein normaler Burger ok?",
        "expect_needs_clarification": False,
        "expect_not_not_ok_by_default": True,
    },
    {
        "id": "veganer_burger_modifier_aware",
        "input_text": "Ist ein veganer Burger ok?",
        "expect_needs_clarification": True,
    },
    {
        "id": "klassischer_hotdog_modifier_aware",
        "input_text": "Ist ein klassischer Hotdog ok?",
        "expect_needs_clarification": False,
    },
    {
        "id": "vegetarischer_hotdog_modifier_aware",
        "input_text": "Ist ein vegetarischer Hotdog ok?",
        "expect_needs_clarification": True,
    },
]


@pytest.mark.parametrize("case", MODIFIER_AWARE_ANALYZER_CASES, ids=lambda c: c["id"])
def test_modifier_aware_natural_language_cases(case):
    results = analyze_text(case["input_text"], llm_fn=None, mode="strict", evaluation_mode="light")

    assert len(results) == 1
    result = results[0]

    assert bool(result.required_questions) is case["expect_needs_clarification"]

    if case.get("expect_not_not_ok_by_default"):
        assert result.verdict.value != "NOT_OK"
