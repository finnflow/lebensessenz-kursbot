# Known Issues & Fixes - Lebensessenz Kursbot

Dokumentation aller entdeckten Probleme, Lösungen und Learnings.

---

## ✅ GELÖSTE PROBLEME

### 1. Parser: Natural Language als Food Items erkannt
**Problem:** Query "Ist Spaghetti Carbonara trennkost-konform? Bitte kurz begründen und Rückfragen stellen"
- Parser splittete auf "und" → "Rückfragen stellen" wurde als Zutat behandelt
- Führte zu UNKNOWN items → CONDITIONAL verdict statt NOT_OK

**Lösung:** `_extract_foods_from_question()` in analyzer.py
- Erkennt Fragen und sucht gezielt nach Compounds/Ontology-Items
- Splittet nur noch echte Zutatenlisten

**Datei:** `trennkost/analyzer.py:64-105`
**Commit:** Initial commit
**Status:** ✅ Fixed

---

### 2. Rezept-Endlos-Schleife
**Problem:** User fragt nach Rezept → Bot schlägt vor → User sagt "ja" → Bot fragt wieder statt Rezept zu geben

**Lösung:**
- System Instruction Rule 10: Rezept-Vorschläge erlaubt
- Explizite Anweisung: "Wenn User Rezept will → SOFORT vollständiges Rezept"
- Follow-up-Detection verbessert

**Datei:** `app/chat_service.py:84-88, 771-773`
**Status:** ✅ Fixed

---

### 3. Non-Konforme Alternativ-Vorschläge
**Problem:** User wählt "lieber den Reis" → Bot schlägt "Reis mit Hähnchen (separat)" vor
- Verletzt Trennkost-Regel: KH + Protein verboten, auch wenn "separat"

**Lösung:** Fix-Richtungen mit expliziten Verboten
- `_generate_fix_directions()`: "WICHTIG: Kein(e) Protein im Alternativgericht!"
- LLM-Instructions: Exklusive Gruppen betonen

**Datei:** `trennkost/analyzer.py:377-405`, `app/chat_service.py:719-722`
**Status:** ✅ Fixed

---

### 4. Smoothie-Ausnahme: Gewürze blockieren OK-Verdict
**Problem:** "Grüner Smoothie mit Banane, Spinat, Apfel, Ingwer, Wasser" → CONDITIONAL statt OK
- Spinat = BLATTGRUEN → sollte OK sein
- Aber Ingwer/Wasser = KRAEUTER → triggerte R013 (Obst + stärkearmes Gemüse verboten)

**Lösung:** `SMOOTHIE_SAFE_SUBGROUPS` erweitert
- Nicht nur BLATTGRUEN, sondern auch KRAEUTER erlaubt
- Gewürze/Wasser beeinflussen Verdauung nicht

**Datei:** `trennkost/engine.py:31-35, 224-228`
**Status:** ✅ Fixed

---

### 5. Wasser als Wassermelone erkannt
**Problem:** Ontologie-Lookup matched "Wasser" → "Wassermelone" (Substring-Match)

**Lösung:**
- "Wasser" in Ontologie hinzugefügt als NEUTRAL/KRAEUTER
- Exact-Match hat Priorität vor Substring-Match

**Datei:** `trennkost/data/ontology.csv:116`
**Status:** ✅ Fixed

---

### 6. Grüner Smoothie als UNKNOWN bei expliziten Zutaten
**Problem:** "Grüner Smoothie mit X, Y, Z" → "Grüner Smoothie" wird als Zutat behandelt statt Gericht-Name

**Lösung:** Parser erkennt Compounds als Gericht-Namen
- Wenn erster Teil nach Split ein Compound ist → Gericht-Name, Rest = Zutaten
- "Grüner Smoothie mit Banane, Spinat" → name="Grüner Smoothie", items=["Banane", "Spinat"]

**Datei:** `trennkost/analyzer.py:143-156`
**Status:** ✅ Fixed

---

### 7. Gewürze als unsicher flagged
**Problem:** Vision API erkennt "Basilikum", "Pfeffer" als uncertain → unnötige Rückfragen

**Lösung:** Filter uncertain items nach Subgroup
- NEUTRAL/KRAEUTER werden aus uncertain_items entfernt
- Gewürze beeinflussen Verdict nicht

**Datei:** `trennkost/analyzer.py:300-320`, `trennkost/data/ontology.csv:101-115`
**Status:** ✅ Fixed

---

### 8. CONDITIONAL schlägt zufällige Zutaten vor
**Problem:** Quinoa-Bowl (CONDITIONAL wegen Fett-Menge) → Bot erwähnt "Apfel, Ingwer, Wasser" obwohl nicht relevant

**Lösung:**
- Explizite CONDITIONAL-Instructions: "Schlage KEINE zusätzlichen Zutaten vor!"
- "Sprich NUR über Zutaten in der Gruppen-Liste"
- Formatted output: "KEINE OFFENEN FRAGEN" wenn alles klar

**Datei:** `app/chat_service.py:737-741, 723-727`
**Status:** ✅ Fixed (teilweise - Grüner Smoothie edge case bleibt)

---

### 9. Rezept-Request als Food Analysis erkannt
**Problem:** "hast du ein leckeres trennkost konformes gericht für mich heute?" → "bedingt OK", "Zutaten nicht zugeordnet"

