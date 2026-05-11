"""Railway/Nixpacks deploy entrypoint shim.

Cron services use each service's start command from Railway (see ``railway.toml``).
Builders require a conventional start phase; importing the package verifies deps.
"""

from __future__ import annotations

import watcher  # noqa: F401  # package imports = environment OK for image build


def main() -> None:
    print("release-watcher: idle — configured crons invoke watcher.jobs.* modules")


if __name__ == "__main__":
    main()
