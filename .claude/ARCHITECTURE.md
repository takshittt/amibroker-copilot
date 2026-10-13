# Architecture: AFL Copilot (v1)
From: intent.md (accepted), spec.md (accepted). Author: Takshit. Status: accepted.

## 1. Requirements recap

**Functional**
- Signed-in users only. Modes: **Write**, **Review**, **Fix-from-error**.
- Market presets (all major markets, India-first) drive timing logic.
- Every answer: code + explanation + check results + doc links.
- Per-user daily rate limit. Conversation history.

**Non-functional**
| Concern | Target (v1) |
|---|---|
| Users | ~500 signed up, ~100 daily active |
| Load | ≤ 2,000 requests/day; peak ~2–3 concurrent pipelines |
| Latency | First progress event < 1 s; full answer p50 ~15 s, p95 < 45 s |
| Availability | Single region, best effort (~99%); no on-call |
| Cost | Hard daily spend cap on OpenAI; per-request token cap |
| Correctness | Never label unchecked code as "checked" |

**Constraints**
Solo developer; ~2–3 weeks to v1. Stack: Next.js + Python. LLM: OpenAI API.
Hosting in India (Mumbai region) for latency, across three providers:
Vercel (Next.js), Oracle Cloud (FastAPI, Redis, Caddy), Supabase (Postgres).

**Key insight driving the design**
The LLM writes; **deterministic code decides** what counts as correct.
The function list, the checker and the market table are plain data and
code. The AI is never the source of truth for them.

## 2. High-level design

```
                     ┌──────────────────────────────┐
  Browser ──HTTPS──▶ │  Next.js (web + BFF), Vercel │
                     │  - UI, session JWT in cookie │
                     │  - /api/* proxy, forwards JWT│
                     └──────────────┬───────────────┘
                                    │ HTTPS + SSE over the public internet
                                    │ (Authorization: Bearer JWT, X-Internal-Key)
                     ┌──────────────▼───────────────┐
                     │  FastAPI  (copilot-api)      │
                     │  ┌────────────────────────┐  │
                     │  │ Rate limiter / guards  │──┼──▶ Redis
                     │  ├────────────────────────┤  │
                     │  │ Orchestrator (pipeline)│  │
                     │  │  ├ Brief builder       │  │
                     │  │  ├ Retriever ──────────┼──┼──▶ Postgres + pgvector
                     │  │  ├ Generator ──────────┼──┼──▶ OpenAI API
                     │  │  ├ Checker (no AI)     │  │
                     │  │  └ Reviewer            │  │
                     │  ├────────────────────────┤  │
                     │  │ Market service         │  │
                     │  └────────────────────────┘  │
                     └──────────────────────────────┘

  Offline (git repo + CI):
  /kb/*.yaml|md|afl ──▶ indexer ──▶ embeddings ──▶ Postgres
  /evals/*          ──▶ eval runner ──▶ report (blocks merge on regression)
```

**Where each part runs** (all in the Mumbai region)
- **Vercel**: Next.js, web pages and BFF routes.
- **Oracle Cloud**: one instance running Docker Compose with FastAPI,
  Redis and Caddy. Caddy terminates HTTPS in front of FastAPI. Redis
  listens on the Compose network only, never on a public port.
- **Supabase**: Postgres with the pgvector extension. FastAPI connects
  over TLS.

**Why a BFF (Next.js proxies to FastAPI)**
The browser never talks to FastAPI directly. There's no CORS, and the
session JWT sits in an httpOnly cookie that page scripts can't read.

**Shared BFF key**
The BFF and FastAPI are on different providers, so FastAPI is reachable
from the internet. To keep it callable only by the BFF, every request
must carry an `X-Internal-Key` header equal to `BFF_SHARED_SECRET`, which
is set in the environment of both services. FastAPI rejects any request
without it, on every route including sign-up and login. The JWT check
below is unchanged and runs after it.

**Auth: one symmetric JWT**
Sign-in is email + password. There is no auth library and no OAuth
provider.
- FastAPI owns `users` and the password hashes (argon2id). On sign-up or
  login it issues a JWT signed with HS256: `sub` = `user_id`, plus `iat`
  and `exp` (7 days).
- One secret, `JWT_SECRET`, is set in the environment of both services.
- The BFF stores the token in an `httpOnly`, `Secure`, `SameSite=Lax`
  cookie. On each request it verifies the signature and expiry, then
  forwards the same token to FastAPI as `Authorization: Bearer`.
