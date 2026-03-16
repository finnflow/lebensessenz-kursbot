"""Targeted regression tests for context-reference preprocessing paths."""
import app.chat_service as chat_service
import app.input_service as input_service
from app.chat_modes import ChatMode
from app.input_service import resolve_context_references


def _install_food_extractor(monkeypatch, mapping):
    monkeypatch.setattr(
        input_service,
        "_extract_foods_ontology",
        lambda text: list(mapping.get(text, [])),
    )


def test_resolve_context_references_returns_none_without_reference_signal():
    recent_messages = [
        {"role": "assistant", "content": "Reis und Banane waren das letzte Gericht."},
    ]

    assert resolve_context_references("Kann ich Joghurt essen?", recent_messages) is None


def test_resolve_context_references_enriches_with_previous_food_context(monkeypatch):
    _install_food_extractor(
        monkeypatch,
        {
            "Kann ich dazu Joghurt essen?": ["Joghurt"],
            "Reis und Banane waren das letzte Gericht.": ["Reis", "Banane"],
        },
    )
    recent_messages = [
        {"role": "assistant", "content": "Reis und Banane waren das letzte Gericht."},
    ]

    result = resolve_context_references("Kann ich dazu Joghurt essen?", recent_messages)

    assert result == "Joghurt, Reis, Banane"


def test_resolve_context_references_returns_none_without_real_new_foods(monkeypatch):
    _install_food_extractor(
        monkeypatch,
        {
            "Kann ich dazu Joghurt mit Reis essen?": ["Joghurt", "Reis"],
            "Reis bleibt das Thema.": ["Reis"],
        },
    )
    recent_messages = [
        {"role": "assistant", "content": "Reis bleibt das Thema."},
    ]

    result = resolve_context_references("Kann ich dazu Joghurt mit Reis essen?", recent_messages)

    assert result is None


def test_resolve_context_references_uses_only_the_latest_relevant_food_context(monkeypatch):
    _install_food_extractor(
        monkeypatch,
        {
            "Kann ich dazu Joghurt essen?": ["Joghurt"],
            "Frueher ging es um Apfel.": ["Apfel"],
            "Nur eine Rueckfrage ohne Essen.": [],
            "Zuletzt ging es um Reis und Banane.": ["Reis", "Banane"],
        },
    )
    recent_messages = [
        {"role": "assistant", "content": "Frueher ging es um Apfel."},
        {"role": "assistant", "content": "Nur eine Rueckfrage ohne Essen."},
        {"role": "user", "content": "Zuletzt ging es um Reis und Banane."},
    ]

    result = resolve_context_references("Kann ich dazu Joghurt essen?", recent_messages)

    assert result == "Joghurt, Reis, Banane"


def test_resolve_context_references_preserves_deduplication(monkeypatch):
    _install_food_extractor(
        monkeypatch,
        {
            "Kann ich dazu Joghurt mit Reis essen?": ["Joghurt", "Reis"],
            "Reis und Banane passen zuletzt.": ["Reis", "Banane", "Banane"],
        },
    )
    recent_messages = [
        {"role": "assistant", "content": "Reis und Banane passen zuletzt."},
    ]

    result = resolve_context_references("Kann ich dazu Joghurt mit Reis essen?", recent_messages)

    assert result == "Joghurt, Reis, Banane"


def test_prepare_analysis_query_uses_context_resolution_for_food_analysis(monkeypatch):
    recent_messages = [{"role": "assistant", "content": "Reis"}]
    calls = []

    def fake_resolve(message, recent):
        calls.append((message, recent))
        return "Joghurt, Reis"

    monkeypatch.setattr(chat_service, "resolve_context_references", fake_resolve)

    result = chat_service._prepare_analysis_query(
        "Kann ich dazu Joghurt essen?",
        recent_messages,
        ChatMode.FOOD_ANALYSIS,
    )

    assert result == "Joghurt, Reis"
    assert calls == [("Kann ich dazu Joghurt essen?", recent_messages)]


def test_prepare_analysis_query_returns_normalized_message_for_other_modes(monkeypatch):
    monkeypatch.setattr(
        chat_service,
        "resolve_context_references",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("resolver should not be called")),
    )
    normalized_message = "normalisierte Nachricht"

    for mode in (
        ChatMode.KNOWLEDGE,
        ChatMode.MENU_ANALYSIS,
        ChatMode.MENU_FOLLOWUP,
        ChatMode.RECIPE_REQUEST,
        ChatMode.RECIPE_FROM_INGREDIENTS,
    ):
        assert chat_service._prepare_analysis_query(normalized_message, [], mode) == normalized_message
