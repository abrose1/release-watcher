# Cloud Agent Handoff — release-watcher

This document is the full implementation spec for building the `release-watcher` repo. It is written for a Cursor cloud agent picking up this repo to implement from scratch.

**Context:** This is one half of a two-repo personal project. The other repo (`taste-profile`) is being built in parallel and is not yet complete. Build this repo fully, but stub out all taste profile DB reads with clear TODOs and mock data so the watcher is runnable end-to-end once the taste profile is wired in.

**Testing expectation:** Write tests as you implement each module — do not leave testing until the end. Use pytest. All external API calls (Spotify, TMDB, Google Books, Brave Search, Anthropic, Twilio) must be mocked in tests; no real credentials are required for the test suite to pass. Use dummy taste profile data (defined in a shared `tests/fixtures.py`) wherever creator data is needed.

---

## What to Build

A Python application (no web framework needed — just runnable scripts) that:

1. Reads tracked creators from a local Postgres table (synced from taste-profile)
2. Checks Spotify, TMDB, and Google Books APIs for new releases from those creators
3. Runs daily Brave Search queries for Tier 1 creators to catch announcements before APIs know
4. Runs a weekly discovery job to find releases matching the user's taste profile
5. Uses Anthropic Claude to decide whether each candidate is worth a notification
6. Fires a Brave Search on every hit to find the best article link
7. Sends an SMS via Twilio with the formatted notification
8. Handles quiet hours by queuing notifications and flushing at 08:00 local time
9. Sends an error SMS if any job crashes

---

## Stack

- **Python 3.11+**
- **SQLAlchemy 2.x** + **Alembic** for DB and migrations
- **psycopg2-binary** for Postgres
- **httpx** for all API calls (consistent with taste-profile repo)
- **anthropic** Python SDK
- **twilio** Python SDK
- **pyyaml** for config.yaml parsing
- **python-dotenv** for local .env loading
- **pytz** for timezone handling in quiet hours logic

---

## Directory Structure to Create

```
release-watcher/
├── watcher/
│   ├── __init__.py
│   ├── config.py              # Loads config.yaml and env vars
│   ├── db.py                  # SQLAlchemy engine + session factory
│   ├── models.py              # All SQLAlchemy models
│   ├── judge.py               # All Anthropic calls
│   ├── notify.py              # Twilio SMS + quiet hours + error SMS
│   ├── sync_creators.py       # Syncs creators from taste-profile DB
│   ├── jobs/
│   │   ├── __init__.py
│   │   ├── watchlist.py       # Daily scan
│   │   ├── announcement.py    # Daily Tier 1 Brave Search scan
│   │   └── discovery.py       # Weekly discovery
│   └── sources/
│       ├── __init__.py
│       ├── spotify.py         # Spotify API client
│       ├── tmdb.py            # TMDB API client
│       ├── books.py           # Google Books API client
│       └── brave.py           # Brave Search API client
├── alembic/
│   ├── env.py
│   └── versions/              # Migration files
├── config.yaml                # Operational settings (see schema below)
├── .env.example               # All required env vars documented
├── requirements.txt
├── alembic.ini
└── railway.toml               # Cron service definitions
```

---

## Database Schema

All tables live in the watcher's own Postgres instance (`DATABASE_URL`). This is separate from the taste-profile DB.

### `tracked_creators`

```sql
id                    SERIAL PRIMARY KEY
category              VARCHAR NOT NULL  -- 'book', 'music', 'tv'
name                  VARCHAR NOT NULL
tier                  INTEGER NOT NULL  -- 1 or 2
external_id           VARCHAR          -- spotify_id, google_books_id, or tmdb_id
last_synced_from_profile  TIMESTAMP
profile_score_at_sync FLOAT            -- score at last sync, used to detect tier drift
```

### `releases`

```sql
id                    SERIAL PRIMARY KEY
tracked_creator_id    INTEGER REFERENCES tracked_creators(id)
external_release_id   VARCHAR NOT NULL
title                 VARCHAR NOT NULL
type                  VARCHAR          -- 'album', 'single', 'novel', 'season', 'movie', 'announcement'
announced_date        DATE
release_date          DATE
notified_announced_at TIMESTAMP
notified_released_at  TIMESTAMP
source_url            VARCHAR
announcement_hash     VARCHAR          -- MD5 of headline+URL for Tier 1 announcement dedup
```

