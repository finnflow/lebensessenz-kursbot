import asyncio
import json
import os
import re
import time
from typing import AsyncGenerator, Generator, Optional, List, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor

from app.clients import client, MODEL, LAST_N, SUMMARY_THRESHOLD, DISTANCE_THRESHOLD, DEBUG_RAG
from app.rag_service import (
    retrieve_with_fallback,
    build_context,
    rewrite_standalone_query,
    expand_alias_terms,
)
from app.input_service import (
    normalize_input,
    classify_intent,
    classify_food_items,
    extract_available_ingredients,
    resolve_context_references,
    llm_call,
)
from app.recipe_builder import handle_recipe_from_ingredients, format_recipe_directly

from app.database import (
    create_conversation,
    get_conversation,
    create_message,
    get_last_n_messages,
    count_messages_since_cursor,
    get_messages_since_cursor,
    update_summary,
    get_total_message_count,
    update_conversation_title,
    generate_title_from_message,
    conversation_belongs_to_guest,
    set_conversation_start_intent,
)
from app.vision_service import (
    analyze_meal_image,
    categorize_food_groups,
    generate_trennkost_query,
    extract_food_from_image,
    VisionAnalysisError,
)
from trennkost.analyzer import (
    detect_temporal_separation,
    analyze_text as trennkost_analyze_text,
    analyze_vision as trennkost_analyze_vision,
)
from trennkost.formatter import build_rag_query
from trennkost.models import TrennkostResult

from app.chat_modes import ChatMode, ChatModifiers, detect_chat_mode
from app.grounding_policy import (
    FALLBACK_SENTENCE,
    evaluate_grounding_policy,
    should_emit_fallback_sentence,
)
from app.prompt_builder import (
    SYSTEM_INSTRUCTIONS,
    build_base_context,
    build_engine_block,
    build_menu_injection,
    build_vision_failed_block,
    build_vision_legacy_block,
    build_breakfast_block,
    build_menu_followup_block,
    build_post_analysis_ack_block,
    build_recipe_context_block,
    build_prompt_food_analysis,
    build_prompt_vision_legacy,
    build_prompt_knowledge,
    build_prompt_recipe_request,
    assemble_prompt,
    build_ui_intent_block,
)

_LAST_MENU_RESULTS_BY_CONVERSATION: Dict[str, List[TrennkostResult]] = {}


# ── UI intent normalizer ──────────────────────────────────────────────

_UI_INTENT_MAP = {
    "lernen": "learn",
    "essen":  "eat",
    "planen": "plan",
}
_VALID_INTENTS = {"learn", "eat", "need", "plan"}


def normalize_ui_intent(raw: Optional[str]) -> Optional[str]:
    """Normalize a raw UI intent hint to a canonical id or None.

    Canonical ids: learn | eat | need | plan
    """
    if raw is None:
        return None
    s = raw.strip().lower()
    if s in _UI_INTENT_MAP:
        return _UI_INTENT_MAP[s]
    if "was brauche" in s or "bedarf" in s:
        return "need"
    if s in _VALID_INTENTS:
        return s
    return None


_INTENT_TITLES: Dict[str, str] = {
    "eat":   "Essen",
    "learn": "Lernen",
    "need":  "Bedürfnis",
    "plan":  "Planung",
}

_FIRST_QUESTIONS: Dict[str, str] = {
    "eat":   "Bist du im Restaurant oder zu Hause?",
    "need":  "Spürst du den Hunger eher im Bauch oder eher im Kopf?",
    "plan":  "Planst du für heute oder für mehrere Tage?",
    "learn": "Worüber möchtest du mehr verstehen?",
}


def first_question_for_intent(intent: str) -> str:
    """Return the fixed opening question for a given start intent."""
    return _FIRST_QUESTIONS[intent]


# ── Summary helpers ───────────────────────────────────────────────────

