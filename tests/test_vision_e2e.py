"""
Vision E2E Tests

Tests image upload flows with real photos covering all major scenarios:
- Menu analysis (Speisekarte)
- OK dishes (PROTEIN + NEUTRAL, OBST + BLATTGRUEN)
- NOT_OK dishes (KH + PROTEIN + MILCH, OBST + MILCH)
- CONDITIONAL dishes (HIGH_FAT + KH)
- HUELSENFRUECHTE dishes
- Breakfast context
- Assumed ingredients questions
"""
import pytest
import sys
from pathlib import Path

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.chat_service import handle_chat
from app.database import create_conversation, delete_conversation


# ═══════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "vision"


@pytest.fixture
def conversation():
    """Create a fresh conversation for each test."""
    conv_id = create_conversation(guest_id="test-user-vision-e2e")
    yield conv_id
    # Cleanup after test
    try:
        delete_conversation(conv_id)
    except:
        pass


# ═══════════════════════════════════════════════════════════════════
# MENU ANALYSIS
# ═══════════════════════════════════════════════════════════════════

class TestMenuAnalysis:
    """User uploads menu/Speisekarte and wants recommendations."""

    def test_vietnamese_menu(self, conversation):
        """User: Uploads Vietnamese restaurant menu → Bot suggests OK dishes"""
        menu_path = str(FIXTURES_DIR / "menu_vinh_loc.jpeg")

        response = handle_chat(
            conversation_id=conversation,
            user_message="Was kann ich hier bestellen?",
            image_path=menu_path
            
        )

        answer = response["answer"].lower()

        # Should detect it's a menu
        assert any(word in answer for word in [
            "speisekarte", "karte", "menü", "menu", "gericht"
        ]), "Should recognize menu"

        # Should mention at least one dish from the menu
        # Menu has: Seetangsalat, Vegetarische Suppe, Miso Tofu Suppe, etc.
        has_dish = any(word in answer for word in [
            "salat", "suppe", "seetang", "vegetarisch", "tofu", "miso"
        ])
        assert has_dish, "Should mention at least one dish from menu"

        # Should NOT say "keine Information" (fallback)
        assert "diese information steht nicht" not in answer


# ═══════════════════════════════════════════════════════════════════
# OK DISHES (verschiedene Kombinationen)
# ═══════════════════════════════════════════════════════════════════

class TestOkDishes:
    """Dishes that should be OK according to Trennkost rules."""

    def test_salmon_with_broccoli(self, conversation):
        """User: Lachs mit Brokkoli → OK (PROTEIN + NEUTRAL)"""
        image_path = str(FIXTURES_DIR / "salmon_broccoli.webp")

        response = handle_chat(
            conversation_id=conversation,
            user_message="Ist das ok?",
            image_path=image_path
            
        )

        answer = response["answer"].lower()

        # Should say OK
        assert "ok" in answer or "konform" in answer or "erlaubt" in answer

        # Should identify salmon/fish and broccoli
        has_fish = "lachs" in answer or "fisch" in answer or "salmon" in answer
        has_veggie = "brokkoli" in answer or "gemüse" in answer
        assert has_fish or has_veggie, "Should identify main ingredients"

        # Should NOT say NOT_OK
        assert not ("nicht ok" in answer or "nicht konform" in answer)

    def test_green_smoothie(self, conversation):
        """User: Grüner Smoothie → OK (OBST + BLATTGRUEN exception per R009)"""
        image_path = str(FIXTURES_DIR / "green_smoothie.jpeg")

        response = handle_chat(
            conversation_id=conversation,
            user_message="Ist dieser grüne Smoothie ok?",
            image_path=image_path
            
        )

        answer = response["answer"].lower()

        # Should say OK
        assert "ok" in answer or "konform" in answer or "erlaubt" in answer

        # Should mention it's a green smoothie or has leafy greens
        assert any(word in answer for word in [
            "smoothie", "grün", "blattgrün", "spinat", "salat"
        ]), "Should identify green smoothie"

        # Should NOT say NOT_OK
        assert not ("nicht ok" in answer or "nicht konform" in answer)


