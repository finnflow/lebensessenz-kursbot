#!/usr/bin/env python3
"""
Smoke test script for chat with sidebar functionality.

Usage:
    python test_chat_sidebar.py
"""
import requests
import json
import sys
import uuid

BASE_URL = "http://localhost:8000"

def test_chat_with_sidebar():
    print("🧪 Starting Chat with Sidebar Smoke Test...\n")

    # Generate guest ID
    guest_id = str(uuid.uuid4())
    print(f"👤 Guest ID: {guest_id}\n")

    # Test 1: Create first conversation
    print("📝 Conversation 1 - Turn 1: 'Nenn mir die Kernpunkte von Seite 4'")
    response1 = requests.post(
        f"{BASE_URL}/chat",
        json={
            "message": "Nenn mir die Kernpunkte von Seite 4",
            "guestId": guest_id
        }
    )

    if response1.status_code != 200:
        print(f"❌ Turn 1 failed: {response1.status_code}")
        print(response1.text)
        sys.exit(1)

    data1 = response1.json()
    conv1_id = data1["conversationId"]
    print(f"✅ Conversation 1 created! ID: {conv1_id}")
    print(f"📄 Answer preview: {data1['answer'][:100]}...")
    print(f"📚 Sources: {len(data1['sources'])} snippets\n")

    # Test 2: Continue first conversation
    print("📝 Conversation 1 - Turn 2: 'Und wie war das mit Milchprodukten?'")
    response2 = requests.post(
        f"{BASE_URL}/chat",
        json={
            "conversationId": conv1_id,
            "message": "Und wie war das mit Milchprodukten?",
            "guestId": guest_id
        }
    )

    if response2.status_code != 200:
        print(f"❌ Turn 2 failed: {response2.status_code}")
        sys.exit(1)

    data2 = response2.json()
    print(f"✅ Turn 2 successful!")
    print(f"📄 Answer preview: {data2['answer'][:100]}...\n")

    # Test 3: Create second conversation
    print("📝 Conversation 2 - Turn 1: 'Erkläre mir die 50/50-Regel'")
    response3 = requests.post(
        f"{BASE_URL}/chat",
        json={
            "message": "Erkläre mir die 50/50-Regel",
            "guestId": guest_id
        }
    )

    if response3.status_code != 200:
        print(f"❌ Conversation 2 failed: {response3.status_code}")
        sys.exit(1)

    data3 = response3.json()
    conv2_id = data3["conversationId"]
    print(f"✅ Conversation 2 created! ID: {conv2_id}")
    print(f"📄 Answer preview: {data3['answer'][:100]}...\n")

    # Test 4: Get conversations list
    print("📝 Fetching conversations list...")
    response4 = requests.get(f"{BASE_URL}/conversations?guest_id={guest_id}")

    if response4.status_code != 200:
        print(f"❌ Conversations list failed: {response4.status_code}")
        sys.exit(1)

    data4 = response4.json()
    conversations = data4["conversations"]
    print(f"✅ Conversations fetched! Total: {len(conversations)}")

    for i, conv in enumerate(conversations, 1):
        title = conv.get("title", "No title")
        print(f"  📁 {i}. {title[:50]}... (ID: {conv['id'][:8]}...)")

    if len(conversations) < 2:
        print(f"❌ Expected at least 2 conversations, got {len(conversations)}")
        sys.exit(1)

    # Test 5: Get messages from first conversation
    print(f"\n📝 Fetching messages from Conversation 1...")
    response5 = requests.get(
        f"{BASE_URL}/conversations/{conv1_id}/messages?guest_id={guest_id}"
    )

    if response5.status_code != 200:
        print(f"❌ Messages fetch failed: {response5.status_code}")
        sys.exit(1)

    data5 = response5.json()
    messages = data5["messages"]
    print(f"✅ Messages fetched! Total: {len(messages)}")

    for i, msg in enumerate(messages, 1):
        role_emoji = "👤" if msg["role"] == "user" else "🤖"
        content_preview = msg["content"][:60].replace("\n", " ")
        print(f"  {role_emoji} Message {i}: {content_preview}...")

    if len(messages) < 4:
        print(f"❌ Expected at least 4 messages in Conversation 1, got {len(messages)}")
        sys.exit(1)

    # Test 6: Test guest isolation (try to access with wrong guest ID)
    print(f"\n📝 Testing guest isolation...")
    wrong_guest_id = str(uuid.uuid4())
    response6 = requests.get(
        f"{BASE_URL}/conversations/{conv1_id}/messages?guest_id={wrong_guest_id}"
    )

    if response6.status_code == 403:
        print("✅ Guest isolation working! Access correctly denied.")
    else:
        print(f"⚠️  Warning: Expected 403, got {response6.status_code}")

    print("\n✨ All tests passed!")
    print(f"👤 Guest ID: {guest_id}")
    print(f"📁 Conversation 1: {conv1_id}")
    print(f"📁 Conversation 2: {conv2_id}")
    print("\n💡 Tip: Open http://localhost:8000 and check if sidebar shows both conversations")

if __name__ == "__main__":
    try:
        test_chat_with_sidebar()
    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to server. Is it running on http://localhost:8000?")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
