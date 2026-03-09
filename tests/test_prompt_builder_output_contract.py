"""
Contract tests for prompt builder verdict wording rules (PR1).
"""
from app.prompt_builder import build_prompt_food_analysis
from trennkost.models import RequiredQuestion, TrennkostResult, Verdict


def _make_result(verdict: Verdict) -> TrennkostResult:
    return TrennkostResult(
        dish_name="Testgericht",
        verdict=verdict,
        strict_verdict=verdict,
        active_mode_verdict=verdict,
        summary="Deterministisch bewertet.",
        required_questions=[
            RequiredQuestion(
                question="Ist zusätzlich Öl enthalten?",
                reason="Klärung nötig",
                affects_items=["Öl"],
            )
        ],
        groups_found={"KH": ["Reis"], "FETT": ["Öl"]},
    )


def test_prompt_builder_keeps_verdict_immutable_without_exact_legacy_wording_instruction():
    prompt = build_prompt_food_analysis(
        trennkost_results=[_make_result(Verdict.NOT_OK)],
        user_message="Ist das konform?",
    )
    lowered = prompt.lower()

    assert "verdict" in lowered
    assert "deterministisch" in lowered
    assert "darf nicht" in lowered
    assert "Gib dies EXAKT so wieder" not in prompt
    assert "Bei 'NICHT OK':" not in prompt


def test_prompt_builder_separates_clarification_from_legacy_verdict_labels():
    prompt = build_prompt_food_analysis(
        trennkost_results=[_make_result(Verdict.CONDITIONAL)],
        user_message="Wie sieht das aus?",
    )
    lowered = prompt.lower()

    assert "verdict" in lowered
    assert "offene fragen" in lowered
    assert "stelle die offene frage" in lowered
    assert "nur dann 'bedingt' sagen" not in lowered
    assert "bei 'bedingt ok'" not in lowered
