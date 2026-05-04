"""Spotify API client supporting both client credentials and refresh token auth."""

from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from watcher.config import get_env


class SpotifyError(Exception):
    pass


@dataclass
class Album:
    id: str
    name: str
    release_date: str
    album_type: str
    artists: list[dict[str, str]]
    spotify_url: str


@dataclass
class Track:
    id: str
    name: str
    artists: list[dict[str, str]]
    album: dict[str, Any]


class SpotifyClient:
    """Spotify API client with client credentials and refresh token auth modes."""

    BASE_URL = "https://api.spotify.com/v1"
    TOKEN_URL = "https://accounts.spotify.com/api/token"
    MAX_RETRIES = 3

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
    ):
        self.client_id = client_id or get_env("SPOTIFY_CLIENT_ID")
        self.client_secret = client_secret or get_env("SPOTIFY_CLIENT_SECRET")
        self.refresh_token = refresh_token or get_env("SPOTIFY_REFRESH_TOKEN", required=False)
        self._client_credentials_token: str | None = None
        self._user_access_token: str | None = None

    async def _get_client_credentials_token(self) -> str:
        if self._client_credentials_token:
            return self._client_credentials_token

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self.TOKEN_URL,
                data={"grant_type": "client_credentials"},
                auth=(self.client_id, self.client_secret),
            )
            if resp.status_code != 200:
                raise SpotifyError(f"Failed to get client credentials token: {resp.status_code}")
            self._client_credentials_token = resp.json()["access_token"]
            return self._client_credentials_token

    async def refresh_access_token(self, refresh_token: str | None = None) -> str:
        """Get a fresh access token using the refresh token."""
        token = refresh_token or self.refresh_token
        if not token:
            raise SpotifyError("No refresh token available")

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self.TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": token,
                },
                auth=(self.client_id, self.client_secret),
            )
            if resp.status_code != 200:
                raise SpotifyError(f"Failed to refresh access token: {resp.status_code}")
            self._user_access_token = resp.json()["access_token"]
            return self._user_access_token

    async def _request(self, path: str, use_user_auth: bool = False, params: dict | None = None) -> Any:
        """Make an authenticated request with retry logic."""
        if use_user_auth:
            if not self._user_access_token:
                await self.refresh_access_token()
            token = self._user_access_token
        else:
            token = await self._get_client_credentials_token()

        for attempt in range(self.MAX_RETRIES):
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.BASE_URL}{path}",
                    headers={"Authorization": f"Bearer {token}"},
                    params=params,
                )
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 2 ** attempt))
                    import asyncio
                    await asyncio.sleep(retry_after)
                    continue
                if resp.status_code != 200:
                    raise SpotifyError(f"Spotify API error {resp.status_code}: {resp.text}")
                return resp.json()

        raise SpotifyError("Max retries exceeded")

    async def get_artist_albums(self, spotify_id: str, after_date: date) -> list[Album]:
        """Get albums by an artist released after the given date."""
        data = await self._request(
            f"/artists/{spotify_id}/albums",
            params={"include_groups": "album", "limit": 50, "market": "US"},
        )
        albums = []
        for item in data.get("items", []):
            if item.get("release_date", "") >= after_date.isoformat():
                albums.append(Album(
                    id=item["id"],
                    name=item["name"],
                    release_date=item["release_date"],
                    album_type=item["album_type"],
                    artists=[{"name": a["name"]} for a in item.get("artists", [])],
                    spotify_url=item.get("external_urls", {}).get("spotify", ""),
                ))
        return albums

    async def get_artist_new_singles(self, spotify_id: str, after_date: date) -> list[Album]:
        """Get singles by an artist released after the given date (Tier 1 only)."""
        data = await self._request(
            f"/artists/{spotify_id}/albums",
            params={"include_groups": "single", "limit": 50, "market": "US"},
        )
        singles = []
        for item in data.get("items", []):
            if item.get("release_date", "") >= after_date.isoformat():
                singles.append(Album(
                    id=item["id"],
                    name=item["name"],
                    release_date=item["release_date"],
                    album_type="single",
                    artists=[{"name": a["name"]} for a in item.get("artists", [])],
                    spotify_url=item.get("external_urls", {}).get("spotify", ""),
                ))
        return singles

    async def get_recommendations(self, seed_artist_ids: list[str], limit: int = 20) -> list[Track]:
        """Get recommendations based on seed artists (requires user auth)."""
        data = await self._request(
            "/recommendations",
            use_user_auth=True,
            params={"seed_artists": ",".join(seed_artist_ids[:5]), "limit": limit},
        )
        tracks = []
        for item in data.get("tracks", []):
            tracks.append(Track(
                id=item["id"],
                name=item["name"],
                artists=[{"name": a["name"]} for a in item.get("artists", [])],
                album=item.get("album", {}),
            ))
        return tracks
