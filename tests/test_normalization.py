"""
Test suite for input normalization with follow-up protection.
"""
from types import SimpleNamespace

import pytest
import app.input_service as input_service
from app.chat_service import normalize_input


def _fake_response(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def _extract_current_message(prompt: str) -> str:
    return (
        prompt.split("**Aktuelle Nachricht:**", 1)[1]
        .split("**Normalisierte Nachricht:**", 1)[0]
        .strip()
    )


@pytest.fixture(autouse=True)
def stub_normalize_llm(monkeypatch):
    canned_responses = {
        "danm": "dann",
        "Ist Resi mit Hähnchen ok?": "Ist Reis mit Hähnchen ok?",
        "Is chicken with rice ok?": "Ist Hähnchen mit Reis ok?",
        "Kann ich chicken mit Reis essen?": "Kann ich Hähnchen mit Reis essen?",
        "Apfel 30 minuten vor Reis": "Apfel 30 min vor Reis",
        "Apfel eine halbe Stunde vor Reis": "Apfel 30 min vor Reis",
        "den Fisch": "den Fisch",
        "ok": "ok",
        "egal": "egal",
        "Was kann ich essen": "Was kann ich essen?",
    }

    def fake_create(*args, **kwargs):
        prompt = kwargs["messages"][0]["content"]
        current_message = _extract_current_message(prompt)
        return _fake_response(canned_responses.get(current_message, current_message))

    monkeypatch.setattr(input_service.client.chat.completions, "create", fake_create)


class TestTypoCorrection:
    """Test typo fixing without context."""

    def test_simple_typo(self):
        """danm → dann"""
        result = normalize_input("danm", [], is_new_conversation=True)
        assert "dann" in result.lower()

    def test_food_typo(self):
        """Resi → Reis"""
        result = normalize_input("Ist Resi mit Hähnchen ok?", [], is_new_conversation=True)
        assert "reis" in result.lower()


class TestLanguageTranslation:
    """Test translation to German."""

    def test_english_food(self):
        """chicken → Hähnchen"""
        result = normalize_input("Is chicken with rice ok?", [], is_new_conversation=True)
        assert "hähnchen" in result.lower() or "huhn" in result.lower()
        assert "reis" in result.lower()

    def test_mixed_language(self):
        """Mixed English/German → all German"""
        result = normalize_input("Kann ich chicken mit Reis essen?", [], is_new_conversation=True)
        assert "hähnchen" in result.lower() or "huhn" in result.lower()


class TestTimeFormatStandardization:
    """Test time format normalization."""

    def test_minutes_word(self):
        """30 minuten → 30 min"""
        result = normalize_input("Apfel 30 minuten vor Reis", [], is_new_conversation=True)
        assert "30 min" in result or "30min" in result

    def test_hour_conversion(self):
        """eine halbe Stunde → 30 min"""
        result = normalize_input("Apfel eine halbe Stunde vor Reis", [], is_new_conversation=True)
        # Should convert to minutes
        assert "min" in result.lower()


class TestFollowUpProtection:
    """Test that short follow-up messages are preserved, not expanded."""

    def test_short_followup_preserved(self):
        """'den Fisch' should stay as is when it's a follow-up"""
        recent_messages = [
            {"role": "assistant", "content": "Möchtest du den Fisch oder den Reis behalten?"},
            {"role": "user", "content": "Ich hatte Fisch mit Reis gegessen"}
        ]
        result = normalize_input("den Fisch", recent_messages, is_new_conversation=False)

        assert result == "den Fisch"
        assert len(result.split()) == 2
        assert not result.endswith("?")

    def test_ok_preserved(self):
        """'ok' should stay as is"""
        recent_messages = [
            {"role": "assistant", "content": "Soll ich dir ein Rezept vorschlagen?"},
        ]
        result = normalize_input("ok", recent_messages, is_new_conversation=False)

        assert result == "ok"

    def test_egal_preserved(self):
        """'egal' should stay as is"""
        recent_messages = [
            {"role": "assistant", "content": "Welche Kategorie bevorzugst du?"},
        ]
        result = normalize_input("egal", recent_messages, is_new_conversation=False)

        assert result == "egal"

    def test_standalone_expanded(self):
        """Standalone questions should be normalized/expanded"""
        # No context, new conversation
        result = normalize_input("Was kann ich essen", [], is_new_conversation=True)

        assert result == "Was kann ich essen?"
        assert len(result) < len("Was kann ich essen") * 3


class TestLongMessagesSkipped:
    """Test that long messages (>200 chars) skip normalization for performance."""

    def test_long_message_unchanged(self, monkeypatch):
        """Long messages should pass through unchanged"""
        monkeypatch.setattr(
            input_service.client.chat.completions,
            "create",
            lambda *args, **kwargs: pytest.fail("LLM should not be called for long inputs"),
        )
        long_msg = "A" * 250
        result = normalize_input(long_msg, [], is_new_conversation=True)
        assert result == long_msg


class TestSafetyChecks:
    """Test safety mechanisms to prevent over-expansion."""

    def test_3x_length_rejected(self, monkeypatch):
        """If normalized is >3x original length, use original"""
        monkeypatch.setattr(
            input_service.client.chat.completions,
            "create",
            lambda *args, **kwargs: _fake_response(
                "Kann ich den Fisch zusammen mit einer großen Beilage und mehreren anderen Sachen essen?"
            ),
        )
        short_msg = "Fisch"
        result = normalize_input(short_msg, [], is_new_conversation=True)

        assert result == short_msg


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
