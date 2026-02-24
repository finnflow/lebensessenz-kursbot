"""
Trennkost result formatters.

Transforms TrennkostResult objects into text for LLM context and RAG queries.
"""
from typing import List

from trennkost.models import TrennkostResult, Verdict


_GROUP_DISPLAY = {
    "KH": "Kohlenhydrate",
    "PROTEIN": "Protein",
    "MILCH": "Milchprodukte",
    "HUELSENFRUECHTE": "Hülsenfrüchte",
    "OBST": "Obst",
    "FETT": "Fette",
    "TROCKENOBST": "Trockenobst",
}


def _generate_fix_directions(result: TrennkostResult) -> List[str]:
    """
    Generate deterministic fix-direction suggestions for NOT_OK dishes.

    For each conflicting group, suggests keeping it and replacing the others
    with stärkearmes Gemüse/Salat.
    """
    if result.verdict != Verdict.NOT_OK:
        return []

    conflicting_groups = set()
    for p in result.problems:
        conflicting_groups.update(p.affected_groups)

    conflicting_groups.discard("NEUTRAL")
    conflicting_groups.discard("UNKNOWN")

    if len(conflicting_groups) < 2:
        return []

    directions = []
    for keep_group in sorted(conflicting_groups):
        keep_items = result.groups_found.get(keep_group, [])
        if not keep_items:
            continue

        keep_display = _GROUP_DISPLAY.get(keep_group, keep_group)
        clean = lambda items: ", ".join(i.split(" → ")[0] for i in items)
        keep_items_str = clean(keep_items)
        replace_str = ", ".join(clean(result.groups_found.get(g, [])) for g in sorted(conflicting_groups) if g != keep_group and result.groups_found.get(g))
        forbidden_displays = [_GROUP_DISPLAY.get(g, g) for g in sorted(conflicting_groups) if g != keep_group]

        directions.append(
            f"Behalte {keep_display} ({keep_items_str}) "
            f"→ ersetze {replace_str} durch stärkearmes Gemüse/Salat. "
            f"WICHTIG: Kein(e) {', '.join(forbidden_displays)} im Alternativgericht!"
        )

    return directions


def _generate_breakfast_block(result: TrennkostResult) -> List[str]:
    """
    Generate breakfast-specific guidance block.

    Based on Modul 1.2 Seite 1-2:
    - Two-stage breakfast concept
    - Fat-free/fat-low recommendation before noon
    - Detoxification reasoning
    """
    lines = []
    lines.append("FRÜHSTÜCKS-HINWEIS (Kurs Modul 1.2):")
    lines.append("Das Kursmaterial empfiehlt ein zweistufiges Frühstück:")
    lines.append("  1. Frühstück: Frisches Obst ODER Grüner Smoothie (fettfrei)")
    lines.append("     → Obst verdaut in 20-30 Min, Bananen/Trockenobst 45-60 Min")
    lines.append("  2. Frühstück (falls 1. nicht reicht): Fettfreie Kohlenhydrate (max 1-2 TL Fett)")
    lines.append("     → Empfehlungen: Overnight-Oats, Porridge, Reis-Pudding, Hirse-Grieß,")
    lines.append("       glutenfreies Brot mit Gurke/Tomate + max 1-2 TL Avocado")
    lines.append("")
    lines.append("WARUM FETTARM VOR MITTAGS?")
    lines.append("  Bis mittags läuft die Entgiftung des Körpers auf Hochtouren.")
    lines.append("  Leichte Kost spart Verdauungsenergie → mehr Energie für Entgiftung/Entschlackung.")
    lines.append("  Fettreiche Lebensmittel belasten die Verdauung und behindern diesen Prozess.")

    fat_rich_groups = {"FETT", "MILCH", "PROTEIN"}
    fat_items = []
    for group in sorted(fat_rich_groups):
        for item in result.groups_found.get(group, []):
            clean_name = item.split(" → ")[0]
            fat_items.append(f"{clean_name} ({_GROUP_DISPLAY.get(group, group)})")

    if fat_items:
        lines.append("")
        lines.append(f"FETTREICHE ITEMS IN DIESER MAHLZEIT: {', '.join(fat_items)}")
        lines.append("→ Empfehle dem User ZUERST fettarme Frühstücks-Alternativen (Obst, Haferflocken, Gemüse-Sticks).")
        lines.append("→ Falls der User darauf besteht: gewählte Komponente + Gemüse ist erlaubt, aber mit Hinweis.")

    return lines


