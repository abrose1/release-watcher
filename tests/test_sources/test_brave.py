"""Tests for Brave Search API client."""

import pytest
import httpx
import respx

from watcher.sources.brave import BraveSearchClient, BraveSearchError
from tests.fixtures import MOCK_BRAVE_SEARCH_RESPONSE


@pytest.fixture
def brave_client():
    return BraveSearchClient(api_key="test_key")


class TestBraveSearchClient:
    @pytest.mark.asyncio
    @respx.mock
    async def test_search(self, brave_client):
        respx.get("https://api.search.brave.com/res/v1/web/search").mock(
            return_value=httpx.Response(200, json=MOCK_BRAVE_SEARCH_RESPONSE)
        )

        results = await brave_client.search("test query")
        assert len(results) == 2
        assert results[0].title == "Test Article - New Album Review"
        assert results[0].url == "https://example.com/review"

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_release(self, brave_client):
        respx.get("https://api.search.brave.com/res/v1/web/search").mock(
            return_value=httpx.Response(200, json=MOCK_BRAVE_SEARCH_RESPONSE)
        )

        results = await brave_client.search_release("Artist", "Album")
        assert len(results) == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_announcement(self, brave_client):
        respx.get("https://api.search.brave.com/res/v1/web/search").mock(
            return_value=httpx.Response(200, json=MOCK_BRAVE_SEARCH_RESPONSE)
        )

        results = await brave_client.search_announcement("Artist", "music", 2026)
        assert len(results) == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_similar_books(self, brave_client):
        respx.get("https://api.search.brave.com/res/v1/web/search").mock(
            return_value=httpx.Response(200, json=MOCK_BRAVE_SEARCH_RESPONSE)
        )

        results = await brave_client.search_similar_books("Author Name")
        assert len(results) == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_error_raises(self, brave_client):
        respx.get("https://api.search.brave.com/res/v1/web/search").mock(
            return_value=httpx.Response(401, text="Unauthorized")
        )

        with pytest.raises(BraveSearchError):
            await brave_client.search("test")

    @pytest.mark.asyncio
    @respx.mock
    async def test_rate_limit_retry(self, brave_client):
        route = respx.get("https://api.search.brave.com/res/v1/web/search")
        route.side_effect = [
            httpx.Response(429),
            httpx.Response(200, json=MOCK_BRAVE_SEARCH_RESPONSE),
        ]

        results = await brave_client.search("test")
        assert len(results) == 2
