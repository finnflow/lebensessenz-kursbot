"""
Focused tests for centralized effective-group resolution.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.models import CombinationGroup, EvaluationMode, FoodGroup, Verdict
from trennkost.normalizer import normalize_dish
from trennkost.ontology import (
    Ontology,
    resolve_combination_group,
    resolve_effective_group,
    resolve_strict_combination_group,
)
from trennkost.engine import TrennkostEngine


@pytest.fixture(scope="module")
def ontology():
    return Ontology()


def test_resolvers_expose_strict_and_display_groups(ontology):
    banana = ontology.lookup_to_food_item("Banane")
    dried = ontology.lookup_to_food_item("Datteln")
    tofu = ontology.lookup_to_food_item("Tofu")
    mayo = ontology.lookup_to_food_item("Mayonnaise")

    assert resolve_strict_combination_group(banana) == CombinationGroup.FRUIT_DENSE
    assert resolve_strict_combination_group(dried) == CombinationGroup.DRIED_FRUIT
    assert resolve_strict_combination_group(tofu) == CombinationGroup.PROTEIN
    assert resolve_strict_combination_group(mayo) == CombinationGroup.FETT

    assert resolve_effective_group(banana) == FoodGroup.OBST
    assert resolve_effective_group(dried) == FoodGroup.TROCKENOBST
    assert resolve_effective_group(tofu) == FoodGroup.PROTEIN
    assert resolve_effective_group(mayo) == FoodGroup.FETT

    assert resolve_combination_group(banana, mode=EvaluationMode.LIGHT) == CombinationGroup.KH
    assert resolve_combination_group(dried, mode=EvaluationMode.LIGHT) == CombinationGroup.KH
    assert resolve_combination_group(tofu, mode=EvaluationMode.LIGHT) == CombinationGroup.KH
    assert resolve_combination_group(mayo, mode=EvaluationMode.LIGHT) == CombinationGroup.FETT

    assert resolve_effective_group(banana, mode=EvaluationMode.LIGHT) == FoodGroup.KH
    assert resolve_effective_group(dried, mode=EvaluationMode.LIGHT) == FoodGroup.KH
    assert resolve_effective_group(tofu, mode=EvaluationMode.LIGHT) == FoodGroup.KH
    assert resolve_effective_group(mayo, mode=EvaluationMode.LIGHT) == FoodGroup.FETT


def test_engine_uses_strict_group_resolver(monkeypatch):
    analysis = normalize_dish("Test", raw_items=["Kartoffel", "Mayonnaise"])

    def fake_resolver(item, mode=EvaluationMode.STRICT):
        if item.canonical == "Mayonnaise" and mode == EvaluationMode.STRICT:
            return CombinationGroup.NEUTRAL
        return item.group_strict or CombinationGroup.UNKNOWN

    monkeypatch.setattr("trennkost.engine.resolve_combination_group", fake_resolver)

    result = TrennkostEngine().evaluate(analysis)

    assert "NEUTRAL" in result.groups_found
    assert "FETT" not in result.groups_found
    assert "NEUTRAL" in result.strict_groups_found
    assert "FETT" not in result.strict_groups_found


def test_mayonnaise_now_uses_target_group_in_strict_evaluation():
    analysis = normalize_dish("Test", raw_items=["Kartoffel", "Mayonnaise"])
    result = TrennkostEngine().evaluate(analysis)

    assert result.verdict == Verdict.OK
    assert "FETT" in result.groups_found
    assert "NEUTRAL" not in result.groups_found
    assert "FETT" in result.strict_groups_found
    assert result.guidance_codes == ["FAT_WITH_CONFLICT_GROUP_TINY_AMOUNT"]
