# Lebensessenz Kursbot — Vollständiger Projekt-Snapshot
**Erstellt:** 2026-02-27
**Zweck:** Übergabedokument für ChatGPT-Zusammenarbeit. Enthält alle architektonischen,
technischen und inhaltlichen Details des Projekts, sodass ChatGPT ohne weiteres Onboarding
produktiv mitarbeiten kann.

---

# 1. Projektübersicht

## Was ist das Projekt?

**Lebensessenz Kursbot** ist ein RAG-basierter Chatbot für Kursteilnehmer eines
Ernährungskurses (Trennkost-Methode). Der Bot beantwortet Fragen auf Basis von
Kursmaterial, analysiert Lebensmittelkombinationen nach festgelegten Regeln, erkennt
Speisekarten-Fotos und schlägt Rezepte vor.

**Stack:** FastAPI + ChromaDB + OpenAI (gpt-4o-mini) + SQLite + Single-File-SPA-Frontend

**Aktueller Stand (Feb 2026):**
- Vollständig produktionsreif mit bekannten Limitationen
- 8.089 Zeilen Python in 27 Dateien
- 66 deterministische Engine-Tests, alle grün
- Multi-Turn-Conversations mit Rolling Summary
- Mobil-optimiertes Frontend (responsive, 100dvh, 56px touch targets)

## Hauptziele

1. **RAG-Wissensbasis:** 26 Kursseiten in ChromaDB → Fragen werden mit Kursbelegen beantwortet
2. **Trennkost-Analyse:** Deterministisches Regelwerk (19 JSON-Regeln + 2 hardcoded) bewertet Lebensmittelkombinationen ohne LLM-Beteiligung am Verdict
3. **Vision-Integration:** GPT-4o analysiert Fotos von Mahlzeiten oder Speisekarten
4. **Rezept-System:** 110 kuratierte Rezepte + RECIPE_FROM_INGREDIENTS-Modus
5. **Conversation Memory:** Rolling-Summary-Mechanismus für lange Gespräche
6. **Feedback-Export:** Vollständiger Chat-Export als Markdown für Kursleiterin

---

# 2. Ordner- & Datei-Struktur

```
lebensessenz-kursbot/
│
├── app/                                   # FastAPI-Backend
│   ├── main.py                   (857 Z)  # API-Endpunkte: POST /chat, /chat/image, /feedback,
│   │                                      #   GET /conversations, /config, /health,
│   │                                      #   DELETE /conversations/{id}
│   │                                      #   CORS, zentrales JSON-Error-Handling
│   │                                      #   Alle Endpoints auch unter /api/v1/... (Versionierung)
│   │                                      #   /api/v1: guest_id Pflichtfeld + strikte Ownership
│   │                                      #   Keine Exception-Leaks: 500er nur via globalem Handler
│   ├── chat_service.py           (729 Z)  # Dispatcher: handle_chat() ~70 Z + 7 private Handler
│   ├── chat_modes.py             (389 Z)  # ChatMode-Enum + Modifier-Detection
│   ├── prompt_builder.py         (631 Z)  # SYSTEM_INSTRUCTIONS (5 Meta-Regeln M1–M5) + alle Prompt-Builder
│   ├── clients.py                 (34 Z)  # Singleton: OpenAI-Client, ChromaDB-Col, MODEL-Konstanten
│   ├── rag_service.py            (294 Z)  # Vector-Retrieval + Query-Rewrite + Alias-Expansion
│   │                                      #   RetrievalAttempt dataclass + _log_rag_debug() (DEBUG_RAG=1)
│   ├── input_service.py          (429 Z)  # Normalisierung, Intent-Klassifikation, Ingredient-Extraktion
│   ├── recipe_service.py         (408 Z)  # Rezept-Suche (LLM-basiert primär + Keyword-Fallback)
│   ├── recipe_builder.py         (265 Z)  # RECIPE_FROM_INGREDIENTS: Feasibility-Check + Custom-Builder
│   ├── vision_service.py         (367 Z)  # GPT-4o Mahlzeit-/Speisekarten-Analyse
│   ├── feedback_service.py        (95 Z)  # Export: chat.md + feedback.md + metadata.json + images/
│   ├── database.py               (292 Z)  # SQLite: Conversations, Messages, Summary, Title
│   │                                      #   conversation_belongs_to_guest(allow_legacy_open=True)
│   ├── image_handler.py          (175 Z)  # Upload-Validierung, Base64-Encoding, Cleanup-Job
│   ├── migrations.py              (69 Z)  # DB-Schema-Migrationen
│   ├── main_frontend.html         (73 KB) # Single-File-SPA: gesamte UI (CSS + JS embedded)
│   └── data/
│       └── recipes.json         (2691 Z)  # 110 kuratierte Trennkost-Rezepte (strukturiert)
│
├── trennkost/                             # Deterministisches Regelwerk (eigenes Package)
│   ├── analyzer.py               (579 Z)  # Top-Level-Einstieg: analyze_text(), analyze_vision()
│   ├── engine.py                 (451 Z)  # Regelauswertung OHNE LLM — liest rules.json
│   ├── formatter.py              (214 Z)  # TrennkostResult → LLM-Context-Text + RAG-Query
│   ├── normalizer.py             (210 Z)  # Compound-Lookup → Ontology-Lookup → LLM-Fallback
│   ├── ontology.py               (209 Z)  # Ontology-Loader + Synonym-Index (Singleton)
│   ├── models.py                 (165 Z)  # Pydantic-Modelle: FoodItem, TrennkostResult, etc.
│   └── data/
│       ├── rules.json            (197 Z)  # 19 Kombinationsregeln (R001–R051)
│       ├── ontology.csv          (371 Z)  # ~370 Lebensmittel-Einträge, bilingual DE+EN
│       └── compounds.json               # ~25 bekannte Compound-Gerichte (Pizza, Burger, etc.)
│
├── scripts/
│   ├── ingest.py                 (332 Z)  # Kursmaterial → ChromaDB (Chunking + Embeddings)
│   ├── parse_recipes.py          (426 Z)  # Rezept-Markdown → recipes.json
│   ├── import_rezepte_uebersicht.py       # Import-Hilfsskripte (einmalig)
│   └── import_uebergang_und_rest.py
│
├── tests/
│   ├── test_api_contract.py              # API-Contract-Tests: /api/v1/health, /config, /chat (TestClient)
│   ├── test_engine.py                    # 66 Tests: Ontology, Rules, 22 Fixture-Dishes
│   ├── test_normalization.py             # Input-Normalisierung Unit-Tests
│   ├── test_normalization_e2e.py         # E2E-Normalisierung
│   ├── test_e2e_user_journeys.py         # Vollständige Konversationsflüsse
│   ├── test_vision_e2e.py                # Vision-API-Tests
│   ├── test_rag_quality.py               # RAG-Retrieval-Qualität
│   └── fixtures/
│       ├── dishes.json                   # 22 Test-Gerichte mit erwarteten Verdicts
│       └── vision/                       # Test-Bilder
│
├── content/pages/                        # Kursmaterial (Markdown + Frontmatter)
│   ├── modul-1.1-optimale-lebensmittelkombinationen/  (11 Seiten)
│   ├── modul-1.2-fruehstueck-und-obstverzehr/         (4 Seiten)
│   └── modul-1.3-naehrstoffspeicher-auffuellen/       (11 Seiten)
│
├── config/
│   └── alias_terms.json                  # Terminologie-Mapping (z.B. "Trennkost" → Kursbegriffe)
│
├── storage/                              # Laufzeit-Daten (nicht im Repo)
│   ├── chroma/                           # ChromaDB Vektor-Index
│   ├── chat.db                           # SQLite
│   ├── uploads/                          # Temp-Bilder (auto-cleanup 24h)
│   └── feedback/                         # Exportierte Feedbacks
│
├── CLAUDE.md                             # Projekt-Instruktionen für Claude Code
├── known-issues.md                       # Vollständige Bug-History + offene Issues
├── requirements.txt
└── .env                                  # API-Keys + Konfiguration
```

