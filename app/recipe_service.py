"""
Recipe search service.

Loads curated Trennkost-compliant recipes from recipes.json
and provides filtered search with ranking.
"""
import json
import re
from pathlib import Path
from typing import List, Dict, Optional

from trennkost.ontology import get_ontology
from app.clients import client as _openai_client, MODEL

DATA_PATH = Path(__file__).parent / "data" / "recipes.json"

_recipes_cache: Optional[List[Dict]] = None


def load_recipes() -> List[Dict]:
    """Load recipes from JSON (cached in memory)."""
    global _recipes_cache
    if _recipes_cache is not None:
        return _recipes_cache
    if not DATA_PATH.exists():
        _recipes_cache = []
        return _recipes_cache
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        _recipes_cache = json.load(f)
    return _recipes_cache


def get_recipe_by_id(recipe_id: str) -> Optional[Dict]:
    """Look up a single recipe by its slug ID."""
    for r in load_recipes():
        if r["id"] == recipe_id:
            return r
    return None


def get_recipe_by_name(name: str) -> Optional[Dict]:
    """Look up a single recipe by exact or fuzzy name match."""
    name_lower = name.lower().strip()
    for r in load_recipes():
        if r["name"].lower() == name_lower:
            return r
    # Fuzzy: check if name is contained
    for r in load_recipes():
        if name_lower in r["name"].lower() or r["name"].lower() in name_lower:
            return r
    return None


def _normalize_ingredient(item: str) -> str:
    """Normalize an ingredient name for matching."""
    return item.strip().lower()


def _ingredient_matches(recipe_ingredient: str, search_term: str) -> bool:
    """Check if a recipe ingredient matches a search term (with ontology synonyms)."""
    ri = _normalize_ingredient(recipe_ingredient)
    st = _normalize_ingredient(search_term)

    # Direct substring match
    if st in ri or ri in st:
        return True

    # Ontology synonym matching
    ontology = get_ontology()
    entry_search = ontology.lookup(search_term)
    entry_recipe = ontology.lookup(recipe_ingredient)

    if entry_search and entry_recipe:
        # Same canonical item = match
        if entry_search.canonical == entry_recipe.canonical:
            return True

    return False


def _llm_select_recipe_ids(
    query: str,
    recipes: List[Dict],
    limit: int = 3,
) -> List[str]:
    """
    LLM-based recipe selection: show all recipe names to the model,
    get back a ranked list of IDs that best match the query.

    Works for up to ~300 recipes (fits easily in mini's 128k context).
    Handles inflections, synonyms and concepts that keyword matching misses.

    Returns: ordered list of recipe IDs (empty if nothing matches).
    On error: returns [] and falls back to keyword scoring.
    """
    # Build compact recipe list: "id — Name (Section) [tag1, tag2]"
    lines = []
    for r in recipes:
        tags_str = ", ".join(r.get("tags", [])[:4])  # max 4 tags to save tokens
        tags_part = f" [{tags_str}]" if tags_str else ""
        lines.append(f"{r['id']} — {r['name']} ({r.get('section', '')}){tags_part}")
    recipe_list = "\n".join(lines)

    prompt = f"""Du bist ein Rezept-Suchassistent für eine Trennkost-App.

NUTZER-ANFRAGE: {query}

VERFÜGBARE REZEPTE:
{recipe_list}

Wähle bis zu {limit} Rezepte die am BESTEN zur Anfrage passen.
Berücksichtige: Küche/Herkunft, Zutaten, Stil, Stimmung — auch wenn Wörter nicht exakt übereinstimmen.
Beispiel: "etwas Italienisches" → Rezepte mit "italienisch", "mediterran", "Pasta", "Risotto" im Namen.
Beispiel: "etwas Traditionelles" → Rezepte mit "altmodisch", "klassisch", "deftig" im Namen.

Wenn KEIN Rezept zur Anfrage passt: leere ids-Liste zurückgeben.
Antworte NUR mit JSON, kein Kommentar:
{{"ids": ["id1", "id2", "id3"]}}"""

    try:
        response = _openai_client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=100,
            timeout=5,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()
        result = json.loads(raw)
        ids = result.get("ids", [])
        if not isinstance(ids, list):
            return []
        # Validate: only return IDs that actually exist
        valid_ids = {r["id"] for r in recipes}
        filtered = [i for i in ids if i in valid_ids]
        print(f"[RECIPE_LLM] query='{query[:50]}' → selected={filtered}")
        return filtered[:limit]
    except Exception as e:
        print(f"[RECIPE_LLM] selection failed (fallback to keyword): {e}")
        return []


