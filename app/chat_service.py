import os
import json
from typing import Optional, List, Dict, Any, Tuple
from dotenv import load_dotenv
from openai import OpenAI
import chromadb
from chromadb.config import Settings
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# Load environment variables
load_dotenv()

from app.database import (
    create_conversation,
    get_conversation,
    create_message,
    get_last_n_messages,
    count_messages_since_cursor,
    get_messages_since_cursor,
    update_summary,
    get_total_message_count,
    update_conversation_title,
    generate_title_from_message,
    conversation_belongs_to_guest,
)
from app.vision_service import (
    analyze_meal_image,
    categorize_food_groups,
    generate_trennkost_query,
    extract_food_from_image,
    VisionAnalysisError,
)
from app.image_handler import ImageValidationError
from trennkost.analyzer import (
    detect_food_query,
    detect_breakfast_context,
    detect_temporal_separation,
    analyze_text as trennkost_analyze_text,
    analyze_vision as trennkost_analyze_vision,
    format_results_for_llm,
    build_rag_query,
)
from trennkost.models import TrennkostResult

from app.chat_modes import ChatMode, ChatModifiers, detect_chat_mode
from app.recipe_service import find_recipes_by_ingredient_overlap
from app.prompt_builder import (
    SYSTEM_INSTRUCTIONS,
    FALLBACK_SENTENCE,
    build_base_context,
    build_engine_block,
    build_menu_injection,
    build_vision_failed_block,
    build_vision_legacy_block,
    build_breakfast_block,
    build_menu_followup_block,
    build_post_analysis_ack_block,
    build_recipe_context_block,
    build_prompt_food_analysis,
    build_prompt_vision_legacy,
    build_prompt_knowledge,
    build_prompt_recipe_request,
    assemble_prompt,
)

# Config
CHROMA_DIR = os.getenv("CHROMA_DIR", "storage/chroma")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "kursmaterial_v1")
DEBUG_RAG = os.getenv("DEBUG_RAG", "0").lower() in ("1", "true", "yes")

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
TOP_K = int(os.getenv("TOP_K", "10"))
LAST_N = int(os.getenv("LAST_N", "8"))
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "9000"))
SUMMARY_THRESHOLD = int(os.getenv("SUMMARY_THRESHOLD", "6"))
DISTANCE_THRESHOLD = float(os.getenv("DISTANCE_THRESHOLD", "1.0"))

# Initialize clients
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
chroma = chromadb.PersistentClient(path=CHROMA_DIR, settings=Settings(anonymized_telemetry=False))
col = chroma.get_or_create_collection(name=COLLECTION_NAME)


# ── Helper functions (unchanged) ─────────────────────────────────────

def embed_one(text: str) -> List[float]:
    """Generate embedding for text."""
    resp = client.embeddings.create(model=EMBED_MODEL, input=[text])
    return resp.data[0].embedding


def _llm_call(system_prompt: str, user_msg: str) -> str:
    """
    Thin LLM wrapper passed to normalizer for extraction/classification.
    Used ONLY for unknown item classification, never for verdicts.
    """
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.1,
        max_tokens=500,
    )
    return response.choices[0].message.content.strip()

def build_context(docs: List[str], metas: List[Dict]) -> str:
    """Build context string from retrieved documents."""
    parts = []
    total = 0
    for doc, meta in zip(docs, metas):
        label = f"[{meta.get('path','?')}#{meta.get('chunk','?')}]"
        piece = f"{label}\n{doc}\n"
        if total + len(piece) > MAX_CONTEXT_CHARS:
            break
        parts.append(piece)
        total += len(piece)
    return "\n".join(parts).strip()

def rewrite_standalone_query(
    summary: Optional[str],
    last_messages: List[Dict[str, Any]],
    user_message: str
) -> str:
    """
    Rewrite user message into a standalone query for retrieval.
    Uses summary + last messages to resolve references.
    """
    if not summary and not last_messages:
        return user_message

    context_parts = []
    if summary:
        context_parts.append(f"ZUSAMMENFASSUNG:\n{summary}\n")

    if last_messages:
        context_parts.append("LETZTE NACHRICHTEN:")
        for msg in last_messages[-4:]:
            role = "User" if msg["role"] == "user" else "Assistant"
            context_parts.append(f"{role}: {msg['content']}")

    context_parts.append(f"\nAKTUELLE NACHRICHT:\n{user_message}")

    prompt = f"""{chr(10).join(context_parts)}

Schreibe die aktuelle Nachricht in eine eigenständige Suchanfrage um, die alle nötigen Informationen enthält.
Falls sie bereits eigenständig ist, gib sie unverändert zurück.
Wenn Begriffe vorkommen, die im Kursmaterial evtl. anders heißen (z.B. "Trennkost"),
ergänze passende Kurs-Begriffe als Synonyme, z.B. "Lebensmittelkombinationen", "Kohlenhydrate", "Protein", "Milieu", "Verdauung".
Antworte NUR mit der umgeschriebenen Anfrage, ohne Erklärung.

STANDALONE QUERY:"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=200
    )

    return response.choices[0].message.content.strip()

def load_alias_terms() -> Dict[str, List[str]]:
    """Load alias terms from config file."""
    config_path = Path(__file__).parent.parent / "config" / "alias_terms.json"
    try:
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Warning: Could not load alias_terms.json: {e}")
    return {}


ALIAS_TERMS = load_alias_terms()


def expand_alias_terms(query: str) -> str:
    """
    Deterministically expand query with course-specific alias terms from config.
    No LLM call - just adds search keywords for concepts that may use different terminology.
    """
    query_lower = query.lower()
    expanded = query

    for key, aliases in ALIAS_TERMS.items():
        if key in query_lower:
            alias_str = " | " + " | ".join(aliases)
            expanded += alias_str
            break
    return expanded

def retrieve_course_snippets(query: str) -> Tuple[List[str], List[Dict], List[float]]:
    """Retrieve relevant course snippets using vector search."""
    qvec = embed_one(query)
    res = col.query(
        query_embeddings=[qvec],
        n_results=TOP_K,
        include=["documents", "metadatas", "distances"],
    )

    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]

    return docs, metas, dists


def deduplicate_by_source(docs: List[str], metas: List[Dict], dists: List[float], max_per_source: int = 2) -> Tuple[List[str], List[Dict], List[float]]:
    """Deduplicate chunks by source file to ensure diverse retrieval."""
    seen_sources = {}
    deduped_docs = []
    deduped_metas = []
    deduped_dists = []

    for doc, meta, dist in zip(docs, metas, dists):
        source = meta.get("path", "unknown")
        count = seen_sources.get(source, 0)

        if count < max_per_source:
            deduped_docs.append(doc)
            deduped_metas.append(meta)
            deduped_dists.append(dist)
            seen_sources[source] = count + 1

    return deduped_docs, deduped_metas, deduped_dists


def normalize_input(
    user_message: str,
    recent_messages: List[Dict[str, Any]],
    is_new_conversation: bool
) -> str:
    """
    Normalize user input to create canonical format for deterministic logic.

    Handles:
    - Language translation to German
    - Time format standardization ("30 minuten" → "30 min")
    - Food name standardization
    - Typo fixing
    - Punctuation cleanup
    - Abbreviation expansion

    Special handling for follow-ups:
    - Short messages (<5 words) with recent context are marked as potential follow-ups
    - LLM preserves or minimally expands follow-ups with context reference
    - Prevents incorrect expansion of context-dependent messages like "den Fisch"
    """
    # Skip normalization for very long messages (already well-formed)
    if len(user_message) > 200:
        return user_message

    # Detect potential follow-up context
    is_potential_followup = False
    previous_context = ""

    if not is_new_conversation and recent_messages:
        # Check if message is short (likely a follow-up)
        word_count = len(user_message.strip().split())
        if word_count <= 5:
            is_potential_followup = True

            # Extract last 2-3 messages for context
            context_messages = []
            for msg in recent_messages[-4:]:
                role = "User" if msg.get("role") == "user" else "Assistant"
                content = msg.get("content", "")[:200]  # Truncate long messages
                context_messages.append(f"{role}: {content}")
            previous_context = "\n".join(context_messages)

    # Build normalization prompt
    normalization_prompt = f"""Du normalisierst Benutzereingaben für ein Trennkost-Ernährungsberatungs-System.

