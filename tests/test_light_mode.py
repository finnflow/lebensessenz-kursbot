"""
Focused tests for dual strict/light deterministic evaluation.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.models import CombinationGroup, EvaluationMode, TrafficLight, Verdict
from trennkost.normalizer import normalize_dish
from trennkost.ontology import Ontology, resolve_combination_group
from trennkost.engine import TrennkostEngine


@pytest.fixture(scope="module")
def ontology():
    return Ontology()


@pytest.fixture(scope="module")
def engine():
    return TrennkostEngine()


@pytest.mark.parametrize(
    ("raw_name", "expected_strict", "expected_light"),
    [
        ("Banane", CombinationGroup.FRUIT_DENSE, CombinationGroup.KH),
        ("Dattel", CombinationGroup.DRIED_FRUIT, CombinationGroup.KH),
        ("Tofu", CombinationGroup.PROTEIN, CombinationGroup.KH),
        ("Tempeh", CombinationGroup.PROTEIN, CombinationGroup.KH),
        ("Seitan", CombinationGroup.PROTEIN, CombinationGroup.KH),
    ],
)
def test_light_mode_resolver_uses_seeded_relaxed_groups(
    ontology,
    raw_name,
    expected_strict,
    expected_light,
):
    item = ontology.lookup_to_food_item(raw_name)

    assert resolve_combination_group(item, mode=EvaluationMode.STRICT) == expected_strict
    assert resolve_combination_group(item, mode=EvaluationMode.LIGHT) == expected_light


@pytest.mark.parametrize("raw_name", ["Tofu", "Tempeh", "Seitan"])
def test_light_mode_relaxes_modeled_plant_proteins_into_kh_combinations(engine, raw_name):
    analysis = normalize_dish("Test", raw_items=[raw_name, "Reis"])

    strict_result = engine.evaluate(analysis)
    light_result = engine.evaluate(analysis, mode="light")

    assert strict_result.verdict == Verdict.NOT_OK
    assert strict_result.strict_verdict == Verdict.NOT_OK
    assert strict_result.active_mode == EvaluationMode.STRICT
    assert strict_result.active_mode_verdict == Verdict.NOT_OK

    assert light_result.active_mode == EvaluationMode.LIGHT
    assert light_result.strict_verdict == Verdict.NOT_OK
    assert light_result.active_mode_verdict == Verdict.OK
    assert light_result.verdict == Verdict.OK
    assert light_result.mode_relaxation_applied is True
    assert light_result.mode_delta_codes == ["LIGHT_MODE_RELAXED"]
    assert set(light_result.strict_groups_found) == {"PROTEIN", "KH"}
    assert set(light_result.groups_found) == {"KH"}
    assert light_result.traffic_light == strict_result.traffic_light
    assert light_result.risk_codes == strict_result.risk_codes


@pytest.mark.parametrize(
    ("items", "strict_fruit_group"),
    [
        (["Banane", "Mandeln"], "FRUIT_DENSE"),
        (["Dattel", "Mandeln"], "DRIED_FRUIT"),
    ],
)
def test_light_mode_turns_relaxed_fruit_fat_cases_into_guidance(engine, items, strict_fruit_group):
    analysis = normalize_dish("Test", raw_items=items)

    strict_result = engine.evaluate(analysis)
    light_result = engine.evaluate(analysis, mode="light")

    assert strict_result.verdict == Verdict.NOT_OK
    assert any(problem.rule_id == "R014" for problem in strict_result.problems)
    assert strict_result.guidance_codes == []

    assert light_result.verdict == Verdict.OK
    assert light_result.strict_verdict == Verdict.NOT_OK
    assert light_result.active_mode_verdict == Verdict.OK
    assert light_result.mode_relaxation_applied is True
    assert light_result.guidance_codes == ["FAT_WITH_CONFLICT_GROUP_TINY_AMOUNT"]
    assert strict_fruit_group in light_result.strict_groups_found
    assert set(light_result.groups_found) == {"KH", "FETT"}
    assert light_result.traffic_light == TrafficLight.GREEN
    assert light_result.traffic_light == strict_result.traffic_light


def test_non_mode_related_case_stays_stable_in_light_mode(engine):
    analysis = normalize_dish("Test", raw_items=["Reis", "Hähnchen"])

    strict_result = engine.evaluate(analysis)
    light_result = engine.evaluate(analysis, mode="light")

    assert strict_result.verdict == Verdict.NOT_OK
    assert light_result.verdict == Verdict.NOT_OK
    assert light_result.strict_verdict == Verdict.NOT_OK
    assert light_result.active_mode_verdict == Verdict.NOT_OK
    assert light_result.mode_relaxation_applied is False
    assert light_result.traffic_light == strict_result.traffic_light == TrafficLight.GREEN
