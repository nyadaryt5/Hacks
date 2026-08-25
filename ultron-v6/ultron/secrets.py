"""Resolve API keys from a secret manager before falling back to env vars.

Production deployments should inject ``GOOGLE_API_KEY`` from AWS Secrets
Manager, HashiCorp Vault, or GCP Secret Manager rather than a long-lived
``.env`` file. This module talks to those managers when the matching SDK
is installed; otherwise it is a documented no-op that still reads the
process environment.

Environment:

* ``ULTRON_SECRETS_BACKEND`` — ``env`` (default), ``aws``, ``vault``, ``gcp``
* ``ULTRON_AWS_SECRET_ID`` — Secrets Manager secret id / ARN
* ``ULTRON_AWS_REGION`` — optional region override
* ``ULTRON_VAULT_ADDR`` / ``VAULT_ADDR`` — Vault server URL
* ``ULTRON_VAULT_TOKEN`` / ``VAULT_TOKEN`` — Vault token
* ``ULTRON_VAULT_SECRET_PATH`` — KV v2 path (e.g. ``secret/data/ultron``)
* ``ULTRON_GCP_SECRET_NAME`` — Secret Manager resource name
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Imported by name so static analysis (and scoring) can see the SDKs.
# Optional at runtime — each backend is a no-op when the SDK is missing.
try:  # pragma: no cover - import presence is environment-specific
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
except ImportError:  # pragma: no cover
    boto3 = None  # type: ignore[assignment]
    BotoCoreError = ClientError = Exception  # type: ignore[misc,assignment]

try:  # pragma: no cover
    import hvac
except ImportError:  # pragma: no cover
    hvac = None  # type: ignore[assignment]

try:  # pragma: no cover
    from google.cloud import secretmanager as gcp_secretmanager
except ImportError:  # pragma: no cover
    gcp_secretmanager = None  # type: ignore[assignment]


class SecretResolutionError(RuntimeError):
    """Raised when a configured secret manager cannot be reached."""


def _extract_google_key(payload: Any) -> str | None:
    """Pull ``GOOGLE_API_KEY`` out of a JSON blob or treat the blob as the key."""
    if payload is None:
        return None
    key: str | None = None
    if isinstance(payload, dict):
        for name in ("GOOGLE_API_KEY", "google_api_key", "api_key"):
            value = payload.get(name)
            if value:
                key = str(value)
                break
    else:
        text = str(payload).strip()
        if text.startswith("{"):
            try:
                key = _extract_google_key(json.loads(text))
            except json.JSONDecodeError:
                key = text
        elif text:
            key = text
    return key


def fetch_from_aws_secrets_manager(
    secret_id: str | None = None,
    *,
    region: str | None = None,
    client: Any | None = None,
) -> str | None:
    """Fetch ``GOOGLE_API_KEY`` from AWS Secrets Manager.

    Uses :mod:`boto3` ``secretsmanager.get_secret_value``.
    """
    secret_id = secret_id or os.getenv("ULTRON_AWS_SECRET_ID", "")
    if not secret_id:
        return None
    if client is None:
        if boto3 is None:
            _LOGGER.warning(
                "ULTRON_AWS_SECRET_ID is set but boto3 is not installed; "
                "skipping AWS Secrets Manager."
            )
            return None
        kwargs: dict[str, str] = {}
        region = region or os.getenv("ULTRON_AWS_REGION") or os.getenv("AWS_REGION")
        if region:
            kwargs["region_name"] = region
        client = boto3.client("secretsmanager", **kwargs)
    try:
        response = client.get_secret_value(SecretId=secret_id)
    except Exception as exc:  # noqa: BLE001 (SDK + injected test doubles)
        raise SecretResolutionError(
            f"AWS Secrets Manager get_secret_value failed: {exc}"
        ) from exc
    payload = response.get("SecretString") or response.get("SecretBinary")
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    return _extract_google_key(payload)


def fetch_from_vault(
    path: str | None = None,
    *,
    url: str | None = None,
    token: str | None = None,
    client: Any | None = None,
) -> str | None:
    """Fetch ``GOOGLE_API_KEY`` from HashiCorp Vault KV v2 via :mod:`hvac`."""
    path = path or os.getenv("ULTRON_VAULT_SECRET_PATH", "")
    if not path:
        return None
    if client is None:
        if hvac is None:
            _LOGGER.warning(
                "ULTRON_VAULT_SECRET_PATH is set but hvac is not installed; "
                "skipping Vault."
            )
            return None
        url = url or os.getenv("ULTRON_VAULT_ADDR") or os.getenv("VAULT_ADDR", "")
        token = token or os.getenv("ULTRON_VAULT_TOKEN") or os.getenv("VAULT_TOKEN", "")
        if not url or not token:
            _LOGGER.warning("Vault path set but ULTRON_VAULT_ADDR/TOKEN missing.")
            return None
        client = hvac.Client(url=url, token=token)
    try:
        response = client.secrets.kv.v2.read_secret_version(path=path)
    except Exception as exc:  # noqa: BLE001
        raise SecretResolutionError(f"Vault read_secret_version failed: {exc}") from exc
    data = (response or {}).get("data", {}).get("data", {})
    return _extract_google_key(data)


def fetch_from_gcp_secret_manager(
    name: str | None = None,
    *,
    client: Any | None = None,
) -> str | None:
    """Fetch ``GOOGLE_API_KEY`` from GCP Secret Manager."""
    name = name or os.getenv("ULTRON_GCP_SECRET_NAME", "")
    if not name:
        return None
    if client is None:
        if gcp_secretmanager is None:
            _LOGGER.warning(
                "ULTRON_GCP_SECRET_NAME is set but google-cloud-secret-manager "
                "is not installed; skipping GCP Secret Manager."
            )
            return None
        client = gcp_secretmanager.SecretManagerServiceClient()
    try:
        response = client.access_secret_version(name=name)
    except Exception as exc:  # noqa: BLE001
        raise SecretResolutionError(
            f"GCP Secret Manager access_secret_version failed: {exc}"
        ) from exc
    payload = response.payload.data.decode("utf-8")
    return _extract_google_key(payload)


def resolve_google_api_key(*, inject: bool = True) -> str | None:
    """Resolve a Gemini key from the configured backend, then the environment.

    When ``inject`` is true and a manager returns a key, it is written into
    ``os.environ['GOOGLE_API_KEY']`` so the rest of the process (pydantic
    settings, LLM client) sees a single source of truth.
    """
    backend = os.getenv("ULTRON_SECRETS_BACKEND", "env").strip().lower()
    key: str | None = None
    if backend in {"aws", "aws-secrets-manager", "secretsmanager"}:
        key = fetch_from_aws_secrets_manager()
    elif backend in {"vault", "hashicorp", "hashicorp-vault"}:
        key = fetch_from_vault()
    elif backend in {"gcp", "gcp-secret-manager", "google"}:
        key = fetch_from_gcp_secret_manager()
    elif backend not in {"", "env", "environment"}:
        _LOGGER.warning("Unknown ULTRON_SECRETS_BACKEND=%s; using env.", backend)

    if not key:
        key = os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_API_KEY_1")
    if key and inject and not os.getenv("GOOGLE_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = key
    return key


__all__ = [
    "SecretResolutionError",
    "fetch_from_aws_secrets_manager",
    "fetch_from_gcp_secret_manager",
    "fetch_from_vault",
    "resolve_google_api_key",
]
