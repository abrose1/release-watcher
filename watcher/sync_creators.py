"""Sync creators from taste-profile DB into watcher's tracked_creators table."""

import argparse
import logging
import sys
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from watcher.config import get_env, get_tv_watchlist
from watcher.db import get_session_factory
from watcher.models import TrackedCreator, TierChange

logger = logging.getLogger(__name__)

# TODO: wire to taste-profile DB — replace these stubs with real data
STUB_CREATORS = [
    {"category": "music", "name": "STUB_ARTIST_1", "tier": 1, "external_id": None},
    {"category": "music", "name": "STUB_ARTIST_2", "tier": 2, "external_id": None},
    {"category": "book", "name": "STUB_AUTHOR_1", "tier": 1, "external_id": None},
    {"category": "book", "name": "STUB_AUTHOR_2", "tier": 2, "external_id": None},
]


def sync_from_taste_profile(session):
    """Sync creators from the taste-profile DB.

    # TODO: connect to TASTE_PROFILE_DATABASE_URL and read book_authors + music_artists + profile_metadata
    """
    taste_db_url = get_env("TASTE_PROFILE_DATABASE_URL")
    taste_engine = create_engine(taste_db_url)
    taste_session = sessionmaker(bind=taste_engine)()

    try:
        # TODO: Read from book_authors and music_artists tables
        # Apply tier thresholds from profile_metadata
        # Upsert into tracked_creators
        logger.warning("Taste profile sync not yet implemented — waiting for taste-profile repo")
    finally:
        taste_session.close()


def sync_stub_data(session):
    """Populate tracked_creators with stub data for development."""
    print("\u26a0 Running with stub data \u2014 taste-profile DB not connected.")

    now = datetime.utcnow()
    for creator_data in STUB_CREATORS:
        existing = (
            session.query(TrackedCreator)
            .filter_by(name=creator_data["name"], category=creator_data["category"])
            .first()
        )
        if existing:
            old_tier = existing.tier
            existing.tier = creator_data["tier"]
            existing.external_id = creator_data["external_id"]
            existing.last_synced_from_profile = now
            existing.profile_score_at_sync = -1.0

            if old_tier != creator_data["tier"]:
                tier_change = TierChange(
                    tracked_creator_id=existing.id,
                    old_tier=old_tier,
                    new_tier=creator_data["tier"],
                    changed_at=now,
                )
                session.add(tier_change)
        else:
            creator = TrackedCreator(
                category=creator_data["category"],
                name=creator_data["name"],
                tier=creator_data["tier"],
                external_id=creator_data["external_id"],
                last_synced_from_profile=now,
                profile_score_at_sync=-1.0,
            )
            session.add(creator)

    session.commit()
    logger.info(f"Synced {len(STUB_CREATORS)} stub creators")


def sync_tv_watchlist(session):
    """Sync TV shows from config.yaml into tracked_creators."""
    tv_shows = get_tv_watchlist()
    now = datetime.utcnow()

    for show in tv_shows:
        existing = (
            session.query(TrackedCreator)
            .filter_by(name=show["name"], category="tv")
            .first()
        )
        if existing:
            old_tier = existing.tier
            existing.tier = show["tier"]
            existing.external_id = str(show.get("tmdb_id", ""))
            existing.last_synced_from_profile = now

            if old_tier != show["tier"]:
                tier_change = TierChange(
                    tracked_creator_id=existing.id,
                    old_tier=old_tier,
                    new_tier=show["tier"],
                    changed_at=now,
                )
                session.add(tier_change)
        else:
            creator = TrackedCreator(
                category="tv",
                name=show["name"],
                tier=show["tier"],
                external_id=str(show.get("tmdb_id", "")),
                last_synced_from_profile=now,
                profile_score_at_sync=0.0,
            )
            session.add(creator)

    session.commit()
    logger.info(f"Synced {len(tv_shows)} TV shows from config")


def run(stub: bool = False):
    """Run the creator sync."""
    session_factory = get_session_factory()
    session = session_factory()

    try:
        if stub:
            sync_stub_data(session)
        else:
            sync_from_taste_profile(session)

        sync_tv_watchlist(session)
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description="Sync creators from taste-profile DB")
    parser.add_argument("--stub", action="store_true", help="Use stub data instead of taste-profile DB")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    run(stub=args.stub)


if __name__ == "__main__":
    main()