---

# 3. Architektur

## End-to-End Request Flow (ASCII)

```
Browser/Mobile
     │
     │  POST /chat  (JSON: conversationId, message, guestId)
     │  POST /chat/image  (Form: + image file)
     ▼
┌─────────────────────────────────────────────────────────┐
│  app/main.py  (FastAPI)                                 │
│  - Validierung, Image-Save, handle_chat() aufrufen      │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│  app/chat_service.py  handle_chat()  (~70 Zeilen)       │
│                                                         │
│  1. Setup: _setup_conversation() → SQLite               │
│                                                         │
│  2. Parallel (ThreadPoolExecutor):                      │
│  ├── normalize_input()      [input_service.py]          │
│  │   LLM-Call: Typos, EN→DE, Zeitformate               │
│  ├── classify_intent()      [input_service.py]          │
│  │   LLM-Call: Erkennt "ich hab X zuhause"-Pattern      │
│  └── _process_vision()      [vision_service.py]         │
│      GPT-4o: Foto → strukturierte Zutaten/Gericht-Liste │
│                                                         │
│  3. detect_chat_mode()  [chat_modes.py]                 │
│     → KNOWLEDGE | FOOD_ANALYSIS | MENU_ANALYSIS         │
│       MENU_FOLLOWUP | RECIPE_REQUEST                    │
│       RECIPE_FROM_INGREDIENTS                           │
│                                                         │
│  3b. _handle_temporal_separation()                      │
│     → Shortcut: "Apfel 30 min vor Reis" → Early-Return  │
│                                                         │
│  3c. _apply_intent_override()                           │
│     → Ggf. Override → RECIPE_FROM_INGREDIENTS          │
│                                                         │
│  4. Dispatch (ctx-Tuple-Unpacking):                     │
│  ┌────────────────────────────────────────────────────┐ │
│  │                                                    │ │
│  │  RECIPE_FROM_INGREDIENTS                           │ │
│  │  → _handle_recipe_from_ingredients_mode()          │ │
│  │    ├── extract_available_ingredients()             │ │
│  │    ├── handle_recipe_from_ingredients()            │ │
│  │    │   (feasibility + custom builder, 2 LLM-Calls) │ │
│  │    └── Fallback → _handle_recipe_request()         │ │
│  │        oder    → _handle_food_analysis()           │ │
│  │                                                    │ │
│  │  FOOD_ANALYSIS / MENU_ANALYSIS / MENU_FOLLOWUP     │ │
│  │  → _handle_food_analysis()                         │ │
│  │    ├── resolve_context_references()                │ │
│  │    ├── _run_engine() → TrennkostResult             │ │
│  │    │   (analyzer → normalizer → engine, KEIN LLM)  │ │
│  │    └── → _finalize_response()                      │ │
│  │                                                    │ │
│  │  RECIPE_REQUEST                                    │ │
│  │  → _handle_recipe_request()                        │ │
│  │    ├── search_recipes() (LLM-Auswahl aus 110)      │ │
│  │    └── → _finalize_response()                      │ │
│  │                                                    │ │
│  │  KNOWLEDGE (+ Fallback)                            │ │
│  │  → _handle_knowledge_mode()                        │ │
│  │    └── → _finalize_response()                      │ │
│  │                                                    │ │
│  └────────────────────────────────────────────────────┘ │
│                                                         │
│  _finalize_response()  (Steps 5–11, shared):            │
│  ├── 5. RAG: build_rag_query() → retrieve_with_fallback()│
│  │       1. Primary embed + ChromaDB                   │
│  │       2. Fallback: expand_alias_terms() (config)    │
│  ├── 6. Fallback-Check → ggf. FALLBACK_SENTENCE        │
│  ├── 7. Prompt bauen  [prompt_builder.py]              │
│  │       build_base_context() + build_engine_block()   │
│  │       + build_recipe_context_block()                │
│  │       + build_prompt_{food_analysis|knowledge|…}()  │
│  ├── 8. OpenAI-Call (gpt-4o-mini, temp=0.0) + save     │
│  ├── 9. Rolling Summary aktualisieren                  │
│  └── 10. Sources aufbereiten                           │
└─────────────────────────────────────────────────────────┘
                       │
                       ▼
         JSON Response: {answer, conversationId, sources}
```

