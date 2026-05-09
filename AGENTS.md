## Cursor Cloud specific instructions

### Overview
This is a Python backend project (no web framework, no frontend) that runs as Railway Cron jobs. It monitors release feeds and sends SMS notifications via Twilio.

### Running tests
```bash
python3 -m pytest tests/ -v
python3 -m pytest tests/ --cov=watcher --cov-report=term-missing
```
Tests use SQLite in-memory — no env vars, credentials, or external services needed.

### Running the application locally
All jobs support `--dry-run` and use a local SQLite DB by default (via `DATABASE_URL` fallback):
```bash
alembic upgrade head
python3 -m watcher.sync_creators --stub
python3 -m watcher.jobs.watchlist --dry-run
```

### Key caveats
- Use `python3` not `python` (the VM has no `python` symlink).
- The `--stub` flag on `sync_creators` populates dummy data so the rest of the system can run without the taste-profile DB.
- All external APIs (Spotify, TMDB, Google Books, Brave, Anthropic, Twilio) are fully mocked in tests. No network calls occur during `pytest`.
- Alembic defaults to SQLite (`watcher.db`) unless `DATABASE_URL` is set.
