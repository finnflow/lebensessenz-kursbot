import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import chromadb
from chromadb.config import Settings
from openai import OpenAI

load_dotenv()

CHROMA_DIR = os.getenv("CHROMA_DIR", "storage/chroma")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "kursmaterial_v1")

MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

TOP_K = int(os.getenv("TOP_K", "6"))
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "9000"))

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

chroma = chromadb.PersistentClient(path=CHROMA_DIR, settings=Settings(anonymized_telemetry=False))
col = chroma.get_or_create_collection(name=COLLECTION_NAME)

app = FastAPI(title="Lebensessenz Kursbot")

class AskIn(BaseModel):
    question: str

SYSTEM_INSTRUCTIONS = """Du bist ein kurs-assistierender Bot.
Regeln:
- Antworte ausschließlich mit Wissen aus dem bereitgestellten KONTEXT.
- Wenn der Kontext nicht reicht: sag klar, dass es im Material nicht steht, und frage nach Präzisierung.
- Gib keine medizinische Diagnose oder Behandlungsanweisung.
- Nenne KEINE Quellen im Text. Die Quellen werden automatisch unten angezeigt.
"""

def embed_one(text: str):
    resp = client.embeddings.create(model=EMBED_MODEL, input=[text])
    return resp.data[0].embedding

