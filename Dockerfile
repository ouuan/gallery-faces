FROM node:26-bookworm-slim AS frontend
WORKDIR /frontend
RUN npm install --global pnpm@12.21.0
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm run build
FROM python:3.14-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data IMPORT_DIR=/imports FRONTEND_DIR=/app/frontend
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /usr/local/bin/uv
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend/app ./app
COPY --from=frontend /frontend/dist ./frontend
ENV PATH="/app/.venv/bin:$PATH"
RUN useradd --uid 10001 --create-home gallery && mkdir /data /imports && chown gallery:gallery /data
USER gallery
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
