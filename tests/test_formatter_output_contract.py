"""
Contract tests for formatter output shaping (PR1).
"""
import re

from trennkost.formatter import format_results_for_llm
from trennkost.models import (
    GuidanceFact,
    ItemRiskFact,
    RequiredQuestion,
    RiskSeverity,
    TrafficLight,
    TrennkostResult,
    Verdict,
)


def _make_result(verdict: Verdict) -> TrennkostResult:
    return TrennkostResult(
        dish_name="Testgericht",
        verdict=verdict,
        traffic_light=TrafficLight.RED,
        summary="Deterministisches Ergebnis.",
        required_questions=[
            RequiredQuestion(
                question="Wie viel Öl ist enthalten?",
                reason="Mengenabhängige Guidance",
                affects_items=["Olivenöl"],
            )
        ],
        risk_codes=["HEAVY_FAT_LOAD"],
        risk_facts=[
            ItemRiskFact(
                item="Olivenöl",
                risk_code="HEAVY_FAT_LOAD",
                severity=RiskSeverity.RED,
            )
        ],
        guidance_codes=["FAT_WITH_CONFLICT_GROUP_TINY_AMOUNT"],
        guidance_facts=[
            GuidanceFact(
                code="FAT_WITH_CONFLICT_GROUP_TINY_AMOUNT",
                affected_groups=["FETT", "KH"],
                affected_items=["Olivenöl", "Reis"],
                amount_hint="Maximal 1-2 TL",
            )
        ],
        groups_found={"KH": ["Reis"], "FETT": ["Olivenöl"]},
    )


def test_formatter_keeps_deterministic_verdict_without_legacy_mandatory_label():
    formatted = format_results_for_llm([_make_result(Verdict.NOT_OK)])

    assert "Verdict:" in formatted
    assert "NOT_OK" in formatted
    assert "Verdict: NICHT OK" not in formatted
    assert "BEDINGT OK" not in formatted


def test_formatter_exposes_separate_required_questions_guidance_and_traffic_light_blocks():
    formatted = format_results_for_llm([_make_result(Verdict.CONDITIONAL)])

    assert re.search(r"(?im)^\s*(traffic light|ampel)\s*:", formatted)
    assert "RED" in formatted
    assert "Offene Fragen" in formatted
    assert "Wie viel Öl ist enthalten?" in formatted
    assert re.search(r"(?im)^\s*(guidance|hinweis(?:e)?)\s*:", formatted)
    assert "Maximal 1-2 TL" in formatted
