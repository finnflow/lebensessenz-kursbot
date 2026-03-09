"""
Focused tests for compound backfill alignment with newer canonicals.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.models import ModifierTag
from trennkost.ontology import Ontology
from trennkost.normalizer import normalize_dish


@pytest.mark.parametrize(
    ("dish_name", "expected_variant"),
    [
        ("veganer Burger", "Veganes Patty"),
        ("vegetarischer Burger", "Vegetarisches Patty"),
        ("Veggie Burger", "Vegetarisches Patty"),
    ],
)
def test_burger_family_uses_cautious_variant_canonicals(dish_name, expected_variant):
    analysis = normalize_dish(dish_name)

    assert {item.canonical for item in analysis.items} == {"Brot", expected_variant}
    assert "Kichererbsen" not in {item.canonical for item in analysis.items}
    variant = next(item for item in analysis.items if item.canonical == expected_variant)
    assert variant.group.value == "UNKNOWN"
    assert analysis.unknown_items == [expected_variant]


@pytest.mark.parametrize(
    ("dish_name", "expected_variant", "expected_tag"),
    [
        ("klassischer Hotdog", "Wurst", ModifierTag.HINT_CLASSIC),
        ("vegetarischer Hotdog", "Vegetarische Wurst", ModifierTag.VEGETARIAN),
        ("veganer Hotdog", "Vegane Wurst", ModifierTag.VEGAN),
    ],
)
def test_hotdog_family_preserves_variant_resolution(dish_name, expected_variant, expected_tag):
    analysis = normalize_dish(dish_name)

    assert {item.canonical for item in analysis.items} == {"Brot", expected_variant}
    variant = next(item for item in analysis.items if item.canonical == expected_variant)
    assert variant.recognized_modifiers == [expected_tag]


def test_hotdog_compounds_exist_as_generic_restaurant_fallbacks():
    ontology = Ontology()

    hotdog = ontology.get_compound("Hotdog")
    hotdog_with_fries = ontology.get_compound("Hotdog mit Pommes")

    assert hotdog is not None
    assert hotdog["base_items"] == ["Brot", "Wurst"]
    assert hotdog["optional_items"] == ["Senf", "Ketchup"]

    assert hotdog_with_fries is not None
    assert hotdog_with_fries["base_items"] == ["Brot", "Wurst", "Pommes"]
    assert hotdog_with_fries["optional_items"] == ["Senf", "Ketchup", "Mayonnaise"]


def test_schnitzel_mit_pommes_uses_prepared_and_potato_canonicals():
    analysis = normalize_dish("Schnitzel mit Pommes")

    canonicals = [item.canonical for item in analysis.items]
    assert canonicals[0] == "Paniertes Schnitzel"
    assert "Pommes" in canonicals
    assert {"Schwein", "Paniermehl", "Ei"}.issubset(set(canonicals))
    assert "Kartoffel" not in canonicals
    assert any(item.canonical == "Zitronensaft" for item in analysis.assumed_items)
    assert any(item.canonical == "Kopfsalat" for item in analysis.assumed_items)


def test_wiener_schnitzel_keeps_breaded_core_without_forcing_generic_potatoes():
    analysis = normalize_dish("Wiener Schnitzel")

    canonicals = [item.canonical for item in analysis.items]
    assumed_canonicals = [item.canonical for item in analysis.assumed_items]

    assert canonicals[0] == "Paniertes Schnitzel"
    assert {"Schwein", "Paniermehl", "Ei"}.issubset(set(canonicals))
    assert "Kartoffel" not in canonicals
    assert "Kartoffel gekocht" in assumed_canonicals


def test_fischstaebchen_mit_pommes_uses_intrinsic_prepared_canonical():
    analysis = normalize_dish("Fischstäbchen mit Pommes")

    canonicals = [item.canonical for item in analysis.items]

    assert canonicals[0] == "Fischstäbchen"
    assert "Pommes" in canonicals
    assert {"Alaska-Seelachs", "Paniermehl"}.issubset(set(canonicals))
    assert "Kartoffel" not in canonicals
    assert any(item.canonical == "Zitronensaft" for item in analysis.assumed_items)


@pytest.mark.parametrize("dish_name", ["Chicken Nuggets mit Pommes", "Nuggets mit Pommes"])
def test_nuggets_with_fries_use_intrinsic_nuggets_and_pommes(dish_name):
    analysis = normalize_dish(dish_name)

    canonicals = [item.canonical for item in analysis.items]

    assert canonicals[0] == "Chicken Nuggets"
    assert "Pommes" in canonicals
    assert {"Hähnchen", "Paniermehl"}.issubset(set(canonicals))
    assert "Kartoffel" not in canonicals
