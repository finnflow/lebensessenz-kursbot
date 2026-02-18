#!/usr/bin/env python3
"""
Parse recipe markdown file and generate structured recipes.json.

Reads rezepte_de_clean_export_full_trennkostfix.md and outputs app/data/recipes.json
with structured data. Only Kalifornische Tostada is excluded (HF+KH unfixable).

Usage:
    python scripts/parse_recipes.py [--input PATH] [--output PATH]
"""
import re
import json
import unicodedata
from pathlib import Path
from typing import List, Dict, Optional

# ── Excluded recipes (permanently non-compliant) ─────────────────────

EXCLUDED_RECIPES = {
    "Kalifornische Tostada",  # Erbsen (HF) + Mais/Tortilla-Chips (KH) — unfixable
}

# ── Post-parse recipe patches ────────────────────────────────────────
# Zutat-Fixes die im Markdown nicht geändert werden sollen

RECIPE_PATCHES = {
    "Curry-Hähnchen-Salat": {
        # Möhren (KH) + Hähnchen (PROTEIN) = R001 → Brokkoli statt Möhren
        "ingredient_replace": [("Möhren", "Brokkoli")],
        "md_replace": [
            ("1–2 Möhren, in feine Stifte", "250 g Brokkoli, in Röschen, bissfest gegart"),
            ("Möhren und optional", "Brokkoli und optional"),
        ],
    },
    "Kantonesischer Seafood-Salat": {
        # Möhre (KH, optional) + Garnelen (PROTEIN) = R001 → Möhre entfernen
        "ingredient_remove": ["Möhre"],
        "md_replace": [
            ("- 1 Möhre, fein geraspelt (optional)\n", ""),
        ],
    },
}

# ── Mandeldrink hint ─────────────────────────────────────────────────
# Recipes using Mandeldrink + Obst: technically OBST+FETT but the
# actual nut content is minimal. Mark with hint for transparency.

MANDELDRINK_HINT = (
    "Mandeldrink enthält nur minimale Mengen Nussfett — nicht ganz "
    "optimal, aber wird als verträglich mit Obst angesehen."
)
MANDELDRINK_RECIPES = {
    "Dattel- oder Erdbeer-Shake",
    "Bananen-Shake",
}


# ── Trennkost category heuristics ────────────────────────────────────

PROTEIN_ITEMS = {
    "hähnchen", "chicken", "steak", "rind", "fleisch", "fisch", "lachs",
    "kabeljau", "garnelen", "seafood", "hackfleisch", "hähnchenstreifen",
    "hähnchenfilets", "hähnchenschenkel", "fischsteaks",
}

KH_ITEMS = {
    "reis", "nudeln", "pasta", "spaghetti", "fusilli", "bulgur", "couscous",
    "kartoffel", "kartoffeln", "brot", "tortilla", "tortillas", "pita",
    "vollkornbrot", "vollkornnudeln", "mais", "maiskolben", "süßkartoffel",
    "süßkartoffeln", "strudelteig",
}

OBST_ITEMS = {
    "apfel", "äpfel", "banane", "bananen", "beeren", "erdbeeren", "kiwi",
    "melone", "heidelbeeren", "orange", "birne", "trauben", "datteln",
}

HF_ITEMS = {
    "linsen", "erbsen", "kichererbsen", "bohnen",
}

MILCH_ITEMS = {
    "käse", "sahne", "joghurt", "schmand", "saure sahne", "frischkäse",
    "milch", "butter", "mozzarella", "parmesan",
}

FETT_ITEMS = {
    "olivenöl", "avocado", "nüsse", "mandeln", "walnüsse",
    "sonnenblumenkerne", "sesam", "nussbutter", "mandelbutter",
    "erdnussbutter", "tahini",
}


def _normalize_quotes(text: str) -> str:
    """Normalize curly/smart quotes to ASCII equivalents."""
    return text.replace("\u2018", "'").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')


