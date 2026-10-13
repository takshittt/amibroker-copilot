#!/bin/bash
# Bug-fix mode: while .claude/bugfix-mode exists, Claude cannot change test
# files, so a failing test is fixed by changing the code and not the test.
# The user switches the mode with `make bugfix-on` and `make bugfix-off`.

input=$(cat)
root="${CLAUDE_PROJECT_DIR:-$(pwd)}"
marker="$root/.claude/bugfix-mode"
tool=$(jq -r '.tool_name // empty' <<<"$input")
event=$(jq -r '.hook_event_name // empty' <<<"$input")
file=$(jq -r '.tool_input.file_path // empty' <<<"$input")
cmd=$(jq -r '.tool_input.command // empty' <<<"$input")

is_test_file() {
  case "$1" in
    */tests/*|tests/*|*/test_*.py|test_*.py|*_test.py|*/conftest.py|*.test.ts|*.test.tsx|*.spec.ts|*.spec.tsx)
      return 0 ;;
  esac
  return 1
}

# Only the user switches bug-fix mode off.
if [ "$event" = "PreToolUse" ]; then
  if [[ "$tool" == "Bash" && ( "$cmd" == *"bugfix-off"* || "$cmd" == *"bugfix-mode"* ) ]]; then
    echo "Blocked: only the user switches bug-fix mode, with make bugfix-on or make bugfix-off." >&2
    exit 2
  fi
  if [[ "$tool" != "Bash" && "$file" == "$marker" ]]; then
    echo "Blocked: only the user switches bug-fix mode, with make bugfix-on or make bugfix-off." >&2
    exit 2
  fi
fi

[ -f "$marker" ] || exit 0

case "$event:$tool" in
  PreToolUse:Edit|PreToolUse:Write)
    if is_test_file "$file"; then
      echo "Blocked: bug-fix mode is on, so test files cannot be changed. Fix the code so the existing test passes. If the test itself is wrong, stop and tell the user." >&2
      exit 2
    fi
    ;;
  PostToolUse:Bash)
    # A shell command can also change a test file; catch that after it runs.
    changed=""
    while IFS= read -r line; do
      path="${line:3}"
      if is_test_file "$path"; then
        changed="$changed $path"
      fi
    done < <(git -C "$root" status --porcelain 2>/dev/null)
    if [ -n "$changed" ]; then
      echo "Bug-fix mode is on, but test files differ from the last commit:$changed. Restore them with git restore, then fix the code instead." >&2
      exit 2
    fi
    ;;
esac

exit 0
