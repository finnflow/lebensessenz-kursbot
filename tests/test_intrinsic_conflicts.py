"""
Focused tests for intrinsically conflictual single products.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.models import FoodGroup, FoodSubgroup, Verdict
from trennkost.normalizer import normalize_dish
from trennkost.ontology import Ontology
from trennkost.engine import TrennkostEngine


@pytest.fixture(scope="module")
def ontology():
    return Ontology()


@pytest.fixture(scope="module")
def engine():
    return TrennkostEngine()


def test_intrinsic_conflict_rows_keep_single_effective_group_and_subgroup(ontology):
    expected = {
        "Cordon Bleu": FoodSubgroup.FLEISCH,
        "Chicken Nuggets": FoodSubgroup.FLEISCH,
        "Fischstäbchen": FoodSubgroup.FISCH,
        "Paniertes Schnitzel": FoodSubgroup.FLEISCH,
    }

    for raw_name, subgroup in expected.items():
        entry = ontology.lookup(raw_name)
        assert entry is not None
        assert entry.group == FoodGroup.PROTEIN
        assert entry.subgroup == subgroup
        assert entry.intrinsic_conflict_code is not None
        assert entry.decompose_for_logic is True
        assert entry.compound_type == "INTRINSIC_CONFLICT_PRODUCT"
        assert entry.forced_components


def test_cordon_bleu_is_represented_and_decomposed_for_logic():
    analysis = normalize_dish("Cordon Bleu")

    canonicals = [item.canonical for item in analysis.items]
    assert "Cordon Bleu" in canonicals
    assert "Schwein" in canonicals
    assert "Speck" in canonicals
    assert "Käse" in canonicals
    assert "Paniermehl" in canonicals
    assert "Ei" in canonicals

    cordon_bleu = next(item for item in analysis.items if item.canonical == "Cordon Bleu")
    assert cordon_bleu.intrinsic_conflict_code == "STUFFED_BREADED_PROTEIN_CONFLICT"
    assert cordon_bleu.decompose_for_logic is True
    assert analysis.unknown_items == []


@pytest.mark.parametrize(
    ("raw_name", "expected_subgroup"),
    [
        ("Chicken Nuggets", FoodSubgroup.FLEISCH),
        ("Fischstäbchen", FoodSubgroup.FISCH),
        ("Paniertes Schnitzel", FoodSubgroup.FLEISCH),
    ],
)
def test_intrinsic_conflict_items_trigger_internal_not_ok(engine, raw_name, expected_subgroup):
    analysis = normalize_dish("Test", raw_items=[raw_name])
    result = engine.evaluate(analysis)

    assert result.verdict == Verdict.NOT_OK
    assert any(problem.rule_id == "R001" for problem in result.problems)

    canonicals = {item.canonical for item in analysis.items}
    assert raw_name in canonicals

    intrinsic_item = next(item for item in analysis.items if item.canonical == raw_name)
    assert intrinsic_item.group == FoodGroup.PROTEIN
    assert intrinsic_item.subgroup == expected_subgroup
    assert intrinsic_item.intrinsic_conflict_code is not None


def test_salad_and_nuggets_blame_nuggets_not_salad(engine):
    analysis = normalize_dish("Test", raw_items=["Kopfsalat", "Chicken Nuggets"])
    result = engine.evaluate(analysis)

    assert result.verdict == Verdict.NOT_OK

    affected_items = [
        affected_item
        for problem in result.problems
        for affected_item in problem.affected_items
    ]
    assert any("Chicken Nuggets" in item for item in affected_items)
    assert not any("Kopfsalat" in item for item in affected_items)
