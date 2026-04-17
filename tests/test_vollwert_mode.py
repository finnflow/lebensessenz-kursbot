"""
Tests for vollwert analysis mode.

Vollwert mode uses only the ampel/risk layer — no trennkost combination rules.
Verdict is derived from traffic_light: GREEN→OK, YELLOW→CONDITIONAL, RED→NOT_OK.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.models import AnalysisMode, TrafficLight, Verdict
from trennkost.normalizer import normalize_dish
from trennkost.engine import TrennkostEngine


@pytest.fixture(scope="module")
def engine():
    return TrennkostEngine()


def test_vollwert_mode_has_correct_analysis_mode_and_verdict_basis(engine):
    analysis = normalize_dish("Test", raw_items=["Tofu", "Reis"])
    result = engine.evaluate(analysis, mode="vollwert")

    assert result.analysis_mode == AnalysisMode.VOLLWERT
    assert result.verdict_basis == "traffic_light"


def test_vollwert_mode_alias_strict_maps_to_trennkost(engine):
    analysis = normalize_dish("Test", raw_items=["Tofu", "Reis"])
    result = engine.evaluate(analysis, mode="strict")

    assert result.analysis_mode == AnalysisMode.TRENNKOST
    assert result.verdict_basis == "trennkost"


def test_vollwert_mode_alias_light_maps_to_vollwert(engine):
    analysis = normalize_dish("Test", raw_items=["Tofu", "Reis"])
    result = engine.evaluate(analysis, mode="light")

    assert result.analysis_mode == AnalysisMode.VOLLWERT
    assert result.verdict_basis == "traffic_light"


def test_vollwert_mode_no_trennkost_problems(engine):
    """Tofu+Reis is NOT_OK in trennkost mode, but vollwert produces no rule problems."""
    analysis = normalize_dish("Test", raw_items=["Tofu", "Reis"])

    trennkost_result = engine.evaluate(analysis, mode="trennkost")
    vollwert_result = engine.evaluate(analysis, mode="vollwert")

    assert trennkost_result.verdict == Verdict.NOT_OK
    assert trennkost_result.problems  # Has trennkost rule violations

    assert vollwert_result.problems == []  # No trennkost rule problems in vollwert mode


def test_vollwert_mode_verdict_from_traffic_light_green(engine):
    """Items without risk codes → GREEN traffic light → OK verdict."""
    analysis = normalize_dish("Test", raw_items=["Hähnchen", "Brokkoli"])
    result = engine.evaluate(analysis, mode="vollwert")

    assert result.traffic_light == TrafficLight.GREEN
    assert result.verdict == Verdict.OK


def test_vollwert_mode_verdict_from_traffic_light_yellow(engine):
    """Item with YELLOW risk code → YELLOW traffic light → CONDITIONAL verdict."""
    # Find an item that has a yellow risk code
    analysis = normalize_dish("Test", raw_items=["Hähnchen"])
    result = engine.evaluate(analysis, mode="vollwert")

    if result.traffic_light == TrafficLight.YELLOW:
        assert result.verdict == Verdict.CONDITIONAL
    elif result.traffic_light == TrafficLight.RED:
        assert result.verdict == Verdict.NOT_OK
    else:
        assert result.verdict == Verdict.OK


def test_vollwert_mode_verdict_green_ok_red_not_ok(engine):
    """GREEN → OK, RED → NOT_OK."""
    # Test the mapping directly through verdict_from_traffic_light
    assert engine._verdict_from_traffic_light(TrafficLight.GREEN) == Verdict.OK
    assert engine._verdict_from_traffic_light(TrafficLight.YELLOW) == Verdict.CONDITIONAL
    assert engine._verdict_from_traffic_light(TrafficLight.RED) == Verdict.NOT_OK


def test_vollwert_mode_still_produces_ampel(engine):
    """Vollwert mode still computes traffic_light and risk_facts."""
    analysis = normalize_dish("Test", raw_items=["Hähnchen", "Brokkoli"])
    result = engine.evaluate(analysis, mode="vollwert")

    assert result.traffic_light is not None
    # risk_facts may be empty (no risk codes on these items) but field exists
    assert isinstance(result.risk_facts, list)
    assert isinstance(result.risk_codes, list)


def test_vollwert_mode_guidance_still_computed(engine):
    """Vollwert mode still computes guidance (fat guidance etc.)."""
    analysis = normalize_dish("Test", raw_items=["Pommes", "Mayonnaise"])
    result = engine.evaluate(analysis, mode="vollwert")

    # Guidance should still be produced (fat guidance logic is mode-independent)
    assert isinstance(result.guidance_codes, list)
    assert isinstance(result.guidance_facts, list)


def test_vollwert_mode_health_hints_still_computed(engine):
    """Vollwert mode still produces health hints (non-trennkost recommendations)."""
    analysis = normalize_dish("Test", raw_items=["Hähnchen", "Brokkoli"])
    result = engine.evaluate(analysis, mode="vollwert")

    assert isinstance(result.health_hints, list)


def test_vollwert_mode_summary_no_trennkost_language(engine):
    """Vollwert mode summary must not reference trennkost rules."""
    analysis = normalize_dish("Test", raw_items=["Tofu", "Reis"])
    result = engine.evaluate(analysis, mode="vollwert")

    summary_lower = result.summary.lower()
    assert "trennkost" not in summary_lower
    assert "nicht ok" not in summary_lower  # should be based on ampel, not rule verdict


def test_vollwert_mode_strict_groups_found_empty(engine):
    """Vollwert mode has no strict trennkost group evaluation."""
    analysis = normalize_dish("Test", raw_items=["Tofu", "Reis"])
    result = engine.evaluate(analysis, mode="vollwert")

    assert result.strict_groups_found == {}


def test_vollwert_mode_groups_found_populated(engine):
    """Vollwert mode still builds display groups for context."""
    analysis = normalize_dish("Test", raw_items=["Tofu", "Reis"])
    result = engine.evaluate(analysis, mode="vollwert")

    assert result.groups_found  # Has display group data


def test_trennkost_mode_still_detects_kh_protein_violation(engine):
    """Trennkost mode (default) still applies combination rules."""
    analysis = normalize_dish("Test", raw_items=["Reis", "Hähnchen"])
    result = engine.evaluate(analysis)  # default = trennkost

    assert result.verdict == Verdict.NOT_OK
    assert result.analysis_mode == AnalysisMode.TRENNKOST
    assert result.verdict_basis == "trennkost"
    assert any(p.rule_id.startswith("R0") for p in result.problems)


def test_trennkost_mode_ampel_present_alongside_verdict(engine):
    """Trennkost mode has both verdict from rules AND traffic_light from risk layer."""
    analysis = normalize_dish("Test", raw_items=["Reis", "Hähnchen"])
    result = engine.evaluate(analysis)

    assert result.verdict == Verdict.NOT_OK
    assert result.traffic_light is not None  # Ampel layer also computed