**Lösung:** Recipe-Request-Patterns in `detect_food_query()`
- "hast du.*gericht", "gib.*gericht", "empfiehl.*gericht" → FALSE (keine Food-Query)
- Bot behandelt als normale Frage, fragt nach Präferenzen

**Datei:** `trennkost/analyzer.py:44-64`
**Status:** ✅ Fixed

---

### 10. Bild-Referenz → Fallback Sentence
**Problem:**
- Bot fragt: "Wie viel Fett ist enthalten?"
- User: "keine ahnung du siehst ja den teller"
- Bot: "Diese Information steht nicht im Kursmaterial" ❌

**Lösung:** System Instruction Rule 11 - Bild-Analyse Grenzen
- Erkennt Bild-Referenzen ("du siehst", "auf dem Foto", "keine Ahnung" auf Mengen-Frage)
- Macht realistische Schätzungen basierend auf typischen Portionsgrößen
- VERBOTEN: FALLBACK_SENTENCE bei Bild-Referenzen

**Datei:** `app/chat_service.py:89-100`
**Status:** ✅ Fixed

---

### 11. Server-Management: Port already in use
**Problem:** `uvicorn` läuft im Hintergrund, neuer Start schlägt fehl: "Address already in use"

**Lösung:**
```bash
kill -9 $(lsof -ti:8000)
```

**Best Practice:** Server mit CTRL+C stoppen, nicht Terminal schließen
**Status:** ✅ Documented

---

### 12. Fix-Direction Follow-up → Fallback Sentence
**Problem:**
- Bot: "Kartoffel + Rotbarsch nicht konform. Was möchtest du behalten?"
- User: "den rotbarsch"
- Bot: "Diese Information steht nicht im Kursmaterial" ❌

**Ursache:** Follow-up triggert Engine nicht → treated as general question → Fallback

**Lösung:** System Instruction Rule 12 + explizite else-branch Instructions
- Erkennt Follow-ups auf "Was möchtest du behalten?"
- "den Rotbarsch" / "die Kartoffel" = Antwort auf eigene Frage
- SOFORT Gericht vorschlagen, NIEMALS Fallback

**Datei:** `app/chat_service.py:101-113, 766-773`
**Status:** ✅ Fixed (zu testen)

---

### 13. Clarification Follow-up Loop (Matcha Latte)
**Problem:**
- Bot: "Matcha Latte bedingt ok. Welche Zutaten?"
- User: "hafermilch, wenig zucker, standard matcha pulver"
- Bot: "Matcha Latte bedingt ok. Welche Zutaten?" ← SCHLEIFE! ❌

**Ursache (ROOT CAUSE):** Items waren genuinely UNKNOWN → Engine triggerte CONDITIONAL → legitime Rückfrage
1. **Matcha/Matcha-Pulver** fehlte komplett in Ontologie → UNKNOWN
2. **Zucker** war als UNKNOWN markiert ("keine Trennkost-Gruppe")
3. **Hafermilch** matched generische "Pflanzenmilch" → ambiguity_flag=true → Rückfrage

**Lösung:** Ontologie erweitern (nicht nur Instructions!)
1. Matcha hinzugefügt als NEUTRAL/KRAEUTER (Grüntee-Pulver)
2. Zucker umklassifiziert von UNKNOWN → KH/GETREIDE (mit Warnung im Note-Feld)
3. Hafermilch/Mandelmilch/Sojamilch etc. als separate Einträge (nicht nur Synonyme von "Pflanzenmilch")
4. System Instruction Rule 13 - Schleifen-Schutz (zusätzlich)

**Test-Ergebnis:**
```
"Matcha Latte mit hafermilch, ein wenig zucker und normales matcha pulver"
→ Verdict: OK
→ Groups: NEUTRAL (Matcha) + KH (Hafermilch, Zucker)
→ Keine offenen Fragen ✅
```

**Datei:** `trennkost/data/ontology.csv:119,233,231-237`, `app/chat_service.py:114-121`
**Status:** ✅ Fixed (2025-02-11)

---

### 14. Anführungszeichen verhindern Item-Erkennung
**Problem:**
- Query OHNE Quotes: "rotbarsch mit kartoffeln ok?" → **NICHT OK** ✅ (korrekt)
- Query MIT Quotes: "\"rotbarsch mit kartoffeln ok?\"" → **OK** ❌ (FALSCH!)

**Ursache:** Regex-Pattern für Word Boundaries in `_extract_foods_from_question()`
- Pattern: `r'(?:^|[\s,;.(])' + name + r'(?:[\s,;.?!)]|$)'`
- Quotes (`"`, `'`) waren NICHT in den Boundary-Zeichen
- `"rotbarsch` → Quote ist keine Boundary → kein Match!
- `kartoffeln` → Space ist Boundary → Match! ✓
- Resultat: Nur Kartoffel erkannt, Rotbarsch fehlte → nur KH → OK (falsch!)

**Lösung:** Quotes zu Boundaries hinzufügen
```python
pattern = r'(?:^|[\s,;.("\'])' + re.escape(name) + r'(?:[\s,;.?!)"\'"]|$)'
```
- Jetzt werden `"`, `'` und `"` als Word Boundaries erkannt
- Alle Varianten funktionieren: ohne Quotes, mit `"..."`, mit `'...'`, mit `(...)`

