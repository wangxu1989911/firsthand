"""The ``search_git_history`` connector (design doc Phase 3).

Public surface:

* :class:`GitHistoryConnector` — construct with a ``git`` :class:`ConnectorConfig`,
  call :meth:`~GitHistoryConnector.run` with a :class:`ToolCall`.
* :class:`GitConnectorSettings` — the ``FIRSTHAND_GIT_*`` process configuration.
* :class:`GitConnectorError` — raised for configuration problems.
"""

from firsthand.connectors.git.connector import GitConnectorError, GitHistoryConnector
from firsthand.connectors.git.settings import GitConnectorSettings

__all__ = [
    "GitConnectorError",
    "GitConnectorSettings",
    "GitHistoryConnector",
]
