"""
Tests for health_hints separation from problems.
H001 (Zucker-Gesundheitshinweis) must land in health_hints, not problems.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.engine import evaluate_dish
from trennkost.normalizer import normalize_dish


def test_h001_lands_in_health_hints_not_problems():
    raw_items = ["Reis", "Zucker"]
    result = evaluate_dish(normalize_dish("Reis mit Zucker", raw_items))
    assert result.verdict.value == "OK"
    assert not any(p.rule_id == "H001" for p in result.problems)
    assert any(h.rule_id == "H001" for h in result.health_hints)


def test_verdict_ok_when_only_zucker_added():
    raw_items = ["Haferflocken", "Zucker"]
    result = evaluate_dish(normalize_dish("Haferflocken mit Zucker", raw_items))
    assert result.verdict.value == "OK"
    assert result.health_hints  # H001 vorhanden
