"""Weekly discovery job.

Finds new releases matching the user's taste profile across music, film, TV, and books.
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime, date, timedelta

from watcher.config import get_film_taste, get_film_genre_ids
from watcher.db import get_session_factory
from watcher.models import TrackedCreator, DiscoverySent, NotificationQueue
from watcher.notify import (
    format_discovery_sms, send_sms, send_error_sms,
    is_quiet_hours, next_send_after,
)
from watcher.sources.spotify import SpotifyClient
from watcher.sources.tmdb import TMDBClient
from watcher.sources.brave import BraveSearchClient
from watcher.judge import judge_discovery_candidate

logger = logging.getLogger(__name__)


def _already_sent(session, external_id: str) -> bool:
    """Check if we already sent a discovery notification for this item."""
    return session.query(DiscoverySent).filter_by(external_id=external_id).first() is not None


def _send_or_queue_discovery(session, sms_text: str, discovery_sent: DiscoverySent, dry_run: bool):
    """Send or queue a discovery notification."""
    if dry_run:
        logger.info(f"[DRY RUN] Would notify: {sms_text}")
        return

    session.add(discovery_sent)
    session.flush()

    if is_quiet_hours():
        queue_item = NotificationQueue(
            discovery_sent_id=discovery_sent.id,
            message_text=sms_text,
            queued_at=datetime.utcnow(),
            send_after=next_send_after(),
            priority=50,
        )
        session.add(queue_item)
    else:
        send_sms(sms_text, dry_run=dry_run)


async def discover_music(session, spotify: SpotifyClient, brave: BraveSearchClient, dry_run: bool) -> int:
    """Music discovery via Spotify recommendations."""
    top_music = (
        session.query(TrackedCreator)
        .filter(TrackedCreator.category == "music")
        .order_by(TrackedCreator.profile_score_at_sync.desc())
        .limit(5)
        .all()
    )

    seed_ids = [c.external_id for c in top_music if c.external_id]
    if not seed_ids:
        return 0

    tracks = await spotify.get_recommendations(seed_ids)
    sent = 0

    for track in tracks:
        artist_name = track.artists[0]["name"] if track.artists else "Unknown"
        track_album = track.album
        external_id = track_album.get("id", track.id) if isinstance(track_album, dict) else track.id

        existing_creator = (
            session.query(TrackedCreator)
            .filter(TrackedCreator.name == artist_name)
            .first()
        )
        if existing_creator:
            continue

        if _already_sent(session, external_id):
            continue

        search_results = await brave.search_release(artist_name, track.name)
        search_dicts = [{"title": r.title, "url": r.url, "snippet": r.snippet} for r in search_results]

        # TODO: pass actual taste profile slice from tracked_creators scores
        taste_slice = {
            "top_creators": [c.name for c in top_music],
            "film_taste": "",
        }

        result = judge_discovery_candidate(
            candidate={"title": track.name, "creator": artist_name, "category": "music", "description": ""},
            taste_profile_slice=taste_slice,
            search_results=search_dicts,
        )

        if result.notify:
            link = result.best_link or (search_dicts[0]["url"] if search_dicts else "")
            sms_text = format_discovery_sms("music", track.name, artist_name, result.reason, link)
            discovery = DiscoverySent(
                external_id=external_id,
                category="music",
                title=track.name,
                creator_name=artist_name,
                sent_at=datetime.utcnow(),
            )
            _send_or_queue_discovery(session, sms_text, discovery, dry_run)
            sent += 1
            if sent >= 2:
                break

    return sent


async def discover_films(session, tmdb: TMDBClient, brave: BraveSearchClient, dry_run: bool) -> int:
    """Film discovery via TMDB genre filter."""
    genre_ids = get_film_genre_ids()
    if not genre_ids:
        return 0

    after_date = date.today() - timedelta(days=30)
    movies = await tmdb.get_upcoming_movies(genre_ids, after_date)
    sent = 0

    for movie in movies:
        external_id = str(movie.id)
        if _already_sent(session, external_id):
            continue

        search_results = await brave.search(f"{movie.title} movie review")
        search_dicts = [{"title": r.title, "url": r.url, "snippet": r.snippet} for r in search_results]

        taste_slice = {
            "top_creators": [],
            "film_taste": get_film_taste(),
        }

        result = judge_discovery_candidate(
            candidate={
                "title": movie.title,
                "creator": "Various",
                "category": "film",
                "description": movie.overview,
            },
            taste_profile_slice=taste_slice,
            search_results=search_dicts,
        )

        if result.notify:
            link = result.best_link or (search_dicts[0]["url"] if search_dicts else "")
            sms_text = format_discovery_sms("film", movie.title, "Various", result.reason, link)
            discovery = DiscoverySent(
                external_id=external_id,
                category="film",
                title=movie.title,
                creator_name="Various",
                sent_at=datetime.utcnow(),
            )
            _send_or_queue_discovery(session, sms_text, discovery, dry_run)
            sent += 1
            if sent >= 1:
                break

    return sent


async def discover_tv(session, tmdb: TMDBClient, brave: BraveSearchClient, dry_run: bool) -> int:
    """TV discovery via TMDB similar series."""
    tv_creators = (
        session.query(TrackedCreator)
        .filter(TrackedCreator.category == "tv", TrackedCreator.tier <= 2)
        .all()
    )

    sent = 0
    ninety_days_ago = date.today() - timedelta(days=90)

    for tv_show in tv_creators:
        if not tv_show.external_id:
            continue

        similar = await tmdb.get_similar_series(int(tv_show.external_id))

        for show in similar:
            external_id = str(show.id)
            if _already_sent(session, external_id):
                continue

            if show.first_air_date and show.first_air_date < ninety_days_ago.isoformat():
                continue

            search_results = await brave.search(f"{show.name} TV series review")
            search_dicts = [{"title": r.title, "url": r.url, "snippet": r.snippet} for r in search_results]

            taste_slice = {
                "top_creators": [c.name for c in tv_creators],
                "film_taste": "",
            }

            result = judge_discovery_candidate(
                candidate={
                    "title": show.name,
                    "creator": show.name,
                    "category": "tv",
                    "description": show.overview,
                },
                taste_profile_slice=taste_slice,
                search_results=search_dicts,
            )

            if result.notify:
                link = result.best_link or (search_dicts[0]["url"] if search_dicts else "")
                sms_text = format_discovery_sms("tv", show.name, show.name, result.reason, link)
                discovery = DiscoverySent(
                    external_id=external_id,
                    category="tv",
                    title=show.name,
                    creator_name=show.name,
                    sent_at=datetime.utcnow(),
                )
                _send_or_queue_discovery(session, sms_text, discovery, dry_run)
                sent += 1
                if sent >= 1:
                    return sent

    return sent


async def discover_books(session, brave: BraveSearchClient, dry_run: bool) -> int:
    """Books discovery via Brave Search for similar authors."""
    top_authors = (
        session.query(TrackedCreator)
        .filter(TrackedCreator.category == "book")
        .order_by(TrackedCreator.profile_score_at_sync.desc())
        .limit(3)
        .all()
    )

    sent = 0

    for author in top_authors:
        search_results = await brave.search_similar_books(author.name)
        search_dicts = [{"title": r.title, "url": r.url, "snippet": r.snippet} for r in search_results]

        taste_slice = {
            "top_creators": [a.name for a in top_authors],
            "film_taste": "",
        }

        result = judge_discovery_candidate(
            candidate={
                "title": f"Books similar to {author.name}",
                "creator": "Various",
                "category": "book",
                "description": f"Discovery based on similarity to {author.name}",
            },
            taste_profile_slice=taste_slice,
            search_results=search_dicts,
        )

        if result.notify:
            link = result.best_link or (search_dicts[0]["url"] if search_dicts else "")
            external_id = f"book_disc_{author.name}_{date.today().isoformat()}"

            if _already_sent(session, external_id):
                continue

            sms_text = format_discovery_sms("book", result.reason[:40], "Various", "", link)
            discovery = DiscoverySent(
                external_id=external_id,
                category="book",
                title=result.reason[:100],
                creator_name="Various",
                sent_at=datetime.utcnow(),
            )
            _send_or_queue_discovery(session, sms_text, discovery, dry_run)
            sent += 1
            if sent >= 1:
                break

    return sent


async def run_discovery(dry_run: bool = False):
    """Run all four discovery pipelines."""
    session_factory = get_session_factory()
    session = session_factory()

    spotify = SpotifyClient()
    tmdb = TMDBClient()
    brave = BraveSearchClient()

    try:
        music_sent = await discover_music(session, spotify, brave, dry_run)
        film_sent = await discover_films(session, tmdb, brave, dry_run)
        tv_sent = await discover_tv(session, tmdb, brave, dry_run)
        book_sent = await discover_books(session, brave, dry_run)

        if not dry_run:
            session.commit()

        logger.info(
            f"Discovery complete: music={music_sent}, film={film_sent}, "
            f"tv={tv_sent}, books={book_sent}"
        )
    finally:
        session.close()


def run(dry_run: bool = False):
    asyncio.run(run_discovery(dry_run=dry_run))


def main():
    parser = argparse.ArgumentParser(description="Weekly discovery job")
    parser.add_argument("--dry-run", action="store_true", help="Log what would be sent without firing Twilio")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    try:
        run(dry_run=args.dry_run)
    except Exception as e:
        logging.exception(f"Job failed: {e}")
        if not args.dry_run:
            send_error_sms("weekly-discovery")
        sys.exit(1)


if __name__ == "__main__":
    main()
