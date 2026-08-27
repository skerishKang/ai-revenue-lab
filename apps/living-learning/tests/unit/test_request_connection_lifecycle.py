from __future__ import annotations

import sqlite3
import threading
from types import SimpleNamespace

from app.ai import MockProvider
from app.factory import get_connection_factory
from app.routes import RequestPipelineRunner, get_pipeline


class TrackingConnection:
    def __init__(self, events: list[tuple[str, int]]) -> None:
        self._events = events

    def close(self) -> None:
        self._events.append(("close", threading.get_ident()))


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        provider_type="mock",
        provider_model="mock/mock-fixture",
        database_url="test.db",
    )


def test_dependency_does_not_create_sqlite_connection() -> None:
    """FastAPI dependency evaluation must carry only a factory, never a DB object."""
    events: list[tuple[str, int]] = []

    def connection_factory():
        events.append(("create", threading.get_ident()))
        return TrackingConnection(events)

    state = SimpleNamespace(settings=_settings(), get_connection=connection_factory)
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    provider = MockProvider(model="mock/mock-fixture")

    runner = get_pipeline(request, provider)

    assert isinstance(runner, RequestPipelineRunner)
    assert events == []


def test_runner_creates_uses_and_closes_connection_on_one_thread() -> None:
    """One pipeline operation owns the complete SQLite lifetime in its caller thread."""
    events: list[tuple[str, int]] = []

    def connection_factory():
        events.append(("create", threading.get_ident()))
        return TrackingConnection(events)

    runner = RequestPipelineRunner(
        connection_factory=connection_factory,
        provider=MockProvider(model="mock/mock-fixture"),
        settings=_settings(),
    )

    def operation(pipeline):
        assert isinstance(pipeline.conn, TrackingConnection)
        events.append(("use", threading.get_ident()))
        return "ok"

    assert runner.run(operation) == "ok"
    assert [name for name, _ in events] == ["create", "use", "close"]
    assert len({thread_id for _, thread_id in events}) == 1


def test_runner_closes_connection_when_pipeline_operation_raises() -> None:
    events: list[tuple[str, int]] = []

    def connection_factory():
        events.append(("create", threading.get_ident()))
        return TrackingConnection(events)

    runner = RequestPipelineRunner(
        connection_factory=connection_factory,
        provider=MockProvider(model="mock/mock-fixture"),
        settings=_settings(),
    )

    try:
        runner.run(lambda pipeline: (_ for _ in ()).throw(RuntimeError("boom")))
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("expected RuntimeError")

    assert [name for name, _ in events] == ["create", "close"]
    assert len({thread_id for _, thread_id in events}) == 1


def test_web_connection_factory_rejects_cross_thread_use() -> None:
    """A future lifecycle regression must fail safely instead of disabling sqlite guards."""
    conn = get_connection_factory(":memory:")()
    failures: list[BaseException] = []

    def cross_thread_use() -> None:
        try:
            conn.execute("SELECT 1").fetchone()
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=cross_thread_use)
    thread.start()
    thread.join()

    try:
        assert len(failures) == 1
        assert isinstance(failures[0], sqlite3.ProgrammingError)
    finally:
        conn.close()
