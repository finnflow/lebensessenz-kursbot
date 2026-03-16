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


def _normalized_key(name: str) -> str:
    return name.strip().lower()


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
    explicit_keys = {_normalized_key(item.raw_name) for item in items}

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

    boundary_candidates = assumed_items + uncertain_items
    deduped_assumed_items = []
    seen_assumed_keys = set()
    for item in boundary_candidates:
        key = _normalized_key(item.raw_name)
        if key in explicit_keys or key in seen_assumed_keys:
            continue
        if item.group == FoodGroup.UNKNOWN:
            continue
        seen_assumed_keys.add(key)
        deduped_assumed_items.append(item)

    analysis_assumed_items = [] if mode == "strict" else deduped_assumed_items

    unknown_items = []
    seen_unknown_keys = set()
    for item in items + boundary_candidates:
        if item.group != FoodGroup.UNKNOWN:
            continue
        key = _normalized_key(item.raw_name)
        if key in seen_unknown_keys:
            continue
        seen_unknown_keys.add(key)
        unknown_items.append(item.raw_name)

    for raw_name in resolved_input.unknown:
        key = _normalized_key(raw_name)
        if key in seen_unknown_keys:
            continue
        seen_unknown_keys.add(key)
        unknown_items.append(raw_name)

    return DishAnalysis(
        dish_name=resolved_input.dish_name,
        items=items,
        unknown_items=unknown_items,
        assumed_items=analysis_assumed_items,
    )
