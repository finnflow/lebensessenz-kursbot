import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.analyzer import analyze_text
from trennkost.engine import TrennkostEngine
from trennkost.models import TrafficLight, Verdict
from trennkost.normalizer import normalize_dish


@pytest.fixture(scope="module")
def engine():
    return TrennkostEngine()


def _problem_ids(result) -> set[str]:
    return {problem.rule_id for problem in result.problems}


@pytest.mark.parametrize(
    ("raw_items", "expected_verdict", "must_have_rules", "must_not_have_rules"),
    [
        (["Hähnchen", "Ei", "Gurke"], Verdict.NOT_OK, {"R018"}, set()),
        (["Hähnchen", "Rind", "Brokkoli"], Verdict.OK, set(), {"R018"}),
        (["Lachs", "Thunfisch", "Salat"], Verdict.OK, set(), {"R018"}),
        (["Lachs", "Ei", "Zucchini"], Verdict.NOT_OK, {"R018"}, set()),
    ],
    ids=[
        "chicken_egg_cucumber_mixed_protein",
        "chicken_beef_same_subgroup_ok",
        "salmon_tuna_same_subgroup_ok",
        "salmon_egg_zucchini_mixed_protein",
    ],
)
def test_protein_gatekeepers(engine, raw_items, expected_verdict, must_have_rules, must_not_have_rules):
    analysis = normalize_dish(" + ".join(raw_items), raw_items=raw_items)
    result = engine.evaluate(analysis)
    rule_ids = _problem_ids(result)

    assert result.strict_verdict == expected_verdict
    assert result.active_mode_verdict == expected_verdict
    assert result.mode_relaxation_applied is False
    assert result.required_questions == []
    assert analysis.unknown_items == []
    assert must_have_rules.issubset(rule_ids)
    assert not (must_not_have_rules & rule_ids)


def test_green_smoothie_gatekeeper_stays_ok_without_r013(engine):
    analysis = normalize_dish(
        "Grüner Smoothie",
        raw_items=["Banane", "Spinat", "Ingwer", "Wasser"],
    )
    result = engine.evaluate(analysis)

    assert result.strict_verdict == Verdict.OK
    assert result.active_mode_verdict == Verdict.OK
    assert result.required_questions == []
    assert "R013" not in _problem_ids(result)


def test_apfel_und_paprika_stays_conditional_with_r013(engine):
    analysis = normalize_dish("Apfel + Paprika", raw_items=["Apfel", "Paprika"])
    result = engine.evaluate(analysis)

    assert result.strict_verdict == Verdict.CONDITIONAL
    assert result.active_mode_verdict == Verdict.CONDITIONAL
    assert "R013" in _problem_ids(result)


def test_reis_brokkoli_olivenoel_stays_ok_with_structured_fat_guidance(engine):
    analysis = normalize_dish(
        "Reis + Brokkoli + Olivenöl",
        raw_items=["Reis", "Brokkoli", "Olivenöl"],
    )
    result = engine.evaluate(analysis)

    assert result.strict_verdict == Verdict.OK
    assert result.active_mode_verdict == Verdict.OK
    assert result.guidance_codes == ["FAT_WITH_CONFLICT_GROUP_TINY_AMOUNT"]
    assert result.required_questions == []


def test_pommes_text_path_keeps_red_traffic_light_and_risk_codes():
    result = analyze_text("Pommes", llm_fn=None, mode="strict", evaluation_mode="strict")[0]

    assert result.dish_name == "Pommes"
    assert result.strict_verdict == Verdict.OK
    assert result.active_mode_verdict == Verdict.OK
    assert result.traffic_light == TrafficLight.RED
    assert result.risk_codes == ["FRIED", "HEAVY_FAT_LOAD"]
    assert result.required_questions == []


def test_cordon_bleu_keeps_intrinsic_semantics_and_not_ok_verdict(engine):
    analysis = normalize_dish("Cordon Bleu")
    result = engine.evaluate(analysis)
    canonicals = {item.canonical for item in analysis.items}

    assert "Cordon Bleu" in canonicals
    assert {"Schwein", "Speck", "Käse", "Paniermehl", "Ei"}.issubset(canonicals)
    intrinsic = next(item for item in analysis.items if item.canonical == "Cordon Bleu")
    assert intrinsic.decompose_for_logic is True
    assert intrinsic.intrinsic_conflict_code == "STUFFED_BREADED_PROTEIN_CONFLICT"
    assert result.strict_verdict == Verdict.NOT_OK
    assert "R001" in _problem_ids(result)


def test_burger_with_explicit_ingredients_avoids_generic_compound_clarification():
    result = analyze_text(
        "Ist ein Burger mit Tempeh, Salat, Gurke und Ketchup ok?",
        llm_fn=None,
        mode="strict",
        evaluation_mode="strict",
    )[0]

    assert result.dish_name == "Burger"
    assert result.required_questions == []
    assert result.debug["unknown_items"] == []
    assert "R001" in _problem_ids(result)
