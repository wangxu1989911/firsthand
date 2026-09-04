"""The Jira connector (design doc §3, §5).

``JiraConnector`` answers the tool contract; ``JiraHTTPTransport`` is the real
REST path and ``RecordedJiraTransport`` the offline one every test uses.
"""

from firsthand.connectors.jira.connector import JiraConnector
from firsthand.connectors.jira.factory import jira_connector_from_config
from firsthand.connectors.jira.fake import RecordedJiraTransport, search_response
from firsthand.connectors.jira.transport import (
    JiraHTTPTransport,
    JiraTransport,
    JiraTransportError,
)

__all__ = [
    "JiraConnector",
    "JiraHTTPTransport",
    "JiraTransport",
    "JiraTransportError",
    "RecordedJiraTransport",
    "jira_connector_from_config",
    "search_response",
]
