"""
Chat mode detection and modifiers.

Central logic for determining how handle_chat() should process a message.
Extracted from the monolithic handle_chat() for clarity.
"""
import re
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

from trennkost.analyzer import detect_food_query, detect_breakfast_context
from trennkost.ontology import get_ontology


class ChatMode(str, Enum):
    KNOWLEDGE = "KNOWLEDGE"
    FOOD_ANALYSIS = "FOOD_ANALYSIS"
    MENU_ANALYSIS = "MENU_ANALYSIS"
    MENU_FOLLOWUP = "MENU_FOLLOWUP"
    RECIPE_REQUEST = "RECIPE_REQUEST"
    RECIPE_FROM_INGREDIENTS = "RECIPE_FROM_INGREDIENTS"


@dataclass
class ChatModifiers:
    is_breakfast: bool = False
    is_followup: bool = False
    vision_failed: bool = False
    needs_clarification: Optional[str] = None
    wants_recipe: bool = False
    is_compliance_check: bool = False
    is_post_analysis_ack: bool = False
    intent_hint: Optional[str] = None


# ── Menu-reference detection ──────────────────────────────────────────

_MENU_REF_PATTERN = re.compile(
    r"(von der |auf der |von dieser )?(speisekarte|karte|menü|menu)"
    r"|ein anderes gericht"
    r"|was anderes (von|auf|aus)"
    r"|gibt.s (noch |auch )?(was|etwas) anderes",
    re.IGNORECASE,
)


def is_menu_reference(text: str) -> bool:
    """Check if user text references a previously sent menu/Speisekarte."""
    return bool(_MENU_REF_PATTERN.search(text))


# ── Recipe-request detection ──────────────────────────────────────────

_RECIPE_REQUEST_PATTERNS = [
    r"rezept",
    r"was.*(kochen|zubereiten|machen)",
    r"was.*kann.*ich.*(kochen|machen|zubereiten|essen)",
    r"was.*soll.*ich.*(kochen|machen|zubereiten|essen)",
    r"was.*kann.*ich.*heute.*(essen|kochen)",
    r"was.*gibt.*es.*zum",
    r"gericht\s*vorschlag",
    r"vorschlag.*gericht",
    r"idee.*zum.*(kochen|essen)",
    r"koch.?idee",
    r"was.*könnte.*ich.*(kochen|machen|essen)",
    r"einkauf",
    r"meal.?prep",
    r"gib.*mir.*(ein|was|gericht)",
    r"hast.*du.*(ein|was|gericht|rezept)",
    r"empfiehl.*mir",
    r"schlage.*mir.*vor",
    r"ich.*will.*was.*(kochen|mit)",
    r"ich.*möchte.*was.*(kochen|mit)",
    r"was.*wäre.*ein.*gutes",
    r"gutes.*gericht",
    r"ein.*gericht.*mit",
    r"schnelles.*gericht",
    r"einfaches.*gericht",
    r"abendessen.*idee",
    r"mittagessen.*idee",
    r"frühstücks?.*idee",
    r"idee.*frühstück",
]

_RECIPE_REQUEST_RE = re.compile(
    "|".join(_RECIPE_REQUEST_PATTERNS), re.IGNORECASE
)


def is_explanation_question(text: str) -> bool:
    """Check if message is an explanation question, not a recipe request."""
    text_lower = text.lower().strip()
    prefix_patterns = [
        r"^(und |aber |also )?(warum|wieso|weshalb)",
        r"^(und |aber |also )?ist (das|es|dies)",
        r"^(und |aber |also )?wie (lange|viel|oft|geht)",
        r"^(und |aber |also )?was (ist|bedeutet|heißt|bringt|passiert)",
        r"^(und |aber |also )?kann (ich|man|das)",
        r"^(und |aber |also )?darf (ich|man|das)",
        r"^(und |aber |also )?muss (ich|man|das)",
        r"^(und |aber |also )?soll (ich|man|das)",
        r"^erkläre",
        r"^erklär",
    ]
    # Trailing compliance patterns: use re.search() so "folgendes rezept konform?" matches
    trailing_compliance = [
        r"trennkost\?",
        r"gesund\?",
        r"\bok\?",
        r"erlaubt\?",
        r"konform\?",
    ]
    if any(re.search(p, text_lower) for p in trailing_compliance):
        return True
    return any(re.match(pattern, text_lower) for pattern in prefix_patterns)


