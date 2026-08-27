"""Resolve API keys from a secret manager before falling back to env vars.

Production deployments should inject ``GOOGLE_API_KEY`` from AWS Secrets
Manager, HashiCorp Vault, or GCP Secret Manager rather than a long-lived
``.env`` file. Environment mode is convenient for local use. Selecting a
manager enables fail-closed behavior: missing configuration, SDKs, provider
access, or secret values stop startup instead of falling back to environment
credentials.

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
import os
from collections.abc import Callable
from typing import Any

# Imported by name so dependency/security tooling can see the SDKs. They are
# optional in env mode; selecting a manager without its SDK fails closed.
try:  # pragma: no cover - import presence is environment-specific
    import boto3
except ImportError:  # pragma: no cover
    boto3 = None

try:  # pragma: no cover
    import hvac
except ImportError:  # pragma: no cover
    hvac = None

try:  # pragma: no cover
    from google.cloud import secretmanager as gcp_secretmanager
except ImportError:  # pragma: no cover
    gcp_secretmanager = None


class SecretResolutionError(RuntimeError):
    """Raised when a configured secret manager cannot be reached."""


def _extract_google_key(payload: Any) -> str | None:
    """Pull ``GOOGLE_API_KEY`` from a JSON object or a raw string value."""
    key: str | None = None
    if isinstance(payload, dict):
        for name in ("GOOGLE_API_KEY", "google_api_key", "api_key"):
            value = payload.get(name)
            if isinstance(value, str) and value.strip():
                key = value.strip()
                break
    elif isinstance(payload, (str, bytes)):
        try:
            text = (
                payload.decode("utf-8") if isinstance(payload, bytes) else payload
            ).strip()
        except UnicodeDecodeError:
            text = ""
        if text.startswith(("{", "[")):
            try:
                key = _extract_google_key(json.loads(text))
            except json.JSONDecodeError:
                key = None
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
            raise SecretResolutionError(
                "AWS Secrets Manager was selected but boto3 is not installed; "
                "install the 'secrets' extra"
            )
        kwargs: dict[str, str] = {}
        region = region or os.getenv("ULTRON_AWS_REGION") or os.getenv("AWS_REGION")
        if region:
            kwargs["region_name"] = region
        try:
            client = boto3.client("secretsmanager", **kwargs)
        except Exception as exc:  # noqa: BLE001
            raise SecretResolutionError(
                "AWS Secrets Manager client initialization failed "
                f"({type(exc).__name__}); provider details were omitted"
            ) from None
    try:
        response = client.get_secret_value(SecretId=secret_id)
        payload = response.get("SecretString") or response.get("SecretBinary")
        return _extract_google_key(payload)
    except Exception as exc:  # noqa: BLE001 (SDK + injected test doubles)
        raise SecretResolutionError(
            "AWS Secrets Manager get_secret_value failed "
            f"({type(exc).__name__}); provider details were omitted"
        ) from None


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
            raise SecretResolutionError(
                "HashiCorp Vault was selected but hvac is not installed; "
                "install the 'secrets' extra"
            )
        url = url or os.getenv("ULTRON_VAULT_ADDR") or os.getenv("VAULT_ADDR", "")
        token = token or os.getenv("ULTRON_VAULT_TOKEN") or os.getenv("VAULT_TOKEN", "")
        if not url or not token:
            raise SecretResolutionError(
                "Vault requires ULTRON_VAULT_ADDR and ULTRON_VAULT_TOKEN"
            )
        try:
            client = hvac.Client(url=url, token=token)
        except Exception as exc:  # noqa: BLE001
            raise SecretResolutionError(
                "Vault client initialization failed "
                f"({type(exc).__name__}); provider details were omitted"
            ) from None
    try:
        response = client.secrets.kv.v2.read_secret_version(path=path)
        data = (response or {}).get("data", {}).get("data", {})
        return _extract_google_key(data)
    except Exception as exc:  # noqa: BLE001
        raise SecretResolutionError(
            "Vault read_secret_version failed "
            f"({type(exc).__name__}); provider details were omitted"
        ) from None


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
            raise SecretResolutionError(
                "GCP Secret Manager was selected but google-cloud-secret-manager "
                "is not installed; install the 'secrets' extra"
            )
        try:
            client = gcp_secretmanager.SecretManagerServiceClient()
        except Exception as exc:  # noqa: BLE001
            raise SecretResolutionError(
                "GCP Secret Manager client initialization failed "
                f"({type(exc).__name__}); provider details were omitted"
            ) from None
    try:
        response = client.access_secret_version(name=name)
        return _extract_google_key(response.payload.data)
    except Exception as exc:  # noqa: BLE001
        raise SecretResolutionError(
            "GCP Secret Manager access_secret_version failed "
            f"({type(exc).__name__}); provider details were omitted"
        ) from None


def resolve_google_api_key(*, inject: bool = True) -> str | None:
    """Resolve the Gemini key using the explicitly configured source.

    ``env`` mode reads ``GOOGLE_API_KEY`` (then ``GOOGLE_API_KEY_1``). A
    configured manager is fail-closed: invalid configuration, an unavailable
    SDK/provider, or an empty payload raises :class:`SecretResolutionError`
    rather than silently using a possibly stale environment value.

    When ``inject`` is true, the resolved value is written to
    ``os.environ['GOOGLE_API_KEY']`` so pydantic settings and the LLM client
    consume the same value. A manager-provided value deliberately replaces an
    existing environment value.
    """
    configured = os.getenv("ULTRON_SECRETS_BACKEND", "env").strip().lower()
    aliases = {
        "": "env",
        "environment": "env",
        "aws-secrets-manager": "aws",
        "secretsmanager": "aws",
        "hashicorp": "vault",
        "hashicorp-vault": "vault",
        "gcp-secret-manager": "gcp",
        "google": "gcp",
    }
    backend = aliases.get(configured, configured)

    if backend == "env":
        key = os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_API_KEY_1")
        if key and inject and not os.getenv("GOOGLE_API_KEY"):
            os.environ["GOOGLE_API_KEY"] = key
        return key

    fetchers: dict[str, Callable[[], str | None]] = {
        "aws": fetch_from_aws_secrets_manager,
        "vault": fetch_from_vault,
        "gcp": fetch_from_gcp_secret_manager,
    }
    fetch = fetchers.get(backend)
    if fetch is None:
        raise SecretResolutionError(
            f"Unsupported ULTRON_SECRETS_BACKEND={configured!r}; "
            "expected env, aws, vault, or gcp"
        )

    key = fetch()
    if not key:
        raise SecretResolutionError(
            f"The {backend} secret backend returned no GOOGLE_API_KEY; "
            "environment fallback is disabled when a manager is selected"
        )
    if inject:
        os.environ["GOOGLE_API_KEY"] = key
    return key


__all__ = [
    "SecretResolutionError",
    "fetch_from_aws_secrets_manager",
    "fetch_from_gcp_secret_manager",
    "fetch_from_vault",
    "resolve_google_api_key",
]
