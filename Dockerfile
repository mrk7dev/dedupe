# DS923+ is x86_64 only — no need for a multi-arch build.

FROM node:22-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS build
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir --prefix=/install .

# Version info baked in from git, not a hand-maintained version string (which
# drifts — pyproject.toml's version has never been bumped). Placed after the
# pip install above so committing code doesn't invalidate that more
# expensive, otherwise-cacheable layer.
COPY .git ./.git
RUN git rev-parse --short HEAD > /build/GIT_SHA 2>/dev/null || echo unknown > /build/GIT_SHA
RUN if [ -n "$(git status --porcelain 2>/dev/null)" ]; then echo true > /build/GIT_DIRTY; else echo false > /build/GIT_DIRTY; fi
RUN date -u +%Y-%m-%dT%H:%M:%SZ > /build/BUILT_AT

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libjpeg62-turbo zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 dedupe

COPY --from=build /install /usr/local
COPY --from=frontend-build /frontend/dist /app/static
COPY --from=build /build/GIT_SHA /build/GIT_DIRTY /build/BUILT_AT /app/

# BROWSE_ROOTS (comparison mode) has no default here on purpose — it's
# auto-discovered at runtime from whichever /volumeN or /volumeUSBn mounts
# exist in the container (see app/config.py), not env-defaulted.
ENV SCAN_ROOTS=/data \
    DB_PATH=/config/dedupe.db \
    STAGING_DIR=/staging \
    STATIC_DIR=/app/static \
    WORKERS=4 \
    PYTHONUNBUFFERED=1

RUN mkdir -p /config /staging && chown -R dedupe:dedupe /config /staging
USER dedupe

EXPOSE 8080
CMD ["dedupe", "serve"]
