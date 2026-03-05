#!/usr/bin/env python3
"""
bot_eval_suite.py — Heuristic evaluation harness for the Lebensessenz Kursbot.

Runs a scenario suite against the local backend and writes structured artifacts:
  eval_artifacts/eval_run_<ts>.jsonl
  eval_artifacts/eval_summary_<ts>.csv
  eval_artifacts/eval_report_<ts>.md

Trennkost rule correctness is explicitly OUT OF SCOPE — only structure,
tone, helpfulness proxies, and intent-style fit are measured.

Usage:
  python scripts/bot_eval_suite.py [options]

Options:
  --base-url   Base URL of the running backend (default: http://localhost:8000)
  --out-dir    Output directory for artifacts    (default: eval_artifacts)
  --n          Limit number of scenarios to run  (default: all)
  --seed       Shuffle seed for scenario ordering (default: 0, 0=no shuffle)
  --stream     Use /api/v1/chat/stream instead of /api/v1/chat (optional)
  --json-only  Skip CSV + Markdown, write JSONL only
"""

import argparse
import csv
import json
import os
import random
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

SCENARIOS: List[Dict[str, Any]] = [
    # ── learn ──────────────────────────────────────────────────────────────
    {
        "id": "learn_01",
        "intent": "learn",
        "tags": ["explain_rules", "obst"],
        "initial_user_message": "Ich verstehe nicht, warum Obst immer alleine gegessen werden soll. Kannst du das erklären?",
        "followup_user_message": "Gibt es eine Ausnahme für Smoothies?",
    },
    {
        "id": "learn_02",
        "intent": "learn",
        "tags": ["explain_rules", "protein_kh"],
        "initial_user_message": "Warum darf man Protein nicht mit Kohlenhydraten kombinieren? Was passiert im Körper?",
        "followup_user_message": None,
    },
    {
        "id": "learn_03",
        "intent": "learn",
        "tags": ["neutral_foods", "examples"],
        "initial_user_message": "Was sind neutrale Lebensmittel und warum sind sie so besonders in der Trennkost?",
        "followup_user_message": "Kannst du mir drei typische Beispiele nennen?",
    },
    {
        "id": "learn_04",
        "intent": "learn",
        "tags": ["explain_rules", "fett"],
        "initial_user_message": "Wie viel Fett darf ich zu einer Mahlzeit essen und worauf muss ich achten?",
        "followup_user_message": None,
    },
    {
        "id": "learn_05",
        "intent": "learn",
        "tags": ["breakfast", "examples"],
        "initial_user_message": "Erkläre mir das Zwei-Stufen-Frühstück einfach und mit Beispielen.",
        "followup_user_message": "Was wäre ein typisches Frühstück für die zweite Stufe?",
    },
    {
        "id": "learn_06",
        "intent": "learn",
        "tags": ["explain_rules", "wartezeiten"],
        "initial_user_message": "Wie lang muss ich nach Obst warten, bevor ich etwas anderes essen darf?",
        "followup_user_message": None,
    },
    {
        "id": "learn_07",
        "intent": "learn",
        "tags": ["hülsenfrüchte", "explain_rules"],
        "initial_user_message": "Ich habe gehört, dass Hülsenfrüchte eine Sonderrolle haben. Was hat es damit auf sich?",
        "followup_user_message": None,
    },
    # ── eat ────────────────────────────────────────────────────────────────
    {
        "id": "eat_01",
        "intent": "eat",
        "tags": ["restaurant", "italian"],
        "initial_user_message": "Ich bin heute Abend im italienischen Restaurant. Was kann ich trennkostkonform bestellen?",
        "followup_user_message": "Was ist mit einem Risotto als Vorspeise?",
    },
    {
        "id": "eat_02",
        "intent": "eat",
        "tags": ["home", "quick"],
        "initial_user_message": "Ich habe Hunger und bin zu Hause. Was kann ich schnell und einfach kochen?",
        "followup_user_message": None,
    },
    {
        "id": "eat_03",
        "intent": "eat",
        "tags": ["restaurant", "asian"],
        "initial_user_message": "Wir gehen heute in ein asiatisches Restaurant. Was passt da zur Trennkost?",
        "followup_user_message": "Was ist mit Sushi?",
    },
    {
        "id": "eat_04",
        "intent": "eat",
        "tags": ["home", "vegetarian"],
        "initial_user_message": "Ich esse kein Fleisch. Was kann ich zu Hause für ein trennkostkonformes Mittagessen kochen?",
        "followup_user_message": None,
    },
    {
        "id": "eat_05",
        "intent": "eat",
        "tags": ["restaurant", "snack"],
        "initial_user_message": "Ich bin auf einer Party und möchte nicht komplett aus dem Trennkost-Konzept fallen. Was soll ich nehmen?",
        "followup_user_message": None,
    },
    {
        "id": "eat_06",
        "intent": "eat",
        "tags": ["home", "breakfast"],
        "initial_user_message": "Was esse ich morgens, wenn ich Trennkost mache und es nicht zu kompliziert sein soll?",
        "followup_user_message": "Kann ich Haferflocken mit Früchten mischen?",
    },
    {
        "id": "eat_07",
        "intent": "eat",
        "tags": ["restaurant", "german"],
        "initial_user_message": "Im deutschen Gasthaus gibt es heute Schweinebraten mit Knödeln und Soße. Kann ich das essen?",
        "followup_user_message": None,
    },
    # ── need ───────────────────────────────────────────────────────────────
    {
        "id": "need_01",
        "intent": "need",
        "tags": ["emotional", "stress"],
        "initial_user_message": "Ich hatte einen stressigen Tag und will jetzt einfach was Comforting essen. Was soll ich tun?",
        "followup_user_message": None,
    },
    {
        "id": "need_02",
        "intent": "need",
        "tags": ["emotional", "süßhunger"],
        "initial_user_message": "Ich habe ständig Lust auf Süßes, obwohl ich eigentlich satt bin. Was steckt dahinter?",
        "followup_user_message": "Gibt es einen ersten kleinen Schritt, den ich heute ausprobieren kann?",
    },
    {
        "id": "need_03",
        "intent": "need",
        "tags": ["uncertainty", "motivation"],
        "initial_user_message": "Ich weiß nicht, ob ich das wirklich durchhalten kann. Die Regeln fühlen sich so kompliziert an.",
        "followup_user_message": None,
    },
    {
        "id": "need_04",
        "intent": "need",
        "tags": ["hunger", "body_signals"],
        "initial_user_message": "Ich merke nicht immer, ob ich wirklich hungrig bin oder nur Lust auf Essen habe. Wie erkenne ich das?",
        "followup_user_message": None,
    },
    {
        "id": "need_05",
        "intent": "need",
        "tags": ["emotional", "abend"],
        "initial_user_message": "Abends nach der Arbeit greife ich immer zu Chips oder Schokolade. Wie höre ich damit auf?",
        "followup_user_message": "Was ist, wenn ich wirklich nicht widerstehen kann?",
    },
    {
        "id": "need_06",
        "intent": "need",
        "tags": ["social_pressure", "uncertainty"],
        "initial_user_message": "Meine Familie kocht immer was anderes als das, was ich essen soll. Ich fühle mich zerrissen.",
        "followup_user_message": None,
    },
    # ── plan ───────────────────────────────────────────────────────────────
    {
        "id": "plan_01",
        "intent": "plan",
        "tags": ["1day", "simple"],
        "initial_user_message": "Kannst du mir einen einfachen Tagesplan für heute erstellen? Kein aufwendiges Kochen.",
        "followup_user_message": "Kannst du auch eine kurze Einkaufsliste dazu machen?",
    },
    {
        "id": "plan_02",
        "intent": "plan",
        "tags": ["3day", "meal_prep"],
        "initial_user_message": "Ich möchte für die nächsten 3 Tage vorplanen und möglichst wenig Zeit kochen. Wie gehe ich vor?",
        "followup_user_message": None,
    },
    {
        "id": "plan_03",
        "intent": "plan",
        "tags": ["shopping_list", "budget"],
        "initial_user_message": "Erstelle mir eine Einkaufsliste für eine Woche Trennkost, die auch nicht zu teuer ist.",
        "followup_user_message": None,
    },
    {
        "id": "plan_04",
        "intent": "plan",
        "tags": ["1day", "vegetarian"],
        "initial_user_message": "Ich esse kein Fleisch. Planst du mir einen vegetarischen Trennkost-Tag?",
        "followup_user_message": "Was esse ich mittags, wenn ich in der Kantine keinen Salat mag?",
    },
    {
        "id": "plan_05",
        "intent": "plan",
        "tags": ["constraints", "family"],
        "initial_user_message": "Ich koche für die ganze Familie, auch für Kinder. Wie plane ich da trennkostkonform?",
        "followup_user_message": None,
    },
    {
        "id": "plan_06",
        "intent": "plan",
        "tags": ["3day", "shopping_list"],
        "initial_user_message": "Ich starte morgen mit Trennkost. Was brauche ich als Einkaufsliste für die ersten 3 Tage?",
        "followup_user_message": "Was kann ich davon schon heute vorbereiten?",
    },
]

# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------

_LEARN_MARKERS = [
    r"\bweil\b", r"\bBeispiel\b", r"\bz\.B\.", r"\bzum Beispiel\b",
    r"\bkurz gesagt\b", r"\bGrund\b", r"\bPrinzip\b", r"\bdas bedeutet\b",
    r"\bFolge\b", r"\bwirkung\b",
]
_EAT_MARKERS = [
    r"\bRestaurant\b", r"\bzu Hause\b", r"\bbestell\b", r"\bwähl\b",
    r"\bOption\b", r"\bAlternative\b", r"\bkann ich\b", r"\bempfehl\b",
    r"\bGericht\b", r"\bMenü\b",
]
_NEED_GENTLE_MARKERS = [
    r"\bMoment\b", r"\bSpür\b", r"\bfühl\b", r"\bpause\b", r"\bAtme\b",
    r"\bschritt\b", r"\bversuch\b", r"\bkleines\b", r"\bfreundlich\b",
    r"\bachtsamk\b", r"\bwas brauchst\b",
]
_PLAN_MARKERS = [
    r"\bTag\b", r"\bWoche\b", r"\bMorgen\b", r"\bMittag\b", r"\bAbend\b",
    r"\bFrühstück\b", r"\bMahlzeit\b", r"\bEinkauf\b", r"\bSchritt\b",
    r"\bPlan\b", r"\bListe\b",
]
_MEDICAL_RISK_TERMS = [
    r"\bDiagnose\b", r"\bTherapie\b", r"\bMedikament\b", r"\bheilen\b",
    r"\bBehandlung\b", r"\bArzt\b", r"\bKrankheit\b", r"\bSyptom\b",
]
_CONCRETE_MARKERS = [
    r"\bz\.B\.", r"\bzum Beispiel\b", r"\bkann ich\b", r"\bkannst du\b",
    r"\bempfehle\b", r"\bprobier\b", r"\bversuche\b", r"\bbeispielsweise\b",
    r"\bkonkret\b", r"\bSchritt\b", r"\bOption\b", r"\bAlternative\b",
    r"-\s", r"\d+\.", r"\*",
]


