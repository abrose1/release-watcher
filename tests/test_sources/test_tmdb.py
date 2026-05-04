"""Tests for TMDB API client."""

import pytest
import httpx
import respx
from datetime import date

from watcher.sources.tmdb import TMDBClient, TMDBError
from tests.fixtures import (
    MOCK_TMDB_TV_RESPONSE, MOCK_TMDB_MOVIES_RESPONSE, MOCK_TMDB_SIMILAR_RESPONSE,
)


@pytest.fixture
def tmdb_client():
    return TMDBClient(api_key="test_key")


class TestTMDBClient:
    @pytest.mark.asyncio
    @respx.mock
    async def test_get_tv_season_updates(self, tmdb_client):
        respx.get("https://api.themoviedb.org/3/tv/12345").mock(
            return_value=httpx.Response(200, json=MOCK_TMDB_TV_RESPONSE)
        )

        seasons = await tmdb_client.get_tv_season_updates(12345, date(2026, 1, 1))
        assert len(seasons) == 1
        assert seasons[0].season_number == 3
        assert seasons[0].name == "Season 3"

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_tv_season_filters_old(self, tmdb_client):
        respx.get("https://api.themoviedb.org/3/tv/12345").mock(
            return_value=httpx.Response(200, json=MOCK_TMDB_TV_RESPONSE)
        )

        seasons = await tmdb_client.get_tv_season_updates(12345, date(2026, 6, 1))
        assert len(seasons) == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_upcoming_movies(self, tmdb_client):
        respx.get("https://api.themoviedb.org/3/discover/movie").mock(
            return_value=httpx.Response(200, json=MOCK_TMDB_MOVIES_RESPONSE)
        )

        movies = await tmdb_client.get_upcoming_movies([18, 53], date(2026, 1, 1))
        assert len(movies) == 1
        assert movies[0].title == "Test Thriller"
        assert 18 in movies[0].genre_ids

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_similar_series(self, tmdb_client):
        respx.get("https://api.themoviedb.org/3/tv/12345/similar").mock(
            return_value=httpx.Response(200, json=MOCK_TMDB_SIMILAR_RESPONSE)
        )

        shows = await tmdb_client.get_similar_series(12345)
        assert len(shows) == 1
        assert shows[0].name == "Similar Show"

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_similar_movies(self, tmdb_client):
        respx.get("https://api.themoviedb.org/3/movie/99999/similar").mock(
            return_value=httpx.Response(200, json={"results": MOCK_TMDB_MOVIES_RESPONSE["results"]})
        )

        movies = await tmdb_client.get_similar_movies(99999)
        assert len(movies) == 1
        assert movies[0].title == "Test Thriller"

    @pytest.mark.asyncio
    @respx.mock
    async def test_error_raises(self, tmdb_client):
        respx.get("https://api.themoviedb.org/3/tv/999").mock(
            return_value=httpx.Response(404, text="Not Found")
        )

        with pytest.raises(TMDBError):
            await tmdb_client.get_tv_season_updates(999, date(2026, 1, 1))

    @pytest.mark.asyncio
    @respx.mock
    async def test_rate_limit_retry(self, tmdb_client):
        route = respx.get("https://api.themoviedb.org/3/tv/12345")
        route.side_effect = [
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json=MOCK_TMDB_TV_RESPONSE),
        ]

        seasons = await tmdb_client.get_tv_season_updates(12345, date(2026, 1, 1))
        assert len(seasons) == 1
