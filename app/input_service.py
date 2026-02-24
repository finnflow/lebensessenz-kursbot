"""
Input processing service.

Handles normalization, intent classification, food extraction and
context reference resolution.
"""
import re
import json
from typing import List, Dict, Optional, Any

from app.clients import client, MODEL


# ── LLM helper ───────────────────────────────────────────────────────

def llm_call(system_prompt: str, user_msg: str) -> str:
    """
    Thin LLM wrapper passed to normalizer for extraction/classification.
    Used ONLY for unknown item classification, never for verdicts.
    """
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.1,
        max_tokens=500,
    )
    return response.choices[0].message.content.strip()


# ── Normalization ─────────────────────────────────────────────────────

def normalize_input(
    user_message: str,
    recent_messages: List[Dict[str, Any]],
    is_new_conversation: bool,
) -> str:
    """
    Normalize user input to create canonical format for deterministic logic.

    Handles:
    - Language translation to German
    - Time format standardization ("30 minuten" → "30 min")
    - Food name standardization
    - Typo fixing
    - Punctuation cleanup
    - Abbreviation expansion

    Special handling for follow-ups:
    - Short messages (<5 words) with recent context are marked as potential follow-ups
    - LLM preserves or minimally expands follow-ups with context reference
    - Prevents incorrect expansion of context-dependent messages like "den Fisch"
    """
    # Skip normalization for very long messages (already well-formed)
    if len(user_message) > 200:
        return user_message

    # Detect potential follow-up context
    is_potential_followup = False
    previous_context = ""

    if not is_new_conversation and recent_messages:
        word_count = len(user_message.strip().split())
        if word_count <= 5:
            is_potential_followup = True

            context_messages = []
            for msg in recent_messages[-4:]:
                role = "User" if msg.get("role") == "user" else "Assistant"
                content = msg.get("content", "")[:200]
                context_messages.append(f"{role}: {content}")
            previous_context = "\n".join(context_messages)

    normalization_prompt = f"""Du normalisierst Benutzereingaben für ein Trennkost-Ernährungsberatungs-System.

**Deine Aufgaben:**
1. **Sprache:** Übersetze alle Texte ins Deutsche (falls nicht bereits Deutsch)
2. **Zeitangaben:** Standardisiere zu "X min" Format (z.B. "30 minuten" → "30 min", "eine halbe Stunde" → "30 min")
3. **Lebensmittel:** Verwende deutsche Standardnamen (z.B. "chicken" → "Hähnchen", "rice" → "Reis")
4. **Tippfehler:** Korrigiere offensichtliche Tippfehler (z.B. "danm" → "dann", "Resi" → "Reis")
5. **Interpunktion:** Bereinige und vervollständige
6. **Abkürzungen:** Expandiere gängige Abkürzungen (z.B. "z.B." bleibt, aber "min" → "Minuten" nur bei Mehrdeutigkeit)

**WICHTIG - Follow-up Nachrichten:**
- Wenn die Nachricht sehr kurz ist (<5 Wörter) UND vorheriger Kontext existiert, ist es wahrscheinlich eine Follow-up-Nachricht
- Follow-ups sollten NICHT erweitert werden, wenn sie klar kontextabhängig sind
- Beispiele:
  * "den Fisch" (im Kontext einer Wahlsituation) → "den Fisch" (NICHT erweitern!)
  * "ok" (als Bestätigung) → "ok" (NICHT erweitern!)
  * "egal" (als Antwort) → "egal" (NICHT erweitern!)
  * "danm" (als Standalone) → "dann" (Tippfehler korrigieren ist OK)

"""

    if is_potential_followup and previous_context:
        normalization_prompt += f"""
**VORHERIGER KONTEXT (Follow-up-Erkennung):**
{previous_context}

Die aktuelle Nachricht ist wahrscheinlich eine Follow-up-Antwort. Bewahre ihre Bedeutung, erweitere sie NICHT zu einer vollständigen Frage, außer sie ist offensichtlich unvollständig.
"""

    normalization_prompt += f"""
**Aktuelle Nachricht:**
{user_message}

**Normalisierte Nachricht:**"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": normalization_prompt}],
            temperature=0.0,
            max_tokens=150,
            timeout=5,
        )
        normalized = response.choices[0].message.content.strip()

        original_len = len(user_message)
        normalized_len = len(normalized)
        if normalized_len > original_len * 3:
            print(f"[NORMALIZE] Warning: normalized message too long ({normalized_len} vs {original_len}), using original")
            return user_message

        if normalized != user_message:
            print(f"[NORMALIZE] '{user_message}' → '{normalized}'")

        return normalized

    except Exception as e:
        print(f"[NORMALIZE] Failed: {e}, using original message")
        return user_message


# ── Food classification ───────────────────────────────────────────────

def classify_food_items(user_message: str, standalone_query: str) -> Optional[Dict[str, Any]]:
    """
    LLM-basierte Analyse von Lebensmitteln in der Frage.
    Extrahiert und klassifiziert automatisch in Kurskategorien.
    """
    classification_prompt = f"""Analysiere die folgende Frage über Lebensmittel und klassifiziere die Komponenten