## Schicht-Beschreibung

### UI / Frontend
- `app/main_frontend.html` (73 KB): Single-File-SPA, kein Build-Step, kein Framework
- Embedded CSS + vanilla JS
- Multi-Conversation-Sidebar (Gespräche als Liste)
- Responsive: 768px (Tablet) + 400px (iPhone 12 mini)
- Hamburger-Menü auf Mobile, safe area insets, 100dvh
- Image-Upload per Drag & Drop oder Button
- Feedback-Modal mit Form + Success-Animation

### Backend / API
- FastAPI mit Pydantic-Validierung
- CORS: `http://localhost:4321` (Astro dev) + `http://localhost:5173` + `http://127.0.0.1:5173` (Vite dev / RicsSite) + `https://lebensessenz.de` (production)
- Zentrales JSON-Error-Handling: `{"error": {"code": ..., "message": ...}}` für 422/4xx/500
- **API-Versionierung:** Alle Endpunkte sind sowohl unter dem Legacy-Pfad als auch unter `/api/v1/...` registriert (je zwei `@app.*`-Dekoratoren, kein Router-Split, vollständig backwards-kompatibel)
- **Exception-Handling:** Endpoints werfen ausschließlich 4xx aktiv (`HTTPException` mit 400/403/404). Kein `except Exception as e: raise HTTPException(500, ...)` — unerwartete Fehler fallen automatisch durch zum globalen Handler (`INTERNAL_ERROR`, kein Leak interner Details). Einzige Ausnahmen: `ValueError → 404` (domain error) und `ImageValidationError → 400` (client error).
- **v1-Ownership-Enforcement:** `/api/v1/conversations`, `/api/v1/conversations/{id}/messages`, `DELETE /api/v1/conversations/{id}`, `/api/v1/feedback` erfordern `guest_id`/`guestId` (sonst 400) und prüfen Ownership strikt (`allow_legacy_open=False`). Legacy-Routen (`/conversations/...`) verhalten sich unverändert — Ownership-Check nur wenn `guest_id` mitgeschickt wird.
- **`conversation_belongs_to_guest(allow_legacy_open: bool = True)`:** `True` = Legacy-Conversations ohne guest_id sind offen (v0 compat); `False` = werden als unzugänglich behandelt (v1 strict)
- Endpunkte:
  - `POST /chat` — Request: `{conversationId?, message, guestId?, userId?, courseId?}`
  - `POST /chat/image` — multipart mit optionalem Image
  - `GET /conversations` — Response: `ConversationsResponse`
  - `GET /conversations/{id}/messages`
  - `DELETE /conversations/{id}`
  - `POST /feedback`
  - `GET /config` — Response: `{model, rag: {top_k, max_history_messages, summary_threshold}, features: {vision_enabled, feedback_enabled}}`
  - `GET /health` — Response: `{"ok": true}`
  - `GET /` — SPA
- `userId` und `courseId` in `ChatRequest` reserviert (noch nicht an `handle_chat()` weitergegeben)
- Guest-ID-System: Conversations gehören einem Browser (localStorage UUID)
- SQLite über `app/database.py`: `conversations` (inkl. `guest_id`, `title`) + `messages` (inkl. `image_path`) + rolling summary
- `init_db()` + `run_migrations()` im `@app.on_event("startup")`-Hook (idempotent, kein DB-Seiteneffekt beim Import)
- Bild-Hosting: `/uploads/` als StaticFiles gemountet, auto-cleanup nach 24h

### Embeddings + Retrieval (ChromaDB)
- Model: `text-embedding-3-small` (OpenAI)
- Chunk-Size: 1200 Zeichen, Overlap: 200
- Metadata pro Chunk: `path`, `source`, `page`, `chunk`, `module_id`, `module_label`,
  `submodule_id`, `submodule_label`
- 2-stufige Retrieval-Strategie: Primary → Alias-Expansion
- Deduplication: max 2 Chunks pro Source-Datei
- Distance Threshold: 1.0 (ChromaDB L2-Distanz)
- `TOP_K=10`, `MAX_CONTEXT_CHARS=9000`

### Trennkost-Regelwerk (deterministisch)
→ Eigenes Kapitel (Abschnitt 7)

### LLM-Pipeline
- **Modell:** `gpt-4o-mini` für alle Chat-Calls (außer Vision: `gpt-4o`)
- **Temperature:** 0.0 für alle Calls (Ausnahme: Normalisierung 0.1)
- **LLM-Calls pro Request (typisch):**
  - normalize_input() parallel zu classify_intent()
  - ggf. rewrite_standalone_query()
  - Haupt-Antwort-Call
  - ggf. summary-Update (alle SUMMARY_THRESHOLD=6 Nachrichten)
- Rezept-Spezialfälle: _llm_select_recipe_ids() + _run_feasibility_check() + _run_custom_recipe_builder()

