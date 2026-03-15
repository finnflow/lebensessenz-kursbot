"""Special deterministic protein rule helpers."""
from collections import defaultdict
from typing import Dict, List, Optional

from trennkost.models import CombinationGroup, EvaluationMode, FoodItem, RuleProblem, Severity
from trennkost.ontology import resolve_combination_group


def _format_item_label(item: FoodItem) -> str:
    if item.canonical and item.canonical != item.raw_name:
        return f"{item.raw_name} → {item.canonical}"
    return item.raw_name


def build_r018_mixed_protein_problem(
    all_items: List[FoodItem],
    mode: EvaluationMode,
) -> Optional[RuleProblem]:
    """
    Build optional R018 problem when multiple PROTEIN subgroups are combined.
    """
    subgroup_items: Dict[str, List[str]] = defaultdict(list)
    for item in all_items:
        if resolve_combination_group(item, mode=mode) == CombinationGroup.PROTEIN and item.subgroup:
            subgroup_items[item.subgroup.value].append(_format_item_label(item))

    if len(subgroup_items) < 2:
        return None

    affected_items: List[str] = []
    for subgroup in sorted(subgroup_items.keys()):
        for item in subgroup_items[subgroup]:
            affected_items.append(f"{item} ({subgroup})")

    return RuleProblem(
        rule_id="R018",
        description="Verschiedene Proteinquellen nicht kombinieren",
        severity=Severity.CRITICAL,
        affected_items=affected_items,
        affected_groups=["PROTEIN"],
        source_ref="modul-1.1/page-004,modul-1.1/page-001",
        explanation=(
            "Pro Mahlzeit sollte nur EINE Art von konzentriertem Lebensmittel gewählt werden. "
            "Fisch/Fleisch/Eier sind unterschiedliche Proteinquellen und sollten nicht miteinander kombiniert "
            "werden. Das Verdauungssystem ist nicht dafür geschaffen, mehr als ein konzentriertes Lebensmittel "
            "gleichzeitig zu verdauen."
        ),
    )
