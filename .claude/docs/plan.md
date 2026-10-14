# Plan: AFL Copilot (v1)
From: intent.md, spec.md, ARCHITECTURE.md (all accepted). Author: Takshit. Status: draft.

This plan sets the build order for v1 and details the first two stages.
Each later stage gets its own detail (files, order, proof) added here
before work on it starts. When the code departs from the plan, the plan
is updated in the same commit.

## Changes in effect

- 2026-10-14: the remaining stages are built before the OpenAI key is
  available, and the proofs that need a real model are owed until it
  arrives. See `.claude/changes/2026-10-14-build-without-openai-key.md`.

## Build order

The order follows the dependencies: the checker needs the function list,
the pipeline needs the checker and the database, the API needs the
pipeline, and the website needs the API.

| # | Stage | What exists at the end | Proof |
|---|---|---|---|
| 0 | Scaffolding | Python project, one test command, CI | `make test` and `make lint` pass locally and in CI |
| 1 | KB format and seed | File formats, validator, about 40 functions, built-ins, markets | Every file in `/kb` passes validation in CI |
| 2 | Checker | Lexer, parser, symbol table, all 10 rules | Rule tests pass; fixture files give the expected findings; tests run with no network |
| 3 | Full function list | Every AFL function with name, parameters and return type | Checker reports no unknown function on the example strategies |
| 4 | Database and indexer | Postgres schema, migrations, KB files loaded with embeddings; local Postgres in Compose for development, Supabase for production | Indexer run twice gives the same rows; search returns `ApplyStop` for "trailing stop" |
| 4b | KB content | Concept notes, example strategies and error notes, in the formats stage 4 defined | Every example passes the checker; `make validate-kb` passes; the notes are indexed |
| 5 | Write pipeline | Steps 1–7 as a command-line tool, no HTTP | 10 sample requests give checked code; eval runner reports the spec section 10 metrics |
| 6 | Review and Fix-from-error | Both modes on the command line | Planted bugs in the Review samples are found; findings carry Verified or AI-suggested |
| 7 | API | Auth, shared BFF key check, conversations, SSE stream, quota, spend cap, admin command to reset a password | API tests pass; a request without the BFF key is rejected; a failed upstream call uses no quota |
| 8 | Website | Landing, sign-up, login, chat, history, usage | A full Write and a full Review work in the browser |
| 9 | Deployment | Next.js on Vercel; FastAPI, Redis and Caddy in Compose on Oracle Cloud; Postgres on Supabase; backups; API deploy from CI | The site answers on its domain; a 45-second answer stream completes through Vercel; a backup restores |

The eval set (`/evals`) grows from stage 2 onward: Review samples first,
because the checker alone can be scored on them, then Write tasks at
stage 5.

## Repository layout

```
api/                  FastAPI service and all Python code
  copilot/
    kb/               file formats, validator, catalog loader
    checker/          lexer, parser, symbols, engine, rules/
  tests/
kb/                   knowledge base files (see ARCHITECTURE.md section 7)
evals/                test set and eval runner
web/                  Next.js (stage 8)
Makefile              test, lint
.github/workflows/    CI
```

Python 3.12, `uv` for dependencies, `pytest` for tests, `ruff` for lint
and format.

## Stage 0: Scaffolding

**Files that change** (all new)
`api/pyproject.toml`, `api/copilot/__init__.py`, `api/tests/test_smoke.py`,
`Makefile`, `.github/workflows/ci.yml`, `.env.example`.

**Order of work**
1. Create the Python project in `api/` with pytest and ruff.
2. Add `make test` and `make lint` at the repository root. Both exit
   non-zero on failure.
3. Add a CI workflow that runs both on every push and pull request.
4. Replace "Current state" in CLAUDE.md with the real commands.

## Stage 1: KB format and seed

Status: done. Takshit verified the market session times on 2026-10-14.

**Files that change** (all new)
`api/copilot/kb/schema.py`, `api/copilot/kb/catalog.py`,
`api/copilot/kb/__main__.py`,
`api/tests/kb/test_schema.py`, `api/tests/kb/test_catalog.py`,
`api/tests/kb/test_seed.py`,
`kb/functions/*.yaml`, `kb/builtins.yaml`, `kb/markets.yaml`,
`kb/VERSION`. `pydantic` and `pyyaml` are added as dependencies.

