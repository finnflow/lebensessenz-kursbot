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


# ── Main pipeline ─────────────────────────────────────────────────────

def handle_chat(
    conversation_id: Optional[str],
    user_message: str,
    guest_id: Optional[str] = None,
    image_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Main chat handler — pipeline architecture.

    Steps:
    0. Normalize input (typo fixing, language, time formats)
    1. Setup conversation (create/validate, save ORIGINAL message, title)
    2. Process vision (if image)
    3. Detect chat mode + modifiers
    4. Run Trennkost engine (if food-related)
    5. Search recipes (if recipe request)
    6. Build RAG query + retrieve
    7. Fallback check
    8. Build prompt
    9. Generate response + save
    10. Update summary
    """
    # 1. Setup conversation (saves ORIGINAL message for transparency)
    conversation_id, is_new, conv_data = _setup_conversation(
        conversation_id, user_message, guest_id, image_path
    )

    # 1b. Get recent messages for normalization context
    recent_messages_for_norm = get_last_n_messages(conversation_id, 4)

    # 1c & 2. Parallel: Normalize + Intent + Vision (if image present)
    vision_data = {"vision_analysis": None, "food_groups": None,
                   "vision_extraction": None, "vision_is_menu": False,
                   "vision_failed": False}
    intent_result: Optional[Dict] = None

    if image_path:
        with ThreadPoolExecutor(max_workers=3) as executor:
            normalize_future = executor.submit(normalize_input, user_message, recent_messages_for_norm, is_new)
            intent_future = executor.submit(classify_intent, user_message, recent_messages_for_norm)
            vision_future = executor.submit(_process_vision, image_path, user_message)

            normalized_message = normalize_future.result()
            intent_result = intent_future.result()
            vision_data = vision_future.result()
        print(f"[PIPELINE] Parallel execution: normalization + intent + vision completed")
    else:
        with ThreadPoolExecutor(max_workers=2) as executor:
            normalize_future = executor.submit(normalize_input, user_message, recent_messages_for_norm, is_new)
            intent_future = executor.submit(classify_intent, user_message, recent_messages_for_norm)

            normalized_message = normalize_future.result()
            intent_result = intent_future.result()
        print(f"[PIPELINE] Parallel execution: normalization + intent completed")

    # 3. Detect chat mode (use normalized message)
    vision_type = None
    if vision_data.get("vision_extraction"):
        vision_type = vision_data["vision_extraction"].get("type")

    recent = get_last_n_messages(conversation_id, 4)
    mode, modifiers = detect_chat_mode(
        normalized_message,
        image_path=image_path,
        vision_type=vision_type,
        is_new_conversation=is_new,
        recent_message_count=len(recent),
        last_messages=recent,
    )
    modifiers.vision_failed = vision_data.get("vision_failed", False)

    # 3b. Temporal separation check — runs BEFORE intent override so "Apfel 30 min vor Reis"
    # is intercepted immediately regardless of what the intent classifier returns.
    temporal_sep = detect_temporal_separation(normalized_message)
    if temporal_sep and temporal_sep["is_temporal"]:
        print(f"[PIPELINE] Temporal separation detected: {temporal_sep}")
        first = ", ".join(temporal_sep["first_foods"])
        second = ", ".join(temporal_sep["second_foods"])
        wait = temporal_sep.get("wait_time")

        response_text = f"Ja, das ist **trennkost-konform**! 🎉\n\n"
        response_text += f"Du isst {first} **zuerst allein** und wartest "
        if wait:
            response_text += f"**{wait} Minuten**, "
        response_text += f"bevor du {second} isst. Das ist sequenzielles Essen und **völlig in Ordnung**!\n\n"
        response_text += "**Wichtige Wartezeiten nach Obst:**\n"
        response_text += "- Wasserreiche Früchte (Melone, Orangen): 20-30 Min\n"
        response_text += "- Äpfel, Birnen, Beeren: 30-45 Min\n"
        response_text += "- Bananen, Trockenobst: 45-60 Min\n\n"
        if wait and wait >= 30:
            response_text += f"✅ Deine {wait} Minuten Wartezeit sind perfekt für die meisten Früchte!"
        elif wait and wait < 30:
            response_text += f"⚠️ Hinweis: {wait} Min könnten bei manchen Früchten knapp sein. Optimal sind 30-45 Min."
        else:
            response_text += "💡 Achte auf die richtigen Wartezeiten, dann ist die Trennung optimal!"

        create_message(conversation_id, "assistant", response_text)
        return {"answer": response_text, "conversationId": conversation_id}

    # 3c. Intent override — for modes where regex had no strong signal
    _can_override_food_analysis = (
        mode == ChatMode.FOOD_ANALYSIS
        and not modifiers.is_compliance_check
        and not image_path
    )
    if (
        intent_result
        and intent_result.get("intent") == "recipe_from_ingredients"
        and intent_result.get("confidence") == "high"
        and (mode in (ChatMode.KNOWLEDGE, ChatMode.RECIPE_REQUEST) or _can_override_food_analysis)
    ):
        mode = ChatMode.RECIPE_FROM_INGREDIENTS
        modifiers.intent_hint = "recipe_from_ingredients"
        print(f"[INTENT] Override → RECIPE_FROM_INGREDIENTS")

    print(f"[PIPELINE] mode={mode.value} | is_breakfast={modifiers.is_breakfast} | wants_recipe={modifiers.wants_recipe}")

    # 3d. Early-exit for RECIPE_FROM_INGREDIENTS
    if mode == ChatMode.RECIPE_FROM_INGREDIENTS:
        available_ingredients = extract_available_ingredients(
            normalized_message, recent_messages_for_norm, vision_data.get("vision_extraction")
        )
        if not available_ingredients:
            print(f"[PIPELINE] RECIPE_FROM_INGREDIENTS: no ingredients found → RECIPE_REQUEST")
            mode = ChatMode.RECIPE_REQUEST
            modifiers.wants_recipe = True
        else:
            _GENERIC_TERMS = {"obst", "gemüse", "lebensmittel", "essen", "zutaten", "früchte", "beeren"}
            _is_only_generic = (
                len(available_ingredients) == 1
                and available_ingredients[0].strip().lower() in _GENERIC_TERMS
            )
            if _is_only_generic:
                print(f"[PIPELINE] RECIPE_FROM_INGREDIENTS: only generic term ({available_ingredients}) → FOOD_ANALYSIS")
                mode = ChatMode.FOOD_ANALYSIS
            else:
                print(f"[PIPELINE] RECIPE_FROM_INGREDIENTS | ingredients={available_ingredients[:5]}")
                response = handle_recipe_from_ingredients(
                    conversation_id, available_ingredients, modifiers.is_breakfast
                )
                conv_data_updated = get_conversation(conversation_id)
                if should_update_summary(conversation_id, conv_data_updated):
                    update_conversation_summary(conversation_id, conv_data_updated)
                return {"conversationId": conversation_id, "answer": response, "sources": []}

    # 3e. Context reference resolution
    analysis_query = normalized_message
    if mode == ChatMode.FOOD_ANALYSIS:
        resolved = resolve_context_references(normalized_message, recent)
        if resolved:
            analysis_query = resolved

    # 4. Run Trennkost engine
    trennkost_results = _run_engine(
        analysis_query, vision_data.get("vision_extraction"), mode
    )

    if DEBUG_RAG and trennkost_results:
        for r in trennkost_results:
            print(f"[TRENNKOST] {r.dish_name}: {r.verdict.value} | "
                  f"problems={len(r.problems)} | questions={len(r.required_questions)}")

    # 5. Search recipes (if recipe request, use normalized message)
    recipe_results = None
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
                            print(f"[PIPELINE] Short follow-up detected, using previous query: '{search_query[:50]}...'")
                            break

            recipe_results = search_recipes(search_query, limit=5)
            print(f"[PIPELINE] recipe_results={len(recipe_results)} recipes found")
            for r in (recipe_results or [])[:3]:
                print(f"  → {r['name']} ({r['trennkost_category']}) score={r.get('score', '?')}")
        except Exception as e:
            print(f"[PIPELINE] recipe search failed: {e}")
            recipe_results = []

    # 6. Load context + build RAG query + retrieve
    summary = conv_data.get("summary_text")
    last_messages = get_last_n_messages(conversation_id, LAST_N)

    standalone_query = _build_rag_query(
        trennkost_results, vision_data.get("food_groups"),
        image_path, summary, last_messages, normalized_message,
        modifiers.is_breakfast,
    )

    needs_clarification = None
    is_followup = not is_new and len(last_messages) >= 2
    if not trennkost_results:
        food_classification_result = classify_food_items(normalized_message, standalone_query)
        if food_classification_result:
            classification = food_classification_result.get("classification", "")
            if not is_followup or len(normalized_message) > 80:
                needs_clarification = food_classification_result.get("needs_clarification")
            if classification:
                standalone_query += f"\n{classification}"

    if DEBUG_RAG:
        print(f"\n[RAG] Primary query: {standalone_query}")

    docs, metas, dists, is_partial = retrieve_with_fallback(standalone_query, normalized_message)

    if DEBUG_RAG:
        print(f"[RAG] Retrieved {len(docs)} chunk(s) | partial={is_partial}")
        for i, (doc, meta, dist) in enumerate(list(zip(docs, metas, dists))[:3], 1):
            print(f"  {i}. path={meta.get('path', '?')} | page={meta.get('page', '?')} | chunk={meta.get('chunk', '?')} | dist={dist:.3f}")

    course_context = build_context(docs, metas)

    # 7. Fallback check
    best_dist = min(dists) if dists else 999.0
    if _check_fallback(trennkost_results, mode, best_dist, is_partial, course_context):
        assistant_message = FALLBACK_SENTENCE
        create_message(conversation_id, "assistant", assistant_message)
        conv_data_updated = get_conversation(conversation_id)
        if should_update_summary(conversation_id, conv_data_updated):
            update_conversation_summary(conversation_id, conv_data_updated)
        return {
            "conversationId": conversation_id,
            "answer": assistant_message,
            "sources": []
        }

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

    # 11. Prepare sources
    sources = _prepare_sources(metas, dists)

    return {
        "conversationId": conversation_id,
        "answer": assistant_message,
        "sources": sources,
    }
