"""
High-level Trennkost analyzer.

Orchestrates: text/vision input → normalizer → engine → formatted output.
This is the single entry point for all Trennkost analysis.
"""
import re
import json
import logging
from typing import List, Optional, Callable, Dict, Any

from trennkost.models import (
    FoodGroup,
    FoodSubgroup,
    Verdict,
    Severity,
    FoodItem,
    DishAnalysis,
    TrennkostResult,
)
from trennkost.ontology import get_ontology
from trennkost.normalizer import normalize_dish
from trennkost.engine import evaluate_dish

logger = logging.getLogger(__name__)

# ── Detection ──────────────────────────────────────────────────────────

# Keywords indicating a food combination / Trennkost question
_FOOD_QUERY_KEYWORDS = [
    "kombinieren", "kombination", "zusammen essen", "zusammen ok",
    "trennkost", "erlaubt", "darf ich", "kann ich.*essen",
    "ist.*ok", "passt.*zusammen", "speisekarte", "menü",
    "gericht", "mahlzeit", "teller",
]
_FOOD_QUERY_RE = re.compile(
    "|".join(_FOOD_QUERY_KEYWORDS), re.IGNORECASE
)

# Common adjectives to ignore (not food items)
_ADJECTIVES_TO_IGNORE = {
    "normaler", "normale", "normales", "normal",
    "frischer", "frische", "frisches", "frisch",
    "roher", "rohe", "rohes", "roh",
    "gekochter", "gekochte", "gekochtes", "gekocht",
    "gebratener", "gebratene", "gebratenes", "gebraten",
    "gegrillter", "gegrillte", "gegrilltes", "gegrillt",
    "gedünsteter", "gedünstete", "gedünstetes", "gedünstet",
    "geschmorter", "geschmorte", "geschmortes", "geschmort",
    "gebackener", "gebackene", "gebackenes", "gebacken",
    "veganer", "vegane", "veganes", "vegan",
    "vegetarischer", "vegetarische", "vegetarisches", "vegetarisch",
    "glutenfreier", "glutenfreie", "glutenfreies", "glutenfrei",
    "laktosefreier", "laktosefreie", "laktosefreies", "laktosefrei",
    "biologischer", "biologische", "biologisches", "bio",
    "kleiner", "kleine", "kleines", "klein",
    "großer", "große", "großes", "groß",
    "ganzer", "ganze", "ganzes", "ganz",
    "halber", "halbe", "halbes", "halb",
}

# Separators for ingredient lists
_ITEM_SEPARATORS = re.compile(r"[,;]\s*|\s+und\s+|\s+mit\s+|\s+&\s+", re.IGNORECASE)

# Breakfast detection keywords
_BREAKFAST_KEYWORDS = re.compile(
    r"frühstück|fruehstueck|morgens|vormittag|zum\s*frühstück|breakfast"
    r"|morgenessen|am\s*morgen|in\s*der\s*früh|in\s*der\s*frueh",
    re.IGNORECASE,
)


def detect_breakfast_context(text: str) -> bool:
    """Detect if a user message is about breakfast / morning eating."""
    return bool(_BREAKFAST_KEYWORDS.search(text))


def detect_food_query(text: str) -> bool:
    """
    Detect if a user message is a food combination analysis question.

    Returns True if:
    - Text contains food-related keywords, OR
    - Text contains 2+ food items from the ontology

    Returns False if:
    - User is asking FOR a recipe/suggestion (not analyzing a specific dish)
    """
    # Exclude recipe requests (user wants suggestions, not analysis)
    recipe_request_patterns = [
        r"hast du.*gericht",
        r"gib.*gericht",
        r"kannst du.*gericht.*vorschlag",
        r"schlage.*gericht.*vor",
        r"empfiehl.*gericht",
        r"idee.*für.*gericht",
        r"rezept.*für.*heute",
        r"was.*soll.*ich.*essen",
        r"was.*kann.*ich.*essen",
        r"was.*darf.*ich.*essen",
        r"was.*könnte.*ich.*essen",
        r"was.*wäre.*eine.*gute.*option",
        r"gute.*option.*für",
        r"vorschlag.*für.*(frühstück|mittagessen|abendessen)",
    ]
    for pattern in recipe_request_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return False

    if _FOOD_QUERY_RE.search(text):
        return True

    # Check for known compound dishes (single item but should be analyzed)
    ontology = get_ontology()
    text_lower = text.lower()
    for compound_name in ontology.compounds.keys():
        if compound_name.lower() in text_lower:
            return True

    # Check for multiple food items
    words = _ITEM_SEPARATORS.split(text.strip())
    found = sum(1 for w in words if w.strip() and ontology.lookup(w.strip()))
    return found >= 2


# ── Text Parsing ───────────────────────────────────────────────────────

