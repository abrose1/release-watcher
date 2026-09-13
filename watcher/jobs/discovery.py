"""Weekly discovery job.

Finds new releases matching the user's taste profile across music, film, TV, and books.
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime, date, timedelta, timezone

from watcher.config import get_film_taste, get_film_genre_ids
from watcher.db import get_session_factory
from watcher.models import TrackedCreator, DiscoverySent, NotificationQueue
from watcher.notify import (
    format_discovery_message, send_sms_to_subscribers,
    is_quiet_hours, next_send_after,
)
from watcher.sources.tmdb import TMDBClient
from watcher.sources.brave import BraveSearchClient
from watcher.judge import judge_discovery_candidate

logger = logging.getLogger(__name__)


def _discovery_title_creator(
    result,
    *,
    fallback_title: str = "",
    fallback_creator: str = "",
    search_dicts: list[dict] | None = None,
) -> tuple[str, str]:
    """Resolve display title/creator from judge output with sensible fallbacks."""
    title = (result.title or fallback_title).strip()
    creator = (result.creator or fallback_creator).strip()

    if not title and search_dicts:
        title = search_dicts[0].get("title", "").strip()

    return title, creator


def _already_sent(session, external_id: str) -> bool:
    """Check if we already sent a discovery notification for this item."""
    return session.query(DiscoverySent).filter_by(external_id=external_id).first() is not None


def _send_or_queue_discovery(session, message_text: str, discovery_sent: DiscoverySent, dry_run: bool):
    """Send or queue a discovery notification."""
    if dry_run:
        logger.info(f"[DRY RUN] Would notify: {message_text}")
        return

    session.add(discovery_sent)
    session.flush()

    if is_quiet_hours():
        queue_item = NotificationQueue(
            discovery_sent_id=discovery_sent.id,
            message_text=message_text,
            queued_at=datetime.now(timezone.utc).replace(tzinfo=None),
            send_after=next_send_after(),
            priority=50,
        )
        session.add(queue_item)
    else:
        send_sms_to_subscribers(message_text, dry_run=dry_run)


async def discover_music(session, brave: BraveSearchClient, dry_run: bool) -> int:
    """Music discovery seeded from top tracked music artists.

    Queries tier 1/2 music TrackedCreators ordered by profile score descending,
    then uses Brave Search to find similar new music for each seed artist.
    """
    top_artists = (
        session.query(TrackedCreator)
        .filter(TrackedCreator.category == "music", TrackedCreator.tier <= 2)
        .order_by(TrackedCreator.profile_score_at_sync.desc())
        .limit(5)
        .all()
    )

    if not top_artists:
        logger.warning("No tier 1/2 music creators found — skipping music discovery")
        return 0

    top_names = [a.name for a in top_artists]
    sent = 0

    for artist in top_artists:
        artist_name = artist.name
        external_id = f"music_disc_{artist_name}_{date.today().isoformat()}"

        if _already_sent(session, external_id):
            continue

        search_results = await brave.search_similar_music(artist_name)
        search_dicts = [{"title": r.title, "url": r.url, "snippet": r.snippet} for r in search_results]

        taste_slice = {
            "top_creators": top_names,
            "film_taste": "",
        }

        result = judge_discovery_candidate(
            candidate={
                "title": f"Music similar to {artist_name}",
                "creator": "Various",
                "category": "music",
                "description": f"New music discovery based on top tracked artist: {artist_name}",
            },
            taste_profile_slice=taste_slice,
            search_results=search_dicts,
        )

        if result.notify:
            link = result.best_link or (search_dicts[0]["url"] if search_dicts else "")
            title, creator = _discovery_title_creator(
                result,
                fallback_title=f"New music like {artist_name}",
                fallback_creator=artist_name,
                search_dicts=search_dicts,
            )
            message_text = format_discovery_message(
                "music", title, creator, result.reason, link
            )
            discovery = DiscoverySent(
                external_id=external_id,
                category="music",
                title=title[:100],
                creator_name=creator[:100] or "Various",
                sent_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            _send_or_queue_discovery(session, message_text, discovery, dry_run)
            sent += 1
            if sent >= 1:
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
            title, creator = _discovery_title_creator(
                result, fallback_title=movie.title, search_dicts=search_dicts
            )
            message_text = format_discovery_message("film", title, creator, result.reason, link)
            discovery = DiscoverySent(
                external_id=external_id,
                category="film",
                title=title[:100],
                creator_name=creator[:100] or "Various",
                sent_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            _send_or_queue_discovery(session, message_text, discovery, dry_run)
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
                    "creator": "",
                    "category": "tv",
                    "description": (
                        f"{show.overview or 'No overview.'} "
                        f"Suggested because you track {tv_show.name}."
                    ),
                },
                taste_profile_slice=taste_slice,
                search_results=search_dicts,
            )

            if result.notify:
                link = result.best_link or (search_dicts[0]["url"] if search_dicts else "")
                title, _ = _discovery_title_creator(
                    result, fallback_title=show.name, search_dicts=search_dicts
                )
                message_text = format_discovery_message("tv", title, "", result.reason, link)
                discovery = DiscoverySent(
                    external_id=external_id,
                    category="tv",
                    title=title[:100],
                    creator_name=tv_show.name[:100],
                    sent_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
                _send_or_queue_discovery(session, message_text, discovery, dry_run)
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

            title, creator = _discovery_title_creator(
                result,
                fallback_title=f"Books like {author.name}",
                fallback_creator=author.name,
                search_dicts=search_dicts,
            )
            message_text = format_discovery_message("book", title, creator, result.reason, link)
            discovery = DiscoverySent(
                external_id=external_id,
                category="book",
                title=title[:100],
                creator_name=creator[:100] or "Various",
                sent_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            _send_or_queue_discovery(session, message_text, discovery, dry_run)
            sent += 1
            if sent >= 1:
                break

    return sent


async def run_discovery(dry_run: bool = False):
    """Run all four discovery pipelines."""
    session_factory = get_session_factory()
    session = session_factory()

    tmdb = TMDBClient()
    brave = BraveSearchClient()

    try:
        music_sent = await discover_music(session, brave, dry_run)
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
        sys.exit(1)


if __name__ == "__main__":
    main()
