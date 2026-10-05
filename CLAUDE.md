# AI-Driven Code Review and Refactoring Framework — Project Context

This file is read automatically by Claude Code at the start of every session in
this folder. Read it fully before doing anything.

## What this project is
A Final Year Project (BSCS, NUML Rawalpindi): an AI agent that reviews Python
code, finds real issues with static analysis, and uses a local small language
model to propose and verify fixes. Defence deadline: end of October. Target:
~60% complete (working backend + frontend + database) by then, 100% later.
**Current status (5 Oct 2026): ~65%** — backend, database and frontend are built
and tested with the real model; see `PROGRESS.md` for the detailed checklist.

## Hardware constraints — these are hard limits, not preferences
- Windows laptop, 16GB RAM, **no dedicated GPU** (CPU-only inference).
- Models run locally via **Ollama** (not cloud APIs): `qwen2.5-coder:7b`,
  `qwen-refactor-7b` (agent: qwen2.5-coder:7b with a role-specific system
  prompt (via Modelfile) -- same base weights as qwen-baseline-7b, confirmed
  via identical sha256 hash, no fine-tuning or LoRA involved; see
  `Modelfile-refactor7b`),
  `qwen-baseline-7b` (patch generation / explanations, see `Modelfile-baseline7b`).
- A single model call typically takes **30 seconds to 3 minutes**. A full
  agent run on one file with several issues takes **15–40 minutes**.
- Do NOT suggest: cloud LLM APIs, larger models, GPU-dependent tooling
  (vLLM, etc.), Kubernetes, Docker Swarm, Celery/Redis, or any
  infrastructure that assumes more than one laptop. Keep every suggestion
  runnable on this exact machine.

