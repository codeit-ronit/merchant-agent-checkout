"""Config loading. This is I/O — it is NOT imported by the policy engine, which
receives its policy set as an already-parsed object.

The config directory is ``config/`` at the repo root, overridable with
``SENTINEL_CONFIG_DIR`` (used by tests to point at fixtures)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def config_dir() -> Path:
    override = os.environ.get("SENTINEL_CONFIG_DIR")
    return Path(override) if override else _REPO_ROOT / "config"


def repo_root() -> Path:
    return _REPO_ROOT


def load_yaml(name: str) -> dict[str, Any]:
    path = config_dir() / name
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    with path.open() as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"config {name} did not parse to a mapping")
    return data


@lru_cache(maxsize=8)
def load_yaml_cached(name: str) -> dict[str, Any]:
    return load_yaml(name)
