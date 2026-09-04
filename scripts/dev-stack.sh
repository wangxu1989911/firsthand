#!/usr/bin/env bash
# Shared helper: derives one isolated Compose project name per worktree (§8.2).
set -euo pipefail

root="$(git rev-parse --show-toplevel)"
if command -v shasum >/dev/null 2>&1; then
  slug="$(printf '%s' "$root" | shasum | cut -c1-8)"
else
  slug="$(printf '%s' "$root" | sha1sum | cut -c1-8)"
fi

export COMPOSE_PROJECT_NAME="firsthand-$slug"
export FIRSTHAND_COMPOSE_ROOT="$root"
