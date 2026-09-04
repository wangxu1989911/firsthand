"""Building a live connector from a stored config: credential decryption degrades gracefully."""

from __future__ import annotations

import sys
import types

import pytest

from firsthand.connectors.jira import JiraConnector
from firsthand.connectors.jira.factory import jira_connector_from_config
from firsthand.contracts import ConnectorConfig


def _config(credential: str, *, type_: str = "jira") -> ConnectorConfig:
    return ConnectorConfig(
        type=type_,  # type: ignore[arg-type]
        base_url="https://jira.test",
        credential=credential,
        updated_by="admin",
    )


def test_without_the_secrets_module_the_credential_is_used_as_plaintext(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setitem(sys.modules, "firsthand.secrets", None)  # force ModuleNotFoundError
    with caplog.at_level("WARNING"):
        connector = jira_connector_from_config(_config("bot@corp:token"))
    assert isinstance(connector, JiraConnector)
    assert "using the Jira credential as plaintext" in caplog.text


def test_with_the_secrets_module_the_credential_is_decrypted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = types.ModuleType("firsthand.secrets")
    fake.decrypt = lambda value: "bot@corp:decrypted-token"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "firsthand.secrets", fake)
    connector = jira_connector_from_config(_config("ciphertext"))
    assert isinstance(connector, JiraConnector)


def test_a_non_jira_config_is_refused() -> None:
    with pytest.raises(ValueError, match="expected a jira connector"):
        jira_connector_from_config(_config("e:t", type_="git"))


def test_a_credential_without_a_colon_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "firsthand.secrets", None)
    with pytest.raises(ValueError, match="email>:<api_token"):
        jira_connector_from_config(_config("just-a-token"))
