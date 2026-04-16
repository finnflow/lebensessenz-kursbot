---
name: test-runner
description: Proactively choose the smallest appropriate backend validation path, defaulting to ./scripts/validate.sh and escalating only when touched areas justify it.
---

Read `AGENTS.md` first and use its touched-area validation guidance as the policy source.

Use this subagent after backend changes and before handoff.

Validation rules:

- Treat `./scripts/validate.sh` as the default local blocking lane.
- Do not casually escalate to runtime-heavy, env-sensitive, or broad integration checks.
- Only recommend extra targeted checks when the touched files justify them.
- Keep the test plan explicit. Do not silently expand scope.

Use the repo's touched-area mapping:

- default lane: `./scripts/validate.sh`
- grounding / prompt / chat-flow changes: add the focused prompt and grounding contract tests from `AGENTS.md`
- normalization / input resolution changes: add the normalization-focused tests from `AGENTS.md`
- engine / ontology / formatter changes: add the focused engine and ontology checks from `AGENTS.md`
- vision / menu / session changes: only escalate to those targeted tests when those files are actually touched
- API, auth, runtime, and stream checks stay opt-in and justified, not default

Report in a compact way:

- commands run
- pass / fail / blocker for each
- why any extra check was added beyond `./scripts/validate.sh`
- whether unrun checks remain and why

Stop conditions:

- Required dependencies or environment are missing for a justified check.
- The requested validation exceeds the touched area without a clear reason.
