from typing import Any, Dict, List, Optional, Tuple

from app.prompt_builder import rank_menu_results
from trennkost.ontology import get_ontology
from trennkost.models import TrennkostResult, Verdict


class EatNowSessionClientError(Exception):
    """Client-side request errors for the eat-now session flow."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


_RECOMMENDABLE_VERDICTS = {Verdict.OK.value, Verdict.CONDITIONAL.value}
_SELECTABLE_VERDICTS = {Verdict.OK.value}
_VISIBLE_OPTION_LABELS = {
    "other_option": "Etwas anderes",
    "more_trennkost": "Trennkost-näher",
    "waiter_phrase": "So dem Kellner sagen",
}
SESSION_STAGE_RECOMMENDATION_READY = "recommendation_ready"
SESSION_STAGE_DECISION_LOOP = "decision_loop"
SESSION_STAGE_COMPLETED = "completed"
_GUIDANCE_HINTS = {
    "CHECK_BINDERS": "Bei Bindemitteln oder Zusätzen kurz nachfragen.",
    "FAT_WITH_CONFLICT_GROUP_TINY_AMOUNT": "Fett dabei sehr klein halten.",
    "FAT_WITH_NEUTRAL_SMALL_AMOUNT": "Fett mit neutralen Lebensmitteln nur moderat einsetzen.",
    "GLUTEN_AWARE": "Gluten bewusst mitdenken.",
    "SMALL_AMOUNT_ONLY": "Davon nur kleine Mengen wählen.",
    "SOY_IN_MODERATION": "Soja eher in Maßen wählen.",
}


def _find_dish(dish_matrix: List[Dict[str, Any]], dish_key: str) -> Dict[str, Any]:
    for dish in dish_matrix:
        if dish["dishKey"] == dish_key:
            return dish
    raise ValueError(f"Dish key {dish_key} not found in dish matrix")


def _is_recommendable(dish: Dict[str, Any]) -> bool:
    return dish["verdict"] in _RECOMMENDABLE_VERDICTS


def _is_selectable(dish: Dict[str, Any]) -> bool:
    return dish["verdict"] in _SELECTABLE_VERDICTS


def _with_rank(dish: Dict[str, Any], rank_lookup: Dict[str, int]) -> Dict[str, Any]:
    return {
        **dish,
        "rank": rank_lookup[dish["dishKey"]],
    }


def _ranked_results_with_keys(
    trennkost_results: List[TrennkostResult],
) -> List[Tuple[str, TrennkostResult]]:
    ranked_results = rank_menu_results(trennkost_results)
    return [
        (f"dish_{index:02d}", result)
        for index, result in enumerate(ranked_results, start=1)
    ]


def build_menu_matrix(trennkost_results: List[TrennkostResult]) -> List[Dict[str, Any]]:
    """Build the minimal persisted menu matrix using the existing ranking logic."""
    dish_matrix: List[Dict[str, Any]] = []

    for dish_key, result in _ranked_results_with_keys(trennkost_results):
        dish_matrix.append(
            {
                "dishKey": dish_key,
                "label": result.dish_name,
                "verdict": result.verdict.value,
                "trafficLight": result.traffic_light.value,
                "hasOpenQuestion": bool(result.required_questions),
            }
        )

    return dish_matrix


def _clean_item_label(label: str) -> Tuple[str, str]:
    if " → " not in label:
        return label, label
    raw_name, canonical_name = label.split(" → ", 1)
    return raw_name.strip(), canonical_name.strip()


def _strip_summary_prefix(result: TrennkostResult) -> str:
    prefix = f"{result.dish_name}:"
    if result.summary.startswith(prefix):
        return result.summary[len(prefix):].strip()
    return result.summary.strip()


def _unique_non_empty(values: List[str]) -> List[str]:
    seen = set()
    lines: List[str] = []
    for value in values:
        candidate = value.strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        lines.append(candidate)
    return lines


def _format_wait_minutes(min_minutes: int, max_minutes: int) -> str:
    if min_minutes == max_minutes:
        if min_minutes % 60 == 0:
            hours = min_minutes // 60
            return f"{hours} Stunde" if hours == 1 else f"{hours} Stunden"
        return f"{min_minutes} Minuten"

    if min_minutes % 60 == 0 and max_minutes % 60 == 0:
        min_hours = min_minutes // 60
        max_hours = max_minutes // 60
        return f"{min_hours}-{max_hours} Stunden"
    return f"{min_minutes}-{max_minutes} Minuten"


def _build_why_lines(result: TrennkostResult) -> List[str]:
    why_lines = [_strip_summary_prefix(result), *result.ok_combinations]
    return _unique_non_empty(why_lines)


def _build_order_hints(result: TrennkostResult) -> List[str]:
    hints: List[str] = []
    for fact in result.guidance_facts:
        item_names = [raw_name for raw_name, _ in (_clean_item_label(item) for item in fact.affected_items)]
        item_prefix = f"{', '.join(item_names)}: " if item_names else ""
        base_hint = _GUIDANCE_HINTS.get(fact.code)

        if fact.code in {"FAT_WITH_CONFLICT_GROUP_TINY_AMOUNT", "FAT_WITH_NEUTRAL_SMALL_AMOUNT"} and fact.amount_hint:
            hints.append(f"{item_prefix}{base_hint} {fact.amount_hint}.")
            continue

        if fact.code == "CHECK_BINDERS":
            hints.append(base_hint)
            continue

        if base_hint:
            hints.append(f"{item_prefix}{base_hint}")
            continue

        if fact.amount_hint:
            hints.append(f"{item_prefix}{fact.amount_hint}.")

    return _unique_non_empty(hints)


def _build_after_meal_hints(result: TrennkostResult) -> List[str]:
    ontology = get_ontology()
    wait_hints: List[str] = []

    seen = set()
    grouped_items = result.strict_groups_found or result.groups_found
    for item_labels in grouped_items.values():
        for item_label in item_labels:
            raw_name, canonical_name = _clean_item_label(item_label)
            entry = ontology.lookup(canonical_name) or ontology.lookup(raw_name)
            if not entry or not entry.post_meal_wait_profile:
                continue

            profile = ontology.wait_profiles.get(entry.post_meal_wait_profile)
            if not profile:
                continue

            signature = (raw_name, profile.profile_id)
            if signature in seen:
                continue
            seen.add(signature)

            wait_hints.append(
                f"Nach {raw_name} bis zur nächsten Mahlzeit etwa {_format_wait_minutes(profile.min_minutes, profile.max_minutes)} warten."
            )

    return _unique_non_empty(wait_hints)


def build_dish_briefs(trennkost_results: List[TrennkostResult]) -> Dict[str, Dict[str, List[str]]]:
    """Build deterministic upfront dish briefs for selectable OK dishes only."""
    dish_briefs: Dict[str, Dict[str, List[str]]] = {}

    for dish_key, result in _ranked_results_with_keys(trennkost_results):
        if result.verdict.value not in _SELECTABLE_VERDICTS:
            continue

        dish_briefs[dish_key] = {
            "why": _build_why_lines(result),
            "orderHints": _build_order_hints(result),
            "afterMealHints": _build_after_meal_hints(result),
        }

    return dish_briefs


def pick_initial_focus_dish_key(dish_matrix: List[Dict[str, Any]]) -> str:
    """Pick the first recommendable option, otherwise the first dish."""
    if not dish_matrix:
        raise ValueError("dish_matrix cannot be empty")

    for dish in dish_matrix:
        if _is_recommendable(dish):
            return dish["dishKey"]

    return dish_matrix[0]["dishKey"]


def derive_selectable_dish_keys(dish_matrix: List[Dict[str, Any]]) -> List[str]:
    return [
        dish["dishKey"]
        for dish in dish_matrix
        if _is_selectable(dish)
    ]


def derive_visible_options(
    dish_matrix: List[Dict[str, Any]],
    focus_dish_key: str,
) -> List[Dict[str, Any]]:
    """Return the visible follow-up actions for the current eat-now focus."""
    _find_dish(dish_matrix, focus_dish_key)
    return [{"id": "waiter_phrase", "label": _VISIBLE_OPTION_LABELS["waiter_phrase"]}]


def build_session_payload(
    menu_state_id: str,
    focus_dish_key: str,
    dish_matrix: List[Dict[str, Any]],
    stage: str = SESSION_STAGE_RECOMMENDATION_READY,
    dish_briefs: Optional[Dict[str, Dict[str, List[str]]]] = None,
) -> Dict[str, Any]:
    """Build the API session payload, deriving rank from the matrix position only."""
    rank_lookup = {
        dish["dishKey"]: index
        for index, dish in enumerate(dish_matrix, start=1)
    }
    selectable_dish_keys = derive_selectable_dish_keys(dish_matrix)
    default_dish_key = selectable_dish_keys[0] if selectable_dish_keys else None
    persisted_briefs = dish_briefs or {}
    response_briefs = {
        dish_key: {
            "why": list(persisted_briefs.get(dish_key, {}).get("why", [])),
            "orderHints": list(persisted_briefs.get(dish_key, {}).get("orderHints", [])),
            "afterMealHints": list(persisted_briefs.get(dish_key, {}).get("afterMealHints", [])),
        }
        for dish_key in selectable_dish_keys
    }
    visible_options = (
        []
        if stage == SESSION_STAGE_COMPLETED
        else derive_visible_options(dish_matrix, focus_dish_key)
    )

    return {
        "type": "eat_now",
        "menuStateId": menu_state_id,
        "stage": stage,
        "focusDishKey": focus_dish_key,
        "defaultDishKey": default_dish_key,
        "selectableDishKeys": selectable_dish_keys,
        "selectableCount": len(selectable_dish_keys),
        "dishBriefs": response_briefs,
        "dishMatrix": [_with_rank(dish, rank_lookup) for dish in dish_matrix],
        "visibleOptions": visible_options,
    }


def stage_for_session_action(action: str) -> str:
    """Return the persisted stage for a supported eat-now session action."""
    if action == "select_dish":
        return SESSION_STAGE_DECISION_LOOP
    if action in {"other_option", "more_trennkost"}:
        return SESSION_STAGE_DECISION_LOOP
    if action == "waiter_phrase":
        return SESSION_STAGE_COMPLETED
    raise ValueError(f"Unsupported eat-now session action: {action}")


def apply_session_action(
    menu_state: Dict[str, Any],
    action: str,
    target_dish_key: Optional[str] = None,
) -> Tuple[str, str]:
    """Apply a deterministic eat-now session action to the active menu state."""
    dish_matrix = menu_state["dish_matrix"]
    focus_dish_key = menu_state.get("focus_dish_key") or pick_initial_focus_dish_key(dish_matrix)
    focus_dish = _find_dish(dish_matrix, focus_dish_key)
    recommendable = [dish for dish in dish_matrix if _is_recommendable(dish)]
    selectable_dish_keys = derive_selectable_dish_keys(dish_matrix)

    if action == "select_dish":
        if not target_dish_key:
            raise ValueError("targetDishKey is required for select_dish")
        _find_dish(dish_matrix, target_dish_key)
        if target_dish_key not in selectable_dish_keys:
            raise ValueError("targetDishKey must reference a selectable OK dish")
        return target_dish_key, ""

    if action == "other_option":
        if not recommendable:
            return focus_dish_key, f"\"{focus_dish['label']}\" bleibt die beste verfuegbare Option auf der Karte."

        recommendable_keys = [dish["dishKey"] for dish in recommendable]
        if focus_dish_key not in recommendable_keys:
            next_dish = recommendable[0]
            return next_dish["dishKey"], f"Eine bessere Option waere \"{next_dish['label']}\"."

        if len(recommendable_keys) == 1:
            return focus_dish_key, f"Es gibt aktuell keine weitere empfehlbare Option als \"{focus_dish['label']}\"."

        next_index = (recommendable_keys.index(focus_dish_key) + 1) % len(recommendable_keys)
        next_dish = recommendable[next_index]
        return next_dish["dishKey"], f"Eine weitere empfehlbare Option ist \"{next_dish['label']}\"."

    if action == "more_trennkost":
        if not recommendable:
            return focus_dish_key, f"\"{focus_dish['label']}\" bleibt die beste verfuegbare Option auf der Karte."

        best_dish = recommendable[0]
        if best_dish["dishKey"] == focus_dish_key:
            return focus_dish_key, f"\"{focus_dish['label']}\" bleibt die trennkost-freundlichste Wahl."

        return best_dish["dishKey"], f"\"{best_dish['label']}\" ist die trennkost-freundlichste Wahl auf der Karte."

    if action == "waiter_phrase":
        if focus_dish["hasOpenQuestion"]:
            return (
                focus_dish_key,
                f'Koennten Sie mir bitte kurz sagen, welche Zutaten genau in "{focus_dish["label"]}" sind und wie es zubereitet wird?',
            )
        return focus_dish_key, f'Ich nehme bitte "{focus_dish["label"]}".'

    raise ValueError(f"Unsupported eat-now session action: {action}")
