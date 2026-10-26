# syntax=docker/dockerfile:1
# CORAL backend (FastAPI + MuJoCo simulator + Whisper) on port 8000.
# Built and run by docker-compose.yml; see ./run.sh.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# Dependencies first so this layer survives source edits.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Editable install: app.config derives REPO_ROOT (assets/, logs/) from the
# source location, so the code stays at /app/backend/app in the final image.
COPY backend/app backend/app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# -----------------------------------------------------------------------------
FROM python:3.12-slim-bookworm

# Runtime libraries for OpenCV/MediaPipe (imported via the vision package) and
# MuJoCo's headless rendering stack.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libegl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/backend/app backend/app
COPY assets/ainex assets/ainex
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["server"]
