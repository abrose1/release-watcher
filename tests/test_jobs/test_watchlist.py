"""Integration tests for the daily watchlist job."""

from datetime import datetime, date, timedelta
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from watcher.models import Base, TrackedCreator, Release, NotificationQueue
from watcher.judge import JudgeResult
from watcher.sources.spotify import Album
from watcher.sources.brave import SearchResult


@pytest.fixture
def job_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    creator = TrackedCreator(
        category="music",
        name="Test Artist",
        tier=1,
        external_id="spotify_123",
        profile_score_at_sync=90.0,
    )
    session.add(creator)
    session.commit()

    yield Session, session
    session.close()


class TestWatchlistJob:
    @patch("watcher.jobs.watchlist.send_sms")
    @patch("watcher.jobs.watchlist.is_quiet_hours", return_value=False)
    @patch("watcher.jobs.watchlist.flush_queue")
    @patch("watcher.jobs.watchlist.judge_watchlist_hit")
    @patch("watcher.jobs.watchlist.BraveSearchClient")
    @patch("watcher.jobs.watchlist.BooksClient")
    @patch("watcher.jobs.watchlist.TMDBClient")
    @patch("watcher.jobs.watchlist.SpotifyClient")
    @patch("watcher.jobs.watchlist.get_session_factory")
    async def test_full_watchlist_flow(
        self, mock_factory, mock_spotify_cls, mock_tmdb_cls, mock_books_cls,
        mock_brave_cls, mock_judge, mock_flush, mock_quiet, mock_send, job_db
    ):
        Session, session = job_db
        mock_factory.return_value = Session

        mock_spotify = AsyncMock()
        mock_spotify.get_artist_albums.return_value = [
            Album(id="album_1", name="New Album", release_date="2026-04-01",
                  album_type="album", artists=[{"name": "Test Artist"}],
                  spotify_url="https://spotify.com/album_1")
        ]
        mock_spotify.get_artist_new_singles.return_value = []
        mock_spotify_cls.return_value = mock_spotify

        mock_tmdb_cls.return_value = AsyncMock()
        mock_books_cls.return_value = AsyncMock()

        mock_brave = AsyncMock()
        mock_brave.search_release.return_value = [
            SearchResult(title="Review", url="https://example.com/review", snippet="Great album")
        ]
        mock_brave_cls.return_value = mock_brave

        mock_judge.return_value = JudgeResult(
            notify=True, reason="Genuine new album", best_link="https://example.com/review"
        )

        from watcher.jobs.watchlist import run_scan
        await run_scan(dry_run=False)

        releases = session.query(Release).all()
        assert len(releases) == 1
        assert releases[0].title == "New Album"
        assert releases[0].external_release_id == "album_1"

        mock_send.assert_called_once()
        call_args = mock_send.call_args[0][0]
        assert "Test Artist" in call_args
        assert "https://example.com/review" in call_args

    @patch("watcher.jobs.watchlist.send_sms")
    @patch("watcher.jobs.watchlist.flush_queue")
    @patch("watcher.jobs.watchlist.judge_watchlist_hit")
    @patch("watcher.jobs.watchlist.BraveSearchClient")
    @patch("watcher.jobs.watchlist.BooksClient")
    @patch("watcher.jobs.watchlist.TMDBClient")
    @patch("watcher.jobs.watchlist.SpotifyClient")
    @patch("watcher.jobs.watchlist.get_session_factory")
    async def test_dry_run_no_db_writes(
        self, mock_factory, mock_spotify_cls, mock_tmdb_cls, mock_books_cls,
        mock_brave_cls, mock_judge, mock_flush, mock_send, job_db
    ):
        Session, session = job_db
        mock_factory.return_value = Session

        mock_spotify = AsyncMock()
        mock_spotify.get_artist_albums.return_value = [
            Album(id="album_dry", name="Dry Run Album", release_date="2026-04-01",
                  album_type="album", artists=[{"name": "Test Artist"}],
                  spotify_url="https://spotify.com/album_dry")
        ]
        mock_spotify.get_artist_new_singles.return_value = []
        mock_spotify_cls.return_value = mock_spotify

        mock_tmdb_cls.return_value = AsyncMock()
        mock_books_cls.return_value = AsyncMock()

        mock_brave = AsyncMock()
        mock_brave.search_release.return_value = [
            SearchResult(title="Review", url="https://example.com", snippet="")
        ]
        mock_brave_cls.return_value = mock_brave

        mock_judge.return_value = JudgeResult(
            notify=True, reason="Test", best_link="https://example.com"
        )

        from watcher.jobs.watchlist import run_scan
        await run_scan(dry_run=True)

        releases = session.query(Release).all()
        assert len(releases) == 0
        mock_send.assert_not_called()

    @patch("watcher.jobs.watchlist.flush_queue")
    @patch("watcher.jobs.watchlist.judge_watchlist_hit")
    @patch("watcher.jobs.watchlist.BraveSearchClient")
    @patch("watcher.jobs.watchlist.BooksClient")
    @patch("watcher.jobs.watchlist.TMDBClient")
    @patch("watcher.jobs.watchlist.SpotifyClient")
    @patch("watcher.jobs.watchlist.get_session_factory")
    async def test_deduplication(
        self, mock_factory, mock_spotify_cls, mock_tmdb_cls, mock_books_cls,
        mock_brave_cls, mock_judge, mock_flush, job_db
    ):
        Session, session = job_db
        creator = session.query(TrackedCreator).first()
        existing_release = Release(
            tracked_creator_id=creator.id,
            external_release_id="album_dup",
            title="Already Known",
        )
        session.add(existing_release)
        session.commit()

        mock_factory.return_value = Session

        mock_spotify = AsyncMock()
        mock_spotify.get_artist_albums.return_value = [
            Album(id="album_dup", name="Already Known", release_date="2026-04-01",
                  album_type="album", artists=[{"name": "Test Artist"}],
                  spotify_url="")
        ]
        mock_spotify.get_artist_new_singles.return_value = []
        mock_spotify_cls.return_value = mock_spotify

        mock_tmdb_cls.return_value = AsyncMock()
        mock_books_cls.return_value = AsyncMock()
        mock_brave_cls.return_value = AsyncMock()

        from watcher.jobs.watchlist import run_scan
        await run_scan(dry_run=False)

        mock_judge.assert_not_called()

    @patch("watcher.jobs.watchlist.send_sms")
    @patch("watcher.jobs.watchlist.next_send_after")
    @patch("watcher.jobs.watchlist.is_quiet_hours", return_value=True)
    @patch("watcher.jobs.watchlist.flush_queue")
    @patch("watcher.jobs.watchlist.judge_watchlist_hit")
    @patch("watcher.jobs.watchlist.BraveSearchClient")
    @patch("watcher.jobs.watchlist.BooksClient")
    @patch("watcher.jobs.watchlist.TMDBClient")
    @patch("watcher.jobs.watchlist.SpotifyClient")
    @patch("watcher.jobs.watchlist.get_session_factory")
    async def test_quiet_hours_queues(
        self, mock_factory, mock_spotify_cls, mock_tmdb_cls, mock_books_cls,
        mock_brave_cls, mock_judge, mock_flush, mock_quiet, mock_next_send,
        mock_send, job_db
    ):
        Session, session = job_db
        mock_factory.return_value = Session
        mock_next_send.return_value = datetime(2026, 4, 16, 15, 0, 0)

        mock_spotify = AsyncMock()
        mock_spotify.get_artist_albums.return_value = [
            Album(id="album_q", name="Queued Album", release_date="2026-04-01",
                  album_type="album", artists=[{"name": "Test Artist"}],
                  spotify_url="")
        ]
        mock_spotify.get_artist_new_singles.return_value = []
        mock_spotify_cls.return_value = mock_spotify

        mock_tmdb_cls.return_value = AsyncMock()
        mock_books_cls.return_value = AsyncMock()

        mock_brave = AsyncMock()
        mock_brave.search_release.return_value = [
            SearchResult(title="R", url="https://example.com", snippet="")
        ]
        mock_brave_cls.return_value = mock_brave

        mock_judge.return_value = JudgeResult(notify=True, reason="", best_link="https://example.com")

        from watcher.jobs.watchlist import run_scan
        await run_scan(dry_run=False)

        queue_items = session.query(NotificationQueue).all()
        assert len(queue_items) == 1
        assert queue_items[0].priority == 10
        mock_send.assert_not_called()
