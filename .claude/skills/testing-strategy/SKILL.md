---
name: testing-strategy
description: Design a test plan for a feature or component of AFL Copilot, covering what to test, which test type fits each area, and where existing coverage has gaps. Use when the user asks for a testing strategy, a test plan, or what tests to write.
---

# Testing Strategy

Design effective testing strategies balancing coverage, speed, and maintenance.

## Testing Pyramid

```
        /  E2E  \          Few, slow, high confidence
       / Integration \     Some, medium speed
      /   Unit Tests   \   Many, fast, focused
```

## What matters in this project

AFL Copilot exists to prevent AFL that does not compile and AFL that compiles but gives wrong backtest results. Tests should prove the tool catches those failures, so put them first in any plan:

- **Real functions only**: generated code must never use an AmiBroker function that does not exist. Test that invented or misspelled function names are rejected and that real ones pass.
- **Silent backtest bugs**: for each mistake the tool claims to catch (look-ahead bias, wrong stops, array mistakes), keep AFL samples that must be flagged and similar-looking correct samples that must not be flagged.
- **Nothing unchecked is shown**: test that code reaches the user only after it has been checked, and that a failed check is reported, not hidden.
- **Write**: a plain-English strategy produces AFL that passes the checks and comes with an explanation of each part.
- **Review**: pasted AFL with a known bug produces a finding for that bug and a suggested fix.

Use realistic samples: Nifty and MCX strategies of the kind Indian retail algo traders write.

Out of scope, so do not plan tests for them: backtesting, live trading, and strategy or profit advice.

The tech stack and the way code is verified are not decided yet. Check `.claude/docs/spec.md`, `.claude/ARCHITECTURE.md` and `.claude/adr/` before naming a test framework or assuming how the checker works; if they are still empty, ask the user.

## Strategy by Component Type

Apply whichever of these match the components the project ends up having:

- **API endpoints**: unit tests for business logic, integration tests for the HTTP layer, contract tests for consumers
- **Data pipelines**: input validation, transformation correctness, idempotency tests
- **Frontend**: component tests, interaction tests, visual regression, accessibility
- **Infrastructure**: smoke tests, chaos engineering, load tests

## What to Cover

Focus on: business-critical paths, error handling, edge cases, security boundaries, data integrity.

Skip: trivial getters/setters, framework code, one-off scripts.

## Output

Produce a test plan with: what to test, the test type for each area, coverage targets, and example test cases. Identify gaps in existing coverage.
