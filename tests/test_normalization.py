"""
Test suite for input normalization with follow-up protection.
"""
import pytest
from app.chat_service import normalize_input


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

        # Should NOT be expanded to full sentence
        # Should be short, just the food choice
        assert len(result.split()) <= 5, f"Follow-up was over-expanded: '{result}'"
        assert "fisch" in result.lower()

    def test_ok_preserved(self):
        """'ok' should stay as is"""
        recent_messages = [
            {"role": "assistant", "content": "Soll ich dir ein Rezept vorschlagen?"},
        ]
        result = normalize_input("ok", recent_messages, is_new_conversation=False)

        # Should stay short
        assert len(result) < 10, f"'ok' was over-expanded: '{result}'"

    def test_egal_preserved(self):
        """'egal' should stay as is"""
        recent_messages = [
            {"role": "assistant", "content": "Welche Kategorie bevorzugst du?"},
        ]
        result = normalize_input("egal", recent_messages, is_new_conversation=False)

        # Should stay short
        assert len(result) < 15, f"'egal' was over-expanded: '{result}'"

    def test_standalone_expanded(self):
        """Standalone questions should be normalized/expanded"""
        # No context, new conversation
        result = normalize_input("Was kann ich essen", [], is_new_conversation=True)

        # Should be normalized but not over-expanded (no 3x length increase)
        assert len(result) > 0
        # Should still be reasonable
        assert len(result) < len("Was kann ich essen") * 3


class TestLongMessagesSkipped:
    """Test that long messages (>200 chars) skip normalization for performance."""

    def test_long_message_unchanged(self):
        """Long messages should pass through unchanged"""
        long_msg = "A" * 250
        result = normalize_input(long_msg, [], is_new_conversation=True)
        assert result == long_msg


class TestSafetyChecks:
    """Test safety mechanisms to prevent over-expansion."""

    def test_3x_length_rejected(self):
        """If normalized is >3x original length, use original"""
        # This test is hard to trigger, but the function should handle it
        # If normalization somehow produces very long output, it should reject it
        short_msg = "Fisch"
        result = normalize_input(short_msg, [], is_new_conversation=True)

        # Result should not be wildly longer than input
        assert len(result) < len(short_msg) * 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