**Test-Ergebnisse:**
```
rotbarsch mit kartoffeln ok?      → NOT_OK (2 groups) ✓
"rotbarsch mit kartoffeln ok?"    → NOT_OK (2 groups) ✓
'rotbarsch mit kartoffeln ok?'    → NOT_OK (2 groups) ✓
(rotbarsch mit kartoffeln ok?)    → NOT_OK (2 groups) ✓
```

**Datei:** `trennkost/analyzer.py:113-114`
**Status:** ✅ Fixed (2025-02-11)

---

### 15. Zucker-Gesundheitsempfehlung
**Problem:** Zucker (weißer Industriezucker) ist Trennkost-konform als KH, aber im Kurs als ungesund beschrieben

**Lösung:** INFO-Level Health Recommendation in Engine
- Neue Rule H001: Erkennt "Zucker" canonical name
- Verdict bleibt OK (Trennkost-konform), aber INFO-Problem wird hinzugefügt
- Empfehlung: "Besser Honig, Ahornsirup oder Kokosblütenzucker verwenden"
- LLM-Instruction: INFO-Probleme kurz und freundlich am Ende erwähnen

**Test:**
```
"Matcha Latte mit Hafermilch und Zucker"
→ Verdict: OK (Trennkost-konform: KH + KH + NEUTRAL)
→ INFO: Zucker sollte durch gesündere Alternativen ersetzt werden
```

**Datei:** `trennkost/engine.py:143-160`, `app/chat_service.py:750-753`
**Status:** ✅ Fixed (2025-02-11)

---

### 16. Compound + Explizite Zutaten → Parser ignoriert Zutaten
**Problem:**
- User: "Burger mit Tempeh, Salat, Gurken, Ketchup ok?"
- Bot: "Bedingt OK. Enthält der Burger noch Salat, Gurken oder Ketchup?" ❌
- Parser fand nur "Burger" → "Brot", ignorierte alle expliziten Zutaten

**Ursache:**
1. **Parser-Bug** in `_extract_foods_from_question()` (analyzer.py:100-101)
   - Wenn Compound gefunden → RETURN sofort
   - Explizite Zutaten nach "mit" wurden NIE geparst
2. **Engine-Bug** in `_build_questions()` (engine.py:323-329)
   - Compound clarification wurde IMMER hinzugefügt
   - Auch wenn User schon explizite Zutaten genannt hatte

**Lösung:**
1. **Parser Fix:** Compound finden, ABER weiter nach Zutaten suchen
   ```python
   found_compound = compound_name if found else None
   # Continue parsing for explicit ingredients...
   if found_compound and found_items:
       return [{"name": found_compound, "items": found_items}]
   ```
2. **Engine Fix:** Skip clarification wenn explizite Items vorhanden
   ```python
   has_explicit_items = len(analysis.items) > 0 and not all(item.assumed for item in analysis.items)
   if compound and needs_clarification and not has_explicit_items:
       # only ask if no explicit ingredients
   ```
3. **Ontologie-Erweiterung:**
   - "Salat" als Synonym zu Kopfsalat hinzugefügt
   - "Ketchup" als NEUTRAL/KRAEUTER hinzugefügt

**Test-Ergebnis:**
```
"Burger mit Tempeh, Brot, Salat, Gurken, Ketchup"
→ Erkannt: Tempeh (HUELSE), Brot (KH), Kopfsalat (NEUTRAL), Gurke (NEUTRAL), Ketchup (NEUTRAL)
→ Verdict: NOT_OK (HUELSE + KH verboten)
→ Keine unnötigen Rückfragen ✅
```

**Datei:** `trennkost/analyzer.py:92-130`, `trennkost/engine.py:322-330`, `trennkost/data/ontology.csv`
**Status:** ✅ Fixed (2025-02-11)

---

### 17. Adjektive als UNKNOWN Items erkannt + Fallback bei Korrektur
**Problem:**
- User: "normaler mit Hafermilch und Zucker"
- Bot: "normale Milch + Hafermilch → bedingt OK" (interpretiert 2 Milchsorten!)
- User: "aber hab doch Hafermilch keine normale Milch"
- Bot: "Diese Information steht nicht im bereitgestellten Kursmaterial." ❌ (Fallback!)

**Ursache:**
1. **Adjektiv-Problem:** "normaler" wird als UNKNOWN Food Item behandelt
   - Parser splittet auf "mit"/"und" → ["normaler", "hafermilch", "ein wenig zucker"]
   - "normaler" ist ein Adjektiv (beschreibt Matcha Latte), KEINE Zutat
2. **Fallback bei Korrektur:** Bot erkennt Klarstellung nicht als Follow-up
   - User korrigiert Missverständnis → Bot denkt es ist neue Kursmaterial-Frage
   - Rule 3 AUSNAHMEN deckte Korrekturen nicht ab

**Lösung:**
1. **Adjektiv-Blacklist:** `_ADJECTIVES_TO_IGNORE` Set erstellt
   - 30+ häufige deutsche Adjektive: normaler, frischer, veganer, glutenfreier, etc.
   - Filter in `_extract_foods_from_question()` und `_parse_text_input()`
2. **Erweiterte Rule 3 AUSNAHMEN:**
   - Neu: "Korrekturen/Klarstellungen des Users (z.B. 'aber ich hab doch X gesagt')"
