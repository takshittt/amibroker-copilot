# CLAUDE.md

AFL Copilot: a website where a signed-in trader gets AFL (AmiBroker Formula Language) code they can trust. Three modes: **Write** (a strategy in plain English becomes AFL), **Review** (pasted AFL gets findings and fixes), and **Fix-from-error** (code plus AmiBroker's error text gets a corrected version). The users are AFL writers who are not strong programmers, mainly Indian retail algo traders (NSE, BSE, MCX).

## Current state

The design is accepted. Stages 0 to 7 of the plan are built: the KB formats, loaders and content in `/kb`; the checker with its 10 rules; the Postgres schema, indexer and searches; all three modes (Write, Review with "apply all fixes", Fix-from-error) in `api/copilot/pipeline/`, with command-line tools and eval sets; and the API in `api/copilot/api/` (auth, BFF key, conversations, event stream, quota, spend cap) with an admin command. **Everything that involves the model has only ever run against a scripted model.** No real OpenAI call has been made, the model ids are unconfirmed, nothing has been run against Supabase, and nothing is deployed (see `.claude/changes/`). Next is stage 8, the website. There is no `web/` side yet.

## Commands

Run from the repository root. Python is managed by `uv` (Python 3.12).

- Start local Postgres and Redis: `make services-up` (Docker must be running: `colima start`). Stop them: `make services-down`
- Run the API on port 8000: `make api` (needs every setting in `.env.example`, including the OpenAI key and model ids). Give a user a new password: `make reset-password EMAIL=...`
- Test: `make test` (ends with "N passed"). The database, Redis and API tests need `make services-up` first; if those are not reachable they are skipped and the summary says "N skipped". The API tests create and wipe their own database (`copilot_api_test`) and Redis database 15
- Apply database migrations: `make db-migrate` (uses `DATABASE_URL`, default the `copilot_dev` database from `docker-compose.yml`)
- Load `/kb` into the database: `make index` (needs `OPENAI_API_KEY`), or `make index FAKE=1` for made-up vectors
- One test: `cd api && uv run pytest tests/test_smoke.py::test_package_imports`
- Lint: `make lint` (ends with "All checks passed!" and "N files already formatted")
- Auto-fix lint and formatting: `make format`
- Compare `/kb` with saved pages of the official reference (by hand, needs the network once to fetch): `cd api && uv run python -m copilot.kb.importer fetch <dir>`, then `compare <dir> ../kb`
- Write AFL for one request (real OpenAI calls; needs `OPENAI_API_KEY`, `STRONG_MODEL` and `CHEAP_MODEL` in `.env`): `make write MARKET=nse_fo TIMEFRAME=5min TEXT="..."`
- Review an AFL file, or fix one from an AmiBroker error (real OpenAI calls): `make review MARKET=... TIMEFRAME=... FILE=...` (add `APPLY=1` to rewrite it), `make fix MARKET=... TIMEFRAME=... FILE=... ERROR="..."`
- Run the Write test set (real OpenAI calls, costs money): `make evals`
- Run the Review test set through the checker only (free, no key, no database): `make evals-review` (ends with the measures; `verified_recall` must be 1.00 and `verified_false_alarms` 0). With the AI review too (real calls): `make evals-review-ai`
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
- Every example in `kb/examples` must pass the checker with nothing reported. If a test for the KB content fails, fix the content or, when the checker is wrong, fix the checker and say so; never loosen the test.
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
- The knowledge base tables are a copy of `/kb`, written only by the indexer. Never edit those rows by hand or from other code.
- A migration file that has been applied is never edited; a schema change is a new numbered file.
- Tests never call OpenAI. Code that needs embeddings takes an `Embedder` and code that needs the model takes an `LLM`; tests pass `FakeEmbedder` and `ScriptedLLM`.
- Text the user typed or pasted reaches a prompt only through `wrap_block` (or `wrap_user_text`), inside tags such as `<user_request>`, `<pasted_code>` and `<amibroker_error>`.
- When a checker rule changes, run `make evals-review`. A planted bug that is no longer found, or a new false alarm, is a regression.
- A written answer is "checked" only when the checker reports nothing at all, every requirement id is covered, and no out-of-scope function is used. Never relax this to make a run pass.
- Model ids have no defaults in code. They come from `STRONG_MODEL` and `CHEAP_MODEL`.
- Every API route, including health, refuses a request without the BFF key, before anything else runs. Never add an exception.
- A run takes a unit of quota before anything is saved and gives it back if no answer comes. A failure must never cost the user quota.
- API errors are JSON (`{"error": {"code", "message"}}`) and never show internals; another user's data answers 404.
- Every KB change bumps `kb_version` and goes through a pull request. Every user-reported bug becomes a new eval case.

## Documentation layout

Project documentation lives under `.claude/`, not at the repository root:

- `.claude/adr/`: architecture decision records (empty).
- `.claude/changes/`: change records, one dated file for each departure from the plan. Read the ones still in effect before starting a stage.
- `.claude/hooks/`: hook scripts, registered in `.claude/settings.json`. They block writing, staging or committing `.env` files; format and lint each edited Python file under `api/`; and lock test files while bug-fix mode is on. Only the user switches bug-fix mode, with `make bugfix-on` and `make bugfix-off`.
- `.claude/skills/testing-strategy/`: project skill for test plans. Its note that the stack is undecided is out of date.

## Keeping this file current

- When an architecture or behaviour change is made, update `ARCHITECTURE.md` or `spec.md` in the same change.
- When Claude makes the same mistake twice, add the correction to this file.
- Keep this file short. Detail belongs in the documents above.
