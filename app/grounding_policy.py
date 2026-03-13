"""Central grounding/fallback policy for runtime and prompt usage."""
from dataclasses import dataclass
from typing import Optional, List

from app.chat_modes import ChatMode
from trennkost.models import TrennkostResult


FALLBACK_SENTENCE = "Diese Information steht nicht im bereitgestellten Kursmaterial."
REASON_NO_SNIPPETS = "no_snippets"
_NO_SNIPPET_UI_EXCEPTIONS = {"need", "plan"}


@dataclass(frozen=True)
class GroundingDecision:
    should_fallback: bool
    reason_code: Optional[str] = None


def evaluate_grounding_policy(
    trennkost_results: Optional[List[TrennkostResult]],
    mode: ChatMode,
    best_dist: float,
    is_partial: bool,
    course_context: str,
    ui_intent: Optional[str],
    distance_threshold: float,
) -> GroundingDecision:
    """Evaluate whether runtime should return the canonical fallback sentence."""
    if trennkost_results:
        return GroundingDecision(should_fallback=False)

    if mode == ChatMode.RECIPE_REQUEST:
        return GroundingDecision(should_fallback=False)

    no_snippets = (best_dist > distance_threshold and not is_partial) or (not course_context.strip())
    if not no_snippets:
        return GroundingDecision(should_fallback=False)

    if ui_intent in _NO_SNIPPET_UI_EXCEPTIONS:
        return GroundingDecision(should_fallback=False)

    return GroundingDecision(should_fallback=True, reason_code=REASON_NO_SNIPPETS)


def should_emit_fallback_sentence(decision: GroundingDecision) -> bool:
    """Return whether runtime should emit the canonical fallback sentence."""
    return decision.should_fallback
