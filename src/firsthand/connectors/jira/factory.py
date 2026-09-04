"""Build a live :class:`JiraConnector` from a stored :class:`ConnectorConfig`.

The stored ``credential`` is ciphertext at rest (§8.7). Decryption lives in
``firsthand.secrets`` (owned by Phase 2). This module lazy-imports it: if it is
not there yet the credential is used as-is and a warning is logged, so Phase 1
can be exercised end to end before Phase 2 lands.
"""

from __future__ import annotations

import importlib
import logging

from firsthand.connectors.jira.connector import JiraConnector
from firsthand.connectors.jira.transport import JiraHTTPTransport
from firsthand.contracts import ConnectorConfig

logger = logging.getLogger(__name__)


def _decrypt(value: str) -> str:
    try:
        secrets = importlib.import_module("firsthand.secrets")
    except ImportError:
        logger.warning(
            "firsthand.secrets not present; using the Jira credential as plaintext."
            " This is only acceptable before Phase 2 lands the secret store (§8.7)."
        )
        return value
    return str(secrets.decrypt(value))


def jira_connector_from_config(config: ConnectorConfig) -> JiraConnector:
    """Decrypt the credential and wire up a real Jira transport.

    ``credential`` decrypts to ``"<email>:<api_token>"`` for Jira Cloud basic
    auth. Raises ``ValueError`` for a wrong-typed or malformed config.
    """
    if config.type != "jira":
        raise ValueError(f"expected a jira connector config, got {config.type!r}")
    email, _, api_token = _decrypt(config.credential).partition(":")
    if not email or not api_token:
        raise ValueError("jira credential must decrypt to '<email>:<api_token>'")
    transport = JiraHTTPTransport(
        base_url=config.base_url,
        email=email,
        api_token=api_token,
    )
    return JiraConnector(transport, browse_base_url=config.base_url)
