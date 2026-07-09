# ---- frontend build ----
FROM node:20-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build:app

# ---- python runtime ----
FROM python:3.13-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY overturn ./overturn
RUN pip install --no-cache-dir ".[server]"
COPY server ./server
COPY alembic.ini ./
COPY --from=frontend /build/dist-app ./frontend/dist-app
ENV SPA_DIR=/app/frontend/dist-app
EXPOSE 8000
CMD ["sh", "-c", "python -m alembic upgrade head && python -m uvicorn server.app:app --host 0.0.0.0 --port 8000"]
