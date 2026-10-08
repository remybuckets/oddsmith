# Ingestion worker image. Runs one `tick` and exits; Railway's cron starts it every 30 min.
# Build from the repo root:  docker build -f ingestion/Dockerfile .
# Only named paths are copied, so .env never gets in. See ingestion/DEPLOY.md.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.4.25 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /srv/ingestion
COPY ingestion/pyproject.toml ingestion/uv.lock ingestion/.python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY ingestion/src ./src
RUN uv sync --frozen --no-dev --no-editable

RUN useradd --system --uid 10001 oddsmith
USER oddsmith

ENV PATH="/srv/ingestion/.venv/bin:$PATH"

# Exit code 1 if any due job failed (each failure is also recorded in job_runs).
CMD ["python", "-m", "oddsmith_ingestion.cli", "tick"]
