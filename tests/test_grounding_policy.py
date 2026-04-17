"""Regression tests for centralized grounding/fallback policy."""
import app.chat_service as chat_service
from app.chat_modes import ChatMode, ChatModifiers
from app.grounding_policy import (
    FALLBACK_SENTENCE,
    GroundingDecision,
    REASON_NO_SNIPPETS,
    evaluate_grounding_policy,
)
from trennkost.models import TrennkostResult, Verdict


def _make_result() -> TrennkostResult:
    return TrennkostResult(
        dish_name="Testgericht",
        verdict=Verdict.OK,
        summary="Deterministisch OK",
    )


def test_policy_keeps_engine_results_out_of_fallback():
    decision = evaluate_grounding_policy(
        trennkost_results=[_make_result()],
        mode=ChatMode.KNOWLEDGE,
        best_dist=999.0,
        is_partial=False,
        course_context="",
        ui_intent=None,
        distance_threshold=1.0,
    )
    assert decision.should_fallback is False
    assert decision.reason_code is None


def test_policy_never_fallbacks_for_recipe_mode():
    decision = evaluate_grounding_policy(
        trennkost_results=None,
        mode=ChatMode.RECIPE_REQUEST,
        best_dist=999.0,
        is_partial=False,
        course_context="",
        ui_intent=None,
        distance_threshold=1.0,
    )
    assert decision.should_fallback is False
    assert decision.reason_code is None


def test_policy_fallbacks_for_bad_distance_without_partial():
    decision = evaluate_grounding_policy(
        trennkost_results=None,
        mode=ChatMode.KNOWLEDGE,
        best_dist=0.91,
        is_partial=False,
        course_context="Snippet",
        ui_intent=None,
        distance_threshold=0.9,
    )
    assert decision.should_fallback is True
    assert decision.reason_code == REASON_NO_SNIPPETS


def test_policy_fallbacks_for_empty_course_context():
    decision = evaluate_grounding_policy(
        trennkost_results=None,
        mode=ChatMode.KNOWLEDGE,
        best_dist=0.2,
        is_partial=True,
        course_context="   ",
        ui_intent=None,
        distance_threshold=0.9,
    )
    assert decision.should_fallback is True
    assert decision.reason_code == REASON_NO_SNIPPETS


def test_policy_keeps_need_and_plan_exception_for_no_snippets():
    for ui_intent in ("need", "plan"):
        decision = evaluate_grounding_policy(
            trennkost_results=None,
            mode=ChatMode.KNOWLEDGE,
            best_dist=0.91,
            is_partial=False,
            course_context="",
            ui_intent=ui_intent,
            distance_threshold=0.9,
        )
        assert decision.should_fallback is False
        assert decision.reason_code is None


def test_chat_service_uses_central_policy_for_early_fallback(monkeypatch):
    seen = {}
    saved_messages = []

    monkeypatch.setattr(chat_service, "get_last_n_messages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(chat_service, "_build_rag_query", lambda *_args, **_kwargs: "query")
    monkeypatch.setattr(chat_service, "retrieve_with_fallback", lambda *_args, **_kwargs: ([], [], [], False))
    monkeypatch.setattr(chat_service, "build_context", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        chat_service,
        "create_message",
        lambda _cid, _role, content, intent=None: saved_messages.append((content, intent)),
    )
    monkeypatch.setattr(chat_service, "get_conversation", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(chat_service, "should_update_summary", lambda *_args, **_kwargs: False)

    def _fake_policy(**kwargs):
        seen.update(kwargs)
        return GroundingDecision(should_fallback=True, reason_code=REASON_NO_SNIPPETS)

    monkeypatch.setattr(chat_service, "evaluate_grounding_policy", _fake_policy)

    result = chat_service._finalize_response(
        conversation_id="conv-grounding-fallback",
        normalized_message="Frage",
        vision_data={},
        mode=ChatMode.KNOWLEDGE,
        modifiers=ChatModifiers(),
        is_new=False,
        conv_data={},
        image_path=None,
        ui_intent="learn",
    )

    assert seen["ui_intent"] == "learn"
    assert result["answer"] == FALLBACK_SENTENCE
    assert saved_messages == [(FALLBACK_SENTENCE, "learn")]


def test_recipe_request_path_does_not_fallback_when_no_snippets(monkeypatch):
    saved_messages = []
    generated = {"called": False}

    monkeypatch.setattr(chat_service, "get_last_n_messages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(chat_service, "_build_rag_query", lambda *_args, **_kwargs: "query")
    monkeypatch.setattr(chat_service, "retrieve_with_fallback", lambda *_args, **_kwargs: ([], [], [], False))
    monkeypatch.setattr(chat_service, "build_context", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(
        chat_service,
        "create_message",
        lambda _cid, _role, content, intent=None: saved_messages.append((content, intent)),
    )
    monkeypatch.setattr(chat_service, "get_conversation", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(chat_service, "should_update_summary", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(chat_service, "_build_prompt_parts", lambda *_args, **_kwargs: (["ctx"], "instr"))
    monkeypatch.setattr(chat_service, "assemble_prompt", lambda *_args, **_kwargs: "llm-input")

    def _fake_generate_and_save(*_args, **_kwargs):
        generated["called"] = True
        return "RECIPE_OK"

    monkeypatch.setattr(chat_service, "_generate_and_save", _fake_generate_and_save)

    result = chat_service._finalize_response(
        conversation_id="conv-recipe-no-fallback",
        normalized_message="Rezeptfrage",
        vision_data={},
        mode=ChatMode.RECIPE_REQUEST,
        modifiers=ChatModifiers(),
        is_new=False,
        conv_data={},
        image_path=None,
        trennkost_results=None,
        recipe_results=[],
        ui_intent=None,
    )

    assert generated["called"] is True
    assert result["answer"] == "RECIPE_OK"
    assert saved_messages == []