3. **Neue Rule 14 - KORREKTUR-ERKENNUNG:**
   - Explizite Anweisung: Missverständnisse erkennen, entschuldigen, re-analysieren
   - Muster: "aber ich hab doch", "nein, keine X", "hab doch keine X"
   - VERBOTEN: Fallback bei Korrekturen

**Test-Ergebnisse:**
```
"normaler mit Hafermilch und Zucker"
→ Dish: hafermilch + ein wenig zucker (✅ "normaler" gefiltert)
→ Verdict: OK (KH + KH erlaubt)
→ H001 INFO: Zucker-Warnung
→ Keine UNKNOWN Items mehr ✅
```

**Datei:** `trennkost/analyzer.py:39-60,140-142,198-200`, `app/chat_service.py:68-73,117-126`
**Status:** ✅ Fixed (2025-02-11)

---

### 18. Verschiedene Proteinquellen kombiniert → OK statt NOT_OK
**Problem:**
- User: "Jar breakfast: fried chicken, poached egg and pickle"
- Bot: "Das Jar breakfast ist trennkost-konform" ❌ (FALSCH!)
- Engine gab OK für Hähnchen (FLEISCH) + Ei (EIER)
- Aber Kursmaterial sagt klar: "Fisch, Fleisch, Eier: NICHT mit anderen Proteinreichen Lebensmitteln kombinieren"

**Ursache:**
- Rules hatten:
  - ✅ R001: KH + PROTEIN = NOT_OK
  - ✅ R002: KH + MILCH = NOT_OK
  - ✅ R006: PROTEIN + MILCH = NOT_OK
  - ❌ **FEHLT: PROTEIN + PROTEIN (verschiedene Subgruppen) = NOT_OK**
- PROTEIN Gruppe hat 3 Subgruppen: FLEISCH, FISCH, EIER
- Kursmaterial (Modul 1.1, Seite 4): "NICHT mit anderen Proteinreichen Lebensmitteln kombinieren"
- Kursmaterial (Modul 1.1, Seite 1): "Nur ein konzentriertes Lebensmittel pro Mahlzeit"
- Kombination von verschiedenen Protein-Subgruppen war nicht verboten

**Lösung:**
- Neue Regel **R018** nach Regel-Loop in `engine.py` (analog zu H001 Zucker-Check)
- Prüft: `len(subgroups_found.get("PROTEIN", set())) >= 2` → NOT_OK
- Erlaubt: Hähnchen + Rind (beide FLEISCH), Lachs + Thunfisch (beide FISCH)
- Verboten: Hähnchen + Ei (FLEISCH + EIER), Lachs + Ei (FISCH + EIER), Hähnchen + Lachs (FLEISCH + FISCH)

**Test-Ergebnisse:**
```
"gebratenes Hähnchen, pochiertes Ei, eingelegte Gurke" (Jar breakfast)
→ Verdict: NOT_OK ✅
→ Problem: R018 - Verschiedene Proteinquellen nicht kombinieren
→ Affected: ['pochiertes Ei → Ei (EIER)', 'gebratenes Hähnchen → Hähnchen (FLEISCH)']

"Hähnchen, Rind, Brokkoli" (beide FLEISCH)
→ Verdict: OK ✅ (gleiche Subgruppe erlaubt)

"Lachs, Thunfisch, Salat" (beide FISCH)
→ Verdict: OK ✅ (gleiche Subgruppe erlaubt)

"Hähnchen, Lachs, Gurke" (FLEISCH + FISCH)
→ Verdict: NOT_OK ✅
→ Problem: R018
```

**Neue Test-Fixtures:**
- D21: "Jar breakfast (Hähnchen mit Ei)" → NOT_OK, R018
- D22: "Lachs-Omelette" (Lachs + Ei) → NOT_OK, R018

**Test-Suite:** 66 Tests (vorher 64) - alle PASSED ✅

**Datei:** `trennkost/engine.py:161-182`, `tests/fixtures/dishes.json:D21,D22`, `tests/test_engine.py:4,228,261-263`
**Status:** ✅ Fixed (2026-02-12)

---

### 19. Englische Food Terms nicht erkannt → UNKNOWN
**Problem:**
- User fotografiert englische Speisekarte (z.B. "Jar breakfast: fried chicken, poached egg and pickle")
- Vision API extrahiert englische Begriffe 1:1 vom Foto
- Analyzer findet sie nicht in Ontology → UNKNOWN → CONDITIONAL verdict
- Betroffene Begriffe: "poached egg", "pickle", "scrambled egg", "mushroom", "cucumber", etc.

**Ursache:**
- Ontology hatte nur deutsche Einträge + vereinzelt englische Synonyme (Chicken, Salmon, Beef)
- Systematische englische Übersetzungen fehlten für ~80% der Einträge
- Vision API gibt Items in der Originalsprache der Speisekarte aus

**Lösung:**
**Dual-Ansatz (beide zero Latenz):**

1. **Englische Synonyme in Ontology** (deterministisch, 100% zuverlässig)
   - ~120 Ontology-Einträge systematisch erweitert mit englischen Food Terms
   - Neue Einträge: Pear, Banana, Cucumber, Tomato, Mushroom, Parsley, Basil, Scrambled egg, Poached egg, Pork, Lamb, Trout, Cheese, Yogurt, Bread, Rice, Carrot, Walnut, etc.
   - Auch: Mayonnaise hinzugefügt (war im Unknowns-Log)
   - Format: `Ei,"...,Egg,Eggs,Poached egg,Fried egg,Scrambled egg,...",PROTEIN,EIER`

