# Plan: AFL Copilot (v1)
From: intent.md, spec.md, ARCHITECTURE.md (all accepted). Author: Takshit. Status: draft.

This plan sets the build order for v1 and details the first two stages.
Each later stage gets its own detail (files, order, proof) added here
before work on it starts. When the code departs from the plan, the plan
is updated in the same commit.

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
