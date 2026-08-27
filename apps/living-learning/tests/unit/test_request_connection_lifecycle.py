from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

from app.ai import MockProvider
from app.routes import get_pipeline


class TrackingConnection:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


def test_pipeline_dependency_is_async_generator() -> None:
    """Connection cleanup must not use FastAPI's sync-generator teardown path."""
    assert inspect.isasyncgenfunction(get_pipeline)


def test_pipeline_connection_stays_open_until_dependency_finishes() -> None:
    """The yielded pipeline owns its connection until async finalization."""

    async def scenario() -> None:
        conn = TrackingConnection()
        settings = SimpleNamespace(
            provider_type="mock",
            provider_model="mock/mock-fixture",
            database_url="test.db",
        )
        state = SimpleNamespace(settings=settings, get_connection=lambda: conn)
        request = SimpleNamespace(app=SimpleNamespace(state=state))
        provider = MockProvider(model="mock/mock-fixture")

        dependency = get_pipeline(request, provider)
        pipeline = await anext(dependency)

        assert pipeline.conn is conn
        assert conn.close_calls == 0

        await dependency.aclose()
        assert conn.close_calls == 1

    asyncio.run(scenario())
