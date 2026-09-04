"""Evidence connectors: thin adapters from a :class:`~firsthand.contracts.ToolCall`
to a list of retrieved :class:`~firsthand.contracts.Evidence` passages.

A connector never decides what evidence means — that is the orchestrator's job
(CLAUDE.md §2). Each connector answers the ``ToolCall`` / ``ToolResult`` contract
in ``firsthand.contracts.tools`` directly against the §3 shapes; a later pass can
factor out whatever the Jira, Git, and Docs adapters end up sharing.
"""