def _extract_foods_from_question(text: str) -> Optional[List[Dict[str, Any]]]:
    """
    Extract food items from a natural language question.

    Searches for known compound dishes and individual ontology items
    embedded in the text. Returns None if nothing found.
    """
    ontology = get_ontology()
    text_lower = text.lower()

    # 1. Check for known compound dishes (longest first to avoid partial matches)
    found_compound = None
    search_text = text_lower  # Use this for subsequent searches
    for compound_name in sorted(ontology.compounds.keys(), key=len, reverse=True):
        if compound_name.lower() in text_lower:
            found_compound = compound_name
            # Remove matched name to avoid double-matching ingredients
            search_text = text_lower.replace(compound_name.lower(), " ")
            break  # Only match one compound per query

    # 2. Check for individual food items from ontology (even if compound found!)
    found_items = []
    seen = set()
    for entry in ontology.entries:
        # Check canonical and synonyms against the text
        names_to_check = [entry.canonical] + entry.synonyms
        for name in names_to_check:
            if len(name) < 3:
                continue
            # Word boundary match to avoid "Reis" matching "Reise"
            # Include quotes (") and apostrophes (') in boundaries
            pattern = r'(?:^|[\s,;.("\'])' + re.escape(name) + r'(?:[\s,;.?!)"\'"]|$)'
            # Use search_text (with compound removed) instead of original text
            if re.search(pattern, search_text, re.IGNORECASE) and entry.canonical not in seen:
                found_items.append(entry.canonical)
                seen.add(entry.canonical)
                break

    # Filter out adjectives that are not food items
    found_items = [item for item in found_items if item.lower() not in _ADJECTIVES_TO_IGNORE]

    # 3. Combine results: compound + explicit ingredients if both found
    if found_compound and found_items:
        # User mentioned a compound dish AND explicit ingredients
        # e.g., "Burger mit Tempeh, Salat, Gurken"
        return [{"name": found_compound, "items": found_items}]
    elif found_compound:
        # Only compound found, no explicit ingredients
        return [{"name": found_compound, "items": None}]
    elif len(found_items) >= 1:
        # No compound, but individual items found
        return [{"name": _infer_dish_name(found_items) if len(found_items) > 1 else found_items[0],
                 "items": found_items if len(found_items) > 1 else None}]

    return None


def _parse_text_input(text: str) -> List[Dict[str, Any]]:
    """
    Parse text input into dish(es) with ingredients.

    Handles:
    - Natural language questions: "Ist Spaghetti Carbonara ok?" → compound lookup
    - "Reis, Hähnchen, Brokkoli" → single dish with 3 ingredients
    - "Spaghetti Carbonara" → compound dish lookup
    - "1. Carbonara  2. Pizza" or newline-separated → multiple dishes

    Returns list of {"name": str, "items": list[str] | None}
    """
    text = text.strip()
    ontology = get_ontology()

    # If text looks like a natural language question, extract food items first
    is_question = bool(re.search(r'\?', text)) or bool(
        re.match(r'(?i)(ist|kann|darf|sind|passt|was|wie|wäre|würde)\s', text)
    )
    if is_question:
        extracted = _extract_foods_from_question(text)
        if extracted:
            return extracted

    # Check for numbered/newline-separated dishes
    lines = [l.strip() for l in re.split(r"\n|(?:\d+[\.\)]\s*)", text) if l.strip()]

    dishes = []
    for line in lines:
        # Check if line is a known compound
        compound = ontology.get_compound(line)
        if compound:
            dishes.append({"name": line, "items": None})  # compound lookup handles it
            continue

        # Split into potential ingredients
        parts = _ITEM_SEPARATORS.split(line)
        parts = [p.strip() for p in parts if p.strip()]

        # Filter out adjectives (e.g., "normaler", "frischer") - not food items
        parts = [p for p in parts if p.lower() not in _ADJECTIVES_TO_IGNORE]

        if len(parts) >= 2:
            # Check if first part is a compound dish name
            first_part_compound = ontology.get_compound(parts[0])
            if first_part_compound:
                # First part is the dish name, rest are explicit ingredients
                dish_name = parts[0]
                ingredients = parts[1:]  # Explicit ingredients provided by user
                dishes.append({"name": dish_name, "items": ingredients})
            else:
                # Multiple items → treat as ingredient list
                # But first check if the whole thing is a dish name
                whole_compound = ontology.get_compound(line)
                if whole_compound:
                    dishes.append({"name": line, "items": None})
                else:
                    name = _infer_dish_name(parts)
                    dishes.append({"name": name, "items": parts})
        elif len(parts) == 1:
            # Single item → could be a dish name
            dishes.append({"name": parts[0], "items": None})

    return dishes if dishes else [{"name": text, "items": None}]


