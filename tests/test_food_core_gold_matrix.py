import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.engine import TrennkostEngine
from trennkost.models import AnalysisMode
from trennkost.normalizer import normalize_dish
from trennkost.ontology import get_ontology


@pytest.fixture(scope="module")
def engine():
    return TrennkostEngine()


@pytest.fixture(scope="module")
def ontology():
    return get_ontology()


ENGINE_GOLD_CASES_P0 = [
    {
        "id": "pommes_single",
        "raw_items": ["Pommes"],
        "verdict": "NOT_OK",
        "traffic_light_exact": "RED",
        "must_have_risk_codes": {"FRIED", "HEAVY_FAT_LOAD"},
        "must_have_guidance_codes": set(),
        "must_have_problem_rule_ids": {"R_FRIED"},
        "needs_clarification": False,
    },
    {
        "id": "pommes_mayo_guidance",
        "raw_items": ["Pommes", "Mayonnaise"],
        "verdict": "NOT_OK",
        "traffic_light_exact": "RED",
        "must_have_risk_codes": {"FRIED", "HEAVY_FAT_LOAD"},
        "must_have_guidance_codes": {"FAT_WITH_CONFLICT_GROUP_TINY_AMOUNT"},
        "must_have_problem_rule_ids": {"R_FRIED"},
        "needs_clarification": False,
    },
    {
        "id": "pommes_airfryer_ok",
        "raw_items": ["Pommes Heißluft"],
        "verdict": "OK",
        "traffic_light_exact": None,
        "must_have_risk_codes": set(),
        "must_have_guidance_codes": {"AIRFRYER_FAT_HINT"},
        "must_have_problem_rule_ids": set(),
        "needs_clarification": False,
    },
    {
        "id": "bratkartoffeln_single_not_ok",
        "raw_items": ["Bratkartoffeln"],
        "verdict": "NOT_OK",
        "traffic_light_exact": None,
        "must_have_risk_codes": {"FRIED"},
        "must_have_guidance_codes": set(),
        "must_have_problem_rule_ids": {"R_FRIED"},
        "needs_clarification": False,
    },
    {
        "id": "pommes_schwein_not_ok",
        "raw_items": ["Pommes", "Schwein"],
        "verdict": "NOT_OK",
        "traffic_light_exact": None,
        "must_have_risk_codes": {"FRIED", "HEAVY_FAT_LOAD"},
        "must_have_guidance_codes": set(),
        "must_have_problem_rule_ids": {"R001"},
        "needs_clarification": False,
    },
    {
        "id": "kartoffel_brokkoli_base_ok",
        "raw_items": ["Kartoffel", "Brokkoli"],
        "verdict": "OK",
        "traffic_light_exact": "GREEN",
        "must_have_risk_codes": set(),
        "must_have_guidance_codes": set(),
        "must_have_problem_rule_ids": set(),
        "needs_clarification": False,
    },
    {
        "id": "bratkartoffeln_ei_not_ok",
        "raw_items": ["Bratkartoffeln", "Ei"],
        "verdict": "NOT_OK",
        "traffic_light_exact": None,
        "must_have_risk_codes": {"FRIED"},
        "must_have_guidance_codes": set(),
        "must_have_problem_rule_ids": {"R001"},
        "needs_clarification": False,
    },
    {
        "id": "quinoa_avocado_guidance_only",
        "raw_items": ["Quinoa", "Avocado"],
        "verdict": "OK",
        "traffic_light_exact": None,
        "must_have_risk_codes": set(),
        "must_have_guidance_codes": {"FAT_WITH_CONFLICT_GROUP_TINY_AMOUNT"},
        "must_have_problem_rule_ids": set(),
        "needs_clarification": False,
    },
    {
        "id": "apfel_oel_not_ok",
        "raw_items": ["Apfel", "Olivenöl"],
        "verdict": "CONDITIONAL",
        "traffic_light_exact": None,
        "must_have_risk_codes": set(),
        "must_have_guidance_codes": set(),
        "must_have_problem_rule_ids": {"R014"},
        "needs_clarification": False,
    },
    {
        "id": "cordon_bleu_intrinsic_conflict",
        "raw_items": ["Cordon Bleu"],
        "verdict": "NOT_OK",
        "traffic_light_exact": None,
        "must_have_risk_codes": set(),
        "must_have_guidance_codes": set(),
        "must_have_problem_rule_ids": {"R001"},
        "needs_clarification": False,
        "intrinsic_item": "Cordon Bleu",
    },
    {
        "id": "chicken_nuggets_intrinsic_conflict",
        "raw_items": ["Chicken Nuggets"],
        "verdict": "NOT_OK",
        "traffic_light_exact": None,
        "must_have_risk_codes": set(),
        "must_have_guidance_codes": set(),
        "must_have_problem_rule_ids": {"R001"},
        "needs_clarification": False,
        "intrinsic_item": "Chicken Nuggets",
    },
]

