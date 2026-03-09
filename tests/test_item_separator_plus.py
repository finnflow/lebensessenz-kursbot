"""
Focused parser tests for '+' as item separator in text input.
"""
import pytest

from trennkost.analyzer import _parse_text_input


@pytest.mark.parametrize(
    ("text", "expected_items"),
    [
        ("Reis + Hähnchen", ["Reis", "Hähnchen"]),
        ("Pommes + Mayo", ["Pommes", "Mayo"]),
        ("Banane + Nüsse", ["Banane", "Nüsse"]),
        ("Bratkartoffeln + Ei", ["Bratkartoffeln", "Ei"]),
    ],
)
def test_plus_separator_splits_items(text, expected_items):
    parsed = _parse_text_input(text)

    assert len(parsed) == 1
    assert parsed[0]["items"] == expected_items


def test_existing_ampersand_separator_still_splits_items():
    parsed = _parse_text_input("Reis & Hähnchen")

    assert len(parsed) == 1
    assert parsed[0]["items"] == ["Reis", "Hähnchen"]