### Logging / Monitoring
- `print()` mit `[PIPELINE]`, `[RECIPE_LLM]`, `[RECIPE_FROM_ING]` Prefixes
- `storage/trennkost_unknowns.log`: Unbekannte Lebensmittel werden automatisch geloggt
- `DEBUG_RAG=1` env var: Strukturiertes `[RAG_DEBUG]` JSON-Log pro `retrieve_with_fallback()`-Aufruf
  - Felder: `user_message`, `chosen_variant`, `attempts` (PRIMARY/ALIAS_FALLBACK/NO_RESULTS), `used_docs`
  - `RetrievalAttempt` dataclass: `variant`, `query`, `threshold`, `n_results`, `best_distance`, `accepted`, `notes`
- Kein strukturiertes Logging-Framework, kein externes Monitoring

---

# 4. Datenquellen & Verarbeitung

## Kursmaterial (RAG-Basis)

**Quelle:** 26 Markdown-Dateien in `content/pages/` mit YAML-Frontmatter
```
---
title: "Optimale Lebensmittelkombinationen"
module_id: "modul-1.1"
submodule_id: "page-001"
---
[Kursinhalt...]
```

**Module:**
- `modul-1.1`: Optimale Lebensmittelkombinationen (11 Seiten)
- `modul-1.2`: Frühstück und Obstverzehr (4 Seiten)
- `modul-1.3`: Nährstoffspeicher auffüllen (11 Seiten)

**Ingestion (`scripts/ingest.py`):**
1. Frontmatter parsen (YAML)
2. Body in Chunks aufteilen (1200 Zeichen, 200 Überlapp, satzbasiert)
3. OpenAI Embedding generieren (`text-embedding-3-small`)
4. In ChromaDB speichern mit vollem Metadaten-Set

**Neuingestion nötig wenn:** Inhalte in `content/pages/` ändern
```bash
source .venv/bin/activate && python scripts/ingest.py
```

## Rezepte

**Quelle:** `/Users/finn/Downloads/rezepte_de_clean_export_full_trennkostfix.md` (extern)

**Parser (`scripts/parse_recipes.py`):**
- Parst Markdown-Rezepte mit Überschriften, Zutatenlisten, Schritten
- Erkennt optionale Zutaten (`(optional)` Tag)
- Bug-Fix (Feb 2026): `(optional)` darf NICHT `in_optional` für Folgezeilen setzen
- Patcht 2 Rezepte automatisch (Curry-Hähnchen, Kantonesischer Seafood)
- Schließt 1 Rezept aus (Kalifornische Tostada: HF + KH unfixbar)
- Output: `app/data/recipes.json` (110 Rezepte)

**Rezept-Struktur (recipes.json):**
```json
{
  "id": "curry-haehnchen-salat",
  "name": "Curry-Hähnchen-Salat",
  "section": "Protein-Gerichte",
  "trennkost_category": "PROTEIN",
  "tags": ["schnell", "sommer", "protein"],
  "ingredients": ["Hähnchenbrust", "Brokkoli", "Gurke"],
  "optional_ingredients": ["Zitronensaft"],
  "full_recipe_md": "...",
  "trennkost_hinweis": "..."
}
```

**Kategorien:** NEUTRAL(33), KH(31), OBST(10), PROTEIN(6), HUELSENFRUECHTE(6)
_(110 Rezepte gesamt laut aktueller Zählung; CLAUDE.md nennt 86 — Diskrepanz durch spätere Erweiterung)_

## Speisekarten / Mahlzeiten-Fotos

**Verarbeitung (`app/vision_service.py`):**
1. Bild wird Base64-encoded und an GPT-4o gesendet
2. `FOOD_EXTRACTION_PROMPT` extrahiert strukturiert Gerichte + Zutaten
3. Anti-Hallucination-Rules: Keine Gewürze, Zusatzstoffe, E-Nummern, Verdickungsmittel
4. Output auf DEUTSCH (auch bei englischer Karte)
5. Rückgabe: `{"type": "menu"|"meal", "dishes": [...]}`

## Bekannte Probleme bei Datenverarbeitung

- **Kochmethoden-Adjektive** (Issue I0): "fried", "gebraten" werden als normale Adjektive gefiltert → Fett geht verloren bei Analyse
- **Compounds ohne Definition**: Viele echte Gerichte noch nicht in `compounds.json` (Issue I4)
- **Unbekannte Lebensmittel** (Issue I3): Trotz ~370 Ontologie-Einträgen fehlen noch viele
- **JSON-Parsing der Vision-API** (gelöst Feb 2026): Manchmal Preamble-Text vor JSON → Regex-Extraktion als Fallback

---

# 5. RAG Pipeline (detailliert)

## Vollständiger Flow

```
User-Nachricht (normalisiert)
       │
       ├─ [bei TrennkostResult vorhanden]
       │   build_rag_query(results, breakfast_context)
       │   → Deterministisch aus groups_found + problems extrahiert
       │   → Breakfast-Keywords optional angehängt
       │
       ├─ [bei Bild + food_groups]
       │   generate_trennkost_query(food_groups)
       │
       └─ [sonst: KNOWLEDGE-Mode]
           rewrite_standalone_query(summary, last_messages, message)
           → LLM-Call: löst Referenzen auf (z.B. "das" → konkretes Lebensmittel)
       │
       ▼
expand_alias_terms(query)          ← deterministisch, config/alias_terms.json
       │
       ▼
retrieve_with_fallback(query, user_message)
  ├── 1. PRIMARY: embed_one() → col.query(n_results=TOP_K)
  │         + deduplicate_by_source(max_per_source=2)
  │         → OK wenn best_dist ≤ DISTANCE_THRESHOLD(1.0) und ≥2 Ergebnisse
  │
  ├── 2. ALIAS_FALLBACK: expand_alias_terms(query) [alias_terms.json]
  │         → Threshold: DISTANCE_THRESHOLD + 0.2
  │         → Nur wenn expanded_query != query
  │
  └── 3. NO_RESULTS: leerer RetrievalAttempt, FALLBACK_SENTENCE greift
       │
       ▼
build_context(docs, metas)
  → Chunks zusammenfügen (MAX_CONTEXT_CHARS=9000)
  → Jeder Chunk gelabelt: [path#chunk]
       │
       ▼
assemble_prompt(parts, course_context, answer_instructions)
  → system: SYSTEM_INSTRUCTIONS
  → user: base_context + engine_block + course_context + answer_instructions
```

