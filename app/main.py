import os
from typing import List, Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from pydantic import BaseModel

from app.database import (
    init_db,
    get_messages,
    get_conversations_by_guest,
    conversation_belongs_to_guest,
)
from app.migrations import run_migrations
from app.clients import MODEL, TOP_K, LAST_N, SUMMARY_THRESHOLD
from app.chat_service import handle_chat
from app.image_handler import save_image, ImageValidationError
from app.feedback_service import export_feedback
from trennkost.analyzer import analyze_text as trennkost_analyze_text, format_results_for_llm

load_dotenv()

# Initialize database on startup
init_db()
run_migrations()

app = FastAPI(title="Lebensessenz Kursbot Chat")

origins = [
    "http://localhost:4321",  # Astro dev
    "https://lebensessenz.de",  # future production
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Invalid request payload",
                "details": exc.errors(),
            }
        },
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    code_map = {
        400: "BAD_REQUEST",
        403: "ACCESS_DENIED",
        404: "NOT_FOUND",
    }
    error_code = code_map.get(exc.status_code, "HTTP_ERROR")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": error_code,
                "message": exc.detail,
            }
        },
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
            }
        },
    )

# Mount uploads directory for serving images
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "storage/uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

class ChatRequest(BaseModel):
    conversationId: Optional[str] = None
    message: str
    guestId: Optional[str] = None
    userId: Optional[str] = None    # reserved for future auth; not passed to handle_chat
    courseId: Optional[str] = None  # reserved for future multi-course support

class ChatResponse(BaseModel):
    conversationId: str
    answer: str
    sources: list

class HealthResponse(BaseModel):
    ok: bool

class ConversationItem(BaseModel):
    id: str
    title: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    guest_id: Optional[str] = None

class ConversationsResponse(BaseModel):
    conversations: List[ConversationItem]

class RagConfig(BaseModel):
    top_k: int
    max_history_messages: int
    summary_threshold: Optional[int] = None

class FeaturesConfig(BaseModel):
    vision_enabled: bool
    feedback_enabled: bool

class ConfigResponse(BaseModel):
    model: str
    rag: RagConfig
    features: FeaturesConfig

@app.get("/health", response_model=HealthResponse)
@app.get("/api/v1/health", response_model=HealthResponse)
def health():
    return {"ok": True}

@app.get("/config", response_model=ConfigResponse)
@app.get("/api/v1/config", response_model=ConfigResponse)
def get_config():
    return ConfigResponse(
        model=MODEL,
        rag=RagConfig(
            top_k=TOP_K,
            max_history_messages=LAST_N,
            summary_threshold=SUMMARY_THRESHOLD,
        ),
        features=FeaturesConfig(
            vision_enabled=True,
            feedback_enabled=True,
        ),
    )

