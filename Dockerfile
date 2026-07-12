FROM node:22-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY frontend/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.5.11-python3.12-bookworm-slim AS backend-build
WORKDIR /app/backend
ENV UV_COMPILE_BYTECODE=1
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend/ ./

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/backend/.venv/bin:$PATH" \
    ECOS_FRONTEND_STATIC_DIR=/app/frontend/dist
WORKDIR /app
RUN groupadd --system ecos && useradd --system --gid ecos --home /app ecos
COPY --from=backend-build /app/backend /app/backend
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist
USER ecos
EXPOSE 8000
WORKDIR /app/backend
CMD ["uvicorn", "--app-dir", "src", "ecos.main:app", "--host", "0.0.0.0", "--port", "8000"]