def detect_recipe_compliance(text: str) -> bool:
    """
    Check if user is submitting their own recipe/ingredient list for compliance checking.
    Has priority over detect_recipe_request() to avoid misclassification.
    """
    text_lower = text.lower()
    compliance_signals = [
        "konform", "erlaubt", "passt das", "geht das", "ist das ok",
        "trennkostgerecht", "trennkost-gerecht", "darf ich das", "kann ich das so",
        "war das trennkost", "war das konform",
        "war das rezept", "war das ok", "ist das ok so", "ist das rezept ok",
        "war das in ordnung", "ist das in ordnung",
    ]
    fix_signals = [
        r"was muss ich.*(ändern|anpassen)",
        r"wie.*(konform|trennkost).*machen",
        r"etwas konformes",
    ]
    has_compliance = any(s in text_lower for s in compliance_signals)
    has_fix = any(re.search(p, text_lower) for p in fix_signals)
    if not (has_compliance or has_fix):
        return False
    # Signal 1: "folgendes" + compliance
    if "folgendes" in text_lower:
        return True
    # Signal 2: Structured ingredient list (3+ newlines) + compliance question
    if text_lower.count('\n') >= 3 and (has_compliance or has_fix):
        return True
    # Signal 3: Long pasted recipe (>300 chars) + compliance question
    if len(text) > 300 and has_compliance:
        return True
    # Signal 4: "mein rezept" + compliance
    if "mein rezept" in text_lower and (has_compliance or has_fix):
        return True
    # Signal 5: Comma-separated ingredient list (3+ commas = list of items) + compliance
    if text_lower.count(',') >= 3 and has_compliance:
        return True
    # Signal 6: "ich hab gegessen" / "ich habe gegessen" pattern (past eating) + compliance
    if re.search(r"ich habe? gegessen", text_lower) and has_compliance:
        return True
    return False


def detect_recipe_request(text: str) -> bool:
    """Check if user is requesting a recipe or meal suggestion."""
    # First: exclude explanation questions
    if is_explanation_question(text):
        return False
    return bool(_RECIPE_REQUEST_RE.search(text))


# ── Follow-up suppression ────────────────────────────────────────────

def should_suppress_engine(
    user_message: str,
    is_followup: bool,
    has_image: bool,
    is_menu_ref: bool,
) -> bool:
    """
    In follow-up messages, only re-run engine if actual food items found (2+),
    not just generic keywords like "gericht" or "mahlzeit".
    EXCEPTION: Never suppress for images or menu references.
    """
    if not is_followup or has_image or is_menu_ref:
        return False

    ont = get_ontology()
    words = re.split(r'[,;\s]+', user_message.strip())
    food_count = sum(
        1 for w in words
        if w.strip() and len(w.strip()) >= 3 and ont.lookup(w.strip())
    )
    return food_count < 2


# ── Post-analysis acknowledgement detection ───────────────────────────

_POST_ANALYSIS_ACK_PATTERNS = [
    r"^(ok|okay)[\s!?.]*$",
    r"^(klar|alles klar)[\s!?.]*$",
    r"(macht|macht'?s?) sinn",
    r"^das (ist |macht )?(mir )?(klar|ok|sinn)",
    r"^naja[\s!?,.]",
    r"interessiert mich nicht",
    r"^egal[\s!?.]*$",
    r"^(nicht |kein) (nötig|bedarf)",
    r"^passt[\s!?.]*$",
    r"^gut zu wissen",
    r"^verstanden[\s!?.]*$",
    r"^danke[\s!?.]*$",
]


def detect_post_analysis_followup(
    user_message: str,
    last_messages: List[Dict],
) -> bool:
    """
    Detect when user acknowledged a food analysis verdict
    without picking a fix-direction choice.

    Returns True if:
    - The last assistant message contained a fix-direction offer
    - AND the user response matches an acknowledgement/dismissal pattern
    """
    if not last_messages:
        return False

    # Check recent assistant messages for fix-direction indicators
    for msg in reversed(last_messages[-3:]):
        if msg.get("role") != "assistant":
            continue
        content_lower = msg.get("content", "").lower()
        fix_indicators = ["behalten", "konforme variante", "falls du magst", "was lieber"]
        if not any(ind in content_lower for ind in fix_indicators):
            continue

        # Bot made a fix-direction offer — check if user acknowledged without choosing
        msg_lower = user_message.lower().strip()
        if any(re.search(p, msg_lower) for p in _POST_ANALYSIS_ACK_PATTERNS):
            return True
        break  # Only check the most recent relevant assistant message

    return False


# ── Central mode detection ────────────────────────────────────────────

def _is_recipe_followup(user_message: str, last_messages: List[Dict]) -> bool:
    """
    Check if a short message is a follow-up to a recipe conversation.

    Detects cases like:
    - Bot asked "Welche Zutaten?" → User answers "Kartoffeln"
    - Bot suggested recipes → User says "ja" or "das erste"

    BUT excludes explanation questions like:
    - "und warum trennkost?" → KNOWLEDGE, not recipe request
    - "ist das gesund?" → KNOWLEDGE
    - "wie lange haltbar?" → KNOWLEDGE
    """
    if not last_messages or len(last_messages) < 2:
        return False

    # Check if this is an explanation question ABOUT the recipe, not FOR a recipe
    msg_lower = user_message.lower().strip()
    explanation_patterns = [
        r"^(und |aber |also )?(warum|wieso|weshalb)",
        r"^(und |aber |also )?ist (das|es)",
        r"^(und |aber |also )?wie (lange|viel|oft|geht)",
        r"^(und |aber |also )?was (ist|bedeutet|heißt|passiert)",
        r"^(und |aber |also )?kann (ich|man)",
        r"^(und |aber |also )?darf (ich|man)",
        r"^(und |aber |also )?muss (ich|man)",
        r"^(und |aber |also )?soll (ich|man)",
        r"^erkläre",
        r"^erklär",
        r"trennkost\?$",
        r"gesund\?$",
        r"ok\?$",
        r"erlaubt\?$",
    ]
    if any(re.match(pattern, msg_lower) for pattern in explanation_patterns):
        return False  # It's a question ABOUT the recipe, not a request FOR a recipe

    # Check if recent assistant message mentioned recipes or asked a food-preference clarification
    for msg in reversed(last_messages[-4:]):
        if msg.get("role") == "assistant":
            content_lower = msg.get("content", "").lower()
            if any(kw in content_lower for kw in [
                "rezept", "rezeptdatenbank", "zubereitung",
                "welche zutaten", "was für einen",
                # Bot clarification questions about dinner preferences:
                "art von lebensmittel", "schwebt dir", "passenden vorschlag",
                "vorschlag zu machen", "abendessen vor", "mittagessen vor",
            ]):
                return True
            break  # Only check last assistant message

    return False


