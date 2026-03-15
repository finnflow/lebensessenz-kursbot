"""
Minimal boundary model for resolved text input.

This layer stays internal to the analyzer boundary and adapts back into the
existing DishAnalysis engine contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from trennkost.models import DishAnalysis
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