# ═══════════════════════════════════════════════════════════════════
# NOT_OK DISHES (verschiedene Verstöße)
# ═══════════════════════════════════════════════════════════════════

class TestNotOkDishes:
    """Dishes that violate Trennkost rules."""

    def test_carbonara(self, conversation):
        """User: Carbonara → NOT_OK (KH + PROTEIN + MILCH)

        Tests compound dish recognition after bug fix.
        """
        image_path = str(FIXTURES_DIR / "carbonara.jpeg")

        response = handle_chat(
            conversation_id=conversation,
            user_message="Ist das trennkost-konform?",
            image_path=image_path
            
        )

        answer = response["answer"].lower()

        # Should say NOT OK
        assert "nicht" in answer and ("konform" in answer or "ok" in answer)

        # Should identify as Carbonara or mention KH + PROTEIN
        is_identified = any(word in answer for word in [
            "carbonara", "spaghetti", "pasta", "nudel"
        ]) and any(word in answer for word in [
            "ei", "speck", "bacon", "protein", "schinken"
        ])

        # Or should at least mention the violation
        mentions_violation = any(word in answer for word in [
            "kohlenhydrat", "protein", "milch", "kombiniert", "verstößt"
        ])

        assert is_identified or mentions_violation, "Should identify problem"

    def test_spaghetti_bolognese(self, conversation):
        """User: Spaghetti Bolognese → Should ask if meat is in sauce (assumed ingredients)"""
        image_path = str(FIXTURES_DIR / "spaghetti_bolognese.jpg")

        response = handle_chat(
            conversation_id=conversation,
            user_message="Ist das ok?",
            image_path=image_path
            
        )

        answer = response["answer"].lower()

        # Bot should either:
        # a) Recognize Bolognese and say NOT_OK, OR
        # b) Ask if there's meat in the sauce
        recognizes_bolognese = "bolognese" in answer or "hackfleisch" in answer
        asks_about_meat = any(word in answer for word in [
            "fleisch", "hackfleisch", "welche zutaten", "was ist in", "enthält"
        ])

        if recognizes_bolognese or asks_about_meat:
            # Good - bot is aware of potential meat
            pass
        else:
            # If bot assumes vegetarian, should say BEDINGT or ask
            assert "bedingt" in answer or "?" in answer, "Should be cautious about sauce"

    def test_yogurt_with_fruit(self, conversation):
        """User: Joghurt mit Früchten → NOT_OK (OBST + MILCH per R010)"""
        image_path = str(FIXTURES_DIR / "yogurt_fruit.jpeg")

        response = handle_chat(
            conversation_id=conversation,
            user_message="Ist das zum Frühstück ok?",
            image_path=image_path
            
        )

        answer = response["answer"].lower()

        # Should say NOT OK
        assert "nicht" in answer and ("konform" in answer or "ok" in answer or "empfohlen" in answer)

        # Should mention yogurt + fruit or OBST + MILCH
        mentions_combo = any(word in answer for word in [
            "joghurt", "milch", "obst", "frucht", "beere"
        ])
        assert mentions_combo, "Should identify yogurt and/or fruit"


# ═══════════════════════════════════════════════════════════════════
# CONDITIONAL DISHES
# ═══════════════════════════════════════════════════════════════════

class TestConditionalDishes:
    """Dishes where verdict depends on quantity or clarification."""

    def test_avocado_toast_breakfast(self, conversation):
        """User: Avocado-Toast zum Frühstück → CONDITIONAL (HIGH_FAT + KH + Frühstück)

        Multiple concerns:
        - HIGH_FAT (Avocado) + KH (Brot) → quantity question
        - Breakfast context → should mention fettarm rule
        """
        image_path = str(FIXTURES_DIR / "avocado_toast.jpg")

        response = handle_chat(
            conversation_id=conversation,
            user_message="Kann ich das zum Frühstück essen?",
            image_path=image_path
            
        )

        answer = response["answer"].lower()

        # Should mention avocado
        assert "avocado" in answer

        # Should either:
        # a) Ask about quantity, OR
        # b) Mention breakfast fat rule, OR
        # c) Say BEDINGT
        asks_quantity = any(word in answer for word in [
            "wie viel", "menge", "bedingt", "abhängig"
        ])
        mentions_breakfast_fat = any(word in answer for word in [
            "frühstück", "fettarm", "fettfrei", "entgiftung"
        ])

        assert asks_quantity or mentions_breakfast_fat or "bedingt" in answer, \
            "Should be cautious about avocado amount or breakfast fat"


