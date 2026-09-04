"""IssueDraft and friends — the per-conversation state (design doc §3)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: The clarification loop is bounded (§2): three rounds, then the draft is
#: either sufficient or gets flagged incomplete for a human.
MAX_CLARIFICATION_ROUNDS = 3

#: At or above this cosine similarity a match is treated as the same request
#: rather than a neighbour (§2).
DUPLICATE_SIMILARITY_THRESHOLD = 0.9

Surface = Literal["web", "slack"]
Category = Literal["bug", "feature", "question"]
EvidenceSource = Literal["jira", "git", "docs"]
Urgency = Literal["low", "med", "high"]
RoutingDecision = Literal["auto_file", "escalate", "ask_again"]
DraftStatus = Literal[
    "gathering_info",
    "investigating",
    "scored",
    "filed",
    "escalated",
    "closed",
]


class Contract(BaseModel):
    """Base for every wire shape: strict, so a typo is a validation error.

    ``validate_assignment`` matters as much as validation at construction here:
    a draft is mutated across turns, and without it ``draft.round = -1`` or
    ``draft.status = "done"`` is accepted silently, defeats the §2 round cap,
    and then raises on the *next* container to read it back (§8.3) — the writer
    never sees the error, the reader takes the crash.
    """

    model_config = ConfigDict(extra="forbid", frozen=False, validate_assignment=True)


class Conversation(Contract):
    """Which intake adapter and session own this draft."""

    surface: Surface
    session_id: str = Field(min_length=1)


class Evidence(Contract):
    """A passage an agent actually retrieved. Never a conclusion (§3)."""

    source: EvidenceSource
    ref: str = Field(min_length=1, description="Ticket key, commit sha, or doc URL — followable")
    snippet: str = Field(
        min_length=1, description="The actual passage the claim rests on — never empty"
    )
    retrieved_by: str = Field(min_length=1, description="Which tool call produced this")


class DuplicateOf(Contract):
    """The existing ticket this request duplicates, and how close the match is."""

    ticket_id: str = Field(min_length=1)
    similarity: float = Field(ge=0.0, le=1.0)


class Score(Contract):
    """RICE-shaped rubric output (§5). Impact and effort are 0-10."""

    impact: float = Field(ge=0.0, le=10.0)
    effort: float = Field(ge=0.0, le=10.0)
    urgency: Urgency
    confidence: float = Field(ge=0.0, le=1.0)


class Routing(Contract):
    """What the urgency gate decided, and why (§2)."""

    decision: RoutingDecision
    reason: str = Field(min_length=1)


class Ticket(Contract):
    """The tracker ticket this draft became."""

    id: str = Field(min_length=1)
    url: str = Field(min_length=1)
    status: str = Field(min_length=1)


class IssueDraft(Contract):
    """Everything one conversation has accumulated so far.

    ``raw_text`` holds exactly what the reporter typed; ``redacted_text`` is the
    only version any model is ever shown (§1). Both are kept so a human
    reviewing an escalation can still see the original.
    """

    conversation: Conversation
    raw_text: str
    redacted_text: str = ""
    #: A short, neutral one-line restatement of the request, produced at
    #: classification (§5). Used as the dedup/search query and as the filed
    #: ticket's title; carries no names or specifics, so it is safe to embed
    #: and to show a reviewer. Empty until the draft has been classified.
    summary: str = ""
    category: Category | None = None
    round: int = Field(default=0, ge=0)
    required_fields: list[str] = Field(default_factory=list)
    extracted_fields: dict[str, str] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    duplicate_of: DuplicateOf | None = None
    score: Score | None = None
    routing: Routing | None = None
    ticket: Ticket | None = None
    status: DraftStatus = "gathering_info"

    @property
    def rounds_remaining(self) -> int:
        """Clarification rounds left before the round cap forces a decision."""
        return max(MAX_CLARIFICATION_ROUNDS - self.round, 0)

    @property
    def may_ask_again(self) -> bool:
        """Whether the agent is still allowed to ask a clarifying question (§2)."""
        return self.round < MAX_CLARIFICATION_ROUNDS

    def recompute_missing_fields(self, inferable: set[str] | None = None) -> list[str]:
        """Required minus filled, minus anything evidence already answers (§3).

        Sets and returns ``missing_fields``. ``inferable`` names fields the
        orchestrator believes the gathered evidence covers, so the agent does
        not spend a round asking about something it already knows.
        """
        # Keyed on having an answer, not on having a key: an extractor that
        # emits "" for "not found" must not silently retire the question.
        covered = {name for name, value in self.extracted_fields.items() if value.strip()}
        covered |= inferable or set()
        self.missing_fields = [field for field in self.required_fields if field not in covered]
        return self.missing_fields

    def cite(self, source: EvidenceSource) -> list[Evidence]:
        """Evidence gathered from one source — the backing for a grounded claim."""
        return [item for item in self.evidence if item.source == source]
