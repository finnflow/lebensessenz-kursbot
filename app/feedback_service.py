"""
Feedback export service.

Exports a full conversation as Markdown + copies images + writes metadata.
"""
import os
import re
import json
import shutil
from datetime import datetime
from typing import Dict, Any

from app.database import export_conversation_for_feedback


def export_feedback(
    conversation_id: str,
    feedback_text: str,
    feedback_dir: str,
) -> Dict[str, Any]:
    """
    Export a conversation as feedback to disk.

    Creates a folder: {feedback_dir}/{timestamp}_{slug}/
    Writes: chat.md, feedback.md, metadata.json, images/ (if any).

    Returns:
        {"folder": str, "message_count": int}

    Raises:
        ValueError: if conversation not found
    """
    data = export_conversation_for_feedback(conversation_id)
    if not data:
        raise ValueError("Conversation not found")

    conv = data["conversation"]
    messages = data["messages"]

    now = datetime.now()
    title = conv.get("title") or "Untitled"
    slug = re.sub(r"[^a-zA-Z0-9äöüÄÖÜß]+", "-", title).strip("-").lower()[:40]
    folder_name = f"{now.strftime('%Y-%m-%d_%H-%M')}_{slug}"
    folder_path = os.path.join(feedback_dir, folder_name)
    os.makedirs(folder_path, exist_ok=True)
    images_dir = os.path.join(folder_path, "images")

    # Build Markdown chat export
    md_lines = [f"# Chat: {title}\n"]
    md_lines.append(f"**Conversation ID:** `{conversation_id}`")
    md_lines.append(f"**Erstellt:** {conv.get('created_at', '?')}")
    md_lines.append(f"**Exportiert:** {now.isoformat()}\n")
    md_lines.append("---\n")

    for msg in messages:
        role_label = "Du" if msg["role"] == "user" else "Kursbot"
        md_lines.append(f"### {role_label}")
        md_lines.append(f"{msg['content']}\n")

        if msg.get("image_path"):
            src_path = msg["image_path"]
            if os.path.exists(src_path):
                os.makedirs(images_dir, exist_ok=True)
                filename = os.path.basename(src_path)
                dst_path = os.path.join(images_dir, filename)
                shutil.copy2(src_path, dst_path)
                md_lines.append(f"![Bild](images/{filename})\n")

        md_lines.append("")

    # Write chat.md
    with open(os.path.join(folder_path, "chat.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    # Write feedback.md
    with open(os.path.join(folder_path, "feedback.md"), "w", encoding="utf-8") as f:
        f.write(f"# Feedback\n\n")
        f.write(f"**Datum:** {now.strftime('%d.%m.%Y %H:%M')}\n")
        f.write(f"**Chat:** {title}\n\n")
        f.write("---\n\n")
        f.write(feedback_text)
        f.write("\n")

    # Write metadata.json
    with open(os.path.join(folder_path, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump({
            "conversation_id": conversation_id,
            "title": title,
            "feedback": feedback_text,
            "exported_at": now.isoformat(),
            "message_count": len(messages),
            "image_count": len([m for m in messages if m.get("image_path")]),
        }, f, ensure_ascii=False, indent=2)

    return {"folder": folder_name, "message_count": len(messages)}
