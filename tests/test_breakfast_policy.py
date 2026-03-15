"""Regression tests for centralized breakfast prompt policy."""
from app.breakfast_policy import BREAKFAST_POLICY
from app.prompt_builder import build_breakfast_block, build_prompt_knowledge


def test_breakfast_block_keeps_two_stage_concept():
    block = build_breakfast_block()
    block_text = "\n".join(block)

    assert "zweistufiges Frühstück" in block_text
    assert BREAKFAST_POLICY.stage_one in block_text
    assert BREAKFAST_POLICY.stage_two in block_text
    assert "WARUM FETTARM VOR MITTAGS?" in block_text


def test_breakfast_knowledge_prompt_uses_canonical_policy():
    prompt = build_prompt_knowledge("Was ist ein gutes Frühstück?", is_breakfast=True)

    assert BREAKFAST_POLICY.stage_one in prompt
    assert BREAKFAST_POLICY.stage_two in prompt
    assert BREAKFAST_POLICY.stage_two_examples[0] in prompt
    assert BREAKFAST_POLICY.morning_fat_rationale[0] in prompt


def test_non_breakfast_knowledge_prompt_stays_without_breakfast_section():
    prompt = build_prompt_knowledge("Was ist Trennkost?", is_breakfast=False)

    assert "- FRÜHSTÜCK-SPEZIFISCH" not in prompt
    assert "- PROAKTIV HANDELN: Lieber einen konkreten Vorschlag machen als weitere Fragen stellen." in prompt


def test_breakfast_block_and_knowledge_prompt_share_core_breakfast_content():
    block_text = "\n".join(build_breakfast_block())
    prompt = build_prompt_knowledge("Frühstücksidee?", is_breakfast=True)

    shared_snippets = [
        BREAKFAST_POLICY.stage_one,
        BREAKFAST_POLICY.stage_two,
        BREAKFAST_POLICY.stage_two_examples[0],
        BREAKFAST_POLICY.stage_two_examples[1],
        BREAKFAST_POLICY.morning_fat_rationale[0],
    ]
    for snippet in shared_snippets:
        assert snippet in block_text
        assert snippet in prompt