2. **Vision Prompt Update** (proaktiv, kostet keine Extra-Latenz)
   - Neue Anweisung im `FOOD_EXTRACTION_PROMPT`:
   - "WICHTIG: Gib alle Zutaten auf DEUTSCH aus, auch wenn die Speisekarte auf Englisch/Französisch/etc. ist. Übersetze erkannte Zutaten ins Deutsche"
   - Vision API ist bereits GPT-4, kann gut übersetzen
   - Kein zusätzlicher API-Call, nur Prompt-Text geändert

**Warum dieser Ansatz?**
- ✅ Null Extra-Latenz (CSV-Lookup + bestehender Vision-API-Call)
- ✅ 100% deterministisch für häufige Begriffe (Ontology)
- ✅ Flexibel für seltene Begriffe (Vision übersetzt)
- ✅ Skaliert für alle Sprachen (nicht nur Englisch)
- ❌ Alternative "Übersetzungs-Layer im Analyzer" hätte +200-500ms Latenz gekostet

**Test-Ergebnisse:**
```
"fried chicken, poached egg, pickle"
→ Hähnchen (PROTEIN/FLEISCH) + Ei (PROTEIN/EIER) + Gurke (NEUTRAL)
→ Verdict: NOT_OK ✅ (R018 + alle Items erkannt)

"salmon, rice, broccoli" → NOT_OK ✅ (keine UNKNOWN)
"scrambled eggs, toast, butter" → NOT_OK ✅ (keine UNKNOWN)
"mushroom soup, bread" → OK ✅ (keine UNKNOWN)
"grilled chicken, cucumber, tomato, lettuce" → OK ✅ (keine UNKNOWN)
"pork, mashed potato, green beans" → NOT_OK ✅ (keine UNKNOWN)
"tuna, arugula, olives" → OK ✅ (keine UNKNOWN)
```

**Coverage:**
- ~120 häufigste Food Items jetzt bilingual (DE + EN)
- Ontology: 292 Einträge (Mayonnaise neu)
- Vision Prompt: Deutsche Ausgabe bevorzugt

**Test-Suite:** 66/66 Tests bestanden ✅

**Datei:** `trennkost/data/ontology.csv` (+120 English synonyms), `app/vision_service.py:60-66` (Prompt)
**Status:** ✅ Fixed (2026-02-12)

---

## 🔄 BEKANNTE LIMITATIONEN

### L1. Grüner Smoothie mit partiellen Zutaten
**Problem:** "Grüner Smoothie mit Banane, Spinat" (ohne Apfel, Ingwer, Wasser)
- Bot sagt teilweise: "Falls Apfel, Ingwer, Wasser enthalten sind..."
- Verwechselt explizite Zutatenliste mit Compound-Definition

**Workaround:** Aktuell akzeptabel - Bot fragt höflich statt direkt zu vermuten
**Status:** 🟡 Minor (Low Priority)

---

### L2. Komplexe Multi-Dish Queries
**Problem:** "Kann ich Frühstück: Müsli + Mittag: Steak + Abend: Salat essen?"
- Parser erkennt multiple Dishes, aber zeitliche Abfolge nicht berücksichtigt
- Trennkost hat zeitliche Regeln (Wartezeiten zwischen Mahlzeiten)

**Workaround:** User muss separate Queries stellen
**Status:** 🟡 Minor (Future Feature)

---

### L3. Mengenabhängige Bewertungen ohne konkrete Angabe
**Problem:** "Avocado-Salat" → Fett-Menge entscheidend, aber oft nicht spezifiziert
- Bot fragt nach Menge → User gibt vage Antwort ("normal halt")
- Schwierig deterministisch zu bewerten

**Workaround:** Bot macht Schätzungen bei Bild-Uploads
**Status:** 🟡 Minor (inherent ambiguity)

---

## 🚧 OFFENE ISSUES

### I0. Kochmethoden-Adjektive werden gefiltert (Fett geht verloren)
**Problem:** "Fried mushrooms", "gebratenes Hähnchen", "frittierte Garnelen"
- Kochmethoden-Adjektive (fried, gebraten, frittiert) werden als normale Adjektive behandelt
- Aktuell in `_ADJECTIVES_TO_IGNORE`: "gebraten", "gegrillt", "gebacken"
- Diese Kochmethoden fügen aber **Fett** hinzu → wichtig für Trennkost-Analyse!
- Resultat: Fett wird nicht erkannt → Analyse unvollständig

**Beispiel aus Sushi-Menü:**
```
Vision API: "Fried mushroom spring onion"
Parser: filtert "fried" → nur "mushroom spring onion"
Korrekt wäre: Pilze (NEUTRAL) + Fett (FETT) → Fett-Mengen-Frage
```

**Unterscheidung nötig:**
- ✅ Reine Adjektive filtern: "normaler", "frischer", "veganer" (ändern nichts)
- ❌ Kochmethoden NICHT filtern: "fried", "gebraten", "frittiert" (fügen Fett hinzu)

**Mögliche Lösungen:**
1. **Quick-Fix:** Kochmethoden-Adjektive aus Blacklist entfernen
   - "gebraten", "frittiert", "gebacken" → raus aus `_ADJECTIVES_TO_IGNORE`
   - ⚠️ Werden dann als UNKNOWN erkannt, aber sichtbar
