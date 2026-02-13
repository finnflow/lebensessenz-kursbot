import os
import json
from typing import Optional, List, Dict, Any, Tuple
from dotenv import load_dotenv
from openai import OpenAI
import chromadb
from chromadb.config import Settings
from pathlib import Path

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
    analyze_text as trennkost_analyze_text,
    analyze_vision as trennkost_analyze_vision,
    format_results_for_llm,
    build_rag_query,
)
from trennkost.models import TrennkostResult

# Config
CHROMA_DIR = os.getenv("CHROMA_DIR", "storage/chroma")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "kursmaterial_v1")
FALLBACK_SENTENCE = "Diese Information steht nicht im bereitgestellten Kursmaterial."
DEBUG_RAG = os.getenv("DEBUG_RAG", "0").lower() in ("1", "true", "yes")

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
TOP_K = int(os.getenv("TOP_K", "10"))  # Increased from 6 to 10
LAST_N = int(os.getenv("LAST_N", "8"))  # Last N messages to include
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "9000"))
SUMMARY_THRESHOLD = int(os.getenv("SUMMARY_THRESHOLD", "6"))  # Update summary every N messages
DISTANCE_THRESHOLD = float(os.getenv("DISTANCE_THRESHOLD", "1.0"))  # Max L2 distance (0=identical, 1.0=moderate, 2.0=weak)

# Initialize clients
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
chroma = chromadb.PersistentClient(path=CHROMA_DIR, settings=Settings(anonymized_telemetry=False))
col = chroma.get_or_create_collection(name=COLLECTION_NAME)

