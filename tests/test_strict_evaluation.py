"""
Focused tests for strict combination-group evaluation.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.models import Verdict
from trennkost.normalizer import normalize_dish
from trennkost.engine import TrennkostEngine


@pytest.fixture(scope="module")
def engine():
    return TrennkostEngine()


def test_banana_keeps_distinct_strict_group_but_mixed_fruit_salad_is_ok(engine):
    watery_only = normalize_dish("Test", raw_items=["Apfel", "Kiwi"])
    dense_mix = normalize_dish("Test", raw_items=["Apfel", "Banane"])

    watery_result = engine.evaluate(watery_only)
    dense_result = engine.evaluate(dense_mix)

    assert watery_result.verdict == Verdict.OK
    assert dense_result.verdict == Verdict.OK
    assert dense_result.problems == []
    assert set(dense_result.strict_groups_found) == {"FRUIT_WATERY", "FRUIT_DENSE"}


def test_dried_fruit_keeps_distinct_strict_group_but_mixed_fruit_salad_is_ok(engine):
    analysis = normalize_dish("Test", raw_items=["Apfel", "Dattel"])
    result = engine.evaluate(analysis)

    assert result.verdict == Verdict.OK
    assert result.problems == []
    assert set(result.strict_groups_found) == {"FRUIT_WATERY", "DRIED_FRUIT"}


def test_fruit_and_leafy_greens_smoothie_stays_explicitly_ok(engine):
    analysis = normalize_dish("Smoothie", raw_items=["Apfel", "Banane", "Spinat"])
    result = engine.evaluate(analysis)

    assert result.verdict == Verdict.OK
    assert any(note == "Obst + Blattgrün ist OK (Smoothie-Ausnahme)" for note in result.ok_combinations)
    assert set(result.strict_groups_found) == {"FRUIT_WATERY", "FRUIT_DENSE", "NEUTRAL"}


@pytest.mark.parametrize("raw_name", ["Tofu", "Tempeh"])
def test_plant_proteins_now_follow_protein_milk_rule(engine, raw_name):
    analysis = normalize_dish("Test", raw_items=[raw_name, "Käse"])
    result = engine.evaluate(analysis)

    assert result.verdict == Verdict.NOT_OK
    assert any(problem.rule_id == "R006" for problem in result.problems)
    assert not any(problem.rule_id == "R005" for problem in result.problems)
    assert "PROTEIN" in result.strict_groups_found
    assert "MILCH" in result.strict_groups_found


def test_seitan_behaves_as_protein_in_strict_evaluation(engine):
    analysis = normalize_dish("Test", raw_items=["Seitan", "Reis"])
    result = engine.evaluate(analysis)

    assert result.verdict == Verdict.NOT_OK
    assert any(problem.rule_id == "R001" for problem in result.problems)
    assert "PROTEIN" in result.strict_groups_found
    assert "KH" in result.strict_groups_found


def test_mayonnaise_fat_guidance_survives_strict_group_migration(engine):
    analysis = normalize_dish("Test", raw_items=["Kartoffel", "Mayonnaise"])
    result = engine.evaluate(analysis)

    assert result.verdict == Verdict.OK
    assert result.guidance_codes == ["FAT_WITH_CONFLICT_GROUP_TINY_AMOUNT"]
    assert set(result.strict_groups_found) == {"KH", "FETT"}
