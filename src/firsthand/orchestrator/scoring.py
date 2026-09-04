"""RICE-shaped scoring, LLM-as-judge over the evidence gathered (design doc §5).

The model is given the redacted request, every retrieved passage, and whether a
duplicate was found, and returns impact / effort / urgency / confidence. It
scores only what the evidence supports — a thin evidence set should come back
with low confidence, which is what makes the routing gate escalate it (§2).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from firsthand.contracts import DuplicateOf, Evidence, Score, Urgency
from firsthand.llm.base import LLMClient

SYSTEM_PROMPT = """\
You score a product request on a RICE-style rubric from evidence only. Return
JSON only, with keys:
- "impact": number 0-10, how much this matters to users.
- "effort": number 0-10, rough build cost (10 = very large).
- "urgency": one of "low", "med", "high".
- "confidence": number 0-1, how well the evidence supports this score. If little
  or no evidence was retrieved, confidence must be low.
- "rationale": one sentence, citing the evidence you used.

Do not invent evidence. Do not decide routing. Return only the JSON object.
"""


class ScoreJudgement(BaseModel):
    """Structured output of the scoring call — a superset of ``Score``."""

    model_config = {"extra": "ignore"}

    impact: float = Field(ge=0.0, le=10.0)
    effort: float = Field(ge=0.0, le=10.0)
    urgency: Urgency
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""

    def to_score(self) -> Score:
        """Drop the rationale; keep the four rubric numbers the contract carries."""
        return Score(
            impact=self.impact,
            effort=self.effort,
            urgency=self.urgency,
            confidence=self.confidence,
        )


def _render_evidence(evidence: list[Evidence]) -> str:
    if not evidence:
        return "NO EVIDENCE WAS RETRIEVED."
    return "\n".join(f"- [{item.source}:{item.ref}] {item.snippet}" for item in evidence)


def scoring_user_prompt(
    redacted_text: str,
    evidence: list[Evidence],
    duplicate_of: DuplicateOf | None,
) -> str:
    """The exact user turn ``score_draft`` sends — public so callers/tests can key on it."""
    dup_line = (
        f"A likely duplicate exists: {duplicate_of.ticket_id} "
        f"(similarity {duplicate_of.similarity:.2f})."
        if duplicate_of is not None
        else "No duplicate was found."
    )
    return f"REQUEST:\n{redacted_text}\n\nEVIDENCE:\n{_render_evidence(evidence)}\n\n{dup_line}"


async def score_draft(
    llm: LLMClient,
    *,
    redacted_text: str,
    evidence: list[Evidence],
    duplicate_of: DuplicateOf | None,
) -> Score:
    """Ask the judge for a score over exactly the evidence on the draft."""
    user = scoring_user_prompt(redacted_text, evidence, duplicate_of)
    judgement = await llm.structured(system=SYSTEM_PROMPT, user=user, schema=ScoreJudgement)
    return judgement.to_score()
