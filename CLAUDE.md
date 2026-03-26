# CLAUDE.md

Read `AGENTS.md` first. It is the canonical repo policy.

Use the current repo state as truth:
- code, scripts, tests, and repo structure beat README or older wrapper docs
- deterministic Trennkost and Eat-now semantics beat prompt phrasing
- keep deltas small and stop before touching contracts, rules, DB, auth, or policy prompts

Core commands:
- `./start.sh`
- `source .venv/bin/activate && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
- `pytest tests/test_api_contract.py -v`
- `pytest tests/test_engine.py tests/test_food_core_gold_matrix.py tests/test_ontology_schema.py -v`
- `pytest tests/test_normalization.py tests/test_normalization_e2e.py -v`
- `pytest tests/test_auth_entitlements.py -v`
- `pytest tests/test_vision_e2e.py tests/test_menu_followup_reuse.py tests/test_eat_now_session.py -v`

If a public workflow path or contract changes, update `AGENTS.md` and keep this file as a thin pointer only.