2. **Proper Fix:** Kochmethoden-Erkennung im Parser
   - "fried" / "gebraten" → automatisch "Öl" oder "Fett" zur Zutatenliste hinzufügen
   - Unterscheidung: gekocht/gedünstet (kein Fett) vs. gebraten/frittiert (viel Fett)
   - Erfordert neue Logik + Kochmethoden-Mapping

**Betroffene Kochmethoden:**
- **Mit Fett:** fried, deep-fried, pan-fried, sautéed, gebraten, frittiert, ausgebacken, paniert
- **Ohne/wenig Fett:** boiled, steamed, poached, grilled, gekocht, gedünstet, gedämpft, gegrillt

**Priority:** 🟠 Medium (beeinflusst Genauigkeit, aber nicht kritisch)
**Status:** ⏳ Parked (weitere Diskussion nötig)

---



### I1. Kochmethoden nicht in Adjektiv-Blacklist
**Siehe:** Issue I0 oben - Parked für spätere Entscheidung

### I2. Ambiguous Follow-ups ohne klaren Context
**Problem:** Lange Konversation → User sagt nur "und mit Reis?"
- Unklar worauf sich "und" bezieht
- Konversations-Context wird summarized, Details gehen verloren

**Mögliche Lösung:**
- Explizit fragen: "Meinst du [letztes Gericht] + Reis?"
- Oder: Always assume latest food context

**Priority:** 🟠 Medium
**Status:** ⏳ To Do

---

### I3. Neue unbekannte Lebensmittel
**Problem:** Trotz 284 Einträgen fehlen noch viele Items
- User-Anfragen mit unbekannten Items → UNKNOWN → CONDITIONAL/UNKLAR

**Laufende Lösung:**
- `storage/trennkost_unknowns.log` sammelt automatisch
- Periodisch: Top-Missing-Items zur Ontologie hinzufügen

**Priority:** 🟢 Low (iterative improvement)
**Status:** ⏳ Ongoing

---

### I4. Compound Dishes ohne Definition
**Problem:** Viele echte Gerichte noch nicht in `compounds.json`
- z.B. "Ratatouille", "Risotto", "Paella", etc.
- Bot kann sie analysieren aber nicht optimal dekomponieren

**Mögliche Lösung:**
- Top-50-Gerichte aus Rezeptdatenbanken hinzufügen
- Oder: LLM-basierte dynamische Dekomposition (riskanter)

**Priority:** 🟠 Medium
**Status:** ⏳ To Do

---

### I5. Bot schlägt verbotene Kombinationen vor + ignoriert Frühstücksregeln (Issue #20)
**Problem Teil 1: Verbotene Kombination im Rezept**
User-Szenario aus Chat (2026-02-12):
```
User: "ich esse morgens gerne ein brot mit schinken und käse"
Bot: "Brot mit Schinken und Käse ist leider nicht trennkost-konform."
     → Erklärt korrekt: KH + Protein + Milch = NOT_OK
     → Fragt: "Was möchtest du behalten — die Kohlenhydrate (Brot) oder das Protein (Schinken)?"

User: "den käse will ich am liebsten!!!"
Bot: "Da du den Käse am liebsten behalten möchtest, schlage ich vor, ihn mit einer großen
     Portion Gemüse zu kombinieren. Wie wäre es mit einem leckeren Käseomelette? Du kannst
     dafür Eier verwenden und das Omelett mit viel Gemüse wie Paprika, Zucchini und Spinat füllen."
     → ❌ FALSCH! Käseomelette = Käse (MILCH) + Ei (PROTEIN) = R006 Verstoß!

User: "aber das ist doch protein und protein?"
Bot: "Das ist richtig, Käse ist ebenfalls ein proteinreiches Lebensmittel. In der Trennkost
     sollten wir jedoch darauf achten, dass wir nicht mehrere proteinreiche Lebensmittel
     in einer Mahlzeit kombinieren."
     → Gibt Regel zu, schlägt aber NOCHMAL das gleiche Käseomelette-Rezept vor! ❌
```

**Root Cause Teil 1:**
- Bot versteht Regeln konzeptuell, ignoriert sie aber bei Rezept-Generierung
- Keine Rezept-Validation vor Ausgabe
- Kein Engine-Feedback nach Rezept-Vorschlag
- LLM-Instructions nicht stark genug (Pattern 1: "LLM ignoriert Instructions")

**Problem Teil 2: Frühstücksregel ignoriert**
- User will **Käse zum Frühstück** (fettreiches Lebensmittel)
- Bot schlägt direkt Käseomelette vor
- **Fehlt:** Hinweis dass Frühstück vor 12 Uhr **fettarm** sein sollte

**Frühstücksregel aus Kursmaterial (Modul 1.2, Seite 2):**
> "Wie gestalte ich das Frühstück optimal?"
>
> Part 1: Frisches Obst ODER Grüne Smoothies
> - "besser ohne zusätzliche Fette (Nuss-Muse, Leinoel etc.)"
>
> Part 2: Fettfreies weiteres Frühstück
> - "moeglichst ohne Zugabe von Fetten (maximal 1-2TL Nussmus oder Nuesse/ Samen/
>   Kokosoel/ oder Butter sind jedoch okay)"
> - Empfehlungen: Overnight-Oats, Porridge, Reis-Pudding, Hirse-Griess,
>   Glutenfreies Brot mit Gurke und Tomate und 1-2 TL Avocado

