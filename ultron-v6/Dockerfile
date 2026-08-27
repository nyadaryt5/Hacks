# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.12

# Build the wheel with the same hash-pinned toolchain used by CI.
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY ultron-v6/requirements-build.lock /build/requirements-build.lock
COPY ultron-v6/requirements-dev.lock /build/requirements-dev.lock
RUN python -m pip install --requirement /build/requirements-build.lock \
    && python -m pip install --requirement /build/requirements-dev.lock

COPY pyproject.toml README.md /build/
COPY ultron-v6 /build/ultron-v6
RUN python -m build --wheel --no-isolation \
    --outdir /wheels /build


# Shared, minimal runtime layer.
FROM python:${PYTHON_VERSION}-slim AS runtime-base

LABEL org.opencontainers.image.title="ultron-v6" \
      org.opencontainers.image.description="ULTRON v6 autonomous pentest framework (authorized testing only)" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/nyadaryt5/Hacks"

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
COPY ultron-v6/requirements.lock /app/requirements.lock
RUN python -m pip install --requirement /app/requirements.lock

COPY --from=builder /wheels /tmp/wheels
RUN python -m pip install --no-index --no-deps /tmp/wheels/ultron_v6-*.whl \
    && rm -rf /tmp/wheels \
    && mkdir -p /data \
    && chown -R ultron:ultron /app /data

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)" || exit 1


# Reproducible test target: no dependency is installed ad hoc at container run.
FROM runtime-base AS test

USER root
COPY ultron-v6/requirements-build.lock /app/requirements-build.lock
COPY ultron-v6/requirements-dev.lock /app/requirements-dev.lock
RUN python -m pip install --requirement /app/requirements-build.lock \
    && python -m pip install --requirement /app/requirements-dev.lock
COPY ultron-v6 /app/ultron-v6
COPY tests /app/tests
COPY pyproject.toml .env.example /app/
RUN chown -R ultron:ultron /app

USER ultron
WORKDIR /app
ENTRYPOINT ["python", "-m", "pytest"]
CMD ["tests", "--cov=ultron", "--cov-report=term-missing", "--cov-fail-under=85"]


# Default production target.
FROM runtime-base AS runtime

USER ultron
WORKDIR /data
ENTRYPOINT ["ultron-v6"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8080"]
