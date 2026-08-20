"""Secret scan — the single most important operational guard in the repo.

A key beginning ``rzp_live_`` must never appear in the working tree OR git
history. Test-mode keys (``rzp_test_*``) are the only keys SENTINEL ever uses.

Exit code 0 = clean, 1 = a forbidden pattern was found. Wired into the Makefile,
CI (every push), and the pre-commit hook.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Forbidden patterns. Live Razorpay keys are the headline; generic live-secret
# heuristics catch accidental paste of a real credential.
FORBIDDEN = [
    ("razorpay-live-key", re.compile(r"rzp_live_[A-Za-z0-9]{8,}")),
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private-key-block", re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----")),
]

# Directories that never contain source we authored.
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "dist", ".pytest_cache",
            ".hypothesis", ".ruff_cache", ".mypy_cache"}

# The spec pack and this scanner itself legitimately mention the forbidden token.
ALLOWLIST_PATHS = {"docs/spec", "scripts/secret_scan.py", ".gitleaks.toml",
                  "LIMITATIONS.md", "DECISIONS.md", "README.md"}


def _allowlisted(rel: str) -> bool:
    return any(rel == p or rel.startswith(p + "/") for p in ALLOWLIST_PATHS)


def scan_tree() -> list[str]:
    findings: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        parts = set(path.relative_to(ROOT).parts)
        if parts & SKIP_DIRS:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if _allowlisted(rel):
            continue
        try:
            text = path.read_text(errors="ignore")
        except Exception:
            continue
        for name, pattern in FORBIDDEN:
            if pattern.search(text):
                findings.append(f"[tree] {rel}: matches forbidden pattern '{name}'")
    return findings


def scan_history() -> list[str]:
    """Scan the full git history for live keys. History rewrites are the only fix."""
    findings: list[str] = []
    try:
        blob = subprocess.run(
            ["git", "-C", str(ROOT), "log", "-p", "--all"],
            capture_output=True, text=True, timeout=120,
        ).stdout
    except Exception as exc:  # pragma: no cover - git absent
        return [f"[history] could not read git history: {exc}"]
    # Only the hard live-key rule runs over history; generic heuristics are too
    # noisy against diffs of the spec pack.
    for m in re.finditer(r"rzp_live_[A-Za-z0-9]{8,}", blob):
        findings.append(f"[history] live key present in git history: {m.group()[:14]}...")
    return findings


def main() -> int:
    findings = scan_tree() + scan_history()
    if findings:
        print("SECRET SCAN FAILED — forbidden material present:")
        for f in findings:
            print("  " + f)
        print("\nSENTINEL uses TEST-MODE keys only. Rotate the key and rewrite history.")
        return 1
    print("secret scan clean: no live keys in tree or history.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