# Vollwert-mode cases: no trennkost rules, verdict from traffic_light
ENGINE_GOLD_CASES_VOLLWERT = [
    {
        "id": "banane_mandeln_vollwert",
        "raw_items": ["Banane", "Mandeln"],
        "vollwert_verdict": "OK",     # No risk codes → GREEN → OK
        "no_problems": True,
    },
    {
        "id": "dattel_mandeln_vollwert",
        "raw_items": ["Dattel", "Mandeln"],
        "vollwert_verdict": "OK",
        "no_problems": True,
    },
    {
        "id": "tofu_reis_vollwert",
        "raw_items": ["Tofu", "Reis"],
        "vollwert_verdict": "CONDITIONAL",  # Tofu has SOY (YELLOW risk) → YELLOW → CONDITIONAL
        "must_have_risk_codes": {"SOY"},
        "no_problems": True,
    },
]


def _evaluate_trennkost(engine: TrennkostEngine, raw_items: list[str]):
    analysis = normalize_dish(
        dish_name=" + ".join(raw_items),
        raw_items=raw_items,
    )
    result = engine.evaluate(analysis, mode="trennkost")
    return analysis, result


def _evaluate_vollwert(engine: TrennkostEngine, raw_items: list[str]):
    analysis = normalize_dish(
        dish_name=" + ".join(raw_items),
        raw_items=raw_items,
    )
    result = engine.evaluate(analysis, mode="vollwert")
    return analysis, result


def _problem_rule_ids(result) -> set[str]:
    return {problem.rule_id for problem in result.problems}


def _assert_intrinsic_semantics(ontology, analysis, intrinsic_item: str):
    canonicals = {item.canonical for item in analysis.items}
    assert intrinsic_item in canonicals

    entry = ontology.lookup(intrinsic_item)
    assert entry is not None

    assert bool(
        getattr(entry, "intrinsic_conflict_code", None)
        or getattr(entry, "forced_components", None)
        or getattr(entry, "decompose_for_logic", False)
    ), f"{intrinsic_item} should carry intrinsic/decomposition semantics"


@pytest.mark.parametrize("case", ENGINE_GOLD_CASES_P0, ids=lambda c: c["id"])
def test_engine_gold_matrix_p0(engine, ontology, case):
    analysis, result = _evaluate_trennkost(engine, case["raw_items"])

    assert result.analysis_mode == AnalysisMode.TRENNKOST
    assert result.verdict_basis == "trennkost"
    assert result.verdict.value == case["verdict"]

    if case["traffic_light_exact"] is not None:
        assert result.traffic_light.value == case["traffic_light_exact"]

    assert case["must_have_risk_codes"].issubset(set(result.risk_codes))
    assert case["must_have_guidance_codes"].issubset(set(result.guidance_codes))
    assert case["must_have_problem_rule_ids"].issubset(_problem_rule_ids(result))
    assert bool(result.required_questions) is case["needs_clarification"]

    intrinsic_item = case.get("intrinsic_item")
    if intrinsic_item:
        _assert_intrinsic_semantics(ontology, analysis, intrinsic_item)


@pytest.mark.parametrize("case", ENGINE_GOLD_CASES_VOLLWERT, ids=lambda c: c["id"])
def test_engine_gold_matrix_vollwert(engine, case):
    analysis, result = _evaluate_vollwert(engine, case["raw_items"])

    assert result.analysis_mode == AnalysisMode.VOLLWERT
    assert result.verdict_basis == "traffic_light"
    assert result.verdict.value == case["vollwert_verdict"]
    assert result.problems == [] if case.get("no_problems") else True

    if "must_have_guidance_codes" in case:
        assert case["must_have_guidance_codes"].issubset(set(result.guidance_codes))
    if "must_have_risk_codes" in case:
        assert case["must_have_risk_codes"].issubset(set(result.risk_codes))