def slugify(text: str) -> str:
    """Convert text to URL-safe slug."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s_]+", "-", text).strip("-")
    return text


def parse_time(time_str: str) -> Optional[int]:
    """Parse time string to minutes."""
    if not time_str:
        return None
    time_str = re.sub(r"\(.*?\)", "", time_str).strip()
    # Handle "1 Std. 20 Min." format
    hours_match = re.search(r"(\d+)\s*Std", time_str)
    mins_match = re.search(r"(\d+)\s*Min", time_str)
    if hours_match:
        hours = int(hours_match.group(1))
        mins = int(mins_match.group(1)) if mins_match else 0
        return hours * 60 + mins
    match = re.search(r"(\d+)\s*[–-]\s*(\d+)", time_str)
    if match:
        return (int(match.group(1)) + int(match.group(2))) // 2
    match = re.search(r"(\d+)", time_str)
    if match:
        return int(match.group(1))
    return None


def extract_ingredients(lines: List[str]) -> tuple:
    """Extract ingredients and optional ingredients from recipe lines."""
    ingredients = []
    optional_ingredients = []
    in_optional = False

    for line in lines:
        line = line.strip()
        if not line:
            continue

        lower = line.lower()
        if line.startswith("####"):
            break
        if line.startswith("**") and line.endswith("**"):
            # Section header like **Salat:**, **Optional dazu:**
            if "optional" in lower or "topping" in lower:
                in_optional = True
            else:
                in_optional = False
            continue
        # Standalone optional/topping header (no bold, not an ingredient)
        if not line.startswith("- ") and ("optional" in lower or "topping" in lower):
            in_optional = True
            continue

        if line.startswith("- "):
            item = line[2:].strip()
            clean = re.sub(
                r"^[\d/½¼¾.,–-]+\s+"
                r"(?:(?:g|kg|ml|l|EL|TL|Stk|Stück|Tasse|Tassen|Handvoll|Bund|Dose|Scheiben?|Blatt|Zweig[e]?|Kopf|Rolle|Prise)\s+)?",
                "", item
            ).strip()
            name = re.sub(r"\s*\(.*\)$", "", clean).strip()
            name = re.split(r",\s*(in\s|gewaschen|gehackt|geschnitten|gewürfelt|geraspelt|geschält|fein|grob|bissfest|abgekühlt|zerdrückt|halbiert|angedrückt|abgetropft|entkernt|eingeweicht)", name)[0].strip()

            if name and len(name) >= 2:
                if in_optional:
                    optional_ingredients.append(name)
                else:
                    ingredients.append(name)

    return ingredients, optional_ingredients


def detect_category(
    name: str,
    ingredients: List[str],
    optional_ingredients: List[str],
    section: str,
) -> str:
    """Determine Trennkost category from ingredients and section."""
    all_items = " ".join(ingredients + optional_ingredients + [name]).lower()

    has_protein = any(p in all_items for p in PROTEIN_ITEMS)
    has_kh = any(k in all_items for k in KH_ITEMS)
    has_obst = any(o in all_items for o in OBST_ITEMS)
    has_hf = any(h in all_items for h in HF_ITEMS)

    section_lower = section.lower()
    if "obst" in section_lower or "dessert" in section_lower:
        return "OBST"
    if "drink" in section_lower:
        # Drinks with fruit = OBST
        if has_obst:
            return "OBST"
    if "protein" in section_lower or "chicken" in section_lower or "fish" in section_lower:
        return "PROTEIN"
    if "sättigungsbeilagen" in section_lower or "kartoffel" in section_lower or "getreide" in section_lower:
        return "KH"
    if "brot" in section_lower or "tortilla" in section_lower or "crouton" in section_lower:
        return "KH"

    if has_obst and not has_protein and not has_kh:
        return "OBST"
    if has_hf:
        return "HUELSENFRUECHTE"
    if has_protein and not has_kh:
        return "PROTEIN"
    if has_kh and not has_protein:
        return "KH"
    if has_protein and has_kh:
        return "MIXED"

    return "NEUTRAL"


def detect_tags(
    name: str,
    ingredients: List[str],
    time_minutes: Optional[int],
    section: str,
    category: str,
) -> List[str]:
    """Auto-detect tags from ingredients and metadata."""
    tags = []
    all_items = " ".join(ingredients + [name]).lower()

    has_meat = any(m in all_items for m in {"hähnchen", "steak", "rind", "fleisch", "hackfleisch", "schinken"})
    has_fish = any(f in all_items for f in {"fisch", "lachs", "kabeljau", "garnelen", "seafood"})
    has_dairy = any(d in all_items for d in MILCH_ITEMS)
    has_egg = "ei" in all_items.split() or "eier" in all_items

    if not has_meat and not has_fish and not has_dairy and not has_egg:
        tags.append("vegan")
    elif not has_meat and not has_fish:
        tags.append("vegetarisch")
    if has_fish:
        tags.append("fisch")
    if has_meat:
        tags.append("fleisch")

    if time_minutes and time_minutes <= 15:
        tags.append("schnell")

    section_lower = section.lower()
    if "salat" in section_lower or "slaw" in section_lower:
        tags.append("salat")
    elif "suppe" in section_lower or "bisque" in section_lower or "chowder" in section_lower:
        tags.append("suppe")
    elif "eintopf" in section_lower or "ofen" in section_lower:
        tags.append("eintopf")
    elif "sandwich" in section_lower or "wrap" in section_lower or "toastie" in section_lower:
        tags.append("sandwich")
    elif "protein" in section_lower or "hauptgericht" in section_lower:
        tags.append("hauptgericht")
    elif "beilage" in section_lower or "stir-frie" in section_lower or "gemüse" in section_lower.replace("ü", "ue"):
        tags.append("beilage")
    elif "brot" in section_lower or "crouton" in section_lower:
        tags.append("brot")
    elif "drink" in section_lower or "saft" in section_lower or "smoothie" in section_lower or "shake" in section_lower:
        tags.append("drink")
    elif "obst" in section_lower or "dessert" in section_lower:
        tags.append("dessert")
    elif "dressing" in section_lower or "dip" in section_lower or "sauce" in section_lower:
        tags.append("dressing")

    return tags


def apply_patches(recipe: Dict) -> Dict:
    """Apply post-parse patches to fix specific recipes."""
    name = recipe["name"]

    patch = RECIPE_PATCHES.get(name)
    if patch:
        # Ingredient replacements
        for old, new in patch.get("ingredient_replace", []):
            recipe["ingredients"] = [
                new if old.lower() in ing.lower() else ing
                for ing in recipe["ingredients"]
            ]
            recipe["optional_ingredients"] = [
                new if old.lower() in ing.lower() else ing
                for ing in recipe["optional_ingredients"]
            ]

        # Ingredient removals
        for remove_item in patch.get("ingredient_remove", []):
            recipe["ingredients"] = [
                ing for ing in recipe["ingredients"]
                if remove_item.lower() not in ing.lower()
            ]
            recipe["optional_ingredients"] = [
                ing for ing in recipe["optional_ingredients"]
                if remove_item.lower() not in ing.lower()
            ]

        # Markdown replacements
        for old_md, new_md in patch.get("md_replace", []):
            recipe["full_recipe_md"] = recipe["full_recipe_md"].replace(old_md, new_md)

        print(f"  PATCHED: {name}")

    # Mandeldrink hint
    if name in MANDELDRINK_RECIPES:
        recipe["trennkost_hinweis"] = MANDELDRINK_HINT
        if "mandeldrink" not in recipe.get("tags", []):
            recipe["tags"].append("mandeldrink")
        print(f"  HINT: {name} (Mandeldrink)")

    return recipe


def parse_recipes_file(filepath: str) -> List[Dict]:
    """Parse the markdown file into structured recipe dicts."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    recipes = []
    current_section = ""

    sections = re.split(r"^## ", content, flags=re.MULTILINE)

    for section_block in sections[1:]:
        section_lines = section_block.strip().split("\n")
        current_section = section_lines[0].strip()

        recipe_blocks = re.split(r"^### ", section_block, flags=re.MULTILINE)

        for recipe_block in recipe_blocks[1:]:
            lines = recipe_block.strip().split("\n")
            if not lines:
                continue

            recipe_name = _normalize_quotes(lines[0].strip())

            if recipe_name in EXCLUDED_RECIPES:
                print(f"  EXCLUDED: {recipe_name}")
                continue

            time_str = ""
            servings = ""
            for line in lines[1:5]:
                if "Zeit:" in line:
                    time_match = re.search(r"Zeit:\*?\*?\s*(.*?)\s*\|", line)
                    if time_match:
                        time_str = time_match.group(1).strip()
                    portions_match = re.search(r"Portionen:\*?\*?\s*(.*?)$", line)
                    ergibt_match = re.search(r"Ergibt:\*?\*?\s*(.*?)$", line)
                    if portions_match:
                        servings = portions_match.group(1).strip()
                    elif ergibt_match:
                        servings = ergibt_match.group(1).strip()

            time_minutes = parse_time(time_str)

            ingredient_lines = []
            in_ingredients = False

            for line in lines:
                if line.strip() == "#### Zutaten":
                    in_ingredients = True
                    continue
                if line.strip().startswith("#### ") and in_ingredients:
                    in_ingredients = False
                    continue
                if in_ingredients:
                    ingredient_lines.append(line)

            ingredients, optional_ingredients = extract_ingredients(ingredient_lines)

            category = detect_category(recipe_name, ingredients, optional_ingredients, current_section)
            tags = detect_tags(recipe_name, ingredients, time_minutes, current_section, category)
            full_recipe_md = f"### {recipe_name}\n" + "\n".join(lines[1:])

            recipe = {
                "id": slugify(recipe_name),
                "name": recipe_name,
                "section": current_section,
                "time_minutes": time_minutes,
                "servings": servings,
                "ingredients": ingredients,
                "optional_ingredients": optional_ingredients,
                "trennkost_category": category,
                "tags": tags,
                "full_recipe_md": full_recipe_md,
            }

            # Apply patches
            recipe = apply_patches(recipe)

            recipes.append(recipe)

    return recipes


def main():
    import sys

    input_path = sys.argv[1] if len(sys.argv) > 1 else "/Users/finn/Downloads/rezepte_de_clean_export_full_trennkostfix.md"
    output_path = sys.argv[2] if len(sys.argv) > 2 else str(
        Path(__file__).parent.parent / "app" / "data" / "recipes.json"
    )

    print(f"Parsing recipes from: {input_path}")
    recipes = parse_recipes_file(input_path)

    categories = {}
    for r in recipes:
        cat = r["trennkost_category"]
        categories[cat] = categories.get(cat, 0) + 1

    print(f"\nTotal recipes: {len(recipes)}")
    print(f"Categories: {json.dumps(categories, indent=2)}")
    print(f"Excluded: {len(EXCLUDED_RECIPES)} recipes")

    hints = [r["name"] for r in recipes if r.get("trennkost_hinweis")]
    if hints:
        print(f"Hinweise: {', '.join(hints)}")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(recipes, f, ensure_ascii=False, indent=2)
    print(f"\nWritten to: {output_path}")


if __name__ == "__main__":
    main()
