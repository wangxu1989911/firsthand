# firsthand

An open-source, self-hosted agent that catches duplicate and related feature requests before they're filed twice — grounded in real evidence from Jira, Git history, and design docs, not text similarity. Asks a clarifying question when it lacks what it needs, then auto-files or escalates based on confidence and urgency.

> **Status: Phase 0 — foundations.** The contracts, the local stack, and the CI
> gates are in place. The orchestrator, dedup, and the web chat come next.

## What's here today

- **The data contracts** (`src/firsthand/contracts/`) — `IssueDraft` and the
  per-conversation state it carries, `Evidence`, the connector `ToolCall` shape,
  and the admin/connector configuration models. Every later track is written
  against these, so they are treated as fixed.
- **The storage contracts** (`src/firsthand/storage/`) — `VectorStore` and
  `StateStore`, with `PostgresVectorStore` (pgvector) and `RedisStateStore` as the
  defaults. Swapping either later means writing one class, not touching the
  orchestrator.
- **The local stack** — Postgres + pgvector and Redis as ordinary containers,
  namespaced per git worktree so two branches can run at once.
- **A working skeleton service** — FastAPI with liveness and readiness probes that
  prove the container, the pool, and the schema all come up together.

## Quick start

```bash
pip install -e '.[dev]'      # or: make install
./scripts/dev-up.sh          # starts Postgres + Redis + the app on ephemeral ports
make test                    # unit tests, 100% coverage gate, no containers needed
```

`./scripts/dev-up.sh` prints the host ports Compose assigned. To run the tests
that use the real databases:

```bash
eval "$(./scripts/dev-env.sh)"
make test-integration
```

## Configuration

All configuration arrives through environment variables — nothing cloud-specific
is baked into the image. See `.env.example` for the full set.

| Variable | Default | Purpose |
| --- | --- | --- |
| `FIRSTHAND_DATABASE_URL` | `postgresql://firsthand:firsthand@localhost:5432/firsthand` | Postgres + pgvector |
| `FIRSTHAND_REDIS_URL` | `redis://localhost:6379/0` | Per-conversation state |
| `FIRSTHAND_EMBEDDING_DIMENSIONS` | `1536` | Width of the vector index |
| `FIRSTHAND_STATE_TTL_SECONDS` | `86400` | When an abandoned draft expires |
| `FIRSTHAND_PORT` | `8080` | HTTP port |

## Contributing

`CLAUDE.md` holds the working agreements — the commands, the non-negotiables, and
what "done" means for a feature. Read it before your first change.

## License

MIT — see [LICENSE](LICENSE).
