#!/usr/bin/env python3
"""
Import der restlichen Rezepte aus rezepte_gesamtuebersicht.md.

Neue Kategorie ÜBERGANG: technisch nicht 100% trennkostkonform, aber
als kuratierte Übergangslösung empfohlen (besser als unkontrollierte Alternativen).
"""
import json
from pathlib import Path

OUTPUT = Path("app/data/recipes.json")

NEW_RECIPES = [

    # ── Dressings für stärkehaltige / KH-Gerichte ─────────────────────

    {
        "id": "dressing-zitronen-kraeuter-kh",
        "name": "Zitronen-Kräuter-Dressing (zu KH)",
        "section": "Dressings",
        "time_minutes": 5,
        "servings": "1",
        "ingredients": ["Zitronensaft", "Senf", "Kräuter"],
        "optional_ingredients": [],
        "trennkost_category": "NEUTRAL",
        "tags": ["vegan", "dressing", "kh-geeignet", "schnell", "ölfrei"],
        "_source": "von Ricarda",
        "full_recipe_md": (
            "**Zitronen-Kräuter-Dressing (zu KH)**\n"
            "⏱️ 5 Min. | 🍽️ 1 Portion\n\n"
            "**Zutaten:**\n"
            "- 2 EL Zitronensaft\n"
            "- 1 TL Senf\n"
            "- 1 EL Wasser\n"
            "- frische Kräuter\n"
            "- Salz, Pfeffer\n\n"
            "**Zubereitung:**\n"
            "1. Alle Zutaten gründlich miteinander mixen und abschmecken.\n\n"
            "💡 Passt super zu stärkehaltigen Gerichten (Kartoffeln, Reis, Brot etc.)."
        ),
    },
    {
        "id": "dressing-essig-senf-vinaigrette",
        "name": "Essig-Senf-Vinaigrette (zu KH)",
        "section": "Dressings",
        "time_minutes": 5,
        "servings": "1",
        "ingredients": ["Apfelessig", "Senf"],
        "optional_ingredients": [],
        "trennkost_category": "NEUTRAL",
        "tags": ["vegan", "dressing", "kh-geeignet", "schnell", "ölfrei"],
        "_source": "von Ricarda",
        "full_recipe_md": (
            "**Essig-Senf-Vinaigrette (zu KH)**\n"
            "⏱️ 5 Min. | 🍽️ 1 Portion\n\n"
            "**Zutaten:**\n"
            "- 1 EL Apfelessig\n"
            "- 1 TL scharfer Senf\n"
            "- 2 EL Wasser\n"
            "- 1 Prise Knoblauchpulver\n"
            "- Salz, Pfeffer\n\n"
            "**Zubereitung:**\n"
            "1. Alle Zutaten gründlich miteinander mixen und abschmecken."
        ),
    },
    {
        "id": "dressing-balsamico",
        "name": "Balsamico-Dressing (zu KH)",
        "section": "Dressings",
        "time_minutes": 5,
        "servings": "1",
        "ingredients": ["Balsamico", "Senf"],
        "optional_ingredients": ["Dattelsirup"],
        "trennkost_category": "NEUTRAL",
        "tags": ["vegan", "dressing", "kh-geeignet", "schnell", "ölfrei"],
        "_source": "von Ricarda",
        "full_recipe_md": (
            "**Balsamico-Dressing (zu KH)**\n"
            "⏱️ 5 Min. | 🍽️ 1 Portion\n\n"
            "**Zutaten:**\n"
            "- 2 EL Balsamico\n"
            "- 1 TL Dattelsirup\n"
            "- 1 TL Senf\n"
            "- 2–3 EL Wasser\n"
            "- Salz, Pfeffer\n\n"
            "**Zubereitung:**\n"
            "1. Alle Zutaten gründlich miteinander mixen und abschmecken."
        ),
    },
    {
        "id": "dressing-gurke-dill",
        "name": "Gurke-Dill-Dressing (zu KH)",
        "section": "Dressings",
        "time_minutes": 5,
        "servings": "1",
        "ingredients": ["Gurke", "Zitronensaft", "Senf", "Dill"],
        "optional_ingredients": [],
        "trennkost_category": "NEUTRAL",
        "tags": ["vegan", "dressing", "kh-geeignet", "schnell", "ölfrei", "rohkost"],
        "_source": "von Ricarda",
        "full_recipe_md": (
            "**Gurke-Dill-Dressing (zu KH)**\n"
            "⏱️ 5 Min. | 🍽️ 1 Portion\n\n"
            "**Zutaten:**\n"
            "- ½ Salatgurke\n"
            "- 1 TL Zitronensaft\n"
            "- 1 TL Senf\n"
            "- 1 TL fein gehackter Dill\n"
            "- Salz, Pfeffer\n\n"
            "**Zubereitung:**\n"
            "1. Alle Zutaten gründlich miteinander mixen und abschmecken."
        ),
    },
    {
        "id": "dressing-fettfreie-aioli",
        "name": "Fettfreie Aioli (zu KH)",
        "section": "Dressings",
        "time_minutes": 5,
        "servings": "1",
        "ingredients": ["Kartoffel", "Zitronensaft", "Knoblauch", "Senf", "Apfelessig"],
        "optional_ingredients": [],
        "trennkost_category": "KH",
        "tags": ["vegan", "dressing", "kh-geeignet", "schnell", "ölfrei"],
        "_source": "von Ricarda",
        "full_recipe_md": (
            "**Fettfreie Aioli (zu KH)**\n"
            "⏱️ 5 Min. | 🍽️ 1 Portion\n\n"
            "**Zutaten:**\n"
            "- 1 kleine gekochte Kartoffel\n"
            "- 2 EL Zitronensaft\n"
            "- 1 Knoblauchzehe\n"
            "- ½ TL Senf\n"
            "- 1 TL Apfelessig\n"
            "- 2–3 EL Wasser\n"
            "- Salz, Pfeffer\n\n"
            "**Zubereitung:**\n"
            "1. Alle Zutaten gründlich miteinander mixen und abschmecken.\n\n"
            "💡 Kartoffelbasis macht dieses Dressing zu einer KH-freundlichen Aioli ohne Öl."
        ),
    },
    {
        "id": "dressing-chili-dattel-limette",
        "name": "Chili-Dattel-Limetten-Dressing (zu KH)",
        "section": "Dressings",
        "time_minutes": 5,
        "servings": "1",
        "ingredients": ["Limette", "Datteln", "Chili", "Apfelessig", "Senf"],
        "optional_ingredients": [],
        "trennkost_category": "ÜBERGANG",
        "tags": ["vegan", "dressing", "kh-geeignet", "schnell", "ölfrei", "süß-scharf"],
        "_source": "von Ricarda",
        "trennkost_hinweis": "Übergangsgericht: Datteln (Obst) + KH-Kontext ist technisch nicht ideal, aber in kleinen Mengen als Dressing vertretbar.",
        "full_recipe_md": (
            "**Chili-Dattel-Limetten-Dressing (zu KH)**\n"
            "⏱️ 5 Min. | 🍽️ 1 Portion\n\n"
            "**Zutaten:**\n"
            "- Saft einer Limette\n"
            "- 2–3 weiche Datteln (entsteint)\n"
            "- ½ kleine rote Chilischote\n"
            "- 1 EL Apfelessig\n"
            "- 1 TL Senf\n"
            "- 2–3 EL Wasser\n"
            "- Salz, Pfeffer\n\n"
            "**Zubereitung:**\n"
            "1. Alle Zutaten gründlich miteinander mixen und abschmecken.\n\n"
            "⚠️ Übergangsgericht: Datteln + KH ist nicht klassische Trennkost, als Dressing in kleinen Mengen aber vertretbar."
        ),
    },

    # ── Dressings für eiweißhaltige / PROTEIN-Gerichte ────────────────

    {
        "id": "dressing-avocado-zitronen-kraeuter",
        "name": "Avocado-Zitronen-Kräuter-Dressing (zu Protein)",
        "section": "Dressings",
        "time_minutes": 5,
        "servings": "1",
        "ingredients": ["Avocado", "Zitronensaft", "Kräuter"],
        "optional_ingredients": [],
        "trennkost_category": "NEUTRAL",
        "tags": ["vegan", "dressing", "protein-geeignet", "schnell", "fettreich"],
        "_source": "von Ricarda",
        "full_recipe_md": (
            "**Avocado-Zitronen-Kräuter-Dressing (zu Protein)**\n"
            "⏱️ 5 Min. | 🍽️ 1 Portion\n\n"
            "**Zutaten:**\n"
            "- ½ Avocado\n"
            "- Saft einer ½ Zitrone\n"
            "- 2 EL Wasser\n"
            "- frische Kräuter (z. B. Koriander, Dill)\n"
            "- Salz, Pfeffer\n\n"
            "**Zubereitung:**\n"
            "1. Alle Zutaten gründlich miteinander mixen und abschmecken.\n\n"
            "💡 Passt super zu Tofu oder Hülsenfrüchten mit Gemüse."
        ),
    },
    {
        "id": "dressing-sesam-ingwer",
        "name": "Sesam-Ingwer-Dressing (zu Protein)",
        "section": "Dressings",
        "time_minutes": 5,
        "servings": "1",
        "ingredients": ["Tahini", "Zitronensaft", "Ingwer", "Sojasauce"],
        "optional_ingredients": [],
        "trennkost_category": "NEUTRAL",
        "tags": ["vegan", "dressing", "protein-geeignet", "schnell", "asia"],
        "_source": "von Ricarda",
        "full_recipe_md": (
            "**Sesam-Ingwer-Dressing (zu Protein)**\n"
            "⏱️ 5 Min. | 🍽️ 1 Portion\n\n"
            "**Zutaten:**\n"
            "- 1 EL Sesampaste (Tahini)\n"
            "- 1 TL Zitronensaft / Apfelessig\n"
            "- 1 TL geriebener frischer Ingwer\n"
            "- 1 TL Wasser\n"
            "- Sojasauce\n"
            "- Salz, Pfeffer\n\n"
            "**Zubereitung:**\n"
            "1. Alle Zutaten gründlich miteinander mixen und abschmecken."
        ),
    },
    {
        "id": "dressing-tofu",
        "name": "Tofu-Dressing (zu Gemüse)",
        "section": "Dressings",
        "time_minutes": 5,
        "servings": "1",
        "ingredients": ["Seidentofu", "Zitronensaft", "Kräuter"],
        "optional_ingredients": [],
        "trennkost_category": "ÜBERGANG",
        "tags": ["vegan", "dressing", "protein-geeignet", "schnell", "proteinreich"],
        "_source": "von Ricarda",
        "trennkost_hinweis": "Übergangsgericht: Tofu (Hülsenfrucht) als Dressing zu eiweißhaltigen Gerichten ist technisch HF+PROTEIN, aber als kleine Sauce vertretbar.",
        "full_recipe_md": (
            "**Tofu-Dressing (zu Gemüse)**\n"
            "⏱️ 5 Min. | 🍽️ 1 Portion\n\n"
            "**Zutaten:**\n"
            "- 2 EL Seidentofu / weicher Natur-Tofu\n"
            "- 1 TL Zitronensaft\n"
            "- Wasser zum Verdünnen\n"
            "- Kräuter\n"
            "- Salz, Pfeffer\n\n"
            "**Zubereitung:**\n"
            "1. Alle Zutaten gründlich miteinander mixen und abschmecken.\n\n"
            "⚠️ Übergangsgericht: Als kleine Sauce über Gemüse vertretbar."
        ),
    },
    {
        "id": "dressing-krauter-kokos",
        "name": "Kräuter-Kokos-Dressing (zu Protein)",
        "section": "Dressings",
        "time_minutes": 5,
        "servings": "1",
        "ingredients": ["Kokosjoghurt", "Zitronensaft", "Senf", "Kräuter"],
        "optional_ingredients": [],
        "trennkost_category": "NEUTRAL",
        "tags": ["vegan", "dressing", "protein-geeignet", "schnell"],
        "_source": "von Ricarda",
        "full_recipe_md": (
            "**Kräuter-Kokos-Dressing (zu Protein)**\n"
            "⏱️ 5 Min. | 🍽️ 1 Portion\n\n"
            "**Zutaten:**\n"
            "- 2 EL Kokosjoghurt\n"
            "- 1 TL Zitronensaft\n"
            "- 1 TL Senf\n"
            "- frische Kräuter (z. B. Petersilie, Dill, Schnittlauch)\n"
            "- Salz, Pfeffer\n\n"
            "**Zubereitung:**\n"
            "1. Alle Zutaten gründlich miteinander mixen und abschmecken."
        ),
    },
    {
        "id": "dressing-asia-kokos",
        "name": "Asia-Kokos-Dressing (zu Protein)",
        "section": "Dressings",
        "time_minutes": 5,
        "servings": "1",
        "ingredients": ["Kokosjoghurt", "Tamari", "Ingwer", "Limette", "Sesam"],
        "optional_ingredients": [],
        "trennkost_category": "NEUTRAL",
        "tags": ["vegan", "dressing", "protein-geeignet", "schnell", "asia"],
        "_source": "von Ricarda",
        "full_recipe_md": (
            "**Asia-Kokos-Dressing (zu Protein)**\n"
            "⏱️ 5 Min. | 🍽️ 1 Portion\n\n"
            "**Zutaten:**\n"
            "- 2 EL Kokosjoghurt\n"
            "- 1 TL Tamari (glutenfreie Sojasauce)\n"
            "- ½ TL geriebener frischer Ingwer\n"
            "- 1 TL Limettensaft\n"
            "- 1 TL Sesam\n"
            "- Salz, Pfeffer\n\n"
            "**Zubereitung:**\n"
            "1. Alle Zutaten gründlich miteinander mixen und abschmecken."
        ),
    },
    {
        "id": "dressing-asia-tahini",
        "name": "Asia-Tahini-Dressing (zu Protein)",
        "section": "Dressings",
        "time_minutes": 5,
        "servings": "1",
        "ingredients": ["Sojasauce", "Tahini", "Limette"],
        "optional_ingredients": ["Chili"],
        "trennkost_category": "NEUTRAL",
        "tags": ["vegan", "dressing", "protein-geeignet", "schnell", "asia"],
        "_source": "von Ricarda",
        "full_recipe_md": (
            "**Asia-Tahini-Dressing (zu Protein)**\n"
            "⏱️ 5 Min. | 🍽️ 1 Portion\n\n"
            "**Zutaten:**\n"
            "- 1 EL Sojasauce\n"
            "- 1 TL Tahini\n"
            "- 1 TL Limettensaft\n"
            "- 1 TL Wasser\n"
            "- Chili\n"
            "- Salz, Pfeffer\n\n"
            "**Zubereitung:**\n"
            "1. Alle Zutaten gründlich miteinander mixen und abschmecken."
        ),
    },

    # ── Süßes (vergessen) ──────────────────────────────────────────────

    {
        "id": "chia-schoko-pudding",
        "name": "Chia-Schoko-Pudding",
        "section": "Snacks & Süßes",
        "time_minutes": 5,
        "servings": "1",
        "ingredients": ["Chiasamen", "Mohn", "Kokosdrink"],
        "optional_ingredients": ["Ahornsirup", "Mandeln", "Kokosflocken"],
        "trennkost_category": "NEUTRAL",
        "tags": ["vegan", "schnell", "overnight", "omega3", "süß"],
        "_source": "von Ricarda",
        "full_recipe_md": (
            "**Chia-Schoko-Pudding**\n"
            "⏱️ 5 Min. (+ über Nacht) | 🍽️ 1 Portion\n\n"
            "**Zutaten:**\n"
            "- 20 g Chiasamen\n"
            "- 2 EL Mohn (gemahlen)\n"
            "- 200 ml Kokosdrink (oder beliebiger Pflanzendrink)\n"
            "- 1–2 TL Ahornsirup oder Süßungsmittel\n"
            "- optional: Vanille\n\n"
            "*Zum Servieren (optional):*\n"
            "- Kokosflocken, Mandeln, Kakao-Nibs\n\n"
            "**Zubereitung:**\n"
            "1. Alle Zutaten am Vorabend miteinander vermischen.\n"
            "2. Über Nacht in den Kühlschrank stellen.\n"
            "3. Am nächsten Morgen nach Wunsch toppen.\n\n"
            "💡 Super zeitsparend — am Vorabend vorbereiten!"
        ),
    },

    # ── ÜBERGANGSGERICHTE ──────────────────────────────────────────────
    # Technisch nicht 100% trennkostkonform, aber als kuratierte
    # Übergangslösung empfohlen (besser als unkontrollierte Alternativen).

    {
        "id": "palak-paneer-tofu",
        "name": "Indisches Palak Paneer (mit Tofu)",
        "section": "Mittag / Herzhaft",
        "time_minutes": 20,
        "servings": "1",
        "ingredients": ["Tofu", "Spinat", "Vollkornreis", "Kokosjoghurt", "Zwiebel", "Knoblauch", "Ingwer"],
        "optional_ingredients": ["Koriander"],
        "trennkost_category": "ÜBERGANG",
        "tags": ["vegan", "indisch", "calcium", "proteinreich"],
        "_source": "von Ricarda",
        "trennkost_hinweis": "Übergangsgericht: Tofu (Hülsenfrucht) + Vollkornreis (KH) sind nach Trennkost-Regeln nicht ideal, aber als nährstoffreiche Übergangslösung empfohlen.",
        "full_recipe_md": (
            "**Indisches Palak Paneer (mit Tofu)**\n"
            "⏱️ 20 Min. | 🍽️ 1 Portion\n\n"
            "⚠️ *Übergangsgericht* — reich an Nährstoffen, aber Tofu + Reis nicht klassische Trennkost.\n\n"
            "**Zutaten:**\n"
            "- 100 g Natur-Tofu\n"
            "- 250–300 g frischer Spinat oder TK\n"
            "- 80–100 g Vollkornreis\n"
            "- 1 kleine Zwiebel\n"
            "- 1 Knoblauchzehe\n"
            "- 1 Stück Ingwer (2 cm)\n"
            "- 1–2 EL ungesüßter Kokosjoghurt\n"
            "- ½ TL Kreuzkümmel, Kurkuma, Korianderpulver\n"
            "- 1 TL Zitronensaft\n"
            "- Salz, Pfeffer\n\n"
            "**Zubereitung:**\n"
            "1. Tofu marinieren: in Würfel schneiden, mit Zitronensaft, Kurkuma, Salz mischen. 10 Min. ziehen lassen, dann in Wasser mit Gemüsebrühe dünsten.\n"
            "2. Reis nach Packungshinweis kochen.\n"
            "3. Spinatbasis: Zwiebeln, Knoblauch, Ingwer hacken und glasig dünsten.\n"
            "4. Gewürze und Kokosjoghurt einrühren, glatt mixen.\n"
            "5. Tofuwürfel unter die Spinatmasse heben. Mit Reis servieren.\n\n"
            "💡 Statt normalem Tofu kann auch 'Mandel-Tofu' verwendet werden — noch cremiger!"
        ),
    },
    {
        "id": "spiegelei-linsenwaffel",
        "name": "Spiegelei auf Linsenwaffel",
        "section": "Snacks & Süßes",
        "time_minutes": 5,
        "servings": "1",
        "ingredients": ["Ei", "Hummus", "Linsenwaffel"],
        "optional_ingredients": ["Sprossen", "Chiliflocken"],
        "trennkost_category": "ÜBERGANG",
        "tags": ["vegetarisch", "schnell", "proteinreich", "snack"],
        "_source": "von Ricarda",
        "trennkost_hinweis": "Übergangsgericht: Ei (Protein) + Linsenwaffel/Hummus (Hülsenfrucht) ist nicht klassische Trennkost, aber als proteinreicher Snack empfohlen.",
        "full_recipe_md": (
            "**Spiegelei auf Linsenwaffel**\n"
            "⏱️ 5 Min. | 🍽️ 1 Portion\n\n"
            "⚠️ *Übergangsgericht* — Ei + Linsenwaffel/Hummus nicht klassische Trennkost.\n\n"
            "**Zutaten:**\n"
            "- 1 Ei\n"
            "- 1 EL Hummus\n"
            "- 1 Linsenwaffel\n"
            "- Salz, weißer Pfeffer\n\n"
            "*Zum Servieren (optional):*\n"
            "- Sprossen / Micro-greens\n"
            "- Chili-Flocken\n\n"
            "**Zubereitung:**\n"
            "1. Spiegelei in der Pfanne braten.\n"
            "2. Linsenwaffel mit Hummus bestreichen.\n"
            "3. Spiegelei auflegen und nach Wunsch mit Chili-Flocken und Sprossen garnieren.\n\n"
            "💡 Schneller Snack mit ordentlich Protein!"
        ),
    },
    {
        "id": "blitz-hafer-kekse",
        "name": "Blitz-Hafer-Kekse",
        "section": "Snacks & Süßes",
        "time_minutes": 25,
        "servings": "1",
        "ingredients": ["Banane", "Haferflocken"],
        "optional_ingredients": ["Zartbitter-Schokolade"],
        "trennkost_category": "ÜBERGANG",
        "tags": ["vegan", "süß", "backen", "zink"],
        "_source": "von Ricarda",
        "trennkost_hinweis": "Übergangsgericht: Banane (Obst) + Haferflocken (KH) ist nicht klassische Trennkost, aber als natürlicher Süßsnack ohne Industriezucker empfohlen.",
        "full_recipe_md": (
            "**Blitz-Hafer-Kekse**\n"
            "⏱️ 25 Min. | 🍽️ 1 Portion\n\n"
            "⚠️ *Übergangsgericht* — Banane + Haferflocken nicht klassische Trennkost.\n\n"
            "**Zutaten:**\n"
            "- 1 Banane\n"
            "- 60 g zarte Haferflocken\n"
            "- 1–2 EL Zartbitter-Schoko-Tropfen\n"
            "- 1 Prise Salz\n\n"
            "**Zubereitung:**\n"
            "1. Ofen auf 180 °C Ober-/Unterhitze vorheizen, Backblech mit Backpapier auslegen.\n"
            "2. Banane mit Gabel fein zerdrücken.\n"
            "3. Haferflocken, Schoko-Tropfen und Salz untermischen.\n"
            "4. Portionsweise auf das Blech setzen, leicht plattdrücken.\n"
            "5. Ca. 15–20 Min. backen bis die Ränder leicht braun sind.\n\n"
            "💡 Luftdicht verpackt halten die Kekse mindestens 3 Tage."
        ),
    },
    {
        "id": "schoko-creme-bohnen",
        "name": "Schoko-Creme aus Bohnen",
        "section": "Snacks & Süßes",
        "time_minutes": 10,
        "servings": "1",
        "ingredients": ["Kidneybohnen", "Kakaopulver", "Ahornsirup"],
        "optional_ingredients": ["Mandeldrink", "Vanille"],
        "trennkost_category": "ÜBERGANG",
        "tags": ["vegan", "süß", "schnell", "proteinreich", "magnesium"],
        "_source": "von Ricarda",
        "trennkost_hinweis": "Übergangsgericht: Kidneybohnen (Hülsenfrucht) + Ahornsirup (KH) nicht klassische Trennkost, aber als proteinreiche Nascherei ohne Industriezucker empfohlen.",
        "full_recipe_md": (
            "**Schoko-Creme aus Bohnen**\n"
            "⏱️ 10 Min. | 🍽️ 1 Portion\n\n"
            "⚠️ *Übergangsgericht* — Hülsenfrüchte + KH nicht klassische Trennkost.\n\n"
            "**Zutaten:**\n"
            "- 200 g Kidneybohnen / schwarze Bohnen (gekocht)\n"
            "- 1 EL ungesüßtes Kakaopulver\n"
            "- 1–2 TL Ahornsirup oder Süßungsmittel\n"
            "- etwas Wasser oder ungesüßter Mandeldrink\n"
            "- 1 Prise Salz\n"
            "- optional: Vanille\n\n"
            "**Zubereitung:**\n"
            "1. Alle Zutaten fein pürieren, bis eine glatte Creme entsteht.\n"
            "2. Kalt servieren. Nach Wunsch mit Minze dekorieren.\n\n"
            "💡 Am Vorabend vorbereiten — hält gut im Kühlschrank."
        ),
    },
]

# ── Duplikat-Check & Merge ─────────────────────────────────────────────

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

# Statistik
by_cat = {}
for r in combined:
    c = r.get("trennkost_category", "?")
    by_cat[c] = by_cat.get(c, 0) + 1

print(f"✅ {len(added)} neue Rezepte importiert → {len(combined)} gesamt")
for r in added:
    print(f"   + {r['name']} ({r['trennkost_category']})")
if skipped:
    print(f"\n⚠️  {len(skipped)} übersprungen:")
    for s in skipped:
        print(f"   - {s}")

print("\n📊 Gesamtverteilung:")
for cat, count in sorted(by_cat.items()):
    print(f"   {cat}: {count}")
