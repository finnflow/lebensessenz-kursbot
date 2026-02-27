# Lebensessenz Kursbot

Ein KI-gestützter Chat-Assistent für Kursmaterial mit Rolling Summary und Kontext-Bewusstsein.

## Features

✨ **Chat mit Gedächtnis**: Rolling Summary hält Kontext über lange Konversationen
🎯 **Fakten-basiert**: Antworten strikt auf Kursmaterial begrenzt
💾 **Multi-Conversation**: Sidebar mit allen Conversations
🎫 **Guest ID**: Browser-gebundene Identifikation ohne Login
🔍 **Smart Retrieval**: Automatisches Query Rewriting für bessere Suche
🎨 **Modern UI**: Responsive Chat-Interface mit Sidebar im Website-Design

## Quick Start

```bash
cd ~/Documents/lebensessenz-kursbot
./start.sh
```

Dann öffne: http://localhost:8000

## Installation

### 1. Dependencies installieren

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Environment Variables

Erstelle `.env` im Projekt-Root:

```bash
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
OPENAI_EMBED_MODEL=text-embedding-3-small

CHROMA_DIR=storage/chroma
COLLECTION_NAME=kursmaterial_v1

TOP_K=10
LAST_N=8
SUMMARY_THRESHOLD=6
MAX_CONTEXT_CHARS=9000

DB_PATH=storage/chat.db
```

### 3. Server starten

**Option A: Start Script**
```bash
./start.sh
```

**Option B: Manuell**
```bash
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Testen

```bash
# In neuem Terminal
source .venv/bin/activate

# Basic chat test (single conversation)
python test_chat.py

# Sidebar test (multi-conversation)
python test_chat_sidebar.py
```

## Architektur

```
┌─────────────────────────────────────────────────────────────┐
│                        Browser Client                        │
│  - localStorage: guestId (UUID)                              │
│  - Sidebar mit Conversation-Liste                            │
│  - Chat UI mit Message History                               │
└────────────────────┬────────────────────────────────────────┘
                     │
                     │ POST /chat (+ guestId)
                     │ GET /conversations?guest_id=...
                     │
┌────────────────────▼────────────────────────────────────────┐
│                    FastAPI Backend                           │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ Chat Service                                         │   │
│  │  1. Load Summary + Last N Messages                   │   │
│  │  2. Rewrite Query (resolve references)               │   │
│  │  3. Retrieve Top-K Course Snippets (ChromaDB)        │   │
│  │  4. Generate Response (OpenAI)                       │   │
│  │  5. Update Rolling Summary (if threshold reached)    │   │
│  └──────────────────────────────────────────────────────┘   │
└────────────────────┬────────────────────────────────────────┘
                     │
                     │
┌────────────────────▼────────────────────────────────────────┐
│                   SQLite Database                            │
│  - conversations (id, guest_id, title, summary, timestamps)  │
│  - messages (id, conversation_id, role, content, image_path) │
└─────────────────────────────────────────────────────────────┘
```

## API Endpoints

### POST /chat

```json
// Request
{
  "conversationId": "uuid",         // optional – omit to start a new conversation
  "message": "Wie war das mit Obst vor der Mahlzeit?",
  "guestId": "browser-uuid",        // controls conversation ownership
  "userId": "user-uuid",            // reserved – not yet forwarded to pipeline
  "courseId": "trennkost-basis-1"   // reserved – not yet forwarded to pipeline
}
```

```json
// Response
{
  "conversationId": "uuid",
  "answer": "string",
  "sources": [
    { "path": "modul-1.1/.../page-004.md", "chunk": "0", "distance": 0.234 }
  ]
}
```

`guestId` binds the conversation to a browser session (stored in `localStorage`).
`userId` and `courseId` are accepted but currently ignored — reserved for future auth and multi-course support.

---

### POST /chat/image

Multipart form upload for meal or menu photo analysis.

```
POST /chat/image
Content-Type: multipart/form-data

message=<string>
conversationId=<uuid>   (optional)
guestId=<uuid>          (optional)
image=<file>            (JPG, PNG, HEIC, WebP — optional)
```

Response: same shape as `POST /chat`.

---

### POST /analyze

Standalone Trennkost analysis without chat context.

```json
// Request
{ "text": "Reis, Hähnchen, Brokkoli", "mode": "strict" }
```

```json
// Response (abbreviated)
{
  "results": [
    {
      "dish_name": "Reis, Hähnchen, Brokkoli",
      "verdict": "NOT_OK",
      "summary": "KH + Protein-Kombination",
      "groups": { "KH": ["Reis"], "PROTEIN": ["Hähnchen"] },
      "problems": [ { "rule_id": "R001", "description": "..." } ]
    }
  ],
  "formatted": "string"
}
```

---

### GET /conversations

```
GET /conversations?guest_id=<uuid>
```

```json
// Response
{
  "conversations": [
    {
      "id": "uuid",
      "title": "Nenn mir die Kernpunkte...",
      "created_at": "2024-01-01T12:00:00",
      "updated_at": "2024-01-01T12:05:00",
      "guest_id": "uuid"
    }
  ]
}
```

Returns `{ "conversations": [] }` when `guest_id` is absent (backwards-compatible).

---

### GET /conversations/{conversation_id}/messages

```
GET /conversations/{id}/messages?guest_id=<uuid>
```

```json
// Response
{
  "messages": [
    {
      "id": "uuid",
      "conversation_id": "uuid",
      "role": "user",
      "content": "question",
      "created_at": "2024-01-01T12:00:00"
    }
  ]
}
```

Returns `403 ACCESS_DENIED` if `guest_id` does not match the conversation owner.

---

### DELETE /conversations/{conversation_id}

```
DELETE /conversations/{id}?guest_id=<uuid>
```

Returns `{ "status": "deleted" }` on success. Returns `403` if ownership check fails.

---

### POST /feedback

```json
// Request
{
  "conversationId": "uuid",
  "feedback": "string",
  "guestId": "uuid"   // optional
}
```

Exports the full conversation as Markdown + images to `storage/feedback/`.

---

### GET /health

```json
{ "ok": true }
```

---

### GET /config

Returns current runtime configuration. Intended for frontend capability discovery — single source of truth for model name, RAG limits, and feature flags.

```json
{
  "model": "gpt-4o-mini",
  "rag": {
    "top_k": 10,
    "max_history_messages": 8,
    "summary_threshold": 6
  },
  "features": {
    "vision_enabled": true,
    "feedback_enabled": true
  }
}
```

All values reflect active env-var overrides (see `.env`).

## Error Format

All error responses use a consistent envelope:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable description",
    "details": [ ... ]   // present on VALIDATION_ERROR only
  }
}
```

