"""Tests for secret-manager resolution (AWS / Vault / GCP)."""

from types import SimpleNamespace

import pytest

from ultron.secrets import (
    SecretResolutionError,
    fetch_from_aws_secrets_manager,
    fetch_from_gcp_secret_manager,
    fetch_from_vault,
    resolve_google_api_key,
)


class _FakeAWS:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.called_with: dict | None = None

    def get_secret_value(self, SecretId: str) -> dict:
        self.called_with = {"SecretId": SecretId}
        return {"SecretString": self.payload}


class _FakeVault:
    def __init__(self, data: dict) -> None:
        self._data = data
        self.path = None

    @property
    def secrets(self):
        return self

    @property
    def kv(self):
        return self

    @property
    def v2(self):
        return self

    def read_secret_version(self, path: str) -> dict:
        self.path = path
        return {"data": {"data": self._data}}


class _FakeGCP:
    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.name = None

    def access_secret_version(self, name: str):
        self.name = name
        return SimpleNamespace(payload=SimpleNamespace(data=self.payload.encode()))


def test_aws_secrets_manager_json_payload():
    client = _FakeAWS('{"GOOGLE_API_KEY": "AIza-from-aws"}')
    key = fetch_from_aws_secrets_manager("ultron/key", client=client)
    assert key == "AIza-from-aws"
    assert client.called_with == {"SecretId": "ultron/key"}


def test_aws_secrets_manager_plain_string():
    client = _FakeAWS("AIza-plain")
    assert fetch_from_aws_secrets_manager("id", client=client) == "AIza-plain"


def test_aws_missing_id_is_none(monkeypatch):
    monkeypatch.delenv("ULTRON_AWS_SECRET_ID", raising=False)
    assert fetch_from_aws_secrets_manager() is None


def test_aws_client_error():
    class Boom:
        def get_secret_value(self, SecretId: str) -> dict:
            raise RuntimeError("denied")

    # RuntimeError is not BotoCoreError; wrap via generic path
    with pytest.raises((SecretResolutionError, RuntimeError)):
        fetch_from_aws_secrets_manager("id", client=Boom())


def test_vault_kv2():
    client = _FakeVault({"GOOGLE_API_KEY": "AIza-vault"})
    assert fetch_from_vault("ultron", client=client) == "AIza-vault"
    assert client.path == "ultron"


def test_gcp_secret_manager():
    client = _FakeGCP("AIza-gcp")
    key = fetch_from_gcp_secret_manager(
        "projects/p/secrets/s/versions/1", client=client
    )
    assert key == "AIza-gcp"


def test_resolve_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("ULTRON_SECRETS_BACKEND", "env")
    monkeypatch.setenv("GOOGLE_API_KEY", "AIza-env")
    assert resolve_google_api_key(inject=False) == "AIza-env"


def test_resolve_aws_injects_env(monkeypatch):
    monkeypatch.setenv("ULTRON_SECRETS_BACKEND", "aws")
    monkeypatch.setenv("ULTRON_AWS_SECRET_ID", "ultron/key")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    class Injected:
        def get_secret_value(self, SecretId: str) -> dict:
            return {"SecretString": "AIza-injected"}

    # Patch the fetch helper's client construction by stubbing boto3-less path:
    # call fetch directly then resolve from env after inject.
    from ultron import secrets as secrets_mod

    monkeypatch.setattr(
        secrets_mod,
        "fetch_from_aws_secrets_manager",
        lambda: "AIza-injected",
    )
    key = resolve_google_api_key(inject=True)
    assert key == "AIza-injected"
    assert secrets_mod.os.environ["GOOGLE_API_KEY"] == "AIza-injected"
