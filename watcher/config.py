import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


load_dotenv()

_config_cache: dict[str, Any] | None = None


def get_config() -> dict[str, Any]:
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    config_path = Path(__file__).parent.parent / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"config.yaml not found at {config_path}")

    with open(config_path) as f:
        _config_cache = yaml.safe_load(f)

    return _config_cache


def get_preferences() -> dict[str, Any]:
    return get_config().get("preferences", {})


def get_quiet_hours_config() -> dict[str, Any]:
    return get_preferences().get("quiet_hours", {})


def get_tv_watchlist() -> list[dict[str, Any]]:
    config = get_config()
    return config.get("watchlist", {}).get("tv", {}).get("shows", [])


def get_film_taste() -> str:
    return get_preferences().get("film_taste", "")


def get_film_genre_ids() -> list[int]:
    return get_preferences().get("film_tmdb_genre_ids", [])


def get_env(name: str, required: bool = True) -> str | None:
    value = os.environ.get(name)
    if required and not value:
        raise EnvironmentError(f"Required environment variable {name} is not set")
    return value


def reset_config_cache():
    global _config_cache
    _config_cache = None
