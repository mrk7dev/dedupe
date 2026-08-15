# DS923+ is x86_64 only — no need for a multi-arch build.

FROM node:22-slim AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS build
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libjpeg62-turbo zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 dedupe

COPY --from=build /install /usr/local
COPY --from=frontend-build /frontend/dist /app/static

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
