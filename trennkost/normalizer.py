"""
Food item normalizer.

Pipeline:
1. Compound lookup (deterministic, fast)
2. Ontology synonym lookup (deterministic, fast)
3. LLM fallback for unknown items (slow, used only when needed)

LLM is ONLY used for extraction/normalization, NEVER for the verdict.
"""
import json
import logging
from typing import List, Optional, Dict

from trennkost.models import (
    FoodGroup,
    FoodItem,
    DishAnalysis,
)
from trennkost.ontology import get_ontology, Ontology

logger = logging.getLogger(__name__)

# Valid groups the LLM may return
VALID_GROUPS = {g.value for g in FoodGroup if g != FoodGroup.UNKNOWN}

LLM_CLASSIFY_PROMPT = """Du bist ein Lebensmittel-Klassifikator für ein Trennkost-System.

Gegeben eine Liste von Lebensmitteln, ordne JEDES einzelne einer Gruppe zu.

GRUPPEN:
- OBST: Frisches Obst (Apfel, Banane, Beeren, etc.)
- TROCKENOBST: Trockenfrüchte (Datteln, Feigen, Rosinen)
- NEUTRAL: Stärkearmes Gemüse, Salat, Kräuter, Sprossen (Brokkoli, Gurke, Tomate, Spinat, Petersilie)
- KH: Komplexe Kohlenhydrate - Getreide, Pseudogetreide, stärkehaltiges Gemüse (Reis, Pasta, Brot, Kartoffel, Mais, Quinoa)
- HUELSENFRUECHTE: Hülsenfrüchte (Linsen, Kichererbsen, Bohnen, Tofu, Tempeh)
- PROTEIN: Tierisches Eiweiß - Fisch, Fleisch, Eier (Lachs, Hähnchen, Steak, Ei)
- MILCH: Milchprodukte (Käse, Joghurt, Sahne, Milch) ABER NICHT Butter/Ghee (die sind FETT)
- FETT: Fette und Öle, Nüsse, Samen, Avocado, Butter, Ghee (Olivenöl, Mandeln, Walnüsse)
- UNKNOWN: Wenn du dir nicht sicher bist

WICHTIG:
- Antworte NUR als JSON-Array
- Keine Erklärungen, nur die Zuordnung
- Wenn ein Item mehrdeutig ist, setze "ambiguous": true

Beispiel-Input: ["Spaghetti", "Tomatensauce", "Parmesan", "Basilikum"]
Beispiel-Output:
[
  {"item": "Spaghetti", "group": "KH", "canonical": "Pasta"},
  {"item": "Tomatensauce", "group": "NEUTRAL", "canonical": "Tomate"},
  {"item": "Parmesan", "group": "MILCH", "canonical": "Käse"},
  {"item": "Basilikum", "group": "NEUTRAL", "canonical": "Basilikum"}
]
"""

LLM_EXTRACT_PROMPT = """Du bist ein Lebensmittel-Extraktor. Gegeben ein Gericht oder eine Beschreibung, extrahiere ALLE einzelnen Zutaten.

REGELN:
- Liste JEDE einzelne Zutat separat auf
- Zerlege zusammengesetzte Gerichte (z.B. "Carbonara" → Pasta, Ei, Speck, Parmesan)
- Kennzeichne vermutete Zutaten mit "assumed": true
- Wenn Soßen/Teige dabei sind, zerlege deren Bestandteile
- Sei spezifisch: "Weizenmehl" statt nur "Mehl"

Antworte NUR als JSON:
{
  "dish_name": "Name des Gerichts",
  "items": [
    {"name": "Zutat", "assumed": false},
    {"name": "Vermutete Zutat", "assumed": true, "reason": "Warum vermutet"}
  ]
}

WICHTIG: Markiere Zutaten die du nur vermutest IMMER mit "assumed": true.
Zutaten die klar sichtbar/genannt sind: "assumed": false.
"""


