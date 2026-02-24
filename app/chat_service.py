import re
from typing import Optional, List, Dict, Any, Tuple
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
)
from app.vision_service import (
    analyze_meal_image,
    categorize_food_groups,
    generate_trennkost_query,
    extract_food_from_image,
    VisionAnalysisError,
)
from app.image_handler import ImageValidationError
from trennkost.analyzer import (
    detect_food_query,
    detect_breakfast_context,
    detect_temporal_separation,
    analyze_text as trennkost_analyze_text,
    analyze_vision as trennkost_analyze_vision,
)
from trennkost.formatter import format_results_for_llm, build_rag_query
from trennkost.models import TrennkostResult

from app.chat_modes import ChatMode, ChatModifiers, detect_chat_mode
from app.prompt_builder import (
    SYSTEM_INSTRUCTIONS,
    FALLBACK_SENTENCE,
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
)


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

def _setup_conversation(
    conversation_id: Optional[str],
    user_message: str,
    guest_id: Optional[str],
    image_path: Optional[str],
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

    create_message(conversation_id, "user", user_message, image_path=image_path)

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


def _check_fallback(
    trennkost_results: Optional[List[TrennkostResult]],
    mode: ChatMode,
    best_dist: float,
    is_partial: bool,
    course_context: str,
) -> bool:
    """Check if we should return fallback (no relevant content found)."""
    if trennkost_results:
        return False
    if mode == ChatMode.RECIPE_REQUEST:
        return False
    if best_dist > DISTANCE_THRESHOLD and not is_partial:
        return True
    if not course_context.strip():
        return True
    return False


def _build_prompt_parts(
    mode: ChatMode,
    modifiers: ChatModifiers,
    trennkost_results: Optional[List[TrennkostResult]],
    vision_data: Dict[str, Any],
    summary: Optional[str],
    last_messages: List[Dict[str, Any]],
    user_message: str,
    recipe_results: Optional[List[Dict]] = None,
) -> Tuple[List[str], str]:
    """Build all prompt parts and answer instructions based on mode."""
    parts = build_base_context(summary, last_messages)

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
) -> str:
    """
    Call LLM and save the response.

    Special case: For recipe requests with high-score matches (≥7.0),
    bypass LLM and format recipe directly to avoid unwanted follow-up questions.
    """
    if mode and recipe_results:
        if mode == ChatMode.RECIPE_REQUEST and recipe_results[0].get('score', 0.0) >= 7.0:
            assistant_message = format_recipe_directly(recipe_results[0])
            create_message(conversation_id, "assistant", assistant_message)
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
    create_message(conversation_id, "assistant", assistant_message)
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

    create_message(conversation_id, "assistant", text)
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
        )

    _GENERIC = {"obst", "gemüse", "lebensmittel", "essen", "zutaten", "früchte", "beeren"}
    if len(available_ingredients) == 1 and available_ingredients[0].strip().lower() in _GENERIC:
        print(f"[PIPELINE] RECIPE_FROM_INGREDIENTS: only generic term ({available_ingredients}) → FOOD_ANALYSIS")
        return _handle_food_analysis(
            conversation_id, normalized_message, recent, vision_data,
            ChatMode.FOOD_ANALYSIS, modifiers, is_new, conv_data, image_path,
        )

    print(f"[PIPELINE] RECIPE_FROM_INGREDIENTS | ingredients={available_ingredients[:5]}")
    response = handle_recipe_from_ingredients(
        conversation_id, available_ingredients, modifiers.is_breakfast
    )
    conv_data_updated = get_conversation(conversation_id)
    if should_update_summary(conversation_id, conv_data_updated):
        update_conversation_summary(conversation_id, conv_data_updated)
    return {"conversationId": conversation_id, "answer": response, "sources": []}


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
) -> Dict[str, Any]:
    """
    Steps 3e + 4: context-reference resolution, Trennkost engine, then finalize.
    Handles FOOD_ANALYSIS, MENU_ANALYSIS, MENU_FOLLOWUP.
    """
    analysis_query = normalized_message
    if mode == ChatMode.FOOD_ANALYSIS:
        resolved = resolve_context_references(normalized_message, recent)
        if resolved:
            analysis_query = resolved

    trennkost_results = _run_engine(analysis_query, vision_data.get("vision_extraction"), mode)

    if DEBUG_RAG and trennkost_results:
        for r in trennkost_results:
            print(f"[TRENNKOST] {r.dish_name}: {r.verdict.value} | "
                  f"problems={len(r.problems)} | questions={len(r.required_questions)}")

    return _finalize_response(
        conversation_id, normalized_message, vision_data, mode, modifiers,
        is_new, conv_data, image_path,
        trennkost_results=trennkost_results,
        analysis_query=analysis_query,
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
) -> Dict[str, Any]:
    """Pure RAG path for KNOWLEDGE mode (and any unrecognized mode)."""
    return _finalize_response(
        conversation_id, normalized_message, vision_data, mode, modifiers,
        is_new, conv_data, image_path,
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
    if _check_fallback(trennkost_results, mode, best_dist, is_partial, course_context):
        create_message(conversation_id, "assistant", FALLBACK_SENTENCE)
        conv_data_updated = get_conversation(conversation_id)
        if should_update_summary(conversation_id, conv_data_updated):
            update_conversation_summary(conversation_id, conv_data_updated)
        return {"conversationId": conversation_id, "answer": FALLBACK_SENTENCE, "sources": []}

    # 8. Build prompt
    prompt_parts, answer_instructions = _build_prompt_parts(
        mode, modifiers, trennkost_results, vision_data,
        summary, last_messages, analysis_query, recipe_results,
    )
    modifiers.needs_clarification = needs_clarification
    llm_input = assemble_prompt(
        prompt_parts, course_context, normalized_message,
        answer_instructions, needs_clarification,
    )

    # 9. Generate + save
    assistant_message = _generate_and_save(conversation_id, llm_input, mode, recipe_results)

    # 10. Update summary
    conv_data_updated = get_conversation(conversation_id)
    if should_update_summary(conversation_id, conv_data_updated):
        update_conversation_summary(conversation_id, conv_data_updated)

    return {
        "conversationId": conversation_id,
        "answer": assistant_message,
        "sources": _prepare_sources(metas, dists),
    }


# ── Main pipeline ─────────────────────────────────────────────────────

def handle_chat(
    conversation_id: Optional[str],
    user_message: str,
    guest_id: Optional[str] = None,
    image_path: Optional[str] = None,
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
    conversation_id, is_new, conv_data = _setup_conversation(
        conversation_id, user_message, guest_id, image_path
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
    early = _handle_temporal_separation(normalized_message, conversation_id)
    if early:
        return early

    # ── 3c. Intent override ───────────────────────────────────────────
    mode = _apply_intent_override(mode, modifiers, intent_result, image_path)
    print(f"[PIPELINE] mode={mode.value} | is_breakfast={modifiers.is_breakfast} | wants_recipe={modifiers.wants_recipe}")

    # ── 4. Dispatch ───────────────────────────────────────────────────
    ctx = (conversation_id, normalized_message, recent, vision_data, mode, modifiers, is_new, conv_data, image_path)
    if mode == ChatMode.RECIPE_FROM_INGREDIENTS:
        return _handle_recipe_from_ingredients_mode(*ctx)
    if mode in (ChatMode.FOOD_ANALYSIS, ChatMode.MENU_ANALYSIS, ChatMode.MENU_FOLLOWUP):
        return _handle_food_analysis(*ctx)
    if mode == ChatMode.RECIPE_REQUEST:
        return _handle_recipe_request(*ctx)
    return _handle_knowledge_mode(*ctx)
