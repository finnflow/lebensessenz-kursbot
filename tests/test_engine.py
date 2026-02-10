"""
Tests for the Trennkost Rule Engine.

Runs 20 fixture dishes through the full pipeline:
  ontology lookup → engine evaluation → verdict check.

Usage:
  pytest tests/test_engine.py -v
"""
import json
import sys
from pathlib import Path

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.models import FoodGroup, Verdict, DishAnalysis, FoodItem
from trennkost.ontology import Ontology
from trennkost.engine import TrennkostEngine

FIXTURES = Path(__file__).parent / "fixtures" / "dishes.json"


@pytest.fixture(scope="module")
def ontology():
    return Ontology()


@pytest.fixture(scope="module")
def engine():
    return TrennkostEngine()


@pytest.fixture(scope="module")
def dishes():
    with open(FIXTURES, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["dishes"]


# ── Ontology Lookup Tests ──────────────────────────────────────────────

class TestOntologyLookup:
    """Test that ontology resolves common items correctly."""

    @pytest.mark.parametrize("raw,expected_group", [
        ("Reis", FoodGroup.KH),
        ("Spaghetti", FoodGroup.KH),
        ("Hähnchen", FoodGroup.PROTEIN),
        ("Lachs", FoodGroup.PROTEIN),
        ("Brokkoli", FoodGroup.NEUTRAL),
        ("Spinat", FoodGroup.NEUTRAL),
        ("Käse", FoodGroup.MILCH),
        ("Parmesan", FoodGroup.MILCH),
        ("Olivenöl", FoodGroup.FETT),
        ("Avocado", FoodGroup.FETT),
        ("Linsen", FoodGroup.HUELSENFRUECHTE),
        ("Kichererbsen", FoodGroup.HUELSENFRUECHTE),
        ("Apfel", FoodGroup.OBST),
        ("Banane", FoodGroup.OBST),
        ("Datteln", FoodGroup.TROCKENOBST),
        ("Butter", FoodGroup.FETT),
    ])
    def test_basic_lookup(self, ontology, raw, expected_group):
        entry = ontology.lookup(raw)
        assert entry is not None, f"'{raw}' not found in ontology"
        assert entry.group == expected_group, f"'{raw}': expected {expected_group}, got {entry.group}"

    @pytest.mark.parametrize("raw,expected_group", [
        ("Vollkornreis", FoodGroup.KH),
        ("Penne", FoodGroup.KH),
        ("Hühnchen", FoodGroup.PROTEIN),
        ("Räucherlachs", FoodGroup.PROTEIN),
        ("Mozzarella", FoodGroup.MILCH),
        ("Creme fraiche", FoodGroup.MILCH),
        ("Mandeln", FoodGroup.FETT),
        ("Tahini", FoodGroup.FETT),
        ("Falafel", FoodGroup.HUELSENFRUECHTE),
        ("Hummus", FoodGroup.HUELSENFRUECHTE),
    ])
    def test_synonym_lookup(self, ontology, raw, expected_group):
        entry = ontology.lookup(raw)
        assert entry is not None, f"Synonym '{raw}' not found"
        assert entry.group == expected_group

    def test_unknown_item(self, ontology):
        entry = ontology.lookup("Xylophon-Frucht")
        assert entry is None

    def test_ambiguous_item(self, ontology):
        entry = ontology.lookup("Bohnen")
        assert entry is not None
        assert entry.ambiguity_flag is True


# ── Rule Engine Unit Tests ─────────────────────────────────────────────

class TestRuleEngine:
    """Test individual rules."""

    def _make_analysis(self, name: str, items: list, ontology) -> DishAnalysis:
        food_items = []
        unknown = []
        for raw in items:
            fi = ontology.lookup_to_food_item(raw)
            food_items.append(fi)
            if fi.group == FoodGroup.UNKNOWN:
                unknown.append(raw)
        return DishAnalysis(dish_name=name, items=food_items, unknown_items=unknown)

    def test_kh_protein_not_ok(self, engine, ontology):
        """R001: KH + PROTEIN → NOT_OK"""
        analysis = self._make_analysis("Test", ["Reis", "Hähnchen"], ontology)
        result = engine.evaluate(analysis)
        assert result.verdict == Verdict.NOT_OK
        assert any(p.rule_id == "R001" for p in result.problems)

    def test_kh_milch_not_ok(self, engine, ontology):
        """R002: KH + MILCH → NOT_OK"""
        analysis = self._make_analysis("Test", ["Brot", "Käse"], ontology)
        result = engine.evaluate(analysis)
        assert result.verdict == Verdict.NOT_OK
        assert any(p.rule_id == "R002" for p in result.problems)

    def test_huelse_kh_not_ok(self, engine, ontology):
        """R003: HUELSENFRUECHTE + KH → NOT_OK"""
        analysis = self._make_analysis("Test", ["Linsen", "Brot"], ontology)
        result = engine.evaluate(analysis)
        assert result.verdict == Verdict.NOT_OK
        assert any(p.rule_id == "R003" for p in result.problems)

    def test_huelse_protein_not_ok(self, engine, ontology):
        """R004: HUELSENFRUECHTE + PROTEIN → NOT_OK"""
        analysis = self._make_analysis("Test", ["Kichererbsen", "Hähnchen"], ontology)
        result = engine.evaluate(analysis)
        assert result.verdict == Verdict.NOT_OK

    def test_protein_milch_not_ok(self, engine, ontology):
        """R006: PROTEIN + MILCH → NOT_OK"""
        analysis = self._make_analysis("Test", ["Ei", "Käse"], ontology)
        result = engine.evaluate(analysis)
        assert result.verdict == Verdict.NOT_OK

    def test_obst_kh_not_ok(self, engine, ontology):
        """R007: OBST + KH → NOT_OK"""
        analysis = self._make_analysis("Test", ["Apfel", "Brot"], ontology)
        result = engine.evaluate(analysis)
        assert result.verdict == Verdict.NOT_OK

    def test_obst_protein_not_ok(self, engine, ontology):
        """R008: OBST + PROTEIN → NOT_OK"""
        analysis = self._make_analysis("Test", ["Banane", "Hähnchen"], ontology)
        result = engine.evaluate(analysis)
        assert result.verdict == Verdict.NOT_OK

    def test_smoothie_ok(self, engine, ontology):
        """R012: OBST + BLATTGRUEN → OK (Smoothie-Ausnahme)"""
        analysis = self._make_analysis("Smoothie", ["Banane", "Spinat"], ontology)
        result = engine.evaluate(analysis)
        assert result.verdict == Verdict.OK

    def test_obst_non_blattgruen_conditional(self, engine, ontology):
        """R013: OBST + stärkearmes Gemüse (nicht Blattgrün) → CONDITIONAL (WARNING)"""
        analysis = self._make_analysis("Test", ["Apfel", "Paprika"], ontology)
        result = engine.evaluate(analysis)
        assert result.verdict == Verdict.CONDITIONAL
        assert any(p.rule_id == "R013" for p in result.problems)

    def test_kh_kh_ok(self, engine, ontology):
        """R015: Multiple KH sources → OK"""
        analysis = self._make_analysis("Test", ["Reis", "Kartoffel"], ontology)
        result = engine.evaluate(analysis)
        assert result.verdict == Verdict.OK

    def test_neutral_only_ok(self, engine, ontology):
        """Pure NEUTRAL meal → OK"""
        analysis = self._make_analysis("Salat", ["Gurke", "Tomate", "Paprika"], ontology)
        result = engine.evaluate(analysis)
        assert result.verdict == Verdict.OK

    def test_kh_neutral_ok(self, engine, ontology):
        """KH + NEUTRAL (no fat) → OK"""
        analysis = self._make_analysis("Test", ["Kartoffel", "Brokkoli", "Zwiebel"], ontology)
        result = engine.evaluate(analysis)
        assert result.verdict == Verdict.OK

    def test_fett_triggers_conditional(self, engine, ontology):
        """FETT with other concentrated food → CONDITIONAL (quantity dependent)"""
        analysis = self._make_analysis("Test", ["Reis", "Brokkoli", "Olivenöl"], ontology)
        result = engine.evaluate(analysis)
        assert result.verdict == Verdict.CONDITIONAL
        assert any(q for q in result.required_questions if "Fett" in q.question or "fett" in q.question.lower())

    def test_unknown_item_conditional(self, engine, ontology):
        """Unknown items → CONDITIONAL"""
        items = [
            FoodItem(raw_name="Kartoffel", canonical="Kartoffel", group=FoodGroup.KH),
            FoodItem(raw_name="Mysterium-Pulver", group=FoodGroup.UNKNOWN),
        ]
        analysis = DishAnalysis(
            dish_name="Test",
            items=items,
            unknown_items=["Mysterium-Pulver"],
        )
        result = engine.evaluate(analysis)
        assert result.verdict == Verdict.CONDITIONAL

    def test_assumed_items_trigger_question(self, engine, ontology):
        """Assumed items → required question about confirmation."""
        items = [FoodItem(raw_name="Pasta", canonical="Pasta", group=FoodGroup.KH)]
        assumed = [FoodItem(
            raw_name="Sahne", canonical="Sahne", group=FoodGroup.MILCH,
            assumed=True, assumption_reason="oft in Carbonara"
        )]
        analysis = DishAnalysis(
            dish_name="Test", items=items, assumed_items=assumed,
        )
        result = engine.evaluate(analysis)
        assert any("vermute" in q.question.lower() or "stimmt" in q.question.lower()
                    for q in result.required_questions)


# ── Fixture-Based Integration Tests ───────────────────────────────────

class TestFixtureDishes:
    """Run all 20 fixture dishes through the pipeline."""

    def test_all_fixtures(self, engine, ontology, dishes):
        """Test that every fixture dish gets the expected verdict."""
        failures = []
        for dish in dishes:
            analysis = DishAnalysis(
                dish_name=dish["name"],
                items=[ontology.lookup_to_food_item(item) for item in dish["items"]],
                unknown_items=[
                    item for item in dish["items"]
                    if ontology.lookup(item) is None
                ],
            )
            result = engine.evaluate(analysis)
            expected = Verdict(dish["expected_verdict"])

            if result.verdict != expected:
                failures.append(
                    f"  {dish['id']} {dish['name']}: "
                    f"expected {expected.value}, got {result.verdict.value}\n"
                    f"    groups: {dict(result.groups_found)}\n"
                    f"    problems: {[p.rule_id for p in result.problems]}\n"
                    f"    questions: {len(result.required_questions)}"
                )

        if failures:
            pytest.fail(
                f"{len(failures)}/{len(dishes)} fixtures failed:\n"
                + "\n".join(failures)
            )

    @pytest.mark.parametrize("dish_id", [
        "D01", "D02", "D03", "D04", "D05", "D06", "D07", "D08", "D09", "D10",
        "D11", "D12", "D13", "D14", "D15", "D16", "D17", "D18", "D19", "D20",
    ])
    def test_individual_fixture(self, engine, ontology, dishes, dish_id):
        """Test each fixture individually for clearer failure messages."""
        dish = next(d for d in dishes if d["id"] == dish_id)
        analysis = DishAnalysis(
            dish_name=dish["name"],
            items=[ontology.lookup_to_food_item(item) for item in dish["items"]],
            unknown_items=[
                item for item in dish["items"]
                if ontology.lookup(item) is None
            ],
        )
        result = engine.evaluate(analysis)
        expected = Verdict(dish["expected_verdict"])

        assert result.verdict == expected, (
            f"{dish['name']}: expected {expected.value}, got {result.verdict.value}\n"
            f"Groups: {dict(result.groups_found)}\n"
            f"Problems: {[(p.rule_id, p.description) for p in result.problems]}\n"
            f"Questions: {[q.question for q in result.required_questions]}\n"
            f"Note: {dish['note']}"
        )