def search_recipes(
    query: str,
    category: Optional[str] = None,
    ingredients: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    exclude_ingredients: Optional[List[str]] = None,
    limit: int = 5,
) -> List[Dict]:
    """
    Search curated recipes with LLM-based selection (primary) + keyword scoring (fallback).

    Primary path: _llm_select_recipe_ids() — handles inflections, synonyms, cuisine names.
    Fallback path: keyword + ingredient + tag scoring (used when LLM call fails).

    Args:
        query: User's text
        category: Trennkost category filter (KH, PROTEIN, NEUTRAL, OBST, HUELSENFRUECHTE)
        ingredients: Required ingredients (match any)
        tags: Required tags (match any)
        exclude_ingredients: Ingredients to exclude
        limit: Max results

    Returns:
        List of recipe dicts (with full_recipe_md for top match only)
    """
    all_recipes = load_recipes()
    if not all_recipes:
        return []

    query_lower = query.lower()

    # Hard filters (explicit constraints — applied regardless of search path)
    if not category:
        category = _detect_category_from_query(query_lower)

    def _passes_filters(recipe: Dict) -> bool:
        if category and recipe["trennkost_category"] != category:
            return False
        if exclude_ingredients:
            all_items = " ".join(
                recipe["ingredients"] + recipe.get("optional_ingredients", [])
            ).lower()
            if any(_normalize_ingredient(ex) in all_items for ex in exclude_ingredients):
                return False
        return True

    candidates = [r for r in all_recipes if _passes_filters(r)]
    if not candidates:
        return []

    # ── Primary: LLM selection ────────────────────────────────────────
    selected_ids = _llm_select_recipe_ids(query, candidates, limit=limit)

    if selected_ids:
        # Build results in LLM-ranked order, assign descending scores
        # Scores 6.0, 5.5, 5.0 … → above "clear match" threshold (5.0),
        # below direct-output bypass threshold (7.0) so main LLM writes intro.
        id_to_recipe = {r["id"]: r for r in candidates}
        results = []
        for i, rid in enumerate(selected_ids):
            recipe = id_to_recipe.get(rid)
            if not recipe:
                continue
            score = max(5.0, 6.0 - i * 0.5)
            result = _build_result(recipe, score, include_full_md=(i == 0))
            results.append(result)
        return results

    # ── Fallback: keyword + ingredient + tag scoring ──────────────────
    print(f"[RECIPE_LLM] LLM returned no matches — falling back to keyword scoring")
    if not ingredients:
        ingredients = _extract_ingredients_from_query(query_lower)
    if not tags:
        tags = _detect_tags_from_query(query_lower)

    query_words = set(re.split(r'[\s,;]+', query_lower))
    scored = []
    for recipe in candidates:
        score = 0.0
        all_recipe_items = recipe["ingredients"] + recipe.get("optional_ingredients", [])
        all_items_lower = " ".join(all_recipe_items).lower()
        recipe_name_lower = recipe["name"].lower()

        if ingredients:
            for ing in ingredients:
                if any(_ingredient_matches(ri, ing) for ri in all_recipe_items):
                    score += 3.0
        if tags:
            for tag in tags:
                if tag in recipe.get("tags", []):
                    score += 2.0
        for word in query_words:
            if len(word) >= 3:
                if word in recipe_name_lower:
                    score += 2.0
                elif word in all_items_lower:
                    score += 1.0
        section_lower = recipe.get("section", "").lower()
        if any(w in query_lower for w in section_lower.split() if len(w) >= 4):
            score += 1.0
        scored.append((score, recipe))

    scored.sort(key=lambda x: (-x[0], x[1]["name"]))
    return [
        _build_result(recipe, score, include_full_md=(i == 0))
        for i, (score, recipe) in enumerate(scored[:limit])
    ]


def _build_result(recipe: Dict, score: float, include_full_md: bool = False) -> Dict:
    """Build a standardized result dict from a recipe."""
    result = {
        "id": recipe["id"],
        "name": recipe["name"],
        "section": recipe["section"],
        "time_minutes": recipe["time_minutes"],
        "servings": recipe["servings"],
        "ingredients": recipe["ingredients"],
        "optional_ingredients": recipe.get("optional_ingredients", []),
        "trennkost_category": recipe["trennkost_category"],
        "tags": recipe.get("tags", []),
        "score": score,
    }
    if include_full_md:
        result["full_recipe_md"] = recipe.get("full_recipe_md", "")
    if recipe.get("trennkost_hinweis"):
        result["trennkost_hinweis"] = recipe["trennkost_hinweis"]
    return result


