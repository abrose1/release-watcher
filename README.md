# release-watcher

A scheduled agent that monitors new releases across books, music, TV, and movies — texting you via Twilio when something worth knowing about comes out. Driven by a personal taste profile stored in a separate [`taste-profile`](../taste-profile/) repo.

**Part of:** [ReleaseWatcherAgent](../)

> **Build status:** Scaffolding in progress. See [CLOUD_AGENT_HANDOFF.md](./CLOUD_AGENT_HANDOFF.md) for the full implementation spec if picking this up fresh.

---

## How It Works

1. **Daily scan** — Railway Cron checks each tracked creator for new releases via Spotify, TMDB, and Google Books APIs
2. **Daily Tier 1 announcement scan** — Brave Search for each Tier 1 creator (releases / seasons). *Stretch:* concerts or tours for Tier 1 music acts.
3. **Weekly discovery** — finds new releases matching your taste profile across all four categories
4. **Anthropic judge** — decides if each candidate is worth a notification based on taste fit, not review scores
5. **Web search** — fires on every hit to find the best article/review link for the SMS
6. **Twilio SMS** — sends a short formatted message with the link

---

## Two-Repo Architecture

The taste profile (author/artist scores derived from your bookshelf and Spotify history) lives in a separate repo with its own Postgres. This repo reads creator data from that DB via `TASTE_PROFILE_DATABASE_URL` — a **public** Railway Postgres URL, not the Railway internal hostname.

The `sync_creators.py` script syncs creator data into this repo's Postgres `tracked_creators` table (on Railway in production). All scans run against that DB — no live cross-project DB queries during job execution.

### Production default (Railway)

Scheduled jobs and the DB the agent uses are on **Railway**. Treat laptop runs as dev unless you are intentionally targeting production: use **`DATABASE_PUBLIC_URL`** + `scripts/sync_creators_remote.py` for creator sync from your machine, deploy code after watcher changes, and keep **`TASTE_PROFILE_DATABASE_URL`** pointed at the **public** taste-profile Postgres URL. See `.cursor/rules/railway-production-default.mdc`.

---

## Notification Rules

| Tier | Books / Music | TV | Movies |
|------|--------------|-----|--------|
| Tier 1 (top N by score) | Announce + Release | Announce + new season | Genre-based discovery only |
| Tier 2 (mid-range) | Release only (music: albums + singles on Spotify; no announce scan) | New season only | Genre-based discovery only |
| Tier 3 / tail | Books: release notifications. **Music:** not polled on the daily Spotify watchlist until discovery-style flows exist (tiers still synced from taste-profile). | Similar series via TMDB | TMDB genre filter + judge |

- Music: Tier **1** and **2** — Spotify **albums + singles** on the daily scan; Tier **1** also gets the Brave **announcement** scan. Tier **3** music — **no** proactive album/single SMS from the daily scan (stretch: discovery picks worth notifying later).
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
4. Copy [`config.override.example.yaml`](./config.override.example.yaml) to **`config.override.yaml`** and fill film taste / playlists / `sms_first_name` / TZ — **or** set the optional env vars documented under [Config](#config). Repo `config.yaml` stays generic.
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

Tracked **`config.yaml`** is intentionally **generic** so the repo stays safe to fork. Customize via:

1. **`config.override.yaml`** (copy from [`config.override.example.yaml`](./config.override.example.yaml)) — merged on top at runtime and **listed in `.gitignore`**. Prefer this on your laptop where you edit YAML normally.
2. **Environment variables** (handy when Railway deploy builds from Git and you prefer not committing override YAML):

   | Variable | Effect |
   |----------|--------|
   | `SMS_GREETING_NAME` or `SMS_FIRST_NAME` | Sets `preferences.sms_first_name` for SMS greetings. |
   | `SPOTIFY_SEED_PLAYLIST_IDS` | Comma-separated Spotify **user-owned mirror** playlist IDs. |
   | `FILM_TASTE` | Full film-taste prose for the judge (multiline OK in Railway / `.env`). |
   | `FILM_TMDB_GENRE_IDS` | e.g. `18,53,878` → Drama, Thriller, Sci-Fi-style discovery seeding. |
   | `SMS_QUIET_TIMEZONE` | IANA TZ for `preferences.quiet_hours.timezone`. |

**Deploying locally with `railway up`:** the CLI **respects `.gitignore`** by default, so **`config.override.yaml` is not uploaded**. Use **`railway up --no-gitignore`** if you bundle an override file locally; or rely on Railway env vars above.

**Synced taste data** (scores, tiers, tracked creators) still lives in Postgres (`taste-profile` DB + `tracked_creators`), not here.

Minimal shape (see repo `config.yaml` for defaults):

```yaml
preferences:
  film_taste: >
    Plain-language description of film taste for the Anthropic judge.
  film_tmdb_genre_ids: [18, 53, 878]

  quiet_hours:
    start: "22:00"
    end: "08:00"
    timezone: "America/Los_Angeles"

watchlist:
  tv:
    shows:
      - name: "Example show"
        tier: 1
        tmdb_id: 12345
```

---

## Deployment (Railway)

**Build / deploy:** Railway’s builder (Railpack/Nixpacks) needs a conventional Python start phase. Repo root **`main.py`** runs `python main.py` during image build/deploy only (smoke-imports `watcher`). **Scheduled runs** still use each service’s Cron **start command** — keep those as `python -m watcher....` below (and in the Dashboard if `railway.toml` doesn’t populate them).

| Service | Schedule (UTC) | Command |
|---------|---------------|---------|
| daily-scan | `0 14 * * *` (6am PT) | `python -m watcher.jobs.watchlist` |
| announcement-scan | `0 14 * * *` | `python -m watcher.jobs.announcement` |
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
| `SPOTIFY_CLIENT_ID` | Same Spotify app as taste-profile (Client Credentials only — no refresh token needed here) |
| `SPOTIFY_CLIENT_SECRET` | Same Spotify app as taste-profile |
| `TMDB_API_KEY` | Free at themoviedb.org |
| `GOOGLE_BOOKS_API_KEY` | Free at console.cloud.google.com |
| `BRAVE_SEARCH_API_KEY` | Free tier: 2000 queries/month |
| `ANTHROPIC_API_KEY` | Already have |
| `TWILIO_ACCOUNT_SID` | Twilio console |
| `TWILIO_AUTH_TOKEN` | Twilio console |
| `TWILIO_MESSAGING_SERVICE_SID` | Preferred for A2P 10DLC; when set, SMS sends via Messaging Service instead of raw `from_` |
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
│   │   ├── spotify.py         # Spotify client (Client Credentials)
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