**Deine Aufgaben:**
1. **Sprache:** Übersetze alle Texte ins Deutsche (falls nicht bereits Deutsch)
2. **Zeitangaben:** Standardisiere zu "X min" Format (z.B. "30 minuten" → "30 min", "eine halbe Stunde" → "30 min")
3. **Lebensmittel:** Verwende deutsche Standardnamen (z.B. "chicken" → "Hähnchen", "rice" → "Reis")
4. **Tippfehler:** Korrigiere offensichtliche Tippfehler (z.B. "danm" → "dann", "Resi" → "Reis")
5. **Interpunktion:** Bereinige und vervollständige
6. **Abkürzungen:** Expandiere gängige Abkürzungen (z.B. "z.B." bleibt, aber "min" → "Minuten" nur bei Mehrdeutigkeit)

**WICHTIG - Follow-up Nachrichten:**
- Wenn die Nachricht sehr kurz ist (<5 Wörter) UND vorheriger Kontext existiert, ist es wahrscheinlich eine Follow-up-Nachricht
- Follow-ups sollten NICHT erweitert werden, wenn sie klar kontextabhängig sind
- Beispiele:
  * "den Fisch" (im Kontext einer Wahlsituation) → "den Fisch" (NICHT erweitern!)
  * "ok" (als Bestätigung) → "ok" (NICHT erweitern!)
  * "egal" (als Antwort) → "egal" (NICHT erweitern!)
  * "danm" (als Standalone) → "dann" (Tippfehler korrigieren ist OK)

"""

    if is_potential_followup and previous_context:
        normalization_prompt += f"""
**VORHERIGER KONTEXT (Follow-up-Erkennung):**
{previous_context}

Die aktuelle Nachricht ist wahrscheinlich eine Follow-up-Antwort. Bewahre ihre Bedeutung, erweitere sie NICHT zu einer vollständigen Frage, außer sie ist offensichtlich unvollständig.
"""

    normalization_prompt += f"""
**Aktuelle Nachricht:**
{user_message}

**Normalisierte Nachricht:**"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": normalization_prompt}],
            temperature=0.0,
            max_tokens=150,
            timeout=5
        )
        normalized = response.choices[0].message.content.strip()

        # Safety check: if normalization is wildly different in length, use original
        original_len = len(user_message)
        normalized_len = len(normalized)
        if normalized_len > original_len * 3:  # More than 3x longer → likely over-expanded
            print(f"[NORMALIZE] Warning: normalized message too long ({normalized_len} vs {original_len}), using original")
            return user_message

        if normalized != user_message:
            print(f"[NORMALIZE] '{user_message}' → '{normalized}'")

        return normalized

    except Exception as e:
        print(f"[NORMALIZE] Failed: {e}, using original message")
        return user_message


