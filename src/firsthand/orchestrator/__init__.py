"""The dedup MVP orchestrator (design doc §2, §5).

``Orchestrator.handle`` is the entry point: one inbound message in, one
``OrchestratorReply`` out, all state through the ``StateStore``. Phase 2's web
and Slack adapters call it; this package owns the loop, routing, redaction,
classification, dedup and scoring that sit behind it.
"""

from firsthand.orchestrator.classify import Classification, classify, next_question
from firsthand.orchestrator.dedup import index_request, nearest, pick_duplicate
from firsthand.orchestrator.fields import REQUIRED_FIELDS, required_fields_for
from firsthand.orchestrator.loop import (
    Orchestrator,
    OrchestratorDeps,
    OrchestratorReply,
)
from firsthand.orchestrator.redaction import redact
from firsthand.orchestrator.routing import CONFIDENCE_FLOOR, decide_routing
from firsthand.orchestrator.scoring import ScoreJudgement, score_draft
from firsthand.orchestrator.tools import ToolBudgetError, ToolRegistry

__all__ = [
    "CONFIDENCE_FLOOR",
    "REQUIRED_FIELDS",
    "Classification",
    "Orchestrator",
    "OrchestratorDeps",
    "OrchestratorReply",
    "ScoreJudgement",
    "ToolBudgetError",
    "ToolRegistry",
    "classify",
    "decide_routing",
    "index_request",
    "nearest",
    "next_question",
    "pick_duplicate",
    "redact",
    "required_fields_for",
    "score_draft",
]
