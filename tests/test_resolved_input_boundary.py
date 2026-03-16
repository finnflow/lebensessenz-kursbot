import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.models import DishAnalysis
from trennkost.resolved_input import (
    ResolvedInput,
    adapt_resolved_input_to_dish_analysis,
    adapt_resolved_vision_input_to_dish_analysis,
    build_resolved_input,
    build_resolved_vision_input,
)


def test_build_resolved_input_text_populates_only_explicit():
    resolved = build_resolved_input(
        {
            "name": "Reis + Brokkoli",
            "items": ["Reis", "Brokkoli"],
        }
    )

    assert resolved.dish_name == "Reis + Brokkoli"
    assert resolved.explicit == ["Reis", "Brokkoli"]
    assert resolved.assumed == []
    assert resolved.uncertain == []
    assert resolved.unknown == []


def test_build_resolved_input_text_missing_items_yields_empty_lists():
    missing_items = build_resolved_input({"name": "Nur Name"})
    empty_items = build_resolved_input({"name": "Leere Liste", "items": []})

    for resolved in (missing_items, empty_items):
        assert resolved.explicit == []
        assert resolved.assumed == []
        assert resolved.uncertain == []
        assert resolved.unknown == []


def test_adapt_resolved_input_to_dish_analysis_returns_dishanalysis_and_uses_only_explicit():
    resolved = ResolvedInput(
        dish_name="Boundary Text",
        explicit=["Reis", "Brokkoli"],
        assumed=["Sahne"],
        uncertain=["Lachs"],
        unknown=["Manuell Unbekannt"],
    )

    analysis = adapt_resolved_input_to_dish_analysis(resolved)

    assert isinstance(analysis, DishAnalysis)
    assert [item.raw_name for item in analysis.items] == ["Reis", "Brokkoli"]
    assert analysis.assumed_items == []
    assert analysis.unknown_items == []


def test_build_resolved_vision_input_separates_explicit_and_uncertain():
    resolved = build_resolved_vision_input(
        {
            "name": "Vision Teller",
            "items": ["Reis", "Brokkoli"],
            "uncertain_items": ["Lachs"],
        }
    )

    assert resolved.dish_name == "Vision Teller"
    assert resolved.explicit == ["Reis", "Brokkoli"]
    assert resolved.uncertain == ["Lachs"]
    assert resolved.assumed == []
    assert resolved.unknown == []


def test_build_resolved_vision_input_defaults_name_to_mahlzeit():
    resolved = build_resolved_vision_input({"items": ["Reis"]})

    assert resolved.dish_name == "Mahlzeit"
    assert resolved.explicit == ["Reis"]
    assert resolved.uncertain == []


def test_adapt_resolved_vision_input_strict_keeps_assumed_and_uncertain_out_of_assumed_items():
    resolved = ResolvedInput(
        dish_name="Vision Strict",
        explicit=["Reis"],
        assumed=["Brokkoli"],
        uncertain=["Lachs"],
    )

    analysis = adapt_resolved_vision_input_to_dish_analysis(resolved, mode="strict")

    assert [item.raw_name for item in analysis.items] == ["Reis"]
    assert analysis.assumed_items == []


def test_adapt_resolved_vision_input_light_promotes_assumed_and_uncertain_to_assumed_items():
    resolved = ResolvedInput(
        dish_name="Vision Light",
        explicit=["Reis"],
        assumed=["Brokkoli"],
        uncertain=["Lachs"],
    )

    analysis = adapt_resolved_vision_input_to_dish_analysis(resolved, mode="light")

    assert [item.raw_name for item in analysis.items] == ["Reis"]
    assert [item.raw_name for item in analysis.assumed_items] == ["Brokkoli", "Lachs"]
    assert all(item.assumed for item in analysis.assumed_items)


def test_adapt_resolved_vision_input_collects_unknown_from_lookup_and_manual_unknown():
    resolved = ResolvedInput(
        dish_name="Vision Unknown",
        explicit=["Reis", "Grenzfallzutat Alpha"],
        unknown=["Manuell Unbekannt"],
    )

    analysis = adapt_resolved_vision_input_to_dish_analysis(resolved, mode="strict")

    assert "Grenzfallzutat Alpha" in analysis.unknown_items
    assert "Manuell Unbekannt" in analysis.unknown_items


def test_boundary_target_object_is_dishanalysis_for_text_and_vision():
    text_analysis = adapt_resolved_input_to_dish_analysis(
        ResolvedInput(dish_name="Text", explicit=["Reis"])
    )
    vision_analysis = adapt_resolved_vision_input_to_dish_analysis(
        ResolvedInput(dish_name="Vision", explicit=["Reis"]),
        mode="strict",
    )

    assert isinstance(text_analysis, DishAnalysis)
    assert isinstance(vision_analysis, DishAnalysis)


def test_unknown_and_uncertain_do_not_merge_semantically_in_vision_adapter():
    resolved = ResolvedInput(
        dish_name="Vision Semantics",
        explicit=["Reis"],
        uncertain=["Grenzfallzutat Beta"],
        unknown=["Manuell Unbekannt"],
    )

    analysis = adapt_resolved_vision_input_to_dish_analysis(resolved, mode="light")

    assert "Grenzfallzutat Beta" in analysis.unknown_items
    assert "Manuell Unbekannt" in analysis.unknown_items
    assert "Grenzfallzutat Beta" not in [item.raw_name for item in analysis.assumed_items]
    assert "Manuell Unbekannt" not in [item.raw_name for item in analysis.assumed_items]


def test_explicit_takes_precedence_over_duplicate_uncertain_entry():
    resolved = ResolvedInput(
        dish_name="Vision Duplicate",
        explicit=["Reis"],
        uncertain=["Reis"],
    )

    analysis = adapt_resolved_vision_input_to_dish_analysis(resolved, mode="light")
    all_raw_names = [item.raw_name for item in analysis.items + analysis.assumed_items]

    assert [item.raw_name for item in analysis.items] == ["Reis"]
    assert [item.raw_name for item in analysis.assumed_items] == []
    assert all_raw_names.count("Reis") == 1