SYSTEM_INSTRUCTIONS = f"""Du bist ein kurs-assistierender Bot.

ANREDE: Sprich den User IMMER mit "du" an (informell, freundlich). Verwende NIEMALS "Sie" außer der User wünscht dies explizit.

WICHTIGE REGELN:
1. FAKTENBASIS: Antworte ausschließlich basierend auf den bereitgestellten KURS-SNIPPETS.
2. CHAT-KONTEXT: Nutze die Konversationshistorie nur für Referenzen und Disambiguierung (z.B. "das", "wie vorhin", "und noch").
3. GRENZEN: Wenn die Information NICHT in den Kurs-Snippets steht, sag klar: "{FALLBACK_SENTENCE}"
   AUSNAHMEN (verwende NIEMALS Fallback bei):
   - Follow-up-Antworten auf deine eigenen Fragen (z.B. "den Rotbarsch" nach "Was möchtest du behalten?")
   - Bild-Referenzen (z.B. "du siehst ja den Teller")
   - Rezept-Requests (z.B. "gib mir ein Gericht")
   - Zusätzliche Details auf Rückfragen (z.B. "Hafermilch, wenig Zucker" nach "Welche Zutaten?")
   - Korrekturen/Klarstellungen des Users (z.B. "aber ich hab doch X gesagt", "nein, ich meinte Y", "keine X, nur Y")
4. BEGRIFFS-ALIAS (wichtig): NUR wenn der USER einen Begriff verwendet, der NICHT wörtlich im Kursmaterial vorkommt (z.B. USER fragt nach "Trennkost"),
   aber das KONZEPT in den Snippets beschrieben ist, dann:
   - erkläre das Konzept ausschließlich aus den Snippets
   - und weise EINMAL kurz darauf hin: "Der Begriff X wird im Kursmaterial nicht wörtlich definiert; gemeint ist hier …"
   WICHTIG: Führe NIEMALS selbst Begriffe ein, die nicht im Kursmaterial stehen! Verwende nur die Begriffe aus den Snippets.
5. TEILANTWORTEN: Wenn die Frage mehrere Teile hat und nur ein Teil in den Snippets steht:
   - beantworte den belegbaren Teil
   - für den nicht belegbaren Teil verwende: "{FALLBACK_SENTENCE}"
6. KEINE SPEKULATIONEN: Erfinde keine Fakten, die nicht in den Snippets stehen.
7. KEINE MEDIZIN: Gib keine medizinische Diagnose oder Behandlungsanweisung.
8. KEINE QUELLEN IM TEXT: Nenne keine Quellenlabels im Text. Die Quellen werden automatisch angezeigt.
9. ZEITLICHE REGELN (KRITISCH):
   - Lies Wartezeit-Tabellen SEHR GENAU: "Wartedauer BIS ZUM Verzehr von X" bedeutet: ERST warten, DANN X essen.
   - Beispiel: "vor dem Obstverzehr 3h Abstand" = ERST 3h nach einer Mahlzeit warten, DANN Obst essen.
   - Die Tabelle zeigt wie lange man NACH verschiedenen Mahlzeiten warten muss, BEVOR man Obst isst.
   - Nach dem Obst selbst ist die Wartezeit kurz (20-30 Min für normales Obst).
10. REZEPT-VORSCHLÄGE: Wenn der User nach einem konkreten Rezept fragt, basierend auf einer zuvor
    besprochenen konformen Kombination, darfst du ein einfaches Rezept vorschlagen.
    Die REGELN kommen aus dem Kursmaterial, die Rezeptidee darf aus deinem allgemeinen Kochwissen kommen.
    Stelle sicher, dass das Rezept die Trennkost-Regeln einhält (keine verbotenen Kombinationen).
    Markiere dies am Ende kurz: "Dieses Rezept basiert auf den Kombinationsregeln aus dem Kurs."
11. BILD-ANALYSE GRENZEN: Wenn der User auf ein hochgeladenes Bild referenziert (z.B. "du siehst ja den Teller",
    "keine Ahnung, schau doch", "auf dem Foto"), dann ist das KEINE Kursmaterial-Frage!
    - Basierend auf dem Gericht: Mache eine REALISTISCHE Schätzung für typische Portionsgrößen
    - Beispiel Pfannengericht mit Gemüse: "Ich schätze ca. 2-3 EL Öl für so eine Portion"
    - Beispiel Salat mit Sesam: "Ich schätze ca. 1 EL Sesam (das überschreitet 1-2 TL) → nur mit Gemüse OK"
    - Gib dann das finale Verdict basierend auf dieser Schätzung
    - KRITISCH: Verwende NIEMALS "{FALLBACK_SENTENCE}" bei Bild-Referenzen!
    - Wenn der User sagt "keine Ahnung" auf deine Mengen-Frage, ist das eine Bild-Referenz, kein "weiß nicht"!
12. FOLLOW-UP auf FIX-RICHTUNGEN: Wenn du zuvor gefragt hast "Was möchtest du behalten?" und der User
    antwortet mit einem Lebensmittel oder einer Gruppe (z.B. "den Rotbarsch", "die Kartoffel", "das Protein",
    "lieber den Reis"), dann ist das KEINE Kursmaterial-Frage!
    - Erkenne dies als ANTWORT auf deine eigene Frage
    - Schlage SOFORT ein konkretes Gericht vor basierend auf der Wahl
    - Beispiel: User wählt "Rotbarsch" → schlage vor: "Rotbarsch mit Brokkoli, Paprika und Zitrone"
    - Das Gericht darf NUR die gewählte Komponente + stärkearmes Gemüse/Salat enthalten
    - KRITISCH: Verwende NIEMALS "{FALLBACK_SENTENCE}" bei Follow-up-Antworten!
    - Wenn unsicher welche Komponente gemeint ist, frage kurz nach, aber gib NICHT den Fallback-Satz!
13. SCHLEIFEN-SCHUTZ: Wenn du eine Frage gestellt hast (z.B. "Welche Zutaten?") und der User antwortet,
    dann stelle NIEMALS die GLEICHE Frage nochmal!
    - Prüfe den Chat-Verlauf: Habe ich diese Frage schon gestellt?
    - Wenn der User Zutaten genannt hat (auch unvollständig), arbeite damit weiter
    - Beispiel: User sagt "Hafermilch, wenig Zucker" → analysiere das! Frage NICHT nochmal nach Zutaten!
    - Wenn immer noch unklar: Stelle eine ANDERE, spezifischere Frage
    - VERBOTEN: Identische Frage wiederholen → führt zu Frustration!
14. KORREKTUR-ERKENNUNG: Wenn der User seine vorherige Aussage korrigiert oder klarstellt,
    dann ist das KEINE Kursmaterial-Frage!
    - Muster: "aber ich hab doch X gesagt", "nein, keine X, nur Y", "hab doch keine X"
    - KRITISCH: Verwende NIEMALS "{FALLBACK_SENTENCE}" bei Korrekturen!
    - Beispiel: User sagt "normaler mit Hafermilch", du verstehst "normale Milch + Hafermilch",
      User korrigiert "aber hab doch Hafermilch keine normale Milch" → RE-ANALYSIERE mit Hafermilch!
    - Erkenne Missverständnisse, entschuldige dich kurz und analysiere korrekt: "Ah verstehe, nur Hafermilch! ..."

Du darfst auf frühere Nachrichten referenzieren, aber neue Fakten müssen aus den Kurs-Snippets kommen.
"""

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
    # If no context, return as-is
    if not summary and not last_messages:
        return user_message

    # Build context for query rewriting
    context_parts = []
    if summary:
        context_parts.append(f"ZUSAMMENFASSUNG:\n{summary}\n")

    if last_messages:
        context_parts.append("LETZTE NACHRICHTEN:")
        for msg in last_messages[-4:]:  # Only last 4 for query rewriting
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

    # Check each alias key
    for key, aliases in ALIAS_TERMS.items():
        if key in query_lower:
            # Add aliases separated by pipe
            alias_str = " | " + " | ".join(aliases)
            expanded += alias_str
            break  # Only expand first match to avoid bloat

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
    """
    Deduplicate chunks by source file to ensure diverse retrieval.
    Keeps top-N chunks per source (by distance), skips rest.

    Helps prevent one long page from dominating the context.
    """
    seen_sources = {}  # source -> count
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


