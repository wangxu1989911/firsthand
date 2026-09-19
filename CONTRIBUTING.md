# Contributing to Firsthand

Thanks for looking at this. Firsthand is young — most of the surface area
described here was built in the last few weeks — so expect rough edges, and
expect this file to change as they get sanded down.

## Before you start

- **Read [CLAUDE.md](CLAUDE.md).** It holds the working agreements: the
  commands, the non-negotiables (fixed contracts, no `raw_text` to a model,
  no in-process state, secrets never in the clear, caps on the agent loop),
  and the definition of done for a feature. This file is the *process*;
  CLAUDE.md is the *rules*.
- **The design doc is the source of truth** for why things are shaped the way
  they are. It isn't checked into this repo yet (it predates the code and
  lives elsewhere); CLAUDE.md's section references (§3, §8.2, …) point into
  it. If you're missing context a comment references, ask rather than guess —
  a wrong guess here tends to compound, since later phases build on earlier
  contracts.
- Firsthand doesn't have a lockfile yet. Dependencies are floor-pinned
  (`package>=X.Y`) in `pyproject.toml`; if you bump one for a real reason
  (a CVE, a needed feature), say why in the PR, the same way existing pins
  do (see the `cryptography`/`setuptools`/`msgpack` comments there).

## Dev setup

```bash
git clone https://github.com/wangxu1989911/firsthand.git
cd firsthand
pip install -e '.[dev]'
./scripts/dev-up.sh      # Postgres + pgvector, Redis, and the app, on ephemeral ports
make test                # unit tests, 100% coverage gate — no containers needed
```

Using VS Code: `.devcontainer/` gives you the same image as production plus
`git` and the dev dependencies, attached to the same isolated stack. Two
worktrees never collide — every stack is namespaced by
`COMPOSE_PROJECT_NAME`, derived from the worktree path (§8.2), so you can have
two branches running and testing at once.

Optional real dependencies, each gated behind its own extra and its own test
marker so the fast path never needs them:

```bash
# The real dedup pipeline instead of the deterministic stub — needs an API key.
export FIRSTHAND_LLM_API_KEY=sk-...

# The real Presidio/spaCy NER redaction pass instead of the pattern-only fallback.
pip install -e '.[dev,pii]'
python -m spacy download en_core_web_sm
make test-presidio
```

## Making a change

1. **Implement it.**
2. **Run the full suite**: `make check` (lint, typecheck, unit tests at 100%
   coverage), plus `make test-integration` if you touched storage or anything
   with a container behind it, plus `make test-presidio` if you touched
   redaction's NER layer.
3. **Run a code-review pass on your own diff and resolve what it finds** —
   actually iterate until it comes back clean, don't skim it. Green tests are
   the floor: 100% coverage proves the plumbing runs, it doesn't prove the
   judgement behind it was right. If you're using Claude Code, `/code-review`
   is that pass.
4. Open a PR. CI runs the same gates: lint + typecheck, unit tests at 100%
   coverage, integration tests against real Postgres/Redis, the dedup eval
   against its committed baseline, a Presidio job, and a Docker build with a
   Trivy vulnerability scan. All of them have to be green — there's no merge
   queue judgment call, they're pass/fail.

### The one rule worth over-communicating

**§3's contracts are fixed**: `IssueDraft`, `Evidence`, `ToolCall`,
`VectorStore`, `StateStore`. If a change genuinely needs a new field or
method on one of these, say so explicitly in the PR rather than routing
around it — these shapes are what let the connectors, the orchestrator, and
the web layer be built and tested independently of each other. A local
workaround here is exactly the kind of thing that looks fine in isolation and
breaks integration later.

### Where things get extra scrutiny

Changes near the redaction path (`src/firsthand/redaction.py` and its two
call sites) and anything touching how secrets are stored or transmitted
(`src/firsthand/secrets.py`, `src/firsthand/auth/`, connector credential
handling) get held to a higher bar than "tests pass." Say in the PR
description what you checked, not just what you changed.

## What's not done yet

Called out explicitly rather than left implicit:

- The Slack adapter (optional in the roadmap) — the web chat's intake
  interface is written to be transport-agnostic for exactly this, but nothing
  implements the Slack side yet.
- The Jira connector config is read once at startup; saving a new one in the
  admin area needs a restart to take effect.
- Docs connector: Confluence only (the provider interface is ready for
  Notion, unimplemented). Git connector: GitHub only (same shape for GitLab).
- No lockfile — floor-pinned dependencies only.
- No live/gated end-to-end suite against a real LLM, real Jira, real
  Confluence, or real GitHub API — every test that needs one of those runs
  against a fixture or a `MockTransport` instead. Building that gated live
  suite (§8.6) is open work, not a design decision to leave it out forever.

If you pick one of these up, say so in the issue/PR before you're deep into
it — some of them (the Jira hot-reload one especially) touch the fixed
contracts question above.

## Reporting a security issue

Don't open a public issue for it — see [SECURITY.md](SECURITY.md).
