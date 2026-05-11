"""Tests for SQLAlchemy models — schema correctness and FK constraints."""

from datetime import datetime, date, timezone

from watcher.models import (
    TrackedCreator, Release, NotificationQueue, DiscoverySent,
    UserOverride, TierChange,
)


class TestTrackedCreator:
    def test_create_creator(self, db_session):
        creator = TrackedCreator(
            category="music",
            name="Test Artist",
            tier=1,
            external_id="spotify_123",
            profile_score_at_sync=95.0,
        )
        db_session.add(creator)
        db_session.commit()

        result = db_session.query(TrackedCreator).first()
        assert result.name == "Test Artist"
        assert result.category == "music"
        assert result.tier == 1
        assert result.external_id == "spotify_123"
        assert result.profile_score_at_sync == 95.0

    def test_creator_relationships(self, db_session):
        creator = TrackedCreator(
            category="book", name="Test Author", tier=2,
        )
        db_session.add(creator)
        db_session.commit()

        release = Release(
            tracked_creator_id=creator.id,
            external_release_id="book_123",
            title="New Novel",
            type="novel",
        )
        db_session.add(release)
        db_session.commit()

        assert len(creator.releases) == 1
        assert creator.releases[0].title == "New Novel"


class TestRelease:
    def test_create_release(self, db_session):
        creator = TrackedCreator(category="music", name="Artist", tier=1)
        db_session.add(creator)
        db_session.commit()

        release = Release(
            tracked_creator_id=creator.id,
            external_release_id="album_456",
            title="New Album",
            type="album",
            release_date=date(2026, 4, 1),
            source_url="https://example.com",
        )
        db_session.add(release)
        db_session.commit()

        result = db_session.query(Release).first()
        assert result.title == "New Album"
        assert result.type == "album"
        assert result.tracked_creator.name == "Artist"

    def test_announcement_hash(self, db_session):
        creator = TrackedCreator(category="music", name="Artist", tier=1)
        db_session.add(creator)
        db_session.commit()

        release = Release(
            tracked_creator_id=creator.id,
            external_release_id="ann_abc123",
            title="Announcement",
            type="announcement",
            announcement_hash="abc123def456",
        )
        db_session.add(release)
        db_session.commit()

        result = db_session.query(Release).filter_by(announcement_hash="abc123def456").first()
        assert result is not None
        assert result.title == "Announcement"


class TestNotificationQueue:
    def test_queue_with_release(self, db_session):
        creator = TrackedCreator(category="music", name="Artist", tier=1)
        db_session.add(creator)
        db_session.commit()

        release = Release(
            tracked_creator_id=creator.id,
            external_release_id="album_1",
            title="Album",
        )
        db_session.add(release)
        db_session.commit()

        queue_item = NotificationQueue(
            release_id=release.id,
            message_text="Test message",
            queued_at=datetime.now(timezone.utc).replace(tzinfo=None),
            send_after=datetime.now(timezone.utc).replace(tzinfo=None),
            priority=10,
        )
        db_session.add(queue_item)
        db_session.commit()

        result = db_session.query(NotificationQueue).first()
        assert result.message_text == "Test message"
        assert result.release_id == release.id
        assert result.discovery_sent_id is None

    def test_queue_with_discovery(self, db_session):
        discovery = DiscoverySent(
            external_id="disc_1",
            category="music",
            title="Discovery",
            creator_name="New Artist",
            sent_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db_session.add(discovery)
        db_session.commit()

        queue_item = NotificationQueue(
            discovery_sent_id=discovery.id,
            message_text="Discovery message",
            queued_at=datetime.now(timezone.utc).replace(tzinfo=None),
            send_after=datetime.now(timezone.utc).replace(tzinfo=None),
            priority=50,
        )
        db_session.add(queue_item)
        db_session.commit()

        result = db_session.query(NotificationQueue).first()
        assert result.discovery_sent_id == discovery.id
        assert result.release_id is None


class TestDiscoverySent:
    def test_create_discovery(self, db_session):
        discovery = DiscoverySent(
            external_id="movie_123",
            category="film",
            title="Test Movie",
            creator_name="Director",
            sent_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db_session.add(discovery)
        db_session.commit()

        result = db_session.query(DiscoverySent).first()
        assert result.title == "Test Movie"
        assert result.category == "film"


class TestUserOverride:
    def test_mute_override(self, db_session):
        creator = TrackedCreator(category="music", name="Artist", tier=1)
        db_session.add(creator)
        db_session.commit()

        override = UserOverride(
            tracked_creator_id=creator.id,
            action="mute",
            expires_at=None,
        )
        db_session.add(override)
        db_session.commit()

        result = db_session.query(UserOverride).first()
        assert result.action == "mute"
        assert result.tracked_creator.name == "Artist"


class TestTierChange:
    def test_tier_change_logging(self, db_session):
        creator = TrackedCreator(category="music", name="Artist", tier=2)
        db_session.add(creator)
        db_session.commit()

        change = TierChange(
            tracked_creator_id=creator.id,
            old_tier=1,
            new_tier=2,
            changed_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )
        db_session.add(change)
        db_session.commit()

        result = db_session.query(TierChange).first()
        assert result.old_tier == 1
        assert result.new_tier == 2
