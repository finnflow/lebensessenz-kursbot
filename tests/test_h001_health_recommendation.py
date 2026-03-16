"""Regression tests for extracted H001 health/helper recommendation handling."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.engine import TrennkostEngine
from trennkost.formatter import format_results_for_llm
from trennkost.health_recommendations import build_h001_sugar_problem, build_health_recommendation_problems
from trennkost.models import FoodItem, Severity, Verdict
from trennkost.normalizer import normalize_dish


@pytest.fixture(scope="module")
def engine():
    return TrennkostEngine()


def test_health_helper_emits_h001_when_sugar_is_present():
    items = [
        FoodItem(raw_name="Zucker", canonical="Zucker"),
        FoodItem(raw_name="Reis", canonical="Reis"),
    ]

    problems = build_health_recommendation_problems(items)

    assert len(problems) == 1
    problem = problems[0]
    assert problem.rule_id == "H001"
    assert problem.description == "Zucker (weißer Industriezucker) sollte vermieden werden"
    assert problem.affected_groups == ["KH"]


def test_h001_aggregates_multiple_sugar_items_in_stable_order():
    items = [
        FoodItem(raw_name="weißer Zucker", canonical="Zucker"),
        FoodItem(raw_name="brauner Zucker", canonical="Zucker"),
        FoodItem(raw_name="Reis", canonical="Reis"),
    ]

    problem = build_h001_sugar_problem(items)

    assert problem is not None
    assert problem.rule_id == "H001"
    assert problem.affected_items == [
        "weißer Zucker → Zucker",
        "brauner Zucker → Zucker",
    ]


def test_health_helper_skips_h001_without_sugar():
    items = [
        FoodItem(raw_name="Reis", canonical="Reis"),
        FoodItem(raw_name="Hähnchen", canonical="Hähnchen"),
    ]

    problems = build_health_recommendation_problems(items)

    assert problems == []


def test_health_helper_marks_h001_as_info():
    items = [FoodItem(raw_name="Zucker", canonical="Zucker")]

    problem = build_h001_sugar_problem(items)

    assert problem is not None
    assert problem.severity == Severity.INFO


def test_sugar_plus_other_violations_keeps_existing_verdict_logic(engine):
    analysis = normalize_dish("Test", raw_items=["Reis", "Hähnchen", "Zucker"])
    result = engine.evaluate(analysis)

    assert result.verdict == Verdict.NOT_OK
    assert any(problem.rule_id == "R001" for problem in result.problems)
    h001 = [problem for problem in result.problems if problem.rule_id == "H001"]
    assert len(h001) == 1
    assert h001[0].severity == Severity.INFO


def test_formatter_output_for_h001_stays_available(engine):
    analysis = normalize_dish("Test", raw_items=["Zucker"])
    result = engine.evaluate(analysis)

    rendered = format_results_for_llm([result])

    assert "[H001] Zucker (weißer Industriezucker) sollte vermieden werden" in rendered
    assert "Besser: Honig, Ahornsirup oder Kokosblütenzucker verwenden." in rendered
