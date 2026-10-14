.PHONY: test lint format validate-kb services-up services-down db-migrate index bugfix-on bugfix-off

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

# Bug-fix mode: while it is on, Claude cannot change test files.
# Commit the failing test first, then switch it on.
bugfix-on:
	@if [ -n "$$(git status --porcelain -- api/tests)" ]; then \
		echo "Commit the failing test first: api/tests has uncommitted changes."; exit 1; \
	fi
	@touch .claude/bugfix-mode && echo "Bug-fix mode is on. Test files are locked."

bugfix-off:
	@rm -f .claude/bugfix-mode && echo "Bug-fix mode is off."
