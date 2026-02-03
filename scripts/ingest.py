import os
import argparse
from pathlib import Path
from typing import Dict, Any, Tuple, List

import yaml
from dotenv import load_dotenv
import chromadb
from chromadb.config import Settings
from openai import OpenAI

load_dotenv()

PAGES_DIR = Path("content/pages")

CHROMA_DIR = os.getenv("CHROMA_DIR", "storage/chroma")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "kursmaterial_v1")
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1200"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def parse_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """
    Erwartetes Format:
    ---
    key: value
    ---
    body...
    """
    t = text.lstrip()
    if not t.startswith("---"):
        return {}, text

    lines = t.splitlines()
    if len(lines) < 3:
        return {}, text

    if lines[0].strip() != "---":
        return {}, text

    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return {}, text

    fm_text = "\n".join(lines[1:end_idx]).strip()
    body = "\n".join(lines[end_idx + 1 :]).lstrip()

    try:
        meta = yaml.safe_load(fm_text) or {}
        if not isinstance(meta, dict):
            meta = {}
    except Exception:
        meta = {}
        body = text  # Fallback: komplett als Body

    return meta, body


def split_blocks(md: str) -> List[str]:
    md = md.replace("\r\n", "\n")
    blocks: List[str] = []
    buf: List[str] = []

    for line in md.split("\n"):
        if line.strip() == "":
            if buf:
                blocks.append("\n".join(buf).strip())
                buf = []
            continue
        buf.append(line)

    if buf:
        blocks.append("\n".join(buf).strip())

    return [b for b in blocks if b.strip()]


def chunk_blocks(blocks: List[str], chunk_size: int, overlap_chars: int) -> List[str]:
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0

    def flush():
        nonlocal current, current_len
        if not current:
            return
        text = "\n\n".join(current).strip()
        chunks.append(text)

        # Overlap: tail-Blöcke behalten, bis overlap_chars erreicht
        tail: List[str] = []
        tail_len = 0
        for b in reversed(current):
            bl = len(b) + 2
            if tail_len + bl > overlap_chars:
                break
            tail.insert(0, b)
            tail_len += bl

        current = tail
        current_len = sum(len(b) + 2 for b in current)

    for b in blocks:
        bl = len(b) + 2
        if current_len + bl > chunk_size and current:
            flush()
        current.append(b)
        current_len += bl

    flush()
    return chunks


def embed_batch(texts: List[str]) -> List[List[float]]:
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [d.embedding for d in resp.data]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="Delete & recreate collection")
    args = ap.parse_args()

    if not PAGES_DIR.exists():
        raise SystemExit("content/pages existiert nicht. Lege Dateien dort ab.")

    files = sorted(
        [
            p
            for p in PAGES_DIR.glob("**/*")
            if p.is_file() and p.suffix.lower() in [".md", ".txt"]
        ]
    )
    if not files:
        raise SystemExit("Keine Dateien in content/pages gefunden (.md/.txt).")

    Path(CHROMA_DIR).mkdir(parents=True, exist_ok=True)
    chroma = chromadb.PersistentClient(
        path=CHROMA_DIR, settings=Settings(anonymized_telemetry=False)
    )

    if args.reset:
        try:
            chroma.delete_collection(COLLECTION_NAME)
        except Exception:
            pass

    col = chroma.get_or_create_collection(name=COLLECTION_NAME)

    ids: List[str] = []
    docs: List[str] = []
    metas: List[Dict[str, Any]] = []

    for fp in files:
        raw = fp.read_text(encoding="utf-8", errors="ignore")
        meta, body = parse_frontmatter(raw)

        blocks = split_blocks(body)
        chunks = chunk_blocks(blocks, CHUNK_SIZE, CHUNK_OVERLAP)

        rel = fp.relative_to(PAGES_DIR).as_posix()

        # tags IMMER zu einem String machen (wegen Chroma)
        tags_val = meta.get("tags", [])
        if isinstance(tags_val, list):
            tags_val = ", ".join(str(t) for t in tags_val)
        elif tags_val is None:
            tags_val = str("")

        base_meta = {
            "path": rel,
            "source": meta.get("source", rel),
            "page": meta.get("page", None),
            "type": meta.get("type", None),
            "section": meta.get("section", None),
            "tags": tags_val,
        }

        for i, ch in enumerate(chunks):
            ids.append(f"{rel}::chunk_{i}")
            docs.append(ch)
            m = dict(base_meta)
            m["chunk"] = i
            metas.append(m)

    # ggf. existierende gleiche IDs löschen
    try:
        col.delete(ids=ids)
    except Exception:
        pass

    BATCH = 64
    for i in range(0, len(docs), BATCH):
        batch_docs = docs[i : i + BATCH]
        batch_ids = ids[i : i + BATCH]
        batch_metas = metas[i : i + BATCH]
        vecs = embed_batch(batch_docs)
        import json
        def _sanitize_chroma_metadata(_m):
            _out = {}
            for _k, _v in _m.items():
                if _v is None:
                    continue
                if isinstance(_v, (list, tuple, set)):
                    _out[_k] = ", ".join(str(x) for x in _v)
                elif isinstance(_v, dict):
                    _out[_k] = json.dumps(_v, ensure_ascii=False)
                else:
                    _out[_k] = _v
            return _out
        batch_metas = [_sanitize_chroma_metadata(_m) for _m in batch_metas]


        def _normalize_source_to_mdpath(_m):

            # Ziel: source soll immer der relative MD-Pfad sein (für Debugging/Quellenanzeige)

            # ingest setzt typischerweise zusätzlich eine "path"/"file"/"id"-Info irgendwo; hier greifen wir auf source nur dann zu,

            # wenn es wie ein PDF-Name aussieht und wir einen md-Pfad im _m haben.

            _src = str(_m.get("source") or "")

            if _src.lower().endswith(".pdf"):

                for k in ("md_path","path","file_path","file","id"):

                    v = _m.get(k)

                    if v and str(v).endswith(".md"):

                        _m["origin_pdf"] = _src

                        _m["source"] = str(v)

                        break

            return _m


        def _fill_page_from_source(_m):
            import re as _re
            if "page" not in _m:
                _src = str(_m.get("source") or "")
                _mo = _re.search(r"page-(\d+)\.md", _src)
                if _mo:
                    _m["page"] = int(_mo.group(1))
            return _m

        batch_metas = [_fill_page_from_source(_m) for _m in batch_metas]


        batch_metas = [_normalize_source_to_mdpath(_m) for _m in batch_metas]

        col.add(
            ids=batch_ids,
            documents=batch_docs,
            metadatas=batch_metas,
            embeddings=vecs,
        )

    print(
        f"OK: {len(docs)} Chunks indexiert in '{COLLECTION_NAME}' ({CHROMA_DIR})."
    )


if __name__ == "__main__":
    main()
