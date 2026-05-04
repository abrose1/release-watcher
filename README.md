# release-watcher

A scheduled agent that monitors new releases across books, music, TV, and movies — texting you via Twilio when something worth knowing about comes out. Driven by a personal taste profile stored in a separate [`taste-profile`](../taste-profile/) repo.

**Part of:** [ReleaseWatcherAgent](../)

> **Build status:** Scaffolding in progress. See [CLOUD_AGENT_HANDOFF.md](./CLOUD_AGENT_HANDOFF.md) for the full implementation spec if picking this up fresh.

---

## How It Works

1. **Daily scan** — Railway Cron checks each tracked creator for new releases via Spotify, TMDB, and Google Books APIs
2. **Daily Tier 1 announcement scan** — Brave Search queries for each Tier 1 creator to catch announcements before they hit APIs
3. **Weekly discovery** — finds new releases matching your taste profile across all four categories
4. **Anthropic judge** — decides if each candidate is worth a notification based on taste fit, not review scores
5. **Web search** — fires on every hit to find the best article/review link for the SMS
6. **Twilio SMS** — sends a short formatted message with the link

---

## Two-Repo Architecture

The taste profile (author/artist scores derived from your bookshelf and Spotify history) lives in a separate repo with its own Postgres. This repo reads creator data from that DB via `TASTE_PROFILE_DATABASE_URL` — a **public** Railway Postgres URL, not the Railway internal hostname.

The `sync_creators.py` script syncs creator data into this repo's local `tracked_creators` table. All scans run against the local copy — no live cross-project DB queries during job execution.

---

## Notification Rules

| Tier | Books / Music | TV | Movies |
|------|--------------|-----|--------|
| Tier 1 (top N by score) | Announce + Release | Announce + new season | Genre-based discovery only |
| Tier 2 (mid-range) | Release only | New season only | Genre-based discovery only |
| Discovery | Release only (taste fit scored by judge) | Similar series via TMDB | TMDB genre filter + judge |

- Music: albums for all tiers; singles only for Tier 1
- Books: novels and novellas only (not collections or non-fiction from fiction authors by default)
- TV: new seasons only, not individual episodes

---

## Setup

### Prerequisites

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env`. The taste-profile repo must be set up and populated first — see [first-run order](#first-run-order).

### First-Run Order

The watcher cannot run meaningfully until the taste profile is populated. Follow this sequence:

1. Set up `taste-profile` repo — run migrations, deploy Railway Postgres, run book and Spotify intake
2. Set tier thresholds in taste-profile's `profile_metadata`
3. Deploy this repo's Railway Postgres and run migrations: `alembic upgrade head`
4. Fill in `config.yaml` — write your `film_taste` description, set `film_tmdb_genre_ids`, add TV shows with tiers, confirm `quiet_hours.timezone`
5. Run `python -m watcher.sync_creators` locally to populate `tracked_creators`
6. Dry-run the daily scan: `python -m watcher.jobs.watchlist --dry-run`
7. Deploy Railway Cron services
8. Trigger one live manual run to confirm Twilio SMS delivery

### Database

```bash
alembic upgrade head
```

### Local Testing

All jobs support `--dry-run` — logs what would be sent without firing Twilio:

```bash
TASTE_PROFILE_DATABASE_URL=... DATABASE_URL=... python -m watcher.jobs.watchlist --dry-run
TASTE_PROFILE_DATABASE_URL=... DATABASE_URL=... python -m watcher.jobs.discovery --dry-run
```

---

## Config

`config.yaml` controls operational settings, TV watchlist, and film taste. **No creator data lives here** — all book/music creators come from the taste profile DB.

```yaml
preferences:
  film_taste: >
    Plain-language description of your film taste for the Anthropic judge.
  film_tmdb_genre_ids: [18, 53, 878]  # Drama, Thriller, Sci-Fi — set at setup
  quiet_hours:
    start: "22:00"
    end: "08:00"
    timezone: "America/Los_Angeles"
    behavior: queue   # queue = hold until 08:00 | drop = discard silently
    max_batch: 3      # max SMS sent at quiet-hours end to avoid flood
  discovery_frequency: weekly
  tier1_announcement_search: true

watchlist:
  tv:
    shows:
      - name: "Show Name"
        tier: 1
        tmdb_id: 12345
```

---

## Deployment (Railway)

Three Cron services + one Postgres in this Railway project:

| Service | Schedule (UTC) | Command |
|---------|---------------|---------|
| daily-scan | `0 14 * * *` (6am PT) | `python -m watcher.jobs.watchlist` |
| weekly-discovery | `0 15 * * 0` (7am PT Sun) | `python -m watcher.jobs.discovery` |
| weekly-sync | `0 13 * * 0` (5am PT Sun) | `python -m watcher.sync_creators` |

The weekly sync runs before discovery so fresh creator data is available.

Stretch: a Railway Web service for the inbound SMS webhook (`watcher/webhook.py`) — only needed if building the SMS reply loop.

---

## Env Vars

See `.env.example` for the full list.

| Var | Description |
|-----|-------------|
| `DATABASE_URL` | This repo's Railway Postgres |
| `TASTE_PROFILE_DATABASE_URL` | **Public** URL of taste-profile Railway Postgres |
| `SPOTIFY_CLIENT_ID` | Same Spotify app as taste-profile |
| `SPOTIFY_CLIENT_SECRET` | Same Spotify app as taste-profile |
| `SPOTIFY_REFRESH_TOKEN` | Same token as taste-profile — used for Spotify rec discovery |
| `TMDB_API_KEY` | Free at themoviedb.org |
| `GOOGLE_BOOKS_API_KEY` | Free at console.cloud.google.com |
| `BRAVE_SEARCH_API_KEY` | Free tier: 2000 queries/month |
| `ANTHROPIC_API_KEY` | Already have |
| `TWILIO_ACCOUNT_SID` | Twilio console |
| `TWILIO_AUTH_TOKEN` | Twilio console |
| `TWILIO_FROM_NUMBER` | Your Twilio phone number |
| `YOUR_PHONE_NUMBER` | Your personal number to receive SMS |

---

## Project Structure

```
release-watcher/
├── watcher/
│   ├── jobs/
│   │   ├── watchlist.py       # Daily scan
│   │   ├── announcement.py    # Daily Tier 1 Brave Search scan
│   │   └── discovery.py       # Weekly discovery
│   ├── sources/
│   │   ├── spotify.py         # Spotify client (client creds + refresh token)
│   │   ├── tmdb.py            # TMDB client
│   │   ├── books.py           # Google Books client
│   │   └── brave.py           # Brave Search client
│   ├── judge.py               # All Anthropic calls
│   ├── notify.py              # Twilio SMS + quiet hours + error SMS
│   ├── sync_creators.py       # Syncs creators from taste profile DB
│   └── webhook.py             # Stretch: inbound SMS handler
├── alembic/                   # Migrations
├── config.yaml                # Operational settings, TV watchlist, film taste
├── .env.example
├── requirements.txt
├── railway.toml
└── CLOUD_AGENT_HANDOFF.md     # Full implementation spec for cloud agent build
```
