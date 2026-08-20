"""CRITICAL TEST — the policy engine performs no I/O.

Enforced structurally, not by discipline: we walk the import graph of every
module in ``sentinel.policy`` and assert none of them import a forbidden I/O
module (socket, http, sqlite3, requests, httpx, open-the-network, the clock, or
randomness). A pure engine can be exhaustively unit-tested, property-tested, and
replayed; the moment it reads a clock it becomes untestable.

Until Phase 2 lands the policy package, this test asserts the *absence* is not a
silent pass — it xfails with a clear message so the gate is visibly pending.
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib

import pytest

pytestmark = [pytest.mark.tier1, pytest.mark.critical]

# Modules a pure decision core must never pull in.
FORBIDDEN_IMPORTS = {
    "socket", "http", "httpx", "requests", "urllib", "urllib3", "aiohttp",
    "sqlite3", "psycopg2", "sqlalchemy",
    "random", "secrets",
    "asyncio",
    # 'time' and 'datetime' are forbidden too: the engine receives the clock via
    # DecisionContext.env, never reads it. 'os' is forbidden (env/fs access).
    "time", "datetime", "os", "pathlib", "subprocess",
}

# Standard-library helpers a pure engine legitimately uses.
ALLOWED = {"enum", "dataclasses", "typing", "math", "functools", "itertools",
          "collections", "re", "sentinel"}


def _policy_package_dir() -> pathlib.Path | None:
    spec = importlib.util.find_spec("sentinel")
    assert spec and spec.submodule_search_locations
    root = pathlib.Path(list(spec.submodule_search_locations)[0])
    policy = root / "policy"
    return policy if policy.is_dir() else None


def _imports_of(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                found.add(node.module.split(".")[0])
    return found


def test_policy_engine_has_no_io_imports():
    pkg = _policy_package_dir()
    if pkg is None:
        pytest.xfail("sentinel.policy not built yet (Phase 2). Gate pending, not passing.")
    offenders = {}
    for py in pkg.rglob("*.py"):
        bad = _imports_of(py) & FORBIDDEN_IMPORTS
        if bad:
            offenders[py.name] = sorted(bad)
    assert not offenders, (
        "policy engine imports forbidden I/O modules: "
        + "; ".join(f"{k} -> {v}" for k, v in offenders.items())
    )
