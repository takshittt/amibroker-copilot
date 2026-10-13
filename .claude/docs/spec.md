# Spec: AFL Copilot (v1)
From: intent.md (accepted). Author: Takshit. Status: Complete.

## 1. Product summary
A website where a signed-in trader can:
- **Write**: describe a strategy in plain English → get checked, working AFL.
- **Review**: paste existing AFL → get a list of bugs and suggested fixes.

Primary audience: Indian traders (NSE, BSE, MCX). Also usable for world
markets. VS Code extension is a future version, not v1.

## 2. User flows

### Sign-in
- Sign-in is required to use anything. Email + password; no Google
  sign-in in v1.
- Landing page (public) explains the product with an example; everything
  else is behind login.

### Write
1. User picks a **market preset** (e.g. NSE equity, NSE F&O, MCX, NYSE,
   Crypto 24x7) and timeframe (e.g. 5-min, daily).
2. User describes the strategy in plain English.
3. If something important is missing (stop-loss? exit time? long/short?),
   the copilot asks up to 2 short clarifying questions.
4. Copilot returns:
   - AFL code (copy button)
   - plain-English explanation of each block
   - "checks passed" panel showing what was verified
   - links to the official AmiBroker docs for every function used
5. User can ask for changes in follow-up messages.
6. **Fix-from-error**: user pastes an AmiBroker error message → copilot
   fixes the code.

### Review
1. User pastes AFL code.
2. Copilot returns a list of findings, each with: severity (Critical /
   Warning / Tip), the line, what's wrong in plain English, and a fix.
3. One click: "apply all fixes" → corrected code.

### History
- Each user sees their past conversations and code.

## 3. Market presets (timings)
Timing logic in AFL is a common source of bugs, so markets are data, not
guesswork.

- A **market table** stores, for each market: name, exchange, time zone,
  session open/close, pre-open, any extra/evening sessions, and
  daylight-saving rules where relevant.
- v1 markets: NSE (equity, F&O), BSE, MCX, NYSE/NASDAQ, LSE, crypto
  (24x7). The table is easy to extend.
- MCX's evening close changes with US daylight saving: stored as two
  seasonal rules, not one fixed time.
- Generated code puts timings in **editable parameters at the top**
  (`Param` / variables), never buried in logic.
- **Data time zone warning**: AmiBroker uses the time stamps of the user's
  data feed. If the feed is in a different time zone than the exchange,
  times will be wrong. The copilot asks or warns about this whenever
  time filters are used.
- The table records a "last verified" date; timings are reviewed
  periodically.

## 4. Knowledge base (what the copilot knows)
| Source | What we store | Shown to user? |
|---|---|---|
| Function list | Our own record per AFL function: name, inputs, input types, return type (array/number), one-line description in our words, official doc link | Description + link only |
| Concept notes | Our own short notes on key topics: arrays vs loops, `IIf`, `ExRem`, stops (`ApplyStop`), position sizing, trade delays, plotting, time filters | Yes |
| Example strategies | Generic, tested example AFL written for this project (not my private strategies) | Yes |
| Mistake catalogue | Known AFL mistakes with bad/good examples (feeds both retrieval and the checker) | Yes |

AmiBroker's own docs and forum text are used only as reference while we
write our own records. Their text is not stored or shown.

## 5. How it answers (pipeline)
1. **Understand**: turn the request + market preset into a structured
   brief (entry, exit, stops, sizing, time rules, timeframe).
2. **Break down**: split into concepts (e.g. "opening range", "ATR
   trailing stop", "exit at 3:15").
3. **Search (hybrid)** per concept: keyword search (exact function names)
   + meaning-based vector search, merged.
4. **Rerank**: keep only the most relevant 8–12 items.
5. **Write**: generate AFL using only retrieved functions.
6. **Check** (section 6). If it fails → re-search the failing part and
   rewrite. Max 3 attempts.
7. **Answer**: if checks still fail after 3 attempts, show the code with
   a clear warning listing what failed, never as "checked".

Review mode uses steps 3–6 on the pasted code, plus the checker directly.

## 6. The checker
Runs on every generated or reviewed piece of code. Deterministic code,
not AI.

- **Unknown functions**: every function call must exist in the function list.
- **Wrong number of inputs** per function.
- **Common mistakes** (from the mistake catalogue), v1 set:
  - `if` used on an array instead of `IIf`
  - signals not cleaned with `ExRem` where needed
  - look-ahead: `Ref(x, positive)` used in signals
  - `SetTradeDelays` not set / inconsistent with price arrays
  - intrabar stop without matching `BuyPrice` / `SellPrice`
  - time filters without an end-of-day exit for intraday strategies
  - hard-coded timings instead of parameters
- **Basic syntax**: balanced brackets, semicolons, assignment vs `==`.

Each check returns pass/fail with a line number and a plain-English message.

## 7. v1 scope
**In**: indicators, buy/sell/short/cover signals, stops, position sizing,
time filters, plots, explorations/scans.
**Out (later)**: custom backtester (CBI), multi-timeframe, loops-heavy
code, plugins/OLE, VS Code extension.

## 8. Limits and accounts
- Sign-in required.
- Rate limit per user per day, counted per request (exact number in
  plan; starting proposal: 20 requests/day).
- Very long pasted code is rejected above a size limit.
- Users see their remaining requests.

## 9. Tech stack
- **Frontend**: Next.js website.
- **Backend**: Python (FastAPI) for the AI pipeline and checker.
- **Database**: Postgres with pgvector (vectors) + full-text search
  (keywords). Also stores users, history and market table.
- **Rate limiting**: Redis.
- **AI**: OpenAI API for writing, understanding and embeddings.
  Reranking with an OpenAI model or a small open-source reranker (decide
  in plan by cost and quality).
- **Auth**: email + password. The session is a JWT signed with one
  shared secret (HS256), kept in an httpOnly cookie.

## 10. Measuring quality
- **Test set**: 60–100 tasks (Write) and 30+ buggy AFL samples with known
  bugs (Review), across markets and difficulty.
- **Metrics**:
  - invented-function rate (target ≈ 0)
  - checker pass rate
  - search quality: did the right functions get found
  - Review: bugs found vs bugs planted, and false alarms
  - manual correctness score on a sample
- Every pipeline change is run against the test set before release.
- Every real user-reported bug becomes a new test case.

## 11. Areas of concern
- **API cost**: rate limit protects it, but retries (up to 3) multiply
  cost per request. Needs monitoring.
- **Checker can't catch everything**: logic that is valid but not what
  the user meant. Explanations + user testing in AmiBroker cover this.
- **Market timings change** (DST, exchange changes): needs the "last
  verified" process.
- **Financial responsibility**: clear notice that the tool writes code,
  doesn't give trading advice, and users must backtest before trading.
- **Copyright**: only our own written records are stored and shown.

## 12. Open questions (please confirm)
- Example strategies: generic ones written for the project, not my
  private strategies. OK?
- v1 scope as in section 7. OK?
- Rate limit number: 20 requests/day to start?