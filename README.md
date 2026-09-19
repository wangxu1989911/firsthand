# firsthand

An open-source, self-hosted agent that catches duplicate and related feature requests before they're filed twice — grounded in real evidence from Jira, Git history, and design docs, not text similarity. Asks a clarifying question when it lacks what it needs, then auto-files or escalates based on confidence and urgency.

[![CI](https://github.com/wangxu1989911/firsthand/actions/workflows/ci.yml/badge.svg)](https://github.com/wangxu1989911/firsthand/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-blue.svg)](pyproject.toml)

> **Status: pre-release, feature-complete for a first cut.** Contracts, the
> local stack, the dedup pipeline, the Jira/Git/Docs connectors, the web chat
> and admin area, and PII redaction are all in and covered by CI. What's left
> before a tagged release: the optional Slack adapter, and burning down the
> "not yet done" items called out in [Contributing](#contributing).

## What it does

1. Someone describes a request in the web chat (Slack is a planned second front door, behind the same interface).
2. The agent redacts anything personal, classifies it, and asks one targeted question at a time for whatever's missing — capped at three rounds so it never fishes forever.
3. It searches Jira, Git history, and design docs for evidence — never a guess — and checks a vector index for near-duplicates.
4. It scores impact, effort, and urgency against that evidence, then either auto-files the ticket (and links it as a duplicate, if it is one) or hands it to a person when the stakes or the ambiguity are too high.

Every claim traces back to something a connector actually retrieved. Nothing overrides the routing decision to save a person's time except more evidence.

## What's here today

- **The data contracts** (`src/firsthand/contracts/`) — `IssueDraft` and the per-conversation state it carries, `Evidence`, the connector `ToolCall` shape, and the admin/connector configuration models. Every track is written against these; they're treated as fixed.
- **The dedup pipeline** (`src/firsthand/orchestrator/`, `src/firsthand/llm/`) — classify → clarify → investigate → score → route, against an OpenAI-compatible LLM API. Offline-evaluated against a labelled public issue set (`src/firsthand/eval/`), gated in CI against a committed precision/recall baseline.
- **Redaction** (`src/firsthand/redaction.py`) — a deterministic regex pass (emails, phones, IPs, card-shaped numbers, bearer tokens) plus an optional Microsoft Presidio + spaCy NER layer that additionally masks names and places. `raw_text` is never sent to a model; only the redacted copy is, and it's kept alongside `raw_text` for a human reviewing an escalation.
- **Connectors** (`src/firsthand/connectors/`) — Jira (search + file + link-duplicate), Git history (GitHub, with churn/ownership as an effort signal), and design docs (Confluence, BM25-ranked). Each returns evidence, never a conclusion; a missing or misconfigured connector degrades to "no evidence found," not a guess.
- **The web chat + admin area** (`src/firsthand/web/`, `src/firsthand/admin/`, `src/firsthand/auth/`) — a public, unauthenticated chat implementing the clarification loop; an admin dashboard for per-request traces, eval numbers, and escalation review; a Configuration page for connecting Jira/Git/Docs, with credentials encrypted at rest (`src/firsthand/secrets.py`). Username/password auth, argon2id-hashed, with a random admin account generated on first boot.
- **The storage contracts** (`src/firsthand/storage/`) — `VectorStore` and `StateStore`, with `PostgresVectorStore` (pgvector) and `RedisStateStore` as the defaults. Swapping either means writing one class, not touching the orchestrator.
- **The local stack** — Postgres + pgvector and Redis as ordinary containers, namespaced per git worktree so two branches can run at once, plus a `Dockerfile` shipping the same image to Cloud Run or Fargate/App Runner unchanged.

## Quick start

```bash
pip install -e '.[dev]'      # or: make install
./scripts/dev-up.sh          # starts Postgres + Redis + the app on ephemeral ports
make test                    # unit tests, 100% coverage gate, no containers needed
```

`./scripts/dev-up.sh` prints the host ports Compose assigned — open the app URL it prints and you have a working web chat. To run the tests that use the real databases:

```bash
eval "$(./scripts/dev-env.sh)"
make test-integration
```

The chat works out of the box with a deterministic stand-in for the LLM (`StubOrchestrator`) — no API key needed to click through it. To exercise the real dedup pipeline, set `FIRSTHAND_LLM_API_KEY` (see [Configuration](#configuration)) and restart. To connect Jira, Git, or design docs, log into the admin area (`/admin/login` — the first-boot password is printed once in the app's logs) and use the Configuration page.

## Configuration

All configuration arrives through environment variables — nothing cloud-specific is baked into the image. See [`.env.example`](.env.example) for the full set, including the LLM provider, the admin session/encryption key, and the Jira project key. The core knobs:

| Variable | Default | Purpose |
| --- | --- | --- |
| `FIRSTHAND_DATABASE_URL` | `postgresql://firsthand:firsthand@localhost:5432/firsthand` | Postgres + pgvector |
| `FIRSTHAND_REDIS_URL` | `redis://localhost:6379/0` | Per-conversation state |
| `FIRSTHAND_EMBEDDING_DIMENSIONS` | `1536` | Width of the vector index |
| `FIRSTHAND_STATE_TTL_SECONDS` | `86400` | When an abandoned draft expires |
| `FIRSTHAND_PORT` | `8080` | HTTP port |
| `FIRSTHAND_LLM_API_KEY` | *(empty)* | Enables the real dedup pipeline; empty runs the deterministic stub |
| `FIRSTHAND_SECRET_KEY` | *(empty)* | Required for the admin area and encrypted connector credentials (§8.7) |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the dev workflow, and [CLAUDE.md](CLAUDE.md) for the working agreements — commands, non-negotiables, and what "done" means for a feature. Read both before your first change. Security issues go through [SECURITY.md](SECURITY.md), not a public issue.

## License

MIT — see [LICENSE](LICENSE).
