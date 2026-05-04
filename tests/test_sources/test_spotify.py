"""Tests for Spotify API client."""

import pytest
import httpx
import respx

from watcher.sources.spotify import SpotifyClient, SpotifyError
from tests.fixtures import (
    MOCK_SPOTIFY_ALBUMS_RESPONSE, MOCK_SPOTIFY_SINGLES_RESPONSE,
    MOCK_SPOTIFY_TOKEN_RESPONSE, MOCK_SPOTIFY_RECOMMENDATIONS,
)
from datetime import date


@pytest.fixture
def spotify_client():
    return SpotifyClient(
        client_id="test_id",
        client_secret="test_secret",
        refresh_token="test_refresh",
    )


class TestSpotifyClient:
    @pytest.mark.asyncio
    @respx.mock
    async def test_get_client_credentials_token(self, spotify_client):
        respx.post("https://accounts.spotify.com/api/token").mock(
            return_value=httpx.Response(200, json=MOCK_SPOTIFY_TOKEN_RESPONSE)
        )

        token = await spotify_client._get_client_credentials_token()
        assert token == "test_access_token"

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_artist_albums(self, spotify_client):
        respx.post("https://accounts.spotify.com/api/token").mock(
            return_value=httpx.Response(200, json=MOCK_SPOTIFY_TOKEN_RESPONSE)
        )
        respx.get("https://api.spotify.com/v1/artists/spotify_id_aaa/albums").mock(
            return_value=httpx.Response(200, json=MOCK_SPOTIFY_ALBUMS_RESPONSE)
        )

        albums = await spotify_client.get_artist_albums("spotify_id_aaa", date(2026, 1, 1))
        assert len(albums) == 1
        assert albums[0].name == "Test Album"
        assert albums[0].album_type == "album"

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_artist_albums_filters_old(self, spotify_client):
        respx.post("https://accounts.spotify.com/api/token").mock(
            return_value=httpx.Response(200, json=MOCK_SPOTIFY_TOKEN_RESPONSE)
        )
        respx.get("https://api.spotify.com/v1/artists/spotify_id_aaa/albums").mock(
            return_value=httpx.Response(200, json=MOCK_SPOTIFY_ALBUMS_RESPONSE)
        )

        albums = await spotify_client.get_artist_albums("spotify_id_aaa", date(2026, 5, 1))
        assert len(albums) == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_artist_new_singles(self, spotify_client):
        respx.post("https://accounts.spotify.com/api/token").mock(
            return_value=httpx.Response(200, json=MOCK_SPOTIFY_TOKEN_RESPONSE)
        )
        respx.get("https://api.spotify.com/v1/artists/spotify_id_aaa/albums").mock(
            return_value=httpx.Response(200, json=MOCK_SPOTIFY_SINGLES_RESPONSE)
        )

        singles = await spotify_client.get_artist_new_singles("spotify_id_aaa", date(2026, 1, 1))
        assert len(singles) == 1
        assert singles[0].album_type == "single"

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_recommendations(self, spotify_client):
        respx.post("https://accounts.spotify.com/api/token").mock(
            return_value=httpx.Response(200, json=MOCK_SPOTIFY_TOKEN_RESPONSE)
        )
        respx.get("https://api.spotify.com/v1/recommendations").mock(
            return_value=httpx.Response(200, json=MOCK_SPOTIFY_RECOMMENDATIONS)
        )

        tracks = await spotify_client.get_recommendations(["spotify_id_aaa"])
        assert len(tracks) == 1
        assert tracks[0].name == "Recommended Song"

    @pytest.mark.asyncio
    @respx.mock
    async def test_rate_limit_retry(self, spotify_client):
        respx.post("https://accounts.spotify.com/api/token").mock(
            return_value=httpx.Response(200, json=MOCK_SPOTIFY_TOKEN_RESPONSE)
        )
        route = respx.get("https://api.spotify.com/v1/artists/test/albums")
        route.side_effect = [
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"items": []}),
        ]

        albums = await spotify_client.get_artist_albums("test", date(2026, 1, 1))
        assert len(albums) == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_error_raises(self, spotify_client):
        respx.post("https://accounts.spotify.com/api/token").mock(
            return_value=httpx.Response(200, json=MOCK_SPOTIFY_TOKEN_RESPONSE)
        )
        respx.get("https://api.spotify.com/v1/artists/bad/albums").mock(
            return_value=httpx.Response(404, text="Not Found")
        )

        with pytest.raises(SpotifyError):
            await spotify_client.get_artist_albums("bad", date(2026, 1, 1))

    @pytest.mark.asyncio
    @respx.mock
    async def test_refresh_access_token(self, spotify_client):
        respx.post("https://accounts.spotify.com/api/token").mock(
            return_value=httpx.Response(200, json=MOCK_SPOTIFY_TOKEN_RESPONSE)
        )

        token = await spotify_client.refresh_access_token()
        assert token == "test_access_token"