**What departed from the first draft of this stage**
- `returns` has a fifth value, `any`, for functions whose result is an
  array or a number depending on the arguments (`IIf`, `Max`, `Min`,
  `abs`, `Nz`). The stage 2 `if`-on-array rule must treat `any` as
  unknown and not fire.
- `kb_version` is one whole number in `kb/VERSION`.
- The validator is a command, `make validate-kb`, which CI runs.
- A market's `last_verified` may be empty, meaning not yet checked. The
  validator lists those markets but does not fail.
- `ApplyStop` and `Param` are recorded more leniently than the reference
  page's syntax line (`exitatstop`, and `min`/`max`/`step`, are marked
  optional) so that short calls are not reported as Critical. Takshit
  confirmed on 2026-10-14 that both short calls compile in AmiBroker.
- Functions that take any number of arguments (`printf`, `StrFormat`)
  were not in the seed. Stage 3 added `variadic` for them.

**Order of work**
1. Define the function record: `name`, `params` (each with `name`, `type`,
   `optional`), `returns` (array, number, string, none or any),
   `description`, `doc_url`, `category`.
2. Define the built-in record: `name`, `kind` (variable or constant),
   `type`, `description`, and `aliases` (`C` for `Close`).
3. Write the validator. It rejects unknown fields, missing fields and
   duplicate names.
4. Write the catalog loader: `/kb` files in, one in-memory `Catalog` out.
   The checker takes a `Catalog` as input.
5. Write the seed: the functions the rules and test fixtures need, about
   40 (`MA`, `EMA`, `RSI`, `ATR`, `Cross`, `Ref`, `IIf`, `ExRem`,
   `ApplyStop`, `SetTradeDelays`, `TimeNum`, `Param`, `Plot`, `HHV`,
   `LLV`, `ValueWhen` and others), the price and signal built-ins, and
   the v1 markets with both MCX seasonal rules.
6. Add a CI step that validates every file in `/kb`.

## Stage 7: API

Status: built and tested against the Docker Postgres and Redis, with a
scripted model. Started once locally and called with `curl`: the stream
arrives step by step. **Not yet run with real OpenAI calls, and not
deployed.**

**Files** (all new unless noted)
`api/copilot/api/`: `app.py` (routes), `security.py`, `limits.py`,
`store.py`, `answers.py`, `streaming.py`, `main.py` (start from the
environment); `api/copilot/admin.py`; `api/migrations/0003_message_answers.sql`;
tests in `api/tests/api/`. Changed: `config.py`, the Write pipeline
(follow-up messages), `Makefile`, CI (a Redis service), `.env.example`.
New dependencies: `fastapi`, `uvicorn`, `pyjwt`, `argon2-cffi`, `redis`,
`psycopg-pool`; `httpx` for tests.

**What was decided** (agreed 2026-10-14)
- **Libraries.** PyJWT signs the token and argon2-cffi hashes passwords.
  CLAUDE.md's "no auth library" is read as no auth framework (Auth.js,
  fastapi-users): the cryptography is not written by hand.
- **Quota is taken before a run and given back** when the run gives no
  answer: a clarifying question, an error from the model or from our
  side, or a cancelled run. It is taken before the user's message is
  saved, so a refused request leaves nothing behind.
- **The day for quota and spend runs midnight to midnight India time**
  (`QUOTA_TIMEZONE`).
- **Two routes added** to the architecture's table: follow-up messages
  in Write (the conversation's last code is the code to change, and a
  reply to a clarifying question is added to the request that prompted
  it), and `POST /v1/messages/{id}/apply-fixes`.
- **A spend cap needs prices**: with `DAILY_SPEND_CAP_USD` set, the API
  refuses to start unless all four model prices are set.
- **Passwords**: 10 to 128 characters, nothing else required. Emails are
  stored in lower case.

**Also decided while building**
- The BFF key is checked first, on every route including health and
  unknown paths, before the body is read. The browser's IP comes from
  the BFF's `X-Client-IP` header, trusted only because the key matched.
- Wrong password and unknown email get the same answer. Login is
  limited per email and per IP (10 in 15 minutes); a successful login
  clears the count for that email. Sign-ups are limited per IP (5 an hour).
- A hash made with older argon2 settings is replaced at the next login.
- Another user's conversation or message answers 404, the same as one
  that does not exist.
