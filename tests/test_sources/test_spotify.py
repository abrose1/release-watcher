"""Tests for Spotify API client."""

import pytest
import httpx
import respx

from watcher.sources.spotify import SpotifyClient, SpotifyError
from tests.fixtures import (
    MOCK_SPOTIFY_ALBUMS_RESPONSE, MOCK_SPOTIFY_SINGLES_RESPONSE,
    MOCK_SPOTIFY_TOKEN_RESPONSE, MOCK_SPOTIFY_PLAYLIST_RESPONSE,
    MOCK_SPOTIFY_USER_TOKEN_RESPONSE,
)
from datetime import date


@pytest.fixture
def spotify_client():
    """Client without a refresh token — suitable for artist/album calls only."""
    return SpotifyClient(
        client_id="test_id",
        client_secret="test_secret",
    )


@pytest.fixture
def spotify_client_with_refresh():
    """Client with a refresh token — required for playlist reads."""
    return SpotifyClient(
        client_id="test_id",
        client_secret="test_secret",
        refresh_token="test_refresh_token",
    )


class TestSpotifyClient:
    @pytest.mark.asyncio
    @respx.mock
    async def test_get_token(self, spotify_client):
        respx.post("https://accounts.spotify.com/api/token").mock(
            return_value=httpx.Response(200, json=MOCK_SPOTIFY_TOKEN_RESPONSE)
        )

        token = await spotify_client._get_token()
        assert token == "test_access_token"

    @pytest.mark.asyncio
    @respx.mock
    async def test_token_cached_until_expiry(self, spotify_client):
        """Token should not be re-fetched while still valid."""
        token_route = respx.post("https://accounts.spotify.com/api/token").mock(
            return_value=httpx.Response(200, json=MOCK_SPOTIFY_TOKEN_RESPONSE)
        )
        respx.get("https://api.spotify.com/v1/artists/spotify_id_aaa/albums").mock(
            return_value=httpx.Response(200, json=MOCK_SPOTIFY_ALBUMS_RESPONSE)
        )

        await spotify_client.get_artist_albums("spotify_id_aaa", date(2026, 1, 1))
        await spotify_client.get_artist_albums("spotify_id_aaa", date(2026, 1, 1))

        assert token_route.call_count == 1

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
    async def test_401_forces_token_refresh(self, spotify_client):
        """On a 401 the client should clear its cached token and retry."""
        token_route = respx.post("https://accounts.spotify.com/api/token").mock(
            return_value=httpx.Response(200, json=MOCK_SPOTIFY_TOKEN_RESPONSE)
        )
        route = respx.get("https://api.spotify.com/v1/artists/test/albums")
        route.side_effect = [
            httpx.Response(401, text="Unauthorized"),
            httpx.Response(200, json={"items": []}),
        ]

        albums = await spotify_client.get_artist_albums("test", date(2026, 1, 1))
        assert len(albums) == 0
        assert token_route.call_count == 2

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

    # ------------------------------------------------------------------ #
    # Playlist tests — require user OAuth (refresh token)                 #
    # ------------------------------------------------------------------ #

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_playlist_tracks(self, spotify_client_with_refresh):
        respx.post("https://accounts.spotify.com/api/token").mock(
            return_value=httpx.Response(200, json=MOCK_SPOTIFY_USER_TOKEN_RESPONSE)
        )
        respx.get("https://api.spotify.com/v1/playlists/test_playlist/items").mock(
            return_value=httpx.Response(200, json=MOCK_SPOTIFY_PLAYLIST_RESPONSE)
        )

        tracks = await spotify_client_with_refresh.get_playlist_tracks("test_playlist")
        assert len(tracks) == 2
        assert tracks[0].name == "Song One"
        assert tracks[0].artists == ["Artist Alpha"]
        assert tracks[1].artists == ["Artist Beta", "Artist Gamma"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_playlist_tracks_skips_null_items(self, spotify_client_with_refresh):
        """Entries with a null `item` (e.g. local files) should be silently skipped."""
        respx.post("https://accounts.spotify.com/api/token").mock(
            return_value=httpx.Response(200, json=MOCK_SPOTIFY_USER_TOKEN_RESPONSE)
        )
        respx.get("https://api.spotify.com/v1/playlists/test_playlist/items").mock(
            return_value=httpx.Response(200, json={
                "items": [
                    {"item": None},
                    {"item": {"id": "t1", "name": "Real Song", "artists": [{"name": "Artist"}]}},
                ],
            })
        )

        tracks = await spotify_client_with_refresh.get_playlist_tracks("test_playlist")
        assert len(tracks) == 1
        assert tracks[0].name == "Real Song"

    @pytest.mark.asyncio
    async def test_get_playlist_tracks_without_refresh_token_raises(self, spotify_client):
        """Calling get_playlist_tracks without SPOTIFY_REFRESH_TOKEN raises SpotifyError."""
        with pytest.raises(SpotifyError, match="SPOTIFY_REFRESH_TOKEN"):
            await spotify_client.get_playlist_tracks("any_playlist_id")

    @pytest.mark.asyncio
    @respx.mock
    async def test_user_token_cached_until_expiry(self, spotify_client_with_refresh):
        """User token should not be re-fetched from the token endpoint while still valid."""
        token_route = respx.post("https://accounts.spotify.com/api/token").mock(
            return_value=httpx.Response(200, json=MOCK_SPOTIFY_USER_TOKEN_RESPONSE)
        )
        respx.get("https://api.spotify.com/v1/playlists/p1/items").mock(
            return_value=httpx.Response(200, json=MOCK_SPOTIFY_PLAYLIST_RESPONSE)
        )

        await spotify_client_with_refresh.get_playlist_tracks("p1")
        await spotify_client_with_refresh.get_playlist_tracks("p1")

        assert token_route.call_count == 1

    @pytest.mark.asyncio
    @respx.mock
    async def test_playlist_401_forces_user_token_refresh(self, spotify_client_with_refresh):
        """On a 401 from the playlist endpoint, clear and re-exchange the user token."""
        token_route = respx.post("https://accounts.spotify.com/api/token").mock(
            return_value=httpx.Response(200, json=MOCK_SPOTIFY_USER_TOKEN_RESPONSE)
        )
        playlist_route = respx.get("https://api.spotify.com/v1/playlists/p1/items")
        playlist_route.side_effect = [
            httpx.Response(401, text="Unauthorized"),
            httpx.Response(200, json={"items": []}),
        ]

        tracks = await spotify_client_with_refresh.get_playlist_tracks("p1")
        assert tracks == []
        # Token endpoint hit twice: initial fetch + re-exchange after 401
        assert token_route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_artist_calls_use_client_credentials_not_user_token(self, spotify_client_with_refresh):
        """Artist album/single calls must use client-credentials, not the user token."""
        token_route = respx.post("https://accounts.spotify.com/api/token").mock(
            return_value=httpx.Response(200, json=MOCK_SPOTIFY_TOKEN_RESPONSE)
        )
        respx.get("https://api.spotify.com/v1/artists/spotify_id_aaa/albums").mock(
            return_value=httpx.Response(200, json=MOCK_SPOTIFY_ALBUMS_RESPONSE)
        )

        await spotify_client_with_refresh.get_artist_albums("spotify_id_aaa", date(2026, 1, 1))

        # Only client-credentials token fetched; user token cache still empty
        assert token_route.call_count == 1
        assert spotify_client_with_refresh._user_access_token is None
