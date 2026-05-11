"""Integration tests for the weekly discovery job."""

from datetime import datetime, date, timedelta
from unittest.mock import patch, AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from watcher.models import Base, TrackedCreator, DiscoverySent, NotificationQueue
from watcher.judge import JudgeResult
from watcher.sources.spotify import PlaylistTrack
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
    @patch("watcher.jobs.discovery.get_spotify_seed_playlist_ids", return_value=["test_playlist"])
    async def test_music_discovery_flow(
        self, mock_playlist_ids, mock_judge, mock_quiet, mock_send, disc_session
    ):
        mock_spotify = AsyncMock()
        mock_spotify.get_playlist_tracks.return_value = [
            PlaylistTrack(id="t1", name="Song One", artists=["New Artist"]),
        ]

        mock_brave = AsyncMock()
        mock_brave.search_similar_music.return_value = [
            SearchResult(title="New Artist Debut", url="https://example.com/music", snippet="Sounds great")
        ]

        mock_judge.return_value = JudgeResult(
            notify=True, reason="Similar vibe", best_link="https://example.com/music"
        )

        from watcher.jobs.discovery import discover_music
        sent = await discover_music(disc_session, mock_spotify, mock_brave, dry_run=False)

        assert sent == 1
        mock_spotify.get_playlist_tracks.assert_called_once_with("test_playlist")
        discovery = disc_session.query(DiscoverySent).filter_by(category="music").all()
        assert len(discovery) == 1

    @patch("watcher.jobs.discovery.judge_discovery_candidate")
    @patch("watcher.jobs.discovery.get_spotify_seed_playlist_ids", return_value=["test_playlist"])
    async def test_skips_already_tracked_artists_as_seeds(
        self, mock_playlist_ids, mock_judge, disc_session
    ):
        """Artists already in TrackedCreators should be skipped as seeds."""
        mock_spotify = AsyncMock()
        mock_spotify.get_playlist_tracks.return_value = [
            PlaylistTrack(id="t1", name="Song", artists=["Top Artist"]),
        ]
        mock_brave = AsyncMock()

        from watcher.jobs.discovery import discover_music
        sent = await discover_music(disc_session, mock_spotify, mock_brave, dry_run=False)

        assert sent == 0
        mock_judge.assert_not_called()

    @patch("watcher.jobs.discovery.get_spotify_seed_playlist_ids", return_value=[])
    async def test_no_playlist_configured(self, mock_playlist_ids, disc_session):
        """Returns 0 immediately when no playlist IDs are configured."""
        mock_spotify = AsyncMock()
        mock_brave = AsyncMock()

        from watcher.jobs.discovery import discover_music
        sent = await discover_music(disc_session, mock_spotify, mock_brave, dry_run=False)

        assert sent == 0
        mock_spotify.get_playlist_tracks.assert_not_called()

    @patch("watcher.jobs.discovery.judge_discovery_candidate")
    @patch("watcher.jobs.discovery.get_spotify_seed_playlist_ids", return_value=["test_playlist"])
    async def test_music_discovery_no_results_when_judge_skips(
        self, mock_playlist_ids, mock_judge, disc_session
    ):
        mock_spotify = AsyncMock()
        mock_spotify.get_playlist_tracks.return_value = [
            PlaylistTrack(id="t1", name="Song", artists=["New Artist"]),
        ]
        mock_brave = AsyncMock()
        mock_brave.search_similar_music.return_value = [
            SearchResult(title="Something", url="https://example.com", snippet="")
        ]

        mock_judge.return_value = JudgeResult(notify=False, reason="Not relevant", best_link="")

        from watcher.jobs.discovery import discover_music
        sent = await discover_music(disc_session, mock_spotify, mock_brave, dry_run=False)

        assert sent == 0


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
    @patch("watcher.jobs.discovery.get_spotify_seed_playlist_ids", return_value=["test_playlist"])
    async def test_dry_run_no_db_writes(
        self, mock_playlist_ids, mock_judge, mock_send, disc_session
    ):
        mock_spotify = AsyncMock()
        mock_spotify.get_playlist_tracks.return_value = [
            PlaylistTrack(id="t1", name="Song", artists=["New Artist"]),
        ]
        mock_brave = AsyncMock()
        mock_brave.search_similar_music.return_value = [
            SearchResult(title="New Sound", url="https://example.com", snippet="")
        ]

        mock_judge.return_value = JudgeResult(
            notify=True, reason="Good", best_link="https://example.com"
        )

        from watcher.jobs.discovery import discover_music
        sent = await discover_music(disc_session, mock_spotify, mock_brave, dry_run=True)

        assert sent == 1
        discovery = disc_session.query(DiscoverySent).all()
        assert len(discovery) == 0
        mock_send.assert_not_called()