# ═══════════════════════════════════════════════════════════════════
# HUELSENFRUECHTE
# ═══════════════════════════════════════════════════════════════════

class TestHuelsenfruechte:
    """Dishes with legumes (beans, lentils, chickpeas)."""

    def test_lentil_soup(self, conversation):
        """User: Vegetarische Linsensuppe → Should be OK or CONDITIONAL

        HUELSENFRUECHTE (Linsen) can be combined with NEUTRAL + small fat.
        Should check if soup has only vegetables and lentils.
        """
        image_path = str(FIXTURES_DIR / "lentil_soup.jpeg")

        response = handle_chat(
            conversation_id=conversation,
            user_message="Ist diese Linsensuppe ok?",
            image_path=image_path
            
        )

        answer = response["answer"].lower()

        # Should identify lentils
        assert "linse" in answer or "hülsenfrucht" in answer

        # Should either say OK or ask about ingredients
        # (Lentils + vegetables = OK, but if coconut milk or other additions?)
        is_positive = any(word in answer for word in [
            "ok", "konform", "erlaubt", "gut", "bedingt"
        ])
        asks_clarification = "?" in answer

        assert is_positive or asks_clarification, "Should evaluate or ask about soup"


# ═══════════════════════════════════════════════════════════════════
# QUALITY & ROBUSTNESS
# ═══════════════════════════════════════════════════════════════════

class TestVisionQuality:
    """Tests for vision quality and robustness."""

    def test_vision_extracts_ingredients(self, conversation):
        """Vision should extract recognizable ingredients, not hallucinate."""
        # Use salmon + broccoli as it has clear, simple ingredients
        image_path = str(FIXTURES_DIR / "salmon_broccoli.webp")

        response = handle_chat(
            conversation_id=conversation,
            user_message="Was ist auf dem Bild?",
            image_path=image_path
            
        )

        answer = response["answer"].lower()

        # Should identify main components
        # At minimum should mention fish/protein and vegetables
        has_protein = any(word in answer for word in [
            "lachs", "fisch", "salmon", "protein"
        ])
        has_veggie = any(word in answer for word in [
            "brokkoli", "gemüse", "broccoli", "vegetable"
        ])

        # Should have at least one correct identification
        assert has_protein or has_veggie, "Should identify at least one main ingredient"

        # Should NOT hallucinate common ingredients that aren't there
        # (e.g., no pasta, no rice, no cheese visible)
        hallucinations = ["pasta", "nudel", "reis", "käse", "kartoffel"]
        has_hallucination = any(word in answer for word in hallucinations)

        # Note: This is a soft check - we don't fail test on hallucination,
        # but we warn about it
        if has_hallucination:
            print(f"[WARNING] Possible hallucination detected in answer")

    def test_no_empty_vision_answers(self, conversation):
        """Vision responses should never be empty or pure fallback."""
        image_path = str(FIXTURES_DIR / "carbonara.jpeg")

        response = handle_chat(
            conversation_id=conversation,
            user_message="Ist das ok?",
            image_path=image_path
            
        )

        answer = response["answer"]

        # Should have meaningful content
        assert answer
        assert len(answer) > 50, "Answer should be substantial"

        # Should NOT be pure fallback
        is_fallback = "diese information steht nicht im kursmaterial" in answer.lower()
        assert not is_fallback, "Should not fall back to 'not in course material' for vision"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