- The API checks every limit itself (sizes of text, code and error
  text, and of the whole body) rather than trusting the BFF.
- Every error is JSON: `{"error": {"code", "message"}}`. Unexpected
  errors are logged and never show internals.
- The answer is saved with the message (`messages.status` and
  `messages.answer`), so history shows exactly what was shown live. A
  review's copy of the reviewed code is stored for "apply all fixes" but
  never sent back to the browser.
- The catalog is read from the database when the API starts. After
  `make index`, the API must be restarted to see a new `kb_version`.
- Tests use their own database (`copilot_api_test`, created by the
  tests) and Redis database 15, because the API commits what it writes.

**Proof**
- API tests pass (146 of the 1167).
- A request without the BFF key, or with a wrong one, is refused with
  401 on every route; tested for 12 routes and 5 kinds of wrong key.
- A failed upstream call uses no quota: tested for a model failure and
  for a crash on our side.

**Known gaps**
- Signing out early is not possible before a token expires; rotating
  `JWT_SECRET` signs everyone out (as designed).
- Embeddings of repeated queries are not cached in Redis yet.
- There is no admin dashboard and no Sentry yet (stage 9).

## Stage 6: Review and Fix-from-error

Status: built. The checker half is proven on a test set. **The model
half has only run against a scripted model**: AI-suggested findings and
the rewritten code are owed until the OpenAI key is available.

**Files** (all new unless noted)
`api/copilot/pipeline/review.py`, `rewrite.py`, `fix_error.py`,
`tracking.py`; the commands `api/copilot/review.py` and `fix.py`;
`evals/review/*.afl` (32 samples); tests. Changed: `evals.py` (a
`review` mode beside `write`), `prompts.py`, `search.py`, `config.py`,
the `eod_exit` rule, `Makefile`.

**What each mode does**
- **Review**: the checker runs first; its findings are labelled
  Verified. The model is then shown the code, those findings, the
  functions the code calls, and the mistake entries, and asked only for
  what the checker cannot see; its findings are labelled AI-suggested.
  The two are never merged.
- **Apply all fixes**: the model rewrites the code to fix the listed
  findings, the checker examines the result, and what still fails goes
  back, up to the attempt limit.
- **Fix-from-error**: the error text is read for its number, line and
  column, matched to our own note on that error, and the code is
  corrected the same way.

**What was decided while building it**
- If the model fails during a review, the Verified findings are still
  returned, with a note that the AI review could not be completed.
- A review never says code is correct. With no findings it says so and
  adds that this proves nothing; after a checker crash it says there
  are no Verified findings and that this does not mean the code is fine.
- AI findings with a line number outside the code are kept but shown as
  about the whole code. At most 15 are shown (a setting).
- The mistake entries that no rule catches are always shown to the
  reviewing model: they are the list of what it is there to find.
- Corrected pasted code is "checked" when the checker has no Critical
  or Warning finding. A Tip does not fail it, unlike newly written
  code, because it is the trader's own code; the Tip is passed on.
- When fixing, functions already in the trader's code stay allowed,
  even from areas v1 does not write.
- Fixes for AI-suggested findings cannot be verified, and the answer
  says so. A fix from an error says it has not been compiled, since we
  never run AFL.
- Pasted code and pasted error text reach the model only inside
  `<pasted_code>` and `<amibroker_error>` blocks, as data.

**Proof**
- `make evals-review` runs 32 samples through the checker: 17 planted
  bugs the checker must find, 10 only a reader can find, 6 clean
  samples. Result: 17 of 17 found, no false alarm. A test repeats this
  on every run, so a rule change that loses a bug fails CI.
- Findings carry "Verified" or "AI-suggested" in every result and in
  the command's output; tests assert both.
- Owed: `make evals-review-ai`, which scores the 10 AI-only bugs.

**A checker fault found by the test set and fixed**
The first run found 16 of 17. `eod_exit` missed an intraday strategy
with no end-of-day exit, because `Sell = ExRem(Sell, Buy)` mentions
`Buy` and `Buy` had a time filter. The rule now ignores the other
signals when it asks whether an exit depends on the time.

**Known gaps**
- The 32 samples are made from the 8 strategy examples in `/kb`, which
  the reviewing model is also shown as notes. That is fine for the
  checker's score but may flatter the AI score.
