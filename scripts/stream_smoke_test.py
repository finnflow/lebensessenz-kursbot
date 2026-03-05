"""
Smoke test for POST /api/v1/chat/stream.

Usage:
  python scripts/stream_smoke_test.py [--base-url http://localhost:8000]

To test status events with a slow-first-token simulation:
  Start the server with STREAM_TEST_DELAY_BEFORE_FIRST_TOKEN=3.0, then run:
  python scripts/stream_smoke_test.py --delay-test

Requires the server to be running.
"""
import argparse
import json
import sys
import time
import uuid
import urllib.request

try:
    import requests as _requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False


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
    with urllib.request.urlopen(req, timeout=120) as resp:
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


def read_sse_timed(url: str, payload: dict) -> tuple[list[dict], list[float]]:
    """
    Like read_sse but records elapsed seconds (from request start) per event.

    Uses the `requests` library (stream=True) when available so that meta events
    are delivered immediately rather than held in urllib's socket read buffer.
    Falls back to urllib if requests is not installed.
    """
    events: list[dict] = []
    timestamps: list[float] = []
    t0 = time.monotonic()

    if _HAS_REQUESTS:
        with _requests.post(
            url,
            json=payload,
            stream=True,
            headers={"Accept": "text/event-stream"},
            timeout=120,
        ) as resp:
            event_type = None
            for raw_line in resp.iter_lines():
                line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                if line.startswith("event:"):
                    event_type = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    data_str = line[len("data:"):].strip()
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        data = {"raw": data_str}
                    events.append({"event": event_type, "data": data})
                    timestamps.append(time.monotonic() - t0)
                    event_type = None
    else:
        # urllib fallback – note: may buffer small chunks, affecting early-event timestamps
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
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
                    timestamps.append(time.monotonic() - t0)
                    event_type = None

    return events, timestamps


def check_normal(base_url: str, guest_id: str) -> tuple[bool, bool, bool, str]:
    """Returns (meta_ok, deltas_ok, final_ok, note)."""
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

    final_data = next((e["data"] for e in events if e["event"] == "final"), {})
    if not final_data.get("answer"):
        final_ok = False

    note = f"{len(delta_events)} delta(s), answer={repr(final_data.get('answer', '')[:40])}"
    return meta_ok, deltas_ok, final_ok, note


