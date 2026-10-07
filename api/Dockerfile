# API image (FastAPI + orchestrator). Build from the repo root:
#   docker build -f api/Dockerfile .
# The repo layout is kept (/srv/api, /srv/oddsmith_tools.json) because the orchestrator loads
# oddsmith_tools.json from the repo root. Only named paths are copied, so .env never gets in.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.4.25 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /srv/api
COPY api/pyproject.toml api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY oddsmith_tools.json /srv/oddsmith_tools.json
COPY api/app ./app
COPY api/orchestrator ./orchestrator

RUN useradd --system --uid 10001 oddsmith
USER oddsmith

ENV PATH="/srv/api/.venv/bin:$PATH" \
    PORT=8000
EXPOSE 8000

# --proxy-headers: trust X-Forwarded-For from FORWARDED_ALLOW_IPS (read by uvicorn from the env)
# so the per-IP rate limit sees the client, not Railway's proxy.
CMD ["sh", "-c", "exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port \"$PORT\" --proxy-headers"]
