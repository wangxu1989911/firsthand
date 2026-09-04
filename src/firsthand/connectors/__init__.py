"""Connectors: each one retrieves evidence for the orchestrator, never a verdict.

Every connector is written directly against the §3 ``ToolCall`` / ``Evidence``
contracts — there is deliberately no shared base class to couple them together.
"""
