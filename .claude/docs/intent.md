# Intent: AFL Copilot
Author: Takshit. Status: Accepted.

## Problem
Turning a trading idea into AmiBroker AFL code is slow and error-prone.
General AI tools like ChatGPT write AFL that often doesn't compile, or worse,
compiles but gives wrong backtest results (look-ahead bias, wrong stops,
array mistakes) without the trader noticing.

## Proposed outcome
A trader describes a strategy in plain English and gets AFL code that works
and can be trusted: it uses only real AmiBroker functions, is checked for
common mistakes before it's shown, and explains what each part does.

It does two jobs:
- **Write**: strategy in plain English → working AFL code.
- **Review**: paste existing AFL → it points out bugs and mistakes that
  make backtests wrong, and suggests fixes.

## Affected users and systems
A public tool for AmiBroker users who write AFL, especially Indian retail
algo traders who aren't strong programmers. I am the first user (Nifty and
MCX strategies). Inputs: AmiBroker docs and a library of tested AFL
strategies. Output: AFL pasted into AmiBroker.

## Constraints
Must not invent functions. Must not show unchecked code as if it were
correct. No backtesting, no live trading, no strategy or profit advice.

## Open questions
- How do we check the code works? Proposed: our own checker (real function
  list + common-mistake rules), plus a flow where the user pastes
  AmiBroker's error message back and the copilot fixes it.
- Can we use AmiBroker's docs and forum content in a public tool? Proposed:
  build our own function list in our own words and link to the official
  docs instead of copying their text.