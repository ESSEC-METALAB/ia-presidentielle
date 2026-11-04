# The register on a server (Dokploy): the site, its "Actualiser" button and the 08:00
# update, in one container. Mount a volume on /app/data. Settings come from the
# environment (.env.example): LLM_PROVIDER, MISTRAL_API_KEY, MISTRAL_MODEL, ...
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    RUN="" \
    TZ=Europe/Paris \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project

COPY src ./src
COPY config ./config
COPY web ./web
COPY annotations ./annotations
COPY scripts ./scripts
RUN uv sync --frozen && chmod +x scripts/*.sh

EXPOSE 8000
VOLUME ["/app/data"]
CMD ["scripts/container-start.sh"]
