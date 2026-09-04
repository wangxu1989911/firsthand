#!/usr/bin/env bash
# Bring this worktree's stack up on its own project name and ephemeral ports.
set -euo pipefail

source "$(dirname "$0")/dev-stack.sh"

compose() {
  docker compose -f "$FIRSTHAND_COMPOSE_ROOT/docker-compose.yml" -p "$COMPOSE_PROJECT_NAME" "$@"
}

compose up -d --build "$@"

# Assigned, not inlined into echo: a command substitution inside an argument
# discards its exit status, so a crashed container would print an empty URL and
# still exit 0 despite `set -e`.
app_port="$(compose port app 8080)"
db_port="$(compose port db 5432)"
redis_port="$(compose port redis 6379)"

echo
echo "stack:    $COMPOSE_PROJECT_NAME"
echo "app:      http://${app_port}"
echo "postgres: ${db_port}"
echo "redis:    ${redis_port}"
