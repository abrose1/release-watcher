"""Google Books API client."""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from watcher.config import get_env

logger = logging.getLogger(__name__)


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
        import asyncio

        request_params = {"key": self.api_key}
        if params:
            request_params.update(params)

        url = f"{self.BASE_URL}{path}"
        # Log without the key so it's safe to copy from logs
        safe_params = {k: v for k, v in (params or {}).items()}
        logger.debug("Books API request: GET %s params=%s", url, safe_params)

        last_exc: Exception | None = None
        for attempt in range(self.MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(url, params=request_params)

                logger.debug(
                    "Books API response: attempt=%d status=%d url=%s",
                    attempt + 1, resp.status_code, url,
                )

                if resp.status_code == 200:
                    return resp.json()

                if resp.status_code == 429 or resp.status_code >= 500:
                    delay = 2 ** attempt
                    logger.warning(
                        "Books API transient error (attempt %d/%d): status=%d body=%r — retrying in %ds",
                        attempt + 1, self.MAX_RETRIES, resp.status_code,
                        resp.text[:200], delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                # 4xx (except 429) are not retryable
                logger.error(
                    "Books API non-retryable error: status=%d body=%r params=%s",
                    resp.status_code, resp.text[:200], safe_params,
                )
                raise BooksError(f"Google Books API error {resp.status_code}: {resp.text}")

            except httpx.TimeoutException as exc:
                delay = 2 ** attempt
                logger.warning(
                    "Books API timeout (attempt %d/%d) url=%s — retrying in %ds",
                    attempt + 1, self.MAX_RETRIES, url, delay,
                )
                last_exc = exc
                await asyncio.sleep(delay)

        raise BooksError(
            f"Google Books API: max retries ({self.MAX_RETRIES}) exceeded for {url}"
            + (f" — last error: {last_exc}" if last_exc else "")
        )

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