| HTTP Status | Code | Trigger |
|-------------|------|---------|
| 422 | `VALIDATION_ERROR` | Invalid request payload (Pydantic) |
| 403 | `ACCESS_DENIED` | Guest-ID ownership mismatch |
| 404 | `NOT_FOUND` | Resource not found |
| 500 | `INTERNAL_ERROR` | Unhandled exception — no internal details leaked |
| Other 4xx | `HTTP_ERROR` | All other HTTP exceptions |

---

## Smoke Test

### Automated
```bash
python test_chat_sidebar.py
```

### Manueller Test-Flow:

1. **Erste Conversation**
   - Browser öffnen: http://localhost:8000
   - ✅ guest_id wird automatisch generiert
   - Frage stellen: "Nenn mir die Kernpunkte von Seite 4"
   - ✅ Antwort erscheint
   - ✅ Sidebar zeigt neue Conversation mit Auto-Titel

2. **Zweite Conversation**
   - Klick "+ Neuer Chat"
   - Frage stellen: "Erkläre die 50/50-Regel"
   - ✅ Neue Conversation in Sidebar
   - ✅ Beide Conversations sichtbar

3. **Wechsel zwischen Conversations**
   - Klick auf erste Conversation
   - ✅ Historie lädt korrekt
   - ✅ Kann weiterchatten

4. **Reload Test**
   - F5 (Reload)
   - ✅ Sidebar zeigt alle Conversations
   - ✅ guest_id bleibt erhalten (localStorage)

## Konfiguration

### Mehr Kontext
```bash
LAST_N=12          # Mehr Messages in Kontext
TOP_K=15           # Mehr Kurs-Snippets
```

### Häufigere Summaries
```bash
SUMMARY_THRESHOLD=4  # Summary alle 4 Messages statt 6
```

### Längere Snippets
```bash
MAX_CONTEXT_CHARS=12000  # Mehr Zeichen für Kontext
```

## Database Initialization

Schema setup runs automatically on every server start — no manual migration steps required.

```python
init_db()        # Creates tables and indexes if they don't exist
run_migrations() # Applies schema changes to existing databases (idempotent)
```

Both operations are safe to run repeatedly. A fresh database and an already-migrated database both reach the same final state.

---

## CORS

The following origins are allowed by default:

| Origin | Purpose |
|--------|---------|
| `http://localhost:4321` | Astro dev server |
| `https://lebensessenz.de` | Production frontend |

To allow additional origins, add them to `origins` in `app/main.py`.

---

## Projekt-Struktur

```
lebensessenz-kursbot/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app + Endpoints
│   ├── main_frontend.html   # Sidebar UI
│   ├── database.py          # SQLite layer + guest_id
│   ├── chat_service.py      # Chat logic + Rolling Summary
│   ├── migrations.py        # Database migrations
│   └── main_old_backup.py   # Original Q&A version
├── scripts/
│   └── ingest.py            # ChromaDB ingestion (existing)
├── storage/
│   ├── chroma/              # Vector database
│   └── chat.db              # SQLite conversations
├── content/                  # Course material (existing)
├── .env                     # Environment variables
├── requirements.txt         # Python dependencies
├── start.sh                 # Convenience start script
├── test_chat.py             # Basic smoke test
├── test_chat_sidebar.py     # Sidebar smoke test
├── README.md                # This file
├── CHAT_IMPLEMENTATION.md   # Rolling Summary deep-dive
└── SIDEBAR_IMPLEMENTATION.md # Multi-Conversation deep-dive
```

## Dokumentation

- **README.md** (diese Datei): Quick Start & Übersicht
- **CHAT_IMPLEMENTATION.md**: Rolling Summary, technische Details
- **SIDEBAR_IMPLEMENTATION.md**: Multi-Conversation, guest_id System

## Rollback zur alten Version

Falls du zur einfachen Q&A-Version zurück möchtest:

```bash
cd ~/Documents/lebensessenz-kursbot
mv app/main.py app/main_chat.py
mv app/main_old_backup.py app/main.py
uvicorn app.main:app --reload
```

## Lizenz

Implementiert für Lebensessenz.
