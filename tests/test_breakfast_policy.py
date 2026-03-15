"""Regression tests for centralized breakfast prompt policy."""
from app.breakfast_policy import BREAKFAST_POLICY, build_breakfast_recipe_instruction
from app.prompt_builder import (
    _breakfast_section,
    build_breakfast_block,
    build_prompt_knowledge,
    build_prompt_recipe_request,
)


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


def test_food_analysis_breakfast_section_uses_same_canonical_core_content():
    section = _breakfast_section(is_breakfast=True, has_obst_kh=False)

    assert BREAKFAST_POLICY.stage_one in section
    assert BREAKFAST_POLICY.stage_two in section
    assert BREAKFAST_POLICY.stage_two_examples[0] in section
    assert BREAKFAST_POLICY.morning_fat_rationale_short in section


def test_food_analysis_obst_kh_section_stays_as_special_case_of_same_policy():
    section = _breakfast_section(is_breakfast=False, has_obst_kh=True)

    assert "OBST+KH KONFLIKT ERKANNT" in section
    assert BREAKFAST_POLICY.stage_two in section
    assert BREAKFAST_POLICY.obst_kh_wait_rule_hint in section


def test_food_analysis_non_breakfast_path_stays_empty():
    assert _breakfast_section(is_breakfast=False, has_obst_kh=False) == ""


def test_recipe_prompt_breakfast_hint_uses_canonical_policy():
    prompt = build_prompt_recipe_request([], "Frühstücksrezept?", is_breakfast=True)

    assert build_breakfast_recipe_instruction().strip() in prompt
