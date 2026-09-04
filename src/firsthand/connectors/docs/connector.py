"""``search_design_docs`` — retrieve design-doc passages for a query.

The connector returns passages, never a verdict. When a passage records that
something was already decided, that passage is what comes back; whether it means
"don't file this" is the orchestrator's call, not the connector's (§5). When
nothing matches, the result is ``ToolSuccess(evidence=[])`` — an explicit
no-evidence state, never a hedged or invented hit.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable

import httpx

from firsthand.connectors.docs.providers import (
    DEFAULT_TIMEOUT_SECONDS,
    ConfluenceProvider,
    DocsProvider,
)
from firsthand.connectors.docs.retrieval import Bm25Index, chunk_page
from firsthand.contracts import (
    ConnectorConfig,
    Evidence,
    ToolCall,
    ToolError,
    ToolName,
    ToolResult,
    ToolSuccess,
)

logger = logging.getLogger(__name__)

#: Default number of passages one lookup returns. The load-bearing cap is the
#: six tool calls per request (§7); this just keeps a single call's payload sane.
DEFAULT_MAX_RESULTS = 5

#: A decryptor turns the stored ciphertext credential into a usable token.
Decryptor = Callable[[str], str]


def _default_decryptor(ciphertext: str) -> str:
    """Decrypt via ``firsthand.secrets`` (Phase 2); pass through if it is absent.

    The module is imported lazily so this connector can be built and unit-tested
    before Phase 2 lands. Degrading to a pass-through keeps a dev stack working
    with plaintext credentials; production sets the real key and gets real
    decryption (§8.7).
    """
    try:
        secrets = importlib.import_module("firsthand.secrets")
    except ModuleNotFoundError:
        logger.warning("firsthand.secrets is unavailable; using the connector credential as-is")
        return ciphertext
    return str(secrets.decrypt(ciphertext))


class DesignDocsConnector:
    """Wraps a :class:`DocsProvider` with chunking, ranking, and evidence shaping."""

    tool_name: ToolName = "search_design_docs"

    def __init__(self, provider: DocsProvider, *, max_results: int = DEFAULT_MAX_RESULTS) -> None:
        if max_results <= 0:
            raise ValueError("max_results must be positive")
        self._provider = provider
        self._max_results = max_results

    @classmethod
    def from_config(
        cls,
        config: ConnectorConfig,
        *,
        decrypt: Decryptor | None = None,
        client: httpx.AsyncClient | None = None,
        max_results: int = DEFAULT_MAX_RESULTS,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> DesignDocsConnector:
        """Build the Confluence-backed connector from a stored connector config.

        ``config.credential`` is ciphertext at rest; it is decrypted here and the
        plaintext token never leaves this process. Pass ``client`` to inject a
        pre-built (or test) ``httpx`` client; otherwise one is created and should
        be released with :meth:`aclose`.
        """
        if config.type != "docs":
            raise ValueError(f"expected a 'docs' connector config, got {config.type!r}")
        decryptor = decrypt if decrypt is not None else _default_decryptor
        provider = ConfluenceProvider(
            base_url=config.base_url,
            credential=decryptor(config.credential),
            client=client,
            timeout=timeout,
        )
        return cls(provider, max_results=max_results)

    async def run(self, call: ToolCall) -> ToolResult:
        """Execute a ``search_design_docs`` :class:`ToolCall` from the orchestrator."""
        if call.name != self.tool_name:
            return ToolError(error=f"DesignDocsConnector cannot handle {call.name!r}")
        query = call.args.get("query")
        if not isinstance(query, str):
            return ToolError(error="search_design_docs needs a string 'query' argument")
        raw_limit = call.args.get("limit")
        limit = (
            raw_limit if isinstance(raw_limit, int) and not isinstance(raw_limit, bool) else None
        )
        return await self.search(query, limit=limit)

    async def search(self, query: str, *, limit: int | None = None) -> ToolResult:
        """Retrieve and rank passages for ``query``.

        Returns a :class:`ToolError` when the provider cannot be reached, so a
        transport failure is surfaced rather than silently read as "nothing was
        decided about this".
        """
        text = query.strip()
        if not text:
            return ToolError(error="search_design_docs needs a non-empty query")
        count = self._max_results if limit is None else limit
        if count <= 0:
            return ToolError(error="limit must be positive")

        try:
            pages = await self._provider.fetch(text, limit=count)
        except httpx.TimeoutException:
            logger.warning("docs provider timed out")
            return ToolError(error="docs provider timed out")
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logger.warning("docs provider returned HTTP %s", status)
            return ToolError(error=f"docs provider returned HTTP {status}")
        except httpx.HTTPError:
            logger.exception("docs provider request failed")
            return ToolError(error="could not reach docs provider")
        except ValueError:
            logger.exception("docs provider returned an unreadable response")
            return ToolError(error="could not reach docs provider")

        passages = [passage for page in pages for passage in chunk_page(page)]
        ranked = Bm25Index(passages).rank(text, limit=count)
        evidence = [
            Evidence(
                source="docs",
                ref=passage.page.url,
                snippet=passage.text,
                retrieved_by=self.tool_name,
            )
            for passage in ranked
        ]
        return ToolSuccess(evidence=evidence)

    async def aclose(self) -> None:
        """Release provider-owned network resources."""
        await self._provider.aclose()
