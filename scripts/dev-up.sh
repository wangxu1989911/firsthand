#!/usr/bin/env bash
# Bring this worktree's stack up on its own project name and ephemeral ports.
set -euo pipefail

source "$(dirname "$0")/dev-stack.sh"

docker compose -p "$COMPOSE_PROJECT_NAME" up -d --build "$@"

echo
echo "stack:    $COMPOSE_PROJECT_NAME"
echo "app:      http://$(docker compose -p "$COMPOSE_PROJECT_NAME" port app 8080)"
echo "postgres: $(docker compose -p "$COMPOSE_PROJECT_NAME" port db 5432)"
echo "redis:    $(docker compose -p "$COMPOSE_PROJECT_NAME" port redis 6379)"