## What already works — tested, do not rewrite without a clear reason
### Core pipeline
- `agent/loop.py` — ReAct-style agent loop: `static_analysis` ->
  `propose_patch` -> `apply_and_test` -> `finish`. Has a "finish guard"
  that refuses to stop while static-analysis issues remain (re-checks
  before allowing finish, max 2 refusals so it can't loop forever). Builds
  each patch on top of the previously accepted one rather than restarting
  from the original code. Also has an auto-fix pre-pass for whitespace-only
  issues (e.g. missing final newline) that skips the model entirely when
  that's the only issue. `_resolve_issue` never trusts the model's target:
  it unwraps malformed input, only targets a rule pylint still reports, then
  matches the rule named in the model's Thought, and only then falls back to
  the first remaining finding.
- `sandbox/verify.py` — rejects a patch if: it's identical to the original;
  it renames or removes a function/class; the specific targeted issue is
  still present afterward (re-runs static analysis to check); or overall
  static-analysis findings don't decrease. Only accepts genuine, verified
  improvements. This exists because the SLM has been observed to claim
  fixes it did not make — this is the project's core safety contribution.
  Its accept/reject logic must not be changed; bugs so far were in what gets
  PASSED to it, not in the checks.
- `tools/patcher.py` — builds a prompt naming the specific pylint rule and
  a concrete fix instruction (from a hints dictionary), retries once if the
  model returns unchanged code.
- `tools/analysis.py` — wraps pylint, returns `[{line, type, message, symbol}]`.
  It always writes to `temp.py` in the current folder, so only ONE review may
  run at a time (the API's single worker enforces this).
- `adapters/loader.py` — loads a local folder or clones+loads a GitHub repo.
- `agent/llm.py` — calls Ollama's generate endpoint with streaming (so
  multi-minute waits show live progress, not a silent hang).
- `agent/prompts.py` — shows past steps to the model as real JSON (Python dict
  repr taught the model a non-JSON format that nested itself step by step).
- `agent/parser.py` — reads JSON or single-quoted dicts; unwraps nested `_raw`.
- `agent/report.py` — diff, pylint-confirmed `fixed_issues`, and an explanation
  checked against the diff (one retry, then a factual fallback).

### Backend, database, frontend
- `api/main.py` — FastAPI: `POST /reviews` (code / folder / GitHub URL),
  `POST /reviews/upload`, `GET /reviews`, `GET /reviews/{id}`,
  `POST /reviews/{id}/feedback`, `GET /health` (pylint, Ollama, worker).
- `api/jobs.py` — single daemon worker thread + in-memory queue; storage
  functions backed by SQLite. Queued/running reviews left by a previous server
  process are marked `failed` ("Interrupted") at startup, not restarted.
- `api/runner.py` — runs one job through the pipeline above; max 10 files per
  submission (`REVIEW_MAX_FILES`); `REVIEW_FAKE_LLM=1` swaps in an instant fake
  model for testing (pylint and all checks still run for real).
- `api/db.py` — SQLAlchemy models: `reviews`, `patches` (one per file),
  `findings` (with `fixed` flag), `feedback`. File: `reviews.db` (`REVIEW_DB`).
- `frontend/app.py` — Streamlit page; calls ONLY the existing API endpoints
  (no pipeline/db logic of its own). Live status, side-by-side code, diff,
  explanation, 👍/👎, double-click guards on submit and feedback.

### Evidence and tests
- `verification_gap_evidence.md` — real before/after examples of the verifier
  catching hallucinated fixes, plus the parser/explanation bugs and the first
  clean API runs. Use these as evidence, don't regenerate them.
- `tests/fixtures/` — real review results (`4ffdac0b9e39`: the failing case;
  `2a1cbd019213`: first clean run) replayed by the model-free tests.
- Model-free regression tests (run from the project root, venv active):
  `test_verify_gap.py` (8), `test_parse_gap.py` (11), `test_explanation_gap.py`
  (7), `test_db.py` (6), `test_frontend.py` (7). Each takes under 30 seconds.
  Other `test_*.py` scripts call the real model and take minutes.

## How to run (quick reference)
```powershell
venv\Scripts\activate                  # the venv/ folder, not .venv/
uvicorn api.main:app --port 8000        # backend; logs "Review worker started"
streamlit run frontend/app.py           # frontend, second terminal -> localhost:8501
```
Add `$env:REVIEW_FAKE_LLM="1"` before uvicorn for an instant test run without
the model. Uvicorn does not auto-reload: restart it after changing backend code.

## What's left — in this order
1. **Feedback loop**: analyse stored 👍/👎 per rule / fix type; feed results
   back into fix hints and prompts.
2. **Frontend improvements**: folder/GitHub submission in the UI (API already
   supports it), multi-file dashboard, download corrected file / report,
   inline diff, history search.
3. **Evaluation & benchmarking**: fixed set of real files; fix rate, rejection
   reasons, time per issue; recorded end-to-end demo.
4. **Performance**: the agent history repeats the full code every step; trim it.
5. **Agent robustness**: the model copies code with unescaped `"""` into its
   JSON input (occasional one-layer `_raw`); add hints for structural rules
   such as `consider-using-enumerate`.
6. **Test consolidation** into one `pytest` suite.

Do NOT build: a vector database, RAG, multi-agent orchestration, model
distillation, or any form of containerization/orchestration. These are out
of scope for this timeline and hardware — if asked about them, say so
rather than attempting them.

## Other documentation
- `README.md` — public project documentation (setup, architecture, API).
  Keep it in sync when setup steps, endpoints or status change.
- `PROGRESS.md` — plain-language progress log (rules below).
- FYP report Chapter 4 (Design) is drafted in a Claude Doc:
  https://claude.ai/code/artifact/516a676b-2e62-4318-9894-746e8eb40e11

## How to work with me
- I'm a student, not a professional backend developer. Explain briefly what
  you're doing and why, but prioritize working code over long explanations.
- After each piece you build, tell me exactly how to test it before moving on.
- Don't rewrite the working agent/verify/patcher logic unless something is
  actually broken — it has been tested extensively.
- A full agent run takes a long time. When testing something that needs the
  real model, warn me about expected runtime before I run it.

## Documentation you must maintain — for my supervisor
Keep a file called `PROGRESS.md` in the project root, updated after every
meaningful change, written in **simple, plain language**.
 It must always contain:
1. A checklist of every component from the original proposal (code
   collection, static analysis, SLM agent, verification/testing, feedback
   report, backend, database, frontend, memory/feedback loop) marked done,
   in progress, or not started.
2. A one-paragraph plain-language summary of what currently works, written
   as if explaining it to someone non-technical.
3. A "what's left" section listing remaining work in order.
4. A short "evidence" section linking or quoting real test results (not
   claims) — e.g. actual terminal output showing a fix being verified.
Update this file as part of every work session, not just at the end.
