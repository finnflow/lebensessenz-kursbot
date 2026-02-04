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
    VisionAnalysisError
)
from app.image_handler import ImageValidationError

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

WICHTIGE REGELN:
1. FAKTENBASIS: Antworte ausschließlich basierend auf den bereitgestellten KURS-SNIPPETS.
2. CHAT-KONTEXT: Nutze die Konversationshistorie nur für Referenzen und Disambiguierung (z.B. "das", "wie vorhin", "und noch").
3. GRENZEN: Wenn die Information NICHT in den Kurs-Snippets steht, sag klar: "{FALLBACK_SENTENCE}"
4. BEGRIFFS-ALIAS (wichtig): Wenn ein Begriff in der Frage NICHT wörtlich im Kursmaterial vorkommt (z.B. "Trennkost"),
   aber das KONZEPT in den Snippets beschrieben ist, dann:
   - erkläre das Konzept ausschließlich aus den Snippets
   - und weise EINMAL kurz darauf hin: "Der Begriff X wird im Kursmaterial nicht wörtlich definiert; gemeint ist hier …"
5. TEILANTWORTEN: Wenn die Frage mehrere Teile hat und nur ein Teil in den Snippets steht:
   - beantworte den belegbaren Teil
   - für den nicht belegbaren Teil verwende: "{FALLBACK_SENTENCE}"
6. KEINE SPEKULATIONEN: Erfinde keine Fakten, die nicht in den Snippets stehen.
7. KEINE MEDIZIN: Gib keine medizinische Diagnose oder Behandlungsanweisung.
8. KEINE QUELLEN IM TEXT: Nenne keine Quellenlabels im Text. Die Quellen werden automatisch angezeigt.

Du darfst auf frühere Nachrichten referenzieren, aber neue Fakten müssen aus den Kurs-Snippets kommen.
"""

def embed_one(text: str) -> List[float]:
    """Generate embedding for text."""
    resp = client.embeddings.create(model=EMBED_MODEL, input=[text])
    return resp.data[0].embedding

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


def generalize_query(query: str) -> str:
    """
    Generalize query when specific terms aren't found.
    E.g., "Burger und Pommes" → "Kohlenhydrate und Protein Kombination"
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
    if image_path:
        try:
            vision_analysis = analyze_meal_image(image_path, user_message)
            if vision_analysis.get("items"):
                food_groups = categorize_food_groups(vision_analysis["items"])
        except VisionAnalysisError as e:
            # Log error but continue with text-only response
            print(f"Vision analysis failed: {e}")

    # 7. Load context
    summary = conv_data.get("summary_text")
    last_messages = get_last_n_messages(conversation_id, LAST_N)

    # 8. Rewrite query for better retrieval
    if image_path and food_groups:
        # Use vision-based query for RAG retrieval
        standalone_query = generate_trennkost_query(food_groups)
    else:
        # Standard query rewriting
        standalone_query = rewrite_standalone_query(summary, last_messages[:-1], user_message)  # Exclude current user msg

    # Expand alias terms for better matching
    standalone_query = expand_alias_terms(standalone_query)

    # 9. Retrieve course snippets with multi-step fallback strategy
    if DEBUG_RAG:
        print(f"\n[RAG] Primary query: {standalone_query}")

    docs, metas, dists, is_partial = retrieve_with_fallback(standalone_query, user_message)

    # Debug logging
    if DEBUG_RAG:
        print(f"[RAG] Retrieved {len(docs)} chunk(s) | partial={is_partial}")
        for i, (doc, meta, dist) in enumerate(list(zip(docs, metas, dists))[:3], 1):
            print(f"  {i}. path={meta.get('path', '?')} | page={meta.get('page', '?')} | chunk={meta.get('chunk', '?')} | dist={dist:.3f}")

    course_context = build_context(docs, metas)

    # Check relevance threshold - if best match is too distant, treat as no material
    best_dist = min(dists) if dists else 999.0
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

    # Hard fallback only if we truly have no material at all
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

    if last_messages[:-1]:  # Exclude current user message
        input_parts.append("LETZTE NACHRICHTEN:")
        for msg in last_messages[:-1]:
            role = "User" if msg["role"] == "user" else "Assistant"
            input_parts.append(f"{role}: {msg['content']}")
        input_parts.append("")

    # Include vision analysis if available
    if vision_analysis:
        input_parts.append("BILD-ANALYSE (Mahlzeit):")
        input_parts.append(f"Zusammenfassung: {vision_analysis.get('summary', 'Keine Beschreibung')}")

        if vision_analysis.get("items"):
            input_parts.append("\nIdentifizierte Lebensmittel:")
            for item in vision_analysis["items"]:
                name = item.get("name", "Unbekannt")
                category = item.get("category", "?")
                amount = item.get("amount", "?")
                input_parts.append(f"  - {name} ({category}, Menge: {amount})")

        if food_groups:
            input_parts.append("\nLebensmittelgruppen:")
            if food_groups.get("carbs"):
                input_parts.append(f"  Kohlenhydrate: {', '.join(food_groups['carbs'])}")
            if food_groups.get("proteins"):
                input_parts.append(f"  Proteine: {', '.join(food_groups['proteins'])}")
            if food_groups.get("fats"):
                input_parts.append(f"  Fette: {', '.join(food_groups['fats'])}")
            if food_groups.get("vegetables"):
                input_parts.append(f"  Gemüse: {', '.join(food_groups['vegetables'])}")

        input_parts.append("")

    input_parts.append(f"KURS-SNIPPETS (FAKTENBASIS):\n{course_context}\n")
    input_parts.append(f"AKTUELLE FRAGE:\n{user_message}\n")

    # Answer instructions with concept alias handling
    if vision_analysis:
        input_parts.append(
            "ANTWORT (deutsch, präzise, materialgebunden):\n"
            "- Bewerte die Mahlzeit nach den im Kursmaterial beschriebenen Regeln.\n"
            "- Wenn ein Begriff der Frage nicht wörtlich vorkommt, aber das Konzept beschrieben ist, "
            "erkläre das Konzept aus den Snippets und erwähne das einmal kurz.\n"
        )
    else:
        input_parts.append(
            "ANTWORT (deutsch, präzise, materialgebunden):\n"
            "- Beantworte die Frage aus den Snippets.\n"
            "- Wenn der Begriff (z.B. Trennkost) nicht wörtlich definiert ist, aber die Regeln/Prinzipien "
            "im Material beschrieben sind, erkläre diese Prinzipien aus den Snippets und erwähne das einmal kurz.\n"
            f"- Nur wenn wirklich kein passender Inhalt in den Snippets ist, schreibe exakt: \"{FALLBACK_SENTENCE}\"\n"
        )

    llm_input = "\n".join(input_parts)

    # 11. Generate response
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_INSTRUCTIONS},
            {"role": "user", "content": llm_input}
        ],
        temperature=0.2,
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