### `notification_queue`

```sql
id                    SERIAL PRIMARY KEY
release_id            INTEGER REFERENCES releases(id) NULL      -- set for watchlist hits
discovery_sent_id     INTEGER REFERENCES discovery_sent(id) NULL -- set for discovery recs
message_text          TEXT NOT NULL    -- pre-formatted SMS text
queued_at             TIMESTAMP NOT NULL DEFAULT now()
send_after            TIMESTAMP NOT NULL  -- set to quiet hours end when queued during quiet hours
priority              INTEGER NOT NULL DEFAULT 50  -- lower = higher priority; tier 1 = 10, tier 2 = 30, discovery = 50
sent_at               TIMESTAMP
```

Exactly one of `release_id` or `discovery_sent_id` should be non-null per row.

### `discovery_sent`

```sql
id                    SERIAL PRIMARY KEY
external_id           VARCHAR NOT NULL  -- external API ID of the discovered release
category              VARCHAR NOT NULL
title                 VARCHAR NOT NULL
creator_name          VARCHAR NOT NULL
sent_at               TIMESTAMP NOT NULL DEFAULT now()
```

### `user_overrides`

```sql
id                    SERIAL PRIMARY KEY
tracked_creator_id    INTEGER REFERENCES tracked_creators(id)
action                VARCHAR NOT NULL  -- 'mute', 'deprioritize'
expires_at            TIMESTAMP        -- null = permanent
```

### `tier_changes`

```sql
id                    SERIAL PRIMARY KEY
tracked_creator_id    INTEGER REFERENCES tracked_creators(id)
old_tier              INTEGER
new_tier              INTEGER
changed_at            TIMESTAMP NOT NULL DEFAULT now()
```

---

## Config YAML Schema

`config.yaml` at the repo root. Parse this in `watcher/config.py` using PyYAML.

```yaml
preferences:
  film_taste: >
    # Plain-language description of film taste — used by judge for qualitative matching
    # Example: "I like slow-burn thrillers, literary drama, and thoughtful sci-fi."
  film_tmdb_genre_ids: [18, 53, 878]  # Drama, Thriller, Sci-Fi
  quiet_hours:
    start: "22:00"
    end: "08:00"
    timezone: "America/Los_Angeles"
    behavior: queue   # "queue" or "drop"
    max_batch: 3
  discovery_frequency: weekly
  tier1_announcement_search: true

watchlist:
  tv:
    shows: []
    # Each show:
    # - name: "Show Name"
    #   tier: 1
    #   tmdb_id: 12345
```

---

## Env Vars

Document all of these in `.env.example`:

```
DATABASE_URL                  # This repo's Postgres
TASTE_PROFILE_DATABASE_URL    # Public URL of taste-profile Postgres (separate Railway project)
SPOTIFY_CLIENT_ID
SPOTIFY_CLIENT_SECRET
TMDB_API_KEY
GOOGLE_BOOKS_API_KEY
BRAVE_SEARCH_API_KEY
ANTHROPIC_API_KEY
TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN
TWILIO_FROM_NUMBER
YOUR_PHONE_NUMBER
```

---

## Taste Profile DB Stub

**The taste-profile repo is not yet complete.** The `sync_creators.py` script reads from `TASTE_PROFILE_DATABASE_URL`. Until that DB is populated, stub it:

In `watcher/sync_creators.py`, add a `--stub` flag that populates `tracked_creators` with clearly labeled placeholder data:

```python
STUB_CREATORS = [
    {"category": "music", "name": "STUB_ARTIST_1", "tier": 1, "external_id": None},
    {"category": "music", "name": "STUB_ARTIST_2", "tier": 2, "external_id": None},
    {"category": "book", "name": "STUB_AUTHOR_1", "tier": 1, "external_id": None},
    {"category": "book", "name": "STUB_AUTHOR_2", "tier": 2, "external_id": None},
]
```

