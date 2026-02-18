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


def search_recipes(
    query: str,
    category: Optional[str] = None,
    ingredients: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    exclude_ingredients: Optional[List[str]] = None,
    limit: int = 5,
) -> List[Dict]:
    """
    Search curated recipes with filtering and ranking.

    Args:
        query: User's text (used for keyword matching)
        category: Trennkost category filter (KH, PROTEIN, NEUTRAL, OBST, HUELSENFRUECHTE)
        ingredients: Required ingredients (match any)
        tags: Required tags (match any)
        exclude_ingredients: Ingredients to exclude (allergies/preferences)
        limit: Max results

    Returns:
        List of recipe dicts (without full_recipe_md for brevity)
    """
    all_recipes = load_recipes()
    if not all_recipes:
        return []

    # Extract useful info from query
    query_lower = query.lower()
    query_words = set(re.split(r'[\s,;]+', query_lower))

    # Auto-detect category from query if not specified
    if not category:
        category = _detect_category_from_query(query_lower)

    # Auto-detect ingredients from query using ontology
    if not ingredients:
        ingredients = _extract_ingredients_from_query(query_lower)

    # Auto-detect tags from query
    if not tags:
        tags = _detect_tags_from_query(query_lower)

    # Filter phase
    candidates = []
    for recipe in all_recipes:
        # Category filter
        if category and recipe["trennkost_category"] != category:
            continue

        # Exclude filter
        if exclude_ingredients:
            all_items = " ".join(recipe["ingredients"] + recipe.get("optional_ingredients", [])).lower()
            if any(_normalize_ingredient(ex) in all_items for ex in exclude_ingredients):
                continue

        candidates.append(recipe)

    # Scoring phase
    scored = []
    for recipe in candidates:
        score = 0.0
        all_recipe_items = recipe["ingredients"] + recipe.get("optional_ingredients", [])
        all_items_lower = " ".join(all_recipe_items).lower()
        recipe_name_lower = recipe["name"].lower()

        # Ingredient match scoring
        if ingredients:
            for ing in ingredients:
                if any(_ingredient_matches(ri, ing) for ri in all_recipe_items):
                    score += 3.0

        # Tag match scoring
        if tags:
            for tag in tags:
                if tag in recipe.get("tags", []):
                    score += 2.0

        # Query keyword matching (name + ingredients)
        for word in query_words:
            if len(word) >= 3:
                if word in recipe_name_lower:
                    score += 2.0
                elif word in all_items_lower:
                    score += 1.0

        # Bonus for matching section keywords in query
        section_lower = recipe.get("section", "").lower()
        if any(w in query_lower for w in section_lower.split() if len(w) >= 4):
            score += 1.0

        scored.append((score, recipe))

    # Sort by score descending, then by name
    scored.sort(key=lambda x: (-x[0], x[1]["name"]))

    # Return top N (include full_recipe_md only for top match to save tokens)
    results = []
    for i, (score, recipe) in enumerate(scored[:limit]):
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
        # Include full recipe markdown only for top match
        if i == 0:
            result["full_recipe_md"] = recipe.get("full_recipe_md", "")
        # Pass through trennkost_hinweis if present
        if recipe.get("trennkost_hinweis"):
            result["trennkost_hinweis"] = recipe["trennkost_hinweis"]
        results.append(result)

    return results


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
