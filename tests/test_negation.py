"""
Tests for negation filtering in assumed_items.
'ohne X', 'kein X', 'without X' → X wird nicht als assumed_item ergänzt.
Negation wirkt nur auf assumed/optional, nie auf explizite raw_items.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.analyzer import analyze_text


def test_ohne_mayo_removes_mayo_from_assumed():
    results = analyze_text("Kartoffelsalat ohne Mayonnaise")
    r = results[0]
    # debug["assumed_items"] is a list of raw_name strings
    assumed_names = r.debug.get("assumed_items", [])
    # Nach Prompt 1 ist Mayo aus compounds.json raus — aber falls sie
    # noch als assumed_item käme, muss sie hier fehlen
    assert "Mayonnaise" not in assumed_names


def test_ohne_tahini_removes_tahini_from_assumed():
    results = analyze_text("Hummus mit Gemüsesticks ohne Tahini")
    r = results[0]
    assumed_names = r.debug.get("assumed_items", [])
    assert "Tahini" not in assumed_names


def test_negation_does_not_affect_explicit_items():
    # Explizite Zutat bleibt — Negation wirkt nur auf assumed
    results = analyze_text("Salat mit Olivenöl, ohne Mayonnaise")
    r = results[0]
    # Olivenöl ist explizit → bleibt in groups_found
    flat = [name for group in r.groups_found.values() for name in group]
    assert any("Olivenöl" in name or "olivenöl" in name.lower() for name in flat)


def test_kein_removes_from_assumed():
    results = analyze_text("Sushi kein Sojasauce")
    r = results[0]
    assumed_names = r.debug.get("assumed_items", [])
    assert "Sojasauce" not in assumed_names
