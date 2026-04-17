"""
Deterministic menu recommendation ordering tests (PR5).
"""
from app.prompt_builder import _rank_menu_results, build_menu_injection
from trennkost.models import RequiredQuestion, TrafficLight, TrennkostResult, Verdict


def _make_result(
    dish_name: str,
    verdict: Verdict,
    traffic_light: TrafficLight,
    needs_clarification: bool = False,
) -> TrennkostResult:
    questions = []
    if needs_clarification:
        questions = [
            RequiredQuestion(
                question="Wie viel Öl ist enthalten?",
                reason="Mengenabhängig",
                affects_items=["Öl"],
            )
        ]

    return TrennkostResult(
        dish_name=dish_name,
        verdict=verdict,
        traffic_light=traffic_light,
        summary="Test",
        required_questions=questions,
    )


def _line(parts: list[str], prefix: str) -> str:
    return next(p for p in parts if p.startswith(prefix))


def test_menu_order_uses_traffic_light_within_same_verdict():
    parts = build_menu_injection(
        [
            _make_result("Red Curry", Verdict.OK, TrafficLight.RED),
            _make_result("Green Salad", Verdict.OK, TrafficLight.GREEN),
        ]
    )

    ok_line = _line(parts, "OK Konforme Gerichte:")
    assert ok_line.index("Green Salad") < ok_line.index("Red Curry")


def test_menu_order_prefers_no_clarification_within_same_verdict_and_traffic_light():
    parts = build_menu_injection(
        [
            _make_result("Oil Plate", Verdict.CONDITIONAL, TrafficLight.YELLOW, needs_clarification=True),
            _make_result("Plain Plate", Verdict.CONDITIONAL, TrafficLight.YELLOW, needs_clarification=False),
        ]
    )

    cond_line = _line(parts, "Bedingt konforme Gerichte:")
    assert cond_line.index("Plain Plate") < cond_line.index("Oil Plate")


def test_menu_order_keeps_verdict_as_primary_dimension():
    ranked = _rank_menu_results(
        [
            _make_result("Conditional Green", Verdict.CONDITIONAL, TrafficLight.GREEN),
            _make_result("Ok Red", Verdict.OK, TrafficLight.RED),
        ]
    )

    assert ranked[0].verdict == Verdict.OK
    assert ranked[1].verdict == Verdict.CONDITIONAL