Mark all stub records with a `profile_score_at_sync` of -1.0 so they're easy to identify and replace. Add a `# TODO: wire to taste-profile DB` comment at the top of the real sync logic.

---

## API Clients (`watcher/sources/`)

Build each as a simple class with an `httpx.AsyncClient`. All clients should:

- Raise a typed exception on non-200 responses
- Respect rate limits (add basic retry with exponential backoff, max 3 retries)
- Return typed dataclasses or dicts, not raw JSON

### `spotify.py`

Single auth mode: **Client credentials** (machine-to-machine). No user OAuth or refresh token required by this service — those live in the `taste-profile` repo and are only used there.

Music discovery seeds come from public, **user-owned** playlists configured in `config.yaml` under `spotify_seed_playlist_ids`. Spotify's auto-generated `37i9dQZF*` Wrapped/editorial playlists became inaccessible to new third-party Web API apps in Nov 2024, and Spotify's `/recommendations`, audio-features, audio-analysis, and related-artists endpoints were deprecated at the same time. Discovery instead pulls artist names from those playlists and pipes them through Brave Search + the LLM judge.

Key methods:

- `get_artist_albums(spotify_id, after_date)` → list of albums since date
- `get_artist_new_singles(spotify_id, after_date)` → list of singles since date (daily watchlist uses this for Tier **1** and **2** music only)
- `get_playlist_tracks(playlist_id)` → list of `PlaylistTrack` from `/playlists/{id}/items` (note: the legacy `/tracks` path returns 403 and the response wraps each entry in `item`, not `track`)

### `tmdb.py`

Key methods:

- `get_tv_season_updates(tmdb_id, after_date)` → new seasons announced or released since date
- `get_upcoming_movies(genre_ids, after_date)` → upcoming movies matching genre IDs
- `get_similar_series(tmdb_id, limit=10)` → similar TV shows
- `get_similar_movies(tmdb_id, limit=10)` → similar movies

### `books.py`

Key methods:

- `get_author_new_books(google_books_author_id, after_date)` → new books since date, filtered to novels/novellas
- `search_books_by_author_name(name, after_date)` → fallback when no author ID is set

### `brave.py`

Key methods:

- `search(query, num_results=5)` → list of `{title, url, snippet}` dicts
- Pre-built query helpers:
  - `search_release(creator, title)` → find best article for a known release
  - `search_announcement(creator, category, year)` → find announcement news
  - `search_similar_books(author_name)` → "books similar to [author]" style

---

## The Anthropic Judge (`watcher/judge.py`)

Three distinct judge calls. Each returns a typed result. Use `claude-3-5-haiku-20241022` for cost efficiency (this runs daily).

### 1. `judge_watchlist_hit(creator, release_metadata, search_results)`

Determines if a detected release is genuine and worth notifying about.

Prompt context includes:

- Creator name, tier, category
- Release metadata from API (title, type, date)
- Top 3 Brave Search results for context

Returns: `JudgeResult(notify: bool, reason: str, best_link: str)`

Key things to detect and reject:

- Remasters, compilations, re-editions, deluxe editions
- Rumors vs. confirmed announcements
- Re-releases of existing work under a new title

### 2. `judge_discovery_candidate(candidate, taste_profile_slice, search_results)`

Determines if a discovery candidate fits the user's taste profile.

Prompt context includes:

- Candidate metadata (title, creator, category, description)
- Top 5 scored creators from taste profile (for taste reference)
- Film taste description from `config.yaml` (for film candidates)
- Top 3 Brave Search results for stylistic context

Returns: `JudgeResult(notify: bool, reason: str, best_link: str)`

**Critical prompt instruction:** "Primary signal is style and genre similarity to the user's top-scored creators. Do NOT cite review scores or ratings as a reason to notify. If the release is worth surfacing, explain specifically what it has in common with what the user already loves."

### 3. `judge_sms_reply(reply_text, recent_notifications)` *(stretch)*

Parses an inbound SMS reply into a structured command.

Returns: `SMSCommand(action: str, creator_name: str | None, duration_days: int | None)`

Supported actions: `mute`, `less`, `more`, `stop`, `add`, `unknown`

---