- FastAPI verifies the token again and takes `user_id` from `sub`. It
  accepts HS256 only.
- Logout clears the cookie. There is no refresh token and no server-side
  session store, so a token can't be revoked before it expires; rotating
  `JWT_SECRET` signs everyone out.

## 3. Components

| Component | Responsibility | Notes |
|---|---|---|
| Next.js web | Pages: landing, sign-up, login, chat (Write/Review), history, usage | Session JWT in an httpOnly cookie |
| BFF routes | Verify the session JWT → forward it to FastAPI with the shared BFF key → stream SSE back | No business logic |
| Auth | Sign-up, login, password hashing, issuing the JWT | In FastAPI; HS256, one shared secret |
| Rate limiter | Daily quota per user; global spend kill-switch | Redis counters |
| Orchestrator | Runs the pipeline as explicit steps; emits progress events | Plain Python, no agent framework |
| Brief builder | Request → structured strategy brief (JSON schema) | Cheap model |
| Retriever | Hybrid search + exact lookup + rerank | Postgres FTS + pgvector |
| Generator | Writes AFL from brief + retrieved context | Strong model |
| Checker | Lexer + rule engine; unknown functions, arg counts, mistakes | Pure Python, unit-tested |
| Reviewer | Review mode: checker findings + AI findings + fixes | AI findings labelled separately |
| Market service | Market presets, session times, DST rules | Data in DB, seeded from git |
| Indexer (offline) | KB files → DB rows + embeddings | Runs in CI on KB change |
| Eval runner (offline) | Runs test set, reports metrics | Runs in CI |

## 4. The pipeline (deep dive)

### 4.1 Write mode
```
request ─▶ [1 Brief] ─▶ missing critical info? ─yes─▶ ask ≤2 questions (no quota used)
                │no
                ▼
          [2 Decompose] ─▶ concepts[]
                ▼
          [3 Retrieve] per concept (hybrid) + exact lookup of named functions
                ▼
          [4 Rerank] ─▶ top 8–12 context items
                ▼
          [5 Generate] ─▶ {code, explanation_blocks[]}
                ▼
          [6 Check] ──pass──▶ [7 Answer: "checked"]
                │fail (attempt < 3)
                ▼
          re-retrieve for failing parts ─▶ regenerate with failures as feedback ─▶ [6]
                │fail (attempt = 3)
                ▼
          [7 Answer: code + "not fully checked" warning + failed checks]
```

**1. Brief** (cheap model, JSON-schema output)
```json
{
  "market_id": "nse_fo", "timeframe": "5min",
  "direction": "long_short",
  "entry": "...", "exit": "...", "stops": ["atr_trailing"],
  "sizing": "fixed_lots", "time_rules": ["no_entry_after 14:30", "exit_at 15:15"],
  "other_requirements": ["only trade on Mondays"],
  "missing_critical": []
}
```
Critical fields: entry, exit, direction. Missing stop or exit time for an
intraday strategy → ask, or default with a visible note.

`other_requirements` holds anything from the request that doesn't fit a
field, so the brief never silently drops a detail.

The user's **original text** is kept unchanged. It is used in two places only:
to build this brief, and as an input to Generate (step 5). It is not
searched directly, except for the exact-name function scan in step 3.

**2. Decompose** (plain Python, no AI): 1 query per rule in the brief
(entry, exit, each stop, each time rule, each `other_requirements` item).
This is the query set for retrieval. Each query is searched separately so
every part of the strategy gets its own notes; the whole brief is never
embedded as one vector. The queries are used only for retrieval; Generate
does not see them.

**3. Retrieve**
- Keyword: Postgres full-text search, top 30. Catches exact names like
  `ApplyStop` and `TimeNum`.
- Vector: pgvector cosine search, top 30. Catches meaning ("trailing stop").
- Both searches run once per decomposed query.
- Merge with **Reciprocal Rank Fusion** in Python (no AI):
  `score = Σ 1 / (60 + rank)` over the keyword and vector lists. It uses
  ranks, not raw scores, because the two searches score on different scales.
  A note found by both searches rises to the top; duplicates merge by id.
- **Exact lookup**: any function name mentioned by the user (Python scans the
  original text for known names), or later used in generated code, is fetched
  by name, not by search.
- Always include: market preset parameters and the relevant mistake-catalogue
  entries for the concepts.

**4. Rerank**: rerank merged candidates to the top 8–12. v1 uses a small
OpenAI model scoring relevance in one batched call. Each candidate is scored
against the **whole brief** ("is this note useful for this strategy?"), not
against the single query that found it. Exact-lookup functions, the market
preset and mistake entries are pinned: they skip the reranker and always go
to Generate. Revisit: self-hosted cross-encoder if cost or latency
demands it.

