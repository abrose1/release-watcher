"""Tests for notification formatting, quiet hours, and queue flushing."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest
from freezegun import freeze_time

from watcher.notify import (
    format_watchlist_message, format_discovery_message,
    is_quiet_hours, next_send_after, flush_queue, send_sms,
    get_opted_in_numbers,
)
from watcher.models import NotificationQueue, Base

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class TestFormatWatchlistMessage:
    def test_basic_format(self):
        msg = format_watchlist_message(
            creator_name="Artist",
            category="music",
            title="Album Title",
            release_type="album",
            link="https://example.com",
        )
        assert "New album from Artist" in msg
        assert "Album Title" in msg
        assert "https://example.com" in msg

    def test_announcement_type(self):
        msg = format_watchlist_message(
            creator_name="Author",
            category="book",
            title="New Book",
            release_type="announcement",
            link="https://example.com",
        )
        assert "New announcement from Author" in msg

    def test_season_type(self):
        msg = format_watchlist_message(
            creator_name="Show",
            category="tv",
            title="Season 3",
            release_type="season",
            link="https://example.com",
        )
        assert "New season from Show" in msg

    def test_link_always_present(self):
        link = "https://example.com/article/12345"
        msg = format_watchlist_message(
            creator_name="Artist",
            category="music",
            title="Title",
            release_type="album",
            link=link,
        )
        assert link in msg

    def test_unknown_release_type_falls_back(self):
        msg = format_watchlist_message(
            creator_name="Artist",
            category="music",
            title="Something",
            release_type="compilation",
            link="https://example.com",
        )
        assert "New release from Artist" in msg


class TestFormatDiscoveryMessage:
    def test_basic_format(self):
        msg = format_discovery_message(
            category="music",
            title="New Song",
            creator_name="New Artist",
            reason="Similar atmospheric style",
            link="https://example.com",
        )
        assert "Rec" in msg
        assert "Music" in msg
        assert "New Song" in msg
        assert "Similar atmospheric style" in msg

    def test_reason_omitted_when_empty(self):
        msg = format_discovery_message(
            category="music",
            title="Song",
            creator_name="Artist",
            reason="",
            link="https://example.com",
        )
        lines = msg.strip().splitlines()
        assert "https://example.com" in lines[-1]

    def test_link_always_present(self):
        msg = format_discovery_message(
            category="film",
            title="Movie",
            creator_name="Various",
            reason="",
            link="https://example.com/film",
        )
        assert "https://example.com/film" in msg


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
    @patch("watcher.notify.get_opted_in_numbers", return_value=["+15550001111"])
    @patch("watcher.notify.get_quiet_hours_config")
    def test_flush_sends_pending(self, mock_config, mock_numbers, mock_send, mock_factory):
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

        mock_factory.return_value = Session

        flush_queue(dry_run=False)
        mock_send.assert_called_once_with("Test message", to_number="+15550001111", dry_run=False)

    @patch("watcher.notify.get_session_factory")
    @patch("watcher.notify.send_sms")
    @patch("watcher.notify.get_opted_in_numbers", return_value=["+15550001111"])
    @patch("watcher.notify.get_quiet_hours_config")
    def test_flush_respects_max_batch(self, mock_config, mock_numbers, mock_send, mock_factory):
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
        # 2 messages × 1 subscriber = 2 send_sms calls
        assert mock_send.call_count == 2

    @patch("watcher.notify.get_session_factory")
    @patch("watcher.notify.send_sms")
    @patch("watcher.notify.get_opted_in_numbers", return_value=["+15550001111"])
    @patch("watcher.notify.get_quiet_hours_config")
    def test_flush_dry_run(self, mock_config, mock_numbers, mock_send, mock_factory):
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
        mock_send.assert_called_once_with("Test", to_number="+15550001111", dry_run=True)


class TestSendSms:
    @patch("watcher.notify._get_twilio_client")
    @patch("watcher.notify.get_env")
    def test_send_sms_calls_twilio(self, mock_env, mock_twilio):
        def env_side_effect(name, required=True):
            values = {"TWILIO_FROM_NUMBER": "+15559829514"}
            if name in values:
                return values[name]
            if required:
                raise KeyError(name)
            return None

        mock_env.side_effect = env_side_effect
        mock_client = MagicMock()
        mock_twilio.return_value = mock_client

        send_sms("Hello", to_number="+16109520020", dry_run=False)

        mock_client.messages.create.assert_called_once_with(
            body="Hello",
            to="+16109520020",
            from_="+15559829514",
        )

    def test_send_sms_dry_run_no_twilio(self):
        send_sms("Hello", to_number="+16109520020", dry_run=True)
