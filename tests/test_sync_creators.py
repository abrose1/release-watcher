"""Tests for creator sync — tier thresholds, tier drift, stub mode."""

from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from watcher.models import Base, TrackedCreator, TierChange
from watcher.sync_creators import sync_stub_data, sync_tv_watchlist, run, STUB_CREATORS


@pytest.fixture
def sync_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestSyncStubData:
    def test_creates_stub_creators(self, sync_session):
        sync_stub_data(sync_session)

        creators = sync_session.query(TrackedCreator).all()
        assert len(creators) == len(STUB_CREATORS)

    def test_stub_creators_have_negative_score(self, sync_session):
        sync_stub_data(sync_session)

        creators = sync_session.query(TrackedCreator).all()
        for creator in creators:
            assert creator.profile_score_at_sync == -1.0

    def test_stub_creators_categories(self, sync_session):
        sync_stub_data(sync_session)

        music = sync_session.query(TrackedCreator).filter_by(category="music").all()
        books = sync_session.query(TrackedCreator).filter_by(category="book").all()
        assert len(music) == 2
        assert len(books) == 2

    def test_stub_idempotent(self, sync_session):
        sync_stub_data(sync_session)
        sync_stub_data(sync_session)

        creators = sync_session.query(TrackedCreator).all()
        assert len(creators) == len(STUB_CREATORS)

    def test_tier_change_detection(self, sync_session):
        creator = TrackedCreator(
            category="music",
            name="STUB_ARTIST_1",
            tier=2,
            profile_score_at_sync=-1.0,
        )
        sync_session.add(creator)
        sync_session.commit()

        sync_stub_data(sync_session)

        changes = sync_session.query(TierChange).all()
        assert len(changes) == 1
        assert changes[0].old_tier == 2
        assert changes[0].new_tier == 1

    def test_no_tier_change_when_same(self, sync_session):
        sync_stub_data(sync_session)

        sync_stub_data(sync_session)

        changes = sync_session.query(TierChange).all()
        assert len(changes) == 0


class TestSyncTVWatchlist:
    @patch("watcher.sync_creators.get_tv_watchlist")
    def test_syncs_tv_shows(self, mock_watchlist, sync_session):
        mock_watchlist.return_value = [
            {"name": "Test Show", "tier": 1, "tmdb_id": 12345},
            {"name": "Another Show", "tier": 2, "tmdb_id": 67890},
        ]

        sync_tv_watchlist(sync_session)

        tv_creators = sync_session.query(TrackedCreator).filter_by(category="tv").all()
        assert len(tv_creators) == 2
        assert tv_creators[0].name == "Test Show"
        assert tv_creators[0].tier == 1
        assert tv_creators[0].external_id == "12345"

    @patch("watcher.sync_creators.get_tv_watchlist")
    def test_tv_sync_idempotent(self, mock_watchlist, sync_session):
        mock_watchlist.return_value = [
            {"name": "Test Show", "tier": 1, "tmdb_id": 12345},
        ]

        sync_tv_watchlist(sync_session)
        sync_tv_watchlist(sync_session)

        tv_creators = sync_session.query(TrackedCreator).filter_by(category="tv").all()
        assert len(tv_creators) == 1

    @patch("watcher.sync_creators.get_tv_watchlist")
    def test_tv_tier_change(self, mock_watchlist, sync_session):
        creator = TrackedCreator(
            category="tv",
            name="Test Show",
            tier=2,
            external_id="12345",
        )
        sync_session.add(creator)
        sync_session.commit()

        mock_watchlist.return_value = [
            {"name": "Test Show", "tier": 1, "tmdb_id": 12345},
        ]

        sync_tv_watchlist(sync_session)

        changes = sync_session.query(TierChange).all()
        assert len(changes) == 1
        assert changes[0].old_tier == 2
        assert changes[0].new_tier == 1

    @patch("watcher.sync_creators.get_tv_watchlist")
    def test_empty_watchlist(self, mock_watchlist, sync_session):
        mock_watchlist.return_value = []
        sync_tv_watchlist(sync_session)

        tv_creators = sync_session.query(TrackedCreator).filter_by(category="tv").all()
        assert len(tv_creators) == 0


class TestRunFunction:
    @patch("watcher.sync_creators.sync_tv_watchlist")
    @patch("watcher.sync_creators.sync_stub_data")
    @patch("watcher.sync_creators.get_session_factory")
    def test_run_with_stub(self, mock_factory, mock_sync_stub, mock_sync_tv):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        mock_factory.return_value = Session

        run(stub=True)

        mock_sync_stub.assert_called_once()
        mock_sync_tv.assert_called_once()

    @patch("watcher.sync_creators.sync_tv_watchlist")
    @patch("watcher.sync_creators.sync_from_taste_profile")
    @patch("watcher.sync_creators.get_session_factory")
    def test_run_without_stub(self, mock_factory, mock_sync_profile, mock_sync_tv):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        mock_factory.return_value = Session

        run(stub=False)

        mock_sync_profile.assert_called_once()
        mock_sync_tv.assert_called_once()
