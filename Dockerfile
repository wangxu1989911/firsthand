# One image, deployed unchanged to Cloud Run or Fargate/App Runner (design doc §8.3).
# Nothing cloud-specific is baked in: all configuration arrives via environment.
FROM python:3.14-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /app

# The base image's pip lags its own releases; upgrading once here keeps resolver
# behaviour current and keeps the "new release of pip" notice out of every log.
RUN pip install --no-cache-dir --upgrade pip

# Installing as root is correct here: the base image builds CPython from source
# into /usr/local and apt manages no python3 at all, so there is no system
# package manager for pip to conflict with — hence PIP_ROOT_USER_ACTION above.
# One install step, so a source edit does re-resolve dependencies. Splitting it
# would need a lockfile the project does not have yet; the honest comment beats
# a cache layer that silently is not one.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 firsthand
USER firsthand

EXPOSE 8080
CMD ["python", "-m", "firsthand"]
