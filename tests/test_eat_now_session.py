import importlib.metadata
import sys
import types

import pytest
from fastapi.testclient import TestClient
import pydantic.networks as pydantic_networks

import app.chat_service as chat_service
import app.database as database
import app.migrations as migrations
from app.chat_modes import ChatMode, ChatModifiers, detect_chat_mode
from app.eat_now_session import apply_session_action, build_menu_matrix, build_session_payload
from trennkost.models import RequiredQuestion, TrafficLight, TrennkostResult, Verdict


if "email_validator" not in sys.modules:
    email_validator_stub = types.ModuleType("email_validator")

    class EmailNotValidError(ValueError):
        pass

    def validate_email(email, *args, **kwargs):
        return types.SimpleNamespace(email=email)

    email_validator_stub.EmailNotValidError = EmailNotValidError
    email_validator_stub.validate_email = validate_email
    sys.modules["email_validator"] = email_validator_stub

_real_version = importlib.metadata.version
pydantic_networks.version = lambda package: "2.0.0" if package == "email-validator" else _real_version(package)

import app.main as main


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch, tmp_path):
    db_path = tmp_path / "chat.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    monkeypatch.setattr(migrations, "DB_PATH", str(db_path))
    database.init_db()
    migrations.run_migrations()
    chat_service._LAST_MENU_RESULTS_BY_CONVERSATION.clear()
    yield
    chat_service._LAST_MENU_RESULTS_BY_CONVERSATION.clear()


