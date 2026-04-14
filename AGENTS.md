# AGENTS.md

## Repo Purpose
- FastAPI-Backend mit produktnaher Business-Logik fuer den Lebensessenz Kursbot.
- Deterministische Trennkost-Verdicts, Ranking und Session-Semantik haben Vorrang vor kreativer Antwortverbesserung.
- Bevorzuge minimale Deltas und kleine, reviewbare Aenderungen. Standard-Workflow: ein Executor, optional ein read-only Reviewer.

## Source of Truth / Architecture Map
- `app/main.py`: API-, Streaming-, Request/Response- und Error-Entry.
- `app/chat_service.py`: zentrale Orchestrierung fuer Normalisierung, Modus-Routing, Vision, RAG, Prompt-Aufbau, Persistenz und Streaming-Vorbereitung.
- `app/chat_modes.py`: Modus-Detection, Follow-up- und Menu-Heuristiken.
- `app/input_service.py`: Normalisierung, Intent-Klassifikation und Kontext-Referenz-Aufloesung.
- `app/grounding_policy.py`: zentrale Fallback-/Grounding-Policy fuer Runtime und Prompt-Pfade.
- `app/clients.py`: Modell-, Retrieval- und Provider-Konfiguration.
- `trennkost/`: deterministischer Kern (`analyzer.py`, `normalizer.py`, `ontology.py`, `engine.py`, `formatter.py`, Daten-Dateien). Verdict-Semantik lebt hier, nicht im Prompt.
- `app/prompt_builder.py`: policy- und produktnahe Promptlogik, immutable-verdict wording, deterministische Menu-Ranking-Helfer.
- `app/database.py` und `app/migrations.py`: Persistenz-, Ownership-, Active-Menu-State- und Schema-Zone.
- `app/auth.py` und `app/entitlements.py`: Security-, JWT- und Access-Zone.
- `app/eat_now_session.py`: deterministische Eat-now-Session-Transitions und Payload-Semantik.
- `docs/eat-now-session-contract-v0.1.md`: oeffentliche Eat-now-v0.1-Referenz; wenn Doku, Code und Tests auseinanderlaufen, gelten Code und Tests.

## Working Commands
- `./start.sh`
- `source .venv/bin/activate && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
- `./scripts/validate.sh` (default local blocking lane)
- `pytest tests/test_engine.py tests/test_food_core_gold_matrix.py tests/test_ontology_schema.py -v`
- `pytest tests/test_normalization.py tests/test_normalization_e2e.py -v`
- `pytest tests/test_grounding_policy.py tests/test_prompt_builder_output_contract.py tests/test_output_contract.py -v`
- `pytest tests/test_vision_e2e.py tests/test_menu_followup_reuse.py tests/test_eat_now_session.py -v`
- Dependency-/Env-sensitive Checks nur wenn passend:
  - `pytest tests/test_api_contract.py -v`
  - `pytest tests/test_auth_entitlements.py -v`
- Runtime-nahe Checks nur wenn passend und ein lokaler Server sinnvoll ist:
  - `python scripts/stream_smoke_test.py --base-url http://localhost:8000`
  - `bash tests/run_tests.sh`

## Change Classes
- Safe local changes: kleine Fixes in genau einer nicht-sensitiven Zone bei stabilem Contract und passender fokussierter Validierung.
- Guarded changes: Aenderungen in einer sensiblen Zone wie Chat-Orchestrierung, Prompt-Aufbau, Vision/Menu oder Grounding, solange API-/DB-/Auth-Contracts stabil bleiben.
- Privileged changes requiring explicit approval: Rule-/Ontology-/Verdict-Semantik, API- oder SSE-Shape, DB-Schema oder Migrationsbedeutung, Auth/JWT/Entitlements, System-/Policy-Prompts, Dependency-/Provider-/Model-Wechsel oder Cross-Zone-Aenderungen ueber mehrere sensible Flaechen.

## Hard Stop & Ask Rules
- Stop vor Aenderungen an Trennkost-Regeln, Ontology, Verdict-/Traffic-Light-/Wait-Profile-Semantik oder Eat-now-Ranking/Fokus-Semantik.
- Stop vor Aenderungen an API-Shape, Error-Envelope, Request/Response-Feldern oder SSE-Event-Vertrag.
- Stop vor Aenderungen an DB-Schema, Migrationen, persistierter Feldbedeutung oder Ownership-Semantik.
- Stop vor Aenderungen an Auth-Defaults, JWT-Verhalten, Entitlement-Semantik oder Dev-vs-Prod-Gating.
- Stop vor Aenderungen an `SYSTEM_INSTRUCTIONS`, Grounding-Fallback-Policy, Produkt-/Policy-Prompts, Dependencies, Netzwerk-Integrationen oder Model-/Provider-Wiring.
- Stop, wenn ein einzelner Change Core + API + DB + Auth oder mehrere andere sensible Zonen zusammen beruehrt.

