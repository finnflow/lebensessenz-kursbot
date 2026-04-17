"""Regression tests for subgroup-specific R018 mixed-protein handling."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.engine import TrennkostEngine
from trennkost.formatter import format_results_for_llm
from trennkost.models import AnalysisMode, FoodGroup, FoodItem, FoodSubgroup, Severity, Verdict
from trennkost.normalizer import normalize_dish
from trennkost.protein_rules import build_r018_mixed_protein_problem


@pytest.fixture(scope="module")
def engine():
    return TrennkostEngine()


def _protein_item(name: str, subgroup: FoodSubgroup) -> FoodItem:
    return FoodItem(
        raw_name=name,
        canonical=name,
        group=FoodGroup.PROTEIN,
        subgroup=subgroup,
        group_strict=None,
    )


def test_same_protein_subgroup_has_no_r018():
    items = [
        _protein_item("Hähnchen", FoodSubgroup.FLEISCH),
        _protein_item("Rindfleisch", FoodSubgroup.FLEISCH),
    ]

    problem = build_r018_mixed_protein_problem(items, mode=AnalysisMode.TRENNKOST)

    assert problem is None


def test_distinct_protein_subgroups_emit_r018():
    items = [
        _protein_item("Hähnchen", FoodSubgroup.FLEISCH),
        _protein_item("Ei", FoodSubgroup.EIER),
    ]

    problem = build_r018_mixed_protein_problem(items, mode=AnalysisMode.TRENNKOST)

    assert problem is not None
    assert problem.rule_id == "R018"
    assert problem.description == "Verschiedene Proteinquellen nicht kombinieren"
    assert problem.affected_groups == ["PROTEIN"]


def test_r018_affected_items_are_subgroup_based_and_stable():
    items = [
        _protein_item("Hähnchen", FoodSubgroup.FLEISCH),
        _protein_item("Ei", FoodSubgroup.EIER),
        _protein_item("Rindfleisch", FoodSubgroup.FLEISCH),
    ]

    problem = build_r018_mixed_protein_problem(items, mode=AnalysisMode.TRENNKOST)

    assert problem is not None
    assert problem.affected_items == [
        "Ei (EIER)",
        "Hähnchen (FLEISCH)",
        "Rindfleisch (FLEISCH)",
    ]


def test_r018_severity_stays_critical():
    items = [
        _protein_item("Lachs", FoodSubgroup.FISCH),
        _protein_item("Ei", FoodSubgroup.EIER),
    ]

    problem = build_r018_mixed_protein_problem(items, mode=AnalysisMode.TRENNKOST)

    assert problem is not None
    assert problem.severity == Severity.CRITICAL


def test_mixed_protein_subgroups_keep_existing_not_ok_verdict(engine):
    analysis = normalize_dish("Test", raw_items=["Hähnchen", "Ei"])
    result = engine.evaluate(analysis)

    assert result.verdict == Verdict.NOT_OK
    r018 = [problem for problem in result.problems if problem.rule_id == "R018"]
    assert len(r018) == 1


def test_other_not_ok_plus_r018_keeps_verdict_logic_stable(engine):
    analysis = normalize_dish("Test", raw_items=["Reis", "Hähnchen", "Ei"])
    result = engine.evaluate(analysis)

    assert result.verdict == Verdict.NOT_OK
    assert any(problem.rule_id == "R001" for problem in result.problems)
    assert any(problem.rule_id == "R018" for problem in result.problems)


def test_formatter_output_keeps_r018_visible(engine):
    analysis = normalize_dish("Test", raw_items=["Hähnchen", "Ei"])
    result = engine.evaluate(analysis)

    rendered = format_results_for_llm([result])

    assert "[R018] Verschiedene Proteinquellen nicht kombinieren" in rendered
