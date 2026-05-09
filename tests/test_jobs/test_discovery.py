"""Integration tests for the weekly discovery job."""

from datetime import datetime, date, timedelta
from unittest.mock import patch, AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from watcher.models import Base, TrackedCreator, DiscoverySent, NotificationQueue
from watcher.judge import JudgeResult
from watcher.sources.spotify import Track
from watcher.sources.tmdb import Movie, TVShow
from watcher.sources.brave import SearchResult


@pytest.fixture
def disc_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    creators = [
        TrackedCreator(category="music", name="Top Artist", tier=1,
                      external_id="spotify_top", profile_score_at_sync=95.0),
        TrackedCreator(category="book", name="Top Author", tier=1,
                      external_id="gbooks_top", profile_score_at_sync=88.0),
        TrackedCreator(category="tv", name="Top Show", tier=1,
                      external_id="12345", profile_score_at_sync=0.0),
    ]
    for c in creators:
        session.add(c)
    session.commit()

    yield session
    session.close()


class TestMusicDiscovery:
    @patch("watcher.jobs.discovery.send_sms")
    @patch("watcher.jobs.discovery.is_quiet_hours", return_value=False)
    @patch("watcher.jobs.discovery.judge_discovery_candidate")
    @patch("watcher.jobs.discovery.BraveSearchClient")
    @patch("watcher.jobs.discovery.SpotifyClient")
    async def test_music_discovery_flow(
        self, mock_spotify_cls, mock_brave_cls, mock_judge, mock_quiet, mock_send, disc_session
    ):
        mock_spotify = AsyncMock()
        mock_spotify.get_recommendations.return_value = [
            Track(id="rec_1", name="New Song", artists=[{"name": "New Artist"}],
                  album={"id": "rec_album", "name": "Album"})
        ]
        mock_spotify_cls.return_value = mock_spotify

        mock_brave = AsyncMock()
        mock_brave.search_release.return_value = [
            SearchResult(title="Review", url="https://example.com", snippet="")
        ]
        mock_brave_cls.return_value = mock_brave

        mock_judge.return_value = JudgeResult(
            notify=True, reason="Similar style", best_link="https://example.com"
        )

        from watcher.jobs.discovery import discover_music
        sent = await discover_music(disc_session, mock_spotify, mock_brave, dry_run=False)

        assert sent == 1
        discovery = disc_session.query(DiscoverySent).filter_by(category="music").all()
        assert len(discovery) == 1
        assert discovery[0].creator_name == "New Artist"

    @patch("watcher.jobs.discovery.judge_discovery_candidate")
    @patch("watcher.jobs.discovery.BraveSearchClient")
    @patch("watcher.jobs.discovery.SpotifyClient")
    async def test_skips_existing_creators(
        self, mock_spotify_cls, mock_brave_cls, mock_judge, disc_session
    ):
        mock_spotify = AsyncMock()
        mock_spotify.get_recommendations.return_value = [
            Track(id="rec_2", name="Song", artists=[{"name": "Top Artist"}],
                  album={"id": "album_2", "name": "Album"})
        ]
        mock_spotify_cls.return_value = mock_spotify
        mock_brave_cls.return_value = AsyncMock()

        from watcher.jobs.discovery import discover_music
        sent = await discover_music(disc_session, mock_spotify, mock_brave_cls.return_value, dry_run=False)

        assert sent == 0
        mock_judge.assert_not_called()


