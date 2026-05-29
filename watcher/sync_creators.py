"""Sync creators from taste-profile DB into watcher's tracked_creators table."""

import argparse
import logging
from collections.abc import Mapping
from datetime import datetime, timezone

from sqlalchemy import MetaData, Table, create_engine, select

from watcher.config import get_env, get_tv_watchlist
from watcher.db import get_session_factory
from watcher.models import TrackedCreator, TierChange

logger = logging.getLogger(__name__)

# Book-only stubs for local dev when taste-profile DB is unavailable.
STUB_CREATORS = [
    {"category": "book", "name": "STUB_AUTHOR_1", "tier": 1, "external_id": None},
    {"category": "book", "name": "STUB_AUTHOR_2", "tier": 2, "external_id": None},
]


def _resolve_book_tier_cutoffs(meta_row: Mapping[str, object] | None) -> tuple[int, int]:
    """Return (tier1_top_n, tier2_top_n) from profile_metadata.

    Authors are ranked by ``rank_score`` descending; positions 1..t1 are tier 1,
    t1+1..t2 tier 2, remainder tier 3. Missing cutoffs use defaults (10 / max(t1+20, 30)).
    """
    t1: int | None = None
    t2: int | None = None
    if meta_row is not None:
        raw1 = meta_row.get("tier1_book_cutoff")
        raw2 = meta_row.get("tier2_book_cutoff")
        t1 = int(raw1) if raw1 is not None else None
        t2 = int(raw2) if raw2 is not None else None

    used_default = t1 is None or t2 is None
    if t1 is None:
        t1 = 10
    if t2 is None:
        t2 = max(t1 + 20, 30)
    if t2 < t1:
        logger.warning(
            "tier2_book_cutoff (%s) < tier1_book_cutoff (%s); clamping tier2 to tier1",
            t2,
            t1,
        )
        t2 = t1
    if used_default:
        logger.warning(
            "Book tier cutoffs missing or incomplete in profile_metadata; "
            "using tier1_top_n=%s tier2_top_n=%s",
            t1,
            t2,
        )
    return t1, t2


def _resolve_music_tier_cutoffs(meta_row: Mapping[str, object] | None) -> tuple[int, int]:
    """Return (tier1_top_n, tier2_top_n) for ``music_artists`` ordering.

    Uses ``tier1_music_cutoff`` / ``tier2_music_cutoff`` from ``profile_metadata``.
    Missing values default to tier1=8, tier2=25 with a warning.
    """
    t1: int | None = None
    t2: int | None = None
    if meta_row is not None:
        raw1 = meta_row.get("tier1_music_cutoff")
        raw2 = meta_row.get("tier2_music_cutoff")
        t1 = int(raw1) if raw1 is not None else None
        t2 = int(raw2) if raw2 is not None else None

    used_default = t1 is None or t2 is None
    if t1 is None:
        t1 = 8
    if t2 is None:
        t2 = 25
    if t2 < t1:
        logger.warning(
            "tier2_music_cutoff (%s) < tier1_music_cutoff (%s); clamping tier2 to tier1",
            t2,
            t1,
        )
        t2 = t1
    if used_default:
        logger.warning(
            "Music tier cutoffs missing or incomplete in profile_metadata; "
            "using tier1_top_n=%s tier2_top_n=%s",
            t1,
            t2,
        )
    return t1, t2


def _tier_for_rank(position_1based: int, tier1_top_n: int, tier2_top_n: int) -> int:
    if position_1based <= tier1_top_n:
        return 1
    if position_1based <= tier2_top_n:
        return 2
    return 3


def _coerce_google_books_external_id(raw: object) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    return s if s else None


def _coerce_spotify_external_id(raw: object) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    return s if s else None


