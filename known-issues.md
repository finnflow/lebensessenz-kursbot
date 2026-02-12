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

### I1. Ambiguous Follow-ups ohne klaren Context
**Problem:** Lange Konversation → User sagt nur "und mit Reis?"
- Unklar worauf sich "und" bezieht
- Konversations-Context wird summarized, Details gehen verloren

**Mögliche Lösung:**
- Explizit fragen: "Meinst du [letztes Gericht] + Reis?"
- Oder: Always assume latest food context

**Priority:** 🟠 Medium
**Status:** ⏳ To Do

---

### I2. Neue unbekannte Lebensmittel
**Problem:** Trotz 284 Einträgen fehlen noch viele Items
- User-Anfragen mit unbekannten Items → UNKNOWN → CONDITIONAL/UNKLAR

**Laufende Lösung:**
- `storage/trennkost_unknowns.log` sammelt automatisch
- Periodisch: Top-Missing-Items zur Ontologie hinzufügen

**Priority:** 🟢 Low (iterative improvement)
**Status:** ⏳ Ongoing

---

### I3. Compound Dishes ohne Definition
**Problem:** Viele echte Gerichte noch nicht in `compounds.json`
- z.B. "Ratatouille", "Risotto", "Paella", etc.
- Bot kann sie analysieren aber nicht optimal dekomponieren

**Mögliche Lösung:**
- Top-50-Gerichte aus Rezeptdatenbanken hinzufügen
- Oder: LLM-basierte dynamische Dekomposition (riskanter)

**Priority:** 🟠 Medium
**Status:** ⏳ To Do

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

**Letzte Aktualisierung:** 2025-02-11
**Ontologie-Größe:** 293 Einträge (Matcha + 6 Pflanzenmilch + Zucker reklassifiziert + Salat + Ketchup)
**Compounds:** 25 Gerichte
**Fixes:** 16 gelöste Probleme + Zucker-Gesundheitsempfehlung (H001)
**Status:** Production-Ready (mit bekannten Limitationen)
