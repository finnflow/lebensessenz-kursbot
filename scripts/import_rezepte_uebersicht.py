#!/usr/bin/env python3
"""
Import kompatible Rezepte aus rezepte_gesamtuebersicht.md in recipes.json.

Importiert: 6 Hauptrezepte + 1 Süßes (kompatibel)
NICHT importiert: Palak Paneer (HF+KH), Spiegelei/Linsenwaffel (PROTEIN+HF),
                  Hafer-Kekse (OBST+KH), Schoko-Creme aus Bohnen (HF+KH)
"""
import json
import re
from pathlib import Path

OUTPUT = Path("app/data/recipes.json")

NEW_RECIPES = [
    # ── A) Brotbeläge & Aufstriche ──────────────────────────────────
    {
        "id": "basic-avocado-creme",
        "name": "Basic Avocado-Creme",
        "section": "Brotbeläge & Aufstriche",
        "time_minutes": 10,
        "servings": "1",
        "ingredients": ["Avocado", "Zitronensaft"],
        "optional_ingredients": ["Kala Namak"],
        "trennkost_category": "NEUTRAL",
        "tags": ["vegan", "schnell", "aufstrich", "fettreich"],
        "full_recipe_md": (
            "**Basic Avocado-Creme**\n"
            "⏱️ 5–10 Min. | 🍽️ 1 Portion\n\n"
            "**Zutaten:**\n"
            "- 1 reife Avocado\n"
            "- etwas Zitronensaft\n"
            "- Salz, Pfeffer\n"
            "- optional: Kala Namak (für Ei-Geschmack)\n\n"
            "**Zubereitung:**\n"
            "1. Alle Zutaten gründlich miteinander mixen und abschmecken.\n\n"
            "💡 Passt super zu stärkehaltigen Gerichten (Kartoffeln, Reis, Mais, Brot)."
        ),
    },
    {
        "id": "tomate-zucchini-aufstrich",
        "name": "Tomate-Zucchini-Aufstrich",
        "section": "Brotbeläge & Aufstriche",
        "time_minutes": 10,
        "servings": "1",
        "ingredients": ["Zucchini", "Tomate", "Sonnenblumenkerne"],
        "optional_ingredients": [],
        "trennkost_category": "NEUTRAL",
        "tags": ["vegan", "schnell", "aufstrich"],
        "full_recipe_md": (
            "**Tomate-Zucchini-Aufstrich**\n"
            "⏱️ 5–10 Min. | 🍽️ 1 Portion\n\n"
            "**Zutaten:**\n"
            "- 1 kleine gedünstete Zucchini\n"
            "- 1 Tomate\n"
            "- 1 EL Sonnenblumenkerne oder Nussmus\n"
            "- 1 TL Zitronensaft\n"
            "- Salz, Pfeffer\n\n"
            "**Zubereitung:**\n"
            "1. Alle Zutaten gründlich miteinander mixen und abschmecken."
        ),
    },
    {
        "id": "paprika-sonnenblumenkerne-aufstrich",
        "name": "Paprika-Sonnenblumenkerne-Aufstrich",
        "section": "Brotbeläge & Aufstriche",
        "time_minutes": 10,
        "servings": "1",
        "ingredients": ["Paprika", "Sonnenblumenkerne", "Apfelessig"],
        "optional_ingredients": [],
        "trennkost_category": "NEUTRAL",
        "tags": ["vegan", "schnell", "aufstrich"],
        "full_recipe_md": (
            "**Paprika-Sonnenblumenkerne-Aufstrich**\n"
            "⏱️ 5–10 Min. | 🍽️ 1 Portion\n\n"
            "**Zutaten:**\n"
            "- 1 rote geröstete Paprika\n"
            "- 2 EL eingeweichte Sonnenblumenkerne\n"
            "- 1 TL Apfelessig\n"
            "- Salz, Pfeffer\n\n"
            "**Zubereitung:**\n"
            "1. Alle Zutaten gründlich miteinander mixen und abschmecken."
        ),
    },

    # ── C) Mittag / Herzhaft ──────────────────────────────────────
    {
        "id": "tofu-gemuesepfanne-rucola",
        "name": "Tofu-Gemüsepfanne mit Rucola",
        "section": "Mittag / Herzhaft",
        "time_minutes": 20,
        "servings": "1",
        "ingredients": ["Tofu", "Zucchini", "Paprika", "Brokkoli", "Rucola"],
        "optional_ingredients": ["Kokosflocken", "Mandeln", "Kakao-Nibs"],
        "trennkost_category": "HUELSENFRUECHTE",
        "tags": ["vegan", "proteinreich", "calcium"],
        "full_recipe_md": (
            "**Tofu-Gemüsepfanne mit Rucola**\n"
            "⏱️ 20 Min. | 🍽️ 1 Portion\n\n"
            "**Zutaten:**\n"
            "- 150 g Tofu\n"
            "- 1 Tasse Zucchini, Paprika, Brokkoli\n"
            "- 1 Handvoll frischer Rucola\n"
            "- 1 TL Sojasauce, 1 TL Sesamöl, frische Kräuter\n"
            "- Salz, Pfeffer, evtl. Chili\n\n"
            "**Zubereitung:**\n"
            "1. Den Tofu in Sesamöl und Sojasauce anbraten.\n"
            "2. Das Gemüse hinzugeben und bissfest garen.\n"
            "3. Den Rucola auf einen Teller geben, Tofu-Gemüse darüber verteilen.\n"
            "4. Mit Salz, Pfeffer und Chili abschmecken, mit Kräutern garnieren.\n\n"
            "💡 Mit etwas Chili wird das Gericht noch würziger und entzündungshemmend."
        ),
    },
    {
        "id": "gruenkohl-brokkoli-salat",
        "name": "Grünkohl-Brokkoli-Salat",
        "section": "Mittag / Herzhaft",
        "time_minutes": 20,
        "servings": "1",
        "ingredients": ["Grünkohl", "Brokkoli", "Tahini", "Zitronensaft", "Sojasauce"],
        "optional_ingredients": ["Sesam", "Kokosflocken", "Mandeln"],
        "trennkost_category": "NEUTRAL",
        "tags": ["vegan", "calcium", "rohkost"],
        "full_recipe_md": (
            "**Grünkohl-Brokkoli-Salat**\n"
            "⏱️ 20 Min. | 🍽️ 1 Portion\n\n"
            "**Zutaten:**\n"
            "- 1 Handvoll Grünkohl\n"
            "- 1 Tasse Brokkoli-Röschen\n"
            "- 1 TL Sesam\n"
            "- *Dressing:* 1 EL Tahini, 2 TL Zitronensaft, 1 TL Sojasauce, etwas Wasser\n"
            "- Salz, Pfeffer, evtl. Chili\n\n"
            "**Zubereitung:**\n"
            "1. Den Grünkohl kleinschneiden. Brokkoli-Röschen bissfest dämpfen.\n"
            "2. Aus Tahini, Zitronensaft, Sojasauce und Wasser das Dressing anrühren.\n"
            "3. Grünkohl und Brokkoli auf einen Teller, Dressing darüber verteilen.\n"
            "4. Mit Salz, Pfeffer, evtl. Chili würzen und mit Sesam bestreuen."
        ),
    },
    {
        "id": "cashew-tomatensauce-nudeln",
        "name": "Cremige Cashew-Tomatensauce mit Nudeln",
        "section": "Mittag / Herzhaft",
        "time_minutes": 20,
        "servings": "1",
        "ingredients": ["glutenfreie Spaghetti", "Cherry-Tomaten", "Knoblauch", "Zwiebel", "Cashewmus", "Olivenöl", "Basilikum"],
        "optional_ingredients": [],
        "trennkost_category": "KH",
        "tags": ["vegan", "pasta", "antioxidantien"],
        "full_recipe_md": (
            "**Cremige Cashew-Tomatensauce mit Nudeln**\n"
            "⏱️ 20 Min. | 🍽️ 1 Portion\n\n"
            "**Zutaten:**\n"
            "- 125 g glutenfreie Spaghetti (z. B. Reis-Spaghetti)\n"
            "- 250 g Cherry-Tomaten\n"
            "- 2 Knoblauchzehen\n"
            "- 1 kleine Zwiebel, kleingeschnitten\n"
            "- 1 Handvoll Basilikum\n"
            "- 1 EL Cashewmus\n"
            "- 1 EL Olivenöl\n"
            "- 1–2 TL Zitronensaft\n"
            "- Salz, Pfeffer, evtl. Chili\n\n"
            "**Zubereitung:**\n"
            "1. Cherry-Tomaten, Knoblauch und Zwiebel in Olivenöl anrösten.\n"
            "2. Mit Cashewmus und etwas Wasser im Mixer pürieren.\n"
            "3. Basilikum und Zitronensaft einrühren, nochmals mixen.\n"
            "4. Glutenfreie Nudeln bissfest kochen.\n"
            "5. Sauce über die Nudeln geben, mit Salz und Pfeffer abschmecken.\n\n"
            "💡 Die Sauce lässt sich auch mit rohen Cocktail-Tomaten zubereiten."
        ),
    },

    # ── F) Lust auf Süßes ─────────────────────────────────────────
    {
        "id": "datteln-mit-nussmus",
        "name": "Datteln mit Nussmus",
        "section": "Snacks & Süßes",
        "time_minutes": 10,
        "servings": "1",
        "ingredients": ["Datteln", "Nussmus"],
        "optional_ingredients": ["Kakaonibs", "Zartbitterschokolade"],
        "trennkost_category": "OBST",
        "tags": ["vegan", "schnell", "süß", "snack"],
        "full_recipe_md": (
            "**Datteln mit Nussmus**\n"
            "⏱️ 10 Min. | 🍽️ 1 Portion\n\n"
            "**Zutaten:**\n"
            "- Datteln (am besten Medjool oder Mazafati)\n"
            "- etwas Nussmus (Mandel-, Pistazien-, Erdnuss- oder Haselnussmus)\n"
            "- optional: Kakaonibs, etwas Zartbitterschokolade\n\n"
            "**Zubereitung:**\n"
            "1. Die Datteln zur Hälfte aufschneiden und entkernen.\n"
            "2. Etwas Nussmus in die Dattelhälften geben.\n"
            "3. Nach Wunsch mit Kakaonibs oder Schokolade toppen.\n\n"
            "💡 Mit Zartbitter-Schokolade auch schön zum Verschenken!"
        ),
    },
]

