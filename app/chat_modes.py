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


@dataclass
class ChatModifiers:
    is_breakfast: bool = False
    is_followup: bool = False
    vision_failed: bool = False
    needs_clarification: Optional[str] = None
    wants_recipe: bool = False


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
    r"gericht\s*vorschlag",
    r"vorschlag.*gericht",
    r"was.*kann.*ich.*(kochen|machen|zubereiten)",
    r"was.*soll.*ich.*(kochen|machen|zubereiten)",
    r"idee.*zum.*(kochen|essen)",
    r"koch.?idee",
    r"was.*könnte.*ich.*(kochen|machen)",
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
]

_RECIPE_REQUEST_RE = re.compile(
    "|".join(_RECIPE_REQUEST_PATTERNS), re.IGNORECASE
)


def is_explanation_question(text: str) -> bool:
    """Check if message is an explanation question, not a recipe request."""
    text_lower = text.lower().strip()
    explanation_patterns = [
        r"^(und |aber |also )?(warum|wieso|weshalb)",
        r"^ist (das|es|dies)",
        r"^wie (lange|viel|oft|geht)",
        r"^was (ist|bedeutet|heißt|bringt)",
        r"^kann (ich|man|das)",
        r"^darf (ich|man|das)",
        r"^muss (ich|man|das)",
        r"^soll (ich|man|das)",
        r"^erkläre",
        r"^erklär",
        r"trennkost\?$",  # Questions ending with just "trennkost?"
        r"gesund\?$",
        r"ok\?$",
        r"erlaubt\?$",
        r"konform\?$",
    ]
    return any(re.match(pattern, text_lower) for pattern in explanation_patterns)


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
        r"^(und |aber )?(warum|wieso|weshalb)",
        r"^ist (das|es)",
        r"^wie (lange|viel|oft)",
        r"^was (ist|bedeutet|heißt)",
        r"^kann (ich|man)",
        r"^darf (ich|man)",
        r"^erkläre",
        r"^erklär",
        r"trennkost\?$",  # Questions ending with just "trennkost?"
        r"gesund\?$",
        r"ok\?$",
        r"erlaubt\?$",
    ]
    if any(re.match(pattern, msg_lower) for pattern in explanation_patterns):
        return False  # It's a question ABOUT the recipe, not a request FOR a recipe

    # Check if recent assistant message mentioned recipes/Rezept
    for msg in reversed(last_messages[-4:]):
        if msg.get("role") == "assistant":
            content_lower = msg.get("content", "").lower()
            if any(kw in content_lower for kw in [
                "rezept", "rezeptdatenbank", "zubereitung",
                "welche zutaten", "was für einen",
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

    # 4. Recipe request (explicit keywords)
    if detect_recipe_request(user_message):
        modifiers.wants_recipe = True
        return ChatMode.RECIPE_REQUEST, modifiers

    # 4b. Recipe follow-up (short answer in recipe conversation context)
    if modifiers.is_followup and _is_recipe_followup(user_message, last_messages or []):
        modifiers.wants_recipe = True
        return ChatMode.RECIPE_REQUEST, modifiers

    # 5. Food query detection
    is_food = detect_food_query(user_message)
    if is_food:
        # Check if engine should be suppressed for generic follow-ups
        if should_suppress_engine(user_message, modifiers.is_followup, False, False):
            return ChatMode.KNOWLEDGE, modifiers
        return ChatMode.FOOD_ANALYSIS, modifiers

    # 6. Default
    return ChatMode.KNOWLEDGE, modifiers
