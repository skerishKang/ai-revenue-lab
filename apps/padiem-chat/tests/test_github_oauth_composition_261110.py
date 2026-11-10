"""#6859: one shared GitHub App OAuth port composition for Worker and host.

The Worker and the COM2 CPython host must bind the same class pair behind
the same reviewed fail-closed gate. These tests pin the gate itself: any
missing material keeps both ports unbound so the routes answer the
reviewed 503 instead of a half pair or a boot error.
"""
from __future__ import annotations

from app.github_oauth_composition import compose_github_oauth_ports
from app.github_oauth_provider import GitHubAppOAuthProvider
from app.github_oauth_store import D1GitHubOAuthStore

SYNTHETIC_CLIENT_SECRET = "synthetic-github-app-secret-0123456789"
SYNTHETIC_SESSION_SECRET = "synthetic-product-session-secret-0123456789abcdef"


def test_missing_client_secret_is_fail_closed():
    for value in ("", "   ", None):
        store, provider, reason = compose_github_oauth_ports(
            db=object(),
            session_secret=SYNTHETIC_SESSION_SECRET,
            client_secret=value,
        )
        assert (store, provider, reason) == (None, None, "secret_absent")


def test_missing_db_is_fail_closed():
    store, provider, reason = compose_github_oauth_ports(
        db=None,
        session_secret=SYNTHETIC_SESSION_SECRET,
        client_secret=SYNTHETIC_CLIENT_SECRET,
    )
    assert (store, provider, reason) == (None, None, "store_unavailable")


def test_weak_or_absent_session_secret_is_fail_closed():
    for value in (None, "", "short-secret-0", "x" * 31):
        store, provider, reason = compose_github_oauth_ports(
            db=object(),
            session_secret=value,
            client_secret=SYNTHETIC_CLIENT_SECRET,
        )
        assert (store, provider, reason) == (None, None, "session_secret_weak")


def test_both_ports_bind_with_the_shared_classes_and_transport():
    sentinel_transport = object()
    store, provider, reason = compose_github_oauth_ports(
        db=object(),
        session_secret=SYNTHETIC_SESSION_SECRET,
        client_secret="  " + SYNTHETIC_CLIENT_SECRET + "  ",
        provider_transport=sentinel_transport,
    )
    assert reason is None
    assert isinstance(store, D1GitHubOAuthStore)
    assert isinstance(provider, GitHubAppOAuthProvider)
    assert provider.client_secret == SYNTHETIC_CLIENT_SECRET
    assert provider.transport is sentinel_transport
