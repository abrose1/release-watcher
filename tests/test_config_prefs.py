"""Preferences loading — env overrides atop config.yaml + optional merge file."""

import pytest

import watcher.config as config


@pytest.fixture(autouse=True)
def _clear_cfg_cache(request):
    config.reset_config_cache()
    yield
    config.reset_config_cache()


def test_spotify_env_override_comma(monkeypatch):
    monkeypatch.setenv("SPOTIFY_SEED_PLAYLIST_IDS", "abc, ,def ")
    monkeypatch.delenv("SMS_GREETING_NAME", raising=False)
    monkeypatch.delenv("SMS_FIRST_NAME", raising=False)
    assert config.get_spotify_seed_playlist_ids() == ["abc", "def"]


def test_sms_greeting_env_override(monkeypatch):
    monkeypatch.setenv("SMS_GREETING_NAME", "  Taylor  ")
    assert config.get_sms_first_name() == "Taylor"


def test_film_genre_env_override(monkeypatch):
    monkeypatch.setenv("FILM_TMDB_GENRE_IDS", "1, ,99")
    assert config.get_film_genre_ids() == [1, 99]


def test_quiet_hours_timezone_env_override(monkeypatch):
    monkeypatch.setenv("SMS_QUIET_TIMEZONE", "Atlantic/Reykjavik")
    qc = config.get_quiet_hours_config()
    assert qc.get("timezone") == "Atlantic/Reykjavik"