def _match_any(patterns: List[str], text: str) -> bool:
    t = text.lower()
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            return True
    return False


def score_turn(answer: str, intent: str, sources_count: int) -> Tuple[Dict, Dict]:
    """Return (metrics, flags) for a single answer turn."""
    words = answer.split()
    sentences = re.split(r"[.!?]+", answer)
    sentences = [s for s in sentences if s.strip()]
    q_count = answer.count("?")

    # Intent style markers
    if intent == "learn":
        style_match = _match_any(_LEARN_MARKERS, answer)
    elif intent == "eat":
        style_match = _match_any(_EAT_MARKERS, answer)
    elif intent == "need":
        style_match = _match_any(_NEED_GENTLE_MARKERS, answer)
    elif intent == "plan":
        style_match = _match_any(_PLAN_MARKERS, answer)
    else:
        style_match = False

    # Helpfulness proxy: concrete suggestion or structured question
    is_concrete = _match_any(_CONCRETE_MARKERS, answer)
    is_generic = not is_concrete and q_count == 0

    # Need-specific: question count guard (≤ 2)
    need_guard_pass = (q_count <= 2) if intent == "need" else None

    # Medical risk flag (should be False)
    medical_flag = _match_any(_MEDICAL_RISK_TERMS, answer)

    metrics = {
        "chars_len": len(answer),
        "words_len": len(words),
        "sentences_est": len(sentences),
        "question_count": q_count,
        "has_followup_question": q_count >= 1,
        "too_long": len(words) > 140,
        "too_short": len(words) < 20,
        "intent_style_match": style_match,
        "sources_count": sources_count,
        "grounded": sources_count > 0,
        "is_generic": is_generic,
        "need_question_guard_pass": need_guard_pass,
    }
    flags = {
        "medical_safety_risk": medical_flag,
        "too_long": metrics["too_long"],
        "too_short": metrics["too_short"],
        "is_generic": is_generic,
    }
    return metrics, flags


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _post_json(base_url: str, payload: Dict, timeout: int = 60) -> Tuple[Dict, float]:
    """POST to /api/v1/chat, return (response_dict, latency_ms)."""
    import urllib.request

    url = f"{base_url.rstrip('/')}/api/v1/chat"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            latency_ms = (time.monotonic() - t0) * 1000
            return json.loads(body), latency_ms
    except Exception as exc:
        latency_ms = (time.monotonic() - t0) * 1000
        return {"error": str(exc), "answer": f"[ERROR: {exc}]", "sources": [], "conversationId": None}, latency_ms


