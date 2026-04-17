import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.engine import TrennkostEngine
from trennkost.normalizer import normalize_dish
from trennkost.ontology import get_ontology


@pytest.fixture(scope="module")
def ontology():
    return get_ontology()


@pytest.fixture(scope="module")
def engine():
    return TrennkostEngine()


COMPOUND_STRUCTURE_CASES = [
    {
        "id": "burger_generic_structure",
        "dish_name": "Burger",
        "expected_base_items_subset": {"Brot"},
        "expected_needs_clarification": True,
    },
    {
        "id": "wrap_structure",
        "dish_name": "Wrap",
        "expected_base_items_subset": {"Tortilla"},
        "expected_needs_clarification": True,
    },
    {
        "id": "lasagne_structure",
        "dish_name": "Lasagne",
        "expected_base_items_subset": {"Pasta", "Hackfleisch", "Tomatensauce", "Käse", "Sahne"},
        "expected_needs_clarification": False,
    },
    {
        "id": "hotdog_generic_fallback",
        "dish_name": "Hotdog",
        "expected_base_items_subset": {"Brot", "Wurst"},
        "expected_needs_clarification": True,
    },
]


@pytest.mark.parametrize("case", COMPOUND_STRUCTURE_CASES, ids=lambda c: c["id"])
def test_compound_definitions_are_aligned(ontology, case):
    compound = ontology.get_compound(case["dish_name"])

    assert compound is not None
    assert case["expected_base_items_subset"].issubset(set(compound["base_items"]))
    assert bool(compound["needs_clarification"]) is case["expected_needs_clarification"]


def test_hotdog_modifier_aware_paths_override_generic_fallback():
    classic = normalize_dish("klassischer Hotdog")
    vegetarian = normalize_dish("vegetarischer Hotdog")
    vegan = normalize_dish("veganer Hotdog")

    assert {item.canonical for item in classic.items} == {"Brot", "Wurst"}
    assert {item.canonical for item in vegetarian.items} == {"Brot", "Vegetarische Wurst"}
    assert {item.canonical for item in vegan.items} == {"Brot", "Vegane Wurst"}


def test_lasagne_is_a_stable_compound_not_ok(engine):
    analysis = normalize_dish("Lasagne")
    result = engine.evaluate(analysis)

    assert result.verdict.value == "NOT_OK"


def test_burger_and_wrap_stay_cautious_compounds(engine):
    for dish_name in ("Burger", "Wrap"):
        analysis = normalize_dish(dish_name)
        result = engine.evaluate(analysis, mode="light")

        assert result.required_questions