in diese Kategorien aus unserem Ernährungskurs:
- Protein (Fleisch, Fisch, Eier, Käse, Hülsenfrüchte)
- Komplexe Kohlenhydrate (Reis, Vollkornbrot, Kartoffeln, Hülsenfrüchte)
- Obst (frisch, Säfte)
- Gemüse / Salat
- Fette / Öle
- Zucker / Süßes

WICHTIG:
1. Bei zusammengesetzten Lebensmitteln (Döner, Burger, Pizza, etc.):
   - Zerlege sie in ihre Standard-Komponenten
   - Beispiele:
     * Pizza → Teig (Kohlenhydrate), Käse (Protein), Sauce (Gemüse/Zucker)
     * Döner (Standard) → Fleisch (Protein), Brot (Kohlenhydrate), Salat (Gemüse), Sauce (Fett)
     * Burger (Standard) → Fleisch (Protein), Brötchen (Kohlenhydrate)

2. Bei MEHRDEUTIGEN Lebensmitteln:
   - Wenn wichtige Details fehlen (z.B. "Burger" - vegan oder Fleisch?)
   - Oder wenn Varianten die Kombination ändern (z.B. "Pizza" - welcher Belag?)
   - Markiere dies mit "NEEDS_CLARIFICATION: [konkrete Frage]"

3. Bei Wartezeit-Fragen:
   - Erkenne Richtung (VOR oder NACH dem Verzehr)
   - Füge Keywords hinzu: "Wartedauer", "zeitlicher Abstand", "Obstverzehr"

Frage: {user_message}

Antworte im Format:
1. Erkannte Lebensmittel: [...]
2. Klassifikation: [...]
3. Falls mehrdeutig: NEEDS_CLARIFICATION: [konkrete Frage an Nutzer]
"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": classification_prompt}],
            temperature=0.1,
            max_tokens=200,
            timeout=5,
        )
        result = response.choices[0].message.content.strip()

        needs_clarification = None
        if "NEEDS_CLARIFICATION:" in result:
            parts = result.split("NEEDS_CLARIFICATION:")
            classification = parts[0].strip()
            needs_clarification = parts[1].strip()
        else:
            classification = result

        return {
            "classification": classification,
            "needs_clarification": needs_clarification,
        }
    except Exception:
        return None


# ── Intent classifier ─────────────────────────────────────────────────

