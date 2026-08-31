#!/usr/bin/env bash
# Print the env vars pointing at this worktree's running stack:
#   eval "$(./scripts/dev-env.sh)" && pytest -m integration
set -euo pipefail

source "$(dirname "$0")/dev-stack.sh"

db="$(docker compose -p "$COMPOSE_PROJECT_NAME" port db 5432)"
redis="$(docker compose -p "$COMPOSE_PROJECT_NAME" port redis 6379)"

echo "export FIRSTHAND_DATABASE_URL=postgresql://firsthand:firsthand@${db}/firsthand"
echo "export FIRSTHAND_REDIS_URL=redis://${redis}/0"
