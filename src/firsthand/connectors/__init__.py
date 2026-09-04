"""Connectors: each one retrieves evidence for the orchestrator, never a verdict.

Every connector answers the §3 ``ToolCall`` / ``ToolResult`` contract in
``firsthand.contracts.tools`` and returns ``Evidence`` passages directly — there
is deliberately no shared base class coupling Jira, Git, and Docs together. A
connector never decides what its evidence means; that is the orchestrator's job
(CLAUDE.md §2).
"""
