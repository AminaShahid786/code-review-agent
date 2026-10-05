# AI-Driven Code Review and Refactoring Framework — Project Context

This file is read automatically by Claude Code at the start of every session in
this folder. Read it fully before doing anything.

## What this project is
A Final Year Project (BSCS, NUML Rawalpindi): an AI agent that reviews Python
code, finds real issues with static analysis, and uses a local small language
model to propose and verify fixes. Defence deadline: end of October. Target:
~60% complete (working backend + frontend + database) by then, 100% later.

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
- `agent/loop.py` — ReAct-style agent loop: `static_analysis` ->
  `propose_patch` -> `apply_and_test` -> `finish`. Has a "finish guard"
  that refuses to stop while static-analysis issues remain (re-checks
  before allowing finish, max 2 refusals so it can't loop forever). Builds
  each patch on top of the previously accepted one rather than restarting
  from the original code. Also has an auto-fix pre-pass for whitespace-only
  issues (e.g. missing final newline) that skips the model entirely when
  that's the only issue.
- `sandbox/verify.py` — rejects a patch if: it's identical to the original;
  it renames or removes a function/class; the specific targeted issue is
  still present afterward (re-runs static analysis to check); or overall
  static-analysis findings don't decrease. Only accepts genuine, verified
  improvements. This exists because the SLM has been observed to claim
  fixes it did not make — this is the project's core safety contribution.
- `tools/patcher.py` — builds a prompt naming the specific pylint rule and
  a concrete fix instruction (from a hints dictionary), retries once if the
  model returns unchanged code.
- `tools/analysis.py` — wraps pylint, returns `[{line, type, message, symbol}]`.
- `adapters/loader.py` — loads a local folder or clones+loads a GitHub repo.
- `agent/llm.py` — calls Ollama's generate endpoint with streaming (so
  multi-minute waits show live progress, not a silent hang).
- Verified results exist in `verification_gap_evidence.md` (if present) —
  read it for real before/after examples of the verifier catching
  hallucinated fixes. Use these as evidence, don't regenerate them.

Files that may be missing or that you have not seen yet: `agent/prompts.py`,
`agent/parser.py`, `report.py`. Ask me to paste them before changing them.

## What's missing — build in this order
1. **FastAPI backend.** `POST /reviews` (submit code, a file, a folder, or a
   GitHub URL; runs the existing agent loop as a background job — it takes
   minutes, so this MUST be async/job-based, never request-response
   blocking); `GET /reviews/{id}` (poll status and result);
   `POST /reviews/{id}/feedback` (store 👍/👎).
2. **SQLite database** (SQLAlchemy, no need for anything heavier): tables
   for reviews, findings, patches, feedback. Keep it simple.
3. **Streamlit frontend**: submit code, see live job status, side-by-side
   original vs. fixed code, plain-English explanation, feedback buttons.

Do NOT build: a vector database, RAG, multi-agent orchestration, model
distillation, or any form of containerization/orchestration. These are out
of scope for this timeline and hardware — if asked about them, say so
rather than attempting them.

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
