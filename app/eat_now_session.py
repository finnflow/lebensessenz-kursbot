from typing import Any, Dict, List, Tuple

from app.prompt_builder import rank_menu_results
from trennkost.models import TrennkostResult, Verdict


class EatNowSessionClientError(Exception):
    """Client-side request errors for the eat-now session flow."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


_RECOMMENDABLE_VERDICTS = {Verdict.OK.value, Verdict.CONDITIONAL.value}
_VISIBLE_OPTION_LABELS = {
    "other_option": "Etwas anderes",
    "more_trennkost": "Trennkost-näher",
    "waiter_phrase": "So dem Kellner sagen",
}


def _find_dish(dish_matrix: List[Dict[str, Any]], dish_key: str) -> Dict[str, Any]:
    for dish in dish_matrix:
        if dish["dishKey"] == dish_key:
            return dish
    raise ValueError(f"Dish key {dish_key} not found in dish matrix")


def _is_recommendable(dish: Dict[str, Any]) -> bool:
    return dish["verdict"] in _RECOMMENDABLE_VERDICTS


def _with_rank(dish: Dict[str, Any], rank_lookup: Dict[str, int]) -> Dict[str, Any]:
    return {
        **dish,
        "rank": rank_lookup[dish["dishKey"]],
    }


def build_menu_matrix(trennkost_results: List[TrennkostResult]) -> List[Dict[str, Any]]:
    """Build the minimal persisted menu matrix using the existing ranking logic."""
    ranked_results = rank_menu_results(trennkost_results)
    dish_matrix: List[Dict[str, Any]] = []

    for index, result in enumerate(ranked_results, start=1):
        dish_matrix.append(
            {
                "dishKey": f"dish_{index:02d}",
                "label": result.dish_name,
                "verdict": result.verdict.value,
                "trafficLight": result.traffic_light.value,
                "hasOpenQuestion": bool(result.required_questions),
            }
        )

    return dish_matrix


def pick_initial_focus_dish_key(dish_matrix: List[Dict[str, Any]]) -> str:
    """Pick the first recommendable option, otherwise the first dish."""
    if not dish_matrix:
        raise ValueError("dish_matrix cannot be empty")

    for dish in dish_matrix:
        if _is_recommendable(dish):
            return dish["dishKey"]

    return dish_matrix[0]["dishKey"]


def derive_visible_options(
    dish_matrix: List[Dict[str, Any]],
    focus_dish_key: str,
) -> List[Dict[str, Any]]:
    """Return the visible follow-up actions for the current eat-now focus."""
    _find_dish(dish_matrix, focus_dish_key)

    visible_options = [
        {"id": "more_trennkost", "label": _VISIBLE_OPTION_LABELS["more_trennkost"]},
        {"id": "waiter_phrase", "label": _VISIBLE_OPTION_LABELS["waiter_phrase"]},
    ]

    has_other_recommendable = any(
        dish["dishKey"] != focus_dish_key and _is_recommendable(dish)
        for dish in dish_matrix
    )
    if has_other_recommendable:
        visible_options.insert(0, {"id": "other_option", "label": _VISIBLE_OPTION_LABELS["other_option"]})

    return visible_options


def build_session_payload(
    menu_state_id: str,
    focus_dish_key: str,
    dish_matrix: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build the API session payload, deriving rank from the matrix position only."""
    rank_lookup = {
        dish["dishKey"]: index
        for index, dish in enumerate(dish_matrix, start=1)
    }
    visible_options = derive_visible_options(dish_matrix, focus_dish_key)

    return {
        "type": "eat_now",
        "menuStateId": menu_state_id,
        "focusDishKey": focus_dish_key,
        "dishMatrix": [_with_rank(dish, rank_lookup) for dish in dish_matrix],
        "visibleOptions": visible_options,
    }


def apply_session_action(
    menu_state: Dict[str, Any],
    action: str,
) -> Tuple[str, str]:
    """Apply a deterministic eat-now session action to the active menu state."""
    dish_matrix = menu_state["dish_matrix"]
    focus_dish_key = menu_state.get("focus_dish_key") or pick_initial_focus_dish_key(dish_matrix)
    focus_dish = _find_dish(dish_matrix, focus_dish_key)
    recommendable = [dish for dish in dish_matrix if _is_recommendable(dish)]

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