def classify_food_items(user_message: str, standalone_query: str) -> Optional[Dict[str, Any]]:
    """
    LLM-basierte Analyse von Lebensmitteln in der Frage.
    Extrahiert und klassifiziert automatisch in Kurskategorien.
    """
    classification_prompt = f"""Analysiere die folgende Frage über Lebensmittel und klassifiziere die Komponenten
in diese Kategorien aus unserem Ernährungskurs:
- Protein (Fleisch, Fisch, Eier, Käse, Hülsenfrüchte)
- Komplexe Kohlenhydrate (Reis, Vollkornbrot, Kartoffeln, Hülsenfrüchte)
- Obst (frisch, Säfte)
- Gemüse / Salat
- Fette / Öle
- Zucker / Süßes

WICHTIG:
1. Bei zusammengesetzten Lebensmitteln (Döner, Burger, Pizza, etc.):
   - Zerlege sie in ihre Standard-Komponenten
   - Beispiele:
     * Pizza → Teig (Kohlenhydrate), Käse (Protein), Sauce (Gemüse/Zucker)
     * Döner (Standard) → Fleisch (Protein), Brot (Kohlenhydrate), Salat (Gemüse), Sauce (Fett)
     * Burger (Standard) → Fleisch (Protein), Brötchen (Kohlenhydrate)

2. Bei MEHRDEUTIGEN Lebensmitteln:
   - Wenn wichtige Details fehlen (z.B. "Burger" - vegan oder Fleisch?)
   - Oder wenn Varianten die Kombination ändern (z.B. "Pizza" - welcher Belag?)
   - Markiere dies mit "NEEDS_CLARIFICATION: [konkrete Frage]"

3. Bei Wartezeit-Fragen:
   - Erkenne Richtung (VOR oder NACH dem Verzehr)
   - Füge Keywords hinzu: "Wartedauer", "zeitlicher Abstand", "Obstverzehr"

Frage: {user_message}

Antworte im Format:
1. Erkannte Lebensmittel: [...]
2. Klassifikation: [...]
3. Falls mehrdeutig: NEEDS_CLARIFICATION: [konkrete Frage an Nutzer]
"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": classification_prompt}],
            temperature=0.1,
            max_tokens=200,
            timeout=5
        )
        result = response.choices[0].message.content.strip()

        needs_clarification = None
        if "NEEDS_CLARIFICATION:" in result:
            parts = result.split("NEEDS_CLARIFICATION:")
            classification = parts[0].strip()
            needs_clarification = parts[1].strip()
        else:
            classification = result

        return {
            "classification": classification,
            "needs_clarification": needs_clarification
        }
    except Exception:
        return None


def generalize_query(query: str) -> str:
    """
    DEPRECATED: Legacy function for regex-based query generalization.
    Kept for fallback in retrieve_with_fallback().
    """
    generalization_map = {
        r"\bburger\b": "Fleisch und Kohlenhydrate",
        r"\bpommes\b": "Kohlenhydrate",
        r"\bfisch\b": "Protein",
        r"\bhähnchen\b": "Protein",
        r"\bsalat\b": "Gemüse",
        r"\bbrot\b": "Kohlenhydrate",
        r"\breis\b": "Kohlenhydrate",
        r"\bnudeln\b": "Kohlenhydrate",
        r"\beier?\b": "Protein",
        r"\bkäse\b": "Protein",
        r"\bbanane?n?\b": "Obst",
        r"\beis\b": "Süßigkeiten",
        r"\bsahne\b": "Fett",
        r"\bschokolade\b": "Süßigkeiten",
        r"\bpudding\b": "Süßigkeiten",
        r"\bkuchen\b": "Kohlenhydrate und Zucker",
    }

    import re
    generalized = query.lower()

    for pattern, replacement in generalization_map.items():
        if re.search(pattern, generalized):
            generalized = re.sub(pattern, replacement, generalized)

    if generalized != query.lower():
        return generalized
    return None


def retrieve_with_fallback(query: str, user_message: str) -> Tuple[List[str], List[Dict], List[float], bool]:
    """Multi-step retrieval with fallback strategies."""
    docs, metas, dists = retrieve_course_snippets(query)
    docs, metas, dists = deduplicate_by_source(docs, metas, dists, max_per_source=2)

    best_dist = min(dists) if dists else 999.0

    if len(docs) >= 2 and best_dist <= DISTANCE_THRESHOLD:
        if DEBUG_RAG:
            print(f"[RAG] Primary retrieval successful (distance: {best_dist:.3f})")
        return docs, metas, dists, False

    if best_dist > DISTANCE_THRESHOLD or len(docs) < 2:
        generalized = generalize_query(user_message)
        if generalized and generalized != query.lower():
            if DEBUG_RAG:
                print(f"[RAG] Trying generalized query: {generalized}")
            docs_gen, metas_gen, dists_gen = retrieve_course_snippets(generalized)
            docs_gen, metas_gen, dists_gen = deduplicate_by_source(docs_gen, metas_gen, dists_gen, max_per_source=2)

            best_dist_gen = min(dists_gen) if dists_gen else 999.0
            if len(docs_gen) >= 1 and best_dist_gen <= (DISTANCE_THRESHOLD + 0.3):
                if DEBUG_RAG:
                    print(f"[RAG] Fallback retrieval successful (distance: {best_dist_gen:.3f})")
                return docs_gen, metas_gen, dists_gen, True

    if best_dist > DISTANCE_THRESHOLD or len(docs) < 1:
        expanded_query = expand_alias_terms(query)
        if expanded_query != query and expanded_query not in [q for q, _, _ in [(query, None, None)]]:
            if DEBUG_RAG:
                print(f"[RAG] Trying alias-expanded query")
            docs_exp, metas_exp, dists_exp = retrieve_course_snippets(expanded_query)
            docs_exp, metas_exp, dists_exp = deduplicate_by_source(docs_exp, metas_exp, dists_exp, max_per_source=2)

            best_dist_exp = min(dists_exp) if dists_exp else 999.0
            if len(docs_exp) >= 1 and best_dist_exp <= (DISTANCE_THRESHOLD + 0.2):
                if DEBUG_RAG:
                    print(f"[RAG] Alias fallback successful (distance: {best_dist_exp:.3f})")
                return docs_exp, metas_exp, dists_exp, True

    if DEBUG_RAG:
        print(f"[RAG] All retrieval strategies exhausted (best distance: {best_dist:.3f})")
    return docs, metas, dists, False

def generate_summary(old_summary: Optional[str], new_messages: List[Dict[str, Any]]) -> str:
    """Generate or update rolling summary."""
    context_parts = []

    if old_summary:
        context_parts.append(f"BISHERIGE ZUSAMMENFASSUNG:\n{old_summary}\n")

    context_parts.append("NEUE NACHRICHTEN:")
    for msg in new_messages:
        role = "User" if msg["role"] == "user" else "Assistant"
        context_parts.append(f"{role}: {msg['content']}")

    prompt = f"""{chr(10).join(context_parts)}

