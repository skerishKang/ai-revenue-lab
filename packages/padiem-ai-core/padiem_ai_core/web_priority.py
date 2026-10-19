"""#4469: shared TinyFish-first, Daum-on-402/429-only public search.

This composes the existing Core provider implementations. It creates no new
provider API, endpoint, credential store or model fallback. Fetch never falls
back to Daum; empty results and non-quota failures remain terminal.
"""
from __future__ import annotations

from dataclasses import replace

import httpx

from .contracts import Evidence
from .web_runtime import (
    DaumWebProvider,
    TinyFishWebProvider,
    WebRuntimeConfig,
    WebRuntimeError,
)


class TinyFishDaumPriorityWebProvider:
    """One TinyFish Search, optionally one Daum Search on 402/429 only."""

    def __init__(
        self,
        *,
        tinyfish_key: str,
        daum_key: str,
        timeout_seconds: float = 15.0,
        daum_search_sort: str = "accuracy",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # Fail closed before any public egress unless BOTH existing keys exist.
        config = WebRuntimeConfig(
            provider="tinyfish",
            tinyfish_api_key=tinyfish_key,
            daum_rest_api_key=daum_key,
            daum_search_sort=daum_search_sort,
            web_timeout_seconds=timeout_seconds,
        )
        if not config.daum_rest_api_key:
            raise ValueError("Daum key is required by the shared search priority")
        self._primary = TinyFishWebProvider(config, transport=transport)
        self._secondary = DaumWebProvider(
            replace(config, provider="daum", tinyfish_api_key=None),
            transport=transport,
        )

    async def search(self, query: str, limit: int = 5) -> list[Evidence]:
        try:
            return await self._primary.search(query, limit=limit)
        except WebRuntimeError as exc:
            if exc.code not in {"web_quota_exhausted", "web_busy"}:
                raise
        return await self._secondary.search(query, limit=limit)

    async def fetch(self, url: str) -> Evidence:
        return await self._primary.fetch(url)


__all__ = ["TinyFishDaumPriorityWebProvider"]
