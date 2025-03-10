FROM python:3.12.9-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.6.5 /uv /uvx /bin/

RUN apt-get update --yes && \
    apt-get install --yes --no-install-recommends \
    libpq-dev

RUN apt-get autoremove --yes && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
COPY README.md /app/README.md
COPY uv.lock /app/uv.lock
COPY src /app/src
COPY tests /app/tests

RUN mkdir /app/temp

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen

ENV PATH="/app/.venv/bin:$PATH"
