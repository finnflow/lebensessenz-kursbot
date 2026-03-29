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

        # Re-read columns after potential changes
        cursor.execute("PRAGMA table_info(messages)")
        message_columns = [row[1] for row in cursor.fetchall()]

        if 'intent' not in message_columns:
            print("  ✓ Adding intent column to messages table...")
            cursor.execute("""
                ALTER TABLE messages
                ADD COLUMN intent TEXT
            """)

        # Re-read conversations columns after potential changes
        cursor.execute("PRAGMA table_info(conversations)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'start_intent' not in columns:
            print("  ✓ Adding start_intent column to conversations table...")
            cursor.execute("""
                ALTER TABLE conversations
                ADD COLUMN start_intent TEXT
            """)

        # Re-read conversations columns after potential changes
        cursor.execute("PRAGMA table_info(conversations)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'active_menu_state_id' not in columns:
            print("  ✓ Adding active_menu_state_id column to conversations table...")
            cursor.execute("""
                ALTER TABLE conversations
                ADD COLUMN active_menu_state_id TEXT
            """)

        if 'active_menu_focus_dish_key' not in columns:
            print("  ✓ Adding active_menu_focus_dish_key column to conversations table...")
            cursor.execute("""
                ALTER TABLE conversations
                ADD COLUMN active_menu_focus_dish_key TEXT
            """)

        if 'active_menu_dish_matrix_json' not in columns:
            print("  ✓ Adding active_menu_dish_matrix_json column to conversations table...")
            cursor.execute("""
                ALTER TABLE conversations
                ADD COLUMN active_menu_dish_matrix_json TEXT
            """)

        if 'active_menu_dish_briefs_json' not in columns:
            print("  ✓ Adding active_menu_dish_briefs_json column to conversations table...")
            cursor.execute("""
                ALTER TABLE conversations
                ADD COLUMN active_menu_dish_briefs_json TEXT
            """)

        if 'active_menu_stage' not in columns:
            print("  ✓ Adding active_menu_stage column to conversations table...")
            cursor.execute("""
                ALTER TABLE conversations
                ADD COLUMN active_menu_stage TEXT
            """)

        cursor.execute("""
            UPDATE conversations
            SET active_menu_stage = 'recommendation_ready'
            WHERE active_menu_state_id IS NOT NULL
              AND (active_menu_stage IS NULL OR TRIM(active_menu_stage) = '')
        """)

        print("✅ Migrations completed successfully!")

if __name__ == "__main__":
    run_migrations()