- An AI finding counts as correct when it is within three lines of the
  planted bug; nothing checks that it names the right problem.
- A review looks at one piece of code. It does not know the trader's
  intent beyond the code's own comments and names.

## Stage 5: Write pipeline

Status: built and tested against a scripted model. **Not yet run with a
real model.** The stage's proof (10 sample requests give checked code;
the eval runner reports the spec section 10 measures) is owed until the
OpenAI key and the model ids are available. See
`.claude/changes/2026-10-14-build-without-openai-key.md`.

**Files** (all new)
`api/copilot/pipeline/`: `llm.py`, `prompts.py`, `brief.py`,
`decompose.py`, `retrieve.py`, `rerank.py`, `generate.py`,
`orchestrator.py`, `setup.py`; `api/copilot/write.py` (the command);
`api/copilot/evals.py` (the eval runner); `evals/write/*.yaml` (10
tasks); tests in `api/tests/pipeline/` and `api/tests/db/`. Changed:
`config.py` (model ids, limits, prices), `search.py`, the checker
(`called_functions`), `Makefile` (`make write`, `make evals`, and it now
reads `.env`).

**What was decided while building it**
- **When an answer counts as checked.** The checker must report nothing
  at all, not even a Tip, every requirement must be accounted for, and
  no function may come from an area v1 does not write. Generated code
  is held to a stricter standard than pasted code, because CLAUDE.md
  requires generated timings to be parameters.
- **Model ids have no defaults.** `STRONG_MODEL` and `CHEAP_MODEL` must
  be set; the commands refuse to run without them. The ids in the
  design ("GPT-6.1 Sol", "GPT-6 Luna") are unconfirmed.
- **The brief gained `kind`** (strategy, indicator or exploration) and
  `goal`. Entry, exit and direction are required only for a strategy.
- **Clarifying questions are fixed sentences chosen by code**, one for
  each missing field, two at most. The model does not write them.
- **Each requirement gets an id** (R1, R2, ...). The model must map
  every id to lines of code. A missing id is fed back like a checker
  finding and, if still missing at the end, listed as a failed check.
- **`functions_used` is not asked of the model.** The functions and the
  doc links are read from the code itself.
- **Merging search results.** Keyword and vector results are merged
  with Reciprocal Rank Fusion for each query, and the queries' lists
  are then interleaved. Summing ranks across all queries, as first
  written, let notes that were middling for every part crowd out the
  best note for one part.
- **Functions the user names** are looked up exactly only when the word
  is clearly a function: followed by a bracket, spelt as AmiBroker
  spells it with internal capitals, or an all-capitals name of three or
  more letters. Many function names are ordinary words (Max, Day, Hold).
- **Mistakes shown to the model** are chosen by tag from the KB:
  `backtest` for every strategy, `intraday` for intraday timeframes, the
  rule's own entry after a failed check, plus the best three found by
  searching.
- **The generator sees** full notes for retrieved items, and the bare
  names of every function in the categories v1 writes from, built from
  the Catalog at run time.
- **If reranking fails**, the search order is used and the run record
  says so.
- **A checker crash** ends the run at once with "not checked".

**Deferred to stage 7**
Writing the run record to the `runs` table, the quota and spend cap,
caching query embeddings in Redis, and wiring the stop flag to a client
disconnect.

**Known gaps**
- The prompts have never met a real model.
- The eval set has 10 tasks; the spec wants 60 to 100.
- A request that mixes several strategies, or asks for a change to
  earlier code, is not handled: follow-up messages come with the API.

## Stage 4b: KB content

Status: done. `kb_version` is 4. All of it is written in our own words;
none of it has been reviewed by a second person yet.

**What `/kb` now holds besides functions, built-ins and markets**
- 12 concept notes (`kb/concepts/*.md`): arrays, `IIf`, signals and
  `ExRem`, `ApplyStop`, position sizing, trade delays and prices,
  look-ahead bias, time filters and the end-of-day exit, the data feed's
  time zone, parameters, plotting, explorations.
- 10 example strategies (`kb/examples/`): daily and intraday, long-only
  and long-short, on NSE equity, NSE F&O, MCX and crypto, plus one
  exploration and one indicator.
- 19 error notes (`kb/errors/*.yaml`). Every error number was checked
  against AmiBroker's own error list; the wording is ours.
