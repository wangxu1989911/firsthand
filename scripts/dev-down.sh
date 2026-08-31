#!/usr/bin/env bash
# Tear this worktree's stack down, volumes included.
set -euo pipefail

source "$(dirname "$0")/dev-stack.sh"

docker compose -p "$COMPOSE_PROJECT_NAME" down -v "$@"