## Zuständige Funktionen

| Funktion | Datei | Beschreibung |
|----------|-------|--------------|
| `retrieve_with_fallback()` | rag_service.py | 3-stufige Retrieval-Logik |
| `retrieve_course_snippets()` | rag_service.py | Einzelner ChromaDB-Query |
| `deduplicate_by_source()` | rag_service.py | Max 2 Chunks per Source |
| `build_context()` | rag_service.py | Chunks → Text (mit Char-Limit) |
| `rewrite_standalone_query()` | rag_service.py | LLM-Rewrite für Konversationskontext |
| `expand_alias_terms()` | rag_service.py | Deterministisch via alias_terms.json |
| `build_rag_query()` | trennkost/formatter.py | Aus TrennkostResult |

## Schwachstellen

1. **Kein Re-Ranking:** Reihenfolge ist pure L2-Distanz, kein Cross-Encoder
2. **Distance Threshold 1.0 sehr weit:** Kann irrelevante Snippets einschließen
3. **`generalize_query()` LEGACY:** Regex-Map, nicht mehr aufgerufen — safe to delete
4. **Alias-Terms nur 1 Match:** Schleife bricht bei erstem Treffer ab (`break`)
5. **Kein separater Test für RAG-Qualität:** `test_rag_quality.py` existiert, ist aber nur eine Funktion
6. **Kein Caching der Embeddings:** Jede Anfrage embeddet neu
7. **Context-Limit-Truncation:** Chunks werden hart abgeschnitten wenn MAX_CONTEXT_CHARS erreicht

---

# 6. Systemprompts & Tooling

## SYSTEM_INSTRUCTIONS (app/prompt_builder.py)

5 Meta-Regeln (M1–M5), die für ALLE Modi gelten. Domänen-spezifische Details (Zeitwerte,
Lebensmittelbeispiele, Rule-IDs) wurden bewusst entfernt — sie stecken in den mode-spezifischen
Buildern (`build_prompt_food_analysis()`, `build_prompt_knowledge()` etc.).

| Regel | Inhalt |
|-------|--------|
| M1 | Quellenbindung: Nur Kurs-Snippets + Engine-Ergebnis + explizite Metadaten — kein externes Allgemeinwissen |
| M2 | Zahlen & konkrete Angaben: Nur Werte aus Snippets/Engine — niemals neue Zahlen erfinden |
| M3 | Engine-Verdicts respektieren: Unveränderlich — erklären ja, überschreiben/abschwächen nein |
| M4 | Keine Spekulationen: Keine erfundenen Fakten/Regeln, keine Medizin, keine Quellenlabels im Text, gleiche Frage nie zweimal |
| M5 | Lücken ehrlich kommunizieren: Fallback-Satz wenn Material keine Aussage hat; Ausnahme: Follow-ups, Bilder, Rezepte |

**FALLBACK_SENTENCE:** `"Diese Information steht nicht im bereitgestellten Kursmaterial."`

## Mode-spezifische Prompt-Builder

| Funktion | Datei | Verwendung |
|----------|-------|------------|
| `build_prompt_food_analysis()` | prompt_builder.py | FOOD_ANALYSIS + MENU_ANALYSIS |
| `build_prompt_menu_overview()` | prompt_builder.py | Multi-Dish-Menü-Analyse |
| `build_prompt_knowledge()` | prompt_builder.py | KNOWLEDGE-Mode |
| `build_prompt_recipe_request()` | prompt_builder.py | RECIPE_REQUEST |
| `build_prompt_vision_legacy()` | prompt_builder.py | Älterer Vision-Pfad |

## Context-Blocks (werden zusammengebaut)

| Funktion | Inhalt |
|----------|--------|
| `build_base_context()` | Rolling-Summary + letzte LAST_N=8 Nachrichten |
| `build_engine_block()` | TrennkostResult als strukturierter Text (verdict, groups, problems) |
| `build_menu_injection()` | Gerichteliste bei Speisekarten |
| `build_recipe_context_block()` | Rezept-Treffer aus recipes.json |
| `build_breakfast_block()` | Frühstücks-Konzept (Modul 1.2) |
| `build_vision_failed_block()` | Hinweis wenn Vision-Analyse fehlschlug |
| `build_post_analysis_ack_block()` | Nach einer abgeschlossenen Analyse |

## Deterministische Einbauten in Prompts

- **Verdict-Lock:** `"KRITISCH: Das Verdict lautet '{verdict_display}'. Gib dies EXAKT so wieder."`
- **Keine-Fragen-Lock:** `"⚠️ KRITISCH: Alle Zutaten sind explizit genannt. Stelle KEINE Rückfragen zu Zutaten!"`
- **Fix-Direction-Anleitung:** Explizite Verbotsliste (Käseomelette, Käse+Schinken etc.)
- **Compliance-Check-Block:** Aktiviert wenn `is_compliance_check=True`
- **Breakfast-Section:** Aktiviert wenn `is_breakfast=True` oder OBST+KH-Konflikt erkannt

---

# 7. Trennkost-Regelwerk (deterministische Logik)

## Übersicht

