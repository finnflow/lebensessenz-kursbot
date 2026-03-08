"""
Focused tests for centralized effective-group resolution.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.models import FoodGroup, Verdict
from trennkost.normalizer import normalize_dish
from trennkost.ontology import Ontology, resolve_effective_group
from trennkost.engine import TrennkostEngine


@pytest.fixture(scope="module")
def ontology():
    return Ontology()


def test_resolve_effective_group_is_strict_only_and_stable(ontology):
    banana = ontology.lookup_to_food_item("Banane")
    dried = ontology.lookup_to_food_item("Datteln")
    tofu = ontology.lookup_to_food_item("Tofu")
    mayo = ontology.lookup_to_food_item("Mayonnaise")

    assert resolve_effective_group(banana) == FoodGroup.OBST
    assert resolve_effective_group(dried) == FoodGroup.TROCKENOBST
    assert resolve_effective_group(tofu) == FoodGroup.HUELSENFRUECHTE
    assert resolve_effective_group(mayo) == FoodGroup.FETT

    with pytest.raises(NotImplementedError):
        resolve_effective_group(mayo, mode="light")


def test_engine_uses_effective_group_resolver(monkeypatch):
    analysis = normalize_dish("Test", raw_items=["Kartoffel", "Mayonnaise"])

    def fake_resolver(item, mode="strict"):
        if item.canonical == "Mayonnaise":
            return FoodGroup.NEUTRAL
        return item.group

    monkeypatch.setattr("trennkost.engine.resolve_effective_group", fake_resolver)

    result = TrennkostEngine().evaluate(analysis)

    assert "NEUTRAL" in result.groups_found
    assert "FETT" not in result.groups_found


def test_mayonnaise_now_uses_target_group_in_strict_evaluation():
    analysis = normalize_dish("Test", raw_items=["Kartoffel", "Mayonnaise"])
    result = TrennkostEngine().evaluate(analysis)

    assert result.verdict == Verdict.OK
    assert "FETT" in result.groups_found
    assert "NEUTRAL" not in result.groups_found
    assert result.guidance_codes == ["FAT_WITH_CONFLICT_GROUP_TINY_AMOUNT"]