- 14 mistake entries: the ten that match checker rules, and four the
  checker cannot see (`checker_rule: null`): trading on `Zig`/`Peak`,
  a time written as 915, `Cross` with its arguments swapped, and a level
  that contains the current bar.

**Tests that tie the content to the checker** (`api/tests/kb/test_content.py`
and `test_mistakes_seed.py`)
- Every example passes the checker with nothing reported, not even a Tip.
- Every code block in a concept note has no Critical finding.
- A mistake entry's wrong example sets off the rule it names and no
  other; an entry with no rule sets off nothing; every right example is
  clean.
- A function named as `Name(` in a note must exist.

**Changed outside `/kb`**
- The `eod_exit` rule no longer fires for a market that trades all day,
  every day (crypto). `Market.never_closes` decides.
- The mistake entry for `=` in a condition now says what AmiBroker does:
  it gives warning 501 and carries on, with the variable changed. The
  checker still reports it as Critical, since the logic is silently
  wrong.

**A fault found in stage 4 and fixed here**
- Vector search filtered by `kind` sometimes returned fewer rows than
  asked for, or none. The cause was the HNSW index, which is approximate
  and filters after picking candidates. It showed up as a test that
  failed about one run in eight. Migration `0002_exact_vector_search.sql`
  drops the index, so the search is now an exact scan; a test runs 200
  filtered searches and requires every one to fill its limit.
- Three search tests that named exact results were rewritten, because
  the new notes changed the rankings: a concept note with a function's
  name in its title now ranks beside the function itself.

**Known gaps**
- `eod_exit` accepts any exit whose own condition depends on
  `TimeNum()`. An exit built from an opening-range level, which is
  worked out from the time, passes even with no end-of-day exit.
  (Stage 6 closed the related gap where a time filter on entries was
  counted through `ExRem`.)
- The four mistakes with no rule are caught only by the AI review, which
  does not exist until stage 6.
- More examples and error notes will be wanted as the eval set grows.

## Stage 4: Database and indexer

Status: done on local and CI Postgres. Not yet run against Supabase, and
search by meaning has not been tried with real embeddings (no OpenAI key
was available).

**Files** (all new unless noted)
`api/migrations/0001_initial.sql`, `api/copilot/config.py`,
`api/copilot/db/` (`connection.py`, `migrate.py`, `kb.py`),
`api/copilot/embeddings.py`, `api/copilot/chunks.py`,
`api/copilot/indexer.py`, `api/copilot/search.py`,
`api/copilot/kb/notes.py`, `kb/mistakes/*.yaml` (ten),
tests under `api/tests/db/` and `api/tests/`; changed: `schema.py`,
`kb/__main__.py`, `Makefile`, CI, `.env.example`; also new:
`docker-compose.yml` and `docker/postgres-init.sql`. New dependencies:
`psycopg` and `openai`. `kb_version` is 3.

**What was decided while building it**
- Migrations are numbered plain SQL files applied by a small runner
  (`make db-migrate`). No Alembic and no ORM.
- Local development uses `docker-compose.yml`: Postgres 17 with
  pgvector (databases `copilot_dev` and `copilot_test`) and Redis,
  started with `make services-up`. On the development Mac, Docker runs
  through Colima. The production Compose file (FastAPI, Redis, Caddy)
  is a separate file, written at stage 9.
- The database code is synchronous (`psycopg` 3). FastAPI can run it in
  its thread pool at stage 7.
- `index_kb` does not commit; the command line wraps it in one
  transaction, so a failed run changes nothing.
- Chunks are re-embedded only when their title or text changes, or when
  the embedding model changes. A function with no description gets no
  chunk; it is still found by exact lookup.
- Keyword search matches any word of the query. Chunks with more of the
  different words come first, then a title-weighted rank, so an exact
  function name beats a long note that mentions it.
- Database tests share one connection and never commit. Without a
  reachable test database they are skipped with the reason shown; with
  `REQUIRE_DB` set, as in CI, they fail instead.
- Four new note formats: mistakes and error notes as YAML, concept notes
  as Markdown with a header, examples as an `.afl` file with a `.md`
  beside it. A test runs the checker over every mistake entry: the wrong
  example must set off its rule and no other, the right one must be
  clean.

**Proof**
- The indexer run twice gives identical rows and embeds nothing the
  second time (a test, and `make index FAKE=1` twice on the dev
  database).
