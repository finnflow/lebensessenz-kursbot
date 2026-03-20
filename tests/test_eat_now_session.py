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
    assert session["focusDishKey"] == "dish_01"
    assert [dish["label"] for dish in session["dishMatrix"]] == [
        "Seetangsalat",
        "Miso Tofu Suppe",
        "Gebratene Nudeln",
    ]
    assert [dish["rank"] for dish in session["dishMatrix"]] == [1, 2, 3]
    assert [option["action"] for option in session["visibleOptions"]] == [
        "other_option",
        "more_trennkost",
        "waiter_phrase",
    ]

    active_state = database.get_active_menu_state(conversation_id)
    assert active_state["menu_state_id"] == session["menuStateId"]
    assert active_state["focus_dish_key"] == session["focusDishKey"]
    assert [dish["label"] for dish in active_state["dish_matrix"]] == [
        "Seetangsalat",
        "Miso Tofu Suppe",
        "Gebratene Nudeln",
    ]
    assert all("rank" not in dish for dish in active_state["dish_matrix"])


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
    assert active_state["menu_state_id"] == second_response["session"]["menuStateId"]
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
    assert response["answer"] == 'Eine weitere empfehlbare Option ist "Miso Tofu Suppe".'
    assert database.get_active_menu_state(conversation_id)["focus_dish_key"] == "dish_02"
    assert database.get_messages(conversation_id) == []


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
    assert first["answer"] == '"Seetangsalat" ist die trennkost-freundlichste Wahl auf der Karte.'
    assert second["session"]["focusDishKey"] == "dish_01"
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

    assert [option["action"] for option in single_recommendable_payload["visibleOptions"]] == [
        "more_trennkost",
        "waiter_phrase",
    ]
    assert [option["action"] for option in multiple_recommendable_payload["visibleOptions"]] == [
        "other_option",
        "more_trennkost",
        "waiter_phrase",
    ]


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
                    "visibleOptions": [
                        {"action": "other_option"},
                        {"action": "more_trennkost"},
                        {"action": "waiter_phrase"},
                    ],
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

    assert wrong_response.status_code == 400
    assert wrong_response.json()["error"]["code"] == "BAD_REQUEST"
    assert stale_response.status_code == 400
    assert stale_response.json()["error"]["code"] == "BAD_REQUEST"


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
