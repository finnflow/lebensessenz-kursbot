"""
Food item normalizer.

Pipeline:
1. Compound lookup (deterministic, fast)
2. Ontology synonym lookup (deterministic, fast)
3. LLM fallback for unknown items (slow, used only when needed)

LLM is ONLY used for extraction/normalization, NEVER for the verdict.
"""
from dataclasses import dataclass, field
import json
import logging
import re
from typing import List, Optional, Dict

from trennkost.models import (
    FoodGroup,
    FoodItem,
    DishAnalysis,
    ModifierTag,
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


@dataclass
class _ModifierInterpretation:
    raw_name: str
    normalized_text: str
    base_text: str
    tags: List[ModifierTag] = field(default_factory=list)


@dataclass
class _ResolvedModifierItem:
    lookup_name: str
    modifier_tags: List[ModifierTag] = field(default_factory=list)
    raw_name_override: Optional[str] = None


_MODIFIER_PATTERNS = [
    (ModifierTag.VEGAN, re.compile(r"\bvegan(?:er|e|es|en)?\b", re.IGNORECASE)),
    (ModifierTag.VEGETARIAN, re.compile(r"\b(?:vegetar\w*|veggie)\b", re.IGNORECASE)),
    (ModifierTag.WITH_MEAT, re.compile(r"\bmit\s+fleisch\b", re.IGNORECASE)),
    (ModifierTag.WITH_FISH, re.compile(r"\bmit\s+fisch\b", re.IGNORECASE)),
    (ModifierTag.PREP_BREADED, re.compile(r"\b(?:paniert\w*|breaded)\b", re.IGNORECASE)),
    (ModifierTag.PREP_NATUR, re.compile(r"\bnatur\b", re.IGNORECASE)),
    (ModifierTag.PREP_FRIED, re.compile(r"\b(?:frittiert\w*|fried|gebraten\w*)\b", re.IGNORECASE)),
    (ModifierTag.HINT_CLASSIC, re.compile(r"\b(?:klassisch\w*|classic|normal\w*)\b", re.IGNORECASE)),
]

_MODIFIER_STRIP_PATTERNS = [
    re.compile(r"\bvegan(?:er|e|es|en)?\b", re.IGNORECASE),
    re.compile(r"\b(?:vegetar\w*|veggie)\b", re.IGNORECASE),
    re.compile(r"\bmit\s+fleisch\b", re.IGNORECASE),
    re.compile(r"\bmit\s+fisch\b", re.IGNORECASE),
    re.compile(r"\b(?:paniert\w*|breaded)\b", re.IGNORECASE),
    re.compile(r"\bnatur\b", re.IGNORECASE),
    re.compile(r"\b(?:frittiert\w*|fried|gebraten\w*)\b", re.IGNORECASE),
    re.compile(r"\b(?:klassisch\w*|classic|normal\w*)\b", re.IGNORECASE),
]


def _interpret_modifiers(raw_name: str) -> _ModifierInterpretation:
    normalized_text = re.sub(r"[-_/]+", " ", raw_name.strip().lower())
    normalized_text = re.sub(r"\s+", " ", normalized_text).strip()

    tags: List[ModifierTag] = []
    for tag, pattern in _MODIFIER_PATTERNS:
        if pattern.search(normalized_text):
            tags.append(tag)

    base_text = normalized_text
    for pattern in _MODIFIER_STRIP_PATTERNS:
        base_text = pattern.sub(" ", base_text)
    base_text = re.sub(r"\s+", " ", base_text).strip(" ,")

    return _ModifierInterpretation(
        raw_name=raw_name.strip(),
        normalized_text=normalized_text,
        base_text=base_text,
        tags=tags,
    )


def _build_modifier_item(
    ontology: Ontology,
    spec: _ResolvedModifierItem,
) -> FoodItem:
    item = ontology.lookup_to_food_item(spec.lookup_name)
    if spec.raw_name_override:
        item.raw_name = spec.raw_name_override
    item.recognized_modifiers = list(spec.modifier_tags)
    return item


def _resolve_modifier_specs(
    raw_name: str,
    ontology: Ontology,
) -> Optional[List[_ResolvedModifierItem]]:
    interpretation = _interpret_modifiers(raw_name)
    tags = interpretation.tags
    normalized_text = interpretation.normalized_text

    if "burger" in normalized_text:
        if ModifierTag.VEGAN in tags:
            return [
                _ResolvedModifierItem("Brötchen"),
                _ResolvedModifierItem("Veganes Patty", [ModifierTag.VEGAN]),
            ]
        if ModifierTag.VEGETARIAN in tags:
            return [
                _ResolvedModifierItem("Brötchen"),
                _ResolvedModifierItem("Vegetarisches Patty", [ModifierTag.VEGETARIAN]),
            ]

    if "hotdog" in normalized_text or "hot dog" in normalized_text:
        sausage_tags = [tag for tag in tags if tag in {ModifierTag.VEGAN, ModifierTag.VEGETARIAN, ModifierTag.HINT_CLASSIC}]
        sausage_name = "Wurst"
        if ModifierTag.VEGAN in tags:
            sausage_name = "Vegane Wurst"
        elif ModifierTag.VEGETARIAN in tags:
            sausage_name = "Vegetarische Wurst"
        resolved_items = [
            _ResolvedModifierItem("Brot"),
            _ResolvedModifierItem(sausage_name, sausage_tags),
        ]
        if "pommes" in normalized_text:
            resolved_items.append(_ResolvedModifierItem("Pommes"))
        return resolved_items

    if "patty" in normalized_text:
        if ModifierTag.VEGAN in tags:
            return [_ResolvedModifierItem("Veganes Patty", [ModifierTag.VEGAN], raw_name_override=raw_name.strip())]
        if ModifierTag.VEGETARIAN in tags:
            return [_ResolvedModifierItem("Vegetarisches Patty", [ModifierTag.VEGETARIAN], raw_name_override=raw_name.strip())]

    if "schnitzel" in normalized_text:
        prep_tags = [tag for tag in tags if tag in {ModifierTag.PREP_BREADED, ModifierTag.PREP_NATUR, ModifierTag.PREP_FRIED}]
        if ModifierTag.VEGAN in tags:
            return [_ResolvedModifierItem("Veganes Schnitzel", [ModifierTag.VEGAN, *prep_tags], raw_name_override=raw_name.strip())]
        if ModifierTag.VEGETARIAN in tags:
            return [_ResolvedModifierItem("Vegetarisches Schnitzel", [ModifierTag.VEGETARIAN, *prep_tags], raw_name_override=raw_name.strip())]
        if ModifierTag.PREP_BREADED in tags:
            return [_ResolvedModifierItem("Paniertes Schnitzel", [ModifierTag.PREP_BREADED], raw_name_override=raw_name.strip())]
        if ModifierTag.PREP_NATUR in tags:
            return [_ResolvedModifierItem("Schnitzel", [ModifierTag.PREP_NATUR], raw_name_override=raw_name.strip())]

    prep_tags = [
        tag for tag in tags
        if tag in {ModifierTag.PREP_BREADED, ModifierTag.PREP_NATUR, ModifierTag.PREP_FRIED}
    ]
    if prep_tags:
        full_match = ontology.lookup(raw_name)
        if full_match is not None:
            return [_ResolvedModifierItem(full_match.canonical, prep_tags, raw_name_override=raw_name.strip())]
        if interpretation.base_text:
            base_match = ontology.lookup(interpretation.base_text)
            if base_match is not None:
                return [_ResolvedModifierItem(base_match.canonical, prep_tags, raw_name_override=raw_name.strip())]

    return None


def _append_normalized_item(
    target_items: List[FoodItem],
    source_item: FoodItem,
    ontology: Ontology,
) -> None:
    target_items.append(source_item)
    target_items.extend(ontology.expand_item_for_logic(source_item))


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
    modifier_specs = _resolve_modifier_specs(dish_name, ontology) if raw_items is None else None
    if modifier_specs:
        for spec in modifier_specs:
            _append_normalized_item(items, _build_modifier_item(ontology, spec), ontology)
        logger.info(f"Modifier-driven normalization for dish '{dish_name}': {len(items)} item(s)")

    compound = ontology.get_compound(dish_name) if not items else None
    if compound:
        # Always use compound's base ingredients (even if raw_items also provided)
        all_compound_items = compound.get("base_items", [])
        optional = compound.get("optional_items", [])

        for name in all_compound_items:
            fi = ontology.lookup_to_food_item(name, assumed=False)
            _append_normalized_item(items, fi, ontology)

        # Only add optional items when user didn't supply explicit extra items.
        # If raw_items provided, user has expressed what they want → skip optionals.
        if raw_items is None:
            for name in optional:
                fi = ontology.lookup_to_food_item(
                    name, assumed=True,
                    assumption_reason=f"Typische optionale Zutat in {dish_name}"
                )
                assumed_items.append(fi)
                assumed_items.extend(ontology.expand_item_for_logic(fi))

        # Check if compound needs clarification (handled by engine as CONDITIONAL)
        clarification = compound.get("needs_clarification")
        # This info will be picked up by the engine

        logger.info(f"Compound match for '{dish_name}': {len(items)} base + {len(assumed_items)} optional items")

    # ── Step 2: Raw items provided → ontology lookup ────────────────
    if raw_items is not None:
        for raw in raw_items:
            modifier_specs = _resolve_modifier_specs(raw.strip(), ontology)
            if modifier_specs:
                for spec in modifier_specs:
                    fi = _build_modifier_item(ontology, spec)
                    if fi.group == FoodGroup.UNKNOWN:
                        unknown_items.append(fi.raw_name)
                    _append_normalized_item(items, fi, ontology)
                continue

            fi = ontology.lookup_to_food_item(raw.strip())
            if fi.group == FoodGroup.UNKNOWN:
                unknown_items.append(raw.strip())
            _append_normalized_item(items, fi, ontology)

    # ── Step 2b: Exact ontology hit for single known items/dishes ─────
    if raw_items is None and not items and not assumed_items:
        dish_item = ontology.lookup_to_food_item(dish_name.strip())
        if dish_item.group != FoodGroup.UNKNOWN:
            _append_normalized_item(items, dish_item, ontology)

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
