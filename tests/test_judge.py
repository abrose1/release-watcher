"""Tests for Anthropic judge — mocked SDK responses."""

import json
from unittest.mock import patch, MagicMock

import pytest

from watcher.judge import (
    judge_watchlist_hit, judge_discovery_candidate, judge_sms_reply,
    JudgeResult, SMSCommand, JudgeError,
)
from tests.fixtures import MOCK_JUDGE_NOTIFY, MOCK_JUDGE_SKIP


def _mock_anthropic_response(content: dict) -> MagicMock:
    """Create a mock Anthropic response."""
    mock_response = MagicMock()
    mock_content_block = MagicMock()
    mock_content_block.text = json.dumps(content)
    mock_response.content = [mock_content_block]
    return mock_response


class TestJudgeWatchlistHit:
    @patch("watcher.judge._get_client")
    def test_notify_true(self, mock_client_factory):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_anthropic_response(MOCK_JUDGE_NOTIFY)
        mock_client_factory.return_value = mock_client

        result = judge_watchlist_hit(
            creator={"name": "Test Artist A", "tier": 1, "category": "music"},
            release_metadata={"title": "New Album", "type": "album", "date": "2026-04-01"},
            search_results=[{"title": "Review", "url": "https://example.com", "snippet": "Great album"}],
        )

        assert isinstance(result, JudgeResult)
        assert result.notify is True
        assert result.reason == "Test reason"
        assert result.best_link == "https://example.com/review"

    @patch("watcher.judge._get_client")
    def test_notify_false_remaster(self, mock_client_factory):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_anthropic_response(MOCK_JUDGE_SKIP)
        mock_client_factory.return_value = mock_client

        result = judge_watchlist_hit(
            creator={"name": "Test Artist A", "tier": 1, "category": "music"},
            release_metadata={"title": "Album (Remastered)", "type": "album", "date": "2026-04-01"},
            search_results=[],
        )

        assert result.notify is False
        assert "genuine" in result.reason.lower() or "not" in result.reason.lower()

    @patch("watcher.judge._get_client")
    def test_handles_code_block_response(self, mock_client_factory):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_content_block = MagicMock()
        mock_content_block.text = '```json\n{"notify": true, "reason": "Genuine release", "best_link": "https://example.com"}\n```'
        mock_response.content = [mock_content_block]
        mock_client.messages.create.return_value = mock_response
        mock_client_factory.return_value = mock_client

        result = judge_watchlist_hit(
            creator={"name": "Artist", "tier": 1, "category": "music"},
            release_metadata={"title": "Album", "type": "album", "date": "2026-04-01"},
            search_results=[],
        )

        assert result.notify is True


class TestJudgeDiscoveryCandidate:
    @patch("watcher.judge._get_client")
    def test_discovery_notify(self, mock_client_factory):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_anthropic_response({
            "notify": True,
            "reason": "Similar atmospheric style to user's favorites",
            "best_link": "https://example.com/review",
        })
        mock_client_factory.return_value = mock_client

        result = judge_discovery_candidate(
            candidate={"title": "New Album", "creator": "New Artist", "category": "music", "description": ""},
            taste_profile_slice={"top_creators": ["Test Artist A"], "film_taste": ""},
            search_results=[{"title": "Review", "url": "https://example.com/review", "snippet": "Great"}],
        )

        assert result.notify is True
        assert "review score" not in result.reason.lower()
        assert "star rating" not in result.reason.lower()

    @patch("watcher.judge._get_client")
    def test_discovery_skip(self, mock_client_factory):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_anthropic_response(MOCK_JUDGE_SKIP)
        mock_client_factory.return_value = mock_client

        result = judge_discovery_candidate(
            candidate={"title": "Pop Album", "creator": "Pop Star", "category": "music", "description": ""},
            taste_profile_slice={"top_creators": ["Test Artist A"], "film_taste": ""},
            search_results=[],
        )

        assert result.notify is False

    @patch("watcher.judge._get_client")
    def test_discovery_prompt_no_review_scores(self, mock_client_factory):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_anthropic_response(MOCK_JUDGE_NOTIFY)
        mock_client_factory.return_value = mock_client

        judge_discovery_candidate(
            candidate={"title": "Test", "creator": "Artist", "category": "music", "description": ""},
            taste_profile_slice={"top_creators": [], "film_taste": ""},
            search_results=[],
        )

        call_args = mock_client.messages.create.call_args
        prompt = call_args[1]["messages"][0]["content"]
        assert "Do NOT cite review scores" in prompt


class TestJudgeSMSReply:
    @patch("watcher.judge._get_client")
    def test_mute_command(self, mock_client_factory):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_anthropic_response({
            "action": "mute",
            "creator_name": "Artist Name",
            "duration_days": 30,
        })
        mock_client_factory.return_value = mock_client

        result = judge_sms_reply(
            "mute Artist Name 30 days",
            [{"creator": "Artist Name", "title": "Album", "category": "music"}],
        )

        assert isinstance(result, SMSCommand)
        assert result.action == "mute"
        assert result.creator_name == "Artist Name"
        assert result.duration_days == 30

    @patch("watcher.judge._get_client")
    def test_unknown_command(self, mock_client_factory):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_content_block = MagicMock()
        mock_content_block.text = "invalid json"
        mock_response.content = [mock_content_block]
        mock_client.messages.create.return_value = mock_response
        mock_client_factory.return_value = mock_client

        result = judge_sms_reply("gibberish", [])

        assert result.action == "unknown"
        assert result.creator_name is None
