"""Classification and field extraction from redacted text (design doc §2, §5).

One structured LLM call turns the reporter's words into a category, whatever
required fields it can already see, and a short neutral summary the dedup step
embeds. The model is asked for evidence-free extraction only — it never decides
whether something is a duplicate or how it should be routed (§2).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from firsthand.contracts import Category
from firsthand.llm.base import LLMClient

SYSTEM_PROMPT = """\
You triage incoming product feedback. Read the message and return JSON only.

Fields:
- "category": one of "bug", "feature", "question".
- "extracted_fields": an object mapping any of these keys you can fill from the
  message to a short value; omit keys the message does not answer. Keys:
  steps_to_reproduce, expected_behavior, actual_behavior, problem,
  proposed_solution, affected_users, context.
- "summary": one neutral sentence restating the request, no names or specifics
  that identify a person.

Do not guess. Do not add keys that are not listed. Do not decide if this is a
duplicate. Return only the JSON object.
"""


class Classification(BaseModel):
    """Structured output of the triage call."""

    model_config = {"extra": "ignore"}

    category: Category
    extracted_fields: dict[str, str] = Field(default_factory=dict)
    summary: str = ""

    def clean_fields(self) -> dict[str, str]:
        """Drop keys whose value is blank — an empty answer is not an answer (§3)."""
        return {key: value for key, value in self.extracted_fields.items() if value.strip()}


async def classify(llm: LLMClient, redacted_text: str) -> Classification:
    """Run the triage call. ``redacted_text`` is the only thing the model sees (§1)."""
    result = await llm.structured(
        system=SYSTEM_PROMPT,
        user=redacted_text,
        schema=Classification,
    )
    return result


def next_question(missing_fields: list[str]) -> str:
    """A single clarifying question covering what is still missing (§2).

    Deterministic and template-based so a clarification round costs no extra
    model call — the model's judgement was already spent on extraction.
    """
    readable = [field.replace("_", " ") for field in missing_fields]
    if len(readable) == 1:
        return f"Could you tell me the {readable[0]}?"
    head = ", ".join(readable[:-1])
    return f"Could you tell me the {head} and {readable[-1]}?"
