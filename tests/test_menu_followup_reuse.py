"""
PR6 tests: MENU_FOLLOWUP should reuse cached deterministic menu results.
"""
import pytest

import app.chat_service as chat_service
from app.chat_modes import ChatMode, ChatModifiers
from trennkost.models import TrafficLight, TrennkostResult, Verdict


@pytest.fixture(autouse=True)
def _clear_menu_cache():
    chat_service._LAST_MENU_RESULTS_BY_CONVERSATION.clear()
    yield
    chat_service._LAST_MENU_RESULTS_BY_CONVERSATION.clear()


def _make_result(dish_name: str, verdict: Verdict) -> TrennkostResult:
    return TrennkostResult(
        dish_name=dish_name,
        verdict=verdict,
        strict_verdict=verdict,
        active_mode_verdict=verdict,
        traffic_light=TrafficLight.GREEN,
        summary="Test",
    )


def _fake_finalize_response(
    conversation_id,
    normalized_message,
    vision_data,
    mode,
    modifiers,
    is_new,
    conv_data,
    image_path,
    trennkost_results=None,
    recipe_results=None,
    analysis_query=None,
    ui_intent=None,
):
    return {"conversationId": conversation_id, "results": trennkost_results}


def test_menu_followup_reuses_previous_menu_analysis_results(monkeypatch):
    conversation_id = "conv-menu-reuse"
    cached_results = [
        _make_result("Seetangsalat", Verdict.OK),
        _make_result("Miso Tofu Suppe", Verdict.CONDITIONAL),
    ]

    monkeypatch.setattr(chat_service, "_finalize_response", _fake_finalize_response)
    monkeypatch.setattr(chat_service, "_run_engine", lambda *_args, **_kwargs: cached_results)

    chat_service._handle_food_analysis(
        conversation_id=conversation_id,
        normalized_message="Was kann ich bestellen?",
        recent=[],
        vision_data={"vision_extraction": {"type": "menu"}},
        mode=ChatMode.MENU_ANALYSIS,
        modifiers=ChatModifiers(),
        is_new=False,
        conv_data={},
        image_path=None,
    )

    def _should_not_recompute(*_args, **_kwargs):
        raise AssertionError("MENU_FOLLOWUP should reuse cached menu results without recomputation")

    monkeypatch.setattr(chat_service, "_run_engine", _should_not_recompute)

    followup = chat_service._handle_food_analysis(
        conversation_id=conversation_id,
        normalized_message="Gib mir eine andere Option",
        recent=[],
        vision_data={},
        mode=ChatMode.MENU_FOLLOWUP,
        modifiers=ChatModifiers(),
        is_new=False,
        conv_data={},
        image_path=None,
    )

    reused_names = [r.dish_name for r in followup["results"]]
    assert reused_names == ["Seetangsalat", "Miso Tofu Suppe"]


def test_menu_followup_falls_back_safely_when_no_cached_menu_results(monkeypatch):
    conversation_id = "conv-menu-empty"
    calls = {"count": 0}

    def _run_engine_none(*_args, **_kwargs):
        calls["count"] += 1
        return None

    monkeypatch.setattr(chat_service, "_finalize_response", _fake_finalize_response)
    monkeypatch.setattr(chat_service, "_run_engine", _run_engine_none)

    followup = chat_service._handle_food_analysis(
        conversation_id=conversation_id,
        normalized_message="Was ist die zweitbeste Wahl?",
        recent=[],
        vision_data={},
        mode=ChatMode.MENU_FOLLOWUP,
        modifiers=ChatModifiers(),
        is_new=False,
        conv_data={},
        image_path=None,
    )

    assert calls["count"] == 1
    assert followup["results"] is None


def test_resolve_helper_reuses_cached_results_for_menu_followup(monkeypatch):
    conversation_id = "conv-helper"
    cached_results = [_make_result("Seetangsalat", Verdict.OK)]
    chat_service._LAST_MENU_RESULTS_BY_CONVERSATION[conversation_id] = cached_results

    def _should_not_recompute(*_args, **_kwargs):
        raise AssertionError("Cached follow-up should not call _run_engine")

    monkeypatch.setattr(chat_service, "_run_engine", _should_not_recompute)

    resolved = chat_service._resolve_trennkost_results(
        conversation_id=conversation_id,
        analysis_query="Gib mir eine weitere Option",
        mode=ChatMode.MENU_FOLLOWUP,
        vision_extraction=None,
    )

    assert [r.dish_name for r in resolved] == ["Seetangsalat"]
