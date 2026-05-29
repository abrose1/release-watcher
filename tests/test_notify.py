"""Tests for notification formatting, quiet hours, and queue flushing."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest
from freezegun import freeze_time

from watcher.notify import (
    format_watchlist_sms, format_discovery_sms,
    is_quiet_hours, next_send_after, flush_queue, send_sms,
)
from watcher.models import NotificationQueue, Base

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture(autouse=True)
def _fixed_sms_opening(monkeypatch):
    """Deterministic greetings; production uses varied openers."""
    monkeypatch.setattr("watcher.notify._pick_sms_opening", lambda: "Hey,")


class TestFormatWatchlistSMS:
    def test_basic_format(self):
        msg = format_watchlist_sms(
            creator_name="Artist",
            category="music",
            title="Album Title",
            release_type="album",
            link="https://example.com",
        )
        assert msg.startswith("Hey,\n")
        assert "New Album" in msg
        assert "Artist" in msg
        assert "Album Title" in msg
        assert "https://example.com" in msg

    def test_under_160_chars(self):
        msg = format_watchlist_sms(
            creator_name="Short",
            category="music",
            title="Short",
            release_type="album",
            link="https://x.co",
        )
        assert len(msg) <= 160

    def test_truncates_long_title(self):
        long_title = "A" * 200
        msg = format_watchlist_sms(
            creator_name="Artist",
            category="music",
            title=long_title,
            release_type="album",
            link="https://example.com/very-long-path",
        )
        assert len(msg) <= 160
        assert "https://example.com/very-long-path" in msg

    def test_preserves_link(self):
        link = "https://example.com/article/12345"
        msg = format_watchlist_sms(
            creator_name="A" * 50,
            category="music",
            title="T" * 100,
            release_type="album",
            link=link,
        )
        assert link in msg

    def test_announcement_type(self):
        msg = format_watchlist_sms(
            creator_name="Author",
            category="book",
            title="New Book",
            release_type="announcement",
            link="https://example.com",
        )
        assert "Announced" in msg

    def test_season_type(self):
        msg = format_watchlist_sms(
            creator_name="Show",
            category="tv",
            title="Season 3",
            release_type="season",
            link="https://example.com",
        )
        assert "New Season" in msg


class TestFormatDiscoverySMS:
    def test_basic_format(self):
        msg = format_discovery_sms(
            category="music",
            title="New Song",
            creator_name="New Artist",
            reason="Similar atmospheric style",
            link="https://example.com",
        )
        assert msg.startswith("Hey,\n")
        assert "Rec" in msg
        assert "Music" in msg
        assert "New Song" in msg

    def test_drops_reason_if_over_160(self):
        long_reason = "R" * 100
        msg = format_discovery_sms(
            category="music",
            title="Song Title",
            creator_name="Artist Name",
            reason=long_reason,
            link="https://example.com/article",
        )
        assert len(msg) <= 160
        if long_reason not in msg:
            assert "https://example.com/article" in msg

    def test_hard_cap_160(self):
        msg = format_discovery_sms(
            category="film",
            title="T" * 80,
            creator_name="C" * 80,
            reason="",
            link="https://example.com",
        )
        assert len(msg) <= 160


class TestQuietHours:
    @freeze_time("2026-04-16 06:30:00")
    @patch("watcher.notify.get_quiet_hours_config")
    def test_is_quiet_hours_during(self, mock_config):
        mock_config.return_value = {
            "start": "22:00",
            "end": "08:00",
            "timezone": "UTC",
            "behavior": "queue",
            "max_batch": 3,
        }
        assert is_quiet_hours() is True

    @freeze_time("2026-04-15 12:00:00")
    @patch("watcher.notify.get_quiet_hours_config")
    def test_is_not_quiet_hours(self, mock_config):
        mock_config.return_value = {
            "start": "22:00",
            "end": "08:00",
            "timezone": "UTC",
            "behavior": "queue",
            "max_batch": 3,
        }
        assert is_quiet_hours() is False

    @patch("watcher.notify.get_quiet_hours_config")
    def test_no_config_returns_false(self, mock_config):
        mock_config.return_value = {}
        assert is_quiet_hours() is False

    @freeze_time("2026-04-15 23:00:00", tz_offset=-7)
    @patch("watcher.notify.get_quiet_hours_config")
    def test_next_send_after(self, mock_config):
        mock_config.return_value = {
            "start": "22:00",
            "end": "08:00",
            "timezone": "America/Los_Angeles",
            "behavior": "queue",
            "max_batch": 3,
        }
        result = next_send_after()
        assert result.hour == 15 or result.hour == 8


class TestFlushQueue:
    @patch("watcher.notify.get_session_factory")
    @patch("watcher.notify.send_sms")
    @patch("watcher.notify.get_quiet_hours_config")
    def test_flush_sends_pending(self, mock_config, mock_send, mock_factory):
        mock_config.return_value = {"max_batch": 3}

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        queue_item = NotificationQueue(
            message_text="Test message",
            queued_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1),
            send_after=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=30),
            priority=10,
        )
        session.add(queue_item)
        session.commit()

        mock_factory.return_value = lambda: session
        # Need to mock the factory to return our session
        mock_factory.return_value = Session

        flush_queue(dry_run=False)
        mock_send.assert_called_once_with("Test message", dry_run=False)

    @patch("watcher.notify.get_session_factory")
    @patch("watcher.notify.send_sms")
    @patch("watcher.notify.get_quiet_hours_config")
    def test_flush_respects_max_batch(self, mock_config, mock_send, mock_factory):
        mock_config.return_value = {"max_batch": 2}

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        for i in range(5):
            queue_item = NotificationQueue(
                message_text=f"Message {i}",
                queued_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1),
                send_after=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=30),
                priority=i * 10,
            )
            session.add(queue_item)
        session.commit()

        mock_factory.return_value = Session

        flush_queue(dry_run=False)
        assert mock_send.call_count == 2

    @patch("watcher.notify.get_session_factory")
    @patch("watcher.notify.send_sms")
    @patch("watcher.notify.get_quiet_hours_config")
    def test_flush_dry_run(self, mock_config, mock_send, mock_factory):
        mock_config.return_value = {"max_batch": 3}

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        session = Session()

        queue_item = NotificationQueue(
            message_text="Test",
            queued_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1),
            send_after=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=30),
            priority=10,
        )
        session.add(queue_item)
        session.commit()

        mock_factory.return_value = Session

        flush_queue(dry_run=True)
        mock_send.assert_called_once_with("Test", dry_run=True)


class TestSendSMS:
    @patch("watcher.notify._get_twilio_client")
    @patch("watcher.notify.get_env")
    def test_send_sms_calls_twilio(self, mock_env, mock_twilio):
        def env_side_effect(name, required=True):
            values = {
                "TWILIO_FROM_NUMBER": "+1111111111",
                "YOUR_PHONE_NUMBER": "+2222222222",
                "TWILIO_MESSAGING_SERVICE_SID": None,
            }
            if name in values:
                return values[name]
            if required:
                raise KeyError(name)
            return None

        mock_env.side_effect = env_side_effect
        mock_client = MagicMock()
        mock_twilio.return_value = mock_client

        send_sms("Hello", dry_run=False)

        mock_client.messages.create.assert_called_once_with(
            body="Hello",
            from_="+1111111111",
            to="+2222222222",
        )

    @patch("watcher.notify._get_twilio_client")
    @patch("watcher.notify.get_env")
    def test_send_sms_prefers_messaging_service(self, mock_env, mock_twilio):
        def env_side_effect(name, required=True):
            values = {
                "YOUR_PHONE_NUMBER": "+2222222222",
                "TWILIO_MESSAGING_SERVICE_SID": "MG123",
            }
            if name in values:
                return values[name]
            if name == "TWILIO_FROM_NUMBER" and not required:
                return None
            if required:
                raise KeyError(name)
            return None

        mock_env.side_effect = env_side_effect
        mock_client = MagicMock()
        mock_twilio.return_value = mock_client

        send_sms("Hello", dry_run=False)

        mock_client.messages.create.assert_called_once_with(
            body="Hello",
            messaging_service_sid="MG123",
            to="+2222222222",
        )

    def test_send_sms_dry_run_no_twilio(self):
        send_sms("Hello", dry_run=True)
