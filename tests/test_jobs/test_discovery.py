"""Integration tests for the weekly discovery job."""

from datetime import datetime, date, timedelta
from unittest.mock import patch, AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from watcher.models import Base, TrackedCreator, DiscoverySent, NotificationQueue
from watcher.judge import JudgeResult
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
    @patch("watcher.jobs.discovery.send_sms_to_subscribers")
    @patch("watcher.jobs.discovery.is_quiet_hours", return_value=False)
    @patch("watcher.jobs.discovery.judge_discovery_candidate")
    async def test_seeds_from_top_tracked_artists(
        self, mock_judge, mock_quiet, mock_send, disc_session
    ):
        """Seeds Brave search from tier 1/2 music TrackedCreators, not playlist artists."""
        mock_brave = AsyncMock()
        mock_brave.search_similar_music.return_value = [
            SearchResult(title="New Artist Debut", url="https://example.com/music", snippet="Sounds great")
        ]
        mock_judge.return_value = JudgeResult(
            notify=True, reason="Similar vibe", best_link="https://example.com/music"
        )

        from watcher.jobs.discovery import discover_music
        sent = await discover_music(disc_session, mock_brave, dry_run=False)

        assert sent == 1
        # The DB fixture has "Top Artist" (tier=1) — verify it was the seed
        mock_brave.search_similar_music.assert_called_once_with("Top Artist")
        discovery = disc_session.query(DiscoverySent).filter_by(category="music").all()
        assert len(discovery) == 1

    async def test_no_music_creators_returns_zero(self, disc_session):
        """Returns 0 when no tier 1/2 music creators exist in the DB."""
        disc_session.query(TrackedCreator).filter_by(category="music").delete()
        disc_session.commit()

        mock_brave = AsyncMock()

        from watcher.jobs.discovery import discover_music
        sent = await discover_music(disc_session, mock_brave, dry_run=False)

        assert sent == 0
        mock_brave.search_similar_music.assert_not_called()

    @patch("watcher.jobs.discovery.judge_discovery_candidate")
    async def test_skips_tier_3_music_creators(self, mock_judge, disc_session):
        """Tier 3 (and above) music creators are excluded from seeding."""
        disc_session.query(TrackedCreator).filter_by(category="music").delete()
        disc_session.add(TrackedCreator(
            category="music", name="Tier3 Artist", tier=3, profile_score_at_sync=50.0
        ))
        disc_session.commit()

        mock_brave = AsyncMock()

        from watcher.jobs.discovery import discover_music
        sent = await discover_music(disc_session, mock_brave, dry_run=False)

        assert sent == 0
        mock_judge.assert_not_called()

    @patch("watcher.jobs.discovery.judge_discovery_candidate")
    async def test_judge_decline_returns_zero(self, mock_judge, disc_session):
        """Returns 0 when the judge declines every candidate."""
        mock_brave = AsyncMock()
        mock_brave.search_similar_music.return_value = [
            SearchResult(title="Something", url="https://example.com", snippet="")
        ]
        mock_judge.return_value = JudgeResult(notify=False, reason="Not relevant", best_link="")

        from watcher.jobs.discovery import discover_music
        sent = await discover_music(disc_session, mock_brave, dry_run=False)

        assert sent == 0

    @patch("watcher.jobs.discovery.send_sms_to_subscribers")
    @patch("watcher.jobs.discovery.is_quiet_hours", return_value=False)
    @patch("watcher.jobs.discovery.judge_discovery_candidate")
    async def test_already_sent_skips_to_next_seed(
        self, mock_judge, mock_quiet, mock_send, disc_session
    ):
        """When the top seed was already sent today, the next ranked artist is tried."""
        second = TrackedCreator(
            category="music", name="Second Artist", tier=1, profile_score_at_sync=80.0
        )
        disc_session.add(second)
        disc_session.add(DiscoverySent(
            external_id=f"music_disc_Top Artist_{date.today().isoformat()}",
            category="music",
            title="Already Sent",
            creator_name="Top Artist",
            sent_at=datetime.now().replace(tzinfo=None),
        ))
        disc_session.commit()

        mock_brave = AsyncMock()
        mock_brave.search_similar_music.return_value = [
            SearchResult(title="New Sound", url="https://example.com/music2", snippet="")
        ]
        mock_judge.return_value = JudgeResult(
            notify=True, reason="Good", best_link="https://example.com/music2"
        )

        from watcher.jobs.discovery import discover_music
        sent = await discover_music(disc_session, mock_brave, dry_run=False)

        assert sent == 1
        # Top Artist was already sent — Second Artist (score=80) should be the seed
        mock_brave.search_similar_music.assert_called_once_with("Second Artist")


class TestFilmDiscovery:
    @patch("watcher.jobs.discovery.send_sms_to_subscribers")
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
    @patch("watcher.jobs.discovery.send_sms_to_subscribers")
    @patch("watcher.jobs.discovery.is_quiet_hours", return_value=False)
    @patch("watcher.jobs.discovery.judge_discovery_candidate")
    async def test_tv_discovery_flow(self, mock_judge, mock_quiet, mock_send, disc_session):
        mock_tmdb = AsyncMock()
        recent_date = (date.today() - timedelta(days=30)).isoformat()
        mock_tmdb.get_similar_series.return_value = [
            TVShow(id=55555, name="Similar Series", first_air_date=recent_date,
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
    @patch("watcher.jobs.discovery.send_sms_to_subscribers")
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
    @patch("watcher.jobs.discovery.send_sms_to_subscribers")
    @patch("watcher.jobs.discovery.judge_discovery_candidate")
    async def test_dry_run_no_db_writes(self, mock_judge, mock_send, disc_session):
        """Dry-run mode: judge approves but nothing is written to DB and no SMS is sent."""
        mock_brave = AsyncMock()
        mock_brave.search_similar_music.return_value = [
            SearchResult(title="New Sound", url="https://example.com", snippet="")
        ]
        mock_judge.return_value = JudgeResult(
            notify=True, reason="Good", best_link="https://example.com"
        )

        from watcher.jobs.discovery import discover_music
        sent = await discover_music(disc_session, mock_brave, dry_run=True)

        assert sent == 1
        assert disc_session.query(DiscoverySent).count() == 0
        mock_send.assert_not_called()
