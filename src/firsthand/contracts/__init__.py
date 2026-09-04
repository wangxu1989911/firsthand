"""The three shapes that carry the whole system (design doc §3).

Treat these as fixed. A track that discovers it needs a new field flags the
change rather than patching it locally — see CLAUDE.md and §9.
"""

from firsthand.contracts.admin import AdminUser, ConnectorConfig, ConnectorType
from firsthand.contracts.draft import (
    DUPLICATE_SIMILARITY_THRESHOLD,
    MAX_CLARIFICATION_ROUNDS,
    Category,
    Conversation,
    DraftStatus,
    DuplicateOf,
    Evidence,
    EvidenceSource,
    IssueDraft,
    Routing,
    RoutingDecision,
    Score,
    Surface,
    Ticket,
    Urgency,
)
from firsthand.contracts.tools import (
    MAX_TOOL_CALLS,
    ToolCall,
    ToolError,
    ToolName,
    ToolResult,
    ToolSuccess,
)

__all__ = [
    "DUPLICATE_SIMILARITY_THRESHOLD",
    "MAX_CLARIFICATION_ROUNDS",
    "MAX_TOOL_CALLS",
    "AdminUser",
    "Category",
    "ConnectorConfig",
    "ConnectorType",
    "Conversation",
    "DraftStatus",
    "DuplicateOf",
    "Evidence",
    "EvidenceSource",
    "IssueDraft",
    "Routing",
    "RoutingDecision",
    "Score",
    "Surface",
    "Ticket",
    "ToolCall",
    "ToolError",
    "ToolName",
    "ToolResult",
    "ToolSuccess",
    "Urgency",
]
