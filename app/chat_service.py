import os
from typing import Optional, List, Dict, Any, Tuple
from dotenv import load_dotenv
from openai import OpenAI
import chromadb
from chromadb.config import Settings

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
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
TOP_K = int(os.getenv("TOP_K", "10"))  # Increased from 6 to 10
LAST_N = int(os.getenv("LAST_N", "8"))  # Last N messages to include
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "9000"))
SUMMARY_THRESHOLD = int(os.getenv("SUMMARY_THRESHOLD", "6"))  # Update summary every N messages

# Initialize clients
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
chroma = chromadb.PersistentClient(path=CHROMA_DIR, settings=Settings(anonymized_telemetry=False))
col = chroma.get_or_create_collection(name=COLLECTION_NAME)

SYSTEM_INSTRUCTIONS = """Du bist ein kurs-assistierender Bot.

WICHTIGE REGELN:
1. FAKTENBASIS: Antworte ausschließlich basierend auf den bereitgestellten KURS-SNIPPETS.
2. CHAT-KONTEXT: Nutze die Konversationshistorie nur für Referenzen und Disambiguierung (z.B. "das", "wie vorhin", "und noch").
3. GRENZEN: Wenn die Information NICHT in den Kurs-Snippets steht, sag klar: "Diese Information steht nicht im bereitgestellten Kursmaterial."
4. KEINE SPEKULATIONEN: Erfinde keine Fakten, die nicht in den Snippets stehen.
5. KEINE MEDIZIN: Gib keine medizinische Diagnose oder Behandlungsanweisung.
6. KEINE QUELLEN IM TEXT: Nenne keine Quellenlabels im Text. Die Quellen werden automatisch angezeigt.

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
Antworte NUR mit der umgeschriebenen Anfrage, ohne Erklärung.

STANDALONE QUERY:"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=200
    )

    return response.choices[0].message.content.strip()

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

    # 9. Retrieve course snippets
    docs, metas, dists = retrieve_course_snippets(standalone_query)
    course_context = build_context(docs, metas)

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

    if vision_analysis:
        input_parts.append("ANTWORT (deutsch, präzise, materialgebunden - bewerte die Mahlzeit nach Trennkost-Regeln):")
    else:
        input_parts.append("ANTWORT (deutsch, präzise, materialgebunden):")

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

    # 14. Prepare sources
    sources = []
    for m, d in zip(metas, dists):
        sources.append({
            "path": m.get("path"),
            "source": m.get("source"),
            "page": m.get("page"),
            "chunk": m.get("chunk"),
            "distance": d
        })

    return {
        "conversationId": conversation_id,
        "answer": assistant_message,
        "sources": sources
    }
