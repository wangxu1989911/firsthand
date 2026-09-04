"""Evidence connectors: thin adapters from a :class:`~firsthand.contracts.ToolCall`
to a list of retrieved :class:`~firsthand.contracts.Evidence` passages.

A connector never decides what evidence means — that is the orchestrator's job
(CLAUDE.md §2). Each connector is written directly against the §3 contracts; a
later pass can factor out whatever the Jira/Git/Docs adapters end up sharing.
"""
