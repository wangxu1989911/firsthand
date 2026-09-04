"""A fixture-backed Jira transport, so tests and the eval suite run offline (§8.6).

Live Jira is gated on an API token this build does not have. Everything that
would hit Jira instead goes through :class:`RecordedJiraTransport`, which
replays hand-written or recorded response bodies keyed by method and path.
"""

from __future__ import annotations

from typing import Any


class RecordedJiraTransport:
    """Replays recorded Jira REST responses. Satisfies ``JiraTransport``.

    ``responses`` is keyed by ``"GET /rest/api/3/search"`` etc. A value may be a
    single response dict, or a list consumed one call at a time (so a test can
    script "first search empty, second search hits"). A missing key raises, the
    same way an un-recorded LLM prompt does — it means the test would have
    needed the network.
    """

    def __init__(self, responses: dict[str, Any]) -> None:
        self._responses: dict[str, Any] = {}
        for key, value in responses.items():
            self._responses[key] = list(value) if isinstance(value, list) else value
        #: Every call made, for assertions.
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def _take(self, method: str, path: str, args: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((method, path, args))
        key = f"{method} {path}"
        if key not in self._responses:
            raise KeyError(f"no recorded Jira response for {key!r}")
        value = self._responses[key]
        if isinstance(value, list):
            if not value:
                raise KeyError(f"recorded Jira responses for {key!r} are exhausted")
            return dict(value.pop(0))
        result: dict[str, Any] = dict(value)
        return result

    async def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        return self._take("GET", path, params)

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._take("POST", path, payload)


def search_response(*issues: tuple[str, str, str]) -> dict[str, Any]:
    """Build a ``/search`` body from ``(key, summary, status)`` triples."""
    return {
        "issues": [
            {
                "key": key,
                "fields": {"summary": summary, "status": {"name": status}},
            }
            for key, summary, status in issues
        ]
    }
