"""Daily watchlist scan job.

Checks each tracked creator for new releases via Spotify, TMDB, and Google Books APIs.
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime, date, timedelta, timezone

from watcher.db import get_session_factory
from watcher.models import TrackedCreator, Release, NotificationQueue, UserOverride
from watcher.notify import (
    format_watchlist_message, send_sms_to_subscribers,
    flush_queue, is_quiet_hours, next_send_after,
)
from watcher.sources.spotify import SpotifyClient
from watcher.sources.tmdb import TMDBClient
from watcher.sources.books import BooksClient
from watcher.sources.brave import BraveSearchClient
from watcher.judge import judge_watchlist_hit

logger = logging.getLogger(__name__)


async def check_music_creator(creator: TrackedCreator, spotify: SpotifyClient, after_date: date):
    """Check for new releases from a music creator.

    Tier 1 and Tier 2 both poll albums and singles. Tier 3 is skipped in the
    daily scan until discovery-style flows exist (see ``run_scan``).
    """
    if not creator.external_id:
        return []

    releases = await spotify.get_artist_albums(creator.external_id, after_date)
    if creator.tier in (1, 2):
        singles = await spotify.get_artist_new_singles(creator.external_id, after_date)
        releases.extend(singles)

    return [
        {
            "external_release_id": r.id,
            "title": r.name,
            "type": r.album_type,
            "date": r.release_date,
            "spotify_url": r.spotify_url,
            "image_url": r.image_url,
        }
        for r in releases
    ]


async def check_tv_creator(creator: TrackedCreator, tmdb: TMDBClient, after_date: date):
    """Check for new seasons from a TV show."""
    if not creator.external_id:
        return []

    tmdb_id = int(creator.external_id)
    seasons = await tmdb.get_tv_season_updates(tmdb_id, after_date)

    return [
        {
            "external_release_id": f"tv_{tmdb_id}_s{s.season_number}",
            "title": f"{creator.name} {s.name}",
            "type": "season",
            "date": s.air_date,
        }
        for s in seasons
    ]


async def check_book_creator(creator: TrackedCreator, books: BooksClient, after_date: date):
    """Check for new books from an author."""
    logger.info("Checking books for author: %s (id=%s)", creator.name, creator.external_id)
    if creator.external_id:
        found_books = await books.get_author_new_books(creator.external_id, after_date)
    else:
        found_books = await books.search_books_by_author_name(creator.name, after_date)

    return [
        {
            "external_release_id": b.id,
            "title": b.title,
            "type": "novel",
            "date": b.published_date,
        }
        for b in found_books
    ]


async def run_scan(dry_run: bool = False):
    """Run the daily watchlist scan."""
    session_factory = get_session_factory()
    session = session_factory()

    spotify = SpotifyClient()
    tmdb = TMDBClient()
    books = BooksClient()
    brave = BraveSearchClient()

    try:
        flush_queue(dry_run=dry_run)

        muted_ids = {
            o.tracked_creator_id
            for o in session.query(UserOverride)
            .filter(UserOverride.action == "mute")
            .filter(
                (UserOverride.expires_at.is_(None)) |
                (UserOverride.expires_at > datetime.now(timezone.utc).replace(tzinfo=None))
            )
            .all()
        }

        creators = session.query(TrackedCreator).all()
        creators = [c for c in creators if c.id not in muted_ids]

        after_date = date.today() - timedelta(days=7)
        notifications_sent = 0
        notifications_queued = 0

        for creator in creators:
            try:
                if creator.category == "music":
                    # Tier 3: taste-profile tail — no proactive album/single SMS until discovery is wired.
                    if creator.tier >= 3:
                        continue
                    releases = await check_music_creator(creator, spotify, after_date)
                elif creator.category == "tv":
                    releases = await check_tv_creator(creator, tmdb, after_date)
                elif creator.category == "book":
                    releases = await check_book_creator(creator, books, after_date)
                else:
                    continue
            except Exception:
                logger.exception(
                    "Failed to check creator %r (category=%s, id=%s) — skipping",
                    creator.name, creator.category, creator.external_id,
                )
                continue

            for release_data in releases:
                existing = (
                    session.query(Release)
                    .filter_by(external_release_id=release_data["external_release_id"])
                    .first()
                )
                if existing:
                    continue

                search_results = await brave.search_release(creator.name, release_data["title"])
                search_dicts = [
                    {"title": r.title, "url": r.url, "snippet": r.snippet}
                    for r in search_results
                ]

                judge_result = judge_watchlist_hit(
                    creator={"name": creator.name, "tier": creator.tier, "category": creator.category},
                    release_metadata=release_data,
                    search_results=search_dicts,
                )

                if judge_result.notify:
                    if creator.category == "music":
                        link = release_data.get("spotify_url") or judge_result.best_link or (search_dicts[0]["url"] if search_dicts else "")
                    else:
                        link = judge_result.best_link or (search_dicts[0]["url"] if search_dicts else "")
                    message_text = format_watchlist_message(
                        creator_name=creator.name,
                        category=creator.category,
                        title=release_data["title"],
                        release_type=release_data["type"],
                        link=link,
                    )

                    release = Release(
                        tracked_creator_id=creator.id,
                        external_release_id=release_data["external_release_id"],
                        title=release_data["title"],
                        type=release_data["type"],
                        release_date=date.fromisoformat(release_data["date"]) if release_data.get("date") else None,
                        notified_released_at=datetime.now(timezone.utc).replace(tzinfo=None),
                        source_url=link,
                    )

                    if not dry_run:
                        session.add(release)
                        session.flush()

                        if is_quiet_hours():
                            queue_item = NotificationQueue(
                                release_id=release.id,
                                message_text=message_text,
                                queued_at=datetime.now(timezone.utc).replace(tzinfo=None),
                                send_after=next_send_after(),
                                priority=10 if creator.tier == 1 else 30,
                            )
                            session.add(queue_item)
                            notifications_queued += 1
                        else:
                            send_sms_to_subscribers(message_text, dry_run=dry_run)
                            notifications_sent += 1
                    else:
                        logger.info(f"[DRY RUN] Would notify: {message_text}")
                        notifications_sent += 1

        if not dry_run:
            session.commit()

        logger.info(
            f"Scan complete: {len(creators)} creators checked, "
            f"{notifications_sent} notifications sent, "
            f"{notifications_queued} queued"
        )
    finally:
        session.close()


def run(dry_run: bool = False):
    asyncio.run(run_scan(dry_run=dry_run))


def main():
    parser = argparse.ArgumentParser(description="Daily watchlist scan")
    parser.add_argument("--dry-run", action="store_true", help="Log what would be sent without firing Twilio")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    try:
        run(dry_run=args.dry_run)
    except Exception as e:
        logging.exception(f"Job failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