def classify_food_items(user_message: str, standalone_query: str) -> Optional[Dict[str, Any]]:
    """
    LLM-basierte Analyse von Lebensmitteln in der Frage.
    Extrahiert und klassifiziert automatisch in Kurskategorien.
    Erkennt auch Fragen zu Wartezeiten und mehrdeutige Lebensmittel.

    Returns: Dict mit 'classification' (str) und optional 'needs_clarification' (str)
    Example: {"classification": "Obst, Zucker/Süßes, Fett", "needs_clarification": None}
    Example: {"classification": "Burger", "needs_clarification": "Ist der Burger vegan oder mit Fleisch?"}
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

        # Check if clarification needed
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
    New code should use classify_food_items() instead.
    """
    # Extract main food words and map to course concepts
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

    # Only return if actually generalized
    if generalized != query.lower():
        return generalized
    return None


def retrieve_with_fallback(query: str, user_message: str) -> Tuple[List[str], List[Dict], List[float], bool]:
    """
    Multi-step retrieval with fallback strategies.

    Returns: (docs, metas, dists, is_partial)
    is_partial=True means results came from fallback, answer should note this
    """
    # Step 1: Primary retrieval
    docs, metas, dists = retrieve_course_snippets(query)
    docs, metas, dists = deduplicate_by_source(docs, metas, dists, max_per_source=2)

    best_dist = min(dists) if dists else 999.0

    # If excellent matches, return immediately
    if len(docs) >= 2 and best_dist <= DISTANCE_THRESHOLD:
        if DEBUG_RAG:
            print(f"[RAG] Primary retrieval successful (distance: {best_dist:.3f})")
        return docs, metas, dists, False

    # Step 2: Try generalized query
    if best_dist > DISTANCE_THRESHOLD or len(docs) < 2:
        generalized = generalize_query(user_message)
        if generalized and generalized != query.lower():
            if DEBUG_RAG:
                print(f"[RAG] Trying generalized query: {generalized}")
            docs_gen, metas_gen, dists_gen = retrieve_course_snippets(generalized)
            docs_gen, metas_gen, dists_gen = deduplicate_by_source(docs_gen, metas_gen, dists_gen, max_per_source=2)

            best_dist_gen = min(dists_gen) if dists_gen else 999.0
            if len(docs_gen) >= 1 and best_dist_gen <= (DISTANCE_THRESHOLD + 0.3):  # Slightly more lenient
                if DEBUG_RAG:
                    print(f"[RAG] Fallback retrieval successful (distance: {best_dist_gen:.3f})")
                return docs_gen, metas_gen, dists_gen, True  # Mark as partial

    # Step 3: Try alias expansion again (already done in primary, but as fallback)
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

    # All fallbacks exhausted
    if DEBUG_RAG:
        print(f"[RAG] All retrieval strategies exhausted (best distance: {best_dist:.3f})")
    return docs, metas, dists, False

def generate_summary(old_summary: Optional[str], new_messages: List[Dict[str, Any]]) -> str:
    """
    Generate or update rolling summary.
    Summary should be concise, factual, and deterministic.
    """
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
    # Always update if no summary exists
    if not conv_data.get("summary_text"):
        total_msgs = get_total_message_count(conversation_id)
        return total_msgs >= 4  # At least 2 turns (4 messages)

    # Check if enough new messages since last summary
    cursor = conv_data.get("summary_message_cursor", 0)
    new_msg_count = count_messages_since_cursor(conversation_id, cursor)

    return new_msg_count >= SUMMARY_THRESHOLD