- Keyword search for "trailing stop" returns `ApplyStop` first.
- The catalog read back from the database equals the one from the
  files, and the checker gives the same result with either.

**Still open**
- Vector search with real embeddings: run `make index` with
  `OPENAI_API_KEY` set, then search for "trailing stop".
- Supabase: apply the migrations and run the indexer there. Believed,
  not confirmed: free projects pause after about a week without
  activity and have no automatic backups; the direct connection is
  IPv6-only, so CI and Oracle Cloud may need the pooled address with
  `DB_PREPARED_STATEMENTS=false`.

## Stage 3: Full function list

Status: done. `/kb` holds 447 functions (`kb_version` 2): every function
in the official alphabetical index, plus `RSIa` and `CCIa`, which share
a page with `RSI` and `CCI`.

**Files that changed**
`api/copilot/kb/schema.py` (new fields), `api/copilot/kb/importer.py`
and `api/tests/kb/test_importer.py` (new), `kb/functions/*.yaml` (402
new files), `kb/VERSION`, `api/copilot/checker/rules/arg_count.py`, two
new samples in `api/tests/fixtures/afl/`.

**How it was built**
1. The function record gained `variadic` (any number of further
   arguments), `since` (the AmiBroker version that introduced the
   function) and 14 more categories. `description` became optional.
2. `importer.py` reads saved pages of the official reference and takes
   only facts from them: name, parameter names, which parameters have
   defaults, return type, category and version. It is run by hand
   (`python -m copilot.kb.importer`), never in CI and never by the
   checker. It never overwrites an existing file.
3. The importer was first compared with the 45 hand-checked seed
   functions. It reproduced all of them except `ApplyStop` and `Param`,
   which are deliberately more lenient than the reference.
4. About 20 pages have a cut-off syntax line, an empty RETURNS cell, a
   misspelt name or a variable argument list. Each has a hand correction
   in the importer's `OVERRIDES` table, with the reason.
5. Descriptions in our own words were written for the functions v1
   generates from (indicators, signals, stops, sizing, time, plotting,
   parameters, maths, explorations, statistics, patterns): 237 of the
   447 have one. A test keeps those categories fully described. The
   reference's own descriptive text is not stored anywhere.

**Proof**
- `make validate-kb` reports 447 functions.
- `python -m copilot.kb.importer compare` reports 0 functions missing
  from `/kb`.
- A sample that uses functions from beyond the seed gives no findings.
- The proof in the build-order table, "no unknown function on the
  example strategies", could not be used as written because
  `/kb/examples` does not exist yet.

**Known gaps**
- Where the reference leaves out a default that AmiBroker has, a valid
  short call is reported as a wrong argument count. `Param` and
  `ApplyStop` were found this way. Each new case is a KB fix and an
  eval case.
- A return type of `array` is trusted from the reference except for
  maths functions and `IsEmpty`/`IsTrue`, which give a number for a
  number and are recorded as `any`.
- `Peak`, `Trough`, `PeakBars`, `TroughBars` and `ZIG` look ahead. Their
  descriptions say so, but no checker rule flags them yet.
- Built-in constants beyond the seed (`inDaily`, `actionIndicator`) are
  not in `builtins.yaml`. The checker does not flag unknown identifiers,
  so nothing is reported wrongly because of that.

## Stage 2: Checker

Status: done. The exact condition under which each rule fires is in
ARCHITECTURE.md section 5.

**What was decided while building it**
- `status` is `failed` when there is any Critical or Warning finding. A
  Tip alone passes.
- `CheckResult` also holds `checks`, one entry for each rule (`passed`,
  `failed` or `skipped`), for the answer's check panel.
- When the code does not parse, only the `syntax` rule reports and the
  other nine are `skipped`: they would be judging code that was only
  partly read. Parsing stops at the first token that makes no sense, so
  one mistake is not reported many times; missing semicolons are the
  exception and are all reported.
- A function written in the code is checked for argument count against
  its own parameter list.
- The parser accepts `for`, `while`, `do`, `switch`, subscripts and
  `procedure`, because pasted code contains them.
- The samples in `api/tests/fixtures/afl/` say in header comments what
  the checker must report, so they can be reused as Review eval cases.
  Nothing was added to `/evals` in this stage.

