.PHONY: test lint format bugfix-on bugfix-off

test:
	cd api && uv run pytest

lint:
	cd api && uv run ruff check . && uv run ruff format --check .

format:
	cd api && uv run ruff check --fix . && uv run ruff format .

# Bug-fix mode: while it is on, Claude cannot change test files.
# Commit the failing test first, then switch it on.
bugfix-on:
	@if [ -n "$$(git status --porcelain -- api/tests)" ]; then \
		echo "Commit the failing test first: api/tests has uncommitted changes."; exit 1; \
	fi
	@touch .claude/bugfix-mode && echo "Bug-fix mode is on. Test files are locked."

bugfix-off:
	@rm -f .claude/bugfix-mode && echo "Bug-fix mode is off."
