"""Integration tests for the daily announcement scan job."""

from datetime import datetime, date
from unittest.mock import patch, AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from watcher.models import Base, TrackedCreator, Release
from watcher.judge import JudgeResult
from watcher.sources.brave import SearchResult


@pytest.fixture
def ann_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    creator = TrackedCreator(
        category="music",
        name="Tier 1 Artist",
        tier=1,
        external_id="spotify_tier1",
        profile_score_at_sync=95.0,
    )
    session.add(creator)

    tier2 = TrackedCreator(
        category="book",
        name="Tier 2 Author",
        tier=2,
        external_id="books_tier2",
        profile_score_at_sync=50.0,
    )
    session.add(tier2)
    session.commit()

    yield Session, session
    session.close()


class TestAnnouncementJob:
    @patch("watcher.jobs.announcement.send_sms")
    @patch("watcher.jobs.announcement.is_quiet_hours", return_value=False)
    @patch("watcher.jobs.announcement.judge_watchlist_hit")
    @patch("watcher.jobs.announcement.BraveSearchClient")
    @patch("watcher.jobs.announcement.get_session_factory")
    @patch("watcher.jobs.announcement.get_preferences")
    async def test_full_announcement_flow(
        self, mock_prefs, mock_factory, mock_brave_cls,
        mock_judge, mock_quiet, mock_send, ann_db
    ):
        Session, session = ann_db
        mock_prefs.return_value = {"tier1_announcement_search": True}
        mock_factory.return_value = Session

        mock_brave = AsyncMock()
        mock_brave.search_announcement.return_value = [
            SearchResult(
                title="Artist Announces New Album Coming 2026",
                url="https://example.com/announcement",
                snippet="Big news from the artist",
            )
        ]
        mock_brave_cls.return_value = mock_brave

        mock_judge.return_value = JudgeResult(
            notify=True, reason="Confirmed announcement",
            best_link="https://example.com/announcement"
        )

        from watcher.jobs.announcement import run_announcement_scan
        await run_announcement_scan(dry_run=False)

        releases = session.query(Release).all()
        assert len(releases) == 1
        assert releases[0].type == "announcement"
        assert releases[0].announcement_hash is not None
        mock_send.assert_called_once()

    @patch("watcher.jobs.announcement.judge_watchlist_hit")
    @patch("watcher.jobs.announcement.BraveSearchClient")
    @patch("watcher.jobs.announcement.get_session_factory")
    @patch("watcher.jobs.announcement.get_preferences")
    async def test_only_tier1_scanned(
        self, mock_prefs, mock_factory, mock_brave_cls, mock_judge, ann_db
    ):
        Session, session = ann_db
        mock_prefs.return_value = {"tier1_announcement_search": True}
        mock_factory.return_value = Session

        mock_brave = AsyncMock()
        mock_brave.search_announcement.return_value = []
        mock_brave_cls.return_value = mock_brave

        from watcher.jobs.announcement import run_announcement_scan
        await run_announcement_scan(dry_run=True)

        mock_brave.search_announcement.assert_called_once()
        call_args = mock_brave.search_announcement.call_args
        assert call_args[0][0] == "Tier 1 Artist"

    @patch("watcher.jobs.announcement.BraveSearchClient")
    @patch("watcher.jobs.announcement.get_session_factory")
    @patch("watcher.jobs.announcement.get_preferences")
    async def test_disabled_in_config(self, mock_prefs, mock_factory, mock_brave_cls, ann_db):
        Session, session = ann_db
        mock_prefs.return_value = {"tier1_announcement_search": False}
        mock_factory.return_value = Session

        from watcher.jobs.announcement import run_announcement_scan
        await run_announcement_scan(dry_run=False)

        mock_brave_cls.assert_not_called()

    @patch("watcher.jobs.announcement.judge_watchlist_hit")
    @patch("watcher.jobs.announcement.BraveSearchClient")
    @patch("watcher.jobs.announcement.get_session_factory")
    @patch("watcher.jobs.announcement.get_preferences")
    async def test_deduplication_by_hash(
        self, mock_prefs, mock_factory, mock_brave_cls, mock_judge, ann_db
    ):
        Session, session = ann_db
        mock_prefs.return_value = {"tier1_announcement_search": True}
        mock_factory.return_value = Session

        import hashlib
        ann_hash = hashlib.md5(
            "Existing Announcementhttps://example.com/old".encode()
        ).hexdigest()

        creator = session.query(TrackedCreator).filter_by(tier=1).first()
        existing = Release(
            tracked_creator_id=creator.id,
            external_release_id=f"ann_{ann_hash[:16]}",
            title="Existing Announcement",
            type="announcement",
            announcement_hash=ann_hash,
        )
        session.add(existing)
        session.commit()

        mock_brave = AsyncMock()
        mock_brave.search_announcement.return_value = [
            SearchResult(
                title="Existing Announcement",
                url="https://example.com/old",
                snippet="Old news",
            )
        ]
        mock_brave_cls.return_value = mock_brave

        from watcher.jobs.announcement import run_announcement_scan
        await run_announcement_scan(dry_run=False)

        mock_judge.assert_not_called()

    @patch("watcher.jobs.announcement.send_sms")
    @patch("watcher.jobs.announcement.is_quiet_hours", return_value=False)
    @patch("watcher.jobs.announcement.judge_watchlist_hit")
    @patch("watcher.jobs.announcement.BraveSearchClient")
    @patch("watcher.jobs.announcement.get_session_factory")
    @patch("watcher.jobs.announcement.get_preferences")
    async def test_dry_run_no_writes(
        self, mock_prefs, mock_factory, mock_brave_cls,
        mock_judge, mock_quiet, mock_send, ann_db
    ):
        Session, session = ann_db
        mock_prefs.return_value = {"tier1_announcement_search": True}
        mock_factory.return_value = Session

        mock_brave = AsyncMock()
        mock_brave.search_announcement.return_value = [
            SearchResult(title="News", url="https://example.com", snippet="")
        ]
        mock_brave_cls.return_value = mock_brave

        mock_judge.return_value = JudgeResult(notify=True, reason="", best_link="")

        from watcher.jobs.announcement import run_announcement_scan
        await run_announcement_scan(dry_run=True)

        releases = session.query(Release).all()
        assert len(releases) == 0
        mock_send.assert_not_called()
