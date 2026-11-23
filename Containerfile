FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /uvx /bin/

WORKDIR /app

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH="/app/src" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_CACHE_DIR=/tmp/uv-cache

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY scripts ./scripts
COPY docs/operations/phase-2-product-manifest-v1.json ./docs/operations/phase-2-product-manifest-v1.json
COPY docs/operations/phase-3-source-map-v1.json ./docs/operations/phase-3-source-map-v1.json
RUN uv sync --frozen --no-dev --no-editable

EXPOSE 8000
USER 10001:10001

CMD ["uvicorn", "product_support_agent.api.app:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
