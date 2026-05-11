"""Tests for creator sync — tier thresholds, tier drift, stub mode."""

import pathlib
import sys
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from watcher.models import Base, TrackedCreator, TierChange
from watcher.sync_creators import (
    STUB_CREATORS,
    run,
    sync_from_taste_profile,
    sync_stub_data,
    sync_tv_watchlist,
)

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_TASTE_PROFILE_ROOT = _ROOT / "taste-profile"
if str(_TASTE_PROFILE_ROOT) not in sys.path:
    sys.path.insert(0, str(_TASTE_PROFILE_ROOT))

from models import Base as TasteBase, BookAuthor, MusicArtist, ProfileMetadata  # noqa: E402


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
        assert len(music) == 0
        assert len(books) == 2

    def test_stub_idempotent(self, sync_session):
        sync_stub_data(sync_session)
        sync_stub_data(sync_session)

        creators = sync_session.query(TrackedCreator).all()
        assert len(creators) == len(STUB_CREATORS)

    def test_tier_change_detection(self, sync_session):
        creator = TrackedCreator(
            category="book",
            name="STUB_AUTHOR_1",
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


class TestSyncFromTasteProfileBooks:
    def test_syncs_authors_tiers_and_external_id(self, sync_session, monkeypatch, tmp_path):
        taste_url = f"sqlite:///{tmp_path / 'taste.db'}"
        monkeypatch.setenv("TASTE_PROFILE_DATABASE_URL", taste_url)
        t_engine = create_engine(taste_url)
        TasteBase.metadata.create_all(t_engine)
        t_sess = sessionmaker(bind=t_engine)()
        t_sess.add(
            ProfileMetadata(
                tier1_book_cutoff=1,
                tier2_book_cutoff=2,
            )
        )
        t_sess.add(
            BookAuthor(name="Zed High", rank_score=100.0, google_books_id="gb_zed")
        )
        t_sess.add(BookAuthor(name="Amy Mid", rank_score=50.0, google_books_id=None))
        t_sess.add(BookAuthor(name="Bo Low", rank_score=10.0))
        t_sess.commit()
        t_sess.close()

        sync_from_taste_profile(sync_session)

        by_name = {c.name: c for c in sync_session.query(TrackedCreator).all()}
        assert by_name["Zed High"].tier == 1
        assert by_name["Zed High"].external_id == "gb_zed"
        assert by_name["Zed High"].profile_score_at_sync == 100.0
        assert by_name["Amy Mid"].tier == 2
        assert by_name["Amy Mid"].external_id is None
        assert by_name["Bo Low"].tier == 3

    def test_default_cutoffs_when_metadata_empty(self, sync_session, monkeypatch, tmp_path):
        taste_url = f"sqlite:///{tmp_path / 'taste.db'}"
        monkeypatch.setenv("TASTE_PROFILE_DATABASE_URL", taste_url)
        t_engine = create_engine(taste_url)
        TasteBase.metadata.create_all(t_engine)
        t_sess = sessionmaker(bind=t_engine)()
        for i in range(1, 12):
            t_sess.add(BookAuthor(name=f"A{i:02d}", rank_score=100.0 - i))
        t_sess.commit()
        t_sess.close()

        sync_from_taste_profile(sync_session)

        by_name = {
            c.name: c
            for c in sync_session.query(TrackedCreator).filter_by(category="book").all()
        }
        assert by_name["A01"].tier == 1
        assert by_name["A10"].tier == 1
class TestSyncFromTasteProfileMusic:
    def test_syncs_music_tiers_and_spotify_id(self, sync_session, monkeypatch, tmp_path):
        taste_url = f"sqlite:///{tmp_path / 'taste.db'}"
        monkeypatch.setenv("TASTE_PROFILE_DATABASE_URL", taste_url)
        t_engine = create_engine(taste_url)
        TasteBase.metadata.create_all(t_engine)
        t_sess = sessionmaker(bind=t_engine)()
        t_sess.add(
            ProfileMetadata(
                tier1_music_cutoff=1,
                tier2_music_cutoff=2,
            )
        )
        t_sess.add(MusicArtist(name="Top DJ", listen_score=100.0, spotify_id="spot_top"))
        t_sess.add(MusicArtist(name="Mid Band", listen_score=50.0, spotify_id=None))
        t_sess.add(MusicArtist(name="Low Key", listen_score=10.0))
        t_sess.commit()
        t_sess.close()

        sync_from_taste_profile(sync_session)

        music = {
            c.name: c
            for c in sync_session.query(TrackedCreator).filter_by(category="music").all()
        }
        assert len(music) == 3
        assert music["Top DJ"].tier == 1
        assert music["Top DJ"].external_id == "spot_top"
        assert music["Mid Band"].tier == 2
        assert music["Mid Band"].external_id is None
        assert music["Low Key"].tier == 3

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
