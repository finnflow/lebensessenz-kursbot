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
    "ist.*ok", "in ordnung", "passt.*zusammen", "speisekarte", "menü",
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

# Pattern: "IngredientName (optional notes): quantity/description"
# Matches "Haferflocken: 60g", "Kokosjoghurt (vegan): 2-3 EL", "Banane: ½ Stück"
_INGREDIENT_QUANTITY_LINE = re.compile(
    r"^([A-ZÄÖÜa-zäöüß][A-ZÄÖÜa-zäöüß\s\-]{1,40}?)"  # ingredient name (2-40 chars)
    r"(?:\s*\([^)]{1,30}\))?"                           # optional (parenthetical note)
    r"\s*:\s*"                                           # colon separator
    r"[\d½¼¾⅓⅔\-–~<>]",                                # starts with quantity/range
    re.UNICODE,
)

# Lines to skip when parsing ingredient lists (instructions, emojis, section headers)
_SKIP_LINE_RE = re.compile(
    r"[🧪🥄🍳🔪✅❌⚠️🎉💡→]"
    r"|zubereitung|anleitung|schritt|tipps?:|hinweis|warum|erklärt"
    r"|einweichen|einrühren|vorbereiten|vermischen|anrichten|unterheben",
    re.IGNORECASE,
)

# Breakfast detection keywords (explicit + implicit signals like "Haferflocken", "Porridge")
_BREAKFAST_KEYWORDS = re.compile(
    r"frühstück|fruehstueck|morgens|vormittag|zum\s*frühstück|breakfast"
    r"|morgenessen|am\s*morgen|in\s*der\s*früh|in\s*der\s*frueh"
    r"|haferflocken|porridge|müsli|muesli|overnight|granola|oatmeal",
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
    # Split by common separators ("mit", "und", comma etc.)
    segments = _ITEM_SEPARATORS.split(text.strip())
    found_foods: set = set()
    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue
        # Try full segment first (e.g. "Hähnchen")
        if ontology.lookup(segment):
            found_foods.add(segment.lower())
        else:
            # Try each individual word in segment
            # Handles cases like "Ei in Ordnung?" → "Ei" is a food, rest is not
            for word in re.split(r'\s+', segment):
                word_clean = word.strip('?!.,;:()')
                if word_clean and len(word_clean) >= 3 and ontology.lookup(word_clean):
                    found_foods.add(word_clean.lower())
                    break  # One food hit per segment is enough
    return len(found_foods) >= 2


def detect_temporal_separation(text: str) -> Optional[Dict[str, Any]]:
    """
    Detect if user is asking about SEQUENTIAL eating (temporal separation).

    Examples:
    - "Apfel vor Reis essen"
    - "erst Obst, dann KH"
    - "Apfel 30 Min vor dem Mittagessen"
    - "nach 45 Min dann Hähnchen"

    Returns:
        {
            "is_temporal": bool,
            "first_foods": List[str],  # foods eaten first
            "second_foods": List[str], # foods eaten later
            "wait_time": Optional[int] # minutes if specified
        }
        or None if no temporal separation detected
    """
    text_lower = text.lower()

    # Temporal keywords indicating sequential eating
    temporal_patterns = [
        # "X vor Y"
        r"(\w+(?:\s+\w+)?)\s+(?:(\d+)\s*min(?:uten)?\s+)?vor\s+(?:dem|der)?\s*(\w+)",
        # "erst X, dann Y" / "zuerst X, danach Y"
        r"(?:erst|zuerst)\s+(\w+(?:\s+\w+)?),?\s+(?:dann|danach|anschließend)\s+(\w+)",
        # "X und nach Y Min Z"
        r"(\w+(?:\s+\w+)?)\s+und\s+nach\s+(\d+)\s*min(?:uten)?\s+(\w+)",
        # "nach X dann Y"
        r"nach\s+(?:dem|der)?\s*(\w+(?:\s+\w+)?)\s+dann\s+(\w+)",
    ]

    for pattern in temporal_patterns:
        match = re.search(pattern, text_lower)
        if match:
            groups = match.groups()
            # Extract foods and wait time
            if len(groups) == 3 and groups[1] and groups[1].isdigit():
                # Pattern with time: "X 30 min vor Y"
                return {
                    "is_temporal": True,
                    "first_foods": [groups[0].strip()],
                    "second_foods": [groups[2].strip()],
                    "wait_time": int(groups[1])
                }
            elif len(groups) == 2:
                # Pattern without time: "erst X dann Y"
                return {
                    "is_temporal": True,
                    "first_foods": [groups[0].strip()],
                    "second_foods": [groups[1].strip()],
                    "wait_time": None
                }

    return None


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
            if len(name) < 2:
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


def _try_parse_as_ingredient_list(text: str) -> Optional[List[Dict[str, Any]]]:
    """
    Detect if text is a structured multi-ingredient compliance check (pasted recipe).
    If yes: aggregate all ingredient lines into a SINGLE dish for combined evaluation.

    Detection: ≥3 lines matching "IngredientName: quantity" pattern.
    Aggregation: extract ingredient names (before colon), ignore instructions/questions.

    Returns single-element list [{"name": dish_name, "items": [ingredients]}],
    or None if text doesn't look like an ingredient list.
    """
    raw_lines = [l.strip() for l in text.split('\n') if l.strip()]
    if len(raw_lines) < 3:
        return None

    ingredients: List[str] = []
    question_intro: Optional[str] = None

    for line in raw_lines:
        # Skip instruction/emoji/section-header lines
        if _SKIP_LINE_RE.search(line):
            continue

        # Check for "IngredientName: quantity" pattern
        m = _INGREDIENT_QUANTITY_LINE.match(line)
        if m:
            name = m.group(1).strip().rstrip('-– ')
            if len(name) >= 2:
                ingredients.append(name)
            continue

        # Keep track of the first question line for naming the dish
        if '?' in line and question_intro is None and len(line) < 80:
            question_intro = line

    # Only aggregate if we found enough ingredient lines
    if len(ingredients) < 3:
        return None

    # Build a clean dish name from the question or use generic fallback
    if question_intro:
        dish_name = re.sub(r'\?.*', '', question_intro).strip()
        dish_name = re.sub(r'(?i)^(folgendes?|mein|das|ein|eine)\s+', '', dish_name).strip()
        dish_name = dish_name or "Rezept-Kombination"
    else:
        dish_name = "Rezept-Kombination"

    logger.debug(f"[PARSE] Ingredient-list detected: '{dish_name}' with {len(ingredients)} items: {ingredients}")
    return [{"name": dish_name, "items": ingredients}]


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

    # Check for structured ingredient list (pasted recipe / compliance check)
    # Must run BEFORE question detection — a pasted recipe has a question intro
    # but the body is an ingredient list, not a natural-language question.
    ingredient_list = _try_parse_as_ingredient_list(text)
    if ingredient_list:
        return ingredient_list

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


from trennkost.formatter import format_results_for_llm, build_rag_query  # noqa: F401 (re-export)