def classify_intent(
    user_message: str,
    context_messages: List[Dict[str, Any]],
) -> Optional[Dict]:
    """
    Parallel intent classifier. Recognizes cases that regex misses.
    Timeout: 4s. On error: None (graceful degradation).
    Returns: {"intent": "recipe_from_ingredients" | null, "confidence": "high"|"low"}
    """
    ctx_parts = []
    for msg in context_messages[-3:]:
        role = "User" if msg.get("role") == "user" else "Bot"
        content = msg.get("content", "")[:150]
        ctx_parts.append(f"{role}: {content}")
    ctx_str = "\n".join(ctx_parts) if ctx_parts else "(keine Vorgeschichte)"

    prompt = f"""Du klassifizierst eine Nutzerabsicht für einen Trennkost-Bot.

KONTEXT (letzte Nachrichten):
{ctx_str}

AKTUELLE NACHRICHT:
{user_message}

Erkenne NUR diese spezifische Absicht:
"recipe_from_ingredients" – Der Nutzer möchte ein Rezept aus verfügbaren/vorhandenen Zutaten.
Signale: "ich hab nur", "zu Hause", "im Kühlschrank", "aus diesen Zutaten", "mach daraus", "nur das was ich hab", "gerade da", "vorhandene Zutaten", "was kann ich damit machen", "was mach ich damit", "aus dem was ich habe".

PFLICHT-REGEL (mechanisch anwenden, keine Ausnahmen):
Mindestens EIN konkretes Lebensmittel oder eine konkrete Zutat muss in der Nachricht genannt sein.
Ohne konkretes Lebensmittel → intent = null, egal was sonst steht.
Beispiele ohne Lebensmittel → IMMER null:
  "Was kann ich heute essen?", "Was soll ich zum Abendessen machen?", "Was kann ich kochen?",
  "Was gibt es zum Frühstück?", "Was essen wir heute Abend?"

NIEMALS "recipe_from_ingredients" bei:
- Allgemeinen Essensfragen ohne Zutaten: "Was kann ich heute essen?", "Was soll ich abends kochen?"
- Compliance-Fragen: "Ist X ok?", "Ist X in Ordnung?", "Ist X trennkostkonform?", "Darf ich X?", "Kann ich X essen?"
- Zeitliche Trennung: "X vor Y", "erst X dann Y", "X 30 Minuten vor Y"
- Erklärungsfragen: "Warum...?", "Wieso...?", "Was bedeutet...?"
- Rezept-Requests ohne Einschränkung: "Gib mir ein Rezept mit Hähnchen"
- Modifikationsfragen: "aufpeppen", "verbessern", "ergänzen", "was passt dazu", "kann ich X dazu", "das mit X aufpeppen?", "wie kann ich das ergänzen?"
- Kombinationsfragen: "kann ich dazu X essen?", "passt X dazu?", "und mit dem X zusammen?"

Wenn keines der positiven Signale eindeutig vorhanden → intent = null.

Antworte NUR mit JSON, kein Kommentar:
{{"intent": "recipe_from_ingredients" | null, "confidence": "high" | "low"}}"""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=40,
            timeout=4,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()
        result = json.loads(raw)
        if "intent" in result and "confidence" in result:
            print(f"[INTENT] classify_intent → intent={result['intent']!r} confidence={result['confidence']!r}")
            return result
        return None
    except Exception as e:
        print(f"[INTENT] classify_intent failed (non-fatal): {e}")
        return None


# ── Context reference resolution ──────────────────────────────────────

_REF_PATTERN = re.compile(
    r'\b(dazu|damit|zusammen|dazu\s+essen|kombinier)\b', re.IGNORECASE
)


def _extract_foods_ontology(text: str) -> List[str]:
    """
    Fast ontology-based food extraction from text.
    Returns canonical names found in text (no LLM, no side effects).
    """
    from trennkost.ontology import get_ontology
    ont = get_ontology()
    text_lower = text.lower()
    found: List[str] = []
    seen: set = set()
    for entry in ont.entries:
        names_to_check = [entry.canonical] + entry.synonyms
        for name in names_to_check:
            if len(name) < 2:
                continue
            pattern = (
                r'(?<![a-zA-ZäöüÄÖÜß])'
                + re.escape(name.lower())
                + r'(?![a-zA-ZäöüÄÖÜß])'
            )
            if re.search(pattern, text_lower):
                key = entry.canonical.lower()
                if key not in seen:
                    found.append(entry.canonical)
                    seen.add(key)
                break
    return found