def _infer_dish_name(items: List[str]) -> str:
    """Create a dish name from an ingredient list."""
    if len(items) <= 3:
        return " + ".join(items)
    return f"{items[0]} + {items[1]} + {len(items) - 2} weitere"


# ── Core Analysis ──────────────────────────────────────────────────────

def analyze_text(
    text: str,
    llm_fn: Optional[Callable] = None,
    mode: str = "strict",
) -> List[TrennkostResult]:
    """
    Analyze food items from text input.

    Args:
        text: User input (ingredient list, dish name, or menu text)
        llm_fn: Optional LLM callable for unknown item classification
        mode: "strict" = only explicit ingredients, "assumption" = include assumed

    Returns:
        List of TrennkostResult (one per dish)
    """
    parsed = _parse_text_input(text)
    results = []

    for dish_info in parsed:
        dish_name = dish_info["name"]
        raw_items = dish_info["items"]

        # Normalize through the pipeline
        analysis = normalize_dish(
            dish_name=dish_name,
            raw_items=raw_items,
            llm_fn=llm_fn,
        )

        # In strict mode, remove assumed items from the analysis
        if mode == "strict" and analysis.assumed_items:
            # Keep assumed items only for generating questions, not for verdict
            strict_analysis = DishAnalysis(
                dish_name=analysis.dish_name,
                items=analysis.items,
                unknown_items=analysis.unknown_items,
                assumed_items=[],  # Don't include in verdict
            )
            result = evaluate_dish(strict_analysis)
            # But still mention assumed items as questions
            from trennkost.models import RequiredQuestion
            assumed_names = [it.raw_name for it in analysis.assumed_items]
            assumed_groups = [f"{it.raw_name} ({it.group.value})" for it in analysis.assumed_items]
            if assumed_names:
                # Different message depending on current verdict
                if result.verdict == Verdict.NOT_OK:
                    # Bei NOT_OK: Assumed items verstärken nur die Problematik, keine Frage nötig
                    # Skip adding this to required_questions
                    pass
                else:
                    question_text = (
                        f"Typische weitere Zutaten in {dish_name}: "
                        f"{', '.join(assumed_groups)}. "
                        f"Sind diese enthalten? Das könnte die Bewertung ändern."
                    )
                    result.required_questions.append(RequiredQuestion(
                        question=question_text,
                        reason="Vermutete Zutaten könnten die Kombination beeinflussen.",
                        affects_items=assumed_names,
                    ))
                # If strict result was OK but assumed items would change it,
                # escalate to CONDITIONAL
                if result.verdict == Verdict.OK and assumed_names:
                    assumption_analysis = DishAnalysis(
                        dish_name=analysis.dish_name,
                        items=analysis.items + analysis.assumed_items,
                        unknown_items=analysis.unknown_items,
                        assumed_items=analysis.assumed_items,
                    )
                    assumption_result = evaluate_dish(assumption_analysis)
                    if assumption_result.verdict == Verdict.NOT_OK:
                        result.verdict = Verdict.CONDITIONAL
                        result.summary = (
                            f"{dish_name}: Bedingt OK — "
                            f"mit typischen Zusatz-Zutaten wäre es NOT_OK."
                        )
        else:
            result = evaluate_dish(analysis)

        results.append(result)

    return results


def analyze_vision(
    vision_dishes: List[Dict[str, Any]],
    llm_fn: Optional[Callable] = None,
    mode: str = "strict",
) -> List[TrennkostResult]:
    """
    Analyze dishes extracted from a vision API response.

    Args:
        vision_dishes: List of {"name": str, "items": [str], "uncertain_items": [str]}
        llm_fn: Optional LLM callable
        mode: "strict" or "assumption"

    Returns:
        List of TrennkostResult
    """
    results = []

    for dish in vision_dishes:
        name = dish.get("name", "Mahlzeit")
        visible_items = dish.get("items", [])
        uncertain = dish.get("uncertain_items", [])

        # Build food items
        ontology = get_ontology()
        items = [ontology.lookup_to_food_item(i) for i in visible_items]
        assumed = [
            ontology.lookup_to_food_item(
                i, assumed=True, assumption_reason="Auf dem Bild nicht sicher erkennbar"
            )
            for i in uncertain
        ]
        unknowns = [
            i.raw_name for i in items + assumed if i.group == FoodGroup.UNKNOWN
        ]

        if mode == "strict":
            analysis = DishAnalysis(
                dish_name=name, items=items,
                unknown_items=unknowns, assumed_items=[],
            )
            result = evaluate_dish(analysis)
            # Add uncertain items as questions — but skip irrelevant ones (herbs/spices)
            if uncertain:
                # Filter out herbs/spices (NEUTRAL/KRAEUTER) that don't affect verdict
                relevant_uncertain = []
                for u in uncertain:
                    ent = ontology.lookup(u)
                    # Only ask about uncertain items that aren't herbs/spices
                    if not ent or (ent.group != FoodGroup.NEUTRAL or ent.subgroup != FoodSubgroup.KRAEUTER):
                        relevant_uncertain.append(u)

                if relevant_uncertain:
                    from trennkost.models import RequiredQuestion
                    result.required_questions.append(RequiredQuestion(
                        question=f"Unsicher erkannte Zutaten: {', '.join(relevant_uncertain)}. Sind diese korrekt?",
                        reason="Bild-Erkennung nicht 100% sicher.",
                        affects_items=relevant_uncertain,
                    ))
                if result.verdict == Verdict.OK and relevant_uncertain:
                    result.verdict = Verdict.CONDITIONAL
                    result.summary = f"{name}: Bedingt OK — einige Zutaten unsicher."
        else:
            analysis = DishAnalysis(
                dish_name=name, items=items,
                unknown_items=unknowns, assumed_items=assumed,
            )
            result = evaluate_dish(analysis)

        # LLM-classify any remaining unknowns
        if unknowns and llm_fn:
            analysis_with_llm = normalize_dish(
                dish_name=name, raw_items=visible_items, llm_fn=llm_fn,
            )
            result = evaluate_dish(analysis_with_llm)

        results.append(result)

    return results