def build_context(docs, metas):
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

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/ask")
def ask(inp: AskIn):
    q = (inp.question or "").strip()
    if not q:
        return {"answer": "Bitte eine Frage eingeben.", "sources": []}

    qvec = embed_one(q)
    res = col.query(
        query_embeddings=[qvec],
        n_results=TOP_K,
        include=["documents", "metadatas", "distances"],
    )

    docs = res.get("documents", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    dists = res.get("distances", [[]])[0]

    context = build_context(docs, metas)

    user_input = f"""KONTEXT:
{context}

FRAGE:
{q}

ANTWORT (deutsch, kurz, präzise, materialgebunden):"""

    response = client.responses.create(
        model=MODEL,
        instructions=SYSTEM_INSTRUCTIONS,
        input=user_input,
        temperature=0.2,
    )

    sources = []
    for m, d in zip(metas, dists):
        sources.append({
            "path": m.get("path"),
            "source": m.get("source"),
            "page": m.get("page"),
            "chunk": m.get("chunk"),
            "distance": d
        })

    return {"answer": response.output_text.strip(), "sources": sources}

@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse("""
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Lebensessenz Kursbot</title>
  <style>
    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
    }

    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      background: #f5f1ed;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
      line-height: 1.6;
    }

    .container {
      background: white;
      border-radius: 16px;
      box-shadow: 0 2px 20px rgba(0, 0, 0, 0.08);
      max-width: 900px;
      width: 100%;
      padding: 48px;
      animation: slideUp 0.5s ease-out;
    }

    @keyframes slideUp {
      from {
        opacity: 0;
        transform: translateY(30px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    .header {
      text-align: center;
      margin-bottom: 48px;
    }

    h1 {
      font-size: 2.5rem;
      color: #1a1a1a;
      margin-bottom: 12px;
      font-weight: 500;
      letter-spacing: -0.5px;
    }

    .subtitle {
      color: #666;
      font-size: 1.125rem;
      font-weight: 400;
    }

    .chat-container {
      margin-bottom: 32px;
    }

    .input-group {
      position: relative;
      margin-bottom: 20px;
    }

    textarea {
      width: 100%;
      min-height: 140px;
      padding: 20px;
      border: 1px solid #e5e5e5;
      border-radius: 12px;
      font-family: inherit;
      font-size: 16px;
      resize: vertical;
      transition: all 0.3s ease;
      background: #fafafa;
      color: #1a1a1a;
    }

    textarea:focus {
      outline: none;
      border-color: #c9a897;
      background: white;
      box-shadow: 0 0 0 3px rgba(201, 168, 151, 0.1);
    }

    textarea::placeholder {
      color: #999;
    }

    .button-group {
      display: flex;
      gap: 12px;
      margin-bottom: 32px;
    }

    button {
      flex: 1;
      padding: 18px 32px;
      background: #c9a897;
      color: white;
      border: none;
      border-radius: 999px;
      font-size: 16px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.3s ease;
      box-shadow: 0 2px 8px rgba(201, 168, 151, 0.3);
    }

    button:hover {
      background: #b89786;
      transform: translateY(-1px);
      box-shadow: 0 4px 12px rgba(201, 168, 151, 0.4);
    }

    button:active {
      transform: translateY(0);
    }

    button:disabled {
      opacity: 0.6;
      cursor: not-allowed;
      transform: none;
    }

    .clear-btn {
      background: #e8dfd8;
      color: #666;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
    }

    .clear-btn:hover {
      background: #ddd3cc;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
    }

    .response-container {
      background: #f5f1ed;
      border-radius: 16px;
      padding: 32px;
      min-height: 200px;
      display: none;
    }

    .response-container.visible {
      display: block;
      animation: fadeIn 0.4s ease-out;
    }

    @keyframes fadeIn {
      from { opacity: 0; }
      to { opacity: 1; }
    }

    .response-header {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 20px;
      color: #1a1a1a;
      font-weight: 500;
      font-size: 1.125rem;
    }

    .response-text {
      color: #1a1a1a;
      line-height: 1.8;
      white-space: pre-wrap;
      word-wrap: break-word;
      font-size: 16px;
      font-weight: 400;
    }

    .response-text strong {
      font-weight: 600;
      color: #1a1a1a;
    }

    .response-text h1,
    .response-text h2,
    .response-text h3 {
      margin: 24px 0 12px 0;
      line-height: 1.4;
      color: #1a1a1a;
    }

    .response-text h1 {
      font-size: 1.5rem;
      font-weight: 600;
    }

    .response-text h2 {
      font-size: 1.25rem;
      font-weight: 600;
    }

    .response-text h3 {
      font-size: 1.125rem;
      font-weight: 600;
    }

    .response-text h1:first-child,
    .response-text h2:first-child,
    .response-text h3:first-child {
      margin-top: 0;
    }

    .sources {
      margin-top: 24px;
      padding-top: 24px;
      border-top: 1px solid #e0d7d0;
    }

    .sources-title {
      font-weight: 500;
      color: #666;
      margin-bottom: 12px;
      font-size: 14px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .source-tag {
      display: inline-block;
      background: white;
      padding: 8px 14px;
      border-radius: 20px;
      margin: 4px;
      font-size: 13px;
      color: #c9a897;
      border: 1px solid #e5e5e5;
      font-weight: 500;
    }

    .loading {
      display: flex;
      align-items: center;
      gap: 12px;
      color: #666;
    }

    .spinner {
      width: 20px;
      height: 20px;
      border: 2px solid #f0ebe7;
      border-top: 2px solid #c9a897;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }

    @keyframes spin {
      0% { transform: rotate(0deg); }
      100% { transform: rotate(360deg); }
    }

    .icon {
      width: 22px;
      height: 22px;
      color: #c9a897;
    }

    @media (max-width: 600px) {
      .container {
        padding: 28px;
      }

      h1 {
        font-size: 2rem;
      }

      .button-group {
        flex-direction: column;
      }
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Lebensessenz Kursbot</h1>
      <p class="subtitle">Stelle deine Fragen zum Kursmaterial</p>
    </div>

    <div class="chat-container">
      <div class="input-group">
        <textarea
          id="q"
          placeholder="Worum geht es grob? (Optional, aber hilfreich)"
          onkeydown="if(event.key==='Enter' && event.ctrlKey) ask()"
        ></textarea>
      </div>

      <div class="button-group">
        <button onclick="ask()" id="askBtn">
          <span id="btnText">Frage stellen</span>
        </button>
        <button class="clear-btn" onclick="clearAll()">
          Zurücksetzen
        </button>
      </div>
    </div>

    <div class="response-container" id="responseContainer">
      <div class="response-header">
        <svg class="icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"/>
        </svg>
        <span>Antwort</span>
      </div>
      <div class="response-text" id="a"></div>
      <div class="sources" id="sourcesContainer" style="display:none;">
        <div class="sources-title">Quellen</div>
        <div id="s"></div>
      </div>
    </div>
  </div>

<script>
function formatSource(path) {
  // Parse: "modul-1-optimale-lebensmittelkombinationen/page-007.md#0"
  // Output: "Modul 1 - Seite 7"

  const parts = path.split('/');
  let result = '';

  // Extract module name
  if (parts[0] && parts[0].startsWith('modul-')) {
    const modulNum = parts[0].match(/modul-(\d+)/);
    if (modulNum) {
      result = `Modul ${modulNum[1]}`;
    }
  }

  // Extract page number
  if (parts[1]) {
    const pageMatch = parts[1].match(/page-(\d+)/);
    if (pageMatch) {
      const pageNum = parseInt(pageMatch[1], 10);
      result += ` - Seite ${pageNum}`;
    }
  }

  return result || path;
}

function formatMarkdown(text) {
  // Convert Markdown to HTML
  let html = text;

  // Convert ### Heading to <h3>
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');

  // Convert ## Heading to <h2>
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');

  // Convert # Heading to <h1> (rare but for completeness)
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

  // Convert **bold** to <strong>
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

  return html;
}

async function ask() {
  const q = document.getElementById('q').value.trim();
  if (!q) {
    alert('Bitte gib eine Frage ein!');
    return;
  }

  const askBtn = document.getElementById('askBtn');
  const btnText = document.getElementById('btnText');
  const responseContainer = document.getElementById('responseContainer');
  const answerEl = document.getElementById('a');
  const sourcesContainer = document.getElementById('sourcesContainer');
  const sourcesEl = document.getElementById('s');

  // Show loading state
  askBtn.disabled = true;
  btnText.innerHTML = '<div class="loading"><div class="spinner"></div><span>Denke nach...</span></div>';
  responseContainer.classList.add('visible');
  answerEl.innerHTML = '<div class="loading"><div class="spinner"></div><span>Antwort wird generiert...</span></div>';
  sourcesContainer.style.display = 'none';

  try {
    const r = await fetch('/ask', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question: q})
    });

    const j = await r.json();
    const formattedAnswer = formatMarkdown(j.answer || "Keine Antwort erhalten.");
    answerEl.innerHTML = formattedAnswer;

    if (j.sources && j.sources.length) {
      sourcesContainer.style.display = 'block';
      sourcesEl.innerHTML = j.sources
        .map(x => `<span class="source-tag">${formatSource(x.path)}</span>`)
        .join('');
    }
  } catch (error) {
    answerEl.textContent = 'Fehler beim Abrufen der Antwort. Bitte versuche es erneut.';
    console.error('Error:', error);
  } finally {
    askBtn.disabled = false;
    btnText.textContent = 'Frage stellen';
  }
}

function clearAll() {
  document.getElementById('q').value = '';
  document.getElementById('responseContainer').classList.remove('visible');
  document.getElementById('a').textContent = '';
  document.getElementById('s').innerHTML = '';
  document.getElementById('sourcesContainer').style.display = 'none';
}
</script>
</body>
</html>
""")
