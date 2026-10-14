.PHONY: test test-api test-web lint lint-api lint-web formatvalidate-kb services-up services-down db-migrate index write review fix evals evals-review evals-review-ai api reset-password web-install web demo e2e bugfix-on bugfix-off

# Settings such as OPENAI_API_KEY are read from .env when it exists, and
# handed to every command below. Write each line as NAME=value, with no
# quotes and no spaces around the equals sign.
ifneq (,$(wildcard .env))
include .env
export
endif

# The local databases from docker-compose.yml. Set these in the
# environment to use others; CI sets TEST_DATABASE_URL itself.
DATABASE_URL ?= postgresql://copilot:copilot@localhost:5432/copilot_dev
TEST_DATABASE_URL ?= postgresql://copilot:copilot@localhost:5432/copilot_test
REDIS_URL ?= redis://localhost:6379/0
# Redis database 15 is wiped by the API tests.
TEST_REDIS_URL ?= redis://localhost:6379/15
export DATABASE_URL
export TEST_DATABASE_URL
export REDIS_URL
export TEST_REDIS_URL

# Starts Postgres (with pgvector) and Redis in Docker and waits until
# they answer. Docker itself must be running (`colima start`).
services-up:
	docker compose up -d --wait

# Stops them. The database contents are kept.
services-down:
	docker compose down

# `make test` and `make lint` cover both halves. CI runs each half in its
# own job, since the API job has no Node and the web job no Python.
test: test-api test-web

test-api:
	cd api && uv run pytest

test-web:
	cd web && pnpm test

lint: lint-api lint-web

lint-api:
	cd api && uv run ruff check . && uv run ruff format --check .

lint-web:
	cd web && pnpm lint

format:
	cd api && uv run ruff check --fix . && uv run ruff format .
	cd web && pnpm format

# Installs the website's packages (once, and after they change).
web-install:
	cd web && pnpm install --frozen-lockfile

# Runs the website on http://localhost:3000. Needs API_URL, JWT_SECRET and
# BFF_SHARED_SECRET; with `make demo` running, API_URL=http://127.0.0.1:8000.
web:
	cd web && pnpm dev

# The API with scripted answers instead of OpenAI, for working on the
# website without a key. Listens only on this machine. Needs the dev
# database migrated and indexed, and JWT_SECRET and BFF_SHARED_SECRET.
demo:
	cd api && OFFLINE_DEMO=1 uv run python -m copilot.api.offline

# Browser tests of the full Write and Review flows, against the demo API.
# They start their own servers. Needs `make services-up` first.
e2e:
	cd web && pnpm e2e

# Checks every file in kb/ against the record formats.
validate-kb:
	cd api && uv run python -m copilot.kb ../kb

# Applies any new files in api/migrations to DATABASE_URL.
db-migrate:
	cd api && uv run python -m copilot.db.migrate

# Loads kb/ into DATABASE_URL. Needs OPENAI_API_KEY for the embeddings;
# `make index FAKE=1` uses made-up vectors instead (keyword search only).
index:
	cd api && uv run python -m copilot.indexer ../kb $(if $(FAKE),--fake-embeddings,)

# Writes AFL for one request. Makes real OpenAI calls. Example:
#   make write MARKET=nse_fo TIMEFRAME=5min TEXT="Buy when the 9 EMA crosses above the 21 EMA ..."
write:
	cd api && uv run python -m copilot.write --market "$(MARKET)" --timeframe "$(TIMEFRAME)" "$(TEXT)"

# Reviews an AFL file: Verified findings from the checker, AI-suggested
# ones from the model. Add APPLY=1 to also rewrite the code. Real OpenAI calls.
#   make review MARKET=nse_fo TIMEFRAME=5min FILE=/path/to/strategy.afl
review:
	cd api && uv run python -m copilot.review --market "$(MARKET)" --timeframe "$(TIMEFRAME)" $(if $(APPLY),--apply,) "$(FILE)"

# Corrects an AFL file from the error AmiBroker gave. Real OpenAI calls.
#   make fix MARKET=nse_fo TIMEFRAME=5min FILE=/path/to/strategy.afl ERROR="Error 32. ..."
fix:
	cd api && uv run python -m copilot.fix --market "$(MARKET)" --timeframe "$(TIMEFRAME)" --error "$(ERROR)" "$(FILE)"

# Runs the API on port 8000, reloading on code changes. Needs every
# setting in .env.example, including the OpenAI key and model ids.
api:
	cd api && uv run uvicorn copilot.api.main:create_from_env --factory --reload --port 8000

# Gives a user a new random password and prints it once.
#   make reset-password EMAIL=trader@example.in
reset-password:
	cd api && uv run python -m copilot.admin reset-password "$(EMAIL)"

# Runs the Write test set and prints the quality measures. Makes real
# OpenAI calls for every task, so it costs money.
evals:
	cd api && uv run python -m copilot.evals write ../evals/write --json ../evals/last-report.json

# Runs the Review test set through the checker only. Free: no key, no
# database. Reports planted bugs found and false alarms.
evals-review:
	cd api && uv run python -m copilot.evals review ../evals/review --kb ../kb

# The same with the AI review as well. Makes real OpenAI calls.
evals-review-ai:
	cd api && uv run python -m copilot.evals review ../evals/review --ai --json ../evals/last-review-report.json

# Bug-fix mode: while it is on, Claude cannot change test files.
# Commit the failing test first, then switch it on.
bugfix-on:
	@if [ -n "$$(git status --porcelain -- api/tests 'web/*.test.ts' 'web/*.test.tsx' web/e2e)" ]; then \
		echo "Commit the failing test first: there are uncommitted changes to test files."; exit 1; \
	fi
	@touch .claude/bugfix-mode && echo "Bug-fix mode is on. Test files are locked."

bugfix-off:
	@rm -f .claude/bugfix-mode && echo "Bug-fix mode is off."