## Daily Watchlist Job (`watcher/jobs/watchlist.py`)

Entry point: `python -m watcher.jobs.watchlist [--dry-run]`

```
1. Flush notification_queue (send any queued messages past their send_after time)
2. Load tracked_creators from local DB (exclude muted via user_overrides)
3. For each creator:
   a. Check relevant API for releases since last known release date
   b. If hit found:
      - Check releases table for deduplication (by external_release_id)
      - Fire Brave Search for best article link
      - Call judge_watchlist_hit()
      - If notify=True: format SMS, check quiet hours, send or queue
      - Insert into releases table with notified timestamps
4. Log summary: N creators checked, M notifications sent, K queued
```

Quiet hours check in step 3: if current local time is within `quiet_hours`, write to `notification_queue` with `send_after` = next occurrence of `quiet_hours.end`. Otherwise send immediately via Twilio.

### `--dry-run` flag

Skip all Twilio sends and queue writes. Print what would be sent to stdout instead. Still reads from DB and calls APIs (so you see real results), but produces no side effects.

---

## Daily Announcement Job (`watcher/jobs/announcement.py`)

Entry point: `python -m watcher.jobs.announcement [--dry-run]`

Only runs if `tier1_announcement_search: true` in config.yaml.

```
1. Load Tier 1 tracked_creators from local DB
2. For each Tier 1 creator:
   a. Run Brave Search: "[creator name] new [album/book/season] 2026"
   b. For each result:
      - Compute announcement_hash = MD5(headline + url)
      - Check releases table for existing row with this hash
      - If new: call judge_watchlist_hit() with search results as context
      - If notify=True: insert into releases (type='announcement'), format SMS, send or queue
```

---

## Weekly Discovery Job (`watcher/jobs/discovery.py`)

Entry point: `python -m watcher.jobs.discovery [--dry-run]`

Runs four discovery pipelines in sequence:

### Music Discovery

1. Read `spotify_seed_playlist_ids` from `config.yaml`
2. For each playlist, call `spotify.get_playlist_tracks(playlist_id)` and collect unique artist names not already in `tracked_creators`
3. Sample up to 5 artists spread across the combined pool
4. For each seed artist: call `brave.search_similar_music(artist)` then `judge_discovery_candidate()`
5. Send the first result that passes the judge (capped at 1 per run)

### Film Discovery

1. Use `film_tmdb_genre_ids` from config.yaml
2. Call `tmdb.get_upcoming_movies(genre_ids, after_date=30_days_ago)`
3. Filter out entries already in `discovery_sent`
4. For each candidate: call `judge_discovery_candidate()` with `film_taste` context
5. Send top 1 result that passes

### TV Discovery

1. Get all tracked TV shows from `tracked_creators`
2. Call `tmdb.get_similar_series(tmdb_id)` for each Tier 1 show
3. Filter to series with a season released in the past 90 days
4. Filter out entries already in `discovery_sent`
5. Call `judge_discovery_candidate()` for each candidate
6. Send top 1 result that passes

### Books Discovery

1. Get top 3 book authors by score from `tracked_creators`
2. Run Brave Search: `"books similar to [author name] 2025 2026"` for each
3. Judge extracts specific book titles from search snippets and scores them
4. Filter out entries already in `discovery_sent`
5. Send top 1 result that passes

---

## Notify (`watcher/notify.py`)

### SMS Formatting

```python
def format_watchlist_sms(creator_name, category, title, release_type, link) -> str:
    """Format a watchlist hit SMS. Keeps under 160 chars where possible.
    If over 160 chars, truncate title first. Link is never dropped."""
    type_label = {
        "album": "New Album",
        "single": "New Single",
        "novel": "New Book",
        "season": "New Season",
        "announcement": "Announced",
    }.get(release_type, "New Release")
    
    msg = f"{type_label} · {creator_name}\n\"{title}\"\n{link}"
    if len(msg) > 160:
        # Truncate title to fit
        ...
    return msg

def format_discovery_sms(category, title, creator_name, reason, link) -> str:
    """Format a discovery rec SMS. Drops reason line if over 160 chars."""
    msg = f"Rec · {category.title()}\n\"{title}\" by {creator_name}\n{reason}\n{link}"
    if len(msg) > 160:
        msg = f"Rec · {category.title()}\n\"{title}\" by {creator_name}\n{link}"
    return msg[:160]  # hard cap as last resort
```