def _read_sse_stream(base_url: str, payload: Dict, timeout: int = 60) -> Tuple[Dict, float, float, float]:
    """
    POST to /api/v1/chat/stream, consume SSE, return:
      (final_payload, latency_to_meta_ms, latency_to_first_delta_ms, total_latency_ms)
    """
    import socket
    import http.client
    import urllib.parse

    url = f"{base_url.rstrip('/')}/api/v1/chat/stream"
    parsed = urllib.parse.urlparse(url)
    body = json.dumps(payload).encode("utf-8")

    t0 = time.monotonic()
    t_meta = None
    t_first_delta = None
    final_data: Dict = {}

    try:
        conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 8000, timeout=timeout)
        conn.request("POST", parsed.path, body=body,
                     headers={"Content-Type": "application/json", "Accept": "text/event-stream"})
        resp = conn.getresponse()
        buf = ""
        current_event = None
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if line.startswith("event:"):
                current_event = line[6:].strip()
                if current_event == "meta" and t_meta is None:
                    t_meta = (time.monotonic() - t0) * 1000
            elif line.startswith("data:"):
                data_str = line[5:].strip()
                try:
                    d = json.loads(data_str)
                except Exception:
                    d = {}
                if current_event == "delta" and t_first_delta is None:
                    t_first_delta = (time.monotonic() - t0) * 1000
                if current_event == "final":
                    final_data = d
                    break
            elif line == "":
                current_event = None
        conn.close()
    except Exception as exc:
        final_data = {"error": str(exc), "answer": f"[ERROR: {exc}]", "sources": [], "conversationId": None}

    total = (time.monotonic() - t0) * 1000
    return final_data, t_meta or total, t_first_delta or total, total


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_scenario(
    scenario: Dict,
    guest_id: str,
    base_url: str,
    use_stream: bool = False,
) -> List[Dict]:
    """Run one scenario (1 or 2 turns). Returns list of turn result dicts."""
    turns = []
    conv_id = None

    messages_to_send = [scenario["initial_user_message"]]
    if scenario.get("followup_user_message"):
        messages_to_send.append(scenario["followup_user_message"])

    for turn_idx, msg in enumerate(messages_to_send):
        payload = {
            "message": msg,
            "guestId": guest_id,
            "conversationId": conv_id,
            "intent": scenario["intent"] if turn_idx == 0 else None,
        }
        if use_stream:
            resp, t_meta, t_delta, latency_ms = _read_sse_stream(base_url, payload)
            extra = {"t_meta_ms": t_meta, "t_first_delta_ms": t_delta}
        else:
            resp, latency_ms = _post_json(base_url, payload)
            extra = {}

        answer = resp.get("answer", "")
        sources = resp.get("sources") or []
        conv_id = resp.get("conversationId") or conv_id

        metrics, flags = score_turn(answer, scenario["intent"], len(sources))

        turns.append({
            "scenario_id": scenario["id"],
            "intent": scenario["intent"],
            "tags": scenario.get("tags", []),
            "turn_index": turn_idx,
            "user_message": msg,
            "conversation_id": conv_id,
            "latency_ms": round(latency_ms, 1),
            "answer_text": answer,
            "sources_count": len(sources),
            "metrics": metrics,
            "flags": flags,
            **extra,
        })

        jitter = random.uniform(0.3, 0.8)
        time.sleep(jitter)

    return turns


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def _rate(items: List, key: str) -> float:
    if not items:
        return 0.0
    hits = sum(1 for x in items if x.get("metrics", {}).get(key) or x.get("flags", {}).get(key))
    return round(hits / len(items), 3)


