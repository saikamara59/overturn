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
# One image, two roles: SERVICE_ROLE=worker runs the queue loop; anything
# else validates settings (fail fast with pydantic's error naming missing env
# vars), migrates, then serves the API on $PORT (Railway injects PORT).
# --forwarded-allow-ips '*' makes uvicorn honor X-Forwarded-Proto behind the
# platform proxy so absolute URLs (e.g. invite links) are minted https.
CMD ["sh", "-c", "if [ \"$SERVICE_ROLE\" = \"worker\" ]; then exec python -m server.worker; else python -c 'from server.config import get_settings; get_settings()' && python -m alembic upgrade head && exec python -m uvicorn server.app:app --host 0.0.0.0 --port ${PORT:-8000} --forwarded-allow-ips '*'; fi"]
