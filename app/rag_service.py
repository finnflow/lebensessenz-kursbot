"""
RAG (Retrieval-Augmented Generation) service.

Handles vector search, context building, query rewriting and alias expansion.
"""
import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any

from app.clients import (
    client, col,
    MODEL, EMBED_MODEL,
    TOP_K, MAX_CONTEXT_CHARS, DISTANCE_THRESHOLD, DEBUG_RAG,
)


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


# LEGACY: currently unused; safe to delete
def generalize_query(query: str) -> str:
    """
    DEPRECATED: Legacy function for regex-based query generalization.
    No longer called by retrieve_with_fallback().
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

    generalized = query.lower()

    for pattern, replacement in generalization_map.items():
        if re.search(pattern, generalized):
            generalized = re.sub(pattern, replacement, generalized)

    if generalized != query.lower():
        return generalized
    return None


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


def deduplicate_by_source(
    docs: List[str], metas: List[Dict], dists: List[float], max_per_source: int = 2
) -> Tuple[List[str], List[Dict], List[float]]:
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


@dataclass
class RetrievalAttempt:
    """Debug record for a single retrieval attempt inside retrieve_with_fallback."""
    variant: str                   # "PRIMARY" | "ALIAS_FALLBACK" | "NO_RESULTS"
    query: str                     # Actual query sent to ChromaDB
    threshold: Optional[float]     # Distance threshold used for acceptance
    n_results: int                 # Number of snippets returned after dedup
    best_distance: Optional[float] # Distance of the closest result (None if empty)
    accepted: bool                 # True iff this attempt produced the final output
    notes: Optional[str]           # Extra context (deprecation warnings, special cases)


def _log_rag_debug(
    user_message: str,
    attempts: List[RetrievalAttempt],
    metas: List[Dict],
    dists: List[float],
    chosen_variant: Optional[str],
) -> None:
    """Emit one structured [RAG_DEBUG] log line when DEBUG_RAG is active."""
    if not DEBUG_RAG:
        return

    used_docs = [
        {"path": m.get("path"), "chunk": m.get("chunk"), "distance": round(d, 4)}
        for m, d in zip(metas[:5], dists[:5])
    ]
    payload = {
        "user_message": user_message[:120],
        "chosen_variant": chosen_variant,
        "attempts": [asdict(a) for a in attempts],
        "used_docs": used_docs,
    }
    print(f"[RAG_DEBUG] {json.dumps(payload, ensure_ascii=False)}")


def retrieve_with_fallback(
    query: str, user_message: str
) -> Tuple[List[str], List[Dict], List[float], bool]:
    """Two-step retrieval: PRIMARY → ALIAS_FALLBACK → NO_RESULTS."""
    attempts: List[RetrievalAttempt] = []

    # --- PRIMARY ---
    docs, metas, dists = retrieve_course_snippets(query)
    docs, metas, dists = deduplicate_by_source(docs, metas, dists, max_per_source=2)
    best_dist = min(dists) if dists else 999.0
    primary_accepted = len(docs) >= 2 and best_dist <= DISTANCE_THRESHOLD
    attempts.append(RetrievalAttempt(
        variant="PRIMARY",
        query=query,
        threshold=DISTANCE_THRESHOLD,
        n_results=len(docs),
        best_distance=best_dist if dists else None,
        accepted=primary_accepted,
        notes=None,
    ))

    if primary_accepted:
        _log_rag_debug(user_message, attempts, metas, dists, "PRIMARY")
        return docs, metas, dists, False

    # --- ALIAS_FALLBACK ---
    expanded_query = expand_alias_terms(query)
    if expanded_query != query:
        exp_threshold = DISTANCE_THRESHOLD + 0.2
        docs_exp, metas_exp, dists_exp = retrieve_course_snippets(expanded_query)
        docs_exp, metas_exp, dists_exp = deduplicate_by_source(docs_exp, metas_exp, dists_exp, max_per_source=2)
        best_dist_exp = min(dists_exp) if dists_exp else 999.0
        exp_accepted = len(docs_exp) >= 1 and best_dist_exp <= exp_threshold
        attempts.append(RetrievalAttempt(
            variant="ALIAS_FALLBACK",
            query=expanded_query,
            threshold=exp_threshold,
            n_results=len(docs_exp),
            best_distance=best_dist_exp if dists_exp else None,
            accepted=exp_accepted,
            notes=None,
        ))
        if exp_accepted:
            _log_rag_debug(user_message, attempts, metas_exp, dists_exp, "ALIAS_FALLBACK")
            return docs_exp, metas_exp, dists_exp, True

    # --- NO_RESULTS ---
    attempts.append(RetrievalAttempt(
        variant="NO_RESULTS",
        query=query,
        threshold=DISTANCE_THRESHOLD,
        n_results=0,
        best_distance=best_dist if dists else None,
        accepted=False,
        notes=None,
    ))
    _log_rag_debug(user_message, attempts, metas, dists, "NO_RESULTS")
    return docs, metas, dists, False


def rewrite_standalone_query(
    summary: Optional[str],
    last_messages: List[Dict[str, Any]],
    user_message: str,
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
        max_tokens=200,
    )

    return response.choices[0].message.content.strip()
