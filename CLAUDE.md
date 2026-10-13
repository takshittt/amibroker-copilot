# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current state

The design is accepted but nothing is built. There is no source code, package manifest, test suite, CI, or git repository yet, so there are no build, lint, or test commands. The directories and files named below under "Planned layout" are the design's target, not what is on disk.

Read these before design or implementation work, in this order:

- `.claude/docs/intent.md`: problem, outcome, constraints (accepted).
- `.claude/docs/spec.md`: what v1 does (complete, with three items awaiting confirmation in its section 12).
- `.claude/ARCHITECTURE.md`: how v1 is structured (accepted).

If the three disagree, the later document in that list is the more recent decision, but raise the conflict with the user instead of silently picking one.

## What is being built

AFL Copilot: a website where a signed-in trader gets AFL (AmiBroker Formula Language) code they can trust. The target users are AFL writers who are not strong programmers, especially Indian retail algo traders (NSE, BSE, MCX). The output is AFL that the user pastes into AmiBroker.

Three modes:

- **Write**: a strategy in plain English, plus a market preset and timeframe, becomes AFL with a per-block explanation, a check panel, and links to the official docs.
- **Review**: pasted AFL gets findings (Critical / Warning / Tip, with line and fix) and an "apply all fixes" rewrite.
- **Fix-from-error**: pasted code plus AmiBroker's error text gets a corrected version.

## Hard constraints

- Never invent AmiBroker functions. Every function call in generated code must exist in the project's function list.
- Never label unchecked code as checked. If checks still fail after the retry limit, or the checker itself crashes, the code is shown with a visible "not fully checked" warning listing what failed.
- Never execute AFL.
- Do not store or show AmiBroker's doc or forum text. The knowledge base is written in our own words and links to the official docs.
- Out of scope for the product: backtesting, live trading, and strategy or profit advice.
- Out of scope for v1: custom backtester (CBI), multi-timeframe, loop-heavy code, plugins/OLE, VS Code extension.

## Architecture

The principle behind every design choice: **the LLM writes; deterministic code decides what counts as correct.** The function list, the checker, and the market table are plain data and code. The AI is never the source of truth for them.

Stack: Next.js (web + BFF), FastAPI (pipeline and checker), Postgres with pgvector and full-text search, Redis (quota counters, spend kill-switch), OpenAI API. Deployed as Docker Compose on a single VPS in Mumbai behind Caddy.

Request path: browser → Next.js BFF → FastAPI over internal HTTP + SSE. The browser never calls FastAPI directly. BFF routes hold no business logic: they verify the session JWT from the cookie, forward it to FastAPI as `Authorization: Bearer`, and stream SSE back.

Auth is email + password with one symmetric JWT (HS256), and no auth library or OAuth provider. FastAPI owns users and password hashes and issues the token; the BFF keeps it in an httpOnly cookie. Both services verify it with the same `JWT_SECRET`. Details are in ARCHITECTURE.md section 2.

The Write pipeline is explicit steps in plain Python, with no agent framework:

1. **Brief**: request → structured JSON brief; ask at most 2 clarifying questions if entry, exit, or direction is missing.
2. **Decompose** into concepts.
3. **Retrieve** per concept: Postgres FTS + pgvector merged by Reciprocal Rank Fusion, plus exact by-name lookup of any function mentioned or used.
4. **Rerank** to 8–12 items.
5. **Generate** strict JSON (`code`, `explanation_blocks`, `functions_used`).
6. **Check**. On failure, re-retrieve for the failing parts and regenerate with the findings as feedback, up to 3 attempts.
7. **Answer** as "checked", or with the warning described above.

Review mode runs the checker on the pasted code first, then an LLM pass. Checker findings are labelled **Verified** and LLM findings **AI-suggested**; keep that split visible everywhere, since it is how users know which findings are certain.

The checker is pure Python with no AI: handwritten lexer → light parser → symbol table (built-ins, user variables with an array/number type guess, user-defined functions) → rule engine. Each rule is one Python function with its own unit tests. The rule list and severities are in ARCHITECTURE.md section 5. Unknown identifiers that may come from an `#include` are a Warning, not Critical, because v1 cannot see included files.

The knowledge base is files in git, indexed into Postgres by an offline indexer. The checker reads the same `kb_functions` and `kb_builtins` data that feeds retrieval, so adding a function updates the AI's context and the checker in one change. Do not create a second function list anywhere.

Markets are data, not guesswork: session times and DST rules live in the market table (MCX's evening close has two seasonal rules). Generated AFL puts timings in editable parameters at the top, and intraday strategies must have an end-of-day exit.

Quota: one unit per completed answer. Clarifying questions, internal retries, and failed upstream calls are free to the user.

## Planned layout

- `/kb`: `functions/*.yaml` (one per AFL function), `builtins.yaml`, `concepts/*.md`, `examples/*.afl`, `mistakes/*.yaml`, `errors/*.yaml`, `markets.yaml`. Every change is versioned (`kb_version`) and goes through a pull request.
- `/evals`: the test set (Write tasks and buggy AFL samples for Review). Planned CI runs tests, then evals on prompt, KB, or checker changes, and blocks merge on regression. Every user-reported bug becomes a new eval case.

## Still open

Do not treat these as decided:

- Hosting: single VPS (recommended in the architecture) or Vercel + managed Postgres.
- Model choice per pipeline step, to be picked by cost and quality on the eval set. Model names belong in config, not code.
- Daily rate limit number (proposal: 20 requests/day).
- Spec section 12: generic example strategies only, and the v1 scope, both awaiting confirmation.
- Password reset: it needs an email sender. Decide whether it is in v1 or handled manually.

## Documentation layout

Project documentation lives under `.claude/`, not at the repository root. Besides the three documents above:

- `.claude/adr/`: architecture decision records (empty).
- `.claude/chnages/`: change records (empty). The directory name is misspelled on disk; use the path as it is unless the user renames it.
- `.claude/skills/testing-strategy/`: project skill for test plans. Its note that the stack is undecided predates the spec and architecture.

## Keeping this file current

Once code exists, replace "Current state" with the real build, lint, test, and single-test commands for both the Next.js and Python sides, and turn "Planned layout" into the actual layout.
