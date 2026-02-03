"""
Database migrations for guest_id support.
"""
import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.getenv("DB_PATH", "storage/chat.db")

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

def run_migrations():
    """Run all database migrations."""
    print("🔄 Running database migrations...")

    with get_db() as conn:
        cursor = conn.cursor()

        # Check if guest_id column exists
        cursor.execute("PRAGMA table_info(conversations)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'guest_id' not in columns:
            print("  ✓ Adding guest_id column to conversations table...")
            cursor.execute("""
                ALTER TABLE conversations
                ADD COLUMN guest_id TEXT
            """)

        if 'title' not in columns:
            print("  ✓ Adding title column to conversations table...")
            cursor.execute("""
                ALTER TABLE conversations
                ADD COLUMN title TEXT
            """)

        # Create index for guest_id
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_conversations_guest_id
            ON conversations(guest_id, updated_at DESC)
        """)

        # Check if image_path column exists in messages table
        cursor.execute("PRAGMA table_info(messages)")
        message_columns = [row[1] for row in cursor.fetchall()]

        if 'image_path' not in message_columns:
            print("  ✓ Adding image_path column to messages table...")
            cursor.execute("""
                ALTER TABLE messages
                ADD COLUMN image_path TEXT
            """)

        print("✅ Migrations completed successfully!")

if __name__ == "__main__":
    run_migrations()
