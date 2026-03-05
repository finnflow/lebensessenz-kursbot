"""
Smoke test for POST /api/v1/chat/stream.

Usage:
  python scripts/stream_smoke_test.py [--base-url http://localhost:8000]

Requires the server to be running.
"""
import argparse
import json
import sys
import uuid
import urllib.request


def read_sse(url: str, payload: dict) -> list[dict]:
    """POST to url with JSON payload, read all SSE events, return list of {event, data}."""
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    events = []
    with urllib.request.urlopen(req, timeout=60) as resp:
        event_type = None
        for raw_line in resp:
            line = raw_line.decode("utf-8").rstrip("\n")
            if line.startswith("event:"):
                event_type = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_str = line[len("data:"):].strip()
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    data = {"raw": data_str}
                events.append({"event": event_type, "data": data})
                event_type = None
    return events


def check_normal(base_url: str, guest_id: str) -> tuple[bool, bool, bool, str]:
    """
    Returns (meta_ok, deltas_ok, final_ok, note).
    """
    url = f"{base_url}/api/v1/chat/stream"
    payload = {"message": "Was ist Trennkost?", "guestId": guest_id}
    try:
        events = read_sse(url, payload)
    except Exception as e:
        return False, False, False, str(e)

    types = [e["event"] for e in events]
    meta_ok = types[0] == "meta" if types else False
    final_ok = types[-1] == "final" if types else False
    delta_events = [e for e in events if e["event"] == "delta"]
    deltas_ok = len(delta_events) > 0

    # Verify final has answer
    final_data = next((e["data"] for e in events if e["event"] == "final"), {})
    if not final_data.get("answer"):
        final_ok = False

    note = f"{len(delta_events)} delta(s), answer={repr(final_data.get('answer', '')[:40])}"
    return meta_ok, deltas_ok, final_ok, note


def check_shortcut(base_url: str, guest_id: str) -> tuple[bool, bool, bool, str]:
    """
    Shortcut: message="" + intent="eat" → meta + final, no deltas.
    Returns (meta_ok, no_deltas_ok, final_matches_ok, note).
    """
    from app.chat_service import first_question_for_intent  # import after cwd setup
    expected = first_question_for_intent("eat")

    url = f"{base_url}/api/v1/chat/stream"
    payload = {"message": "", "guestId": guest_id, "intent": "eat"}
    try:
        events = read_sse(url, payload)
    except Exception as e:
        return False, False, False, str(e)

    types = [e["event"] for e in events]
    meta_ok = types[0] == "meta" if types else False
    no_deltas_ok = not any(t == "delta" for t in types)
    final_data = next((e["data"] for e in events if e["event"] == "final"), {})
    final_matches_ok = final_data.get("answer") == expected

    note = f"events={types}, answer={repr(final_data.get('answer', ''))}"
    return meta_ok, no_deltas_ok, final_matches_ok, note


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()

    guest_id = str(uuid.uuid4())
    print(f"Smoke test → {args.base_url}  guest_id={guest_id}\n")

    # --- normal message ---
    m_ok, d_ok, f_ok, note = check_normal(args.base_url, guest_id)
    print("Normal message test:")
    print(f"  meta first:       {'✓' if m_ok else '✗'}")
    print(f"  deltas received:  {'✓' if d_ok else '✗'}")
    print(f"  final last+valid: {'✓' if f_ok else '✗'}")
    print(f"  note: {note}\n")

    # --- shortcut ---
    sm_ok, snd_ok, sf_ok, snote = check_shortcut(args.base_url, guest_id)
    print("Shortcut test (message='', intent='eat'):")
    print(f"  meta first:       {'✓' if sm_ok else '✗'}")
    print(f"  no deltas:        {'✓' if snd_ok else '✗'}")
    print(f"  answer matches:   {'✓' if sf_ok else '✗'}")
    print(f"  note: {snote}\n")

    normal_ok = m_ok and d_ok and f_ok
    shortcut_ok = sm_ok and snd_ok and sf_ok

    print("─" * 50)
    print("RESULTS:")
    print(f"  normal message gets meta+delta+final: {'yes' if normal_ok else 'no'}")
    print(f"  shortcut message gets meta+final:     {'yes' if shortcut_ok else 'no'}")
    print(f"  (assistant persisted once: verify in DB - no duplicate rows expected)")
    print("─" * 50)

    sys.exit(0 if (normal_ok and shortcut_ok) else 1)


if __name__ == "__main__":
    import os
    # Ensure project root is in path so app imports work
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    main()
