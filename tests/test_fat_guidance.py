"""
Focused tests for fat verdict/guidance separation.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.models import Verdict
from trennkost.normalizer import normalize_dish
from trennkost.engine import TrennkostEngine


@pytest.fixture(scope="module")
def engine():
    return TrennkostEngine()


def test_fat_and_fruit_stays_not_ok(engine):
    analysis = normalize_dish("Test", raw_items=["Apfel", "Olivenöl"])
    result = engine.evaluate(analysis)

    assert result.verdict == Verdict.NOT_OK
    assert any(problem.rule_id == "R014" for problem in result.problems)
    assert result.guidance_codes == []


def test_fat_and_neutral_emits_structured_guidance(engine):
    analysis = normalize_dish("Test", raw_items=["Kopfsalat", "Olivenöl", "Avocado"])
    result = engine.evaluate(analysis)

    assert result.verdict == Verdict.OK
    assert result.guidance_codes == ["FAT_WITH_NEUTRAL_SMALL_AMOUNT"]
    assert {fact.fat_category for fact in result.guidance_facts} == {
        "OIL_BUTTER",
        "NUT_SEED_AVOCADO",
    }
    assert {fact.amount_hint for fact in result.guidance_facts} == {
        "ca. 1-2 EL",
        "bis ca. 1/2 Tasse",
    }


def test_mayonnaise_uses_fat_guidance_with_kh(engine):
    analysis = normalize_dish("Test", raw_items=["Kartoffel", "Mayonnaise"])
    result = engine.evaluate(analysis)

    assert result.verdict == Verdict.OK
    assert "FETT" in result.groups_found
    assert result.guidance_codes == ["FAT_WITH_CONFLICT_GROUP_TINY_AMOUNT"]
    assert result.guidance_facts[0].amount_hint == "max. ca. 1-2 TL"
    assert "Mayonnaise" in result.guidance_facts[0].affected_items[0]


def test_non_fat_rule_behavior_stays_stable(engine):
    analysis = normalize_dish("Test", raw_items=["Reis", "Hähnchen"])
    result = engine.evaluate(analysis)

    assert result.verdict == Verdict.NOT_OK
    assert any(problem.rule_id == "R001" for problem in result.problems)
