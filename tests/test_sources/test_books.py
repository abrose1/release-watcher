"""Tests for Google Books API client."""

import pytest
import httpx
import respx
from datetime import date

from watcher.sources.books import BooksClient, BooksError
from tests.fixtures import MOCK_BOOKS_RESPONSE


@pytest.fixture
def books_client():
    return BooksClient(api_key="test_key")


class TestBooksClient:
    @pytest.mark.asyncio
    @respx.mock
    async def test_get_author_new_books(self, books_client):
        respx.get("https://www.googleapis.com/books/v1/volumes").mock(
            return_value=httpx.Response(200, json=MOCK_BOOKS_RESPONSE)
        )

        books = await books_client.get_author_new_books("author_123", date(2026, 1, 1))
        assert len(books) == 1
        assert books[0].title == "Test Novel"
        assert books[0].authors == ["Test Author A"]

    @pytest.mark.asyncio
    @respx.mock
    async def test_get_author_new_books_filters_old(self, books_client):
        respx.get("https://www.googleapis.com/books/v1/volumes").mock(
            return_value=httpx.Response(200, json=MOCK_BOOKS_RESPONSE)
        )

        books = await books_client.get_author_new_books("author_123", date(2026, 6, 1))
        assert len(books) == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_filters_short_books(self, books_client):
        short_book_response = {
            "items": [
                {
                    "id": "short_1",
                    "volumeInfo": {
                        "title": "Short Story Collection",
                        "authors": ["Author"],
                        "publishedDate": "2026-04-01",
                        "description": "Short stories",
                        "pageCount": 30,
                        "infoLink": "https://books.google.com/books?id=short_1",
                    },
                }
            ]
        }
        respx.get("https://www.googleapis.com/books/v1/volumes").mock(
            return_value=httpx.Response(200, json=short_book_response)
        )

        books = await books_client.get_author_new_books("author_123", date(2026, 1, 1))
        assert len(books) == 0

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_by_author_name(self, books_client):
        respx.get("https://www.googleapis.com/books/v1/volumes").mock(
            return_value=httpx.Response(200, json=MOCK_BOOKS_RESPONSE)
        )

        books = await books_client.search_books_by_author_name("Test Author A", date(2026, 1, 1))
        assert len(books) == 1
        assert books[0].title == "Test Novel"

    @pytest.mark.asyncio
    @respx.mock
    async def test_error_raises(self, books_client):
        respx.get("https://www.googleapis.com/books/v1/volumes").mock(
            return_value=httpx.Response(403, text="Forbidden")
        )

        with pytest.raises(BooksError):
            await books_client.get_author_new_books("author_123", date(2026, 1, 1))

    @pytest.mark.asyncio
    @respx.mock
    async def test_rate_limit_retry(self, books_client):
        route = respx.get("https://www.googleapis.com/books/v1/volumes")
        route.side_effect = [
            httpx.Response(429),
            httpx.Response(200, json={"items": []}),
        ]

        books = await books_client.get_author_new_books("author_123", date(2026, 1, 1))
        assert len(books) == 0