def check_shortcut(base_url: str, guest_id: str) -> tuple[bool, bool, bool, str]:
    """
    Shortcut: message="" + intent="eat" → meta + final, no deltas or status events.
    Returns (meta_ok, no_extra_ok, final_matches_ok, note).
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
    no_extra_ok = not any(t in ("delta", "status") for t in types)
    final_data = next((e["data"] for e in events if e["event"] == "final"), {})
    final_matches_ok = final_data.get("answer") == expected

    note = f"events={types}, answer={repr(final_data.get('answer', ''))}"
    return meta_ok, no_extra_ok, final_matches_ok, note


def check_early_meta(base_url: str, guest_id: str, max_meta_seconds: float = 5.0) -> tuple[bool, str]:
    """Verify meta event arrives within max_meta_seconds of request start."""
    url = f"{base_url}/api/v1/chat/stream"
    payload = {"message": "Was ist Trennkost?", "guestId": guest_id}
    try:
        events, timestamps = read_sse_timed(url, payload)
    except Exception as e:
        return False, str(e)

    meta_idx = next((i for i, e in enumerate(events) if e["event"] == "meta"), None)
    if meta_idx is None:
        return False, "no meta event received"

    meta_time = timestamps[meta_idx]
    fast_ok = meta_time <= max_meta_seconds
    note = f"meta at {meta_time:.2f}s (threshold {max_meta_seconds:.1f}s)"
    return fast_ok, note


def check_status_invariants(base_url: str, guest_id: str) -> tuple[bool, bool, str]:
    """
    Verify: at most 2 status events, all appearing before the first delta.
    Returns (max_2_ok, before_delta_ok, note).
    """
    url = f"{base_url}/api/v1/chat/stream"
    payload = {"message": "Was ist Trennkost?", "guestId": guest_id}
    try:
        events = read_sse(url, payload)
    except Exception as e:
        return False, False, str(e)

    types = [e["event"] for e in events]
    status_events = [e for e in events if e["event"] == "status"]
    max_2_ok = len(status_events) <= 2

    first_delta_idx = next((i for i, t in enumerate(types) if t == "delta"), len(types))
    status_after_delta = any(
        i > first_delta_idx for i, t in enumerate(types) if t == "status"
    )
    before_delta_ok = not status_after_delta

    messages = [e["data"].get("message", "") for e in status_events]
    note = f"{len(status_events)} status event(s): {messages}"
    return max_2_ok, before_delta_ok, note


def check_status_with_delay(base_url: str, guest_id: str) -> tuple[bool, bool, bool, str]:
    """
    Verify status events appear before first delta when STREAM_TEST_DELAY > 2.5s.

    This test assumes the server is running with STREAM_TEST_DELAY_BEFORE_FIRST_TOKEN >= 3.0.
    It checks:
    - meta arrives quickly (< 5s)
    - at least 1 status event is emitted before the first token
    - all status events appear before first delta
    - at most 2 status events total

    Returns (meta_fast_ok, has_status_ok, order_ok, note).
    """
    url = f"{base_url}/api/v1/chat/stream"
    payload = {"message": "Was ist Trennkost?", "guestId": guest_id}
    try:
        events, timestamps = read_sse_timed(url, payload)
    except Exception as e:
        return False, False, False, str(e)

    types = [e["event"] for e in events]

    meta_idx = next((i for i, e in enumerate(events) if e["event"] == "meta"), None)
    meta_fast_ok = meta_idx is not None and timestamps[meta_idx] <= 5.0

    status_events = [e for e in events if e["event"] == "status"]
    has_status_ok = len(status_events) >= 1 and len(status_events) <= 2

    first_delta_idx = next((i for i, t in enumerate(types) if t == "delta"), len(types))
    status_after_delta = any(
        i > first_delta_idx for i, t in enumerate(types) if t == "status"
    )
    order_ok = not status_after_delta

    meta_time = f"{timestamps[meta_idx]:.2f}s" if meta_idx is not None else "n/a"
    messages = [e["data"].get("message", "") for e in status_events]
    note = (
        f"meta={meta_time}, {len(status_events)} status event(s): {messages}, "
        f"first_delta_idx={first_delta_idx}, events={types}"
    )
    return meta_fast_ok, has_status_ok, order_ok, note


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument(
        "--delay-test",
        action="store_true",
        help=(
            "Run status-event delay test. "
            "Requires server started with STREAM_TEST_DELAY_BEFORE_FIRST_TOKEN=3.0"
        ),
    )
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
    print(f"  meta first:             {'✓' if sm_ok else '✗'}")
    print(f"  no deltas/status:       {'✓' if snd_ok else '✗'}")
    print(f"  answer matches:         {'✓' if sf_ok else '✗'}")
    print(f"  note: {snote}\n")

    # --- early meta ---
    em_ok, em_note = check_early_meta(args.base_url, str(uuid.uuid4()))
    print("Early meta test:")
    print(f"  meta within 5s:   {'✓' if em_ok else '✗'}")
    print(f"  note: {em_note}\n")

    # --- status invariants (always) ---
    s2_ok, sbd_ok, s_note = check_status_invariants(args.base_url, str(uuid.uuid4()))
    print("Status event invariants:")
    print(f"  at most 2 events: {'✓' if s2_ok else '✗'}")
    print(f"  all before delta: {'✓' if sbd_ok else '✗'}")
    print(f"  note: {s_note}\n")

    # --- delay-knob test (opt-in) ---
    delay_ok = True
    if args.delay_test:
        print("Delay-knob test (STREAM_TEST_DELAY_BEFORE_FIRST_TOKEN=3.0 required):")
        df_ok, dh_ok, do_ok, d_note = check_status_with_delay(
            args.base_url, str(uuid.uuid4())
        )
        print(f"  meta fast (<5s):        {'✓' if df_ok else '✗'}")
        print(f"  ≥1 status event:        {'✓' if dh_ok else '✗'}")
        print(f"  status before delta:    {'✓' if do_ok else '✗'}")
        print(f"  note: {d_note}\n")
        delay_ok = df_ok and dh_ok and do_ok

    normal_ok = m_ok and d_ok and f_ok
    shortcut_ok = sm_ok and snd_ok and sf_ok
    status_ok = s2_ok and sbd_ok

    print("─" * 50)
    print("RESULTS:")
    print(f"  normal message gets meta+delta+final: {'yes' if normal_ok else 'no'}")
    print(f"  shortcut message gets meta+final:     {'yes' if shortcut_ok else 'no'}")
    print(f"  meta arrives early (< 5s):            {'yes' if em_ok else 'no'}")
    print(f"  status events valid (≤2, pre-delta):  {'yes' if status_ok else 'no'}")
    if args.delay_test:
        print(f"  status fires without token chunks:    {'yes' if delay_ok else 'no'}")
    print(f"  (assistant persisted once: verify in DB - no duplicate rows expected)")
    print("─" * 50)

    all_ok = normal_ok and shortcut_ok and em_ok and status_ok and delay_ok
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    import os
    # Ensure project root is in path so app imports work
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    main()
