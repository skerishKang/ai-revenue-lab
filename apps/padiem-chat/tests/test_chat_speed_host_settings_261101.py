"""Production factory consumes the speed controls, including rollback settings."""
import pytest
from starlette.testclient import TestClient

from app import local_cpython


@pytest.mark.parametrize("readers,ttl,link,expected_readers,expected_ttl,expected_link", [
    (None, None, None, 2, 30, 600), ("0", "0", "0", 0, None, None),
    ("3", "60", "120", 3, 60, 120),
])
def test_factory_speed_controls(tmp_path, monkeypatch, readers, ttl, link,
                                expected_readers, expected_ttl, expected_link):
    for name, value in {
        "PADIEM_LOCAL_DEV": "1", "PADIEM_CHAT_RUNTIME_MODE": "mock",
        "PADIEM_CHAT_AUTH_MODE": "off", "PADIEM_CHAT_WEB_PROVIDER": "off",
        "PADIEM_CHAT_PUBLIC_BASE_URL": "http://127.0.0.1:8773",
        "PADIEM_CHAT_LOCAL_DATA_DIR": str(tmp_path),
        "PADIEM_CHAT_SESSION_SECRET": "test-local-secret-0123456789abcdef",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("PC_QUEUE_BACKEND", raising=False)
    for name, value in (("PADIEM_CHAT_SQLITE_READERS", readers),
                        ("PADIEM_CHAT_AUTH_CACHE_SECONDS", ttl),
                        ("PADIEM_CHAT_SHARED_LINK_CACHE_SECONDS", link)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    databases = []
    original = local_cpython.SqliteD1
    def capture(*args, **kwargs):
        db = original(*args, **kwargs)
        databases.append(db)
        return db
    monkeypatch.setattr(local_cpython, "SqliteD1", capture)
    app = local_cpython.build_app()
    db = databases[0]
    assert db.read_workers == expected_readers
    cache = app.state.auth_validation_cache
    if expected_ttl is None:
        assert cache is None
    else:
        assert (cache.db is db and cache.ttl_seconds == expected_ttl
                and cache.link_ttl_seconds == expected_link)
    assert db.close_readers in app.router.on_shutdown
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
    db.connection.close()


@pytest.mark.parametrize("value", ["-1", "1.5", "invalid", "１"])
def test_invalid_reader_count_never_leaks_value(monkeypatch, value):
    name = "PADIEM_CHAT_SQLITE_READERS"
    monkeypatch.setenv(name, value)
    with pytest.raises(local_cpython.ConfigError) as error:
        local_cpython._nonnegative_env(name, 2)
    assert str(error.value) == name + " must be a non-negative integer"
