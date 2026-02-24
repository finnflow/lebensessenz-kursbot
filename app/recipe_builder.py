"""
Recipe builder pipeline.

Handles the RECIPE_FROM_INGREDIENTS flow:
  1. find_recipes_by_ingredient_overlap
  2. feasibility check (LLM Call 1)
  3. format DB recipe OR build custom recipe (LLM Call 2)
"""
import json
from typing import List, Dict, Optional

from app.clients import client, MODEL
from app.recipe_service import find_recipes_by_ingredient_overlap
from app.prompt_builder import SYSTEM_INSTRUCTIONS
from app.database import create_message


def _split_ingredients_by_group(ingredients: List[str]) -> Dict[str, List[str]]:
    """Categorize ingredients by Trennkost group using the ontology."""
    from trennkost.ontology import get_ontology
    ontology = get_ontology()
    result: Dict[str, List[str]] = {}
    for ing in ingredients:
        entry = ontology.lookup(ing)
        group = entry.group.value if entry else "UNKNOWN"
        result.setdefault(group, []).append(ing)
    return result


def _run_feasibility_check(
    available_ingredients: List[str],
    overlap_results: List[Dict],
) -> Dict:
    """
    Call 1: Pure logic — can user cook one of the DB recipes?

    Model: gpt-4o-mini, temperature=0.0, max_tokens=200
    Returns: {"decision": "use_db"|"create_custom", "recipe_id": str|null, "adapt_notes": str, "reason": str}
    """
    if not overlap_results:
        return {"decision": "create_custom", "recipe_id": None, "adapt_notes": "", "reason": "Keine passenden Rezepte in DB"}

    best = overlap_results[0]
    if best["overlap_score"] >= 0.85 and not best["missing_required"]:
        return {"decision": "use_db", "recipe_id": best["id"], "adapt_notes": "", "reason": "Sehr guter Match"}
    if best["overlap_score"] < 0.4:
        return {"decision": "create_custom", "recipe_id": None, "adapt_notes": "", "reason": "Zu wenig passende Zutaten in DB-Rezepten"}

    recipes_summary = []
    for r in overlap_results:
        missing_req = r["missing_required"]
        missing_opt = r["missing_optional"]
        recipes_summary.append(
            f"- {r['name']} (Overlap: {r['overlap_score']:.0%})\n"
            f"  Vorhanden: {', '.join(r['matched_ingredients']) or '–'}\n"
            f"  Fehlt (Pflicht): {', '.join(missing_req) or 'nichts'}\n"
            f"  Fehlt (Optional): {', '.join(missing_opt) or 'nichts'}"
        )
    recipes_text = "\n".join(recipes_summary)

    prompt = f"""Du entscheidest ob ein Rezept aus der Datenbank mit den verfügbaren Zutaten kochbar ist.

Verfügbare Zutaten: {', '.join(available_ingredients)}

Top Rezept-Matches aus DB:
{recipes_text}

Regeln:
- "use_db" wenn: Pflicht-Zutaten ≥70% vorhanden UND fehlende Zutaten sind nur Toppings/Dekoration/leicht weglassbar
- "create_custom" wenn: Mehrere Kern-Zutaten fehlen die das Gericht ausmachen
- adapt_notes: kurzer Hinweis was weggelassen/ersetzt werden kann (max 1 Satz, leer wenn use_db reibungslos)

Antworte NUR mit JSON:
{{"decision": "use_db" | "create_custom", "recipe_id": "<id_des_besten_rezepts>" | null, "adapt_notes": "<hinweis>", "reason": "<kurze_begründung>"}}"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=200,
            timeout=5,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()
        result = json.loads(raw)
        print(f"[RECIPE_FROM_ING] Feasibility → decision={result.get('decision')!r} recipe_id={result.get('recipe_id')!r}")
        return result
    except Exception as e:
        print(f"[RECIPE_FROM_ING] Feasibility check failed (non-fatal): {e}")
        if best["overlap_score"] >= 0.7:
            return {"decision": "use_db", "recipe_id": best["id"], "adapt_notes": "", "reason": "Fallback: overlap ≥ 0.7"}
        return {"decision": "create_custom", "recipe_id": None, "adapt_notes": "", "reason": "Fallback: overlap < 0.7"}


def _run_custom_recipe_builder(
    available_ingredients: List[str],
    is_breakfast: bool = False,
) -> str:
    """
    Call 2: Creative — builds a custom recipe from available ingredients.
    Only called when Call 1 → "create_custom".

    Model: gpt-4o-mini, temperature=0.3, max_tokens=800
    """
    groups = _split_ingredients_by_group(available_ingredients)
    obst_items = groups.get("OBST", []) + groups.get("TROCKENOBST", [])
    kh_items = groups.get("KH", [])
    neutral_items = groups.get("NEUTRAL", [])
    fett_items = groups.get("FETT", [])
    milch_items = groups.get("MILCH", [])

    two_option_breakfast = is_breakfast and bool(obst_items) and bool(kh_items or neutral_items or milch_items)

    if two_option_breakfast:
        kh_cluster = kh_items + neutral_items + fett_items + milch_items
        ingredients_block = (
            f"Zutaten Gruppe A (Obst-Frühstück): {', '.join(obst_items)}\n"
            f"Zutaten Gruppe B (KH-Frühstück): {', '.join(kh_cluster)}"
        )
        breakfast_note = f"""