**Kernprinzip:** LLM extrahiert und normalisiert Lebensmittel, aber das Verdict kommt
**ausschließlich** vom deterministischen Engine in `trennkost/engine.py`.
Das LLM darf das Verdict nur erklären, nicht ändern.

## Lebensmittel-Gruppen

| Gruppe | Beispiele |
|--------|-----------|
| `KH` | Reis, Pasta, Brot, Kartoffeln, Haferflocken, Quinoa |
| `PROTEIN` | Fisch, Fleisch, Eier (Subgruppen: FISCH, FLEISCH, EIER) |
| `MILCH` | Käse, Joghurt, Sahne, Milch |
| `HUELSENFRUECHTE` | Linsen, Kichererbsen, Tofu, Tempeh |
| `OBST` | Frisches Obst |
| `TROCKENOBST` | Datteln, Feigen, Rosinen |
| `FETT` | Öle, Nüsse, Avocado, Butter, Ghee |
| `NEUTRAL` | Stärkearmes Gemüse, Salat, Kräuter (Subgruppe BLATTGRUEN, KRAEUTER) |
| `UNKNOWN` | Nicht erkannt |

## Regeln aus rules.json (19 Regeln)

| ID | Beschreibung | Pair/Condition | Verdict | Severity |
|----|-------------|----------------|---------|----------|
| R001 | KH + Protein | `[KH, PROTEIN]` | NOT_OK | CRITICAL |
| R002 | KH + Milch | `[KH, MILCH]` | NOT_OK | CRITICAL |
| R003 | Hülsenfrüchte + KH | `[HUELSE, KH]` | NOT_OK | CRITICAL |
| R004 | Hülsenfrüchte + Protein | `[HUELSE, PROTEIN]` | NOT_OK | CRITICAL |
| R005 | Hülsenfrüchte + Milch | `[HUELSE, MILCH]` | NOT_OK | CRITICAL |
| R006 | Protein + Milch | `[PROTEIN, MILCH]` | NOT_OK | CRITICAL |
| R007 | Obst + KH | `[OBST, KH]` | NOT_OK | CRITICAL |
| R008 | Obst + Protein | `[OBST, PROTEIN]` | NOT_OK | CRITICAL |
| R009 | Obst + Milch | `[OBST, MILCH]` | NOT_OK | CRITICAL |
| R010 | Obst + Hülsenfrüchte | `[OBST, HUELSE]` | NOT_OK | CRITICAL |
| R011 | Obst + Trockenobst | `[OBST, TROCKENOBST]` | OK | INFO |
| R012 | Obst + Blattgrün (Smoothie-Ausnahme) | `[OBST, NEUTRAL/BLATTGRUEN]` | OK | INFO |
| R013 | Obst + stärkearmes Gemüse (kein Blattgrün) | `[OBST, NEUTRAL]` | NOT_OK | WARNING |
| R014 | Obst + Fett | `[OBST, FETT]` | NOT_OK | WARNING |
| R015 | Mehrere KH-Quellen OK | `[KH, KH]` | OK | INFO |
| R016 | NEUTRAL kombiniert mit allem | `group_present: NEUTRAL` | OK | INFO |
| R017 | Fett in kleinen Mengen (1-2 TL) | `group_present: FETT` | CONDITIONAL | WARNING |
| R050 | Unbekannte Zutaten | `has_unknown: true` | CONDITIONAL | WARNING |
| R051 | Vermutete Zutaten | `has_assumed: true` | CONDITIONAL | WARNING |

## Hardcoded Engine-Regeln (engine.py, nicht in rules.json)

| ID | Beschreibung | Logik |
|----|-------------|-------|
| R018 | Verschiedene PROTEIN-Subgruppen | Wenn ≥2 verschiedene Subgruppen (FLEISCH/FISCH/EIER) → NOT_OK |
| H001 | Zucker-Gesundheitsempfehlung | Wenn canonical="Zucker" → INFO-Problem (Verdict bleibt OK) |

## Verdict-Priorität

`NOT_OK` > `CONDITIONAL` > `OK` (höchste Severity gewinnt)
`CRITICAL` > `WARNING` > `INFO`

Smoothie-Ausnahme: R012 wird VOR R013 geprüft. Wenn ALLE NEUTRAL-Items die Subgruppe
BLATTGRUEN haben → R012 (OK). Sonst R013 (NOT_OK).

## Normalisierungs-Pipeline (trennkost/normalizer.py)

```
User-Text → _extract_foods_from_question()
                │
                ├── Compound-Lookup (compounds.json, case-insensitive)
                │   z.B. "Burger" → {base_items: [Brot, Fleisch], optional: [Käse, Ei]}
                │
                ├── Ontologie-Lookup (ontology.csv, Synonym-Index)
                │   z.B. "chicken" → Hähnchen (PROTEIN/FLEISCH)
                │
                └── LLM-Fallback (nur bei UNKNOWN, LLM_CLASSIFY_PROMPT)
                    → group + canonical zurück
```

## Wo KI beteiligt ist (Trennkost)

| Schritt | KI? | Funktion |
|---------|-----|----------|
| Lebensmittel extrahieren aus Text | KI (LLM) | `_extract_foods_from_question()` |
| Unbekannte Items klassifizieren | KI (LLM) | `normalizer._classify_unknown_items_llm()` |
| Gericht erkennen auf Foto | KI (GPT-4o) | `vision_service.extract_food_from_image()` |
| **Verdict berechnen** | **NEIN — deterministisch** | `engine.evaluate()` |
| Verdict erklären | KI (LLM) | Haupt-Antwort-Call |

## Unschärfen im Regelwerk

