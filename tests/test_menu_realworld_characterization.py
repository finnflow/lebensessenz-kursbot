import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.eat_now_session import apply_session_action, build_menu_matrix, pick_initial_focus_dish_key
from trennkost.analyzer import analyze_text


REALWORLD_MENU_TEXT = """1. Reis mit Brokkoli
2. Grüner Smoothie
3. Pommes
4. Spaghetti Bolognese
"""


def test_realworld_menu_analysis_keeps_all_dishes_without_drops_or_inventions():
    results = analyze_text(
        REALWORLD_MENU_TEXT,
        llm_fn=None,
        mode="strict",
        evaluation_mode="strict",
    )

    assert [result.dish_name for result in results] == [
        "Reis + Brokkoli",
        "Grüner Smoothie",
        "Pommes",
        "Spaghetti Bolognese",
    ]


def test_realworld_menu_followup_other_option_returns_second_best_existing_dish():
    results = analyze_text(
        REALWORLD_MENU_TEXT,
        llm_fn=None,
        mode="strict",
        evaluation_mode="strict",
    )
    dish_matrix = build_menu_matrix(results)
    focus_dish_key = pick_initial_focus_dish_key(dish_matrix)
    result_names = {result.dish_name for result in results}

    assert dish_matrix[0]["label"] == "Reis + Brokkoli"
    assert focus_dish_key == dish_matrix[0]["dishKey"]

    next_focus_key, message = apply_session_action(
        {"dish_matrix": dish_matrix, "focus_dish_key": focus_dish_key},
        "other_option",
    )

    assert next_focus_key == dish_matrix[1]["dishKey"]
    assert dish_matrix[1]["label"] == "Grüner Smoothie"
    assert message == 'Eine weitere empfehlbare Option ist "Grüner Smoothie".'
    assert {dish["label"] for dish in dish_matrix} == result_names
