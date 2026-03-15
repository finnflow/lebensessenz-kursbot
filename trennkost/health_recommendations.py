"""Health recommendation helpers that are separate from core rule definitions."""
from typing import List, Optional

from trennkost.models import FoodItem, RuleProblem, Severity


def _is_refined_sugar(item: FoodItem) -> bool:
    return bool(item.canonical and item.canonical.lower() == "zucker")


def build_h001_sugar_problem(all_items: List[FoodItem]) -> Optional[RuleProblem]:
    """Build optional H001 INFO recommendation for refined sugar items."""
    zucker_items = [item for item in all_items if _is_refined_sugar(item)]
    if not zucker_items:
        return None

    zucker_labels = [f"{item.raw_name} → Zucker" for item in zucker_items]
    return RuleProblem(
        rule_id="H001",  # H = Health recommendation (not Trennkost rule)
        description="Zucker (weißer Industriezucker) sollte vermieden werden",
        severity=Severity.INFO,
        affected_items=zucker_labels,
        affected_groups=["KH"],
        source_ref="modul-1.1,modul-1.2",
        explanation=(
            "Zucker ist zwar Trennkost-konform als Kohlenhydrat, wird aber im Kursmaterial als schädlich "
            "beschrieben. Besser: Honig, Ahornsirup oder Kokosblütenzucker verwenden."
        ),
    )


def build_health_recommendation_problems(all_items: List[FoodItem]) -> List[RuleProblem]:
    """Build non-verdict-changing health recommendation problems."""
    h001_problem = build_h001_sugar_problem(all_items)
    if h001_problem is None:
        return []
    return [h001_problem]