- **HIGH_FAT-Items** (Mayo, Aioli, Pesto, Nussmus): Mengenabhängig — Engine fragt nach Menge
- **Kochmethoden** (Issue I0): "gebratenes Hähnchen" → Fett-Zusatz geht verloren
- **Kakao/Schokolade:** Noch `UNKNOWN` in Ontologie, keine Kategorisierung aus Kursmaterial
- **Hafermilch/Pflanzenmilch:** Als KH klassifiziert (nicht als MILCH — kurskonform)
- **R012/R013 Grenzfall:** "Grüner Smoothie mit Banane, Spinat" → OK; "mit Paprika" → NOT_OK

---

# 8. Bekannte Probleme & Pain Points

## Gelöste Probleme (aus known-issues.md)

| # | Problem | Lösung |
|---|---------|--------|
| P1 | Natural Language als Food Items erkannt ("Rückfragen stellen" → Zutat) | `_extract_foods_from_question()` erkennt Fragen |
| P2 | Rezept-Endlos-Schleife | System Instruction Rule 10 + Follow-up-Detection |
| P3 | Non-konforme Alternativ-Vorschläge (Käseomelette nach "behalte Käse") | Explizite Verbotsliste in Answer Instructions |
| P4 | Smoothie-Ausnahme: Gewürze blockieren OK-Verdict | SMOOTHIE_SAFE_SUBGROUPS inkl. KRAEUTER |
| P5 | "Wasser" → "Wassermelone" (Substring-Match) | Exact-Match hat Priorität |
| P6 | Grüner Smoothie als UNKNOWN bei expliziten Zutaten | Compound als Gericht-Name erkannt |
| P7 | Gewürze als unsicher geflaggt → unnötige Rückfragen | Filter nach NEUTRAL/KRAEUTER |
| P8 | CONDITIONAL schlägt zufällige Zutaten vor | Explizite "KEINE OFFENEN FRAGEN"-Instruction |
| P9 | Rezept-Request als Food Analysis erkannt | Recipe-Request-Patterns in `detect_food_query()` |
| P10 | Bild-Referenz → Fallback Sentence | System Instruction Rule 11 |
| P11 | Fix-Direction Follow-up → Fallback Sentence | System Instruction Rule 12 |
| P12 | Clarification Follow-up Loop (Matcha Latte) | Ontologie-Erweiterung (Matcha, Zucker, Hafermilch) |
| P13 | Anführungszeichen verhindern Item-Erkennung | Quotes als Word Boundaries hinzugefügt |
| P14 | Zucker: trennkost-konform aber ungesund | H001 INFO-Level Rule in Engine |
| P15 | Compound + explizite Zutaten → Parser ignoriert Zutaten | Parser: Compound finden + weiter parsen |
| P16 | Adjektive als UNKNOWN Items ("normaler" → Zutat) | `_ADJECTIVES_TO_IGNORE` Set (~30 Adj.) |
| P17 | Verschiedene Protein-Subgruppen → OK statt NOT_OK | R018 hardcoded in engine.py |
| P18 | Englische Food Terms nicht erkannt | Bilingual Ontologie + Vision-Prompt übersetzt auf Deutsch |
| P19 | Frühstück: Bot schlägt Käseomelette vor (MILCH+PROTEIN) | Explizite Verbotsliste + Breakfast-Detection |

## Aktive Limitationen (Workarounds vorhanden)

| ID | Problem | Schwere |
|----|---------|---------|
| L1 | Grüner Smoothie mit partiellen Zutaten → Bot erwähnt typische Zutaten | Minor |
| L2 | Multi-Dish zeitliche Sequenz-Fragen | Minor / Future Feature |
| L3 | Mengenabhängige Bewertungen ohne Mengenangabe | Inherent ambiguity |

## Offene Issues (keine Lösung)

| ID | Problem | Prio |
|----|---------|------|
| I0 | Kochmethoden-Adjektive ("fried", "gebraten") werden als normale Adj. gefiltert → Fett geht verloren | Medium |
| I2 | Ambiguous Follow-ups in langen Conversations ("und mit Reis?") | Medium |
| I3 | Neue unbekannte Lebensmittel (trotz ~370 Einträgen) | Low/Ongoing |
| I4 | Viele echte Compound-Gerichte noch nicht in compounds.json | Medium |

## Architektonische Unschärfen

1. **RECIPE_FROM_INGREDIENTS**: Ontologie-Substring-Matching verursacht False Positives
   ("ich" → Pfirsich, "und" → Holunderbeere) → LLM-basierte Extraktion als Fix
2. **Compliance-Check + langer Text**: Engine behandelt jede Zeile als separates Gericht
   → weird multi-dish output bei Rezepteingabe
3. **Compounds**: Singleton wird bei Import gecacht → JSON-Änderungen brauchen Server-Restart
   (workaround: `.py`-Datei anfassen für uvicorn `--reload`)
4. **Kakao/Schokolade**: Noch `UNKNOWN` — unklare Kategorisierung aus Kursmaterial
5. **`generalize_query()`**: LEGACY, nicht mehr aufgerufen — safe to delete

---

# 9. Offene Fragen / To-Do-Liste

## Kurzfristig / Bugfixes

- [ ] **I0 Kochmethoden**: Entscheidung: "fried" aus Adjektiv-Blacklist entfernen (Quick-Fix) ODER Parser-Erweiterung die "fried" → Fett-Eintrag generiert
- [ ] **Kakao/Schokolade**: Kategorisierung aus Kursmaterial bestimmen und in Ontologie eintragen
- [ ] **Compliance-Check-Aggregation**: Wenn User ein vollständiges Rezept eingibt, Engine-Ergebnisse vor Ausgabe aggregieren statt als Multi-Dish

## Mittelfristig