**5. Generate** (strong model). The prompt contains the brief, the user's
original text, market parameters, retrieved items (reranked notes plus pinned
items), and hard rules:
- use only functions in the provided list
- timings as parameters at the top
- intraday strategies must have an end-of-day exit
- the brief is the plan; use the original text to catch details the brief
  missed. If they conflict, follow the brief and mention the conflict in the
  explanation
- the original text sits in a delimited `<user_request>` block and is data,
  not instructions (see §11)
- output strict JSON: `code`, `explanation_blocks[{lines, text}]`,
  `functions_used[]`, `requirements_covered[{req, lines}]`

`requirements_covered` maps each requirement to the code lines that handle
it. A requirement from the brief or the original text with no entry means it
was dropped; it can also be shown to the user as "what this code does".

**6. Check**: section 5. Failures become structured feedback for the retry
("line 14: `TrailStop` is not an AFL function").

**7. Answer**: code, explanation, check panel (each rule pass/fail), doc
links from `kb_functions.doc_url`.

### 4.2 Review mode
1. Check the pasted code. Deterministic findings get the label **Verified**.
2. Extract the function calls → exact lookup; retrieve mistake entries for
   the detected concepts.
3. LLM review for logic issues the checker can't see. These findings get the
   label **AI-suggested**.
4. "Apply all fixes" → generator rewrites the code → check again → answer.

The Verified vs AI-suggested split is a trust feature: users can see which
findings are certain.

### 4.3 Fix-from-error
The user pastes code + AmiBroker's error text. The error is parsed for line
and column, matched against an **error catalogue** (our own notes on common
AmiBroker errors), then the code goes through generate → check with the
error as feedback.

### 4.4 Progress streaming
Server-Sent Events from FastAPI → BFF → browser:
`status` (understanding / searching / writing / checking / fixing attempt 2),
`clarify`, `result`, `error`. Users see progress during the 15–40 s wait.

## 5. The checker (deep dive)

```
AFL source ─▶ Lexer ─▶ tokens ─▶ Light parser ─▶ statements + calls + assignments
                                                     │
                                Symbol table ◀───────┘ (built-ins, user vars,
                                     │                  user-defined functions)
                                     ▼
                               Rule engine ─▶ findings[{rule, severity, line, msg, fix_hint}]
```

- **Lexer**: identifiers, numbers, strings, comments (`//`, `/* */`),
  operators, brackets. Handwritten; AFL's grammar is small.
- **Symbol table**:
  - built-in functions and variables from `kb_functions` / `kb_builtins`
    (`Buy`, `Sell`, `Close`/`C`, `BuyPrice` …)
  - **user-defined** `function name(...)` declarations in the code
  - assigned variables, with a simple type guess: *array* if assigned from an
    array-returning function or array expression, else *number*
- **Rules** (one Python function each, each with unit tests):

| Rule | Severity |
|---|---|
| Unknown function call | Critical |
| Wrong argument count (respecting optional params) | Critical |
| `if (...)` condition uses an array-typed value | Critical |
| `Ref(x, n)` with positive `n` in signal logic (look-ahead) | Critical |
| Unbalanced brackets / missing semicolon / `=` in a condition | Critical |
| Intraday time filter without end-of-day exit | Warning |
| Intrabar stop without matching `BuyPrice`/`SellPrice` | Warning |
| `SetTradeDelays` missing or inconsistent | Warning |
| Signals not cleaned with `ExRem` where needed | Warning |
| Hard-coded session times | Tip |

**Input**: the checker does not read files or tables itself. It takes a
`Catalog` object (functions, built-ins, markets, `kb_version`), built from
the `/kb` files in tests and from the `kb_*` rows at runtime. Both come
from the same files, so there is still one function list. A function
whose return type is `any` (array or number depending on its arguments)
counts as unknown for the type guess.

**Known limitation**: the type guess is heuristic, so some array/number
cases will be missed. Those are covered by AI review, and the set of cases is
grown from user reports.

**`#include`**: v1 can't see included files. The checker treats unknown
identifiers from included code as a Warning ("defined in an include?"),
not as Critical.

## 6. Data model (Postgres)

