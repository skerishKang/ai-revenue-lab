"""#5942: a Google login started from the 의원3종 page returns to that page.

The council app signs users in inside its own page, and the provider round trip is the
one step that leaves it. The continuation is therefore decided by the signed state this
Worker issued, against one exact allowlist — never by a caller-supplied URL — and a
Chat login that does not ask keeps landing on the Chat root.
"""

from __future__ import annotations

import time

import pytest

from app.auth import (
    OAUTH_RETURN_TARGETS,
    create_oauth_state,
    oauth_return_target,
    verified_oauth_return_target,
)


class _Settings:
    """Only the fields these helpers read. Every value is synthetic."""

    def __init__(self, secret: str = "return-target-secret-not-real-000000") -> None:
        self.session_secret = secret
        self.auth_mode = "google"
        self.session_max_age_seconds = 3600
        self.cookie_secure = True
        self.public_base_url = "https://chat.example.test"
        self.b66_quote_base_url = None
        self.runtime_mode = "mock"
        self.live_enabled = "false"


def test_the_allowlist_is_the_council_entry_and_nothing_else() -> None:
    assert OAUTH_RETURN_TARGETS == frozenset({"/apps/council/"})


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        0,
        True,
        ["/apps/council/"],
        "https://evil.example/",
        "//evil.example/",
        "/apps/council.evil/",
        "/apps/council/../admin",
        "/apps/council",
        "/apps/council/#sns",
        "/api/chat",
        " /apps/council/",
    ],
)
def test_only_the_exact_declared_entry_is_a_continuation(value: object) -> None:
    assert oauth_return_target(value) is None


def test_the_council_entry_survives_the_signature_and_a_foreign_ask_does_not() -> None:
    settings = _Settings()
    state, signed = create_oauth_state(settings, return_to="/apps/council/")
    assert isinstance(state, str) and state
    assert verified_oauth_return_target(settings, signed) == "/apps/council/"

    _, refused = create_oauth_state(settings, return_to="https://evil.example/")
    assert verified_oauth_return_target(settings, refused) == "/"


def test_chat_login_without_a_return_request_keeps_the_root() -> None:
    settings = _Settings()
    _, signed = create_oauth_state(settings)
    assert verified_oauth_return_target(settings, signed) == "/"


def test_a_state_signed_elsewhere_or_an_expired_state_lands_on_the_root() -> None:
    settings = _Settings()
    other = _Settings(secret="different-return-target-secret-not-real")
    _, foreign = create_oauth_state(other, return_to="/apps/council/")
    assert verified_oauth_return_target(settings, foreign) == "/"

    _, expired = create_oauth_state(
        settings, now=int(time.time()) - 700, return_to="/apps/council/"
    )
    assert verified_oauth_return_target(settings, expired) == "/"


@pytest.mark.parametrize("token", [None, "", "not-a-token", "a.b"])
def test_a_malformed_state_cookie_lands_on_the_root(token: object) -> None:
    assert verified_oauth_return_target(_Settings(), token) == "/"


class _StartClient:
    def __init__(self) -> None:
        self.seen_states: list[str] = []

    def authorization_url(self, state: str, bridge_origin: str | None = None) -> str:
        self.seen_states.append(state)
        return "https://accounts.google.com/o/oauth2/v2/auth?state=" + state


def _start_request(query: dict[str, str]):
    app = type("App", (), {"state": type("S", (), {})()})()
    app.state.settings = _Settings()
    app.state.history_store = object()
    app.state.google_oauth = _StartClient()
    return type("Request", (), {"app": app, "query_params": query, "headers": {}})()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("asked", "expected"),
    [("/apps/council/", "/apps/council/"), ("https://evil.example/", "/")],
)
async def test_google_start_carries_the_continuation_in_its_signed_cookie(
    asked: str, expected: str
) -> None:
    from app.auth_routes import google_start

    request = _start_request({"return_to": asked})
    response = await google_start(request)
    assert response.status_code == 302
    # The provider URL carries only the state this Worker signed: the requested
    # continuation never travels to the provider.
    client = request.app.state.google_oauth
    assert len(client.seen_states) == 1
    assert response.headers["location"].rpartition("state=")[2] == client.seen_states[0]
    assert asked.rstrip("/") not in response.headers["location"]
    cookies = [value for key, value in response.raw_headers if key == b"set-cookie"]
    assert cookies, "google_start must set the signed state cookie"
    signed = cookies[0].decode("utf-8").split("padiem_oauth_state=", 1)[1].split(";", 1)[0]
    assert verified_oauth_return_target(request.app.state.settings, signed) == expected


@pytest.mark.asyncio
async def test_google_callback_redirects_to_the_signed_continuation() -> None:
    from test_b54_google_canonical_session_parity import (
        VERIFIED_IDENTITY,
        _Authority,
        _run_callback,
    )

    chat, _, _, _ = await _run_callback(_Authority(), VERIFIED_IDENTITY)
    assert chat.status_code == 302
    assert chat.headers["location"] == "/"

    app_entry, _, _, _ = await _run_callback(
        _Authority(), VERIFIED_IDENTITY, return_to="/apps/council/"
    )
    assert app_entry.status_code == 302
    assert app_entry.headers["location"] == "/apps/council/"

    forged, _, _, _ = await _run_callback(
        _Authority(), VERIFIED_IDENTITY, return_to="https://evil.example/"
    )
    assert forged.headers["location"] == "/"
