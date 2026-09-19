# One image, deployed unchanged to Cloud Run or Fargate/App Runner (design doc §8.3).
# Nothing cloud-specific is baked in: all configuration arrives via environment.
#
# Two stages off one base, so the dev container and production provably share a
# runtime (§8.2) without the shipped image carrying a toolchain it never uses.
# `runtime` is last, so a bare `docker build .` or `docker compose build` gets
# production; the dev container asks for `target: dev` explicitly.
#
# Pinned by digest, not just tag: `python:3.14-slim` is a moving target, and an
# unpinned FROM makes two builds of the same commit produce different images.
# Getting security patches is a rebase onto a newer digest, not `apt-get
# upgrade` in this file — see Dependabot's `docker` entry in
# .github/dependabot.yml, which opens a PR bumping this line as new digests for
# the tag appear, so the base actually gets refreshed on a schedule instead of
# silently going stale behind a tag that looks current.
FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /app

# The base image's pip lags its own releases; upgrading once here keeps resolver
# behaviour current and keeps the "new release of pip" notice out of every log.
RUN pip install --no-cache-dir --upgrade pip

# Not `apt-get upgrade`: that pulls whatever is newest across the whole image
# on build day, so two builds of this file produce different images (the
# reproducibility problem pinning FROM by digest above exists to avoid). This
# instead names the specific packages a Trivy scan found vulnerable in the
# pinned base — CVE-2026-41992 (gzip), CVE-2026-86145/89157/89161 (libpcre2,
# RCE via crafted regex), CVE-2026-11822/11824 (libsqlite3, RCE via crafted
# FTS5/malformed db), CVE-2026-13221 et al. (perl-base) — and upgrades only
# those, to whatever Debian's trixie-security suite currently has (not a
# pinned version: those CVEs were fixed after this base digest was published,
# so the fix is inherently "whatever lands," the same as any point release).
# Interim measure: Dependabot's `docker` entry bumps the FROM digest as these
# fixes land in a published `python:3.14-slim` build, at which point this
# becomes a redundant no-op to prune, not a correctness risk to carry.
RUN apt-get update \
    && apt-get install -y --only-upgrade gzip libpcre2-8-0 libsqlite3-0 perl-base \
    && rm -rf /var/lib/apt/lists/*


# --- dev: what a person needs at a keyboard, never what gets deployed ---------
FROM base AS dev

# git is the reason this stage exists: VS Code's Source Control panel runs git
# *inside* the attached container, so committing needs it here even though the
# repo lives on the host. openssh-client covers SSH remotes and agent
# forwarding; both would be dead weight and extra attack surface in `runtime`.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Installs the dependency set so a rebuild is cached. postCreateCommand then
# re-runs the editable install against the bind-mounted /workspace, which
# re-points the package at the real source and finds every dependency already
# satisfied here.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir -e '.[dev]'

CMD ["sleep", "infinity"]


# --- runtime: what actually ships --------------------------------------------
FROM base AS runtime

# Installing as root is correct here: the base image builds CPython from source
# into /usr/local and apt manages no python3 at all, so there is no system
# package manager for pip to conflict with — hence PIP_ROOT_USER_ACTION above.
# One install step, so a source edit does re-resolve dependencies. Splitting it
# would need a lockfile the project does not have yet; the honest comment beats
# a cache layer that silently is not one.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
# The `pii` extra (Presidio + spaCy) is baked into the shipped image, not
# optional here: redacting before anything reaches a model is a §1 guarantee
# for the running service, even though it's left out of `dev`/CI's fast jobs
# to keep those quick (see pyproject.toml). Adds real size and build time —
# accepted cost of shipping the NER layer for real rather than as a maybe.
RUN pip install --no-cache-dir '.[pii]' \
    && python -m spacy download en_core_web_sm

RUN useradd --create-home --uid 10001 firsthand
USER firsthand

EXPOSE 8080
# Liveness only (`/healthz`, not `/readyz`) — this answers "should the
# container be restarted", the same question an orchestrator's own liveness
# probe asks; Cloud Run/Fargate configure their readiness checks separately
# against /readyz (§8.3). Reads FIRSTHAND_PORT so it still finds the process
# if a deployment overrides the default.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('FIRSTHAND_PORT', '8080') + '/healthz', timeout=2)"]
CMD ["python", "-m", "firsthand"]