@app.post("/chat", response_model=ChatResponse)
@app.post("/api/v1/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    """
    Main chat endpoint with rolling summary (JSON-based).

    Flow:
    - If conversationId is missing, creates new conversation
    - Saves user message
    - Retrieves course snippets using summary + last N messages
    - Generates response grounded in course material
    - Updates rolling summary if threshold reached
    """
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    try:
        result = handle_chat(request.conversationId, message, request.guestId)
        return ChatResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")

@app.post("/chat/image", response_model=ChatResponse)
@app.post("/api/v1/chat/image", response_model=ChatResponse)
async def chat_with_image(
    message: str = Form(...),
    conversationId: Optional[str] = Form(None),
    guestId: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None)
):
    """
    Chat endpoint with optional image upload for meal analysis.

    Supports multipart/form-data with:
    - message: User question/message (required)
    - conversationId: Existing conversation ID (optional)
    - guestId: Guest identifier (optional)
    - image: Image file (JPG, PNG, HEIC, WebP) (optional)

    If image is provided:
    - Uses GPT-4 Vision to analyze meal
    - Categorizes food groups
    - Generates Trennkost-based evaluation
    """
    message = message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    image_path = None
    if image:
        try:
            # Read and validate image
            file_content = await image.read()
            image_path = save_image(file_content, image.filename)
        except ImageValidationError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Image processing error: {str(e)}")

    try:
        result = handle_chat(conversationId, message, guestId, image_path)
        return ChatResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")

class AnalyzeRequest(BaseModel):
    text: str
    mode: str = "strict"  # "strict" or "assumption"

@app.post("/analyze")
@app.post("/api/v1/analyze")
def analyze_food(request: AnalyzeRequest):
    """
    Standalone Trennkost analysis endpoint (no chat context needed).

    POST /analyze {"text": "Reis, Hähnchen, Brokkoli"}
    Returns deterministic engine verdict + formatted explanation.
    """
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    try:
        results = trennkost_analyze_text(text, mode=request.mode)
        return {
            "results": [
                {
                    "dish_name": r.dish_name,
                    "verdict": r.verdict.value,
                    "summary": r.summary,
                    "groups": dict(r.groups_found),
                    "problems": [
                        {"rule_id": p.rule_id, "description": p.description, "explanation": p.explanation}
                        for p in r.problems
                    ],
                    "questions": [q.question for q in r.required_questions],
                    "ok_combinations": r.ok_combinations,
                }
                for r in results
            ],
            "formatted": format_results_for_llm(results),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis error: {str(e)}")

@app.get("/conversations", response_model=ConversationsResponse)
@app.get("/api/v1/conversations", response_model=ConversationsResponse)
def get_conversations(guest_id: Optional[str] = None):
    """
    Get all conversations for a guest.
    Returns empty list if no guest_id provided (backwards compat).
    """
    if not guest_id:
        return {"conversations": []}

    try:
        conversations = get_conversations_by_guest(guest_id)
        return {"conversations": conversations}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/conversations/{conversation_id}/messages")
@app.get("/api/v1/conversations/{conversation_id}/messages")
def get_conversation_messages(conversation_id: str, guest_id: Optional[str] = None):
    """
    Get all messages for a conversation.
    Validates guest access if guest_id provided.
    """
    try:
        # Validate guest access
        if guest_id and not conversation_belongs_to_guest(conversation_id, guest_id):
            raise HTTPException(status_code=403, detail="Access denied")

        messages = get_messages(conversation_id)
        return {"messages": messages}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/conversations/{conversation_id}")
@app.delete("/api/v1/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, guest_id: Optional[str] = None):
    """
    Delete a conversation.
    Validates guest ownership before deletion.
    """
    try:
        # Validate guest access
        if guest_id and not conversation_belongs_to_guest(conversation_id, guest_id):
            raise HTTPException(status_code=403, detail="Access denied")

        from app.database import delete_conversation
        delete_conversation(conversation_id)
        return {"status": "deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class FeedbackRequest(BaseModel):
    conversationId: str
    feedback: str
    guestId: Optional[str] = None

FEEDBACK_DIR = os.getenv("FEEDBACK_DIR", "storage/feedback")

@app.post("/feedback")
@app.post("/api/v1/feedback")
def submit_feedback(request: FeedbackRequest):
    """
    Save feedback for a conversation.

    Exports the full chat as readable Markdown + copies images + saves feedback text
    to storage/feedback/{timestamp}_{sanitized_title}/.
    """
    if not request.feedback.strip():
        raise HTTPException(status_code=400, detail="Feedback cannot be empty")

    if request.guestId and not conversation_belongs_to_guest(request.conversationId, request.guestId):
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        result = export_feedback(request.conversationId, request.feedback.strip(), FEEDBACK_DIR)
        return {"status": "saved", **result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/", response_class=HTMLResponse)
def home():
    # Read frontend HTML from file
    import pathlib
    html_path = pathlib.Path(__file__).parent / "main_frontend.html"
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    # Add no-cache headers to force browser reload
    return HTMLResponse(
        html_content,
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )

@app.get("/old", response_class=HTMLResponse)
def old_ui():
    """Old single-conversation UI for reference."""
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
      height: 85vh;
      display: flex;
      flex-direction: column;
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
      padding: 24px 32px;
      border-bottom: 1px solid #e5e5e5;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .header-left h1 {
      font-size: 1.5rem;
      color: #1a1a1a;
      font-weight: 500;
      letter-spacing: -0.5px;
    }

    .header-left .subtitle {
      color: #666;
      font-size: 0.875rem;
      margin-top: 4px;
    }

    .new-chat-btn {
      padding: 10px 20px;
      background: #e8dfd8;
      color: #666;
      border: none;
      border-radius: 999px;
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.3s ease;
    }

    .new-chat-btn:hover {
      background: #ddd3cc;
    }

    .chat-history {
      flex: 1;
      overflow-y: auto;
      padding: 24px 32px;
    }

    .message {
      margin-bottom: 24px;
      animation: fadeIn 0.3s ease-out;
    }

    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(10px); }
      to { opacity: 1; transform: translateY(0); }
    }

    .message-role {
      font-weight: 600;
      margin-bottom: 8px;
      color: #c9a897;
      font-size: 0.875rem;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .message.assistant .message-role {
      color: #1a1a1a;
    }

    .message-content {
      color: #1a1a1a;
      line-height: 1.8;
      white-space: pre-wrap;
      word-wrap: break-word;
    }

    .message.assistant .message-content {
      background: #f5f1ed;
      padding: 16px 20px;
      border-radius: 12px;
    }

    .message-content strong {
      font-weight: 600;
    }

    .message-content h1,
    .message-content h2,
    .message-content h3 {
      margin: 16px 0 8px 0;
      line-height: 1.4;
    }

    .message-content h1 { font-size: 1.5rem; font-weight: 600; }
    .message-content h2 { font-size: 1.25rem; font-weight: 600; }
    .message-content h3 { font-size: 1.125rem; font-weight: 600; }

    .sources {
      margin-top: 16px;
      padding-top: 16px;
      border-top: 1px solid #e0d7d0;
    }

    .sources-title {
      font-weight: 500;
      color: #666;
      margin-bottom: 8px;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    .source-tag {
      display: inline-block;
      background: white;
      padding: 6px 12px;
      border-radius: 16px;
      margin: 4px 4px 4px 0;
      font-size: 12px;
      color: #c9a897;
      border: 1px solid #e5e5e5;
      font-weight: 500;
    }

    .input-container {
      padding: 20px 32px;
      border-top: 1px solid #e5e5e5;
      background: #fafafa;
      border-radius: 0 0 16px 16px;
    }

    .input-group {
      display: flex;
      gap: 12px;
      align-items: flex-end;
    }

    textarea {
      flex: 1;
      min-height: 56px;
      max-height: 120px;
      padding: 16px;
      border: 1px solid #e5e5e5;
      border-radius: 12px;
      font-family: inherit;
      font-size: 15px;
      resize: none;
      transition: all 0.3s ease;
      background: white;
      color: #1a1a1a;
    }

    textarea:focus {
      outline: none;
      border-color: #c9a897;
      box-shadow: 0 0 0 3px rgba(201, 168, 151, 0.1);
    }

    textarea::placeholder {
      color: #999;
    }

    .send-btn {
      padding: 16px 28px;
      background: #c9a897;
      color: white;
      border: none;
      border-radius: 12px;
      font-size: 15px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.3s ease;
      white-space: nowrap;
    }

    .send-btn:hover:not(:disabled) {
      background: #b89786;
      transform: translateY(-1px);
    }

    .send-btn:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }

    .loading {
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .spinner {
      width: 16px;
      height: 16px;
      border: 2px solid #f0ebe7;
      border-top: 2px solid #c9a897;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }

    @keyframes spin {
      0% { transform: rotate(0deg); }
      100% { transform: rotate(360deg); }
    }

    .empty-state {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      height: 100%;
      color: #999;
      text-align: center;
      padding: 40px;
    }

    .empty-state-icon {
      font-size: 3rem;
      margin-bottom: 16px;
    }

    .empty-state-text {
      font-size: 1.125rem;
      margin-bottom: 8px;
    }

    .empty-state-subtext {
      font-size: 0.875rem;
    }

    @media (max-width: 600px) {
      .container {
        height: 90vh;
      }

      .header, .chat-history, .input-container {
        padding-left: 20px;
        padding-right: 20px;
      }

      .header {
        flex-direction: column;
        gap: 12px;
        align-items: flex-start;
      }
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="header-left">
        <h1>Lebensessenz Kursbot</h1>
        <p class="subtitle">Stelle deine Fragen zum Kursmaterial</p>
      </div>
      <button class="new-chat-btn" onclick="newChat()">Neuer Chat</button>
    </div>

    <div class="chat-history" id="chatHistory">
      <div class="empty-state">
        <div class="empty-state-icon">💬</div>
        <div class="empty-state-text">Starte eine Konversation</div>
        <div class="empty-state-subtext">Stelle eine Frage zum Kursmaterial</div>
      </div>
    </div>

    <div class="input-container">
      <div class="input-group">
        <textarea
          id="messageInput"
          placeholder="Stelle eine Frage..."
          onkeydown="if(event.key==='Enter' && !event.shiftKey) { event.preventDefault(); sendMessage(); }"
        ></textarea>
        <button class="send-btn" id="sendBtn" onclick="sendMessage()">
          <span id="sendBtnText">Senden</span>
        </button>
      </div>
    </div>
  </div>

<script>
let conversationId = localStorage.getItem('conversationId');
let messages = [];

function formatSource(path) {
  const parts = path.split('/');
  let result = '';

  if (parts[0] && parts[0].startsWith('modul-')) {
    const modulNum = parts[0].match(/modul-(\\d+)/);
    if (modulNum) {
      result = `Modul ${modulNum[1]}`;
    }
  }

  if (parts[1]) {
    const pageMatch = parts[1].match(/page-(\\d+)/);
    if (pageMatch) {
      const pageNum = parseInt(pageMatch[1], 10);
      result += ` - Seite ${pageNum}`;
    }
  }

  return result || path;
}

function formatMarkdown(text) {
  let html = text;
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  html = html.replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>');
  return html;
}

function renderMessage(role, content, sources = null) {
  const chatHistory = document.getElementById('chatHistory');
  const emptyState = chatHistory.querySelector('.empty-state');
  if (emptyState) {
    emptyState.remove();
  }

  const messageDiv = document.createElement('div');
  messageDiv.className = `message ${role}`;

  const roleLabel = role === 'user' ? 'Du' : 'Kursbot';
  const formattedContent = role === 'assistant' ? formatMarkdown(content) : content;

  let html = `
    <div class="message-role">${roleLabel}</div>
    <div class="message-content">${formattedContent}</div>
  `;

  if (sources && sources.length > 0) {
    const sourceTags = sources
      .map(s => `<span class="source-tag">${formatSource(s.path)}</span>`)
      .join('');
    html += `
      <div class="sources">
        <div class="sources-title">Quellen</div>
        ${sourceTags}
      </div>
    `;
  }

  messageDiv.innerHTML = html;
  chatHistory.appendChild(messageDiv);
  chatHistory.scrollTop = chatHistory.scrollHeight;
}

async function loadHistory() {
  if (!conversationId) return;

  try {
    const response = await fetch(`/conversations/${conversationId}/messages`);
    const data = await response.json();
    messages = data.messages;

    const chatHistory = document.getElementById('chatHistory');
    chatHistory.innerHTML = '';

    for (const msg of messages) {
      renderMessage(msg.role, msg.content);
    }
  } catch (error) {
    console.error('Failed to load history:', error);
  }
}

async function sendMessage() {
  const input = document.getElementById('messageInput');
  const message = input.value.trim();

  if (!message) return;

  const sendBtn = document.getElementById('sendBtn');
  const sendBtnText = document.getElementById('sendBtnText');

  // Disable input
  input.disabled = true;
  sendBtn.disabled = true;
  sendBtnText.innerHTML = '<div class="loading"><div class="spinner"></div><span>Denke...</span></div>';

  // Render user message immediately
  renderMessage('user', message);
  input.value = '';

  try {
    const response = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        conversationId: conversationId,
        message: message
      })
    });

    const data = await response.json();

    // Save conversation ID
    if (!conversationId) {
      conversationId = data.conversationId;
      localStorage.setItem('conversationId', conversationId);
    }

    // Render assistant message
    renderMessage('assistant', data.answer, data.sources);

  } catch (error) {
    console.error('Error:', error);
    renderMessage('assistant', 'Fehler beim Abrufen der Antwort. Bitte versuche es erneut.');
  } finally {
    input.disabled = false;
    sendBtn.disabled = false;
    sendBtnText.textContent = 'Senden';
    input.focus();
  }
}

function newChat() {
  if (confirm('Möchtest du einen neuen Chat starten? Der aktuelle Chat bleibt gespeichert.')) {
    conversationId = null;
    localStorage.removeItem('conversationId');
    messages = [];

    const chatHistory = document.getElementById('chatHistory');
    chatHistory.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">💬</div>
        <div class="empty-state-text">Starte eine Konversation</div>
        <div class="empty-state-subtext">Stelle eine Frage zum Kursmaterial</div>
      </div>
    `;

    document.getElementById('messageInput').focus();
  }
}

// Load history on page load
window.addEventListener('DOMContentLoaded', () => {
  loadHistory();
  document.getElementById('messageInput').focus();
});
</script>
</body>
</html>
""")
