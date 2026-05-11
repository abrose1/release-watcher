import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


load_dotenv()

_config_cache: dict[str, Any] | None = None

_ROOT = Path(__file__).resolve().parent.parent


def _deep_merge_inplace(base: dict[str, Any], override: dict[str, Any]) -> None:
    for key, val in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            _deep_merge_inplace(base[key], val)
        else:
            base[key] = val


def _apply_env_preferences_overrides(prefs: dict[str, Any]) -> None:
    """Optional Railway / shell overrides — comma-separated playlists, SMS name, film taste prose."""
    name = (os.environ.get("SMS_GREETING_NAME") or os.environ.get("SMS_FIRST_NAME") or "").strip()
    if name:
        prefs["sms_first_name"] = name

    pl_raw = os.environ.get("SPOTIFY_SEED_PLAYLIST_IDS") or ""
    if pl_raw.strip():
        prefs["spotify_seed_playlist_ids"] = [
            x.strip() for x in pl_raw.split(",") if x.strip()
        ]

    film_taste = os.environ.get("FILM_TASTE")
    if film_taste:
        prefs["film_taste"] = film_taste.strip()

    gids_raw = os.environ.get("FILM_TMDB_GENRE_IDS") or ""
    if gids_raw.strip():
        prefs["film_tmdb_genre_ids"] = [
            int(x.strip()) for x in gids_raw.split(",") if x.strip().isdigit()
        ]

    qtz = os.environ.get("SMS_QUIET_TIMEZONE")
    if qtz:
        qh = prefs.setdefault("quiet_hours", {})
        if isinstance(qh, dict):
            qh["timezone"] = qtz.strip()


def _load_yaml_config() -> dict[str, Any]:
    config_path = _ROOT / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"config.yaml not found at {config_path}")

    with open(config_path) as f:
        cfg: dict[str, Any] = yaml.safe_load(f) or {}

    override_path = _ROOT / "config.override.yaml"
    if override_path.exists():
        with open(override_path) as f:
            over = yaml.safe_load(f)
        if isinstance(over, dict):
            _deep_merge_inplace(cfg, over)

    prefs = cfg.get("preferences")
    if isinstance(prefs, dict):
        _apply_env_preferences_overrides(prefs)

    return cfg


def get_config() -> dict[str, Any]:
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    _config_cache = _load_yaml_config()
    return _config_cache


def get_preferences() -> dict[str, Any]:
    return get_config().get("preferences", {})


def get_sms_first_name() -> str | None:
    raw = get_preferences().get("sms_first_name") or ""
    stripped = str(raw).strip()
    return stripped or None


def get_quiet_hours_config() -> dict[str, Any]:
    return get_preferences().get("quiet_hours", {})


def get_tv_watchlist() -> list[dict[str, Any]]:
    config = get_config()
    return config.get("watchlist", {}).get("tv", {}).get("shows", [])


def get_film_taste() -> str:
    return get_preferences().get("film_taste", "")


def get_film_genre_ids() -> list[int]:
    return get_preferences().get("film_tmdb_genre_ids", [])


def get_spotify_seed_playlist_ids() -> list[str]:
    return get_preferences().get("spotify_seed_playlist_ids", [])


def get_env(name: str, required: bool = True) -> str | None:
    value = os.environ.get(name)
    if required and not value:
        raise EnvironmentError(f"Required environment variable {name} is not set")
    return value


def reset_config_cache() -> None:
    global _config_cache
    _config_cache = None