def generate_summary(old_summary: Optional[str], new_messages: List[Dict[str, Any]]) -> str:
    """Generate or update rolling summary."""
    context_parts = []

    if old_summary:
        context_parts.append(f"BISHERIGE ZUSAMMENFASSUNG:\n{old_summary}\n")

    context_parts.append("NEUE NACHRICHTEN:")
    for msg in new_messages:
        role = "User" if msg["role"] == "user" else "Assistant"
        context_parts.append(f"{role}: {msg['content']}")

    prompt = f"""{chr(10).join(context_parts)}

Erstelle eine prägnante, sachliche Zusammenfassung der Konversation.
- Maximal 3-4 Sätze
- Konzentriere dich auf die wichtigsten Themen und Fragen
- Keine neuen Fakten hinzufügen
- Deterministisch und sachlich

ZUSAMMENFASSUNG:"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=300,
    )

    return response.choices[0].message.content.strip()


def should_update_summary(conversation_id: str, conv_data: Dict[str, Any]) -> bool:
    """Check if summary should be updated."""
    if not conv_data.get("summary_text"):
        total_msgs = get_total_message_count(conversation_id)
        return total_msgs >= 4
    cursor = conv_data.get("summary_message_cursor", 0)
    new_msg_count = count_messages_since_cursor(conversation_id, cursor)
    return new_msg_count >= SUMMARY_THRESHOLD


def update_conversation_summary(conversation_id: str, conv_data: Dict[str, Any]):
    """Update the rolling summary for a conversation."""
    old_summary = conv_data.get("summary_text")
    cursor = conv_data.get("summary_message_cursor", 0)
    new_messages = get_messages_since_cursor(conversation_id, cursor)
    if not new_messages:
        return
    new_summary = generate_summary(old_summary, new_messages)
    new_cursor = get_total_message_count(conversation_id)
    update_summary(conversation_id, new_summary, new_cursor)


# ── Pipeline steps ────────────────────────────────────────────────────

def _cache_menu_results(
    conversation_id: str,
    mode: ChatMode,
    trennkost_results: Optional[List[TrennkostResult]],
) -> None:
    if mode == ChatMode.MENU_ANALYSIS and trennkost_results:
        _LAST_MENU_RESULTS_BY_CONVERSATION[conversation_id] = list(trennkost_results)


def _get_cached_menu_results(conversation_id: str) -> Optional[List[TrennkostResult]]:
    cached = _LAST_MENU_RESULTS_BY_CONVERSATION.get(conversation_id)
    if not cached:
        return None
    return list(cached)


def _resolve_trennkost_results(
    conversation_id: str,
    analysis_query: str,
    mode: ChatMode,
    vision_extraction: Optional[Dict],
) -> Optional[List[TrennkostResult]]:
    trennkost_results = None
    if mode == ChatMode.MENU_FOLLOWUP:
        trennkost_results = _get_cached_menu_results(conversation_id)
        if trennkost_results:
            print(f"[PIPELINE] MENU_FOLLOWUP reused {len(trennkost_results)} cached menu result(s)")

    if trennkost_results is None:
        trennkost_results = _run_engine(analysis_query, vision_extraction, mode)

    _cache_menu_results(conversation_id, mode, trennkost_results)
    return trennkost_results


def _setup_conversation(
    conversation_id: Optional[str],
    user_message: str,
    guest_id: Optional[str],
    image_path: Optional[str],
    ui_intent: Optional[str] = None,
) -> Tuple[str, bool, Dict[str, Any]]:
    """Create/validate conversation, save user message, generate title."""
    if not conversation_id:
        conversation_id = create_conversation(guest_id=guest_id)
        is_new = True
    else:
        is_new = False

    conv_data = get_conversation(conversation_id)
    if not conv_data:
        raise ValueError(f"Conversation {conversation_id} not found")

    if guest_id and not conversation_belongs_to_guest(conversation_id, guest_id):
        raise ValueError(f"Access denied to conversation {conversation_id}")

    if guest_id and not conv_data.get("guest_id"):
        from app.database import update_conversation_guest_id
        update_conversation_guest_id(conversation_id, guest_id)

    if is_new and ui_intent is not None:
        set_conversation_start_intent(conversation_id, ui_intent)
        conv_data["start_intent"] = ui_intent  # keep in-memory copy consistent

    create_message(conversation_id, "user", user_message, image_path=image_path, intent=ui_intent)

    if is_new:
        title = generate_title_from_message(user_message, max_words=10)
        update_conversation_title(conversation_id, title)

    return conversation_id, is_new, conv_data


def _process_vision(image_path: str, user_message: str) -> Dict[str, Any]:
    """Run vision analysis on an uploaded image."""
    result = {
        "vision_analysis": None,
        "food_groups": None,
        "vision_extraction": None,
        "vision_is_menu": False,
        "vision_failed": False,
    }
    try:
        result["vision_extraction"] = extract_food_from_image(image_path, user_message)
        result["vision_is_menu"] = result["vision_extraction"].get("type") == "menu"
        dishes = result["vision_extraction"].get("dishes", [])
        if not dishes or all(not d.get("items") for d in dishes):
            print(f"[VISION] Warning: extraction returned no usable items from image")
            result["vision_failed"] = True
        else:
            print(f"[VISION] Extracted {len(dishes)} dishes (type={result['vision_extraction'].get('type')})")
        result["vision_analysis"] = analyze_meal_image(image_path, user_message)
        if result["vision_analysis"].get("items"):
            result["food_groups"] = categorize_food_groups(result["vision_analysis"]["items"])
    except VisionAnalysisError as e:
        print(f"[VISION] Analysis failed: {e}")
        result["vision_failed"] = True
    return result


def _run_engine(
    user_message: str,
    vision_extraction: Optional[Dict],
    mode: ChatMode,
) -> Optional[List[TrennkostResult]]:
    """Run Trennkost rule engine if mode requires it."""
    if mode not in (ChatMode.FOOD_ANALYSIS, ChatMode.MENU_ANALYSIS):
        return None

    try:
        if vision_extraction and vision_extraction.get("dishes"):
            return trennkost_analyze_vision(
                vision_extraction["dishes"],
                llm_fn=llm_call,
                mode="strict",
            )
        else:
            return trennkost_analyze_text(
                user_message,
                llm_fn=llm_call,
                mode="strict",
            )
    except Exception as e:
        print(f"Trennkost analysis failed (non-fatal): {e}")
        import traceback
        traceback.print_exc()
        return None


def _build_rag_query(
    trennkost_results: Optional[List[TrennkostResult]],
    food_groups: Optional[Dict],
    image_path: Optional[str],
    summary: Optional[str],
    last_messages: List[Dict[str, Any]],
    user_message: str,
    is_breakfast: bool,
) -> str:
    """Build the RAG query using the most appropriate strategy."""
    if trennkost_results:
        standalone_query = build_rag_query(trennkost_results, breakfast_context=is_breakfast)
    elif image_path and food_groups:
        standalone_query = generate_trennkost_query(food_groups)
    else:
        standalone_query = rewrite_standalone_query(summary, last_messages[:-1], user_message)

    return expand_alias_terms(standalone_query)


def _build_prompt_parts(
    mode: ChatMode,
    modifiers: ChatModifiers,
    trennkost_results: Optional[List[TrennkostResult]],
    vision_data: Dict[str, Any],
    summary: Optional[str],
    last_messages: List[Dict[str, Any]],
    user_message: str,
    recipe_results: Optional[List[Dict]] = None,
    ui_intent: Optional[str] = None,
) -> Tuple[List[str], str]:
    """Build all prompt parts and answer instructions based on mode."""
    parts = build_ui_intent_block(ui_intent)  # prepend intent hint (empty list if no intent)
    parts += build_base_context(summary, last_messages)

    if trennkost_results:
        parts.extend(build_engine_block(trennkost_results, modifiers.is_breakfast))
        if vision_data.get("vision_is_menu"):
            parts.extend(build_menu_injection(trennkost_results))

    image_path = bool(vision_data.get("vision_extraction") or vision_data.get("vision_failed"))
    if image_path and vision_data.get("vision_failed") and not trennkost_results:
        parts.extend(build_vision_failed_block())

    if vision_data.get("vision_analysis") and not trennkost_results and not vision_data.get("vision_failed"):
        parts.extend(build_vision_legacy_block(vision_data["vision_analysis"]))

    if modifiers.is_breakfast and not trennkost_results:
        parts.extend(build_breakfast_block())

    if mode == ChatMode.MENU_FOLLOWUP and not trennkost_results:
        parts.extend(build_menu_followup_block())

    if modifiers.is_post_analysis_ack:
        parts.extend(build_post_analysis_ack_block())

    if mode == ChatMode.RECIPE_REQUEST and recipe_results:
        parts.extend(build_recipe_context_block(recipe_results))

    if trennkost_results:
        answer_instructions = build_prompt_food_analysis(
            trennkost_results, user_message, modifiers.is_breakfast,
            is_compliance_check=modifiers.is_compliance_check,
        )
    elif mode == ChatMode.RECIPE_REQUEST:
        answer_instructions = build_prompt_recipe_request(
            recipe_results or [], user_message, modifiers.is_breakfast
        )
    elif vision_data.get("vision_analysis") and not vision_data.get("vision_failed"):
        answer_instructions = build_prompt_vision_legacy(user_message)
    else:
        answer_instructions = build_prompt_knowledge(
            user_message, modifiers.is_breakfast
        )

    return parts, answer_instructions


def _generate_and_save(
    conversation_id: str,
    llm_input: str,
    mode: "ChatMode" = None,
    recipe_results: Optional[List[Dict]] = None,
    ui_intent: Optional[str] = None,
) -> str:
    """
    Call LLM and save the response.

    Special case: For recipe requests with high-score matches (≥7.0),
    bypass LLM and format recipe directly to avoid unwanted follow-up questions.
    """
    if mode and recipe_results:
        if mode == ChatMode.RECIPE_REQUEST and recipe_results[0].get('score', 0.0) >= 7.0:
            assistant_message = format_recipe_directly(recipe_results[0])
            create_message(conversation_id, "assistant", assistant_message, intent=ui_intent)
            print(f"[PIPELINE] High-score recipe (≥7.0) → direct output bypass")
            return assistant_message

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_INSTRUCTIONS},
            {"role": "user", "content": llm_input}
        ],
        temperature=0.0,
    )
    assistant_message = response.choices[0].message.content.strip()
    create_message(conversation_id, "assistant", assistant_message, intent=ui_intent)
    return assistant_message


def _prepare_sources(metas: List[Dict], dists: List[float]) -> List[Dict]:
    """Prepare source metadata for response."""
    sources = []
    for m, d in zip(metas, dists):
        sources.append({
            "path": m.get("path"),
            "source": m.get("source"),
            "page": m.get("page"),
            "chunk": m.get("chunk"),
            "distance": d,
            "module_id": m.get("module_id"),
            "module_label": m.get("module_label"),
            "submodule_id": m.get("submodule_id"),
            "submodule_label": m.get("submodule_label"),
        })
    return sources


# ── Dispatcher helpers ────────────────────────────────────────────────

def _handle_temporal_separation(
    normalized_message: str,
    conversation_id: str,
    ui_intent: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Return a response dict if 'X 30 min vor Y' pattern is detected, else None.
    Runs before intent override so temporal queries never reach the engine.
    """
    temporal_sep = detect_temporal_separation(normalized_message)
    if not (temporal_sep and temporal_sep["is_temporal"]):
        return None

    print(f"[PIPELINE] Temporal separation detected: {temporal_sep}")
    first  = ", ".join(temporal_sep["first_foods"])
    second = ", ".join(temporal_sep["second_foods"])
    wait   = temporal_sep.get("wait_time")

    text  = f"Ja, das ist **trennkost-konform**! 🎉\n\n"
    text += f"Du isst {first} **zuerst allein** und wartest "
    text += (f"**{wait} Minuten**, " if wait else "")
    text += f"bevor du {second} isst. Das ist sequenzielles Essen und **völlig in Ordnung**!\n\n"
    text += "**Wichtige Wartezeiten nach Obst:**\n"
    text += "- Wasserreiche Früchte (Melone, Orangen): 20-30 Min\n"
    text += "- Äpfel, Birnen, Beeren: 30-45 Min\n"
    text += "- Bananen, Trockenobst: 45-60 Min\n\n"
    if wait and wait >= 30:
        text += f"✅ Deine {wait} Minuten Wartezeit sind perfekt für die meisten Früchte!"
    elif wait and wait < 30:
        text += f"⚠️ Hinweis: {wait} Min könnten bei manchen Früchten knapp sein. Optimal sind 30-45 Min."
    else:
        text += "💡 Achte auf die richtigen Wartezeiten, dann ist die Trennung optimal!"

    create_message(conversation_id, "assistant", text, intent=ui_intent)
    return {"answer": text, "conversationId": conversation_id}