FRÜHSTÜCK — GENAU 2 GETRENNTE REZEPTE PFLICHT (NIEMALS kombinieren!):
OPTION A – Obst-Frühstück: Verwende AUSSCHLIESSLICH: {', '.join(obst_items)}
OPTION B – KH-Frühstück: Verwende AUSSCHLIESSLICH: {', '.join(kh_cluster) if kh_cluster else 'keine KH-Zutaten verfügbar'}
Obst darf NICHT in Option B erscheinen. KH/Milch darf NICHT in Option A erscheinen.
Erstelle GENAU ZWEI Rezepte: Option A (Obst) und Option B (KH). Kein drittes Rezept."""
        single_option_note = "Erstelle GENAU ZWEI Rezepte wie oben angegeben."
    elif is_breakfast and obst_items:
        ingredients_block = ', '.join(available_ingredients)
        breakfast_note = f"\n- Frühstück Obst-Variante: Verwende NUR Obst: {', '.join(obst_items)}"
        single_option_note = "Wenn mehrere sinnvolle Varianten möglich sind, präsentiere die beste eine Option."
    elif is_breakfast:
        ingredients_block = ', '.join(available_ingredients)
        breakfast_note = "\n- Frühstück: Nur KH-Variante (kein Obst vorhanden)"
        single_option_note = "Wenn mehrere sinnvolle Varianten möglich sind, präsentiere die beste eine Option."
    else:
        ingredients_block = ', '.join(available_ingredients)
        breakfast_note = ""
        single_option_note = "Wenn mehrere sinnvolle Varianten möglich sind (z.B. KH- oder Protein-Variante), präsentiere die beste eine Option."

    prompt = f"""Erstelle ein trennkostkonformes Rezept ausschließlich aus diesen Zutaten:
{ingredients_block}

REGELN (strikt einhalten):
- Verwende NUR die oben genannten Zutaten (keine Extras ausser Gewürze/Öl/Salz)
- Kein KH + PROTEIN kombinieren
- Obst immer allein, nicht mit anderen Lebensmittelgruppen mischen
- Hülsenfrüchte nur mit Gemüse (NEUTRAL) kombinieren{breakfast_note}

FORMAT:
**[Rezeptname]**
⏱️ [Zeit] Min. | 🍽️ [Portionen]

**Zutaten:**
- [Zutat mit Menge]

**Zubereitung:**
1. [Schritt]

{single_option_note}
Halte die Antwort kompakt und praktisch."""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=800,
            timeout=15,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"[RECIPE_FROM_ING] Custom builder failed: {e}")
        return f"Tut mir leid, ich konnte kein passendes Rezept aus diesen Zutaten erstellen: {', '.join(available_ingredients)}. Bitte versuche es erneut oder frage nach einem konkreten Gericht."


def format_recipe_directly(recipe: Dict) -> str:
    """
    Format recipe directly without LLM, for high-score matches (≥7.0).
    Guarantees immediate output without follow-up questions.
    """
    name = recipe['name']
    time = recipe.get('time_minutes', '?')
    servings = recipe.get('servings', '?')
    full_md = recipe.get('full_recipe_md', '')

    lines = []
    skip_next_time_line = False
    for line in full_md.split('\n'):
        stripped = line.strip()

        if line.startswith('### '):
            skip_next_time_line = True
            continue

        if skip_next_time_line and ('Zeit:' in stripped or 'Portionen:' in stripped or 'Ergibt:' in stripped):
            skip_next_time_line = False
            continue

        skip_next_time_line = False

        if line.startswith('#### '):
            lines.append('**' + line[5:] + '**')
        else:
            lines.append(line)

    formatted_body = '\n'.join(lines)

    intro = f"Hier ist das perfekte Rezept für dich:\n\n"
    header = f"**{name}**  \n⏱️ {time} Min. | 🍽️ {servings}\n\n"

    hint = ""
    if recipe.get('trennkost_hinweis'):
        hint = f"\n\n💡 **Hinweis:** {recipe['trennkost_hinweis']}\n"

    footer = "\n\nDieses Rezept stammt aus unserer kuratierten Rezeptdatenbank."

    return intro + header + formatted_body + hint + footer


def handle_recipe_from_ingredients(
    conversation_id: str,
    available_ingredients: List[str],
    is_breakfast: bool = False,
) -> str:
    """
    Full handler for RECIPE_FROM_INGREDIENTS mode.
    Replaces normal LLM call for this mode.

    1. find_recipes_by_ingredient_overlap(available_ingredients, limit=3)
    2. _run_feasibility_check(available_ingredients, overlap_results)  [Call 1]
    3. If "use_db": format DB recipe + adapt_notes
       If "create_custom": _run_custom_recipe_builder(available_ingredients)  [Call 2]
    4. save + return
    """
    print(f"[RECIPE_FROM_ING] Searching overlap for {len(available_ingredients)} ingredients")
    overlap_results = find_recipes_by_ingredient_overlap(available_ingredients, limit=3)
    for r in overlap_results:
        print(f"  → {r['name']} overlap={r['overlap_score']:.0%} missing_req={r['missing_required'][:3]}")

    feasibility = _run_feasibility_check(available_ingredients, overlap_results)
    decision = feasibility.get("decision", "create_custom")

    if decision == "use_db" and feasibility.get("recipe_id"):
        recipe_id = feasibility["recipe_id"]
        recipe = next((r for r in overlap_results if r["id"] == recipe_id), None)
        if recipe is None:
            recipe = overlap_results[0] if overlap_results else None

        if recipe:
            adapt_notes = feasibility.get("adapt_notes", "")
            response = format_recipe_directly(recipe)
            if adapt_notes:
                response += f"\n\n💡 **Hinweis:** {adapt_notes}"
            create_message(conversation_id, "assistant", response)
            return response

    response = _run_custom_recipe_builder(available_ingredients, is_breakfast)
    response += "\n\n_Dieses Rezept wurde speziell für deine verfügbaren Zutaten erstellt._"
    create_message(conversation_id, "assistant", response)
    return response
