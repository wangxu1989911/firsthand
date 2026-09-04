# Firsthand — working agreements

Firsthand is an open-source, self-hosted agent that catches duplicate and related
feature requests before they're filed twice, grounded in real evidence from Jira,
Git, and design docs. The design doc is the source of truth; section references
below (§3, §8.2, …) point into it.

## Commands

| Task | Command |
| --- | --- |
| Install | `make install` (or `pip install -e '.[dev]'`) |
| Lint + format check | `make lint` |
| Typecheck | `make typecheck` |
| Unit tests + coverage gate | `make test` |
| Integration tests (real DBs) | `make up && eval "$(./scripts/dev-env.sh)" && make test-integration` |
| Everything CI runs locally | `make check` |
| Start / stop the local stack | `./scripts/dev-up.sh` / `./scripts/dev-down.sh` |

**Run the full suite before calling anything done.** Green tests are the floor,
not the finish line — see the review gate below.

## Non-negotiables

1. **§3's contracts are fixed.** `IssueDraft`, `Evidence`, `ToolCall`, `VectorStore`,
   and `StateStore` are what makes parallel tracks safe (§9). If your track
   genuinely needs a new field or method, **stop and flag it** so it propagates to
   every track — never patch it locally in one worktree.
2. **Connectors return evidence, never conclusions.** Only the orchestrator decides
   what evidence means. Every claim traces to a retrieved passage (§5, grounding).
3. **No state in process memory.** Per-conversation state lives in the `StateStore`.
   A follow-up reply can land on a different container instance than the one that
   asked the question (§8.3).
4. **Configuration arrives through environment variables only.** Nothing
   cloud-specific is baked into the image; the same image runs on either cloud.
5. **`raw_text` never reaches a model.** Only `redacted_text` is ever sent (§1, §7).
   Changes anywhere near the redaction path get extra review, not less.
6. **Secrets are never stored in the clear.** Admin passwords are argon2id hashes;
   connector credentials are encrypted with a key that lives only in the
   environment (§8.7).
7. **Caps are load-bearing.** Three clarification rounds (§2) and six tool calls
   (§7) — an uncapped agent loop is the cost problem, not the per-token price.

## Definition of done, per feature

1. Implement it.
2. Run the full suite: `make check`, plus `make test-integration` if you touched
   storage or anything with a container behind it.
3. **Run a code-review pass on the diff and resolve what it finds** — actually
   iterate until it comes back clean, don't skim it (§8.5). 100% coverage proves
   the plumbing runs; it does not prove the judgement behind it was right.

## Local development

One isolated Docker stack per worktree (§8.2): every stack is namespaced by
`COMPOSE_PROJECT_NAME` derived from the worktree path, and no host port is ever
fixed, so two worktrees can run and test at the same time. Always go through
`./scripts/dev-up.sh` rather than a bare `docker compose up`.

Everything runs locally except the one call that has to leave — the LLM API (§8.6).
Integration tests use the real Postgres and Redis containers with LLM and
connector responses mocked from fixtures.

## Layout

```
src/firsthand/contracts/   §3 shapes — treat as fixed
src/firsthand/storage/     VectorStore / StateStore + pgvector and Redis defaults
src/firsthand/config.py    environment-only settings
src/firsthand/resources.py connection lifecycle, wires drivers to the stores
src/firsthand/app.py       the FastAPI skeleton (web chat + admin land here in Phase 2)
tests/unit/                no network, no containers, 100% coverage gate
tests/integration/         real Postgres + Redis, everything external mocked
```