def _apply_intent_override(
    mode: ChatMode,
    modifiers: ChatModifiers,
    intent_result: Optional[Dict],
    image_path: Optional[str],
) -> ChatMode:
    """
    Override mode to RECIPE_FROM_INGREDIENTS when intent classifier is confident.
    Guard: only overrides KNOWLEDGE or RECIPE_REQUEST, or FOOD_ANALYSIS without
    a compliance-check and without an image.
    """
    _can_override_food = (
        mode == ChatMode.FOOD_ANALYSIS
        and not modifiers.is_compliance_check
        and not image_path
    )
    if (
        intent_result
        and intent_result.get("intent") == "recipe_from_ingredients"
        and intent_result.get("confidence") == "high"
        and (mode in (ChatMode.KNOWLEDGE, ChatMode.RECIPE_REQUEST) or _can_override_food)
    ):
        modifiers.intent_hint = "recipe_from_ingredients"
        print(f"[INTENT] Override → RECIPE_FROM_INGREDIENTS")
        return ChatMode.RECIPE_FROM_INGREDIENTS
    return mode


def _handle_recipe_from_ingredients_mode(
    conversation_id: str,
    normalized_message: str,
    recent: List[Dict],
    vision_data: Dict[str, Any],
    mode: ChatMode,
    modifiers: ChatModifiers,
    is_new: bool,
    conv_data: Dict[str, Any],
    image_path: Optional[str],
    ui_intent: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Handle RECIPE_FROM_INGREDIENTS mode.
    Falls back to RECIPE_REQUEST (no ingredients found) or FOOD_ANALYSIS
    (only a generic term like 'Obst') when extraction fails.
    """
    available_ingredients = extract_available_ingredients(
        normalized_message, recent, vision_data.get("vision_extraction")
    )

    if not available_ingredients:
        print(f"[PIPELINE] RECIPE_FROM_INGREDIENTS: no ingredients found → RECIPE_REQUEST")
        modifiers.wants_recipe = True
        return _handle_recipe_request(
            conversation_id, normalized_message, recent, vision_data,
            ChatMode.RECIPE_REQUEST, modifiers, is_new, conv_data, image_path,
            ui_intent=ui_intent,
        )

    _GENERIC = {"obst", "gemüse", "lebensmittel", "essen", "zutaten", "früchte", "beeren"}
    if len(available_ingredients) == 1 and available_ingredients[0].strip().lower() in _GENERIC:
        print(f"[PIPELINE] RECIPE_FROM_INGREDIENTS: only generic term ({available_ingredients}) → FOOD_ANALYSIS")
        return _handle_food_analysis(
            conversation_id, normalized_message, recent, vision_data,
            ChatMode.FOOD_ANALYSIS, modifiers, is_new, conv_data, image_path,
            ui_intent=ui_intent,
        )

    print(f"[PIPELINE] RECIPE_FROM_INGREDIENTS | ingredients={available_ingredients[:5]}")
    response = handle_recipe_from_ingredients(
        conversation_id, available_ingredients, modifiers.is_breakfast
    )
    conv_data_updated = get_conversation(conversation_id)
    if should_update_summary(conversation_id, conv_data_updated):
        update_conversation_summary(conversation_id, conv_data_updated)
    return {"conversationId": conversation_id, "answer": response, "sources": []}


def _prepare_analysis_query(
    normalized_message: str,
    recent: List[Dict[str, Any]],
    mode: ChatMode,
) -> str:
    """Share the existing FOOD_ANALYSIS context-reference resolver path."""
    if mode != ChatMode.FOOD_ANALYSIS:
        return normalized_message

    resolved = resolve_context_references(normalized_message, recent)
    return resolved or normalized_message


def _handle_food_analysis(
    conversation_id: str,
    normalized_message: str,
    recent: List[Dict],
    vision_data: Dict[str, Any],
    mode: ChatMode,
    modifiers: ChatModifiers,
    is_new: bool,
    conv_data: Dict[str, Any],
    image_path: Optional[str],
    ui_intent: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Steps 3e + 4: context-reference resolution, Trennkost engine, then finalize.
    Handles FOOD_ANALYSIS, MENU_ANALYSIS, MENU_FOLLOWUP.
    """
    analysis_query = _prepare_analysis_query(normalized_message, recent, mode)

    trennkost_results = _resolve_trennkost_results(
        conversation_id=conversation_id,
        analysis_query=analysis_query,
        mode=mode,
        vision_extraction=vision_data.get("vision_extraction"),
    )

    if DEBUG_RAG and trennkost_results:
        for r in trennkost_results:
            print(f"[TRENNKOST] {r.dish_name}: {r.verdict.value} | "
                  f"problems={len(r.problems)} | questions={len(r.required_questions)}")

    return _finalize_response(
        conversation_id, normalized_message, vision_data, mode, modifiers,
        is_new, conv_data, image_path,
        trennkost_results=trennkost_results,
        analysis_query=analysis_query,
        ui_intent=ui_intent,
    )


def _handle_recipe_request(
    conversation_id: str,
    normalized_message: str,
    recent: List[Dict],
    vision_data: Dict[str, Any],
    mode: ChatMode,
    modifiers: ChatModifiers,
    is_new: bool,
    conv_data: Dict[str, Any],
    image_path: Optional[str],
    ui_intent: Optional[str] = None,
) -> Dict[str, Any]:
    """Step 5: recipe search, then finalize."""
    recipe_results: List[Dict] = []
    try:
        from app.recipe_service import search_recipes
        search_query = normalized_message
        if modifiers.is_followup and len(normalized_message.strip()) <= 20:
            for msg in reversed(recent):
                if msg.get("role") == "user":
                    content = msg.get("content", "").strip()
                    if len(content) > 20 and content != normalized_message:
                        search_query = content
                        print(f"[PIPELINE] Short follow-up → previous query: '{search_query[:50]}...'")
                        break
        recipe_results = search_recipes(search_query, limit=5)
        print(f"[PIPELINE] recipe_results={len(recipe_results)} recipes found")
        for r in recipe_results[:3]:
            print(f"  → {r['name']} ({r['trennkost_category']}) score={r.get('score', '?')}")
    except Exception as e:
        print(f"[PIPELINE] recipe search failed: {e}")

    return _finalize_response(
        conversation_id, normalized_message, vision_data, mode, modifiers,
        is_new, conv_data, image_path,
        recipe_results=recipe_results,
        ui_intent=ui_intent,
    )


def _handle_knowledge_mode(
    conversation_id: str,
    normalized_message: str,
    recent: List[Dict],
    vision_data: Dict[str, Any],
    mode: ChatMode,
    modifiers: ChatModifiers,
    is_new: bool,
    conv_data: Dict[str, Any],
    image_path: Optional[str],
    ui_intent: Optional[str] = None,
) -> Dict[str, Any]:
    """Pure RAG path for KNOWLEDGE mode (and any unrecognized mode)."""
    return _finalize_response(
        conversation_id, normalized_message, vision_data, mode, modifiers,
        is_new, conv_data, image_path,
        ui_intent=ui_intent,
    )


def _finalize_response(
    conversation_id: str,
    normalized_message: str,
    vision_data: Dict[str, Any],
    mode: ChatMode,
    modifiers: ChatModifiers,
    is_new: bool,
    conv_data: Dict[str, Any],
    image_path: Optional[str],
    trennkost_results: Optional[List[TrennkostResult]] = None,
    recipe_results: Optional[List[Dict]] = None,
    analysis_query: Optional[str] = None,
    ui_intent: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Steps 6–11 — shared by all mode handlers:
    RAG retrieval, fallback check, prompt assembly, LLM call,
    summary update, source preparation.
    """
    if analysis_query is None:
        analysis_query = normalized_message

    summary      = conv_data.get("summary_text")
    last_messages = get_last_n_messages(conversation_id, LAST_N)

    # 6. Build RAG query + retrieve
    standalone_query = _build_rag_query(
        trennkost_results, vision_data.get("food_groups"),
        image_path, summary, last_messages, normalized_message,
        modifiers.is_breakfast,
    )

    needs_clarification = None
    is_followup = not is_new and len(last_messages) >= 2
    if not trennkost_results:
        food_cls = classify_food_items(normalized_message, standalone_query)
        if food_cls:
            classification = food_cls.get("classification", "")
            if not is_followup or len(normalized_message) > 80:
                needs_clarification = food_cls.get("needs_clarification")
            if classification:
                standalone_query += f"\n{classification}"

    if DEBUG_RAG:
        print(f"\n[RAG] Primary query: {standalone_query}")

    docs, metas, dists, is_partial = retrieve_with_fallback(standalone_query, normalized_message)

    if DEBUG_RAG:
        print(f"[RAG] Retrieved {len(docs)} chunk(s) | partial={is_partial}")
        for i, (_, meta, dist) in enumerate(list(zip(docs, metas, dists))[:3], 1):
            print(f"  {i}. path={meta.get('path','?')} | page={meta.get('page','?')} | chunk={meta.get('chunk','?')} | dist={dist:.3f}")

    course_context = build_context(docs, metas)

    # 7. Fallback check
    best_dist = min(dists) if dists else 999.0
    grounding_decision = evaluate_grounding_policy(
        trennkost_results=trennkost_results,
        mode=mode,
        best_dist=best_dist,
        is_partial=is_partial,
        course_context=course_context,
        ui_intent=ui_intent,
        distance_threshold=DISTANCE_THRESHOLD,
    )
    if should_emit_fallback_sentence(grounding_decision):
        create_message(conversation_id, "assistant", FALLBACK_SENTENCE, intent=ui_intent)
        conv_data_updated = get_conversation(conversation_id)
        if should_update_summary(conversation_id, conv_data_updated):
            update_conversation_summary(conversation_id, conv_data_updated)
        return {"conversationId": conversation_id, "answer": FALLBACK_SENTENCE, "sources": []}

    # 8. Build prompt
    prompt_parts, answer_instructions = _build_prompt_parts(
        mode, modifiers, trennkost_results, vision_data,
        summary, last_messages, analysis_query, recipe_results,
        ui_intent=ui_intent,
    )
    modifiers.needs_clarification = needs_clarification
    llm_input = assemble_prompt(
        prompt_parts, course_context, normalized_message,
        answer_instructions, needs_clarification,
    )

    # 9. Generate + save
    assistant_message = _generate_and_save(conversation_id, llm_input, mode, recipe_results, ui_intent)

    # 10. Update summary
    conv_data_updated = get_conversation(conversation_id)
    if should_update_summary(conversation_id, conv_data_updated):
        update_conversation_summary(conversation_id, conv_data_updated)

    start_intent = (conv_data or {}).get("start_intent")
    sources_out = _prepare_sources(metas, dists) if start_intent == "learn" else []

    return {
        "conversationId": conversation_id,
        "answer": assistant_message,
        "sources": sources_out,
    }


# ── Main pipeline ─────────────────────────────────────────────────────

def handle_chat(
    conversation_id: Optional[str],
    user_message: str,
    guest_id: Optional[str] = None,
    image_path: Optional[str] = None,
    intent: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Chat request dispatcher.

    Pre-processes input (normalize + intent + vision in parallel),
    detects the chat mode, then delegates to the appropriate handler:

      RECIPE_FROM_INGREDIENTS → _handle_recipe_from_ingredients_mode()
      FOOD_ANALYSIS / MENU_*  → _handle_food_analysis()
      RECIPE_REQUEST          → _handle_recipe_request()
      KNOWLEDGE / fallback    → _handle_knowledge_mode()

    All handlers converge in _finalize_response() (steps 6–11).
    """
    # ── 1. Setup ──────────────────────────────────────────────────────
    ui_intent = normalize_ui_intent(intent)

    # ── Intent shortcut: empty message + valid intent → first question ──
    # Returns a fixed opening question without any LLM call or user message row.
    if user_message.strip() == "" and ui_intent in _VALID_INTENTS:
        if not conversation_id:
            conversation_id = create_conversation(guest_id=guest_id)
        if guest_id and not conversation_belongs_to_guest(conversation_id, guest_id):
            raise ValueError(f"Access denied to conversation {conversation_id}")
        set_conversation_start_intent(conversation_id, ui_intent)
        update_conversation_title(conversation_id, _INTENT_TITLES.get(ui_intent, ui_intent))
        question = first_question_for_intent(ui_intent)
        create_message(conversation_id, "assistant", question, intent=ui_intent)
        return {"conversationId": conversation_id, "answer": question, "sources": []}

    conversation_id, is_new, conv_data = _setup_conversation(
        conversation_id, user_message, guest_id, image_path, ui_intent=ui_intent
    )
    recent = get_last_n_messages(conversation_id, 4)

    # ── 2. Parallel: normalize + intent (+ vision if image) ───────────
    vision_data: Dict[str, Any] = {
        "vision_analysis": None, "food_groups": None,
        "vision_extraction": None, "vision_is_menu": False, "vision_failed": False,
    }
    with ThreadPoolExecutor(max_workers=3 if image_path else 2) as ex:
        nf  = ex.submit(normalize_input, user_message, recent, is_new)
        inf = ex.submit(classify_intent, user_message, recent)
        vf  = ex.submit(_process_vision, image_path, user_message) if image_path else None
        normalized_message = nf.result()
        intent_result      = inf.result()
        if vf:
            vision_data = vf.result()
    label = "normalization + intent" + (" + vision" if image_path else "")
    print(f"[PIPELINE] Parallel execution: {label} completed")

    # ── 3. Mode detection ─────────────────────────────────────────────
    vision_type = (vision_data.get("vision_extraction") or {}).get("type")
    mode, modifiers = detect_chat_mode(
        normalized_message, image_path=image_path, vision_type=vision_type,
        is_new_conversation=is_new, recent_message_count=len(recent),
        last_messages=recent,
    )
    modifiers.vision_failed = vision_data.get("vision_failed", False)

    # ── 3b. Temporal separation shortcut ─────────────────────────────
    early = _handle_temporal_separation(normalized_message, conversation_id, ui_intent)
    if early:
        return early

    # ── 3c. Intent override ───────────────────────────────────────────
    mode = _apply_intent_override(mode, modifiers, intent_result, image_path)
    print(f"[PIPELINE] mode={mode.value} | is_breakfast={modifiers.is_breakfast} | wants_recipe={modifiers.wants_recipe}")

    # ── 4. Dispatch ───────────────────────────────────────────────────
    ctx = (conversation_id, normalized_message, recent, vision_data, mode, modifiers, is_new, conv_data, image_path)
    if mode == ChatMode.RECIPE_FROM_INGREDIENTS:
        return _handle_recipe_from_ingredients_mode(*ctx, ui_intent=ui_intent)
    if mode in (ChatMode.FOOD_ANALYSIS, ChatMode.MENU_ANALYSIS, ChatMode.MENU_FOLLOWUP):
        return _handle_food_analysis(*ctx, ui_intent=ui_intent)
    if mode == ChatMode.RECIPE_REQUEST:
        return _handle_recipe_request(*ctx, ui_intent=ui_intent)
    return _handle_knowledge_mode(*ctx, ui_intent=ui_intent)


# ── SSE streaming ─────────────────────────────────────────────────────

def _sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _prepare_stream(
    conversation_id: Optional[str],
    user_message: str,
    guest_id: Optional[str],
    ui_intent: Optional[str],
) -> Dict[str, Any]:
    """
    Run the full pipeline up to (but not including) the LLM call.

    Returns either:
      {"conversation_id": ..., "early_answer": ..., "sources": [...], "ui_intent": ...}
      {"conversation_id": ..., "llm_input": ..., "ui_intent": ..., "mode": ...,
       "recipe_results": ..., "sources": [...]}
    """
    conversation_id, is_new, conv_data = _setup_conversation(
        conversation_id, user_message, guest_id, image_path=None, ui_intent=ui_intent
    )
    recent = get_last_n_messages(conversation_id, 4)

    with ThreadPoolExecutor(max_workers=2) as ex:
        nf = ex.submit(normalize_input, user_message, recent, is_new)
        inf = ex.submit(classify_intent, user_message, recent)
        normalized_message = nf.result()
        intent_result = inf.result()

    vision_data: Dict[str, Any] = {
        "vision_analysis": None, "food_groups": None,
        "vision_extraction": None, "vision_is_menu": False, "vision_failed": False,
    }

    mode, modifiers = detect_chat_mode(
        normalized_message, image_path=None, vision_type=None,
        is_new_conversation=is_new, recent_message_count=len(recent),
        last_messages=recent,
    )

    early = _handle_temporal_separation(normalized_message, conversation_id, ui_intent)
    if early:
        return {"conversation_id": conversation_id, "early_answer": early["answer"],
                "sources": [], "ui_intent": ui_intent}

    mode = _apply_intent_override(mode, modifiers, intent_result, image_path=None)

    # RECIPE_FROM_INGREDIENTS: run synchronously (no streaming path for this mode)
    if mode == ChatMode.RECIPE_FROM_INGREDIENTS:
        result = _handle_recipe_from_ingredients_mode(
            conversation_id, normalized_message, recent, vision_data,
            mode, modifiers, is_new, conv_data, image_path=None, ui_intent=ui_intent,
        )
        return {"conversation_id": conversation_id, "early_answer": result["answer"],
                "sources": result.get("sources", []), "ui_intent": ui_intent}

    # Food analysis: run engine if applicable
    analysis_query = _prepare_analysis_query(normalized_message, recent, mode)
    trennkost_results = None
    if mode in (ChatMode.FOOD_ANALYSIS, ChatMode.MENU_ANALYSIS, ChatMode.MENU_FOLLOWUP):
        trennkost_results = _resolve_trennkost_results(
            conversation_id=conversation_id,
            analysis_query=analysis_query,
            mode=mode,
            vision_extraction=None,
        )

    # Recipe search
    recipe_results: Optional[List[Dict]] = None
    if mode == ChatMode.RECIPE_REQUEST:
        try:
            from app.recipe_service import search_recipes
            search_query = normalized_message
            if modifiers.is_followup and len(normalized_message.strip()) <= 20:
                for msg in reversed(recent):
                    if msg.get("role") == "user":
                        content = msg.get("content", "").strip()
                        if len(content) > 20 and content != normalized_message:
                            search_query = content
                            break
            recipe_results = search_recipes(search_query, limit=5)
        except Exception:
            recipe_results = []
        # High-score recipe bypass: format directly, persist, return as early_answer
        if recipe_results and recipe_results[0].get("score", 0.0) >= 7.0:
            assistant_message = format_recipe_directly(recipe_results[0])
            create_message(conversation_id, "assistant", assistant_message, intent=ui_intent)
            return {"conversation_id": conversation_id, "early_answer": assistant_message,
                    "sources": [], "ui_intent": ui_intent}

    # RAG
    summary = conv_data.get("summary_text")
    last_messages = get_last_n_messages(conversation_id, LAST_N)
    standalone_query = _build_rag_query(
        trennkost_results, None, None, summary, last_messages, normalized_message,
        modifiers.is_breakfast,
    )

    needs_clarification = None
    is_followup = not is_new and len(last_messages) >= 2
    if not trennkost_results:
        food_cls = classify_food_items(normalized_message, standalone_query)
        if food_cls:
            classification = food_cls.get("classification", "")
            if not is_followup or len(normalized_message) > 80:
                needs_clarification = food_cls.get("needs_clarification")
            if classification:
                standalone_query += f"\n{classification}"

    docs, metas, dists, is_partial = retrieve_with_fallback(standalone_query, normalized_message)
    course_context = build_context(docs, metas)

    best_dist = min(dists) if dists else 999.0
    grounding_decision = evaluate_grounding_policy(
        trennkost_results=trennkost_results,
        mode=mode,
        best_dist=best_dist,
        is_partial=is_partial,
        course_context=course_context,
        ui_intent=ui_intent,
        distance_threshold=DISTANCE_THRESHOLD,
    )
    if should_emit_fallback_sentence(grounding_decision):
        create_message(conversation_id, "assistant", FALLBACK_SENTENCE, intent=ui_intent)
        conv_data_updated = get_conversation(conversation_id)
        if should_update_summary(conversation_id, conv_data_updated):
            update_conversation_summary(conversation_id, conv_data_updated)
        return {"conversation_id": conversation_id, "early_answer": FALLBACK_SENTENCE,
                "sources": [], "ui_intent": ui_intent}

    prompt_parts, answer_instructions = _build_prompt_parts(
        mode, modifiers, trennkost_results, vision_data,
        summary, last_messages, analysis_query, recipe_results,
        ui_intent=ui_intent,
    )
    modifiers.needs_clarification = needs_clarification
    llm_input = assemble_prompt(
        prompt_parts, course_context, normalized_message,
        answer_instructions, needs_clarification,
    )

    start_intent = (conv_data or {}).get("start_intent")
    sources = _prepare_sources(metas, dists) if start_intent == "learn" else []

    return {
        "conversation_id": conversation_id,
        "llm_input": llm_input,
        "ui_intent": ui_intent,
        "mode": mode,
        "recipe_results": recipe_results,
        "sources": sources,
    }


def handle_chat_stream(
    conversation_id: Optional[str],
    user_message: str,
    guest_id: Optional[str] = None,
    intent: Optional[str] = None,
) -> Generator[str, None, None]:
    """
    Sync generator yielding SSE-formatted strings.

    Event sequence:
      meta → delta* → final     (normal LLM path)
      meta → final              (shortcut / early return)
      error                     (on failure before conv_id known)
      meta → error              (on failure after conv_id known)
    """
    ui_intent = normalize_ui_intent(intent)

    # ── Intent shortcut: empty message + valid intent ──────────────────
    if user_message.strip() == "" and ui_intent in _VALID_INTENTS:
        try:
            if not conversation_id:
                conversation_id = create_conversation(guest_id=guest_id)
            if guest_id and not conversation_belongs_to_guest(conversation_id, guest_id):
                yield _sse("error", {"message": "Zugriff verweigert."})
                return
            set_conversation_start_intent(conversation_id, ui_intent)
            update_conversation_title(conversation_id, _INTENT_TITLES.get(ui_intent, ui_intent))
            question = first_question_for_intent(ui_intent)
            create_message(conversation_id, "assistant", question, intent=ui_intent)
            yield _sse("meta", {"conversationId": conversation_id})
            yield _sse("final", {"conversationId": conversation_id,
                                  "answer": question, "sources": []})
        except Exception as exc:
            print(f"[STREAM] Shortcut error: {exc}")
            yield _sse("error", {"message": "Etwas ist schiefgelaufen."})
        return

    # ── Normal path: ensure conversation ID, yield meta immediately ───
    try:
        if not conversation_id:
            conversation_id = create_conversation(guest_id=guest_id)
            if ui_intent is not None:
                set_conversation_start_intent(conversation_id, ui_intent)
        elif guest_id and not conversation_belongs_to_guest(conversation_id, guest_id):
            yield _sse("error", {"message": "Zugriff verweigert."})
            return
    except Exception as exc:
        print(f"[STREAM] Conversation setup failed: {exc}")
        yield _sse("error", {"message": "Etwas ist schiefgelaufen."})
        return

    meta_payload: Dict[str, Any] = {"conversationId": conversation_id}
    if ui_intent is not None:
        meta_payload["start_intent"] = ui_intent
    yield _sse("meta", meta_payload)
    meta_sent_at = time.monotonic()
    status_sent = 0

    # ── Normal path: prepare pipeline ─────────────────────────────────
    try:
        prep = _prepare_stream(conversation_id, user_message, guest_id, ui_intent)
    except Exception as exc:
        print(f"[STREAM] Prepare failed: {exc}")
        yield _sse("error", {"message": "Etwas ist schiefgelaufen."})
        return

    conv_id = prep["conversation_id"]

    # Early return (temporal, recipe bypass, fallback, recipe-from-ingredients)
    if "early_answer" in prep:
        yield _sse("final", {"conversationId": conv_id,
                              "answer": prep["early_answer"],
                              "sources": prep.get("sources", [])})
        return

    # ── LLM streaming ────────────────────────────────────────────────
    sources = prep.get("sources", [])
    full_text = ""
    first_token_seen = False
    try:
        stream = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                {"role": "user", "content": prep["llm_input"]},
            ],
            temperature=0.0,
            stream=True,
        )
        for chunk in stream:
            if not first_token_seen and status_sent < 2:
                elapsed = time.monotonic() - meta_sent_at
                if elapsed >= 6.0:
                    yield _sse("status", {"message": "Formuliere Antwort \u2026"})
                    status_sent = 2
                elif elapsed >= 2.5 and status_sent < 1:
                    yield _sse("status", {"message": "Suche passende Kursstellen \u2026"})
                    status_sent = 1
            if not chunk.choices:
                continue
            token = chunk.choices[0].delta.content
            if token:
                first_token_seen = True
                full_text += token
                yield _sse("delta", {"text": token})
    except Exception as exc:
        print(f"[STREAM] LLM error: {exc}")
        yield _sse("error", {"message": "Antwort konnte nicht generiert werden."})
        return

    # ── Persist exactly once ──────────────────────────────────────────
    assistant_message = full_text.strip()
    create_message(conv_id, "assistant", assistant_message, intent=prep.get("ui_intent"))
    conv_data_updated = get_conversation(conv_id)
    if conv_data_updated and should_update_summary(conv_id, conv_data_updated):
        update_conversation_summary(conv_id, conv_data_updated)

    yield _sse("final", {"conversationId": conv_id,
                          "answer": assistant_message,
                          "sources": sources})