def _need_guard_rate(turns: List) -> Optional[float]:
    need_turns = [t for t in turns if t["intent"] == "need" and
                  t["metrics"].get("need_question_guard_pass") is not None]
    if not need_turns:
        return None
    return round(sum(1 for t in need_turns if t["metrics"]["need_question_guard_pass"]) / len(need_turns), 3)


def aggregate_scenario(scenario: Dict, turns: List[Dict]) -> Dict:
    return {
        "scenario_id": scenario["id"],
        "intent": scenario["intent"],
        "tags": ",".join(scenario.get("tags", [])),
        "turns": len(turns),
        "avg_latency_ms": round(sum(t["latency_ms"] for t in turns) / len(turns), 1) if turns else 0,
        "too_long_rate": _rate(turns, "too_long"),
        "too_short_rate": _rate(turns, "too_short"),
        "intent_style_match_rate": _rate(turns, "intent_style_match"),
        "has_followup_question_rate": _rate(turns, "has_followup_question"),
        "need_question_guard_pass": _need_guard_rate(turns),
        "medical_risk_flag_rate": _rate(turns, "medical_safety_risk"),
        "grounded_rate": _rate(turns, "grounded"),
        "generic_rate": _rate(turns, "is_generic"),
    }


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------

def write_jsonl(path: str, run_id: str, all_turns: List[Dict]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with open(path, "w", encoding="utf-8") as f:
        for t in all_turns:
            record = {"run_id": run_id, "timestamp_iso": now, **t}
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_csv(path: str, summaries: List[Dict]) -> None:
    if not summaries:
        return
    fieldnames = list(summaries[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(summaries)


def _pct(v) -> str:
    if v is None:
        return "n/a"
    return f"{v * 100:.1f}%"


def write_markdown(path: str, run_id: str, all_turns: List[Dict], summaries: List[Dict]) -> None:
    lines = [
        f"# Bot Eval Report",
        f"",
        f"**Run ID:** `{run_id}`  ",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"**Scenarios:** {len(summaries)}  **Turns:** {len(all_turns)}",
        f"",
        f"---",
        f"",
        f"## Overall Metrics",
        f"",
    ]

    intents = ["learn", "eat", "need", "plan"]
    for intent in intents:
        t_group = [t for t in all_turns if t["intent"] == intent]
        s_group = [s for s in summaries if s["intent"] == intent]
        if not t_group:
            continue
        avg_lat = round(sum(t["latency_ms"] for t in t_group) / len(t_group), 0)
        lines += [
            f"### {intent.upper()}",
            f"- Turns: {len(t_group)}",
            f"- Avg latency: {avg_lat} ms",
            f"- Intent style match: {_pct(_rate(t_group, 'intent_style_match'))}",
            f"- Has follow-up question: {_pct(_rate(t_group, 'has_followup_question'))}",
            f"- Too long: {_pct(_rate(t_group, 'too_long'))}  |  Too short: {_pct(_rate(t_group, 'too_short'))}",
            f"- Generic rate: {_pct(_rate(t_group, 'is_generic'))}",
            f"- Grounded (sources>0): {_pct(_rate(t_group, 'grounded'))}",
            f"",
        ]

    # Need guard
    ng = _need_guard_rate(all_turns)
    lines += [
        f"### NEED question-count guard",
        f"- Pass rate (≤2 questions): {_pct(ng)}",
        f"",
    ]

    # Medical risk
    med_rate = _rate(all_turns, "medical_safety_risk")
    lines += [
        f"### Medical risk flags",
        f"- Rate: {_pct(med_rate)} {'⚠️ REVIEW' if med_rate > 0 else '✅ None detected'}",
        f"",
        f"---",
        f"",
    ]

    # Weakest scenarios (by generic + too_long + intent mismatch)
    def weakness_score(s: Dict) -> float:
        score = 0.0
        score += s.get("generic_rate", 0) * 2
        score += s.get("too_long_rate", 0) * 1.5
        score += (1 - s.get("intent_style_match_rate", 0)) * 1.5
        score += s.get("too_short_rate", 0) * 1
        score += s.get("medical_risk_flag_rate", 0) * 3
        return score

    worst = sorted(summaries, key=weakness_score, reverse=True)[:5]
    lines += [f"## Top 5 Weakest Scenarios", f""]
    for s in worst:
        lines.append(
            f"- **{s['scenario_id']}** ({s['intent']}) — "
            f"generic={_pct(s['generic_rate'])} too_long={_pct(s['too_long_rate'])} "
            f"style={_pct(s['intent_style_match_rate'])} lat={s['avg_latency_ms']}ms"
        )

    # Excerpts for weakest
    lines += [f"", f"### Answer excerpts (weakest, ≤200 chars)", f""]
    shown = 0
    for s in worst[:3]:
        t_for = [t for t in all_turns if t["scenario_id"] == s["scenario_id"]]
        for t in t_for[:1]:
            excerpt = t["answer_text"][:200].replace("\n", " ")
            lines.append(f"> **{s['scenario_id']}** turn {t['turn_index']}: _{excerpt}..._")
            lines.append("")
            shown += 1
            if shown >= 3:
                break
        if shown >= 3:
            break

    lines += [f"", f"---", f"", f"## Scenario Summary Table", f""]
    header = "| ID | Intent | Turns | Lat(ms) | Style | FollowQ | Generic | TooLong | Grounded |"
    sep =    "|----|--------|-------|---------|-------|---------|---------|---------|----------|"
    lines += [header, sep]
    for s in summaries:
        lines.append(
            f"| {s['scenario_id']} | {s['intent']} | {s['turns']} | {s['avg_latency_ms']} "
            f"| {_pct(s['intent_style_match_rate'])} "
            f"| {_pct(s['has_followup_question_rate'])} "
            f"| {_pct(s['generic_rate'])} "
            f"| {_pct(s['too_long_rate'])} "
            f"| {_pct(s['grounded_rate'])} |"
        )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# RESULTS printer
# ---------------------------------------------------------------------------

def print_results(
    all_turns: List[Dict],
    summaries: List[Dict],
    artifacts: List[str],
    elapsed_s: float,
) -> None:
    print("\n" + "=" * 60)
    print("  RESULTS")
    print("=" * 60)

    n_scenarios = len(summaries)
    n_turns = len(all_turns)
    avg_lat = round(sum(t["latency_ms"] for t in all_turns) / n_turns, 0) if all_turns else 0

    print(f"  scenarios_run          : {n_scenarios}")
    print(f"  total_turns            : {n_turns}")
    print(f"  wall_time_s            : {elapsed_s:.1f}")
    print(f"  avg_latency_ms         : {avg_lat}")
    print(f"  generic_rate           : {_pct(_rate(all_turns, 'is_generic'))}")
    print(f"  intent_style_match     : {_pct(_rate(all_turns, 'intent_style_match'))}")
    print()

    for intent in ["learn", "eat", "need", "plan"]:
        t_group = [t for t in all_turns if t["intent"] == intent]
        if not t_group:
            continue
        print(f"  [{intent:<5}] style={_pct(_rate(t_group, 'intent_style_match')):<8} "
              f"generic={_pct(_rate(t_group, 'is_generic')):<8} "
              f"followQ={_pct(_rate(t_group, 'has_followup_question'))}")

    print()
    print(f"  too_long_rate          : {_pct(_rate(all_turns, 'too_long'))}")
    print(f"  too_short_rate         : {_pct(_rate(all_turns, 'too_short'))}")
    ng = _need_guard_rate(all_turns)
    print(f"  need_guard_pass_rate   : {_pct(ng)}")
    print(f"  medical_risk_flag_rate : {_pct(_rate(all_turns, 'medical_safety_risk'))}")
    print()
    print("  Artifacts:")
    for a in artifacts:
        print(f"    {a}")
    print("=" * 60 + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Lebensessenz bot evaluation suite")
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--out-dir", default="eval_artifacts")
    p.add_argument("--n", type=int, default=0, help="Limit number of scenarios (0 = all)")
    p.add_argument("--seed", type=int, default=0, help="Shuffle seed (0 = no shuffle)")
    p.add_argument("--stream", action="store_true", help="Use /api/v1/chat/stream")
    p.add_argument("--json-only", action="store_true", help="Write JSONL only, skip CSV+MD")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # Health check
    import urllib.request
    try:
        with urllib.request.urlopen(f"{args.base_url.rstrip('/')}/api/v1/health", timeout=5) as r:
            pass
    except Exception as exc:
        print(f"[ERROR] Backend not reachable at {args.base_url}: {exc}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(args.out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_id = f"run_{ts}_{uuid.uuid4().hex[:8]}"
    guest_id = f"eval-{uuid.uuid4().hex[:12]}"

    scenarios = list(SCENARIOS)
    if args.seed:
        random.seed(args.seed)
        random.shuffle(scenarios)
    if args.n and args.n > 0:
        scenarios = scenarios[:args.n]

    print(f"[EVAL] run_id={run_id}  scenarios={len(scenarios)}  guest={guest_id}")
    print(f"[EVAL] backend={args.base_url}  stream={args.stream}\n")

    all_turns: List[Dict] = []
    summaries: List[Dict] = []
    t_start = time.monotonic()

    for i, scenario in enumerate(scenarios, 1):
        print(f"  [{i:02d}/{len(scenarios)}] {scenario['id']} ({scenario['intent']}) ...", end=" ", flush=True)
        t0 = time.monotonic()
        turns = run_scenario(scenario, guest_id, args.base_url, use_stream=args.stream)
        elapsed = time.monotonic() - t0
        all_turns.extend(turns)
        summary = aggregate_scenario(scenario, turns)
        summaries.append(summary)
        latencies = [t["latency_ms"] for t in turns]
        print(f"turns={len(turns)}  lat={[round(l) for l in latencies]}ms  "
              f"style={'Y' if summary['intent_style_match_rate'] > 0 else 'N'}  "
              f"generic={'Y' if summary['generic_rate'] > 0 else 'N'}")

    elapsed_s = time.monotonic() - t_start

    # Write artifacts
    jsonl_path = os.path.join(args.out_dir, f"eval_run_{ts}.jsonl")
    write_jsonl(jsonl_path, run_id, all_turns)
    artifacts = [jsonl_path]

    if not args.json_only:
        csv_path = os.path.join(args.out_dir, f"eval_summary_{ts}.csv")
        write_csv(csv_path, summaries)
        artifacts.append(csv_path)

        md_path = os.path.join(args.out_dir, f"eval_report_{ts}.md")
        write_markdown(md_path, run_id, all_turns, summaries)
        artifacts.append(md_path)

    print_results(all_turns, summaries, artifacts, elapsed_s)


if __name__ == "__main__":
    main()
