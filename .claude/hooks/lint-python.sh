#!/bin/bash
# After Claude edits a Python file under api/, formats it and runs the linter.
# Problems ruff cannot fix by itself are sent back to Claude.

input=$(cat)
root="${CLAUDE_PROJECT_DIR:-$(pwd)}"
file=$(jq -r '.tool_response.filePath // .tool_input.file_path // empty' <<<"$input")

case "$file" in
  "$root"/api/.venv/*) exit 0 ;;
  "$root"/api/*.py) ;;
  *) exit 0 ;;
esac
[ -f "$file" ] || exit 0

cd "$root/api" || exit 0
out=$(uv run -q ruff check --fix -q "$file" 2>&1)
status=$?
uv run -q ruff format -q "$file" >/dev/null 2>&1

if [ "$status" -ne 0 ]; then
  echo "ruff found problems in $file that it could not fix:" >&2
  echo "$out" >&2
  exit 2
fi

exit 0