# ---------------------------------------------------------------------------
# Dev-only knob: STREAM_TEST_DELAY_BEFORE_FIRST_TOKEN=<seconds>
# Inserts an artificial sleep AFTER the pipeline but BEFORE the LLM stream so
# the status-event ticker fires during tests even when retrieval is fast.
# ---------------------------------------------------------------------------

_STREAM_TEST_DELAY = float(os.getenv("STREAM_TEST_DELAY_BEFORE_FIRST_TOKEN", "0"))


async def handle_chat_stream_async(
    conversation_id: Optional[str],
    user_message: str,
    guest_id: Optional[str] = None,
    intent: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """
    Async SSE generator.  Status events are emitted by a time-based asyncio
    ticker that is fully independent of OpenAI token chunk arrival.

    Event sequence (same contract as the sync version):
      meta → status* → delta* → final   (normal LLM path)
      meta → final                       (shortcut / early return)
      error                              (failure before conv_id known)
      meta → error                       (failure after conv_id known)
    """
    ui_intent = normalize_ui_intent(intent)
    loop = asyncio.get_running_loop()

    # ── Intent shortcut: empty message + valid intent ──────────────────────
    if user_message.strip() == "" and ui_intent in _VALID_INTENTS:
        try:
            if not conversation_id:
                conversation_id = await loop.run_in_executor(
                    None, create_conversation, guest_id
                )
            if guest_id:
                belongs = await loop.run_in_executor(
                    None, conversation_belongs_to_guest, conversation_id, guest_id
                )
                if not belongs:
                    yield _sse("error", {"message": "Zugriff verweigert."})
                    return
            await loop.run_in_executor(
                None, set_conversation_start_intent, conversation_id, ui_intent
            )
            await loop.run_in_executor(
                None,
                update_conversation_title,
                conversation_id,
                _INTENT_TITLES.get(ui_intent, ui_intent),
            )
            question = first_question_for_intent(ui_intent)
            _cid = conversation_id
            _q = question
            _ui = ui_intent
            await loop.run_in_executor(
                None,
                lambda: create_message(_cid, "assistant", _q, intent=_ui),
            )
            yield _sse("meta", {"conversationId": conversation_id})
            yield _sse("final", {
                "conversationId": conversation_id,
                "answer": question,
                "sources": [],
            })
        except Exception as exc:
            print(f"[STREAM] Shortcut error: {exc}")
            yield _sse("error", {"message": "Etwas ist schiefgelaufen."})
        return

    # ── Normal path: ensure conversation ID, yield meta immediately ────────
    try:
        if not conversation_id:
            conversation_id = await loop.run_in_executor(
                None, create_conversation, guest_id
            )
            if ui_intent is not None:
                await loop.run_in_executor(
                    None, set_conversation_start_intent, conversation_id, ui_intent
                )
        elif guest_id:
            belongs = await loop.run_in_executor(
                None, conversation_belongs_to_guest, conversation_id, guest_id
            )
            if not belongs:
                yield _sse("error", {"message": "Zugriff verweigert."})
                return
    except Exception as exc:
        print(f"[STREAM] Conversation setup failed: {exc}")
        yield _sse("error", {"message": "Etwas ist schiefgelaufen."})
        return

    meta_payload: Dict[str, Any] = {"conversationId": conversation_id}
    if ui_intent is not None:
        meta_payload["start_intent"] = ui_intent
    yield _sse("meta", meta_payload)

    # ── Concurrent pipeline + time-based status ticker ─────────────────────
    out_q: asyncio.Queue = asyncio.Queue()
    stop_event = asyncio.Event()

    async def _ticker() -> None:
        await asyncio.sleep(2.5)
        if not stop_event.is_set():
            await out_q.put(_sse("status", {"message": "Suche passende Kursstellen \u2026"}))
        await asyncio.sleep(3.5)  # 6.0 s total from meta
        if not stop_event.is_set():
            await out_q.put(_sse("status", {"message": "Formuliere Antwort \u2026"}))

    async def _pipeline() -> None:
        try:
            prep = await loop.run_in_executor(
                None, _prepare_stream, conversation_id, user_message, guest_id, ui_intent
            )
        except Exception as exc:
            print(f"[STREAM] Prepare failed: {exc}")
            stop_event.set()
            await out_q.put(_sse("error", {"message": "Etwas ist schiefgelaufen."}))
            await out_q.put(None)
            return

        conv_id = prep["conversation_id"]

        if "early_answer" in prep:
            stop_event.set()
            await out_q.put(_sse("final", {
                "conversationId": conv_id,
                "answer": prep["early_answer"],
                "sources": prep.get("sources", []),
            }))
            await out_q.put(None)
            return

        sources = prep.get("sources", [])

        # Dev-only: artificial delay before LLM stream for status-event testing
        if _STREAM_TEST_DELAY > 0:
            await asyncio.sleep(_STREAM_TEST_DELAY)

        # Run sync OpenAI stream in a thread; push chunks via thread-safe calls
        chunk_q: asyncio.Queue = asyncio.Queue()
        _prep = prep

        def _stream_worker() -> None:
            try:
                stream = client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                        {"role": "user", "content": _prep["llm_input"]},
                    ],
                    temperature=0.0,
                    stream=True,
                )
                for chunk in stream:
                    loop.call_soon_threadsafe(chunk_q.put_nowait, chunk)
                loop.call_soon_threadsafe(chunk_q.put_nowait, None)
            except Exception as exc:
                loop.call_soon_threadsafe(chunk_q.put_nowait, exc)

        loop.run_in_executor(None, _stream_worker)

        full_text = ""
        first_token_seen = False
        while True:
            chunk = await chunk_q.get()
            if chunk is None:
                break
            if isinstance(chunk, Exception):
                print(f"[STREAM] LLM error: {chunk}")
                stop_event.set()
                await out_q.put(_sse("error", {"message": "Antwort konnte nicht generiert werden."}))
                await out_q.put(None)
                return
            if not chunk.choices:
                continue
            token = chunk.choices[0].delta.content
            if token:
                if not first_token_seen:
                    first_token_seen = True
                    stop_event.set()
                full_text += token
                await out_q.put(_sse("delta", {"text": token}))

        # Persist exactly once
        assistant_message = full_text.strip()
        _cid2 = conv_id
        _am = assistant_message
        _ui2 = prep.get("ui_intent")
        await loop.run_in_executor(
            None,
            lambda: create_message(_cid2, "assistant", _am, intent=_ui2),
        )
        conv_data_updated = await loop.run_in_executor(None, get_conversation, conv_id)
        if conv_data_updated:
            should_upd = await loop.run_in_executor(
                None, should_update_summary, conv_id, conv_data_updated
            )
            if should_upd:
                await loop.run_in_executor(
                    None, update_conversation_summary, conv_id, conv_data_updated
                )

        await out_q.put(_sse("final", {
            "conversationId": conv_id,
            "answer": assistant_message,
            "sources": sources,
        }))
        await out_q.put(None)  # sentinel

    ticker_task = asyncio.create_task(_ticker())
    pipeline_task = asyncio.create_task(_pipeline())
    try:
        while True:
            item = await out_q.get()
            if item is None:
                break
            yield item
    finally:
        stop_event.set()
        ticker_task.cancel()
        pipeline_task.cancel()
