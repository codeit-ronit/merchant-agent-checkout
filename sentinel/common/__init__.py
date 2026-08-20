"""Foundational, dependency-light utilities shared across SENTINEL.

Nothing in here does I/O except where explicitly named (e.g. clock helpers used
by callers, never by the policy engine). The policy engine imports only
``canonical`` and ``money`` from this package — both are pure.
"""
