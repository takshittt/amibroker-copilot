.PHONY: test lint format validate-kb services-up services-down db-migrate index write review fix evals evals-review evals-review-ai bugfix-on bugfix-off

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
export DATABASE_URL
export TEST_DATABASE_URL

# Starts Postgres (with pgvector) and Redis in Docker and waits until
# they answer. Docker itself must be running (`colima start`).
services-up:
	docker compose up -d --wait

# Stops them. The database contents are kept.
services-down:
	docker compose down

test:
	cd api && uv run pytest

lint:
	cd api && uv run ruff check . && uv run ruff format --check .

format:
	cd api && uv run ruff check --fix . && uv run ruff format .

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
	@if [ -n "$$(git status --porcelain -- api/tests)" ]; then \
		echo "Commit the failing test first: api/tests has uncommitted changes."; exit 1; \
	fi
	@touch .claude/bugfix-mode && echo "Bug-fix mode is on. Test files are locked."

bugfix-off:
	@rm -f .claude/bugfix-mode && echo "Bug-fix mode is off."