Erstelle eine prägnante, sachliche Zusammenfassung der Konversation.
- Maximal 3-4 Sätze
- Konzentriere dich auf die wichtigsten Themen und Fragen
- Keine neuen Fakten hinzufügen
- Deterministisch und sachlich

ZUSAMMENFASSUNG:"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=300
    )

    return response.choices[0].message.content.strip()

def should_update_summary(conversation_id: str, conv_data: Dict[str, Any]) -> bool:
    """Check if summary should be updated."""
    if not conv_data.get("summary_text"):
        total_msgs = get_total_message_count(conversation_id)
        return total_msgs >= 4
    cursor = conv_data.get("summary_message_cursor", 0)
    new_msg_count = count_messages_since_cursor(conversation_id, cursor)
    return new_msg_count >= SUMMARY_THRESHOLD

def update_conversation_summary(conversation_id: str, conv_data: Dict[str, Any]):
    """Update the rolling summary for a conversation."""
    old_summary = conv_data.get("summary_text")
    cursor = conv_data.get("summary_message_cursor", 0)
    new_messages = get_messages_since_cursor(conversation_id, cursor)
    if not new_messages:
        return
    new_summary = generate_summary(old_summary, new_messages)
    new_cursor = get_total_message_count(conversation_id)
    update_summary(conversation_id, new_summary, new_cursor)


# ── Intent classifier + RECIPE_FROM_INGREDIENTS helpers ──────────────

def classify_intent(
    user_message: str,
    context_messages: List[Dict[str, Any]],
) -> Optional[Dict]:
    """
    Parallel intent classifier. Recognizes cases that regex misses.
    Timeout: 4s. On error: None (graceful degradation).
    Returns: {"intent": "recipe_from_ingredients" | null, "confidence": "high"|"low"}
    """
    # Build compact context from last 3 messages
    ctx_parts = []
    for msg in context_messages[-3:]:
        role = "User" if msg.get("role") == "user" else "Bot"
        content = msg.get("content", "")[:150]
        ctx_parts.append(f"{role}: {content}")
    ctx_str = "\n".join(ctx_parts) if ctx_parts else "(keine Vorgeschichte)"

    prompt = f"""Du klassifizierst eine Nutzerabsicht für einen Trennkost-Bot.

KONTEXT (letzte Nachrichten):
{ctx_str}

AKTUELLE NACHRICHT:
{user_message}

Erkenne NUR diese spezifische Absicht:
"recipe_from_ingredients" – Der Nutzer möchte ein Rezept aus verfügbaren/vorhandenen Zutaten.
Signale: "ich hab nur", "zu Hause", "im Kühlschrank", "aus diesen Zutaten", "mach daraus", "nur das was ich hab", "gerade da", "vorhandene Zutaten", "was kann ich damit machen", "was mach ich damit", "aus dem was ich habe".

NIEMALS "recipe_from_ingredients" bei:
- Compliance-Fragen: "Ist X ok?", "Ist X in Ordnung?", "Ist X trennkostkonform?", "Darf ich X?", "Kann ich X essen?"
- Zeitliche Trennung: "X vor Y", "erst X dann Y", "X 30 Minuten vor Y"
- Erklärungsfragen: "Warum...?", "Wieso...?", "Was bedeutet...?"
- Rezept-Requests ohne Einschränkung: "Gib mir ein Rezept mit Hähnchen"

Wenn keines der positiven Signale eindeutig vorhanden → intent = null.

Antworte NUR mit JSON, kein Kommentar:
{{"intent": "recipe_from_ingredients" | null, "confidence": "high" | "low"}}"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=40,
            timeout=4,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()
        result = json.loads(raw)
        # Validate expected keys
        if "intent" in result and "confidence" in result:
            print(f"[INTENT] classify_intent → intent={result['intent']!r} confidence={result['confidence']!r}")
            return result
        return None
    except Exception as e:
        print(f"[INTENT] classify_intent failed (non-fatal): {e}")
        return None


def _llm_extract_ingredients(user_message: str, last_messages: List[Dict[str, Any]]) -> List[str]:
    """
    LLM-based ingredient extraction — extracts ONLY explicitly mentioned items.
    Used instead of ontology substring matching to avoid false positives.
    Returns: list of ingredient names in German, or [] on failure.
    """
    # Include last 2 user messages for context (the user may have listed ingredients earlier)
    ctx_parts = []
    for msg in last_messages[-4:]:
        if msg.get("role") == "user" and msg.get("content", "").strip() != user_message.strip():
            ctx_parts.append(f"Vorherige Nachricht: {msg.get('content', '')[:200]}")
    ctx_str = "\n".join(ctx_parts) if ctx_parts else ""

    prompt = f"""Extrahiere alle Lebensmittel/Zutaten die der Nutzer explizit als verfügbar erwähnt.
{ctx_str + chr(10) if ctx_str else ""}Aktuelle Nachricht: {user_message}

