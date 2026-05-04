"""TMDB API client for TV and movie data."""

from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from watcher.config import get_env


class TMDBError(Exception):
    pass


@dataclass
class TVSeason:
    show_id: int
    season_number: int
    name: str
    air_date: str | None
    overview: str


@dataclass
class Movie:
    id: int
    title: str
    release_date: str
    overview: str
    genre_ids: list[int]


@dataclass
class TVShow:
    id: int
    name: str
    first_air_date: str | None
    overview: str


class TMDBClient:
    """TMDB API client for TV and movie lookups."""

    BASE_URL = "https://api.themoviedb.org/3"
    MAX_RETRIES = 3

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or get_env("TMDB_API_KEY")

    async def _request(self, path: str, params: dict | None = None) -> Any:
        """Make an authenticated request with retry logic."""
        request_params = {"api_key": self.api_key}
        if params:
            request_params.update(params)

        for attempt in range(self.MAX_RETRIES):
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.BASE_URL}{path}",
                    params=request_params,
                )
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 2 ** attempt))
                    import asyncio
                    await asyncio.sleep(retry_after)
                    continue
                if resp.status_code != 200:
                    raise TMDBError(f"TMDB API error {resp.status_code}: {resp.text}")
                return resp.json()

        raise TMDBError("Max retries exceeded")

    async def get_tv_season_updates(self, tmdb_id: int, after_date: date) -> list[TVSeason]:
        """Get new seasons for a TV show announced or released after the given date."""
        data = await self._request(f"/tv/{tmdb_id}")
        seasons = []
        for season in data.get("seasons", []):
            air_date = season.get("air_date")
            if air_date and air_date >= after_date.isoformat():
                seasons.append(TVSeason(
                    show_id=tmdb_id,
                    season_number=season["season_number"],
                    name=season.get("name", f"Season {season['season_number']}"),
                    air_date=air_date,
                    overview=season.get("overview", ""),
                ))
        return seasons

    async def get_upcoming_movies(self, genre_ids: list[int], after_date: date) -> list[Movie]:
        """Get upcoming movies matching genre IDs released after the given date."""
        data = await self._request(
            "/discover/movie",
            params={
                "with_genres": ",".join(str(g) for g in genre_ids),
                "primary_release_date.gte": after_date.isoformat(),
                "sort_by": "primary_release_date.asc",
                "page": 1,
            },
        )
        movies = []
        for item in data.get("results", []):
            movies.append(Movie(
                id=item["id"],
                title=item["title"],
                release_date=item.get("release_date", ""),
                overview=item.get("overview", ""),
                genre_ids=item.get("genre_ids", []),
            ))
        return movies

    async def get_similar_series(self, tmdb_id: int, limit: int = 10) -> list[TVShow]:
        """Get similar TV shows to a given show."""
        data = await self._request(f"/tv/{tmdb_id}/similar")
        shows = []
        for item in data.get("results", [])[:limit]:
            shows.append(TVShow(
                id=item["id"],
                name=item["name"],
                first_air_date=item.get("first_air_date"),
                overview=item.get("overview", ""),
            ))
        return shows

    async def get_similar_movies(self, tmdb_id: int, limit: int = 10) -> list[Movie]:
        """Get similar movies to a given movie."""
        data = await self._request(f"/movie/{tmdb_id}/similar")
        movies = []
        for item in data.get("results", [])[:limit]:
            movies.append(Movie(
                id=item["id"],
                title=item["title"],
                release_date=item.get("release_date", ""),
                overview=item.get("overview", ""),
                genre_ids=item.get("genre_ids", []),
            ))
        return movies
