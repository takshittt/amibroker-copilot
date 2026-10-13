# CLAUDE.md

AFL Copilot: a website where a signed-in trader gets AFL (AmiBroker Formula Language) code they can trust. Three modes: **Write** (a strategy in plain English becomes AFL), **Review** (pasted AFL gets findings and fixes), and **Fix-from-error** (code plus AmiBroker's error text gets a corrected version). The users are AFL writers who are not strong programmers, mainly Indian retail algo traders (NSE, BSE, MCX).

## Current state

The design is accepted. Stages 0 and 1 of the plan are done: `api/copilot/kb/` holds the KB record formats and the loader that turns `/kb` into a `Catalog`, and `/kb` holds a seed of 45 functions, the built-ins and the v1 markets. There is no checker, pipeline or API yet, and no `web/` side.

## Commands

Run from the repository root. Python is managed by `uv` (Python 3.12).

- Test: `make test` (ends with "N passed")
- One test: `cd api && uv run pytest tests/test_smoke.py::test_package_imports`
- Lint: `make lint` (ends with "All checks passed!" and "N files already formatted")
- Auto-fix lint and formatting: `make format`
- Validate the knowledge base: `make validate-kb` (ends with "KB ok: ..." or lists every problem and fails)

## Verifying your work

Run `make test` and `make lint` before reporting any task complete, and show the output. If a test fails, fix the code, not the test. Never skip or delete a failing test. For a bug fix, write the failing test first and confirm it fails for the expected reason.

## Read before design or implementation work

- `.claude/docs/intent.md`: problem, outcome, constraints (accepted).
- `.claude/docs/spec.md`: what v1 does (accepted).
- `.claude/ARCHITECTURE.md`: how v1 is structured (accepted). The stack, hosting, pipeline steps, checker rules, data model and API are described there, not here.
- `.claude/docs/plan.md`: build order and the detailed plan for the current stage (draft).

If these disagree, the later document in the list is the more recent decision, but raise the conflict with the user instead of silently picking one.

## Hard constraints

- Never invent AmiBroker functions. Every function call in generated code must exist in the project's function list.
- Never label unchecked code as checked. If checks still fail after the retry limit, or the checker itself crashes, the code is shown with a visible "not fully checked" warning listing what failed.
- Never execute AFL.
- No private strategies in the knowledge base. Examples are generic ones written for this project.
- Do not store or show AmiBroker's doc or forum text. The knowledge base is written in our own words and links to the official docs.
- Out of scope for the product: backtesting, live trading, and strategy or profit advice.
- Out of scope for v1: custom backtester (CBI), multi-timeframe, loop-heavy code, plugins/OLE, VS Code extension.

## Design rules

The principle behind every choice: **the LLM writes; deterministic code decides what counts as correct.**

- There is one function list, in `/kb`. The checker and retrieval both read it. Do not create a second one anywhere, including in prompts.
- The checker is pure Python with no AI and no network. Each rule is one function with its own unit tests.
- Checker findings are labelled **Verified** and LLM findings **AI-suggested**. Keep that split visible everywhere.
- The browser never calls FastAPI. BFF routes hold no business logic: they verify the session JWT, forward it, and stream the reply back.
- FastAPI is reachable from the internet, so it rejects any request without the shared BFF key.
- Market session times come from the market table, never from prompts or code. Generated AFL puts timings in editable parameters at the top, and intraday strategies must have an end-of-day exit.
- Model names, the quota and other limits live in config, not code.
- The pipeline is plain Python steps. Do not add an agent framework or an auth library.
- Every KB change bumps `kb_version` and goes through a pull request. Every user-reported bug becomes a new eval case.

## Documentation layout

Project documentation lives under `.claude/`, not at the repository root:

- `.claude/adr/`: architecture decision records (empty).
- `.claude/changes/`: change records (empty).
- `.claude/hooks/`: hook scripts, registered in `.claude/settings.json`. They block writing, staging or committing `.env` files; format and lint each edited Python file under `api/`; and lock test files while bug-fix mode is on. Only the user switches bug-fix mode, with `make bugfix-on` and `make bugfix-off`.
- `.claude/skills/testing-strategy/`: project skill for test plans. Its note that the stack is undecided is out of date.

## Keeping this file current

- When an architecture or behaviour change is made, update `ARCHITECTURE.md` or `spec.md` in the same change.
- When Claude makes the same mistake twice, add the correction to this file.
- Keep this file short. Detail belongs in the documents above.