```
users(id, email unique, name, password_hash, created_at)
conversations(id, user_id, mode, market_id, timeframe, title, created_at)
messages(id, conversation_id, role, content, code, findings jsonb, created_at)
runs(id, message_id, status, attempts, checks jsonb,
     tokens_in, tokens_out, cost_usd, latency_ms, model_versions jsonb,
     kb_version, created_at)                -- one row per pipeline run
feedback(id, message_id, user_id, rating, comment, created_at)

kb_functions(name pk, params jsonb, returns, description, doc_url,
             category, kb_version)
kb_builtins(name pk, kind, type, description)
kb_chunks(id, kind[function|concept|example|mistake|error],
          ref, title, content, tsv tsvector, embedding vector(1536),
          tags text[], kb_version)
  index: GIN(tsv), HNSW(embedding)

markets(id pk, name, exchange, timezone,
        sessions jsonb,      -- [{name, open, close, days}]
        dst_rules jsonb,     -- e.g. MCX evening close by US DST season
        last_verified date)
```

Usage counters live in Redis (`quota:{user}:{yyyy-mm-dd}`, TTL 48 h), with
the daily totals copied into `runs` for analytics.

## 7. Knowledge base as code

```
/kb
  /functions/*.yaml   one file per AFL function (our own wording + doc link)
  /builtins.yaml
  /concepts/*.md      arrays vs loops, stops, sizing, trade delays, time filters
  /examples/*.afl     generic, tested strategies (+ .md description)
  /mistakes/*.yaml    bad example, good example, explanation, checker rule id
  /errors/*.yaml      AmiBroker error notes
  /markets.yaml       presets + DST rules + last_verified
  /VERSION            kb_version, one whole number
```
- `make validate-kb` checks every file against the record formats in
  `api/copilot/kb/schema.py`: unknown fields, missing fields and duplicate
  names are errors.
- Every KB change goes through a pull request and is versioned (`kb_version`).
- CI runs: schema validation → indexer (embed changed chunks only) → evals.
- The checker reads `kb_functions` and `kb_builtins`, so adding a function
  updates both the AI's context and the checker in one change.

