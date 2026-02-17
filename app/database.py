import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
import os

DB_PATH = os.getenv("DB_PATH", "storage/chat.db")

def init_db():
    """Initialize database schema."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Conversations table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            summary_text TEXT,
            summary_updated_at TEXT,
            summary_message_cursor INTEGER DEFAULT 0
        )
    """)

    # Messages table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )
    """)

    # Indexes
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_messages_conversation
        ON messages(conversation_id, created_at)
    """)

    conn.commit()
    conn.close()

@contextmanager
def get_db():
    """Context manager for database connections."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def create_conversation(guest_id: Optional[str] = None, title: Optional[str] = None) -> str:
    """Create a new conversation and return its ID."""
    import uuid
    conversation_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    with get_db() as conn:
        conn.execute("""
            INSERT INTO conversations (id, created_at, updated_at, guest_id, title)
            VALUES (?, ?, ?, ?, ?)
        """, (conversation_id, now, now, guest_id, title))

    return conversation_id

def get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    """Get conversation by ID."""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT * FROM conversations WHERE id = ?
        """, (conversation_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def update_conversation_timestamp(conversation_id: str):
    """Update conversation's updated_at timestamp."""
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        conn.execute("""
            UPDATE conversations SET updated_at = ? WHERE id = ?
        """, (now, conversation_id))

def create_message(conversation_id: str, role: str, content: str, image_path: Optional[str] = None) -> str:
    """Create a new message and return its ID."""
    import uuid
    message_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    with get_db() as conn:
        conn.execute("""
            INSERT INTO messages (id, conversation_id, role, content, created_at, image_path)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (message_id, conversation_id, role, content, now, image_path))

    update_conversation_timestamp(conversation_id)
    return message_id

def get_messages(conversation_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Get messages for a conversation, ordered by created_at."""
    with get_db() as conn:
        query = """
            SELECT * FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC
        """
        if limit:
            query += f" LIMIT {limit}"

        cursor = conn.execute(query, (conversation_id,))
        return [dict(row) for row in cursor.fetchall()]

def get_last_n_messages(conversation_id: str, n: int = 8) -> List[Dict[str, Any]]:
    """Get last N messages for a conversation."""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT * FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (conversation_id, n))
        messages = [dict(row) for row in cursor.fetchall()]
        return list(reversed(messages))  # Return in chronological order

def count_messages_since_cursor(conversation_id: str, cursor_position: int) -> int:
    """Count messages since the summary cursor."""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT COUNT(*) as count FROM (
                SELECT ROW_NUMBER() OVER (ORDER BY created_at) as rn
                FROM messages
                WHERE conversation_id = ?
            ) WHERE rn > ?
        """, (conversation_id, cursor_position))
        return cursor.fetchone()["count"]

def get_messages_since_cursor(conversation_id: str, cursor_position: int) -> List[Dict[str, Any]]:
    """Get messages since the summary cursor."""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT m.* FROM messages m
            INNER JOIN (
                SELECT id, ROW_NUMBER() OVER (ORDER BY created_at) as rn
                FROM messages
                WHERE conversation_id = ?
            ) numbered ON m.id = numbered.id
            WHERE numbered.rn > ?
            ORDER BY m.created_at ASC
        """, (conversation_id, cursor_position))
        return [dict(row) for row in cursor.fetchall()]

def update_summary(conversation_id: str, summary_text: str, new_cursor: int):
    """Update conversation summary and cursor position."""
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        conn.execute("""
            UPDATE conversations
            SET summary_text = ?,
                summary_updated_at = ?,
                summary_message_cursor = ?
            WHERE id = ?
        """, (summary_text, now, new_cursor, conversation_id))

def get_total_message_count(conversation_id: str) -> int:
    """Get total message count for a conversation."""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT COUNT(*) as count FROM messages WHERE conversation_id = ?
        """, (conversation_id,))
        return cursor.fetchone()["count"]

def get_conversations_by_guest(guest_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Get all conversations for a guest, sorted by updated_at desc."""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT id, title, created_at, updated_at, guest_id
            FROM conversations
            WHERE guest_id = ?
            ORDER BY updated_at DESC
            LIMIT ?
        """, (guest_id, limit))
        return [dict(row) for row in cursor.fetchall()]

def get_all_conversations_without_guest(limit: int = 100) -> List[Dict[str, Any]]:
    """Get conversations without guest_id (for migration)."""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT id, title, created_at, updated_at, guest_id
            FROM conversations
            WHERE guest_id IS NULL
            ORDER BY updated_at DESC
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]

def update_conversation_guest_id(conversation_id: str, guest_id: str):
    """Update guest_id for a conversation (migration)."""
    with get_db() as conn:
        conn.execute("""
            UPDATE conversations SET guest_id = ? WHERE id = ?
        """, (guest_id, conversation_id))

def update_conversation_title(conversation_id: str, title: str):
    """Update conversation title."""
    with get_db() as conn:
        conn.execute("""
            UPDATE conversations SET title = ? WHERE id = ?
        """, (title, conversation_id))

def generate_title_from_message(message: str, max_words: int = 10) -> str:
    """Generate a title from the first user message."""
    words = message.strip().split()
    if len(words) <= max_words:
        return message.strip()
    return ' '.join(words[:max_words]) + '...'

def conversation_belongs_to_guest(conversation_id: str, guest_id: Optional[str]) -> bool:
    """Check if conversation belongs to guest (or has no guest_id for backwards compat)."""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT guest_id FROM conversations WHERE id = ?
        """, (conversation_id,))
        row = cursor.fetchone()
        if not row:
            return False

        conv_guest_id = row["guest_id"]

        # Backwards compatibility: if conversation has no guest_id, allow access
        if conv_guest_id is None:
            return True

        # Otherwise, check if guest_id matches
        return conv_guest_id == guest_id

def export_conversation_for_feedback(conversation_id: str) -> Optional[Dict[str, Any]]:
    """Export full conversation data for feedback saving."""
    with get_db() as conn:
        cursor = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
        conv = cursor.fetchone()
        if not conv:
            return None

        cursor = conn.execute("""
            SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC
        """, (conversation_id,))
        messages = [dict(row) for row in cursor.fetchall()]

        return {
            "conversation": dict(conv),
            "messages": messages,
        }


def delete_conversation(conversation_id: str):
    """Delete a conversation and all its messages."""
    with get_db() as conn:
        # Delete messages first (foreign key constraint)
        conn.execute("""
            DELETE FROM messages WHERE conversation_id = ?
        """, (conversation_id,))

        # Delete conversation
        conn.execute("""
            DELETE FROM conversations WHERE id = ?
        """, (conversation_id,))
