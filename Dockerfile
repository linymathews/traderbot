# ── Stage 1: Build frontend ───────────────────────────────────────────────────
FROM node:20-alpine AS frontend-build
WORKDIR /build/frontend
ARG VITE_GOOGLE_CLIENT_ID
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN VITE_GOOGLE_CLIENT_ID=${VITE_GOOGLE_CLIENT_ID} npm run build

# ── Stage 2: Runtime (app + MongoDB in one image) ─────────────────────────────
FROM python:3.12-slim AS runtime
WORKDIR /app

# Install MongoDB + supervisor + build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev curl gnupg \
    && curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc | gpg --dearmor -o /usr/share/keyrings/mongodb-server-8.0.gpg \
    && echo "deb [ signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/debian bookworm/mongodb-org/8.0 main" \
       > /etc/apt/sources.list.d/mongodb-org-8.0.list \
    && apt-get update && apt-get install -y --no-install-recommends \
       mongodb-org supervisor \
    && rm -rf /var/lib/apt/lists/*

# MongoDB data dir
RUN mkdir -p /data/db && chmod 777 /data/db

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r ./backend/requirements.txt

COPY backend/ ./backend/
COPY --from=frontend-build /build/frontend/dist ./frontend/dist

# ── supervisord config ────────────────────────────────────────────────────────
RUN mkdir -p /var/log/supervisor
COPY supervisord.conf /etc/supervisor/conf.d/traderbot.conf

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3); sys.exit(0)" || exit 1

CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/traderbot.conf"]