def update_conversation_summary(conversation_id: str, conv_data: Dict[str, Any]):
    """Update the rolling summary for a conversation."""
    old_summary = conv_data.get("summary_text")
    cursor = conv_data.get("summary_message_cursor", 0)

    # Get new messages since cursor
    new_messages = get_messages_since_cursor(conversation_id, cursor)

    if not new_messages:
        return

    # Generate new summary
    new_summary = generate_summary(old_summary, new_messages)

    # Update cursor to current message count
    new_cursor = get_total_message_count(conversation_id)

    # Save to database
    update_summary(conversation_id, new_summary, new_cursor)

def handle_chat(
    conversation_id: Optional[str],
    user_message: str,
    guest_id: Optional[str] = None,
    image_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Main chat handler with rolling summary and optional image analysis.

    Flow:
    1. Create conversation if needed
    2. Verify guest access
    3. Save user message
    4. Auto-generate title if first message
    5. Analyze image if provided (Vision API)
    6. Load summary + last N messages
    7. Rewrite query if needed (or use vision-based query)
    8. Retrieve course snippets
    9. Generate response with LLM (include vision analysis)
    10. Save assistant message
    11. Update summary if threshold reached
    """
    # 1. Create or get conversation
    if not conversation_id:
        conversation_id = create_conversation(guest_id=guest_id)
        is_new_conversation = True
    else:
        is_new_conversation = False

    conv_data = get_conversation(conversation_id)
    if not conv_data:
        raise ValueError(f"Conversation {conversation_id} not found")

    # 2. Verify guest access (with backwards compatibility)
    if guest_id and not conversation_belongs_to_guest(conversation_id, guest_id):
        raise ValueError(f"Access denied to conversation {conversation_id}")

    # 3. If conversation has no guest_id but guest_id is provided, update it (migration)
    if guest_id and not conv_data.get("guest_id"):
        from app.database import update_conversation_guest_id
        update_conversation_guest_id(conversation_id, guest_id)

    # 4. Save user message (with image_path if provided)
    create_message(conversation_id, "user", user_message, image_path=image_path)

    # 5. Auto-generate title if first message
    if is_new_conversation:
        title = generate_title_from_message(user_message, max_words=10)
        update_conversation_title(conversation_id, title)

    # 6. Analyze image if provided
    vision_analysis = None
    food_groups = None
    vision_extraction = None  # New: structured extraction for engine
    if image_path:
        try:
            # New structured extraction for Trennkost engine
            vision_extraction = extract_food_from_image(image_path, user_message)
            # Legacy analysis for backward compat
            vision_analysis = analyze_meal_image(image_path, user_message)
            if vision_analysis.get("items"):
                food_groups = categorize_food_groups(vision_analysis["items"])
        except VisionAnalysisError as e:
            print(f"Vision analysis failed: {e}")

    # ── 6b. Trennkost Rule Engine Analysis ─────────────────────────
    trennkost_results: Optional[List[TrennkostResult]] = None
    is_food_query = bool(image_path) or detect_food_query(user_message)

    # In follow-up messages, only re-run engine if actual food items found (2+),
    # not just generic keywords like "gericht" or "mahlzeit"
    _recent = get_last_n_messages(conversation_id, 4)
    is_followup = not is_new_conversation and len(_recent) >= 2
    if is_food_query and is_followup and not image_path:
        from trennkost.ontology import get_ontology as _get_ontology
        _ont = _get_ontology()
        import re as _re
        _words = _re.split(r'[,;\s]+', user_message.strip())
        _food_count = sum(1 for w in _words if w.strip() and len(w.strip()) >= 3 and _ont.lookup(w.strip()))
        if _food_count < 2:
            is_food_query = False

    if is_food_query:
        try:
            if vision_extraction and vision_extraction.get("dishes"):
                trennkost_results = trennkost_analyze_vision(
                    vision_extraction["dishes"],
                    llm_fn=_llm_call,
                    mode="strict",
                )
            else:
                trennkost_results = trennkost_analyze_text(
                    user_message,
                    llm_fn=_llm_call,
                    mode="strict",
                )
            if DEBUG_RAG:
                for r in (trennkost_results or []):
                    print(f"[TRENNKOST] {r.dish_name}: {r.verdict.value} | "
                          f"problems={len(r.problems)} | questions={len(r.required_questions)}")
        except Exception as e:
            print(f"Trennkost analysis failed (non-fatal): {e}")
            import traceback
            traceback.print_exc()

    # 6c. Breakfast context detection
    is_breakfast = detect_breakfast_context(user_message)

    # 7. Load context
    summary = conv_data.get("summary_text")
    last_messages = get_last_n_messages(conversation_id, LAST_N)

    # 8. Rewrite query for better retrieval
    if trennkost_results:
        # Use engine-targeted RAG query for relevant course sections
        standalone_query = build_rag_query(trennkost_results, breakfast_context=is_breakfast)
    elif image_path and food_groups:
        standalone_query = generate_trennkost_query(food_groups)
    else:
        standalone_query = rewrite_standalone_query(summary, last_messages[:-1], user_message)

    # Expand alias terms for better matching
    standalone_query = expand_alias_terms(standalone_query)

    # LLM-based food classification for better retrieval (skip if engine already ran)
    needs_clarification = None
    is_followup = not is_new_conversation and len(last_messages) >= 2
    if not trennkost_results:
        food_classification_result = classify_food_items(user_message, standalone_query)
        if food_classification_result:
            classification = food_classification_result.get("classification", "")
            # Don't inject needs_clarification for short follow-up messages —
            # it causes infinite clarification loops when user answers a question
            if not is_followup or len(user_message) > 80:
                needs_clarification = food_classification_result.get("needs_clarification")
            if classification:
                standalone_query += f"\n{classification}"

    # 9. Retrieve course snippets with multi-step fallback strategy
    if DEBUG_RAG:
        print(f"\n[RAG] Primary query: {standalone_query}")

    docs, metas, dists, is_partial = retrieve_with_fallback(standalone_query, user_message)

    if DEBUG_RAG:
        print(f"[RAG] Retrieved {len(docs)} chunk(s) | partial={is_partial}")
        for i, (doc, meta, dist) in enumerate(list(zip(docs, metas, dists))[:3], 1):
            print(f"  {i}. path={meta.get('path', '?')} | page={meta.get('page', '?')} | chunk={meta.get('chunk', '?')} | dist={dist:.3f}")

    course_context = build_context(docs, metas)

    # Check relevance — but if we have engine results, always proceed
    best_dist = min(dists) if dists else 999.0
    if not trennkost_results:
        if best_dist > DISTANCE_THRESHOLD and not is_partial:
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

        if not course_context.strip():
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

    # 10. Build LLM input
    input_parts = []

    if summary:
        input_parts.append(f"KONVERSATIONS-ZUSAMMENFASSUNG:\n{summary}\n")

    if last_messages[:-1]:
        input_parts.append("LETZTE NACHRICHTEN:")
        for msg in last_messages[:-1]:
            role = "User" if msg["role"] == "user" else "Assistant"
            input_parts.append(f"{role}: {msg['content']}")
        input_parts.append("")

    # ── Inject Trennkost engine results ────────────────────────────
    if trennkost_results:
        engine_context = format_results_for_llm(trennkost_results, breakfast_context=is_breakfast)
        input_parts.append(engine_context)
        input_parts.append("")

    # Include vision summary if available (not the old categorization)
    if vision_analysis and not trennkost_results:
        input_parts.append("BILD-ANALYSE (Mahlzeit):")
        input_parts.append(f"Zusammenfassung: {vision_analysis.get('summary', 'Keine Beschreibung')}")
        if vision_analysis.get("items"):
            input_parts.append("\nIdentifizierte Lebensmittel:")
            for item in vision_analysis["items"]:
                name = item.get("name", "Unbekannt")
                category = item.get("category", "?")
                amount = item.get("amount", "?")
                input_parts.append(f"  - {name} ({category}, Menge: {amount})")
        input_parts.append("")

    # ── Inject standalone breakfast guidance if breakfast detected but no engine results ──
    if is_breakfast and not trennkost_results:
        input_parts.append("FRÜHSTÜCKS-HINWEIS (Kurs Modul 1.2):")
        input_parts.append("Das Kursmaterial empfiehlt ein zweistufiges Frühstück:")
        input_parts.append("  1. Frühstück: Frisches Obst ODER Grüner Smoothie (fettfrei)")
        input_parts.append("     → Obst verdaut in 20-30 Min, Bananen/Trockenobst 45-60 Min")
        input_parts.append("  2. Frühstück (falls 1. nicht reicht): Fettfreie Kohlenhydrate (max 1-2 TL Fett)")
        input_parts.append("     → Empfehlungen: Overnight-Oats, Porridge, Reis-Pudding, Hirse-Grieß,")
        input_parts.append("       glutenfreies Brot mit Gurke/Tomate + max 1-2 TL Avocado")
        input_parts.append("")
        input_parts.append("WARUM FETTARM VOR MITTAGS?")
        input_parts.append("  Bis mittags läuft die Entgiftung des Körpers auf Hochtouren.")
        input_parts.append("  Leichte Kost spart Verdauungsenergie → mehr Energie für Entgiftung/Entschlackung.")
        input_parts.append("  Fettreiche Lebensmittel belasten die Verdauung und behindern diesen Prozess.")
        input_parts.append("")
        input_parts.append("ANWEISUNG: Erwähne das zweistufige Frühstücks-Konzept PROAKTIV in deiner Antwort!")
        input_parts.append("Empfehle IMMER zuerst die fettarme Option (Obst/Smoothie, dann ggf. fettfreie KH).")
        input_parts.append("")

    input_parts.append(f"KURS-SNIPPETS (FAKTENBASIS):\n{course_context}\n")
    input_parts.append(f"AKTUELLE FRAGE:\n{user_message}\n")

    # Add clarification note if needed (legacy path)
    if needs_clarification:
        input_parts.append(f"WICHTIG - MEHRDEUTIGES LEBENSMITTEL:\n{needs_clarification}\n")
        input_parts.append(
            "Bitte stelle diese Rückfrage ZUERST, bevor du die Hauptfrage beantwortest. "
            "Erkläre kurz, warum die Info wichtig ist.\n"
        )

    # Answer instructions — different when engine results are present
    if trennkost_results:
        # Extract actual verdict for explicit instruction
        verdict_str = trennkost_results[0].verdict.value if trennkost_results else "UNKNOWN"
        verdict_display = {
            "OK": "OK",
            "NOT_OK": "NICHT OK",
            "CONDITIONAL": "BEDINGT OK",
            "UNKNOWN": "UNKLAR"
        }.get(verdict_str, verdict_str)

        input_parts.append(
            f"USER'S ORIGINAL MESSAGE: {user_message}\n\n"
            "ANTWORT-ANWEISUNGEN:\n"
            f"KRITISCH: Das Verdict lautet '{verdict_display}'. Gib dies EXAKT so wieder.\n"
            "- Offene Fragen bedeuten NICHT, dass das Verdict 'bedingt' ist.\n"
            "- Bei 'NICHT OK': Auch wenn Rückfragen bestehen, bleibt es NICHT OK.\n"
            "- Bei 'BEDINGT OK': Nur dann 'bedingt' sagen, wenn oben CONDITIONAL steht.\n"
            "- Das Verdict wurde DETERMINISTISCH ermittelt und darf NICHT interpretiert werden.\n"
            "- KRITISCH: Wenn oben 'KEINE OFFENEN FRAGEN' steht, dann gibt es NULL weitere Fragen.\n"
            "  Erwähne NICHTS über 'typische Zutaten', 'weitere Zutaten', oder 'könnte die Bewertung ändern'.\n"
            "  Sprich NUR über Zutaten die in der 'Gruppen'-Liste oben stehen. IGNORIERE Infos aus RAG-Snippets\n"
            "  über angeblich 'typische' Zutaten die NICHT in der Gruppen-Liste sind.\n"
            "  VERBOTEN: 'Sind X, Y, Z enthalten?', 'Falls X enthalten ist...', 'Diese Info könnte ändern...'\n"
            "  ERLAUBT: Verdict erklären basierend auf den Zutaten in der Gruppen-Liste, fertig.\n"
            "- Bei INFO-Level Problemen (z.B. Zucker-Empfehlung):\n"
            "  Diese sind KEINE Trennkost-Verstöße, sondern Gesundheits-Empfehlungen aus dem Kurs.\n"
            "  Erwähne sie KURZ und freundlich am Ende (z.B. 'Kleiner Tipp: Honig oder Ahornsirup wären gesünder als Zucker.').\n"
            "  Das Verdict bleibt OK oder BEDINGT OK, nicht NICHT OK wegen INFO-Problemen!\n"
            "\nSTIL & FORMAT:\n"
            "- Schreibe natürlich und freundlich, wie ein Ernährungsberater — KEIN Bericht-Format.\n"
            "- Beginne mit dem Verdict als kurze, klare Aussage (z.B. 'Spaghetti Carbonara ist leider **nicht trennkost-konform**.').\n"
            "- Erkläre die Probleme kurz und verständlich (keine nummerierten Listen, kein Fachjargon).\n"
            "- Belege mit Kurs-Snippets, aber baue es natürlich in den Text ein.\n"
            "- Bei NOT_OK mit ALTERNATIVEN-Block:\n"
            "  Frage den User: 'Was möchtest du behalten — [Gruppe A] oder [Gruppe B]?'\n"
            "  WICHTIG: Die Richtungen sind EXKLUSIV. 'Behalte KH' heißt: NUR KH + Gemüse, KEIN Protein!\n"
            "  'Behalte Protein' heißt: NUR Protein + Gemüse, KEINE Kohlenhydrate!\n"
            "- REZEPT-VALIDIERUNG (KRITISCH — lies das!):\n"
            "  Bevor du ein Rezept oder eine Alternative vorschlägst, prüfe JEDE Zutat gegen die Regeln!\n"
            "  VERBOTENE Kombinationen die du NIEMALS vorschlagen darfst:\n"
            "  ❌ Käseomelette = Käse (MILCH) + Ei (PROTEIN) → R006 Verstoß!\n"
            "  ❌ Käse + Schinken = MILCH + PROTEIN → R006 Verstoß!\n"
            "  ❌ Ei + Brot/Toast = PROTEIN + KH → R001 Verstoß!\n"
            "  ❌ Ei + Käse = PROTEIN + MILCH → R006 Verstoß!\n"
            "  ❌ Käse + Brot = MILCH + KH → R002 Verstoß!\n"
            "  ❌ Joghurt + Müsli = MILCH + KH → R002 Verstoß!\n"
            "  GRUNDREGEL für Alternativen:\n"
            "  Gewählte Gruppe + NEUTRAL (Gemüse/Salat) = EINZIG erlaubte Kombination!\n"
            "  'Behalte MILCH' → NUR Milchprodukte + Gemüse. KEIN Ei, KEIN Fleisch, KEIN Brot!\n"
            "  'Behalte PROTEIN' → NUR Fleisch/Fisch/Ei + Gemüse. KEINE KH, KEINE Milch!\n"
            "  'Behalte KH' → NUR Brot/Reis/Pasta + Gemüse. KEIN Protein, KEINE Milch!\n"
            + (
                "- FRÜHSTÜCK-SPEZIFISCH (User fragt nach Frühstück!):\n"
                "  1. Empfehle ZUERST die fettarme Option aus dem FRÜHSTÜCKS-HINWEIS oben.\n"
                "  2. Erkläre KURZ warum: Entgiftung läuft bis mittags, fettarme Kost optimal.\n"
                "  3. Erwähne das zweistufige Frühstücks-Konzept (1. Obst → 2. fettfreie KH).\n"
                "  4. Falls User auf fettreiche Option besteht: erlaubt, aber mit freundlichem Hinweis.\n"
                "  5. Konkrete fettarme Empfehlungen: Obst, Grüner Smoothie, Overnight-Oats, Porridge,\n"
                "     Reis-Pudding, Hirse-Grieß, glutenfreies Brot mit Gemüse + max 1-2 TL Avocado.\n"
                if is_breakfast else ""
            ) +
            "- Bei BEDINGT OK:\n"
            "  1. Erkläre kurz, warum es bedingt ist\n"
            "  2. Stelle die offene Frage aus 'Offene Fragen' (z.B. 'Wie viel Fett ist enthalten?')\n"
            "  3. WICHTIG: Schlage KEINE zusätzlichen Zutaten oder Alternativen vor!\n"
            "  4. Konzentriere dich NUR auf die Klärung der offenen Frage\n"
            "- Verwende AUSSCHLIESSLICH Begriffe aus den Kurs-Snippets.\n"
        )
    elif vision_analysis:
        input_parts.append(
            "ANTWORT (deutsch, präzise, materialgebunden):\n"
            "- Bewerte die Mahlzeit nach den im Kursmaterial beschriebenen Regeln.\n"
            "- Verwende AUSSCHLIESSLICH Begriffe aus den Kurs-Snippets.\n"
        )
    else:
        breakfast_instruction = ""
        if is_breakfast:
            breakfast_instruction = (
                "- FRÜHSTÜCK-SPEZIFISCH (User fragt nach Frühstück!):\n"
                "  Das Kursmaterial empfiehlt ein zweistufiges Frühstück:\n"
                "  1. Frühstück: Frisches Obst ODER Grüner Smoothie (fettfrei)\n"
                "     → Obst verdaut in 20-30 Min, dann 2. Frühstück möglich\n"
                "  2. Frühstück: Fettfreie Kohlenhydrate (max 1-2 TL Fett)\n"
                "     → Overnight-Oats, Porridge, Reis-Pudding, Hirse, glutenfreies Brot + Gemüse\n"
                "  WARUM: Bis mittags läuft Entgiftung — fettarme Kost spart Verdauungsenergie.\n"
                "  → Empfehle IMMER zuerst die fettarme Option. Bei Insistieren: erlaubt, aber mit Hinweis.\n"
            )
        input_parts.append(
            "ANTWORT (deutsch, natürlich, materialgebunden):\n"
            "- Beantworte die Frage aus den Snippets.\n"
            "- Schreibe natürlich und freundlich, nicht wie ein Bericht.\n"
            "- PROAKTIV HANDELN: Lieber einen konkreten Vorschlag machen als weitere Fragen stellen.\n"
            "- KRITISCH - FOLLOW-UP ERKENNUNG: Prüfe den Chat-Verlauf:\n"
            "  Hast du zuvor 'Was möchtest du behalten?' gefragt? Dann ist jede kurze Antwort\n"
            "  wie 'den Rotbarsch', 'die Kartoffel', 'das Protein' eine ANTWORT darauf!\n"
            "  → Verwende NIEMALS '{FALLBACK_SENTENCE}' für Follow-up-Antworten!\n"
            "  → Schlage SOFORT ein Gericht vor: 'Rotbarsch mit Brokkoli, Paprika, Zitrone'\n"
            "  → Das Gericht darf NUR die gewählte Komponente + Gemüse enthalten\n"
            "  → KEINE KH wenn Protein gewählt! KEINE Proteine wenn KH gewählt!\n"
            "- REZEPT-VALIDIERUNG: Prüfe JEDES vorgeschlagene Rezept gegen die Regeln!\n"
            "  ❌ Käseomelette = Käse (MILCH) + Ei (PROTEIN) → VERBOTEN!\n"
            "  ❌ Käse + Schinken/Fleisch = MILCH + PROTEIN → VERBOTEN!\n"
            "  ❌ Ei + Brot = PROTEIN + KH → VERBOTEN!\n"
            "  ❌ Ei + Käse = PROTEIN + MILCH → VERBOTEN!\n"
            "  Gewählte Gruppe + Gemüse/Salat = EINZIG erlaubte Kombination!\n"
            + breakfast_instruction +
            "- Wenn der User ein Rezept will ('ja gib aus', 'Rezept bitte', 'ja'):\n"
            "  Gib SOFORT ein vollständiges Rezept mit Zutaten und Zubereitung.\n"
            "  Wiederhole NICHT den vorherigen Vorschlag als Frage.\n"
            "- Wenn der User sagt 'soll X nahe kommen' oder 'ähnlich wie X':\n"
            "  Analysiere welche Komponenten von X konform sind (z.B. Reisnudeln, Gemüse)\n"
            "  und welche nicht (z.B. Ei/Tofu). Schlage eine Variante VOR die die konformen\n"
            "  Komponenten nutzt. Wiederhole NICHT das vorherige Rezept.\n"
            f"- Nur wenn wirklich kein passender Inhalt ist: \"{FALLBACK_SENTENCE}\"\n"
        )

    llm_input = "\n".join(input_parts)

    # 11. Generate response
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_INSTRUCTIONS},
            {"role": "user", "content": llm_input}
        ],
        temperature=0.0,  # Fully deterministic to prevent creative hallucinations
    )

    assistant_message = response.choices[0].message.content.strip()

    # 12. Save assistant message
    create_message(conversation_id, "assistant", assistant_message)

    # 13. Update summary if needed
    conv_data_updated = get_conversation(conversation_id)
    if should_update_summary(conversation_id, conv_data_updated):
        update_conversation_summary(conversation_id, conv_data_updated)

    # 14. Prepare sources with module metadata
    sources = []
    for m, d in zip(metas, dists):
        sources.append({
            "path": m.get("path"),
            "source": m.get("source"),
            "page": m.get("page"),
            "chunk": m.get("chunk"),
            "distance": d,
            # Module metadata for professional display
            "module_id": m.get("module_id"),
            "module_label": m.get("module_label"),
            "submodule_id": m.get("submodule_id"),
            "submodule_label": m.get("submodule_label"),
        })

    return {
        "conversationId": conversation_id,
        "answer": assistant_message,
        "sources": sources
    }