def detect_chat_mode(
    user_message: str,
    image_path: Optional[str] = None,
    vision_type: Optional[str] = None,
    is_new_conversation: bool = True,
    recent_message_count: int = 0,
    last_messages: Optional[List[Dict]] = None,
) -> tuple:
    """
    Determine ChatMode and ChatModifiers for a message.

    Priority cascade:
    1. Image + type=="menu" → MENU_ANALYSIS
    2. Image + type=="meal" → FOOD_ANALYSIS
    3. Menu-reference regex → MENU_FOLLOWUP
    4. Recipe intent (explicit or follow-up) → RECIPE_REQUEST
    5. Food query (2+ ontology items or keywords) → FOOD_ANALYSIS
    6. Otherwise → KNOWLEDGE

    Returns: (ChatMode, ChatModifiers)
    """
    modifiers = ChatModifiers()
    modifiers.is_breakfast = detect_breakfast_context(user_message)
    modifiers.is_followup = not is_new_conversation and recent_message_count >= 2

    is_menu_ref = is_menu_reference(user_message)

    # 1. Image + menu
    if image_path and vision_type == "menu":
        return ChatMode.MENU_ANALYSIS, modifiers

    # 2. Image + meal (or any non-menu image)
    if image_path:
        return ChatMode.FOOD_ANALYSIS, modifiers

    # 3. Menu reference in text
    if is_menu_ref:
        return ChatMode.MENU_FOLLOWUP, modifiers

    # 3.5. Compliance check: user submitting own recipe for verification
    # Must run BEFORE recipe-request detection to avoid "rezept" keyword mis-match.
    if detect_recipe_compliance(user_message):
        modifiers.is_compliance_check = True
        return ChatMode.FOOD_ANALYSIS, modifiers

    # 4. Recipe request (explicit keywords)
    if detect_recipe_request(user_message):
        modifiers.wants_recipe = True
        return ChatMode.RECIPE_REQUEST, modifiers

    # 4b. Recipe follow-up (short answer in recipe conversation context)
    if modifiers.is_followup and _is_recipe_followup(user_message, last_messages or []):
        modifiers.wants_recipe = True
        return ChatMode.RECIPE_REQUEST, modifiers

    # 4c. Post-analysis acknowledgement (user got verdict, didn't engage with fix offer)
    if modifiers.is_followup and detect_post_analysis_followup(user_message, last_messages or []):
        modifiers.is_post_analysis_ack = True
        return ChatMode.KNOWLEDGE, modifiers

    # 4d. "zusammen"/"kombinier" with a food → always FOOD_ANALYSIS
    # e.g. "und mit dem obst zusammen?", "kann ich das kombinieren?"
    _ZUSAMMEN_RE = re.compile(r'\b(zusammen|mit\s+\S+\s+essen|kombinier)\b', re.IGNORECASE)
    if _ZUSAMMEN_RE.search(user_message):
        return ChatMode.FOOD_ANALYSIS, modifiers

    # 4e. Timing/wait questions → always KNOWLEDGE
    # e.g. "Wie lange nach dem ersten Frühstück?", "Wie lange warten nach Obst?"
    # These need course-material lookup, not food analysis engine.
    _TIMING_WAIT_RE = re.compile(
        r'\bwie\s+lange\b.{0,60}\b(warten|warte|nach|vor|abstand)\b'
        r'|\bwie\s+lange\s+(muss|soll|kann|darf)\b',
        re.IGNORECASE,
    )
    if _TIMING_WAIT_RE.search(user_message):
        modifiers.is_breakfast = False  # suppress breakfast advice — user wants a timing fact
        return ChatMode.KNOWLEDGE, modifiers

    # 5. Food query detection
    is_food = detect_food_query(user_message)
    if is_food:
        # Check if engine should be suppressed for generic follow-ups
        if should_suppress_engine(user_message, modifiers.is_followup, False, False):
            return ChatMode.KNOWLEDGE, modifiers
        return ChatMode.FOOD_ANALYSIS, modifiers

    # 6. Default
    return ChatMode.KNOWLEDGE, modifiers