Gib NUR die Zutaten zurück, kommagetrennt, auf Deutsch, keine Erklärungen.
Nur was explizit erwähnt wird — keine Annahmen, keine Extrapolationen.
Falls keine Zutaten erwähnt: leere Antwort."""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=80,
            timeout=4,
        )
        raw = response.choices[0].message.content.strip()
        if not raw:
            return []
        items = [i.strip() for i in raw.replace(" und ", ", ").split(",") if i.strip() and len(i.strip()) >= 2]
        print(f"[EXTRACT_ING] LLM extracted: {items}")
        return items
    except Exception as e:
        print(f"[EXTRACT_ING] LLM extraction failed: {e}")
        return []


def _extract_available_ingredients(
    user_message: str,
    last_messages: List[Dict[str, Any]],
    vision_extraction: Optional[Dict],
) -> List[str]:
    """
    Extract the list of ingredients available to the user.

    Priority:
    1. Vision-extracted items (if image present)
    2. LLM-based extraction from current message + recent history
       (NOT ontology substring matching — too many false positives)

    Returns: deduplicated list. Falls back to [] if nothing found.
    """
    found: List[str] = []
    seen: set = set()

    def _add(items: List[str]):
        for item in items:
            key = item.strip().lower()
            if key and key not in seen:
                found.append(item.strip())
                seen.add(key)

    # 1. Vision extraction (highest priority)
    if vision_extraction and vision_extraction.get("dishes"):
        for dish in vision_extraction["dishes"]:
            _add(dish.get("items", []))

    if len(found) >= 2:
        return found

    # 2. LLM extraction (accurate for explicit ingredient lists)
    _add(_llm_extract_ingredients(user_message, last_messages))

    return found


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

    # Deterministic fallback (no LLM call needed if first result has very high/low overlap)
    best = overlap_results[0]
    if best["overlap_score"] >= 0.85 and not best["missing_required"]:
        return {"decision": "use_db", "recipe_id": best["id"], "adapt_notes": "", "reason": "Sehr guter Match"}
    if best["overlap_score"] < 0.4:
        return {"decision": "create_custom", "recipe_id": None, "adapt_notes": "", "reason": "Zu wenig passende Zutaten in DB-Rezepten"}

    # Medium overlap → ask LLM to decide
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
        # Deterministic fallback
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
    breakfast_note = ""
    if is_breakfast:
        breakfast_note = "\n- Frühstücks-Optionen: NUR Obst-Variante ODER KH-Variante (niemals kombiniert!)"

    prompt = f"""Erstelle ein trennkostkonformes Rezept ausschließlich aus diesen Zutaten:
{', '.join(available_ingredients)}

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

Wenn mehrere sinnvolle Varianten möglich sind (z.B. KH- oder Protein-Variante), präsentiere die beste eine Option.
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


