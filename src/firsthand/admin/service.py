"""Admin write actions: escalation review and connector configuration."""

from __future__ import annotations

import logging
from typing import Literal

from firsthand.admin.connectors import ConnectorConfigStore
from firsthand.admin.dashboard import REVIEWABLE_STATES
from firsthand.contracts import ConnectorConfig, ConnectorType, DraftStatus, IssueDraft
from firsthand.secrets import encrypt
from firsthand.storage import StateStore

__all__ = ["ReviewDecision", "review_draft", "save_connector"]

logger = logging.getLogger(__name__)

ReviewDecision = Literal["approve", "reject"]

_STATUS_AFTER: dict[ReviewDecision, DraftStatus] = {"approve": "filed", "reject": "closed"}


async def review_draft(
    state: StateStore,
    session_id: str,
    decision: ReviewDecision,
    *,
    reviewer: str,
) -> IssueDraft:
    """Approve or reject an escalated draft and persist the new status.

    Raises ``LookupError`` if the session has no draft and ``ValueError`` if the
    draft is not in a reviewable state.
    """
    draft = await state.get(session_id)
    if draft is None:
        raise LookupError(f"no draft for session {session_id!r}")
    if draft.status not in REVIEWABLE_STATES:
        raise ValueError(f"draft {session_id!r} is {draft.status}, not awaiting review")

    draft.status = _STATUS_AFTER[decision]
    await state.set(session_id, draft)
    logger.info("escalated draft %r %sed by %r", session_id, decision, reviewer)
    return draft


async def save_connector(
    store: ConnectorConfigStore,
    *,
    connector_type: ConnectorType,
    base_url: str,
    credential: str,
    enabled: bool,
    updated_by: str,
) -> ConnectorConfig:
    """Create or update a connector, encrypting a newly supplied credential.

    An empty ``credential`` leaves an existing one untouched (the form never
    renders the secret back, so a blank field means "unchanged"), or stores an
    empty string when the connector is new.
    """
    existing = await store.get(connector_type)
    if credential:
        stored_credential = encrypt(credential)
    elif existing is not None:
        stored_credential = existing.credential
    else:
        stored_credential = ""

    config = ConnectorConfig(
        type=connector_type,
        base_url=base_url,
        credential=stored_credential,
        enabled=enabled,
        updated_by=updated_by,
    )
    await store.put(config)
    logger.info("connector %r saved by %r", connector_type, updated_by)
    return config
