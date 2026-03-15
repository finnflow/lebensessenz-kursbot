"""
Minimal boundary model for resolved text input.

This layer stays internal to the analyzer boundary and adapts back into the
existing DishAnalysis engine contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from trennkost.models import DishAnalysis, FoodGroup
from trennkost.ontology import get_ontology
from trennkost.normalizer import normalize_dish


@dataclass(frozen=True)
class ResolvedInput:
    """Internal boundary model between raw parsing and DishAnalysis."""

    dish_name: str
    explicit: List[str] = field(default_factory=list)
    assumed: List[str] = field(default_factory=list)
    uncertain: List[str] = field(default_factory=list)
    unknown: List[str] = field(default_factory=list)


def build_resolved_input(parsed_dish: Dict[str, Any]) -> ResolvedInput:
    """
    Lift the existing text parser output into the internal boundary model.

    For this first step, the text path populates only explicit ingredients.
    """
    raw_items = parsed_dish.get("items")
    explicit = list(raw_items) if raw_items else []
    return ResolvedInput(
        dish_name=parsed_dish["name"],
        explicit=explicit,
    )


def build_resolved_vision_input(vision_dish: Dict[str, Any]) -> ResolvedInput:
    """
    Lift the existing vision extraction output into the internal boundary model.

    Vision keeps explicit and uncertain ingredients separate at the boundary.
    """
    return ResolvedInput(
        dish_name=vision_dish.get("name", "Mahlzeit"),
        explicit=list(vision_dish.get("items") or []),
        uncertain=list(vision_dish.get("uncertain_items") or []),
    )


def adapt_resolved_input_to_dish_analysis(
    resolved_input: ResolvedInput,
    llm_fn: Optional[Callable] = None,
) -> DishAnalysis:
    """Adapt the boundary model back to the existing engine-facing contract."""
    return normalize_dish(
        dish_name=resolved_input.dish_name,
        raw_items=resolved_input.explicit or None,
        llm_fn=llm_fn,
    )


def adapt_resolved_vision_input_to_dish_analysis(
    resolved_input: ResolvedInput,
    mode: str = "strict",
) -> DishAnalysis:
    """
    Adapt vision boundary data back into DishAnalysis while preserving
    the existing vision-path semantics.
    """
    ontology = get_ontology()
    items = [ontology.lookup_to_food_item(name) for name in resolved_input.explicit]
    assumed_items = [
        ontology.lookup_to_food_item(
            name,
            assumed=True,
            assumption_reason="Auf dem Bild nicht sicher erkennbar",
        )
        for name in resolved_input.assumed
    ]
    uncertain_items = [
        ontology.lookup_to_food_item(
            name,
            assumed=True,
            assumption_reason="Auf dem Bild nicht sicher erkennbar",
        )
        for name in resolved_input.uncertain
    ]

    analysis_assumed_items = [] if mode == "strict" else assumed_items + uncertain_items
    unknown_items = [
        item.raw_name
        for item in items + assumed_items + uncertain_items
        if item.group == FoodGroup.UNKNOWN
    ]
    unknown_items.extend(resolved_input.unknown)

    return DishAnalysis(
        dish_name=resolved_input.dish_name,
        items=items,
        unknown_items=unknown_items,
        assumed_items=analysis_assumed_items,
    )