**Grund für fettarmes Frühstück (Modul 1.2, Seite 1):**
- **Entgiftung läuft bis mittags auf Hochtouren**
- Obst/leichte Kost spart Verdauungsenergie → Energie für Entgiftung verfügbar
- "die eingesparte Energie kann fuer Entfernung von Schlacken aus Koerper genutzt werden"
- Fettreiche Lebensmittel belasten die Verdauung → behindern Entgiftung

**Betroffene fettreiche Lebensmittel für Frühstück:**
- Käse, Nüsse (>1-2 TL), Avocado (>1-2 TL), Öle, Butter (>1-2 TL), Nussmus (>1-2 TL),
  Eier (PROTEIN + fetthaltig), Fleisch, Fisch

**Korrekter Bot-Flow bei "Käse zum Frühstück":**
1. **Erst:** Fettarm-Empfehlung aussprechen
   > "Käse ist ein fettreiches Lebensmittel. Bis mittags läuft die Entgiftung deines Körpers
   > auf Hochtouren - in dieser Phase ist es optimal, Fett zu vermeiden, damit der Körper
   > sich auf die Entgiftung konzentrieren kann.
   >
   > Möchtest du stattdessen eine fettarme Frühstücksoption wählen? Zum Beispiel:
   > - Frisches Obst (allein oder als Smoothie mit Blattgrün)
   > - Haferflocken mit Apfel und Zimt
   > - Gemüse-Sticks mit leichtem Dip"

2. **Falls User besteht:** Käse + Gemüse vorschlagen (OHNE Ei!)
   > "Okay, wenn du Käse möchtest: Kombiniere ihn mit viel Gemüse (Paprika, Zucchini, Spinat,
   > Tomate). Eine Gemüse-Käse-Pfanne wäre optimal. NICHT mit Ei kombinieren (Käse ist MILCH,
   > Ei ist PROTEIN → verboten). Hinweis: Fettarm wäre für dein Frühstück besser!"

**Was NICHT vorgeschlagen werden darf:**
- ❌ Käseomelette (Käse + Ei = MILCH + PROTEIN = R006)
- ❌ Käse + Schinken (MILCH + PROTEIN = R006)
- ❌ Käse + Brot (MILCH + KH = R002)

**Korrekte Alternativen:**
- ✅ Käse + Gemüse (MILCH + NEUTRAL = OK, aber suboptimal wegen Fett am Morgen)
- ✅ Gemüse-Pfanne mit Paprika, Zucchini, Spinat (NEUTRAL = OK, fettarm)
- ✅ Obst (OBST = OK, fettarm, unterstützt Entgiftung)
- ✅ Haferflocken mit Apfel (KH + OBST nach Wartezeit = OK, fettarm)

**Lösungsansätze:**
1. **Rezept-Validation Layer:**
   - Nach Rezept-Generierung: Zutaten durch Engine laufen lassen
   - Bei NOT_OK: Rezept ablehnen, neu generieren
   - Feedback-Loop: "Dein vorgeschlagenes Rezept verletzt R006 (MILCH + PROTEIN)"

2. **Frühstücks-Detection + Instructions:**
   - Erkennen ob Query Frühstück betrifft (Keywords: "morgens", "Frühstück", "breakfast", Uhrzeit < 12)
   - Neue Instruction: "Bei Frühstück VOR 12 Uhr: Fettarme Optionen bevorzugen! Grund: Entgiftung."
   - Explizite fettreiche Items-Liste in Instructions

3. **Stärkere Negative Examples:**
   - In Instructions: "VERBOTEN: Käseomelette (MILCH + PROTEIN = R006 Verstoß!)"
   - "VERBOTEN: Käse + Schinken (MILCH + PROTEIN = R006 Verstoß!)"
   - Mehrfache Wiederholung (Pattern 1)

4. **Temperature auf 0.0 setzen:**
   - Aktuell bei Rezept-Generierung vermutlich höher
   - Temperature 0.0 = deterministischer, folgt Instructions besser

**Test-Cases:**
```
User: "ich will morgens Käse essen"
→ Bot sollte: Fettarm-Empfehlung + fettarme Alternativen (Obst, Haferflocken)
→ Bei Insist: Käse + Gemüse (OHNE Ei)

User: "ich will Avocado zum Frühstück"
→ Bot sollte: "Avocado ist fettreich - maximal 1-2 TL okay. Besser: Obst oder Haferflocken?"

User: "ich will mittags Käse essen"
→ Bot sollte: KEINE Fettarm-Warnung (nur Trennkost-Regeln), Käse + Gemüse OK

User: "Käseomelette zum Frühstück?"
→ Bot sollte: "NICHT trennkost-konform! Käse (MILCH) + Ei (PROTEIN) = verboten (R006).
              Außerdem: Frühstück sollte fettarm sein. Alternative: Gemüse-Pfanne oder Obst?"
```

**Kursmaterial-Quellen:**
- Modul 1.2, Seite 2: "Wie gestalte ich das Frühstück optimal?" (fettfrei/fettarm)
- Modul 1.2, Seite 1: "Vorteile des Obstverzehrs" (Entgiftung, Energie-Einsparung)
- Modul 1.3, Seite 5: "Optimierung der Ernährung 2" (gesund altern, meiden von Fett)