## 8. API (FastAPI; called only by the BFF)

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/auth/signup` | `{email, password, name}` → `{token}` |
| POST | `/v1/auth/login` | `{email, password}` → `{token}` |
| POST | `/v1/conversations` | Create `{mode, market_id, timeframe}` |
| POST | `/v1/conversations/{id}/messages` | `{mode, text, code?, error_text?}` → **SSE stream** |
| GET | `/v1/conversations` | List the user's conversations |
| GET | `/v1/conversations/{id}` | Messages + code + findings |
| GET | `/v1/markets` | Market presets |
| GET | `/v1/me/usage` | Used / remaining today |
| POST | `/v1/messages/{id}/feedback` | Thumbs up/down + comment |

Every call except the two auth routes carries `Authorization: Bearer <JWT>`
(HS256, `user_id` in `sub`). The BFF puts the `token` from the auth routes
into the session cookie; it never reaches page scripts. Every call,
including the two auth routes, also carries `X-Internal-Key` (section 2).

**Quota rule**: 20 units per user per day to start (config value); one
unit per completed answer. Clarifying questions and
internal retries are free for the user.

## 9. Scale and cost

**Per request** (rough): brief + decompose + rerank on the cheap model ≈ 3–5k
tokens; generation on the strong model ≈ 8–12k input + 1–2k output per
attempt. Average attempts are expected ≈ 1.3.

**Controls**
- Max 3 attempts; per-request token cap; input code size limit (e.g. 30 KB).
- **Global daily spend cap**: when hit, new requests get a friendly "back
  tomorrow" message.
- Cache embeddings of repeated concept queries in Redis.
- Model names live in config, so they can be swapped without code changes.

**Models** (starting choice, decided 2026-10-14)
- Strong model, GPT-6.1 Sol: Generate, the Review LLM pass, "apply all
  fixes", Fix-from-error.
- Cheap model, GPT-6 Luna: Brief, Rerank.
- Embedding model, `text-embedding-3-small` (1536 dimensions): the
  indexer and the vector search in Retrieve. Changing it later means
  re-embedding the knowledge base and altering the `kb_chunks` column.
- The eval set can still overturn any of these choices. The exact API
  model IDs go in config when the pipeline is built.

**Scaling path**: v1 needs nothing special. FastAPI runs with several
workers; the bottleneck is OpenAI latency, not our CPU. Next steps when
needed: a job queue (arq/Celery) for pipelines, a Postgres read replica, more
API instances behind a load balancer.

## 10. Reliability and errors

| Failure | Handling |
|---|---|
| OpenAI timeout / 5xx | Retry with backoff (2×), then fail the request; quota not consumed |
| OpenAI rate limit (429) | Backoff; if persistent, return "busy, try again" |
| Invalid JSON from the model | One repair retry with strict schema, then fail |
| Checker crash | Return code labelled "not checked" and log; never "checked" |
| Client disconnects mid-stream | Cancel the pipeline, saving tokens |
| DB down | Fail fast with an error page |

## 11. Security
- Pasted code is **data**. It's placed in delimited blocks; instructions in
  code comments are ignored by prompt design, and the checker is
  deterministic.
- We **never execute** AFL; there is no sandbox to escape.
- FastAPI is internet-facing behind Caddy, but only the BFF can call it:
  every request needs the shared BFF key (section 2). Redis is not
  exposed publicly.
- Input size limits; per-user quota; basic abuse logging.
- Secrets in environment variables; OpenAI key server-side only.
- Passwords are stored only as argon2id hashes. Login attempts are rate
  limited per email and per IP in Redis. FastAPI sees Vercel's address,
  not the browser's, so the BFF forwards the browser's IP in a header;
  FastAPI trusts that header only when the shared BFF key matched.
- There is no self-service password reset in v1. The admin sets a new
  password with a command on the server.
- `JWT_SECRET` is at least 32 random bytes. Anyone who has it can sign a
  token for any user, so it lives only in the two services' environments.
  `BFF_SHARED_SECRET` is handled the same way.

## 12. Observability
- `runs` table = per-request trace: steps, attempts, checks, tokens, cost,
  latency, model and KB versions.
- Error tracking: Sentry (web + API).
- Simple admin dashboard: requests/day, cost/day, check pass rate, avg
  attempts, p50/p95 latency, thumbs-down rate.
- Thumbs-down + comment feeds new eval cases.

## 13. Deployment (v1)
- **Vercel**: builds and serves Next.js from the git repository, with the
  function region set to Mumbai.
- **Oracle Cloud (Mumbai)**: one instance running Docker Compose with
  FastAPI, Redis and Caddy for HTTPS.
- **Supabase (Mumbai)**: Postgres with the pgvector extension. Migrations
  and the indexer run against it from CI.
- Daily Postgres backups: Supabase's own if the plan includes them,
  otherwise a daily `pg_dump` to object storage.
- Local development uses a Compose file with Postgres (pgvector) and
  Redis, so tests do not need Supabase.
- GitHub Actions: tests → evals (on prompt/KB/checker changes) → build →
  deploy the API. Vercel deploys the web side itself.

## 14. Trade-offs

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Orchestration | Plain Python steps | LangChain / agent framework | Fully debuggable, explicit retries, no lock-in |
| Vector store | pgvector in Postgres | Pinecone / Qdrant | One database, small corpus (thousands of chunks) |
| Keyword search | Postgres FTS | Elasticsearch | Good enough at this size; one less service |
| Correctness | Deterministic checker | LLM-as-judge only | Exact names need exact checks; zero cost per check |
| Pipeline execution | Inline + SSE | Job queue | Simpler for v1; add a queue when concurrency grows |
| Hosting | Vercel + Oracle Cloud + Supabase | Single VPS | Managed web deploys and managed Postgres; costs a public FastAPI (needs the shared BFF key), three providers, and a function time limit on long streams |
| Password reset | Manual, by the admin | Email sender with reset links | No email service in v1; costs a manual step per request |
| Rerank | OpenAI small model | Self-hosted cross-encoder | No GPU/infra in v1 |
| KB | Files in git → DB | Scrape docs into DB | Copyright-safe, reviewable, versioned |
| Auth | Email + password, one HS256 JWT | Auth.js with Google + email | One token and one secret across both services, no OAuth setup; costs Google sign-in and early revocation |

## 15. What we'd revisit as it grows
- Job queue + horizontal API scaling once concurrent pipelines > ~10.
- Self-hosted reranker / smaller models to cut cost per request.
- Run the user's original text as one extra vector query alongside the
  decomposed ones, if evals show retrieval missing details the brief dropped.
- A proper AFL grammar (e.g. tree-sitter) if the light parser hits limits.
- Real compile checks via a Windows worker running AmiBroker.
- VS Code extension reusing the same `/v1` API.
- Multi-timeframe and custom backtester support (needs new checker rules).
- Paid tier → quotas per plan, billing service.

## 16. Open questions
None. Hosting, the three models and password reset were decided on
2026-10-14 (sections 9, 11 and 13).