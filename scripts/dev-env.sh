#!/usr/bin/env bash
# Print the env vars pointing at this worktree's running stack:
#   eval "$(./scripts/dev-env.sh)" && pytest -m integration
set -euo pipefail

source "$(dirname "$0")/dev-stack.sh"

compose() {
  docker compose -f "$FIRSTHAND_COMPOSE_ROOT/docker-compose.yml" -p "$COMPOSE_PROJECT_NAME" "$@"
}

# `docker compose port` reports the *bind* address, which is a wildcard: 0.0.0.0,
# or "::" printed unbracketed as ":::32768". Neither connects, so keep the port
# and dial loopback explicitly.
host_port() {
  local mapping
  mapping="$(compose port "$1" "$2")"
  printf '127.0.0.1:%s' "${mapping##*:}"
}

db="$(host_port db 5432)"
redis="$(host_port redis 6379)"

echo "export FIRSTHAND_DATABASE_URL='postgresql://firsthand:firsthand@${db}/firsthand'"
echo "export FIRSTHAND_REDIS_URL='redis://${redis}/0'"