- [ ] **Top-20 Unknown Items** aus `storage/trennkost_unknowns.log` analysieren und in Ontologie aufnehmen
- [ ] **Top-20 Compound-Dishes** zu `compounds.json` hinzufügen (Ratatouille, Risotto, Paella etc.)
- [ ] **Pytest-Test-Suite erweitern**: `tests/test_chat_flows.py` für kritische Konversationsflüsse
- [ ] **Logging strukturieren**: `log_fallback_case()` für Monitoring der Fallback-Rate
- [ ] **RAG-Qualität testen**: `test_rag_quality.py` ausbauen

## Architekturentscheidungen (bald)

- [ ] **Re-Ranking**: Cross-Encoder für bessere Retrieval-Präzision?
- [ ] **Distance Threshold**: 1.0 ist sehr tolerant — Analyse ob härterer Threshold (0.7?) besser wäre
- [ ] **`generalize_query()`**: LEGACY-Funktion, safe to delete (nicht mehr aufgerufen)
- [ ] **Recipe-Count-Diskrepanz**: CLAUDE.md sagt 86, tatsächliche JSON enthält 110 — Dokumentation anpassen

## Technische Schulden

- Kein strukturiertes Logging (nur `print()`)
- Keine CI/CD-Pipeline
- Kein Health-Monitoring / Alert-System
- CLAUDE.md-Angabe "86 Rezepte" veraltet (aktuell 110)
- `app/migrations.py` wird beim Start via `run_migrations()` (nach `init_db()`) automatisch ausgeführt
- `scripts/import_*.py` Skripte ohne Dokumentation über ihren aktuellen Zweck
- `app/main.py` 859 Zeilen — weiteres Splitting möglich (aktuell: Models + Handler + Routes in einer Datei)

---

# 10. Empfehlungen für ChatGPT-Zusammenarbeit

1. **Das Verdict kommt NIEMALS vom LLM.** Wenn du Code für Trennkost-Logik schreibst,
   darf kein LLM-Call im engine.py oder in der Verdict-Berechnung stehen. Die Architektur ist
   bewusst so: `engine.py` → DETERMINISTISCH, LLM → NUR für Extraktion und Erklärung.

2. **Gruppen-Wissen ist essenziell.** Die 9 Gruppen (KH, PROTEIN, MILCH, HUELSENFRUECHTE,
   OBST, TROCKENOBST, FETT, NEUTRAL, UNKNOWN) + Subgruppen (FLEISCH, FISCH, EIER,
   BLATTGRUEN, KRAEUTER) sind das Herz des Systems. Änderungen an Ontologie oder Regeln
   immer zuerst mit `pytest tests/test_engine.py -v` verifizieren.

3. **`handle_chat()` ist ein ~70-Zeilen-Dispatcher — keine Logik drin.** Die eigentliche Arbeit
   steckt in 7 privaten Funktionen: `_handle_temporal_separation()`, `_apply_intent_override()`,
   `_handle_recipe_from_ingredients_mode()`, `_handle_food_analysis()`, `_handle_recipe_request()`,
   `_handle_knowledge_mode()` und `_finalize_response()` (Steps 5–11, shared von allen Modes).
   Wenn du etwas am Flow änderst: parallele ThreadPoolExecutor-Ausführung in Schritt 2 beachten,
   und `ctx`-Tuple-Unpacking für den Dispatch (Reihenfolge muss mit allen `_handle_*`-Signaturen übereinstimmen).

4. **Prompt-Änderungen sind heikel.** Die globalen SYSTEM_INSTRUCTIONS enthalten jetzt nur 5
   Meta-Regeln (M1–M5) — domänenspezifische Details stecken in den mode-spezifischen Buildern.
   Wenn du Answer-Instructions änderst, teste kritische Flows manuell. Temperature=0.0 ist
   bewusst — nicht erhöhen.

5. **Ontologie-Änderungen brauchen Server-Restart.** Der Ontologie-Singleton wird bei Import
   gecacht. Nach Änderungen an `ontology.csv` oder `compounds.json` den Server neu starten
   (oder eine `.py`-Datei anfassen für uvicorn `--reload`).

6. **Rezepte-Parser hat einen bekannten Bug-Fix.** Wenn `(optional)` in einer Zutatzeile
   steht, darf das NICHT `in_optional=True` für alle nachfolgenden Zeilen setzen. Dieser Fix
   ist in `scripts/parse_recipes.py` implementiert — bei Änderungen am Parser darauf achten.

7. **Drei Fallback-Ebenen im RAG.** Primary → Regex-Generalization → Alias-Expansion.
   Wenn Retrieval-Probleme auftreten: `DEBUG_RAG=1` in `.env` setzen, dann werden
   Distanzen und verwendete Queries geloggt.

8. **Der Vision-Pfad hat zwei Untertypen.** `type="menu"` (Speisekarte) → MENU_ANALYSIS-Mode;
   `type="meal"` (Mahlzeit-Foto) → FOOD_ANALYSIS-Mode. Beide landen in der Trennkost-Engine.
   Anti-Hallucination ist im Vision-Prompt hartverdrahtet: keine Gewürze, keine E-Nummern.

9. **RECIPE_FROM_INGREDIENTS ist der komplexeste Mode.** 2 LLM-Calls (Feasibility + Custom
   Builder), Ingredient-Overlap-Scoring, Fallback-Chain. Einstieg:
   `app/recipe_builder.handle_recipe_from_ingredients()`. Wichtig: Ingredient-Extraktion
   MUSS LLM-basiert sein (ontology substring matching → False Positives wie "ich"→Pfirsich).

10. **known-issues.md ist das wichtigste Dokument nach CLAUDE.md.** Es enthält die vollständige
    Bug-History mit Root-Causes, Fixes, Test-Ergebnissen und offenen Issues. Bevor du ein
    Problem "neu" löst, prüfen ob es dort schon dokumentiert ist — viele Bugs haben
    subtile Ursachen die beim ersten Hinschauen nicht offensichtlich sind.
