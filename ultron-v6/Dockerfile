# syntax=docker/dockerfile:1
FROM python:3.12-slim

LABEL org.opencontainers.image.title="ultron-v6" \
      org.opencontainers.image.description="ULTRON v6 autonomous pentest framework (authorized testing only)" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ULTRON_DB_URL=sqlite:////data/ultron_v6.db

# Recon tooling used by the DISCOVERY phase.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nmap ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin ultron

WORKDIR /app

# Install pinned runtime dependencies first (better layer caching).
COPY ultron-v6/requirements.lock /app/requirements.lock
RUN pip install --no-cache-dir -r /app/requirements.lock

# Install the package itself plus the test suite for the CI/test profile.
COPY ultron-v6 /app/ultron-v6
COPY tests /app/tests
COPY pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir --no-deps /app/ultron-v6 \
    && mkdir -p /data \
    && chown -R ultron:ultron /app /data

USER ultron
WORKDIR /data

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)" || exit 1

ENTRYPOINT ["ultron-v6"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8080"]
