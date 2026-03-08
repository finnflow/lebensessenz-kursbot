"""
Focused tests for compound backfill alignment with newer canonicals.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.models import ModifierTag
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