**Priority:** 🔴 HIGH (Bot gibt falsche Gesundheitsempfehlungen + verletzt eigene Regeln)
**Status:** ⏳ To Fix (kritisch, beeinflusst Nutzererfahrung stark)

---

## 📊 PATTERN & LEARNINGS

### Pattern 1: LLM ignoriert Instructions bei starkem RAG-Signal
**Beobachtung:** Selbst mit expliziten "VERBOTEN" / "KRITISCH" ignoriert LLM manchmal
- Wenn RAG-Snippets sehr dominant sind
- Wenn Conversation-History nicht klar genug ist

**Lösung:**
- Mehrfache redundante Instructions an verschiedenen Stellen
- Temperature auf 0.0 setzen
- Negative Examples in Instructions ("FALSCH: ..., RICHTIG: ...")

---

### Pattern 2: Follow-up Detection ist komplex
**Beobachtung:** Viele Edge Cases bei Multi-Turn-Conversations
- Fix-Direction Follow-up
- Clarification Follow-up
- Image-Reference Follow-up
- Recipe-Request Follow-up

**Lösung:** Separate Instructions für jeden Follow-up-Typ (Rule 10, 11, 12, 13)

---

### Pattern 3: Deterministische Engine + Flexible LLM = Balance
**Beobachtung:**
- Engine liefert korrekte, konsistente Verdicts ✅
- LLM erklärt natural + hilft bei Edge Cases ✅
- Aber: LLM kann Engine-Ergebnisse ignorieren/misinterpretieren ❌

**Best Practice:**
- Engine-Output explizit im Context platzieren
- "KRITISCH: Das Verdict lautet X. Gib dies EXAKT so wieder."
- Verdict nicht "interpretierbar" machen

---

## 🧪 TEST QUERIES (Critical Flows)

### High Priority Tests
1. ✅ **Cheeseburger mit Pommes** - Multi-Verstoß + Fix-Richtungen
2. ✅ **Quinoa-Bowl mit Avocado** - CONDITIONAL + Fett-Menge-Frage
3. ✅ **Grüner Smoothie** - OBST + BLATTGRUEN Ausnahme
4. 🔄 **Rotbarsch mit Kartoffeln → "den rotbarsch"** - Fix-Direction Follow-up
5. ✅ **Matcha Latte + Zutaten-Angabe** - Clarification Follow-up ohne Loop (Fixed: Ontologie-Erweiterung)
6. ✅ **Bild-Upload + "du siehst ja den teller"** - Image-Reference Follow-up
7. ✅ **"hast du ein gericht für mich?"** - Recipe Request Detection

### Edge Case Tests
8. Pizza Margherita (Compound)
9. Müsli mit Milch (KH + MILCH)
10. Hummus mit Gemüsesticks (HUELSENFRUECHTE + Möhre=KH)
11. Pad Thai (Reisnudeln + Ei = NOT_OK)
12. Spaghetti Aglio e Olio (KH + kleine Fett-Menge = OK)
13. ✅ **Jar breakfast (Hähnchen + Ei)** - PROTEIN-Subgruppen-Kombination NOT_OK (Fixed: R018)

---

## 📝 NÄCHSTE SCHRITTE

### Kurzfristig (diese Woche)
- [ ] Test: Fix-Direction Follow-up ("den rotbarsch")
- [ ] Test: Clarification Follow-up Loop (Matcha Latte)
- [ ] Test: Alle 12 Critical Flow Queries
- [ ] Dokumentiere Failures in diesem File

### Mittelfristig (nächste 2 Wochen)
- [ ] Pytest Test-Suite aufbauen (`tests/test_chat_flows.py`)
- [ ] Logging für Fallback-Cases (`log_fallback_case()`)
- [ ] Unknown-Items-Log analysieren → Top-20-Missing-Foods hinzufügen
- [ ] Top-20-Missing-Compounds hinzufügen

### Langfristig
- [ ] User-Feedback-Mechanismus (👍/👎 Buttons)
- [ ] Analytics Dashboard (Fallback-Rate, Unknown-Item-Häufigkeit)
- [ ] A/B Testing für verschiedene Prompt-Varianten
- [ ] Automatische Regression-Tests vor Deploy

---

**Letzte Aktualisierung:** 2026-02-12
**Ontologie-Größe:** 292 Einträge (bilingual: ~120 Items mit EN + DE Synonymen, inkl. Mayonnaise neu)
**Compounds:** 25 Gerichte
**Fixes:** 19 gelöste Probleme + Zucker-Gesundheitsempfehlung (H001) + R018 Protein-Subgruppen-Regel
**Adjektiv-Filter:** 30+ deutsche Adjektive werden ignoriert (normaler, frischer, veganer, etc.)
**Open Issues:** 5 (I0: Kochmethoden, I2: Ambiguous Follow-ups, I3: Neue Lebensmittel, I4: Compound Dishes, I5: Bot schlägt verbotene Kombinationen + ignoriert Frühstücksregeln)
**Test-Suite:** 66 Tests (22 Fixture-Dishes + 44 weitere) - alle bestanden ✅
**Sprach-Support:** Deutsch + Englisch (zero latency, deterministisch via Ontology + Vision Prompt)
**Status:** Production-Ready (mit bekannten Limitationen + Kochmethoden-Diskussion)
