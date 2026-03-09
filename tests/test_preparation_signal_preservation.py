"""
Focused PR2 tests for preserving preparation signals in analyzer parsing.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from trennkost.analyzer import _parse_text_input
from trennkost.models import ModifierTag
from trennkost.normalizer import normalize_dish


def test_question_parser_preserves_fried_signal_for_modifier_path():
    parsed = _parse_text_input("Ist frittiertes Hähnchen ok?")

    assert parsed[0]["items"] == ["frittiertes hähnchen"]
    analysis = normalize_dish(parsed[0]["name"], parsed[0]["items"])
    assert analysis.items[0].canonical == "Hähnchen"
    assert analysis.items[0].recognized_modifiers == [ModifierTag.PREP_FRIED]


def test_question_parser_preserves_cooked_signal_without_collapsing_to_plain_item():
    parsed = _parse_text_input("Sind gekochte Kartoffeln ok?")

    assert parsed[0]["items"] == ["gekochte kartoffeln"]
    analysis = normalize_dish(parsed[0]["name"], parsed[0]["items"])
    canonicals = {item.canonical for item in analysis.items}
    assert "Kartoffel gekocht" in canonicals
    assert "Kartoffel" not in canonicals


def test_question_parser_preserves_grilled_signal_even_if_downstream_mapping_is_limited():
    parsed = _parse_text_input("Ist gegrilltes Hähnchen ok?")

    assert parsed[0]["items"] == ["gegrilltes hähnchen"]
    analysis = normalize_dish(parsed[0]["name"], parsed[0]["items"])
    assert analysis.items[0].raw_name == "gegrilltes hähnchen"
