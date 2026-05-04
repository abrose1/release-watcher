"""Brave Search API client."""

from dataclasses import dataclass
from typing import Any

import httpx

from watcher.config import get_env


class BraveSearchError(Exception):
    pass


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class BraveSearchClient:
    """Brave Search API client for finding articles and announcements."""

    BASE_URL = "https://api.search.brave.com/res/v1"
    MAX_RETRIES = 3

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or get_env("BRAVE_SEARCH_API_KEY")

    async def _request(self, path: str, params: dict | None = None) -> Any:
        """Make an authenticated request with retry logic."""
        for attempt in range(self.MAX_RETRIES):
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.BASE_URL}{path}",
                    headers={
                        "X-Subscription-Token": self.api_key,
                        "Accept": "application/json",
                    },
                    params=params,
                )
                if resp.status_code == 429:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
                    continue
                if resp.status_code != 200:
                    raise BraveSearchError(f"Brave Search API error {resp.status_code}: {resp.text}")
                return resp.json()

        raise BraveSearchError("Max retries exceeded")

    async def search(self, query: str, num_results: int = 5) -> list[SearchResult]:
        """Run a web search and return structured results."""
        data = await self._request(
            "/web/search",
            params={"q": query, "count": num_results},
        )
        results = []
        for item in data.get("web", {}).get("results", []):
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("description", ""),
            ))
        return results

    async def search_release(self, creator: str, title: str) -> list[SearchResult]:
        """Find the best article for a known release."""
        query = f"{creator} \"{title}\" review OR announcement"
        return await self.search(query)

    async def search_announcement(self, creator: str, category: str, year: int) -> list[SearchResult]:
        """Find announcement news for a creator."""
        type_map = {"music": "album", "book": "book", "tv": "season"}
        release_type = type_map.get(category, "release")
        query = f"{creator} new {release_type} {year}"
        return await self.search(query)

    async def search_similar_books(self, author_name: str) -> list[SearchResult]:
        """Search for books similar to an author's work."""
        query = f"books similar to {author_name} 2025 2026"
        return await self.search(query)