def format_results_for_llm(results: List[TrennkostResult], breakfast_context: bool = False) -> str:
    """
    Format TrennkostResult(s) as structured text for the LLM context.

    The LLM must NOT change the verdict — only explain it from course material.
    """
    parts = []
    parts.append("═══ TRENNKOST-ANALYSE (DETERMINISTISCH) ═══")
    parts.append("WICHTIG: Das Verdict wurde regelbasiert ermittelt und darf NICHT verändert werden.")
    parts.append("Deine Aufgabe: Erkläre das Ergebnis anhand der Kurs-Snippets.")

    has_no_questions = any(not r.required_questions for r in results)
    if has_no_questions:
        parts.append("⚠️ KRITISCH: Alle Zutaten sind explizit genannt und bestätigt. Stelle KEINE Rückfragen zu Zutaten!")
    parts.append("")

    for r in results:
        verdict_emoji = {
            Verdict.OK: "OK",
            Verdict.NOT_OK: "NICHT OK",
            Verdict.CONDITIONAL: "BEDINGT",
            Verdict.UNKNOWN: "UNKLAR",
        }

        parts.append(f"── {r.dish_name} ──")
        parts.append(f"Verdict: {verdict_emoji.get(r.verdict, r.verdict.value)}")
        parts.append(f"Zusammenfassung: {r.summary}")

        if r.groups_found:
            group_strs = []
            for g, items in r.groups_found.items():
                if g != "UNKNOWN":
                    group_strs.append(f"  {g}: {', '.join(items)}")
            if group_strs:
                parts.append("Gruppen:")
                parts.extend(group_strs)

        if r.problems:
            parts.append("Probleme:")
            for p in r.problems:
                parts.append(f"  [{p.rule_id}] {p.description}")
                parts.append(f"    Betrifft: {', '.join(p.affected_items)}")
                parts.append(f"    Erklärung: {p.explanation}")
                if p.source_ref:
                    parts.append(f"    Quelle: {p.source_ref}")

        if r.required_questions:
            parts.append("Offene Fragen (bitte an den User weitergeben):")
            for q in r.required_questions:
                parts.append(f"  → {q.question}")
                if q.reason:
                    parts.append(f"     Grund: {q.reason}")
        else:
            parts.append("KEINE OFFENEN FRAGEN — alle Zutaten sind klar und bestätigt.")

        if r.ok_combinations:
            parts.append("OK-Kombinationen: " + "; ".join(r.ok_combinations))

        fix_dirs = _generate_fix_directions(r)
        if fix_dirs:
            parts.append("TRENNKOST-KONFORME ALTERNATIVEN (frage den User):")
            for i, d in enumerate(fix_dirs, 1):
                parts.append(f"  Richtung {i}: {d}")
            parts.append("  → Frage den User, welche Komponente er behalten möchte.")

        if breakfast_context:
            parts.append("")
            parts.extend(_generate_breakfast_block(r))

        parts.append("")

    parts.append("═══ ENDE TRENNKOST-ANALYSE ═══")
    return "\n".join(parts)


def build_rag_query(results: List[TrennkostResult], breakfast_context: bool = False) -> str:
    """
    Build a RAG query from TrennkostResult(s) targeting relevant course sections.
    """
    query_parts = ["Lebensmittelkombinationen Trennkost Regeln"]

    if breakfast_context:
        query_parts.append("Frühstück optimal fettfrei fettarm Obst Smoothie Entgiftung zweistufig Overnight-Oats Porridge")

    groups_mentioned = set()
    for r in results:
        for g in r.groups_found:
            groups_mentioned.add(g)
        for p in r.problems:
            groups_mentioned.update(p.affected_groups)

    group_terms = {
        "KH": "Kohlenhydrate Getreide stärkehaltiges Gemüse",
        "PROTEIN": "Proteine Fleisch Fisch Eier",
        "MILCH": "Milchprodukte Käse sauer verstoffwechselt",
        "HUELSENFRUECHTE": "Hülsenfrüchte schwer verdaulich",
        "OBST": "Obst allein nüchterner Magen Verdauung schnell",
        "FETT": "Fette kleine Mengen Öle",
        "NEUTRAL": "stärkearmes Gemüse Salat neutral kombinierbar",
    }

    for g in groups_mentioned:
        if g in group_terms:
            query_parts.append(group_terms[g])

    for r in results:
        for p in r.problems:
            if "milieu" in p.explanation.lower() or "verdauungssäfte" in p.explanation.lower():
                query_parts.append("verschiedene Milieus Verdauung sauer basisch neutralisieren")
            if "gärung" in p.explanation.lower() or "fäulnis" in p.explanation.lower():
                query_parts.append("Gärung Fäulnis Obst Fermentation")

    return " ".join(query_parts)
