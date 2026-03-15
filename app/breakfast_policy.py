"""Canonical breakfast policy shared across prompt builders."""
from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class BreakfastPolicy:
    stage_one: str
    stage_one_timing_short: str
    stage_one_timing_detailed: str
    stage_two: str
    stage_two_examples: Tuple[str, ...]
    morning_fat_rationale: Tuple[str, ...]
    proactive_instruction: str


BREAKFAST_POLICY = BreakfastPolicy(
    stage_one="Frisches Obst ODER Grüner Smoothie (fettfrei)",
    stage_one_timing_short="Obst verdaut in 20-30 Min, dann 2. Frühstück möglich",
    stage_one_timing_detailed="Obst verdaut in 20-30 Min, Bananen/Trockenobst 45-60 Min",
    stage_two="Fettfreie Kohlenhydrate (max 1-2 TL Fett)",
    stage_two_examples=(
        "Overnight-Oats",
        "Porridge",
        "Reis-Pudding",
        "Hirse-Grieß",
        "glutenfreies Brot mit Gurke/Tomate + max 1-2 TL Avocado",
    ),
    morning_fat_rationale=(
        "Bis mittags läuft die Entgiftung des Körpers auf Hochtouren.",
        "Leichte Kost spart Verdauungsenergie → mehr Energie für Entgiftung/Entschlackung.",
        "Fettreiche Lebensmittel belasten die Verdauung und behindern diesen Prozess.",
    ),
    proactive_instruction="Empfehle IMMER zuerst die fettarme Option (Obst/Smoothie, dann ggf. fettfreie KH).",
)


def _examples_block_lines() -> Tuple[str, str]:
    primary = ", ".join(BREAKFAST_POLICY.stage_two_examples[:-1]) + ","
    tail = BREAKFAST_POLICY.stage_two_examples[-1]
    return primary, tail


def _examples_inline() -> str:
    return ", ".join(BREAKFAST_POLICY.stage_two_examples)


def build_breakfast_block_lines() -> List[str]:
    """Standalone breakfast guidance when no engine results are available."""
    examples_primary, examples_tail = _examples_block_lines()
    return [
        "FRÜHSTÜCKS-HINWEIS (Kurs Modul 1.2):",
        "Das Kursmaterial empfiehlt ein zweistufiges Frühstück:",
        f"  1. Frühstück: {BREAKFAST_POLICY.stage_one}",
        f"     → {BREAKFAST_POLICY.stage_one_timing_detailed}",
        f"  2. Frühstück (falls 1. nicht reicht): {BREAKFAST_POLICY.stage_two}",
        f"     → Empfehlungen: {examples_primary}",
        f"       {examples_tail}",
        "",
        "WARUM FETTARM VOR MITTAGS?",
        f"  {BREAKFAST_POLICY.morning_fat_rationale[0]}",
        f"  {BREAKFAST_POLICY.morning_fat_rationale[1]}",
        f"  {BREAKFAST_POLICY.morning_fat_rationale[2]}",
        "",
        "ANWEISUNG: Erwähne das zweistufige Frühstücks-Konzept PROAKTIV in deiner Antwort!",
        BREAKFAST_POLICY.proactive_instruction,
        "",
    ]


def build_breakfast_knowledge_instruction() -> str:
    """Breakfast instruction snippet for generic knowledge prompt mode."""
    return (
        "- FRÜHSTÜCK-SPEZIFISCH (User fragt nach Frühstück!):\n"
        "  Das Kursmaterial empfiehlt ein zweistufiges Frühstück:\n"
        f"  1. Frühstück: {BREAKFAST_POLICY.stage_one}\n"
        f"     → {BREAKFAST_POLICY.stage_one_timing_short}\n"
        f"  2. Frühstück: {BREAKFAST_POLICY.stage_two}\n"
        f"     → {_examples_inline()}\n"
        f"  WARUM: {BREAKFAST_POLICY.morning_fat_rationale[0]}\n"
        "  → Empfehle IMMER zuerst die fettarme Option. Bei Insistieren: erlaubt, aber mit Hinweis.\n"
    )