def _handle_recipe_from_ingredients(
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
        # Find the matching recipe from overlap results
        recipe_id = feasibility["recipe_id"]
        recipe = next((r for r in overlap_results if r["id"] == recipe_id), None)
        if recipe is None:
            # Fallback: use best overlap result
            recipe = overlap_results[0] if overlap_results else None

        if recipe:
            adapt_notes = feasibility.get("adapt_notes", "")
            response = _format_recipe_directly(recipe)
            if adapt_notes:
                response += f"\n\n💡 **Hinweis:** {adapt_notes}"
            create_message(conversation_id, "assistant", response)
            return response

    # create_custom path (or use_db fallback failed)
    response = _run_custom_recipe_builder(available_ingredients, is_breakfast)
    response += "\n\n_Dieses Rezept wurde speziell für deine verfügbaren Zutaten erstellt._"
    create_message(conversation_id, "assistant", response)
    return response


# ── Pipeline steps ───────────────────────────────────────────────────

def _setup_conversation(
    conversation_id: Optional[str],
    user_message: str,
    guest_id: Optional[str],
    image_path: Optional[str],
) -> Tuple[str, bool, Dict[str, Any]]:
    """Create/validate conversation, save user message, generate title."""
    if not conversation_id:
        conversation_id = create_conversation(guest_id=guest_id)
        is_new = True
    else:
        is_new = False

    conv_data = get_conversation(conversation_id)
    if not conv_data:
        raise ValueError(f"Conversation {conversation_id} not found")

    if guest_id and not conversation_belongs_to_guest(conversation_id, guest_id):
        raise ValueError(f"Access denied to conversation {conversation_id}")

    if guest_id and not conv_data.get("guest_id"):
        from app.database import update_conversation_guest_id
        update_conversation_guest_id(conversation_id, guest_id)

    create_message(conversation_id, "user", user_message, image_path=image_path)

    if is_new:
        title = generate_title_from_message(user_message, max_words=10)
        update_conversation_title(conversation_id, title)

    return conversation_id, is_new, conv_data


def _process_vision(image_path: str, user_message: str) -> Dict[str, Any]:
    """Run vision analysis on an uploaded image."""
    result = {
        "vision_analysis": None,
        "food_groups": None,
        "vision_extraction": None,
        "vision_is_menu": False,
        "vision_failed": False,
    }
    try:
        result["vision_extraction"] = extract_food_from_image(image_path, user_message)
        result["vision_is_menu"] = result["vision_extraction"].get("type") == "menu"
        dishes = result["vision_extraction"].get("dishes", [])
        if not dishes or all(not d.get("items") for d in dishes):
            print(f"[VISION] Warning: extraction returned no usable items from image")
            result["vision_failed"] = True
        else:
            print(f"[VISION] Extracted {len(dishes)} dishes (type={result['vision_extraction'].get('type')})")
        result["vision_analysis"] = analyze_meal_image(image_path, user_message)
        if result["vision_analysis"].get("items"):
            result["food_groups"] = categorize_food_groups(result["vision_analysis"]["items"])
    except VisionAnalysisError as e:
        print(f"[VISION] Analysis failed: {e}")
        result["vision_failed"] = True
    return result


def _run_engine(
    user_message: str,
    vision_extraction: Optional[Dict],
    mode: ChatMode,
) -> Optional[List[TrennkostResult]]:
    """Run Trennkost rule engine if mode requires it."""
    if mode not in (ChatMode.FOOD_ANALYSIS, ChatMode.MENU_ANALYSIS):
        return None

    try:
        if vision_extraction and vision_extraction.get("dishes"):
            return trennkost_analyze_vision(
                vision_extraction["dishes"],
                llm_fn=_llm_call,
                mode="strict",
            )
        else:
            return trennkost_analyze_text(
                user_message,
                llm_fn=_llm_call,
                mode="strict",
            )
    except Exception as e:
        print(f"Trennkost analysis failed (non-fatal): {e}")
        import traceback
        traceback.print_exc()
        return None


def _build_rag_query(
    trennkost_results: Optional[List[TrennkostResult]],
    food_groups: Optional[Dict],
    image_path: Optional[str],
    summary: Optional[str],
    last_messages: List[Dict[str, Any]],
    user_message: str,
    is_breakfast: bool,
) -> str:
    """Build the RAG query using the most appropriate strategy."""
    if trennkost_results:
        standalone_query = build_rag_query(trennkost_results, breakfast_context=is_breakfast)
    elif image_path and food_groups:
        standalone_query = generate_trennkost_query(food_groups)
    else:
        standalone_query = rewrite_standalone_query(summary, last_messages[:-1], user_message)

    return expand_alias_terms(standalone_query)


def _check_fallback(
    trennkost_results: Optional[List[TrennkostResult]],
    mode: ChatMode,
    best_dist: float,
    is_partial: bool,
    course_context: str,
) -> bool:
    """Check if we should return fallback (no relevant content found)."""
    if trennkost_results:
        return False
    if mode == ChatMode.RECIPE_REQUEST:
        return False
    if best_dist > DISTANCE_THRESHOLD and not is_partial:
        return True
    if not course_context.strip():
        return True
    return False


def _build_prompt_parts(
    mode: ChatMode,
    modifiers: ChatModifiers,
    trennkost_results: Optional[List[TrennkostResult]],
    vision_data: Dict[str, Any],
    summary: Optional[str],
    last_messages: List[Dict[str, Any]],
    user_message: str,
    recipe_results: Optional[List[Dict]] = None,
) -> Tuple[List[str], str]:
    """Build all prompt parts and answer instructions based on mode."""
    parts = build_base_context(summary, last_messages)

    # Engine results block
    if trennkost_results:
        parts.extend(build_engine_block(trennkost_results, modifiers.is_breakfast))
        if vision_data.get("vision_is_menu"):
            parts.extend(build_menu_injection(trennkost_results))

    # Vision failed block
    image_path = bool(vision_data.get("vision_extraction") or vision_data.get("vision_failed"))
    if image_path and vision_data.get("vision_failed") and not trennkost_results:
        parts.extend(build_vision_failed_block())

    # Legacy vision block
    if vision_data.get("vision_analysis") and not trennkost_results and not vision_data.get("vision_failed"):
        parts.extend(build_vision_legacy_block(vision_data["vision_analysis"]))

    # Breakfast block (standalone, when no engine results)
    if modifiers.is_breakfast and not trennkost_results:
        parts.extend(build_breakfast_block())

    # Menu followup block
    if mode == ChatMode.MENU_FOLLOWUP and not trennkost_results:
        parts.extend(build_menu_followup_block())

    # Post-analysis acknowledgement block
    if modifiers.is_post_analysis_ack:
        parts.extend(build_post_analysis_ack_block())

    # Recipe context block (injected early, before course snippets)
    if mode == ChatMode.RECIPE_REQUEST and recipe_results:
        parts.extend(build_recipe_context_block(recipe_results))

    # Determine answer instructions based on mode
    if trennkost_results:
        answer_instructions = build_prompt_food_analysis(
            trennkost_results, user_message, modifiers.is_breakfast,
            is_compliance_check=modifiers.is_compliance_check,
        )
    elif mode == ChatMode.RECIPE_REQUEST:
        answer_instructions = build_prompt_recipe_request(
            recipe_results or [], user_message, modifiers.is_breakfast
        )
    elif vision_data.get("vision_analysis") and not vision_data.get("vision_failed"):
        answer_instructions = build_prompt_vision_legacy(user_message)
    else:
        answer_instructions = build_prompt_knowledge(
            user_message, modifiers.is_breakfast
        )

    return parts, answer_instructions


def _format_recipe_directly(recipe: Dict) -> str:
    """
    Format recipe directly without LLM, for high-score matches (≥7.0).
    Guarantees immediate output without follow-up questions.
    """
    name = recipe['name']
    time = recipe.get('time_minutes', '?')
    servings = recipe.get('servings', '?')
    full_md = recipe.get('full_recipe_md', '')

    # Remove #### headers, add bold **, skip duplicate Zeit/Portionen line
    lines = []
    skip_next_time_line = False
    for line in full_md.split('\n'):
        stripped = line.strip()

        # Skip recipe title (we add our own)
        if line.startswith('### '):
            skip_next_time_line = True  # Next line is usually Zeit: ... | Portionen:
            continue

        # Skip Zeit/Portionen line (we add our own in header)
        if skip_next_time_line and ('Zeit:' in stripped or 'Portionen:' in stripped or 'Ergibt:' in stripped):
            skip_next_time_line = False
            continue

        skip_next_time_line = False

        # Convert #### headers to **bold**
        if line.startswith('#### '):
            lines.append('**' + line[5:] + '**')
        else:
            lines.append(line)

    formatted_body = '\n'.join(lines)

    # Build final message
    intro = f"Hier ist das perfekte Rezept für dich:\n\n"
    header = f"**{name}**  \n⏱️ {time} Min. | 🍽️ {servings}\n\n"

    # Add Mandeldrink hint if present
    hint = ""
    if recipe.get('trennkost_hinweis'):
        hint = f"\n\n💡 **Hinweis:** {recipe['trennkost_hinweis']}\n"

    footer = "\n\nDieses Rezept stammt aus unserer kuratierten Rezeptdatenbank."

    return intro + header + formatted_body + hint + footer


def _generate_and_save(
    conversation_id: str,
    llm_input: str,
    mode: "ChatMode" = None,
    recipe_results: Optional[List[Dict]] = None,
) -> str:
    """
    Call LLM and save the response.

    Special case: For recipe requests with high-score matches (≥7.0),
    bypass LLM and format recipe directly to avoid unwanted follow-up questions.
    """
    # Direct recipe output for high-score matches (bypass LLM)
    if mode and recipe_results:
        from app.chat_modes import ChatMode
        if mode == ChatMode.RECIPE_REQUEST and recipe_results[0].get('score', 0.0) >= 7.0:
            assistant_message = _format_recipe_directly(recipe_results[0])
            create_message(conversation_id, "assistant", assistant_message)
            print(f"[PIPELINE] High-score recipe (≥7.0) → direct output bypass")
            return assistant_message

    # Normal LLM call
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_INSTRUCTIONS},
            {"role": "user", "content": llm_input}
        ],
        temperature=0.0,
    )
    assistant_message = response.choices[0].message.content.strip()
    create_message(conversation_id, "assistant", assistant_message)
    return assistant_message


