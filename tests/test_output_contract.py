import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.prompt_builder import build_prompt_food_analysis, build_prompt_menu_overview
from trennkost.engine import TrennkostEngine
from trennkost.formatter import format_results_for_llm
from trennkost.normalizer import normalize_dish


@pytest.fixture(scope="module")
def engine():
    return TrennkostEngine()


def _result_for(engine: TrennkostEngine, raw_items: list[str]):
    analysis = normalize_dish(
        dish_name=" + ".join(raw_items),
        raw_items=raw_items,
    )
    return engine.evaluate(analysis, mode="light")


# ----------------------------
# Characterization tests
# ----------------------------

@pytest.mark.xfail(strict=False, reason="Characterization: current formatter wording may intentionally change")
def test_formatter_current_shape_today(engine):
    result = _result_for(engine, ["Pommes", "Mayonnaise"])
    rendered = format_results_for_llm([result])

    assert "Verdict:" in rendered
    assert "Zusammenfassung:" in rendered
    assert "strict_verdict" not in rendered
    assert "active_mode_verdict" not in rendered
    assert "mode_relaxation_applied" not in rendered


@pytest.mark.xfail(strict=False, reason="Characterization: current prompt wording may intentionally change")
def test_prompt_builder_current_bucket_language(engine):
    single = _result_for(engine, ["Pommes", "Mayonnaise"])
    menu = [
        _result_for(engine, ["Pommes"]),
        _result_for(engine, ["Pommes", "Schwein"]),
    ]

    food_prompt = build_prompt_food_analysis([single], "Ist Pommes mit Mayo ok?")
    menu_prompt = build_prompt_menu_overview(menu, "Was auf der Karte passt?")

    assert "BEDINGT OK" in food_prompt or "NICHT OK" in food_prompt or "OK" in food_prompt
    assert "Bedingt konforme Gerichte" in menu_prompt
    assert "Nicht konforme Gerichte" in menu_prompt


# ----------------------------
# Target contract tests
# ----------------------------

def test_engine_structured_fields_exist_before_rendering(engine):
    result = _result_for(engine, ["Banane", "Mandeln"])

    assert hasattr(result, "strict_verdict")
    assert hasattr(result, "active_mode_verdict")
    assert hasattr(result, "mode_relaxation_applied")
    assert hasattr(result, "traffic_light")
    assert hasattr(result, "risk_codes")
    assert hasattr(result, "guidance_codes")
    assert hasattr(result, "required_questions")


def test_formatter_accepts_results_with_required_questions(engine):
    result = _result_for(engine, ["Burger"])
    assert result.required_questions

    rendered = format_results_for_llm([result])

    assert isinstance(rendered, str) and rendered.strip()
    assert result.dish_name in rendered


def test_formatter_accepts_results_with_guidance(engine):
    result = _result_for(engine, ["Pommes", "Mayonnaise"])
    assert result.guidance_codes

    rendered = format_results_for_llm([result])

    assert isinstance(rendered, str) and rendered.strip()
    assert result.dish_name in rendered


def test_formatter_accepts_results_with_problems(engine):
    result = _result_for(engine, ["Pommes", "Schwein"])
    assert result.problems

    rendered = format_results_for_llm([result])

    assert isinstance(rendered, str) and rendered.strip()
    assert result.dish_name in rendered


def test_adapter_chain_accepts_results_with_traffic_light(engine):
    result = _result_for(engine, ["Pommes", "Mayonnaise"])
    assert result.traffic_light is not None

    rendered = format_results_for_llm([result])
    prompt = build_prompt_food_analysis([result], "Ist Pommes mit Mayo ok?")

    assert isinstance(rendered, str) and rendered.strip()
    assert isinstance(prompt, str) and prompt.strip()
    assert result.dish_name in rendered
    assert "USER'S ORIGINAL MESSAGE:" in prompt


def test_menu_prompt_handles_multiple_results_without_dropping_dishes(engine):
    results = [
        _result_for(engine, ["Pommes"]),
        _result_for(engine, ["Pommes", "Mayonnaise"]),
        _result_for(engine, ["Pommes", "Schwein"]),
    ]

    prompt = build_prompt_menu_overview(results, "Welche Gerichte sind gut?")

    assert isinstance(prompt, str) and prompt.strip()
    for result in results:
        assert result.dish_name in prompt