def normalize_dish(
    dish_name: str,
    raw_items: Optional[List[str]] = None,
    llm_fn=None,
) -> DishAnalysis:
    """
    Normalize a dish into classified food items.

    Pipeline:
    1. Check compounds.json for known dishes
    2. Look up each item in ontology
    3. Use LLM for remaining unknowns (if llm_fn provided)

    Args:
        dish_name: Name of the dish
        raw_items: Optional list of already-extracted ingredients.
                   If None and dish is not a known compound, LLM extraction is attempted.
        llm_fn: Optional callable(prompt: str, user_msg: str) -> str for LLM calls.
                Only used for unknown items. Pass None to skip LLM.

    Returns:
        DishAnalysis with all items classified
    """
    ontology = get_ontology()
    items: List[FoodItem] = []
    unknown_items: List[str] = []
    assumed_items: List[FoodItem] = []

    # ── Step 1: Compound lookup ─────────────────────────────────────
    compound = ontology.get_compound(dish_name)
    if compound and raw_items is None:
        # Use compound's known ingredients
        all_compound_items = compound.get("base_items", [])
        optional = compound.get("optional_items", [])

        for name in all_compound_items:
            fi = ontology.lookup_to_food_item(name, assumed=False)
            items.append(fi)

        for name in optional:
            fi = ontology.lookup_to_food_item(
                name, assumed=True,
                assumption_reason=f"Typische optionale Zutat in {dish_name}"
            )
            assumed_items.append(fi)

        # Check if compound needs clarification (handled by engine as CONDITIONAL)
        clarification = compound.get("needs_clarification")
        # This info will be picked up by the engine

        logger.info(f"Compound match for '{dish_name}': {len(items)} base + {len(assumed_items)} optional items")

    # ── Step 2: Raw items provided → ontology lookup ────────────────
    if raw_items is not None:
        for raw in raw_items:
            fi = ontology.lookup_to_food_item(raw.strip())
            if fi.group == FoodGroup.UNKNOWN:
                unknown_items.append(raw.strip())
            items.append(fi)

    # ── Step 3: No items yet → LLM extraction ──────────────────────
    if not items and not assumed_items and llm_fn is not None:
        extracted = _llm_extract_items(dish_name, llm_fn)
        if extracted:
            for ext in extracted:
                name = ext.get("name", "")
                is_assumed = ext.get("assumed", False)
                reason = ext.get("reason")
                fi = ontology.lookup_to_food_item(
                    name, assumed=is_assumed, assumption_reason=reason
                )
                if is_assumed:
                    assumed_items.append(fi)
                else:
                    items.append(fi)
                if fi.group == FoodGroup.UNKNOWN:
                    unknown_items.append(name)

    # ── Step 4: LLM classification for remaining unknowns ──────────
    unknowns_to_classify = [it for it in items if it.group == FoodGroup.UNKNOWN]
    unknowns_to_classify += [it for it in assumed_items if it.group == FoodGroup.UNKNOWN]

    if unknowns_to_classify and llm_fn is not None:
        classified = _llm_classify_items(
            [it.raw_name for it in unknowns_to_classify], llm_fn
        )
        if classified:
            classification_map = {c["item"].lower(): c for c in classified}
            for it in unknowns_to_classify:
                cls = classification_map.get(it.raw_name.lower())
                if cls:
                    group_str = cls.get("group", "UNKNOWN")
                    if group_str in VALID_GROUPS:
                        it.group = FoodGroup(group_str)
                        it.canonical = cls.get("canonical", it.raw_name)
                        it.confidence = 0.6  # LLM-classified = lower confidence

    # Update unknown_items list (remove items that got classified)
    final_unknowns = [it.raw_name for it in items if it.group == FoodGroup.UNKNOWN]
    final_unknowns += [it.raw_name for it in assumed_items if it.group == FoodGroup.UNKNOWN]

    return DishAnalysis(
        dish_name=dish_name,
        items=items,
        unknown_items=final_unknowns,
        assumed_items=assumed_items,
    )


def _llm_extract_items(dish_name: str, llm_fn) -> Optional[List[dict]]:
    """Use LLM to extract ingredients from a dish name."""
    try:
        response = llm_fn(LLM_EXTRACT_PROMPT, f"Gericht: {dish_name}")
        parsed = json.loads(response)
        return parsed.get("items", [])
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"LLM extraction failed for '{dish_name}': {e}")
        return None


def _llm_classify_items(items: List[str], llm_fn) -> Optional[List[dict]]:
    """Use LLM to classify unknown food items into groups."""
    try:
        response = llm_fn(LLM_CLASSIFY_PROMPT, json.dumps(items, ensure_ascii=False))
        return json.loads(response)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"LLM classification failed: {e}")
        return None
