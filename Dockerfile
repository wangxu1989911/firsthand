# One image, deployed unchanged to Cloud Run or Fargate/App Runner (design doc §8.3).
# Nothing cloud-specific is baked in: all configuration arrives via environment.
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so a source-only change reuses the cached layer.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 firsthand
USER firsthand

EXPOSE 8080
CMD ["python", "-m", "firsthand"]
