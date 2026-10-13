#!/bin/bash
# Keeps secrets out of the repository: blocks Claude from writing .env files
# and from staging or committing them. .env.example is allowed.

input=$(cat)
root="${CLAUDE_PROJECT_DIR:-$(pwd)}"
tool=$(jq -r '.tool_name // empty' <<<"$input")

is_env_file() {
  local name
  name=$(basename "$1")
  [[ "$name" == ".env" || ( "$name" == .env.* && "$name" != ".env.example" ) ]]
}

case "$tool" in
  Edit|Write)
    file=$(jq -r '.tool_input.file_path // empty' <<<"$input")
    if [ -n "$file" ] && is_env_file "$file"; then
      echo "Blocked: $file holds secrets. Put the variable names in .env.example and ask the user to fill in the values." >&2
      exit 2
    fi
    ;;
  Bash)
    cmd=$(jq -r '.tool_input.command // empty' <<<"$input")

    # `git add .env` or `git add -f api/.env.local`
    if [[ "$cmd" == *"git add"* || "$cmd" == *"git stage"* ]]; then
      named=$(grep -oE '\.env(\.[A-Za-z0-9_-]+)*\b' <<<"$cmd" | grep -vx '\.env\.example')
      if [ -n "$named" ]; then
        echo "Blocked: this command stages a .env file. Secrets must not be committed." >&2
        exit 2
      fi
    fi

    # A .env file that is already staged, however it got there
    if [[ "$cmd" == *"git commit"* ]]; then
      while IFS= read -r staged; do
        if [ -n "$staged" ] && is_env_file "$staged"; then
          echo "Blocked: $staged is staged for commit. Unstage it with: git restore --staged \"$staged\"" >&2
          exit 2
        fi
      done < <(git -C "$root" diff --cached --name-only 2>/dev/null)
    fi
    ;;
esac

exit 0
