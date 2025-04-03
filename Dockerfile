FROM python:3.12.9-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.6.12 /uv /uvx /bin/

RUN apt-get update --yes && \
    apt-get install --yes --no-install-recommends \
    gcc git libpq-dev python-dev-is-python3

RUN apt-get autoremove --yes && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

ADD https://raw.githubusercontent.com/vishnubob/wait-for-it/81b1373f17855a4dc21156cfe1694c31d7d1792e/wait-for-it.sh /wait-for-it.sh
RUN chmod +x /wait-for-it.sh

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
