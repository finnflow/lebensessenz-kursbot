import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.engine import TrennkostEngine
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
        "strict_verdict": "OK",
        "light_verdict": "OK",
        "mode_relaxation_applied": False,
        "traffic_light_exact": "RED",
        "must_have_risk_codes": {"FRIED", "HEAVY_FAT_LOAD"},
        "must_have_guidance_codes": set(),
        "must_have_problem_rule_ids": set(),
        "needs_clarification": False,
    },
    {
        "id": "pommes_mayo_guidance",
        "raw_items": ["Pommes", "Mayonnaise"],
        "strict_verdict": "OK",
        "light_verdict": "OK",
        "mode_relaxation_applied": False,
        "traffic_light_exact": "RED",
        "must_have_risk_codes": {"FRIED", "HEAVY_FAT_LOAD"},
        "must_have_guidance_codes": {"FAT_WITH_CONFLICT_GROUP_TINY_AMOUNT"},
        "must_have_problem_rule_ids": set(),
        "needs_clarification": False,
    },
    {
        "id": "pommes_schwein_not_ok",
        "raw_items": ["Pommes", "Schwein"],
        "strict_verdict": "NOT_OK",
        "light_verdict": "NOT_OK",
        "mode_relaxation_applied": False,
        "traffic_light_exact": None,
        "must_have_risk_codes": {"FRIED", "HEAVY_FAT_LOAD"},
        "must_have_guidance_codes": set(),
        "must_have_problem_rule_ids": {"R001"},
        "needs_clarification": False,
    },
    {
        "id": "kartoffel_brokkoli_base_ok",
        "raw_items": ["Kartoffel", "Brokkoli"],
        "strict_verdict": "OK",
        "light_verdict": "OK",
        "mode_relaxation_applied": False,
        "traffic_light_exact": "GREEN",
        "must_have_risk_codes": set(),
        "must_have_guidance_codes": set(),
        "must_have_problem_rule_ids": set(),
        "needs_clarification": False,
    },
    {
        "id": "bratkartoffeln_ei_not_ok",
        "raw_items": ["Bratkartoffeln", "Ei"],
        "strict_verdict": "NOT_OK",
        "light_verdict": "NOT_OK",
        "mode_relaxation_applied": False,
        "traffic_light_exact": None,
        "must_have_risk_codes": {"FRIED"},
        "must_have_guidance_codes": set(),
        "must_have_problem_rule_ids": {"R001"},
        "needs_clarification": False,
    },
    {
        "id": "quinoa_avocado_guidance_only",
        "raw_items": ["Quinoa", "Avocado"],
        "strict_verdict": "OK",
        "light_verdict": "OK",
        "mode_relaxation_applied": False,
        "traffic_light_exact": None,
        "must_have_risk_codes": set(),
        "must_have_guidance_codes": {"FAT_WITH_CONFLICT_GROUP_TINY_AMOUNT"},
        "must_have_problem_rule_ids": set(),
        "needs_clarification": False,
    },
    {
        "id": "apfel_oel_not_ok",
        "raw_items": ["Apfel", "Olivenöl"],
        "strict_verdict": "CONDITIONAL",
        "light_verdict": "CONDITIONAL",
        "mode_relaxation_applied": False,
        "traffic_light_exact": None,
        "must_have_risk_codes": set(),
        "must_have_guidance_codes": set(),
        "must_have_problem_rule_ids": {"R014"},
        "needs_clarification": False,
    },
    {
        "id": "cordon_bleu_intrinsic_conflict",
        "raw_items": ["Cordon Bleu"],
        "strict_verdict": "NOT_OK",
        "light_verdict": "NOT_OK",
        "mode_relaxation_applied": False,
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
        "strict_verdict": "NOT_OK",
        "light_verdict": "NOT_OK",
        "mode_relaxation_applied": False,
        "traffic_light_exact": None,
        "must_have_risk_codes": set(),
        "must_have_guidance_codes": set(),
        "must_have_problem_rule_ids": {"R001"},
        "needs_clarification": False,
        "intrinsic_item": "Chicken Nuggets",
    },
]