def resolve_context_references(
    user_message: str,
    last_messages: List[Dict[str, Any]],
) -> Optional[str]:
    """
    Detects "dazu"/"damit"/"zusammen" in user_message and enriches the query
    with food items from recent conversation history.

    Example: "kann ich dazu Joghurt essen?" → "Joghurt, Haferflocken, Banane"
    Returns: enriched query string or None if no context references found.
    """
    if not _REF_PATTERN.search(user_message):
        return None

    current_foods = _extract_foods_ontology(user_message)

    prev_foods: List[str] = []
    recent = [m for m in last_messages if m.get("content", "").strip() != user_message.strip()]
    for msg in reversed(recent[-3:]):
        items = _extract_foods_ontology(msg.get("content", ""))
        if items:
            prev_foods = items[:5]
            break

    if not prev_foods:
        return None

    seen_keys = {f.lower() for f in current_foods}
    enriched = list(current_foods)
    for food in prev_foods:
        if food.lower() not in seen_keys:
            enriched.append(food)
            seen_keys.add(food.lower())

    if len(enriched) <= len(current_foods):
        return None

    enriched_str = ", ".join(enriched[:6])
    print(f"[CONTEXT_REF] Resolved '{user_message[:60]}' → '{enriched_str}'")
    return enriched_str


# ── Ingredient extraction ─────────────────────────────────────────────

def _llm_extract_ingredients(user_message: str, last_messages: List[Dict[str, Any]]) -> List[str]:
    """
    LLM-based ingredient extraction — extracts ONLY explicitly mentioned items.
    Used instead of ontology substring matching to avoid false positives.
    Returns: list of ingredient names in German, or [] on failure.
    """
    ctx_parts = []
    for msg in last_messages[-4:]:
        if msg.get("role") == "user" and msg.get("content", "").strip() != user_message.strip():
            ctx_parts.append(f"Vorherige Nachricht: {msg.get('content', '')[:200]}")
    ctx_str = "\n".join(ctx_parts) if ctx_parts else ""

    prompt = f"""Extrahiere alle Lebensmittel/Zutaten die der Nutzer explizit als verfügbar erwähnt.
{ctx_str + chr(10) if ctx_str else ""}Aktuelle Nachricht: {user_message}

Gib NUR die Zutaten zurück, kommagetrennt, auf Deutsch, keine Erklärungen.
Nur was explizit erwähnt wird — keine Annahmen, keine Extrapolationen.
Falls keine Zutaten erwähnt: leere Antwort."""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=80,
            timeout=4,
        )
        raw = response.choices[0].message.content.strip()
        if not raw:
            return []
        items = [i.strip() for i in raw.replace(" und ", ", ").split(",") if i.strip() and len(i.strip()) >= 2]
        print(f"[EXTRACT_ING] LLM extracted: {items}")
        return items
    except Exception as e:
        print(f"[EXTRACT_ING] LLM extraction failed: {e}")
        return []


def extract_available_ingredients(
    user_message: str,
    last_messages: List[Dict[str, Any]],
    vision_extraction: Optional[Dict],
) -> List[str]:
    """
    Extract the list of ingredients available to the user.

    Priority:
    1. Vision-extracted items (if image present)
    2. LLM-based extraction from current message + recent history
       (NOT ontology substring matching — too many false positives)

    Returns: deduplicated list. Falls back to [] if nothing found.
    """
    found: List[str] = []
    seen: set = set()

    def _add(items: List[str]):
        for item in items:
            key = item.strip().lower()
            if key and key not in seen:
                found.append(item.strip())
                seen.add(key)

    # 1. Vision extraction (highest priority)
    if vision_extraction and vision_extraction.get("dishes"):
        for dish in vision_extraction["dishes"]:
            _add(dish.get("items", []))

    if len(found) >= 2:
        return found

    # 2. LLM extraction (accurate for explicit ingredient lists)
    _add(_llm_extract_ingredients(user_message, last_messages))

    return found