## Validation by Touched Area
- API / Streaming / Error contract touched: `pytest tests/test_output_contract.py tests/test_prompt_builder_output_contract.py -v`; wenn API-Envelope/-Routes direkt betroffen sind und die Auth-/Email-Dependencies lokal sauber installiert sind, zusaetzlich `pytest tests/test_api_contract.py -v`; bei SSE-Aenderungen zusaetzlich `python scripts/stream_smoke_test.py --base-url http://localhost:8000`.
- Engine / rules / ontology / formatter touched: `pytest tests/test_engine.py tests/test_food_core_gold_matrix.py tests/test_ontology_schema.py tests/test_formatter_output_contract.py -v`; bei Compound-Daten zusaetzlich `pytest tests/test_compound_alignment.py tests/test_compound_gold_cases.py -v`, bei Ontology-/Profil-Aenderungen mindestens `pytest tests/test_ontology_consistency.py -v`.
- Grounding / prompt / chat-flow touched: `pytest tests/test_grounding_policy.py tests/test_prompt_builder_output_contract.py tests/test_output_contract.py tests/test_menu_recommendation_ordering.py -v`; bei Menu-/Session-Flow zusaetzlich `pytest tests/test_menu_followup_reuse.py tests/test_eat_now_session.py -v`.
- Auth / entitlements touched: wenn die Auth-/Email-Dependencies lokal sauber installiert sind `pytest tests/test_auth_entitlements.py -v`.
- Normalization / input resolution touched: `pytest tests/test_normalization.py tests/test_normalization_e2e.py tests/test_context_reference_resolution.py tests/test_resolved_input_boundary.py -v`.
- Vision / menu / image flow touched: `pytest tests/test_vision_e2e.py tests/test_menu_followup_reuse.py tests/test_eat_now_session.py -v`; bei Eat-now-Session-, `currentSession`- oder active-menu-state-Vertrag mindestens `pytest tests/test_eat_now_session.py -v`; wenn der Vision-to-engine-Handoff geaendert wurde, auch `pytest tests/test_vision_guardrails.py -v`.
- Retrieval / runtime-nahe RAG-Aenderungen: zuerst fokussierte Unit-/Contract-Tests, dann nur wenn wirklich passend `bash tests/run_tests.sh`.
- Breite Pipeline-Aenderung: die Vereinigung der betroffenen Zonen laufen lassen, nicht pauschal die Full Suite.

## Review Checklist
- Ueberschreibt oder verwischt irgendein LLM-Pfad ein deterministisches Verdict, Ranking oder eine Session-Transition?
- Bleiben API-, Error- und SSE-Shape fuer bestehende Clients und Tests stabil?
- Bleiben Ownership, Guest-Binding, Auth und Entitlements korrekt?
- Wird kein rein fluechtiger Zustand als persistent verkauft?
- Entsteht keine unbeabsichtigte Contract- oder Doku-Drift?

## Docs Drift Rule
- README nie als alleinige Wahrheit behandeln; Code, Skripte, Tests und aktuelle Repo-Struktur haben Vorrang.
- Wenn oeffentliche Start-, Test-, API- oder Eat-now-Contract-Pfade geaendert werden, muessen passende Doku-Dateien im selben Change mitgezogen werden (`README.md`, `CLAUDE.md`, `docs/eat-now-session-contract-v0.1.md` je nach Flaeche).
- Bei Eat-now-Drift schlagen Code und Tests die v0.1-Doku.
- `AGENTS.md` ist die kanonische Agenten-Policy dieses Repos; Wrapper-Dateien verweisen hierhin und definieren kein zweites Regelwerk.

## PR / Commit Slicing
- One risk surface per PR.
- Tests gehoeren in dieselbe PR wie die Codeaenderung.
- Docs-only moeglichst separat halten.
- Keine Misch-PRs ueber Core + API + DB + Auth.

## Non-Goals
- Keine Architektur-Neuerfindung.
- Keine generischen Cleanups.
- Keine stillen Produktsemantik-Aenderungen.
- Keine pauschalen Dependency- oder Model-/Provider-Upgrades.