def _prepare_sources(metas: List[Dict], dists: List[float]) -> List[Dict]:
    """Prepare source metadata for response."""
    sources = []
    for m, d in zip(metas, dists):
        sources.append({
            "path": m.get("path"),
            "source": m.get("source"),
            "page": m.get("page"),
            "chunk": m.get("chunk"),
            "distance": d,
            "module_id": m.get("module_id"),
            "module_label": m.get("module_label"),
            "submodule_id": m.get("submodule_id"),
            "submodule_label": m.get("submodule_label"),
        })
    return sources


# ── Main pipeline ────────────────────────────────────────────────────

def handle_chat(
    conversation_id: Optional[str],
    user_message: str,
    guest_id: Optional[str] = None,
    image_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Main chat handler — pipeline architecture.

    Steps:
    0. Normalize input (typo fixing, language, time formats)
    1. Setup conversation (create/validate, save ORIGINAL message, title)
    2. Process vision (if image)
    3. Detect chat mode + modifiers
    4. Run Trennkost engine (if food-related)
    5. Search recipes (if recipe request)
    6. Build RAG query + retrieve
    7. Fallback check
    8. Build prompt
    9. Generate response + save
    10. Update summary
    """
    # 1. Setup conversation (saves ORIGINAL message for transparency)
    conversation_id, is_new, conv_data = _setup_conversation(
        conversation_id, user_message, guest_id, image_path
    )

    # 1b. Get recent messages for normalization context
    recent_messages_for_norm = get_last_n_messages(conversation_id, 4)

    # 1c & 2. Parallel: Normalize + Intent + Vision (if image present)
    vision_data = {"vision_analysis": None, "food_groups": None,
                   "vision_extraction": None, "vision_is_menu": False,
                   "vision_failed": False}
    intent_result: Optional[Dict] = None

    if image_path:
        # Parallelize: Run normalization + intent classification + vision simultaneously
        with ThreadPoolExecutor(max_workers=3) as executor:
            normalize_future = executor.submit(normalize_input, user_message, recent_messages_for_norm, is_new)
            intent_future = executor.submit(classify_intent, user_message, recent_messages_for_norm)
            vision_future = executor.submit(_process_vision, image_path, user_message)

            normalized_message = normalize_future.result()
            intent_result = intent_future.result()
            vision_data = vision_future.result()
        print(f"[PIPELINE] Parallel execution: normalization + intent + vision completed")
    else:
        # No image: parallelize normalization + intent classification
        with ThreadPoolExecutor(max_workers=2) as executor:
            normalize_future = executor.submit(normalize_input, user_message, recent_messages_for_norm, is_new)
            intent_future = executor.submit(classify_intent, user_message, recent_messages_for_norm)

            normalized_message = normalize_future.result()
            intent_result = intent_future.result()
        print(f"[PIPELINE] Parallel execution: normalization + intent completed")

    # 3. Detect chat mode (use normalized message)
    vision_type = None
    if vision_data.get("vision_extraction"):
        vision_type = vision_data["vision_extraction"].get("type")

    recent = get_last_n_messages(conversation_id, 4)
    mode, modifiers = detect_chat_mode(
        normalized_message,
        image_path=image_path,
        vision_type=vision_type,
        is_new_conversation=is_new,
        recent_message_count=len(recent),
        last_messages=recent,
    )
    modifiers.vision_failed = vision_data.get("vision_failed", False)

    # 3b. Temporal separation check — runs BEFORE intent override so "Apfel 30 min vor Reis"
    # is intercepted immediately regardless of what the intent classifier returns.
    temporal_sep = detect_temporal_separation(normalized_message)
    if temporal_sep and temporal_sep["is_temporal"]:
        print(f"[PIPELINE] Temporal separation detected: {temporal_sep}")
        first = ", ".join(temporal_sep["first_foods"])
        second = ", ".join(temporal_sep["second_foods"])
        wait = temporal_sep.get("wait_time")

        response_text = f"Ja, das ist **trennkost-konform**! 🎉\n\n"
        response_text += f"Du isst {first} **zuerst allein** und wartest "
        if wait:
            response_text += f"**{wait} Minuten**, "
        response_text += f"bevor du {second} isst. Das ist sequenzielles Essen und **völlig in Ordnung**!\n\n"
        response_text += "**Wichtige Wartezeiten nach Obst:**\n"
        response_text += "- Wasserreiche Früchte (Melone, Orangen): 20-30 Min\n"
        response_text += "- Äpfel, Birnen, Beeren: 30-45 Min\n"
        response_text += "- Bananen, Trockenobst: 45-60 Min\n\n"
        if wait and wait >= 30:
            response_text += f"✅ Deine {wait} Minuten Wartezeit sind perfekt für die meisten Früchte!"
        elif wait and wait < 30:
            response_text += f"⚠️ Hinweis: {wait} Min könnten bei manchen Früchten knapp sein. Optimal sind 30-45 Min."
        else:
            response_text += "💡 Achte auf die richtigen Wartezeiten, dann ist die Trennung optimal!"

        create_message(conversation_id, "assistant", response_text)
        return {"answer": response_text, "conversationId": conversation_id}

    # 3c. Intent override — for modes where regex had no strong signal
    # Also override FOOD_ANALYSIS when it's not a compliance check (e.g. "Ich hab nur X, Y.
    # Mach daraus was" — food items get detected but the intent is really a recipe request).
    # NEVER override: MENU_ANALYSIS, MENU_FOLLOWUP, or compliance checks.
    _can_override_food_analysis = (
        mode == ChatMode.FOOD_ANALYSIS
        and not modifiers.is_compliance_check
        and not image_path  # real meal photo → always food analysis
    )
    if (
        intent_result
        and intent_result.get("intent") == "recipe_from_ingredients"
        and intent_result.get("confidence") == "high"
        and (mode in (ChatMode.KNOWLEDGE, ChatMode.RECIPE_REQUEST) or _can_override_food_analysis)
    ):
        mode = ChatMode.RECIPE_FROM_INGREDIENTS
        modifiers.intent_hint = "recipe_from_ingredients"
        print(f"[INTENT] Override → RECIPE_FROM_INGREDIENTS")

    print(f"[PIPELINE] mode={mode.value} | is_breakfast={modifiers.is_breakfast} | wants_recipe={modifiers.wants_recipe}")

    # 3d. Early-exit for RECIPE_FROM_INGREDIENTS
    if mode == ChatMode.RECIPE_FROM_INGREDIENTS:
        available_ingredients = _extract_available_ingredients(
            normalized_message, recent_messages_for_norm, vision_data.get("vision_extraction")
        )
        if available_ingredients:
            print(f"[PIPELINE] RECIPE_FROM_INGREDIENTS | ingredients={available_ingredients[:5]}")
            response = _handle_recipe_from_ingredients(
                conversation_id, available_ingredients, modifiers.is_breakfast
            )
            conv_data_updated = get_conversation(conversation_id)
            if should_update_summary(conversation_id, conv_data_updated):
                update_conversation_summary(conversation_id, conv_data_updated)
            return {"conversationId": conversation_id, "answer": response, "sources": []}
        else:
            print(f"[PIPELINE] RECIPE_FROM_INGREDIENTS: no ingredients found, falling back to RECIPE_REQUEST")
            mode = ChatMode.RECIPE_REQUEST
            modifiers.wants_recipe = True

    # 4. Run Trennkost engine (use normalized message)
    trennkost_results = _run_engine(
        normalized_message, vision_data.get("vision_extraction"), mode
    )

    if DEBUG_RAG and trennkost_results:
        for r in trennkost_results:
            print(f"[TRENNKOST] {r.dish_name}: {r.verdict.value} | "
                  f"problems={len(r.problems)} | questions={len(r.required_questions)}")

    # 5. Search recipes (if recipe request, use normalized message)
    recipe_results = None
    if mode == ChatMode.RECIPE_REQUEST:
        try:
            from app.recipe_service import search_recipes

            # For short follow-up messages (e.g. "egal", "ok"), use previous user query
            search_query = normalized_message
            if modifiers.is_followup and len(normalized_message.strip()) <= 20:
                # Extract previous substantial user message from chat history
                for msg in reversed(recent):
                    if msg.get("role") == "user":
                        content = msg.get("content", "").strip()
                        if len(content) > 20 and content != normalized_message:
                            search_query = content
                            print(f"[PIPELINE] Short follow-up detected, using previous query: '{search_query[:50]}...'")
                            break

            recipe_results = search_recipes(search_query, limit=5)
            print(f"[PIPELINE] recipe_results={len(recipe_results)} recipes found")
            for r in (recipe_results or [])[:3]:
                print(f"  → {r['name']} ({r['trennkost_category']}) score={r.get('score', '?')}")
        except Exception as e:
            print(f"[PIPELINE] recipe search failed: {e}")
            recipe_results = []

    # 6. Load context + build RAG query + retrieve (use normalized message)
    summary = conv_data.get("summary_text")
    last_messages = get_last_n_messages(conversation_id, LAST_N)

    standalone_query = _build_rag_query(
        trennkost_results, vision_data.get("food_groups"),
        image_path, summary, last_messages, normalized_message,
        modifiers.is_breakfast,
    )

    # LLM food classification for better retrieval (skip if engine already ran, use normalized message)
    needs_clarification = None
    is_followup = not is_new and len(last_messages) >= 2
    if not trennkost_results:
        food_classification_result = classify_food_items(normalized_message, standalone_query)
        if food_classification_result:
            classification = food_classification_result.get("classification", "")
            if not is_followup or len(normalized_message) > 80:
                needs_clarification = food_classification_result.get("needs_clarification")
            if classification:
                standalone_query += f"\n{classification}"

    if DEBUG_RAG:
        print(f"\n[RAG] Primary query: {standalone_query}")

    docs, metas, dists, is_partial = retrieve_with_fallback(standalone_query, normalized_message)

    if DEBUG_RAG:
        print(f"[RAG] Retrieved {len(docs)} chunk(s) | partial={is_partial}")
        for i, (doc, meta, dist) in enumerate(list(zip(docs, metas, dists))[:3], 1):
            print(f"  {i}. path={meta.get('path', '?')} | page={meta.get('page', '?')} | chunk={meta.get('chunk', '?')} | dist={dist:.3f}")

    course_context = build_context(docs, metas)

    # 7. Fallback check
    best_dist = min(dists) if dists else 999.0
    if _check_fallback(trennkost_results, mode, best_dist, is_partial, course_context):
        assistant_message = FALLBACK_SENTENCE
        create_message(conversation_id, "assistant", assistant_message)
        conv_data_updated = get_conversation(conversation_id)
        if should_update_summary(conversation_id, conv_data_updated):
            update_conversation_summary(conversation_id, conv_data_updated)
        return {
            "conversationId": conversation_id,
            "answer": assistant_message,
            "sources": []
        }

    # 8. Build prompt (use normalized message)
    prompt_parts, answer_instructions = _build_prompt_parts(
        mode, modifiers, trennkost_results, vision_data,
        summary, last_messages, normalized_message, recipe_results,
    )
    modifiers.needs_clarification = needs_clarification

    llm_input = assemble_prompt(
        prompt_parts, course_context, normalized_message,
        answer_instructions, needs_clarification,
    )

    # 9. Generate + save
    assistant_message = _generate_and_save(conversation_id, llm_input, mode, recipe_results)

    # 10. Update summary
    conv_data_updated = get_conversation(conversation_id)
    if should_update_summary(conversation_id, conv_data_updated):
        update_conversation_summary(conversation_id, conv_data_updated)

    # 11. Prepare sources
    sources = _prepare_sources(metas, dists)

    return {
        "conversationId": conversation_id,
        "answer": assistant_message,
        "sources": sources
    }