class TestFilmDiscovery:
    @patch("watcher.jobs.discovery.send_sms")
    @patch("watcher.jobs.discovery.is_quiet_hours", return_value=False)
    @patch("watcher.jobs.discovery.judge_discovery_candidate")
    @patch("watcher.jobs.discovery.get_film_genre_ids", return_value=[18, 53])
    @patch("watcher.jobs.discovery.get_film_taste", return_value="I like thrillers")
    async def test_film_discovery_flow(
        self, mock_taste, mock_genres, mock_judge, mock_quiet, mock_send, disc_session
    ):
        mock_tmdb = AsyncMock()
        mock_tmdb.get_upcoming_movies.return_value = [
            Movie(id=77777, title="New Thriller", release_date="2026-05-01",
                  overview="A thriller", genre_ids=[18, 53])
        ]

        mock_brave = AsyncMock()
        mock_brave.search.return_value = [
            SearchResult(title="Review", url="https://example.com/film", snippet="")
        ]

        mock_judge.return_value = JudgeResult(
            notify=True, reason="Matches thriller taste", best_link="https://example.com/film"
        )

        from watcher.jobs.discovery import discover_films
        sent = await discover_films(disc_session, mock_tmdb, mock_brave, dry_run=False)

        assert sent == 1
        discovery = disc_session.query(DiscoverySent).filter_by(category="film").all()
        assert len(discovery) == 1


class TestTVDiscovery:
    @patch("watcher.jobs.discovery.send_sms")
    @patch("watcher.jobs.discovery.is_quiet_hours", return_value=False)
    @patch("watcher.jobs.discovery.judge_discovery_candidate")
    async def test_tv_discovery_flow(self, mock_judge, mock_quiet, mock_send, disc_session):
        mock_tmdb = AsyncMock()
        mock_tmdb.get_similar_series.return_value = [
            TVShow(id=55555, name="Similar Series", first_air_date="2026-04-01",
                   overview="A similar show")
        ]

        mock_brave = AsyncMock()
        mock_brave.search.return_value = [
            SearchResult(title="Review", url="https://example.com/tv", snippet="")
        ]

        mock_judge.return_value = JudgeResult(
            notify=True, reason="Similar to your favorites", best_link="https://example.com/tv"
        )

        from watcher.jobs.discovery import discover_tv
        sent = await discover_tv(disc_session, mock_tmdb, mock_brave, dry_run=False)

        assert sent == 1
        discovery = disc_session.query(DiscoverySent).filter_by(category="tv").all()
        assert len(discovery) == 1


class TestBookDiscovery:
    @patch("watcher.jobs.discovery.send_sms")
    @patch("watcher.jobs.discovery.is_quiet_hours", return_value=False)
    @patch("watcher.jobs.discovery.judge_discovery_candidate")
    async def test_book_discovery_flow(self, mock_judge, mock_quiet, mock_send, disc_session):
        mock_brave = AsyncMock()
        mock_brave.search_similar_books.return_value = [
            SearchResult(title="Similar Books", url="https://example.com/books", snippet="Books like...")
        ]

        mock_judge.return_value = JudgeResult(
            notify=True, reason="Similar literary style", best_link="https://example.com/books"
        )

        from watcher.jobs.discovery import discover_books
        sent = await discover_books(disc_session, mock_brave, dry_run=False)

        assert sent == 1


class TestDiscoveryDryRun:
    @patch("watcher.jobs.discovery.send_sms")
    @patch("watcher.jobs.discovery.judge_discovery_candidate")
    @patch("watcher.jobs.discovery.BraveSearchClient")
    @patch("watcher.jobs.discovery.SpotifyClient")
    async def test_dry_run_no_db_writes(
        self, mock_spotify_cls, mock_brave_cls, mock_judge, mock_send, disc_session
    ):
        mock_spotify = AsyncMock()
        mock_spotify.get_recommendations.return_value = [
            Track(id="rec_dry", name="Dry Song", artists=[{"name": "Dry Artist"}],
                  album={"id": "dry_album", "name": "Album"})
        ]
        mock_spotify_cls.return_value = mock_spotify

        mock_brave = AsyncMock()
        mock_brave.search_release.return_value = [
            SearchResult(title="R", url="https://example.com", snippet="")
        ]
        mock_brave_cls.return_value = mock_brave

        mock_judge.return_value = JudgeResult(
            notify=True, reason="Good", best_link="https://example.com"
        )

        from watcher.jobs.discovery import discover_music
        sent = await discover_music(disc_session, mock_spotify, mock_brave, dry_run=True)

        assert sent == 1
        discovery = disc_session.query(DiscoverySent).all()
        assert len(discovery) == 0
        mock_send.assert_not_called()