### Sending

```python
def send_sms(message_text: str, dry_run: bool = False):
    """Send via Twilio. Noop if dry_run=True."""
    
def send_error_sms(job_name: str):
    """Send a brief error notification. Format: '[Watcher] {job_name} failed — check Railway logs'"""
    
def flush_queue(dry_run: bool = False):
    """Send all notification_queue rows where send_after <= now(), ordered by priority ASC.
    Respects max_batch from config — drops lowest priority items if over limit."""
```

### Quiet Hours

```python
def is_quiet_hours() -> bool:
    """Check if current local time (per config timezone) falls within quiet window."""
    
def next_send_after() -> datetime:
    """Return the next occurrence of quiet_hours.end as a UTC datetime."""
```

---

## Creator Sync (`watcher/sync_creators.py`)

Entry point: `python -m watcher.sync_creators [--stub]`

```
1. Connect to TASTE_PROFILE_DATABASE_URL
2. SELECT * FROM book_authors ORDER BY rank_score DESC
3. SELECT * FROM music_artists ORDER BY listen_score DESC
4. Apply tier thresholds from taste-profile's profile_metadata table
5. Upsert into local tracked_creators table
6. For each updated creator, compare new tier to profile_score_at_sync:
   - If tier decreased (1→2): log to tier_changes, downgrade pending queue items
   - If tier increased (2→1): log to tier_changes
7. Load TV shows from config.yaml and upsert those too
```

`**--stub` flag:** Skip TASTE_PROFILE_DATABASE_URL connection entirely. Insert STUB_CREATORS (defined at top of file) with `profile_score_at_sync = -1.0`. Print a clear warning: "⚠ Running with stub data — taste-profile DB not connected."

---

## Error Handling

Wrap the main execution block of each job in a try/except:

```python
if __name__ == "__main__":
    try:
        run(dry_run=args.dry_run)
    except Exception as e:
        logging.exception(f"Job failed: {e}")
        if not args.dry_run:
            send_error_sms("daily-scan")  # or "weekly-discovery" etc.
        sys.exit(1)
```

---

## `railway.toml`

```toml
[build]
builder = "nixpacks"

[[services]]
name = "daily-scan"
type = "cron"
schedule = "0 14 * * *"
startCommand = "python -m watcher.jobs.watchlist"

[[services]]
name = "announcement-scan"
type = "cron"
schedule = "0 14 * * *"
startCommand = "python -m watcher.jobs.announcement"

[[services]]
name = "weekly-discovery"
type = "cron"
schedule = "0 15 * * 0"
startCommand = "python -m watcher.jobs.discovery"

[[services]]
name = "weekly-sync"
type = "cron"
schedule = "0 13 * * 0"
startCommand = "python -m watcher.sync_creators"
```

---

## Testing Requirements

Write tests as you go — module by module, not at the end. The test suite must pass without any real credentials or external network calls.

### Test Structure

```
tests/
├── fixtures.py            # Shared dummy data — taste profile slice, mock API responses
├── test_models.py         # Schema correctness, FK constraints
├── test_sources/
│   ├── test_spotify.py    # Mocked Spotify API responses
│   ├── test_tmdb.py
│   ├── test_books.py
│   └── test_brave.py
├── test_judge.py          # Mocked Anthropic responses — test all three judge call types
├── test_notify.py         # SMS formatting, quiet hours logic, truncation, flush_queue
├── test_sync_creators.py  # Tier threshold application, tier drift detection
└── test_jobs/
    ├── test_watchlist.py  # Full job flow with mocked sources + judge
    ├── test_announcement.py
    └── test_discovery.py
```

### Shared Fixtures (`tests/fixtures.py`)

Define dummy taste profile data used across all tests. This represents what the real taste profile DB would provide once wired in:

```python
DUMMY_CREATORS = [
    {"id": 1, "category": "music", "name": "Test Artist A", "tier": 1,
     "external_id": "spotify_id_aaa", "profile_score_at_sync": 95.0},
    {"id": 2, "category": "music", "name": "Test Artist B", "tier": 2,
     "external_id": "spotify_id_bbb", "profile_score_at_sync": 60.0},
    {"id": 3, "category": "book", "name": "Test Author A", "tier": 1,
     "external_id": "gbooksid_aaa", "profile_score_at_sync": 88.0},
    {"id": 4, "category": "book", "name": "Test Author B", "tier": 2,
     "external_id": "gbooksid_bbb", "profile_score_at_sync": 45.0},
]

DUMMY_TASTE_PROFILE_SLICE = {
    "top_music_artists": ["Test Artist A", "Test Artist B"],
    "top_book_authors": ["Test Author A"],
    "film_taste": "I like slow-burn thrillers and literary drama.",
}

MOCK_SPOTIFY_ALBUM = {
    "id": "album_123", "name": "Test Album", "release_date": "2026-04-01",
    "album_type": "album", "artists": [{"name": "Test Artist A"}],
    "external_urls": {"spotify": "https://open.spotify.com/album/album_123"},
}

MOCK_JUDGE_NOTIFY = {"notify": True, "reason": "Test reason", "best_link": "https://example.com"}
MOCK_JUDGE_SKIP = {"notify": False, "reason": "Not a genuine release", "best_link": ""}
```

### What to Test per Module

**API clients:** Mock `httpx` responses. Test happy path, 429 rate-limit retry, and non-200 error raising.

**Judge:** Mock the `anthropic` SDK. Test each call type returns the right structure. Test that the discovery judge prompt does NOT include any instruction referencing review scores as a positive signal (assert the phrase "review score" or "star rating" does not appear in a `notify=True` reason).

**Notify:** No mocking needed for formatting tests. Test SMS truncation logic explicitly — construct a message >160 chars and assert the link is preserved and the reason line is dropped first.

**Quiet hours:** Use `freezegun` or mock `datetime.now()` to test in-window vs. out-of-window behavior. Test queue write during quiet hours and flush at end of window.

**Jobs (integration-style):** Use a real SQLite DB (`:memory:`) or test Postgres. Mock all API clients and the judge. Assert the correct rows are written to `releases`, `notification_queue`, and `discovery_sent` tables. Test `--dry-run` produces no DB writes and no Twilio calls.

**Sync creators:** Test that tier thresholds are applied correctly. Test tier drift detection — provide a creator whose score has crossed a threshold and assert a `tier_changes` row is written.

### Running Tests

```bash
pytest tests/ -v
pytest tests/ --cov=watcher --cov-report=term-missing
```

No env vars required to run the test suite. Tests that need a DB use SQLite in-memory or a fixture that creates/tears down tables.

---

## What to Leave as TODOs

The taste-profile repo is being built in parallel. Leave these as explicit TODO comments rather than implementing them:

- In `judge.py` discovery calls: `# TODO: pass actual taste profile slice from tracked_creators scores`
- Any place that reads `profile_score_at_sync` for comparison: add a comment that real values come post-sync

**Implemented:** `sync_creators.sync_from_taste_profile` reads `book_authors`, `music_artists`, and `profile_metadata` via `TASTE_PROFILE_DATABASE_URL` (music tiers use `tier*_music_cutoff`; Spotify polling skips Tier 3 music on the daily watchlist until discovery).

Everything else should be fully implemented and runnable with stub data.

---

## Definition of Done

The agent's work is complete when:

- All files in the directory structure exist
- `alembic upgrade head` runs successfully against a local Postgres
- `python -m watcher.sync_creators --stub` populates `tracked_creators` with stub records
- `python -m watcher.jobs.watchlist --dry-run` runs without error and prints what it would send
- `python -m watcher.jobs.discovery --dry-run` runs without error
- `pytest tests/ -v` passes with no real credentials or network calls
- Test coverage is >80% on `watcher/judge.py`, `watcher/notify.py`, and `watcher/sync_creators.py`
- All API clients have clear docstrings and typed return values
- `.env.example` documents every required env var
- `requirements.txt` is complete and pinned
- TODO comments are in place wherever taste-profile DB data is needed

