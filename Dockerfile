# syntax=docker/dockerfile:1
# Production Coral backend container.
# Builds the Python app with uv and runs uvicorn on port 8000.
#
# The MuJoCo viewer is disabled inside the container (no display); the browser
# viewer is served by a separate dev/build frontend outside this image.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# Copy build metadata first; the lockfile pins the full dependency tree.
COPY pyproject.toml /app/pyproject.toml
COPY uv.lock /app/uv.lock

# Install dependencies first so layer caching survives source edits.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Copy the backend source and assets, then install the project itself.
COPY backend/app /app/backend/app
COPY assets /app/assets
COPY README.md /app/README.md
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# -----------------------------------------------------------------------------
FROM python:3.12-slim-bookworm

# OpenCV + MuJoCo runtime dependencies that aren't present in the slim image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libxcb1 \
    libx11-6 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the installed virtual environment from the builder stage.
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Copy source, assets, and project metadata needed at runtime.
COPY --from=builder /app/backend/app /app/backend/app
COPY --from=builder /app/assets /app/assets
COPY --from=builder /app/pyproject.toml /app/pyproject.toml
COPY --from=builder /app/uv.lock /app/uv.lock

# MuJoCo native viewer cannot open inside a container; run headless.
# The simulator still computes physics and serves /ws/sim and /move.
ENV CORAL_NO_VIEWER=1
ENV PYTHONPATH=/app/backend/app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
