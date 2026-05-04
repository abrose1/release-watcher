"""Google Books API client."""

from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from watcher.config import get_env


class BooksError(Exception):
    pass


@dataclass
class Book:
    id: str
    title: str
    authors: list[str]
    published_date: str
    description: str
    info_link: str


class BooksClient:
    """Google Books API client for author book lookups."""

    BASE_URL = "https://www.googleapis.com/books/v1"
    MAX_RETRIES = 3

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or get_env("GOOGLE_BOOKS_API_KEY")

    async def _request(self, path: str, params: dict | None = None) -> Any:
        """Make an authenticated request with retry logic."""
        request_params = {"key": self.api_key}
        if params:
            request_params.update(params)

        for attempt in range(self.MAX_RETRIES):
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.BASE_URL}{path}",
                    params=request_params,
                )
                if resp.status_code == 429:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
                    continue
                if resp.status_code != 200:
                    raise BooksError(f"Google Books API error {resp.status_code}: {resp.text}")
                return resp.json()

        raise BooksError("Max retries exceeded")

    async def get_author_new_books(self, author_id: str, after_date: date) -> list[Book]:
        """Get new books by an author since the given date, filtered to novels/novellas."""
        data = await self._request(
            "/volumes",
            params={
                "q": f"inauthor:{author_id}",
                "orderBy": "newest",
                "maxResults": 20,
            },
        )
        books = []
        for item in data.get("items", []):
            vol_info = item.get("volumeInfo", {})
            published = vol_info.get("publishedDate", "")
            if published >= after_date.isoformat():
                page_count = vol_info.get("pageCount", 0)
                if page_count and page_count < 50:
                    continue
                books.append(Book(
                    id=item["id"],
                    title=vol_info.get("title", ""),
                    authors=vol_info.get("authors", []),
                    published_date=published,
                    description=vol_info.get("description", ""),
                    info_link=vol_info.get("infoLink", ""),
                ))
        return books

    async def search_books_by_author_name(self, name: str, after_date: date) -> list[Book]:
        """Fallback search by author name when no author ID is set."""
        data = await self._request(
            "/volumes",
            params={
                "q": f"inauthor:\"{name}\"",
                "orderBy": "newest",
                "maxResults": 20,
            },
        )
        books = []
        for item in data.get("items", []):
            vol_info = item.get("volumeInfo", {})
            published = vol_info.get("publishedDate", "")
            if published >= after_date.isoformat():
                page_count = vol_info.get("pageCount", 0)
                if page_count and page_count < 50:
                    continue
                books.append(Book(
                    id=item["id"],
                    title=vol_info.get("title", ""),
                    authors=vol_info.get("authors", []),
                    published_date=published,
                    description=vol_info.get("description", ""),
                    info_link=vol_info.get("infoLink", ""),
                ))
        return books
