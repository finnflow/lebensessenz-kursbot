"""
Singleton clients and shared configuration for the app.

Import from here to avoid re-initializing OpenAI/ChromaDB in multiple modules:
    from app.clients import client, col, MODEL, EMBED_MODEL, LAST_N, SUMMARY_THRESHOLD, ...
"""
import os
from dotenv import load_dotenv
from openai import OpenAI
import chromadb
from chromadb.config import Settings

load_dotenv()

# ── Model config ──────────────────────────────────────────────────────
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

# ── Retrieval config ──────────────────────────────────────────────────
TOP_K = int(os.getenv("TOP_K", "10"))
LAST_N = int(os.getenv("LAST_N", "8"))
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "9000"))
SUMMARY_THRESHOLD = int(os.getenv("SUMMARY_THRESHOLD", "6"))
DISTANCE_THRESHOLD = float(os.getenv("DISTANCE_THRESHOLD", "1.0"))

# ── ChromaDB config ───────────────────────────────────────────────────
CHROMA_DIR = os.getenv("CHROMA_DIR", "storage/chroma")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "kursmaterial_v1")
DEBUG_RAG = os.getenv("DEBUG_RAG", "0").lower() in ("1", "true", "yes")

# ── Singleton clients ─────────────────────────────────────────────────
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
chroma = chromadb.PersistentClient(path=CHROMA_DIR, settings=Settings(anonymized_telemetry=False))
col = chroma.get_or_create_collection(name=COLLECTION_NAME)
