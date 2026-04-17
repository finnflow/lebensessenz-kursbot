"""
Focused tests for centralized modifier interpretation.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.analyzer import analyze_text
from trennkost.engine import TrennkostEngine
from trennkost.models import ModifierTag, Verdict
from trennkost.normalizer import normalize_dish


@pytest.fixture(scope="module")
def engine():
    return TrennkostEngine()


def test_schnitzel_natur_and_breaded_normalize_differently():
    natur = normalize_dish("Test", raw_items=["Schnitzel natur"])
    breaded = normalize_dish("Test", raw_items=["paniertes Schnitzel"])

    assert natur.items[0].canonical == "Schwein"
    assert natur.items[0].recognized_modifiers == [ModifierTag.PREP_NATUR]

    assert breaded.items[0].canonical == "Paniertes Schnitzel"
    assert breaded.items[0].recognized_modifiers == [ModifierTag.PREP_BREADED]
    assert breaded.items[0].canonical != natur.items[0].canonical


def test_breaded_schnitzel_connects_to_intrinsic_conflict_path(engine):
    analysis = normalize_dish("Test", raw_items=["paniertes Schnitzel"])
    result = engine.evaluate(analysis)

    canonicals = [item.canonical for item in analysis.items]
    assert canonicals[0] == "Paniertes Schnitzel"
    assert {"Schwein", "Paniermehl", "Ei"}.issubset(set(canonicals))
    assert analysis.items[0].intrinsic_conflict_code == "BREADED_PROTEIN_CONFLICT"
    assert analysis.items[0].decompose_for_logic is True
    assert result.verdict == Verdict.NOT_OK


def test_vegan_burger_variant_stays_explicitly_uncertain():
    analysis = normalize_dish("veganer Burger")

    assert {item.canonical for item in analysis.items} == {"Brot", "Veganes Patty"}
    variant = next(item for item in analysis.items if item.canonical == "Veganes Patty")
    assert variant.group.value == "UNKNOWN"
    assert variant.risk_codes == ["UNKNOWN_BINDERS"]
    assert variant.guidance_codes == ["CHECK_BINDERS"]
    assert variant.recognized_modifiers == [ModifierTag.VEGAN]
    assert analysis.unknown_items == ["Veganes Patty"]


def test_classic_burger_does_not_fake_a_specific_patty_variant():
    analysis = normalize_dish("Test", raw_items=["normaler Burger"])

    assert len(analysis.items) == 1
    assert analysis.items[0].raw_name == "normaler Burger"
    assert analysis.items[0].canonical is None
    assert analysis.items[0].group.value == "UNKNOWN"
    assert analysis.unknown_items == ["normaler Burger"]


@pytest.mark.parametrize(
    ("dish_name", "expected_variant", "expected_tag", "expected_unknowns"),
    [
        ("klassischer Hotdog", "Wurst", ModifierTag.HINT_CLASSIC, []),
        ("vegetarischer Hotdog", "Vegetarische Wurst", ModifierTag.VEGETARIAN, ["Vegetarische Wurst"]),
        ("veganer Hotdog", "Vegane Wurst", ModifierTag.VEGAN, ["Vegane Wurst"]),
    ],
)
def test_hotdog_variant_cues_are_handled_in_a_controlled_way(
    dish_name,
    expected_variant,
    expected_tag,
    expected_unknowns,
):
    analysis = normalize_dish(dish_name)

    assert {item.canonical for item in analysis.items} == {"Brot", expected_variant}
    variant = next(item for item in analysis.items if item.canonical == expected_variant)
    assert variant.recognized_modifiers == [expected_tag]
    assert analysis.unknown_items == expected_unknowns


@pytest.mark.parametrize(
    ("dish_name", "expected_variant", "expected_tag", "expected_unknowns"),
    [
        ("klassischer Hotdog mit Pommes", "Wurst", ModifierTag.HINT_CLASSIC, []),
        ("vegetarischer Hotdog mit Pommes", "Vegetarische Wurst", ModifierTag.VEGETARIAN, ["Vegetarische Wurst"]),
        ("veganer Hotdog mit Pommes", "Vegane Wurst", ModifierTag.VEGAN, ["Vegane Wurst"]),
    ],
)
def test_hotdog_with_fries_keeps_variant_resolution_and_explicit_side(
    dish_name,
    expected_variant,
    expected_tag,
    expected_unknowns,
):
    analysis = normalize_dish(dish_name)

    assert {item.canonical for item in analysis.items} == {"Brot", expected_variant, "Pommes"}
    variant = next(item for item in analysis.items if item.canonical == expected_variant)
    assert variant.recognized_modifiers == [expected_tag]
    assert analysis.unknown_items == expected_unknowns


def test_generic_veggie_patty_does_not_become_fake_certainty():
    analysis = normalize_dish("Test", raw_items=["veggie patty"])

    assert len(analysis.items) == 1
    item = analysis.items[0]
    assert item.raw_name == "veggie patty"
    assert item.canonical == "Vegetarisches Patty"
    assert item.group.value == "UNKNOWN"
    assert item.recognized_modifiers == [ModifierTag.VEGETARIAN]
    assert analysis.unknown_items == ["veggie patty"]


def test_preparation_modifier_is_structurally_recognized():
    analysis = normalize_dish("Test", raw_items=["frittiertes Hähnchen"])

    assert len(analysis.items) == 1
    assert analysis.items[0].canonical == "Hähnchen"
    assert analysis.items[0].recognized_modifiers == [ModifierTag.PREP_FRIED]


def test_gebraten_does_not_trigger_fried_risk_code():
    analysis = normalize_dish("Test", raw_items=["gebratenes Hähnchen"])
    assert analysis.items[0].canonical == "Hähnchen"
    assert ModifierTag.PREP_FRIED in analysis.items[0].recognized_modifiers
    # PREP_FRIED als Modifier ist korrekt — aber kein FRIED-Risikocode
    # (gebraten ≠ frittiert, kein R_FRIED-Verdikt)
    from trennkost.engine import build_r_fried_problem
    result = build_r_fried_problem(analysis.items)
    assert result is None


def test_analyzer_keeps_modifier_aware_burger_question_on_uncertain_path():
    result = analyze_text("Ist ein veganer Burger ok?")[0]

    assert result.dish_name == "veganer Burger"
    assert result.verdict == Verdict.CONDITIONAL
    assert result.debug["unknown_items"] == ["Veganes Patty"]