def _detect_category_from_query(query_lower: str) -> Optional[str]:
    """Auto-detect Trennkost category from query text."""
    # Explicit category mentions
    cat_keywords = {
        "protein": "PROTEIN",
        "kohlenhydrat": "KH",
        "neutral": "NEUTRAL",
        "obst": "OBST",
        "hülsenfrucht": "HUELSENFRUECHTE",
        "hülsenfrücht": "HUELSENFRUECHTE",
    }
    for kw, cat in cat_keywords.items():
        if kw in query_lower:
            return cat

    # Ingredient-based detection
    protein_words = {"fleisch", "fisch", "hähnchen", "steak", "lachs", "garnelen"}
    kh_words = {"reis", "nudeln", "pasta", "kartoffel", "brot", "couscous", "bulgur"}

    if any(w in query_lower for w in protein_words):
        return "PROTEIN"
    if any(w in query_lower for w in kh_words):
        return "KH"

    return None


def _extract_ingredients_from_query(query_lower: str) -> List[str]:
    """Extract food items from query using ontology."""
    ontology = get_ontology()
    words = re.split(r'[\s,;]+', query_lower)
    found = []
    seen = set()
    for word in words:
        if len(word) < 3:
            continue
        entry = ontology.lookup(word)
        if entry and entry.canonical not in seen:
            found.append(entry.canonical)
            seen.add(entry.canonical)
    return found


def extract_ingredients_from_query(query: str) -> List[str]:
    """Public alias: extract food items from query using ontology."""
    return _extract_ingredients_from_query(query.lower())


def find_recipes_by_ingredient_overlap(
    available_ingredients: List[str],
    limit: int = 3,
) -> List[Dict]:
    """
    Find recipes by ingredient overlap — NOT semantic similarity.

    For each recipe, counts how many required ingredients the user has.
    Uses _ingredient_matches() for ontology-aware fuzzy matching.

    Returns: recipes sorted by overlap DESC, enriched with:
      overlap_score: float (0.0–1.0)
      matched_ingredients: List[str]
      missing_required: List[str]
      missing_optional: List[str]
    """
    all_recipes = load_recipes()
    if not all_recipes or not available_ingredients:
        return []

    scored = []
    for recipe in all_recipes:
        required = recipe.get("ingredients", [])
        optional = recipe.get("optional_ingredients", [])

        if not required:
            continue

        matched = []
        missing_required = []
        for req_ing in required:
            if any(_ingredient_matches(req_ing, avail) for avail in available_ingredients):
                matched.append(req_ing)
            else:
                missing_required.append(req_ing)

        missing_optional = [
            opt for opt in optional
            if not any(_ingredient_matches(opt, avail) for avail in available_ingredients)
        ]

        overlap_score = len(matched) / len(required) if required else 0.0

        scored.append((overlap_score, {
            "id": recipe["id"],
            "name": recipe["name"],
            "section": recipe["section"],
            "time_minutes": recipe["time_minutes"],
            "servings": recipe["servings"],
            "ingredients": required,
            "optional_ingredients": optional,
            "trennkost_category": recipe["trennkost_category"],
            "tags": recipe.get("tags", []),
            "full_recipe_md": recipe.get("full_recipe_md", ""),
            "trennkost_hinweis": recipe.get("trennkost_hinweis"),
            "overlap_score": overlap_score,
            "matched_ingredients": matched,
            "missing_required": missing_required,
            "missing_optional": missing_optional,
        }))

    scored.sort(key=lambda x: (-x[0], x[1]["name"]))
    return [r for _, r in scored[:limit]]


def _detect_tags_from_query(query_lower: str) -> List[str]:
    """Detect relevant tags from query text."""
    tags = []
    tag_keywords = {
        "vegan": "vegan",
        "vegetarisch": "vegetarisch",
        "schnell": "schnell",
        "salat": "salat",
        "suppe": "suppe",
        "eintopf": "eintopf",
        "sandwich": "sandwich",
        "dessert": "dessert",
        "drink": "drink",
        "smoothie": "drink",
        "saft": "drink",
        "beilage": "beilage",
        "hauptgericht": "hauptgericht",
    }
    for kw, tag in tag_keywords.items():
        if kw in query_lower and tag not in tags:
            tags.append(tag)
    return tags