def sync_from_taste_profile(session):
    """Sync book authors and music artists from the taste-profile DB into ``tracked_creators``.

    Reads tier cutoffs from ``profile_metadata`` (defaults if unset). Books use
    ``rank_score`` order; music uses ``listen_score`` order. Music ``external_id``
    is Spotify artist id when present (required for Spotify polling).
    """
    taste_db_url = get_env("TASTE_PROFILE_DATABASE_URL")
    taste_engine = create_engine(taste_db_url)
    metadata_obj = MetaData()
    try:
        book_authors_tbl = Table("book_authors", metadata_obj, autoload_with=taste_engine)
        profile_meta_tbl = Table("profile_metadata", metadata_obj, autoload_with=taste_engine)
        music_artists_tbl = Table("music_artists", metadata_obj, autoload_with=taste_engine)

        with taste_engine.connect() as conn:
            meta_row = conn.execute(select(profile_meta_tbl).limit(1)).mappings().first()
            tier1_n, tier2_n = _resolve_book_tier_cutoffs(meta_row)
            mt1, mt2 = _resolve_music_tier_cutoffs(meta_row)
            author_rows = conn.execute(
                select(book_authors_tbl).order_by(
                    book_authors_tbl.c.rank_score.desc(),
                    book_authors_tbl.c.name.asc(),
                )
            ).mappings().all()
            music_rows = conn.execute(
                select(music_artists_tbl).order_by(
                    music_artists_tbl.c.listen_score.desc(),
                    music_artists_tbl.c.name.asc(),
                )
            ).mappings().all()
    finally:
        taste_engine.dispose()

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for position, row in enumerate(author_rows, start=1):
        name = row["name"]
        tier = _tier_for_rank(position, tier1_n, tier2_n)
        rank_score = float(row["rank_score"])
        external_id = _coerce_google_books_external_id(row.get("google_books_id"))

        existing = (
            session.query(TrackedCreator)
            .filter_by(name=name, category="book")
            .first()
        )
        if existing:
            old_tier = existing.tier
            existing.tier = tier
            existing.external_id = external_id
            existing.last_synced_from_profile = now
            existing.profile_score_at_sync = rank_score
            if old_tier != tier:
                session.add(
                    TierChange(
                        tracked_creator_id=existing.id,
                        old_tier=old_tier,
                        new_tier=tier,
                        changed_at=now,
                    )
                )
        else:
            session.add(
                TrackedCreator(
                    category="book",
                    name=name,
                    tier=tier,
                    external_id=external_id,
                    last_synced_from_profile=now,
                    profile_score_at_sync=rank_score,
                )
            )

    for position, row in enumerate(music_rows, start=1):
        name = row["name"]
        tier = _tier_for_rank(position, mt1, mt2)
        listen_score = float(row["listen_score"])
        external_id = _coerce_spotify_external_id(row.get("spotify_id"))

        existing = (
            session.query(TrackedCreator)
            .filter_by(name=name, category="music")
            .first()
        )
        if existing:
            old_tier = existing.tier
            existing.tier = tier
            existing.external_id = external_id
            existing.last_synced_from_profile = now
            existing.profile_score_at_sync = listen_score
            if old_tier != tier:
                session.add(
                    TierChange(
                        tracked_creator_id=existing.id,
                        old_tier=old_tier,
                        new_tier=tier,
                        changed_at=now,
                    )
                )
        else:
            session.add(
                TrackedCreator(
                    category="music",
                    name=name,
                    tier=tier,
                    external_id=external_id,
                    last_synced_from_profile=now,
                    profile_score_at_sync=listen_score,
                )
            )

    session.commit()
    logger.info(
        "Synced %d book author(s) from taste-profile (tier1=1..%s, tier2=%s..%s, tier3=remainder)",
        len(author_rows),
        tier1_n,
        tier1_n + 1,
        tier2_n,
    )
    logger.info(
        "Synced %d music artist(s) (tier1=1..%s, tier2=%s..%s; tier 3 excluded from daily Spotify scan)",
        len(music_rows),
        mt1,
        mt1 + 1,
        mt2,
    )


def sync_stub_data(session):
    """Populate tracked_creators with stub data for development."""
    print("\u26a0 Running with stub data \u2014 taste-profile DB not connected.")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
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

    # TODO: Film is not creator-synced here (judge/style via ``config.yaml`` only). If a
    # structured film watchlist or taste-profile source is added later, wire it like TV or books.

    tv_shows = get_tv_watchlist()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

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

        # TODO: When running books-only in production, consider a ``--books-only`` flag (or
        # config) to skip this block so TV never touches ``tracked_creators``.
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