# ── Check für Duplikate & Merge ───────────────────────────────────────

existing = json.loads(OUTPUT.read_text(encoding="utf-8"))
existing_ids = {r["id"] for r in existing}
existing_names = {r["name"].lower() for r in existing}

added = []
skipped = []
for r in NEW_RECIPES:
    if r["id"] in existing_ids:
        skipped.append(f"ID-Duplikat: {r['name']}")
    elif r["name"].lower() in existing_names:
        skipped.append(f"Name-Duplikat: {r['name']}")
    else:
        added.append(r)

combined = existing + added
OUTPUT.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"✅ {len(added)} neue Rezepte importiert → {len(combined)} gesamt")
for r in added:
    print(f"   + {r['name']} ({r['trennkost_category']})")
if skipped:
    print(f"\n⚠️  {len(skipped)} übersprungen:")
    for s in skipped:
        print(f"   - {s}")

print("\n❌ NICHT importiert (Trennkost-inkompatibel):")
print("   - Indisches Palak Paneer: Tofu (HF) + Vollkornreis (KH) → R003")
print("   - Spiegelei auf Linsenwaffel: Ei (PROTEIN) + Hummus/Linsenwaffel (HF) → R004")
print("   - Blitz-Hafer-Kekse: Banane (OBST) + Haferflocken (KH) → R007")
print("   - Schoko-Creme aus Bohnen: Kidneybohnen (HF) + Ahornsirup (KH) + Kakao (UNKNOWN)")
print("\n⚠️  Bowl-Basis (B): Beschreibungstext, kein Rezept → übersprungen")
print("⚠️  Dressings (D): Zu trivial für Rezeptdatenbank → übersprungen")