ENGINE_GOLD_CASES_P1 = [
    {
        "id": "banane_mandeln_light_relaxed",
        "raw_items": ["Banane", "Mandeln"],
        "strict_verdict": "CONDITIONAL",
        "light_verdict": "OK",
        "mode_relaxation_applied": True,
        "traffic_light_exact": None,
        "must_have_risk_codes": set(),
        "must_have_guidance_codes": {"FAT_WITH_CONFLICT_GROUP_TINY_AMOUNT"},
        "must_have_problem_rule_ids": {"R014"},
        "needs_clarification": False,
    },
    {
        "id": "dattel_mandeln_light_relaxed",
        "raw_items": ["Dattel", "Mandeln"],
        "strict_verdict": "CONDITIONAL",
        "light_verdict": "OK",
        "mode_relaxation_applied": True,
        "traffic_light_exact": None,
        "must_have_risk_codes": set(),
        "must_have_guidance_codes": {"FAT_WITH_CONFLICT_GROUP_TINY_AMOUNT"},
        "must_have_problem_rule_ids": {"R014"},
        "needs_clarification": False,
    },
    {
        "id": "tofu_reis_light_relaxed",
        "raw_items": ["Tofu", "Reis"],
        "strict_verdict": "NOT_OK",
        "light_verdict": "OK",
        "mode_relaxation_applied": True,
        "traffic_light_exact": None,
        "must_have_risk_codes": {"SOY"},
        "must_have_guidance_codes": set(),
        "must_have_problem_rule_ids": {"R001"},
        "needs_clarification": False,
    },
]


def _evaluate_raw_items(engine: TrennkostEngine, raw_items: list[str]):
    analysis = normalize_dish(
        dish_name=" + ".join(raw_items),
        raw_items=raw_items,
    )
    result = engine.evaluate(analysis, mode="light")
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
    analysis, result = _evaluate_raw_items(engine, case["raw_items"])

    assert result.strict_verdict.value == case["strict_verdict"]
    assert result.active_mode_verdict.value == case["light_verdict"]
    assert result.mode_relaxation_applied is case["mode_relaxation_applied"]

    if case["traffic_light_exact"] is not None:
        assert result.traffic_light.value == case["traffic_light_exact"]

    assert case["must_have_risk_codes"].issubset(set(result.risk_codes))
    assert case["must_have_guidance_codes"].issubset(set(result.guidance_codes))
    assert case["must_have_problem_rule_ids"].issubset(_problem_rule_ids(result))
    assert bool(result.required_questions) is case["needs_clarification"]

    intrinsic_item = case.get("intrinsic_item")
    if intrinsic_item:
        _assert_intrinsic_semantics(ontology, analysis, intrinsic_item)


@pytest.mark.p1_light_mode
@pytest.mark.xfail(strict=False, reason="P1 non-blocking characterization in default suite")
@pytest.mark.parametrize("case", ENGINE_GOLD_CASES_P1, ids=lambda c: c["id"])
def test_engine_gold_matrix_p1_light_mode(engine, case):
    analysis, result = _evaluate_raw_items(engine, case["raw_items"])

    assert result.strict_verdict.value == case["strict_verdict"]
    assert result.active_mode_verdict.value == case["light_verdict"]
    assert result.mode_relaxation_applied is case["mode_relaxation_applied"]

    if case["traffic_light_exact"] is not None:
        assert result.traffic_light.value == case["traffic_light_exact"]

    assert case["must_have_risk_codes"].issubset(set(result.risk_codes))
    assert case["must_have_guidance_codes"].issubset(set(result.guidance_codes))
    assert case["must_have_problem_rule_ids"].issubset(_problem_rule_ids(result))
    assert bool(result.required_questions) is case["needs_clarification"]
