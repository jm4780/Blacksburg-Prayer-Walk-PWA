"""Which build is this, actually?

Added after a Phase 3.5 preview looked identical to the previous version and there was
no way, from the app itself, to tell whether that was a stale checkout, a stale
frontend bundle, a stale service worker, or a real bug. Four candidate causes and no
observable to separate them is a bad place to debug from.

So: every layer states its own identity, and the app shows all of them.

  - the SERVER build      resolved here, from git or `BPW_BUILD_ID`
  - the FRONTEND build    stamped into the bundle at `vite build` time
  - the NETWORK data      whether the segments on disk carry v1.3 neighbourhoods

Those three can disagree, and *which* pair disagrees names the problem:

  frontend ≠ server   the browser or service worker is serving an old bundle
  data is v1.2        the pipeline has not been re-run since the network changed
  server is behind    the checkout was never pulled

Resolution order is git, then `BPW_BUILD_ID`, then "unknown". Git is preferred because
it needs nothing set up — the common deployment here is a Codespace with a real
checkout — but a container built from an export has no `.git`, so the environment
variable is the documented escape hatch.
"""
from __future__ import annotations

import functools
import os
import subprocess
from datetime import datetime, timezone

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stamped when the process started. Not when the code was written — a long-running
# server that has not been restarted is itself a thing worth being able to see.
_STARTED_AT = datetime.now(timezone.utc).isoformat(timespec="seconds")


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(("git", *args), cwd=_REPO_ROOT, capture_output=True,
                             text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


@functools.lru_cache(maxsize=1)
def build_info() -> dict:
    """Identity of the running server. Cached — none of it changes while it runs."""
    env_id = os.environ.get("BPW_BUILD_ID", "").strip()

    commit = _git("rev-parse", "--short=7", "HEAD")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    committed_at = _git("log", "-1", "--format=%cI")
    # Uncommitted edits mean the commit id alone is a lie about what is running.
    dirty = bool(_git("status", "--porcelain"))

    return dict(
        build_id=commit or env_id or "unknown",
        source="git" if commit else ("env" if env_id else "unknown"),
        branch=branch,
        commit_date=committed_at,
        dirty=dirty,
        started_at=_STARTED_AT,
    )


def build_id() -> str:
    """Short human-comparable string. What goes on screen next to the frontend's."""
    info = build_info()
    return f"{info['build_id']}{'+edits' if info['dirty'] else ''}"