def _make_result(
    dish_name: str,
    verdict: Verdict,
    traffic_light: TrafficLight,
    has_open_question: bool = False,
) -> TrennkostResult:
    questions = []
    if has_open_question:
        questions = [
            RequiredQuestion(
                question="Welche Zutaten sind genau enthalten?",
                reason="Unklare Zubereitung",
                affects_items=["Sauce"],
            )
        ]

    return TrennkostResult(
        dish_name=dish_name,
        verdict=verdict,
        strict_verdict=verdict,
        active_mode_verdict=verdict,
        traffic_light=traffic_light,
        summary="Test",
        required_questions=questions,
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
    return {
        "conversationId": conversation_id,
        "answer": "LLM_ANSWER",
        "sources": [],
    }


def _make_menu_matrix():
    return [
        _make_result("Gebratene Nudeln", Verdict.NOT_OK, TrafficLight.RED),
        _make_result("Miso Tofu Suppe", Verdict.CONDITIONAL, TrafficLight.YELLOW, has_open_question=True),
        _make_result("Seetangsalat", Verdict.OK, TrafficLight.GREEN),
    ]


def _visible_option(option_id: str, label: str):
    return {"id": option_id, "label": label}


def _assert_recommendation_ready_session(session):
    assert session["type"] == "eat_now"
    assert session["menuStateId"]
    assert session["stage"] == "recommendation_ready"
    assert session["focusDishKey"]
    assert session["dishMatrix"]
    assert session["visibleOptions"]


def _derive_primary_and_secondary(session):
    primary = next(
        dish for dish in session["dishMatrix"] if dish["dishKey"] == session["focusDishKey"]
    )
    secondary = next(
        (
            dish
            for dish in session["dishMatrix"]
            if dish["dishKey"] != session["focusDishKey"] and dish["verdict"] != "NOT_OK"
        ),
        None,
    )
    return primary, secondary


def test_menu_analysis_creates_session_and_persists_active_state(monkeypatch):
    conversation_id = database.create_conversation()
    results = _make_menu_matrix()

    monkeypatch.setattr(chat_service, "_resolve_trennkost_results", lambda **_kwargs: results)
    monkeypatch.setattr(chat_service, "_finalize_response", _fake_finalize_response)

    response = chat_service._handle_food_analysis(
        conversation_id=conversation_id,
        normalized_message="Was kann ich hier bestellen?",
        recent=[],
        vision_data={},
        mode=ChatMode.MENU_ANALYSIS,
        modifiers=ChatModifiers(),
        is_new=False,
        conv_data={},
        image_path=None,
    )

    session = response["session"]
    assert response["answer"] == "LLM_ANSWER"
    assert session["type"] == "eat_now"
    assert session["stage"] == "recommendation_ready"
    assert session["focusDishKey"] == "dish_01"
    assert [dish["label"] for dish in session["dishMatrix"]] == [
        "Seetangsalat",
        "Miso Tofu Suppe",
        "Gebratene Nudeln",
    ]
    assert [dish["rank"] for dish in session["dishMatrix"]] == [1, 2, 3]
    assert session["visibleOptions"] == [
        _visible_option("other_option", "Etwas anderes"),
        _visible_option("more_trennkost", "Trennkost-näher"),
        _visible_option("waiter_phrase", "So dem Kellner sagen"),
    ]

    active_state = database.get_active_menu_state(conversation_id)
    assert active_state["menu_state_id"] == session["menuStateId"]
    assert active_state["focus_dish_key"] == session["focusDishKey"]
    assert active_state["stage"] == "recommendation_ready"
    assert [dish["label"] for dish in active_state["dish_matrix"]] == [
        "Seetangsalat",
        "Miso Tofu Suppe",
        "Gebratene Nudeln",
    ]
    assert all("rank" not in dish for dish in active_state["dish_matrix"])


def test_handle_chat_returns_recommendation_ready_session_for_pasted_menu_text(monkeypatch):
    def _fake_resolve_trennkost_results(**kwargs):
        assert kwargs["mode"] == ChatMode.MENU_ANALYSIS
        return _make_menu_matrix()

    monkeypatch.setattr(chat_service, "normalize_input", lambda user_message, *_args: user_message)
    monkeypatch.setattr(chat_service, "classify_intent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(chat_service, "_resolve_trennkost_results", _fake_resolve_trennkost_results)
    monkeypatch.setattr(chat_service, "_finalize_response", _fake_finalize_response)

    response = chat_service.handle_chat(
        conversation_id=None,
        user_message=(
            "Mittagskarte\n"
            "1. Seetangsalat 5,90 EUR\n"
            "2. Miso Tofu Suppe 6,50 EUR\n"
            "3. Gebratene Nudeln 9,50 EUR"
        ),
        guest_id="guest-text",
    )

    session = response["session"]
    primary, secondary = _derive_primary_and_secondary(session)
    _assert_recommendation_ready_session(session)
    assert response["answer"] == "LLM_ANSWER"
    assert primary["label"] == "Seetangsalat"
    assert secondary["label"] == "Miso Tofu Suppe"

    active_state = database.get_active_menu_state(response["conversationId"])
    assert active_state["menu_state_id"] == session["menuStateId"]
    assert active_state["focus_dish_key"] == session["focusDishKey"]
    assert active_state["stage"] == "recommendation_ready"


def test_handle_chat_returns_session_for_slash_separated_menu_text_even_with_recipe_intent(monkeypatch):
    def _fake_resolve_trennkost_results(**kwargs):
        assert kwargs["mode"] == ChatMode.MENU_ANALYSIS
        assert kwargs["analysis_query"] == (
            "Gegrillter Lachs mit Brokkoli\n"
            "Spaghetti Bolognese\n"
            "Pommes"
        )
        return _make_menu_matrix()

    monkeypatch.setattr(chat_service, "normalize_input", lambda user_message, *_args: user_message)
    monkeypatch.setattr(
        chat_service,
        "classify_intent",
        lambda *_args, **_kwargs: {"intent": "recipe_from_ingredients", "confidence": "high"},
    )
    monkeypatch.setattr(chat_service, "_resolve_trennkost_results", _fake_resolve_trennkost_results)
    monkeypatch.setattr(chat_service, "_finalize_response", _fake_finalize_response)

    response = chat_service.handle_chat(
        conversation_id=None,
        user_message="Gegrillter Lachs mit Brokkoli / Spaghetti Bolognese / Pommes",
        guest_id="guest-slash",
        intent="eat",
    )

    session = response["session"]
    primary, secondary = _derive_primary_and_secondary(session)
    _assert_recommendation_ready_session(session)
    assert response["answer"] == "LLM_ANSWER"
    assert primary["label"] == "Seetangsalat"
    assert secondary["label"] == "Miso Tofu Suppe"


def test_handle_chat_returns_recommendation_ready_session_for_menu_image(monkeypatch):
    def _fake_process_vision(image_path, user_message):
        assert image_path == "/tmp/menu.jpg"
        assert user_message == ""
        return {
            "vision_analysis": None,
            "food_groups": None,
            "vision_extraction": {
                "type": "menu",
                "dishes": [{"name": "Seetangsalat", "items": ["Seetang"]}],
            },
            "vision_is_menu": True,
            "vision_failed": False,
        }

    def _fake_resolve_trennkost_results(**kwargs):
        assert kwargs["mode"] == ChatMode.MENU_ANALYSIS
        assert kwargs["vision_extraction"]["type"] == "menu"
        return _make_menu_matrix()

    monkeypatch.setattr(chat_service, "normalize_input", lambda user_message, *_args: user_message)
    monkeypatch.setattr(chat_service, "classify_intent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(chat_service, "_process_vision", _fake_process_vision)
    monkeypatch.setattr(chat_service, "_resolve_trennkost_results", _fake_resolve_trennkost_results)
    monkeypatch.setattr(chat_service, "_finalize_response", _fake_finalize_response)

    response = chat_service.handle_chat(
        conversation_id=None,
        user_message="",
        guest_id="guest-image",
        image_path="/tmp/menu.jpg",
        intent="eat",
    )

    session = response["session"]
    primary, secondary = _derive_primary_and_secondary(session)
    _assert_recommendation_ready_session(session)
    assert response["answer"] == "LLM_ANSWER"
    assert primary["label"] == "Seetangsalat"
    assert secondary["label"] == "Miso Tofu Suppe"

    active_state = database.get_active_menu_state(response["conversationId"])
    assert active_state["menu_state_id"] == session["menuStateId"]
    assert active_state["focus_dish_key"] == session["focusDishKey"]
    assert active_state["stage"] == "recommendation_ready"


def test_new_menu_analysis_replaces_previous_active_state(monkeypatch):
    conversation_id = database.create_conversation()

    monkeypatch.setattr(chat_service, "_finalize_response", _fake_finalize_response)
    monkeypatch.setattr(
        chat_service,
        "_resolve_trennkost_results",
        lambda **_kwargs: [
            _make_result("Seetangsalat", Verdict.OK, TrafficLight.GREEN),
            _make_result("Gebratene Nudeln", Verdict.NOT_OK, TrafficLight.RED),
        ],
    )
    first_response = chat_service._handle_food_analysis(
        conversation_id=conversation_id,
        normalized_message="Erste Karte",
        recent=[],
        vision_data={},
        mode=ChatMode.MENU_ANALYSIS,
        modifiers=ChatModifiers(),
        is_new=False,
        conv_data={},
        image_path=None,
    )

    monkeypatch.setattr(
        chat_service,
        "_resolve_trennkost_results",
        lambda **_kwargs: [
            _make_result("Sommerrolle", Verdict.OK, TrafficLight.GREEN),
            _make_result("Currysuppe", Verdict.CONDITIONAL, TrafficLight.YELLOW, has_open_question=True),
        ],
    )
    second_response = chat_service._handle_food_analysis(
        conversation_id=conversation_id,
        normalized_message="Neue Karte",
        recent=[],
        vision_data={},
        mode=ChatMode.MENU_ANALYSIS,
        modifiers=ChatModifiers(),
        is_new=False,
        conv_data={},
        image_path=None,
    )

    active_state = database.get_active_menu_state(conversation_id)
    assert second_response["session"]["menuStateId"] != first_response["session"]["menuStateId"]
    assert second_response["session"]["stage"] == "recommendation_ready"
    assert active_state["menu_state_id"] == second_response["session"]["menuStateId"]
    assert active_state["stage"] == "recommendation_ready"
    assert [dish["label"] for dish in active_state["dish_matrix"]] == [
        "Sommerrolle",
        "Currysuppe",
    ]


def test_other_option_switches_focus_correctly_without_persisting_empty_message():
    conversation_id = database.create_conversation()
    dish_matrix = chat_service.build_menu_matrix(_make_menu_matrix())
    database.save_active_menu_state(conversation_id, "menu_active", "dish_01", dish_matrix)

    response = chat_service.handle_chat(
        conversation_id=conversation_id,
        user_message="",
        session={
            "type": "eat_now",
            "menuStateId": "menu_active",
            "sessionAction": "other_option",
        },
    )

    assert response["session"]["focusDishKey"] == "dish_02"
    assert response["session"]["stage"] == "decision_loop"
    assert response["answer"] == 'Eine weitere empfehlbare Option ist "Miso Tofu Suppe".'
    assert database.get_active_menu_state(conversation_id)["focus_dish_key"] == "dish_02"
    assert database.get_active_menu_state(conversation_id)["stage"] == "decision_loop"
    messages = database.get_messages(conversation_id)
    assert len(messages) == 1
    assert messages[0]["role"] == "assistant"
    assert messages[0]["content"] == 'Eine weitere empfehlbare Option ist "Miso Tofu Suppe".'


def test_session_action_uses_summary_check_after_persisting_assistant_message(monkeypatch):
    conversation_id = database.create_conversation()
    dish_matrix = chat_service.build_menu_matrix(_make_menu_matrix())
    database.save_active_menu_state(conversation_id, "menu_active", "dish_01", dish_matrix)
    seen = {}

    def _should_update_summary(conv_id, conv_data):
        seen["should_conv_id"] = conv_id
        seen["message_count_at_check"] = len(database.get_messages(conv_id))
        return True

    def _update_summary(conv_id, conv_data):
        seen["update_conv_id"] = conv_id
        seen["message_count_at_update"] = len(database.get_messages(conv_id))

    monkeypatch.setattr(chat_service, "should_update_summary", _should_update_summary)
    monkeypatch.setattr(chat_service, "update_conversation_summary", _update_summary)

    response = chat_service.handle_chat(
        conversation_id=conversation_id,
        user_message="",
        session={
            "type": "eat_now",
            "menuStateId": "menu_active",
            "sessionAction": "waiter_phrase",
        },
    )

    assert response["answer"] == 'Ich nehme bitte "Seetangsalat".'
    assert response["session"]["stage"] == "completed"
    assert response["session"]["visibleOptions"] == []
    assert database.get_active_menu_state(conversation_id)["stage"] == "completed"
    assert seen == {
        "should_conv_id": conversation_id,
        "message_count_at_check": 1,
        "update_conv_id": conversation_id,
        "message_count_at_update": 1,
    }


def test_more_trennkost_jumps_to_best_option_then_confirms_current_focus():
    conversation_id = database.create_conversation()
    dish_matrix = chat_service.build_menu_matrix(_make_menu_matrix())
    database.save_active_menu_state(conversation_id, "menu_active", "dish_02", dish_matrix)

    first = chat_service.handle_chat(
        conversation_id=conversation_id,
        user_message="",
        session={
            "type": "eat_now",
            "menuStateId": "menu_active",
            "sessionAction": "more_trennkost",
        },
    )
    second = chat_service.handle_chat(
        conversation_id=conversation_id,
        user_message="",
        session={
            "type": "eat_now",
            "menuStateId": "menu_active",
            "sessionAction": "more_trennkost",
        },
    )

    assert first["session"]["focusDishKey"] == "dish_01"
    assert first["session"]["stage"] == "decision_loop"
    assert first["answer"] == '"Seetangsalat" ist die trennkost-freundlichste Wahl auf der Karte.'
    assert second["session"]["focusDishKey"] == "dish_01"
    assert second["session"]["stage"] == "decision_loop"
    assert second["answer"] == '"Seetangsalat" bleibt die trennkost-freundlichste Wahl.'


def test_waiter_phrase_is_deterministic():
    closed_focus_state = {
        "menu_state_id": "menu_closed",
        "focus_dish_key": "dish_01",
        "dish_matrix": chat_service.build_menu_matrix(
            [_make_result("Seetangsalat", Verdict.OK, TrafficLight.GREEN)]
        ),
    }
    open_focus_state = {
        "menu_state_id": "menu_open",
        "focus_dish_key": "dish_01",
        "dish_matrix": chat_service.build_menu_matrix(
            [_make_result("Miso Tofu Suppe", Verdict.CONDITIONAL, TrafficLight.YELLOW, has_open_question=True)]
        ),
    }

    assert apply_session_action(closed_focus_state, "waiter_phrase") == (
        "dish_01",
        'Ich nehme bitte "Seetangsalat".',
    )
    assert apply_session_action(open_focus_state, "waiter_phrase") == (
        "dish_01",
        'Koennten Sie mir bitte kurz sagen, welche Zutaten genau in "Miso Tofu Suppe" sind und wie es zubereitet wird?',
    )


def test_visible_options_only_expose_session_actions_with_correct_visibility():
    single_recommendable_payload = build_session_payload(
        "menu_one",
        "dish_01",
        build_menu_matrix(
            [
                _make_result("Seetangsalat", Verdict.OK, TrafficLight.GREEN),
                _make_result("Gebratene Nudeln", Verdict.NOT_OK, TrafficLight.RED),
            ]
        ),
    )
    multiple_recommendable_payload = build_session_payload(
        "menu_two",
        "dish_01",
        build_menu_matrix(
            [
                _make_result("Seetangsalat", Verdict.OK, TrafficLight.GREEN),
                _make_result("Miso Tofu Suppe", Verdict.CONDITIONAL, TrafficLight.YELLOW, has_open_question=True),
                _make_result("Gebratene Nudeln", Verdict.NOT_OK, TrafficLight.RED),
            ]
        ),
    )

    assert single_recommendable_payload["visibleOptions"] == [
        _visible_option("more_trennkost", "Trennkost-näher"),
        _visible_option("waiter_phrase", "So dem Kellner sagen"),
    ]
    assert single_recommendable_payload["stage"] == "recommendation_ready"
    assert multiple_recommendable_payload["visibleOptions"] == [
        _visible_option("other_option", "Etwas anderes"),
        _visible_option("more_trennkost", "Trennkost-näher"),
        _visible_option("waiter_phrase", "So dem Kellner sagen"),
    ]
    assert multiple_recommendable_payload["stage"] == "recommendation_ready"


def test_chat_endpoint_allows_empty_message_for_session_action(monkeypatch):
    seen = {}

    def _fake_handle_chat(conversation_id, user_message, guest_id=None, image_path=None, intent=None, session=None):
        seen.update(
            {
                "conversation_id": conversation_id,
                "user_message": user_message,
                "session": session,
            }
        )
        return {
            "conversationId": conversation_id or "conv-test",
            "answer": "Session answer",
            "sources": [],
                "session": {
                    "type": "eat_now",
                    "menuStateId": "menu_active",
                    "stage": "completed",
                    "focusDishKey": "dish_01",
                    "dishMatrix": [
                    {
                        "dishKey": "dish_01",
                        "label": "Seetangsalat",
                        "rank": 1,
                        "verdict": "OK",
                        "trafficLight": "GREEN",
                        "hasOpenQuestion": False,
                    }
                    ],
                    "visibleOptions": [],
                },
            }

    monkeypatch.setattr(main, "handle_chat", _fake_handle_chat)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/chat",
            json={
                "conversationId": "conv-test",
                "message": "",
                "session": {
                    "type": "eat_now",
                    "menuStateId": "menu_active",
                    "sessionAction": "waiter_phrase",
                },
            },
        )

    assert response.status_code == 200
    assert seen == {
        "conversation_id": "conv-test",
        "user_message": "",
        "session": {
            "type": "eat_now",
            "menuStateId": "menu_active",
            "sessionAction": "waiter_phrase",
        },
    }


def test_chat_image_endpoint_allows_empty_message_with_image_and_eat_intent(monkeypatch):
    seen = {}

    def _fake_save_image(file_content, filename):
        seen["saved_image"] = (filename, file_content)
        return "/tmp/menu.jpg"

    def _fake_handle_chat(conversation_id, user_message, guest_id=None, image_path=None, intent=None, session=None):
        seen["handle_chat"] = {
            "conversation_id": conversation_id,
            "user_message": user_message,
            "image_path": image_path,
            "intent": intent,
        }
        return {
            "conversationId": conversation_id or "conv-image",
            "answer": "Bild analysiert",
            "sources": [],
        }

    monkeypatch.setattr(main, "save_image", _fake_save_image)
    monkeypatch.setattr(main, "handle_chat", _fake_handle_chat)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/chat/image",
            data={"message": "", "intent": "eat"},
            files={"image": ("menu.jpg", b"fake-image", "image/jpeg")},
        )

    assert response.status_code == 200
    assert seen["saved_image"] == ("menu.jpg", b"fake-image")
    assert seen["handle_chat"] == {
        "conversation_id": None,
        "user_message": "",
        "image_path": "/tmp/menu.jpg",
        "intent": "eat",
    }


def test_missing_menu_state_id_returns_400_not_404():
    conversation_id = database.create_conversation()
    dish_matrix = chat_service.build_menu_matrix(_make_menu_matrix())
    database.save_active_menu_state(conversation_id, "menu_active", "dish_01", dish_matrix)

    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/chat",
            json={
                "conversationId": conversation_id,
                "message": "",
                "session": {
                    "type": "eat_now",
                    "sessionAction": "other_option",
                },
            },
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"


def test_missing_conversation_id_for_session_action_returns_400():
    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/chat",
            json={
                "message": "",
                "session": {
                    "type": "eat_now",
                    "menuStateId": "menu_active",
                    "sessionAction": "other_option",
                },
            },
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"


def test_no_active_session_returns_409_conflict():
    conversation_id = database.create_conversation()

    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/chat",
            json={
                "conversationId": conversation_id,
                "message": "",
                "session": {
                    "type": "eat_now",
                    "menuStateId": "menu_missing",
                    "sessionAction": "other_option",
                },
            },
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


def test_wrong_and_stale_menu_state_id_return_client_errors():
    conversation_id = database.create_conversation()
    first_matrix = chat_service.build_menu_matrix(_make_menu_matrix())
    database.save_active_menu_state(conversation_id, "menu_old", "dish_01", first_matrix)

    with TestClient(main.app) as client:
        wrong_response = client.post(
            "/api/v1/chat",
            json={
                "conversationId": conversation_id,
                "message": "",
                "session": {
                    "type": "eat_now",
                    "menuStateId": "menu_wrong",
                    "sessionAction": "other_option",
                },
            },
        )

        second_matrix = chat_service.build_menu_matrix(
            [
                _make_result("Sommerrolle", Verdict.OK, TrafficLight.GREEN),
                _make_result("Pho", Verdict.CONDITIONAL, TrafficLight.YELLOW, has_open_question=True),
            ]
        )
        database.save_active_menu_state(conversation_id, "menu_new", "dish_01", second_matrix)

        stale_response = client.post(
            "/api/v1/chat",
            json={
                "conversationId": conversation_id,
                "message": "",
                "session": {
                    "type": "eat_now",
                    "menuStateId": "menu_old",
                    "sessionAction": "other_option",
                },
            },
        )

    assert wrong_response.status_code == 409
    assert wrong_response.json()["error"]["code"] == "CONFLICT"
    assert stale_response.status_code == 409
    assert stale_response.json()["error"]["code"] == "CONFLICT"


def test_completed_session_rejects_further_actions_with_409():
    conversation_id = database.create_conversation()
    dish_matrix = chat_service.build_menu_matrix(_make_menu_matrix())
    database.save_active_menu_state(
        conversation_id,
        "menu_done",
        "dish_01",
        dish_matrix,
        stage="completed",
    )

    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/chat",
            json={
                "conversationId": conversation_id,
                "message": "",
                "session": {
                    "type": "eat_now",
                    "menuStateId": "menu_done",
                    "sessionAction": "other_option",
                },
            },
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


def test_conversation_load_returns_current_session_with_stage():
    conversation_id = database.create_conversation(guest_id="guest-load")
    dish_matrix = chat_service.build_menu_matrix(_make_menu_matrix())
    database.create_message(conversation_id, "assistant", "Bestehende Nachricht")
    database.save_active_menu_state(
        conversation_id,
        "menu_done",
        "dish_01",
        dish_matrix,
        stage="completed",
    )

    with TestClient(main.app) as client:
        response = client.get(
            f"/api/v1/conversations/{conversation_id}/messages",
            params={"guest_id": "guest-load"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][0]["content"] == "Bestehende Nachricht"
    assert payload["currentSession"]["menuStateId"] == "menu_done"
    assert payload["currentSession"]["stage"] == "completed"
    assert payload["currentSession"]["visibleOptions"] == []


def test_conversation_load_returns_null_current_session_when_absent():
    conversation_id = database.create_conversation(guest_id="guest-load")
    database.create_message(conversation_id, "assistant", "Bestehende Nachricht")

    with TestClient(main.app) as client:
        response = client.get(
            f"/api/v1/conversations/{conversation_id}/messages",
            params={"guest_id": "guest-load"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["messages"][0]["content"] == "Bestehende Nachricht"
    assert "currentSession" in payload
    assert payload["currentSession"] is None


def test_non_eat_now_responses_do_not_include_session_block(monkeypatch):
    monkeypatch.setattr(
        main,
        "handle_chat",
        lambda *_args, **_kwargs: {
            "conversationId": "conv-plain",
            "answer": "Normale Antwort",
            "sources": [],
        },
    )

    with TestClient(main.app) as client:
        response = client.post(
            "/api/v1/chat",
            json={
                "message": "Hallo",
            },
        )

    assert response.status_code == 200
    assert "session" not in response.json()


def test_detect_chat_mode_starts_menu_analysis_for_pasted_text_menu():
    mode, _ = detect_chat_mode(
        user_message=(
            "Mittagskarte\n"
            "1. Seetangsalat 5,90 EUR\n"
            "2. Miso Tofu Suppe 6,50 EUR\n"
            "3. Gebratene Nudeln 9,50 EUR"
        ),
        image_path=None,
        vision_type=None,
        is_new_conversation=True,
        recent_message_count=0,
        last_messages=[],
    )

    assert mode == ChatMode.MENU_ANALYSIS


def test_detect_chat_mode_starts_menu_analysis_for_slash_separated_menu_text():
    mode, _ = detect_chat_mode(
        user_message="Gegrillter Lachs mit Brokkoli / Spaghetti Bolognese / Pommes",
        image_path=None,
        vision_type=None,
        is_new_conversation=True,
        recent_message_count=0,
        last_messages=[],
    )

    assert mode == ChatMode.MENU_ANALYSIS


def test_detect_chat_mode_starts_menu_analysis_for_simple_multiline_menu_without_prices():
    mode, _ = detect_chat_mode(
        user_message=(
            "Gegrillter Lachs mit Brokkoli\n"
            "Spaghetti Bolognese\n"
            "Pommes"
        ),
        image_path=None,
        vision_type=None,
        is_new_conversation=True,
        recent_message_count=0,
        last_messages=[],
    )

    assert mode == ChatMode.MENU_ANALYSIS


@pytest.mark.parametrize(
    "user_message",
    [
        "Kann ich gegrillten Lachs mit Brokkoli essen?",
        "Spaghetti Bolognese",
    ],
)
def test_detect_chat_mode_keeps_single_dish_cases_out_of_menu_analysis(user_message):
    mode, _ = detect_chat_mode(
        user_message=user_message,
        image_path=None,
        vision_type=None,
        is_new_conversation=True,
        recent_message_count=0,
        last_messages=[],
    )

    assert mode != ChatMode.MENU_ANALYSIS
