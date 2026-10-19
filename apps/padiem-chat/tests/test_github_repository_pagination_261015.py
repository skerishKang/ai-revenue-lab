"""GitHub installation repository listing must include later API pages."""
import httpx
import pytest
from app.github_oauth_provider import GitHubAppOAuthProvider


@pytest.mark.asyncio
async def test_repository_listing_fetches_every_page():
    seen_pages = []
    def handle(request):
        page = int(request.url.params["page"])
        seen_pages.append(page)
        assert request.url.params["per_page"] == "100"
        first = 0 if page == 1 else 100
        last = 100 if page == 1 else 105
        return httpx.Response(200, json={
            "total_count": 105,
            "repositories": [
                {"full_name": f"demo/repository-{index}", "private": index % 3 == 0}
                for index in range(first, last)
            ],
        })
    provider = GitHubAppOAuthProvider(
        client_secret="fixture-only", transport=httpx.MockTransport(handle))
    items = await provider.repositories("example-token", 171513671)
    assert len(items) == 105
    assert seen_pages == [1, 2]
    assert items[-1]["full_name"] == "demo/repository-104"
    assert items[-1]["private"] is False


@pytest.mark.asyncio
async def test_repository_listing_rejects_incomplete_page():
    def handle(request):
        return httpx.Response(200, json={"total_count": 40, "repositories": []})
    provider = GitHubAppOAuthProvider(
        client_secret="fixture-only", transport=httpx.MockTransport(handle))
    with pytest.raises(ValueError, match="incomplete"):
        await provider.repositories("example-token", 171513671)
