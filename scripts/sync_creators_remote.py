#!/usr/bin/env python3
"""Run ``watcher.sync_creators`` against Railway Postgres from your laptop.

``DATABASE_URL`` in Railway cron uses ``postgres.railway.internal``, which does not
resolve off-platform. Set ``DATABASE_PUBLIC_URL`` to the **public** Postgres URL
(Railway dashboard → Postgres → Connect → public URL).

Usage::

  python3 scripts/sync_creators_remote.py

Loads ``release-watcher/.env`` (same dir parent as ``scripts/``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    try:
        from dotenv import load_dotenv
    except ImportError:
        print("ERROR: pip install python-dotenv", file=sys.stderr)
        sys.exit(1)

    load_dotenv(root / ".env")

    public = (os.environ.get("DATABASE_PUBLIC_URL") or "").strip()
    current = (os.environ.get("DATABASE_URL") or "").strip()

    if public:
        os.environ["DATABASE_URL"] = public
    elif "railway.internal" in current:
        print(
            "ERROR: DATABASE_URL points at postgres.railway.internal (only reachable inside Railway).\n"
            "Add DATABASE_PUBLIC_URL=postgresql://… to release-watcher/.env\n"
            "using the public Postgres URL from your Railway watcher project, then re-run.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not os.environ.get("DATABASE_URL", "").strip():
        print("ERROR: DATABASE_URL / DATABASE_PUBLIC_URL not set.", file=sys.stderr)
        sys.exit(1)

    if not os.environ.get("TASTE_PROFILE_DATABASE_URL", "").strip():
        print("ERROR: TASTE_PROFILE_DATABASE_URL not set.", file=sys.stderr)
        sys.exit(1)

    r = subprocess.run(
        [sys.executable, "-m", "watcher.sync_creators"],
        cwd=str(root),
        env=os.environ.copy(),
    )
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
