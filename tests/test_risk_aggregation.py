"""
Focused tests for structured risk / ampel aggregation.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.models import TrafficLight, Verdict
from trennkost.normalizer import normalize_dish
from trennkost.engine import TrennkostEngine


@pytest.fixture(scope="module")
def engine():
    return TrennkostEngine()


def test_yellow_risk_item_produces_yellow_traffic_light(engine):
    analysis = normalize_dish("Test", raw_items=["Seitan"])
    result = engine.evaluate(analysis)

    assert result.verdict == Verdict.OK
    assert result.traffic_light == TrafficLight.YELLOW
    assert result.risk_codes == ["GLUTEN_HIGH"]
    assert result.risk_facts[0].risk_code == "GLUTEN_HIGH"
    assert result.risk_facts[0].severity.value == "YELLOW"


def test_red_risk_item_produces_red_traffic_light(engine):
    analysis = normalize_dish("Test", raw_items=["Mayonnaise"])
    result = engine.evaluate(analysis)

    assert result.verdict == Verdict.OK
    assert result.traffic_light == TrafficLight.RED
    assert result.risk_codes == ["HEAVY_FAT_LOAD"]
    assert result.risk_facts[0].risk_code == "HEAVY_FAT_LOAD"
    assert result.risk_facts[0].severity.value == "RED"


def test_risk_aggregation_uses_max_severity(engine):
    analysis = normalize_dish("Test", raw_items=["Tofu", "Mayonnaise"])
    result = engine.evaluate(analysis)

    assert result.verdict == Verdict.OK
    assert result.traffic_light == TrafficLight.RED
    assert result.risk_codes == ["SOY", "HEAVY_FAT_LOAD"]
    assert {fact.severity.value for fact in result.risk_facts} == {"YELLOW", "RED"}


def test_verdict_problem_without_item_risk_stays_green(engine):
    analysis = normalize_dish("Test", raw_items=["Reis", "Hähnchen"])
    result = engine.evaluate(analysis)

    assert result.verdict == Verdict.NOT_OK
    assert result.traffic_light == TrafficLight.GREEN
    assert result.risk_codes == []
    assert result.risk_facts == []


def test_fat_guidance_alone_does_not_color_traffic_light(engine):
    analysis = normalize_dish("Test", raw_items=["Kartoffel", "Olivenöl"])
    result = engine.evaluate(analysis)

    assert result.verdict == Verdict.OK
    assert result.guidance_codes == ["FAT_WITH_CONFLICT_GROUP_TINY_AMOUNT"]
    assert result.traffic_light == TrafficLight.GREEN
    assert result.risk_codes == []


def test_intrinsic_conflict_without_risk_metadata_stays_green(engine):
    analysis = normalize_dish("Test", raw_items=["Cordon Bleu"])
    result = engine.evaluate(analysis)

    assert result.verdict == Verdict.NOT_OK
    assert result.traffic_light == TrafficLight.GREEN
    assert result.risk_codes == []