**Files that change** (all new, under `api/copilot/checker/` and
`api/tests/checker/`)
`lexer.py`, `parser.py`, `symbols.py`, `engine.py`, `findings.py`,
`rules/<one file per rule>.py`, a test file for each, and
`api/tests/fixtures/afl/` holding good and bad AFL samples.

**Public interface**
`check(source, catalog, context) -> CheckResult`. `context` carries the
timeframe and market, which the end-of-day-exit rule needs. `CheckResult`
holds the findings and one status: `passed`, `failed` or `checker_error`.

**Order of work**
1. Lexer: identifiers, numbers, strings, both comment styles, operators,
   brackets. Every token keeps its line and column.
2. Parser: statements, assignments, function calls with argument counts,
   `function` declarations, `if` conditions, `#include` lines.
3. Symbol table: built-ins from the catalog, user-defined functions, and
   assigned variables with the array or number guess.
4. Engine and finding type: `rule`, `severity`, `line`, `message`,
   `fix_hint`. Any exception inside the checker is caught at `check()`
   and returned as `checker_error`, never as `passed`.
5. Critical rules, in this order: syntax (brackets, semicolons, `=` in a
   condition), unknown function, wrong argument count, `if` on an array,
   look-ahead `Ref`.
6. Warning rules: end-of-day exit, intrabar stop prices,
   `SetTradeDelays`, `ExRem`. Then the Tip rule: hard-coded session times.
7. `#include` handling: unknown identifiers become a Warning when the
   file has an `#include`.
8. Fixture test: each sample file lists its expected findings; one test
   runs the checker over all of them.

Each rule is written test-first: a sample that should fail, a sample that
should pass, then the rule.

**Proof**
- `make test` passes, with at least one passing and one failing case per rule.
- The checker package imports nothing from the network or OpenAI; a test
  asserts this.
- A forced exception inside a rule gives `checker_error`.

## Risks

- **Incomplete function list gives false alarms.** A real AFL function
  missing from the list is reported as Critical "unknown function".
  Stage 3 therefore records every function's name, parameters and return
  type before the pipeline is built; descriptions in our own words can
  follow for the most-used functions first.
- **Writing the full list is the largest non-code task.** AFL has several
  hundred functions. It may not fit the 2–3 week target alongside the
  code and should be started early, in parallel with stage 2.
- **The checker reads files, the architecture says tables.** The plan has
  the checker take a `Catalog` object, built from `/kb` files in tests
  and from the database rows at runtime. Both come from the same files,
  so there is still one function list. ARCHITECTURE.md section 5 says
  this since stage 1.
- **The light parser may not cover real-world AFL.** Pasted code in Review
  mode is less tidy than generated code. A parse failure must give a
  syntax finding or `checker_error`, never a pass.
- **The array or number guess is heuristic.** Some `if`-on-array cases
  will be missed (ARCHITECTURE.md section 5). The rule should only fire
  when the type is known, to avoid false Criticals.

- **FastAPI is reachable from the internet.** Vercel and Oracle Cloud
  share no private network. The shared BFF key (ARCHITECTURE.md section
  2) is what keeps FastAPI callable only by the BFF, so it is built and
  tested in stage 7, before anything is deployed.
- **Vercel limits how long a function can run.** An answer stream lasts
  up to about 45 seconds. The limit on the chosen Vercel plan must be
  checked at stage 8.
- **Supabase and Oracle Cloud tier limits.** Check at stage 4 whether the
  Supabase plan pauses idle projects and whether it includes backups.
  Check at stage 9 whether the Oracle instance is ARM, since the Docker
  images must then be built for ARM.
- **Model names are recorded as given.** The exact API model IDs for
  GPT-6.1 Sol and GPT-6 Luna are confirmed against OpenAI's model list
  at stage 5.

## Decisions

| Decision | Outcome | Status |
|---|---|---|
| Model for each pipeline step | GPT-6.1 Sol for Generate, Review, apply fixes and Fix-from-error; GPT-6 Luna for Brief and Rerank | Decided 2026-10-14 |
| Password reset | Manual, by the admin; no email sender in v1 | Decided 2026-10-14 |
| Hosting | Next.js on Vercel; FastAPI, Redis and Caddy on Oracle Cloud; Postgres on Supabase | Decided 2026-10-14 |
| Embedding model | `text-embedding-3-small`, 1536 dimensions | Decided 2026-10-14 |
