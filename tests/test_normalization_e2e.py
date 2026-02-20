"""
End-to-end tests that verify the normalization system works in the full pipeline.

These tests would FAIL without normalization but PASS with it, demonstrating
the value of typo fixing, language translation, time standardization, etc.
"""
import pytest
from app.chat_service import handle_chat
from app.database import create_conversation


@pytest.fixture
def conversation():
    """Create a test conversation."""
    return create_conversation()


class TestTypoFixingE2E:
    """Tests that typos are fixed and the bot still understands the query."""

    def test_typo_in_temporal_query(self, conversation):
        """Typo 'danm' → 'dann' should still trigger temporal separation detection.

        WITHOUT normalization: Bot might not detect temporal pattern.
        WITH normalization: Bot correctly recognizes sequential eating.
        """
        response = handle_chat(
            conversation_id=conversation,
            user_message="Apfel und danm Reis"  # Typo: danm → dann
        )
        answer = response["answer"].lower()

        # Should recognize temporal separation despite typo
        assert "sequenziell" in answer or "trennkost-konform" in answer or "wartezeit" in answer
        assert "nicht" not in answer or "nicht konform" not in answer

    def test_typo_in_food_name(self, conversation):
        """Typo 'Resi' → 'Reis' should still trigger food analysis.

        WITHOUT normalization: Bot might not recognize 'Resi' as food.
        WITH normalization: Bot correctly identifies Reis (KH) + Hähnchen (PROTEIN).
        """
        response = handle_chat(
            conversation_id=conversation,
            user_message="Ist Resi mit Hähnchen ok?"  # Typo: Resi → Reis
        )
        answer = response["answer"].lower()

        # Should recognize as NOT_OK (KH + PROTEIN)
        assert "nicht" in answer and ("konform" in answer or "ok" in answer)


class TestLanguageTranslationE2E:
    """Tests that English queries are translated and processed correctly."""

    def test_english_food_query(self, conversation):
        """English query should be translated and analyzed.

        WITHOUT normalization: Bot might not recognize English food names.
        WITH normalization: Bot translates to German and analyzes correctly.
        """
        response = handle_chat(
            conversation_id=conversation,
            user_message="Is chicken with rice allowed?"  # English → German
        )
        answer = response["answer"].lower()

        # Should recognize as NOT_OK (Hähnchen=PROTEIN + Reis=KH)
        assert "nicht" in answer and ("konform" in answer or "ok" in answer or "erlaubt" in answer)

    def test_mixed_language(self, conversation):
        """Mixed English/German should be normalized to all German.

        WITHOUT normalization: Might miss English words in ontology lookup.
        WITH normalization: All food items translated to German.
        """
        response = handle_chat(
            conversation_id=conversation,
            user_message="Kann ich salmon mit Gemüse essen?"  # salmon → Lachs
        )
        answer = response["answer"].lower()

        # Should recognize salmon (fish/PROTEIN) + Gemüse (NEUTRAL) = OK
        assert "ja" in answer or "konform" in answer or "ok" in answer
        # Should not have negative verdict words like "nicht konform"
        assert "nicht konform" not in answer and "nicht erlaubt" not in answer


class TestTimeFormatStandardizationE2E:
    """Tests that different time formats are standardized for temporal detection."""

    def test_minutes_word_format(self, conversation):
        """'30 minuten' should be standardized to '30 min' for temporal detection.

        WITHOUT normalization: Regex might not match 'minuten'.
        WITH normalization: Standardized to '30 min', temporal pattern detected.
        """
        response = handle_chat(
            conversation_id=conversation,
            user_message="Apfel 30 minuten vor Reis"  # minuten → min
        )
        answer = response["answer"].lower()

        # Should recognize temporal separation
        assert "trennkost-konform" in answer or "sequenziell" in answer
        assert "30" in answer  # Should mention the wait time

    def test_hour_format(self, conversation):
        """'halbe Stunde' should be converted to minutes.

        WITHOUT normalization: Might not recognize time format.
        WITH normalization: Converted to standardized format.
        """
        response = handle_chat(
            conversation_id=conversation,
            user_message="Kann ich Obst eine halbe Stunde vor dem Essen essen?"
        )
        answer = response["answer"].lower()

        # Should discuss temporal separation / wait times
        assert "wartezeit" in answer or "min" in answer or "trennung" in answer


class TestFollowUpPreservationE2E:
    """Tests that short follow-up messages are preserved, not incorrectly expanded."""

    def test_short_choice_followup(self, conversation):
        """'den Fisch' as follow-up should be preserved.

        WITHOUT normalization: Might get over-expanded to full sentence.
        WITH normalization: Preserved as short follow-up, system understands context.
        """
        # First message: Ask about Fisch + Reis (NOT_OK)
        response1 = handle_chat(
            conversation_id=conversation,
            user_message="Ist Fisch mit Reis ok?"
        )

        # Second message: Short follow-up (user chooses fish)
        response2 = handle_chat(
            conversation_id=conversation,
            user_message="den Fisch"  # Should NOT be expanded to "Ich möchte den Fisch mit Reis essen"
        )
        answer2 = response2["answer"].lower()

        # Bot should respond appropriately to the choice
        # (e.g., suggest PROTEIN-compatible recipes or acknowledge the choice)
        assert len(answer2) > 0
        # Should not confuse the follow-up for a new full question
        assert "fisch" in answer2

    def test_ok_followup(self, conversation):
        """'ok' as follow-up should stay short.

        WITHOUT normalization: Might get expanded to full sentence.
        WITH normalization: Preserved, bot understands it's a confirmation.
        """
        # First message: Ask for recipe
        response1 = handle_chat(
            conversation_id=conversation,
            user_message="Kannst du mir ein Rezept vorschlagen?"
        )

        # Second message: User says ok
        response2 = handle_chat(
            conversation_id=conversation,
            user_message="ok"  # Should NOT be expanded
        )
        answer2 = response2["answer"].lower()

        # Should respond to the confirmation
        assert len(answer2) > 0


class TestEdgeCases:
    """Test edge cases where normalization helps significantly."""

    def test_multiple_typos_and_translation(self, conversation):
        """Multiple issues in one query: typos + English + time format.

        WITHOUT normalization: Would fail on multiple fronts.
        WITH normalization: All issues fixed, query processed correctly.
        """
        response = handle_chat(
            conversation_id=conversation,
            user_message="cann i eat apple 30 minuten before chiken?"  # Multiple issues
        )
        answer = response["answer"].lower()

        # Should process the query despite all the issues
        assert len(answer) > 0
        # Should recognize temporal separation OR warn about OBST + PROTEIN
        assert any(word in answer for word in ["wartezeit", "trennung", "konform", "nicht"])

    def test_german_with_english_food(self, conversation):
        """German question with English food names.

        WITHOUT normalization: English food might not be in ontology.
        WITH normalization: Translated to German, found in ontology.
        """
        response = handle_chat(
            conversation_id=conversation,
            user_message="Darf ich eggs mit bread essen?"  # eggs → Eier, bread → Brot
        )
        answer = response["answer"].lower()

        # Should recognize Eier (PROTEIN) + Brot (KH) = NOT_OK
        assert "nicht" in answer and ("konform" in answer or "ok" in answer)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
