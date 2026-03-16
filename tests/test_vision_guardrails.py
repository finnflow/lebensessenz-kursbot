"""Guardrails for legacy vision fallback behavior."""
import app.chat_service as chat_service
from app.chat_modes import ChatMode, ChatModifiers
from app.grounding_policy import GroundingDecision
from trennkost.models import TrafficLight, TrennkostResult, Verdict


def _make_result() -> TrennkostResult:
    return TrennkostResult(
        dish_name="Lachs mit Brokkoli",
        verdict=Verdict.OK,
        strict_verdict=Verdict.OK,
        active_mode_verdict=Verdict.OK,
        traffic_light=TrafficLight.GREEN,
        summary="Deterministisch OK",
    )


def _make_vision_data(*, vision_failed: bool = False) -> dict:
    return {
        "vision_analysis": {
            "summary": "Ein Teller mit Lachs und Brokkoli.",
            "items": [
                {"name": "Lachs", "category": "Proteine", "amount": "mittel"},
                {"name": "Brokkoli", "category": "Stärkearmes Gemüse", "amount": "mittel"},
            ],
        },
        "food_groups": {"proteins": ["Lachs"], "vegetables": ["Brokkoli"]},
        "vision_extraction": {"type": "meal", "dishes": [{"name": "Mahlzeit", "items": ["Lachs", "Brokkoli"]}]},
        "vision_is_menu": True,
        "vision_failed": vision_failed,
    }


def test_guardrail_strips_legacy_vision_semantics_when_engine_results_exist():
    vision_data = _make_vision_data(vision_failed=True)

    guarded = chat_service._apply_legacy_vision_guardrail(vision_data, [_make_result()])

    assert guarded["vision_analysis"] is None
    assert guarded["food_groups"] is None
    assert guarded["vision_extraction"] == vision_data["vision_extraction"]
    assert guarded["vision_is_menu"] is True
    assert guarded["vision_failed"] is True
    assert vision_data["vision_analysis"] is not None
    assert vision_data["food_groups"] is not None


def test_guardrail_keeps_legacy_vision_fallback_without_engine_results():
    vision_data = _make_vision_data(vision_failed=True)

    guarded = chat_service._apply_legacy_vision_guardrail(vision_data, None)

    assert guarded == vision_data


def test_prompt_parts_keep_legacy_vision_fallback_without_engine_results():
    parts, answer_instructions = chat_service._build_prompt_parts(
        mode=ChatMode.FOOD_ANALYSIS,
        modifiers=ChatModifiers(),
        trennkost_results=None,
        vision_data=_make_vision_data(),
        summary=None,
        last_messages=[],
        user_message="Ist das ok?",
    )

    joined_parts = "\n".join(parts)
    assert "BILD-ANALYSE (Mahlzeit):" in joined_parts
    assert answer_instructions == chat_service.build_prompt_vision_legacy("Ist das ok?")


def test_prompt_parts_keep_vision_failed_fallback_without_engine_results():
    parts, answer_instructions = chat_service._build_prompt_parts(
        mode=ChatMode.FOOD_ANALYSIS,
        modifiers=ChatModifiers(),
        trennkost_results=None,
        vision_data=_make_vision_data(vision_failed=True),
        summary=None,
        last_messages=[],
        user_message="Ist das ok?",
    )

    joined_parts = "\n".join(parts)
    assert "BILD-ANALYSE FEHLGESCHLAGEN:" in joined_parts
    assert "BILD-ANALYSE (Mahlzeit):" not in joined_parts
    assert answer_instructions == chat_service.build_prompt_knowledge("Ist das ok?", False)


def test_finalize_response_uses_guarded_vision_data_downstream_when_engine_results_exist(monkeypatch):
    seen = {}

    def _capture_rag_query(trennkost_results, food_groups, image_path, summary, last_messages, user_message, is_breakfast):
        seen["food_groups"] = food_groups
        return "query"

    def _capture_prompt_parts(mode, modifiers, trennkost_results, vision_data, summary, last_messages, user_message, recipe_results=None, ui_intent=None):
        seen["vision_data"] = vision_data
        return (["ctx"], "instr")

    monkeypatch.setattr(chat_service, "get_last_n_messages", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(chat_service, "_build_rag_query", _capture_rag_query)
    monkeypatch.setattr(chat_service, "retrieve_with_fallback", lambda *_args, **_kwargs: (["doc"], [{"path": "p"}], [0.1], False))
    monkeypatch.setattr(chat_service, "build_context", lambda *_args, **_kwargs: "ctx")
    monkeypatch.setattr(
        chat_service,
        "evaluate_grounding_policy",
        lambda **_kwargs: GroundingDecision(should_fallback=False, reason_code=None),
    )
    monkeypatch.setattr(chat_service, "_build_prompt_parts", _capture_prompt_parts)
    monkeypatch.setattr(chat_service, "assemble_prompt", lambda *_args, **_kwargs: "llm-input")
    monkeypatch.setattr(chat_service, "_generate_and_save", lambda *_args, **_kwargs: "OK")
    monkeypatch.setattr(chat_service, "get_conversation", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(chat_service, "should_update_summary", lambda *_args, **_kwargs: False)

    result = chat_service._finalize_response(
        conversation_id="conv-vision-guardrail",
        normalized_message="Ist das ok?",
        vision_data=_make_vision_data(vision_failed=True),
        mode=ChatMode.FOOD_ANALYSIS,
        modifiers=ChatModifiers(),
        is_new=False,
        conv_data={},
        image_path="/tmp/test-image.jpg",
        trennkost_results=[_make_result()],
        ui_intent=None,
    )

    assert seen["food_groups"] is None
    assert seen["vision_data"]["vision_analysis"] is None
    assert seen["vision_data"]["food_groups"] is None
    assert seen["vision_data"]["vision_extraction"]["type"] == "meal"
    assert seen["vision_data"]["vision_is_menu"] is True
    assert seen["vision_data"]["vision_failed"] is True
    assert result["answer"] == "OK"
