"""
Focused tests for profile-backed deterministic guidance facts.
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


def test_item_guidance_code_surfaces_as_structured_guidance_fact(engine):
    analysis = normalize_dish("Test", raw_items=["Seitan"])
    result = engine.evaluate(analysis)

    assert result.verdict == Verdict.OK
    assert result.guidance_codes == ["GLUTEN_AWARE"]
    assert result.guidance_facts[0].code == "GLUTEN_AWARE"
    assert "Seitan" in result.guidance_facts[0].affected_items[0]


def test_verdict_stays_unchanged_while_guidance_becomes_structured(engine):
    analysis = normalize_dish("Test", raw_items=["Tofu", "Reis"])
    result = engine.evaluate(analysis)

    assert result.verdict == Verdict.NOT_OK
    assert any(problem.rule_id == "R001" for problem in result.problems)
    assert "SOY_IN_MODERATION" in result.guidance_codes


def test_duplicate_item_guidance_code_is_aggregated_once(engine):
    analysis = normalize_dish("Test", raw_items=["Tofu", "Tempeh"])
    result = engine.evaluate(analysis)

    assert result.guidance_codes == ["SOY_IN_MODERATION"]
    assert len(result.guidance_facts) == 1
    assert set(result.guidance_facts[0].affected_items) == {"Tofu", "Tempeh"}