# ── Fix-Directions for NOT_OK ─────────────────────────────────────────

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

    # Collect all groups involved in conflicts
    conflicting_groups = set()
    for p in result.problems:
        conflicting_groups.update(p.affected_groups)

    # Remove groups that combine with everything
    conflicting_groups.discard("NEUTRAL")
    conflicting_groups.discard("UNKNOWN")

    if len(conflicting_groups) < 2:
        return []

    directions = []
    for keep_group in sorted(conflicting_groups):
        keep_items = result.groups_found.get(keep_group, [])
        if not keep_items:
            continue

        # Items to replace: everything from other conflicting groups
        replace_parts = []
        for other_group in sorted(conflicting_groups):
            if other_group == keep_group:
                continue
            other_items = result.groups_found.get(other_group, [])
            if other_items:
                replace_parts.append(", ".join(other_items))

        keep_display = _GROUP_DISPLAY.get(keep_group, keep_group)
        # Clean up "Parmesan → Käse" labels to just first name
        clean = lambda items: ", ".join(i.split(" → ")[0] for i in items)
        keep_items_str = clean(keep_items)
        replace_str = ", ".join(clean(result.groups_found.get(g, [])) for g in sorted(conflicting_groups) if g != keep_group and result.groups_found.get(g))

        # Build list of forbidden groups for this direction
        forbidden_displays = [_GROUP_DISPLAY.get(g, g) for g in sorted(conflicting_groups) if g != keep_group]

        directions.append(
            f"Behalte {keep_display} ({keep_items_str}) "
            f"→ ersetze {replace_str} durch stärkearmes Gemüse/Salat. "
            f"WICHTIG: Kein(e) {', '.join(forbidden_displays)} im Alternativgericht!"
        )

    return directions


# ── Breakfast Guidance ─────────────────────────────────────────────────

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

    # Identify fat-rich items in the current meal
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


# ── Formatting for LLM Context ────────────────────────────────────────

def format_results_for_llm(results: List[TrennkostResult], breakfast_context: bool = False) -> str:
    """
    Format TrennkostResult(s) as structured text for the LLM context.

    The LLM must NOT change the verdict — only explain it from course material.
    """
    parts = []
    parts.append("═══ TRENNKOST-ANALYSE (DETERMINISTISCH) ═══")
    parts.append("WICHTIG: Das Verdict wurde regelbasiert ermittelt und darf NICHT verändert werden.")
    parts.append("Deine Aufgabe: Erkläre das Ergebnis anhand der Kurs-Snippets.")

    # Check if any result has no questions - if so, add emphatic warning
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

        # Fix-directions for NOT_OK
        fix_dirs = _generate_fix_directions(r)
        if fix_dirs:
            parts.append("TRENNKOST-KONFORME ALTERNATIVEN (frage den User):")
            for i, d in enumerate(fix_dirs, 1):
                parts.append(f"  Richtung {i}: {d}")
            parts.append("  → Frage den User, welche Komponente er behalten möchte.")

        # Breakfast guidance
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

    # Add specific problem-related terms
    for r in results:
        for p in r.problems:
            if "milieu" in p.explanation.lower() or "verdauungssäfte" in p.explanation.lower():
                query_parts.append("verschiedene Milieus Verdauung sauer basisch neutralisieren")
            if "gärung" in p.explanation.lower() or "fäulnis" in p.explanation.lower():
                query_parts.append("Gärung Fäulnis Obst Fermentation")

    return " ".join(query_parts)
