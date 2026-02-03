#!/usr/bin/env python3
"""
Smoke test script for chat functionality.

Usage:
    python test_chat.py
"""
import requests
import json
import sys

BASE_URL = "http://localhost:8000"

def test_chat():
    print("🧪 Starting Chat Smoke Test...\n")

    # Test 1: First turn
    print("📝 Turn 1: 'Nenn mir die Kernpunkte von Seite 4'")
    response1 = requests.post(
        f"{BASE_URL}/chat",
        json={"message": "Nenn mir die Kernpunkte von Seite 4"}
    )

    if response1.status_code != 200:
        print(f"❌ Turn 1 failed: {response1.status_code}")
        print(response1.text)
        sys.exit(1)

    data1 = response1.json()
    conversation_id = data1["conversationId"]
    print(f"✅ Turn 1 successful! Conversation ID: {conversation_id}")
    print(f"📄 Answer preview: {data1['answer'][:150]}...")
    print(f"📚 Sources: {len(data1['sources'])} snippets\n")

    # Test 2: Follow-up with reference
    print("📝 Turn 2: 'Und wie war das mit Milchprodukten?'")
    response2 = requests.post(
        f"{BASE_URL}/chat",
        json={
            "conversationId": conversation_id,
            "message": "Und wie war das mit Milchprodukten?"
        }
    )

    if response2.status_code != 200:
        print(f"❌ Turn 2 failed: {response2.status_code}")
        print(response2.text)
        sys.exit(1)

    data2 = response2.json()
    print(f"✅ Turn 2 successful!")
    print(f"📄 Answer preview: {data2['answer'][:150]}...")
    print(f"📚 Sources: {len(data2['sources'])} snippets\n")

    # Test 3: Get conversation history
    print("📝 Fetching conversation history...")
    response3 = requests.get(f"{BASE_URL}/conversations/{conversation_id}/messages")

    if response3.status_code != 200:
        print(f"❌ History fetch failed: {response3.status_code}")
        sys.exit(1)

    data3 = response3.json()
    messages = data3["messages"]
    print(f"✅ History fetched! Total messages: {len(messages)}")

    for i, msg in enumerate(messages, 1):
        role_emoji = "👤" if msg["role"] == "user" else "🤖"
        content_preview = msg["content"][:60].replace("\n", " ")
        print(f"  {role_emoji} Message {i}: {content_preview}...")

    print("\n✨ All tests passed!")
    print(f"🔗 Conversation ID: {conversation_id}")

if __name__ == "__main__":
    try:
        test_chat()
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to server. Is it running on http://localhost:8000?")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
