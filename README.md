# AFL Copilot

An AI assistant for **AmiBroker Formula Language (AFL)**. It helps traders who aren't strong programmers get AFL code they can trust. It's built mainly for Indian retail algo traders on NSE, BSE and MCX.

> 🚧 **Status:** in development. All three modes, the API and the website are built. It has not been deployed yet.

## What it does

| Mode | You give it | You get back |
|---|---|---|
| ✍️ **Write** | A strategy described in plain English | AFL code |
| 🔍 **Review** | AFL code you've pasted in | Findings and fixes |
| 🛠️ **Fix from error** | Your code plus AmiBroker's error message | A corrected version |

## How it stays accurate

**The AI writes the code, and plain code decides whether it's correct.**

- 📚 **Knowledge base** (`/kb`): the list of AmiBroker functions, plus concepts, common errors, common mistakes and worked examples. It's written in the project's own words.
- ✅ **Checker:** pure Python, no AI and no network. It checks every answer against the function list, so the copilot can't make up functions that don't exist.
- 🏷️ **Clear labels:** checker findings are marked **Verified**. AI findings are marked **AI-suggested**. Code that doesn't pass every check carries a visible "not fully checked" warning.
- 🧪 **Test sets** (`/evals`) for the Write and Review modes.

## Tech stack

- **API:** Python 3.12, FastAPI, OpenAI, Postgres with pgvector, Redis (managed with `uv`)
- **Web:** Next.js, React, TypeScript, Biome, Vitest, Playwright
- **Local services:** Docker Compose

## Run it locally

```bash
cp .env.example .env      # fill in your settings
make services-up          # start Postgres and Redis (needs Docker)
make web-install          # first time only
make web                  # website on http://localhost:3000
make demo                 # scripted answers, if you don't have an OpenAI key
```

Run the tests and the linter with `make test` and `make lint`.

## Not included

Backtesting, live trading, and strategy or profit advice are not part of the product.

## License

MIT
