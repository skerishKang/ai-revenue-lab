"""The parallel pages.dev entry shares one authority, two host-scoped logins (#6850).

``chat.padiem.net`` stays the canonical public base: links, MCP metadata and
password-reset mails keep pointing at it. The pages.dev host is an additional
*reviewed origin* — it may pass the same-origin guard and it gets its own
``/auth/shared/callback`` so the OAuth round trip never leaves the host the
browser is using. Nothing here widens the expectation from request data.
"""

from __future__ import annotations

import pytest

from app.config import ConfigError, Settings
from app.same_origin_guard import (
    ORIGIN_REJECTED_CODE,
    SameOriginGuardMiddleware,
    expected_browser_origin,
    expected_browser_origins,
)
from app.shared_login_flow import SharedLoginFlow, parse_extra_origins

CANONICAL = "https://chat.padiem.net"
PAGES = "https://padiem-chat.pages.dev"
UNREVIEWED = "https://evil.example.test"
SESSION_SECRET = "issue-6850-parallel-pages-origin-session-secret-000000000000"
CLIENT_JWK = {"kty": "EC", "crv": "P-256", "x": "a" * 43, "y": "b" * 43, "d": "c" * 43}


def _settings(**overrides) -> Settings:
    values = dict(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url=CANONICAL,
        google_client_id="unit-test-client.apps.googleusercontent.com",
        google_client_secret="unit-test-secret",
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )
    values.update(overrides)
    return Settings.from_values(**values)


class _Headers:
    """Just enough of a Starlette Headers object for these checks."""

    def __init__(self, values: dict[str, str]) -> None:
        self._values = {key.lower(): value for key, value in values.items()}

    def get(self, name: str, default=None):
        return self._values.get(name.lower(), default)


class _Request:
    def __init__(self, **headers: str) -> None:
        self.headers = _Headers(headers)


def _flow(*, extra_origins=()) -> SharedLoginFlow:
    async def exchange(*args, **kwargs):
        raise AssertionError("no exchange in this contract")

    async def resolve_account(*args, **kwargs):
        return None

    async def issue_session(*args, **kwargs):
        raise AssertionError("no session in this contract")

    return SharedLoginFlow(
        state_key=b"k" * 32,
        client_id="b62",
        client_jwk=dict(CLIENT_JWK),
        kid="6850-test",
        operator_guard=lambda request: False,
        legacy_user=lambda request: None,
        comparator=lambda *args: None,
        exchange=exchange,
        resolve_account=resolve_account,
        issue_session=issue_session,
        public_base_url=CANONICAL,
        extra_origins=extra_origins,
    )


def test_config_keeps_canonical_base_and_lists_extra_origins_only():
    settings = _settings(public_base_urls=f" {PAGES} , {CANONICAL} ")
    assert settings.public_base_url == CANONICAL
    assert settings.public_base_urls == (PAGES,)
    assert expected_browser_origin(settings) == CANONICAL
    assert expected_browser_origins(settings) == (CANONICAL, PAGES)


def test_config_without_extra_origins_is_unchanged():
    settings = _settings()
    assert settings.public_base_urls == ()
    assert expected_browser_origins(settings) == (CANONICAL,)


def test_config_rejects_an_origin_that_is_not_https_root():
    for value in ("http://padiem-chat.pages.dev", "https://padiem-chat.pages.dev/app"):
        with pytest.raises(ConfigError):
            _settings(public_base_urls=value)


def test_parse_extra_origins_drops_anything_malformed():
    assert parse_extra_origins(f"{PAGES}, https://user:pw@x.test, http://y.test, /relative, ") == (PAGES,)


def _decide(settings: Settings, *, origin: str | None):
    class _State:
        pass

    class _App:
        state = _State()

    _App.state.settings = settings
    headers = [(b"cookie", b"padiem_session=abc")]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    scope = {"type": "http", "method": "POST", "path": "/api/projects", "headers": headers, "app": _App}
    return SameOriginGuardMiddleware(lambda *args: None).decide(scope)


def test_cookie_mutation_from_the_pages_host_passes_the_guard():
    assert _decide(_settings(public_base_urls=PAGES), origin=PAGES) is None


def test_cookie_mutation_from_an_unreviewed_host_still_fails_closed():
    denial = _decide(_settings(public_base_urls=PAGES), origin=UNREVIEWED)
    assert denial is not None and denial.status_code == 403
    assert denial.body.decode().find(ORIGIN_REJECTED_CODE) >= 0


def test_login_callback_follows_the_host_the_browser_is_using():
    flow = _flow(extra_origins=(PAGES,))
    assert flow.callback_for(_Request(**{"x-forwarded-host": "padiem-chat.pages.dev"})) == (
        PAGES + "/auth/shared/callback"
    )
    # The canonical host keeps the canonical callback (front door sets this).
    assert flow.callback_for(_Request(**{"x-forwarded-host": "chat.padiem.net"})) == (
        CANONICAL + "/auth/shared/callback"
    )
    # No header, or a host nobody reviewed: the reviewed default.
    assert flow.callback_for(_Request()) == CANONICAL + "/auth/shared/callback"
    assert flow.callback_for(_Request(host="evil.example.test")) == CANONICAL + "/auth/shared/callback"


def test_login_callback_is_untouched_when_no_extra_origin_is_configured():
    flow = _flow()
    assert flow.callback_for(_Request(**{"x-forwarded-host": "padiem-chat.pages.dev"})) == (
        CANONICAL + "/auth/shared/callback"
    )


async def test_start_login_redirects_to_the_authority_with_the_host_own_callback():
    flow = _flow(extra_origins=(PAGES,))
    response = await flow.start_login(_Request(**{"x-forwarded-host": "padiem-chat.pages.dev"}))
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://auth.padiem.net/login?")
    assert "redirect_uri=https%3A%2F%2Fpadiem-chat.pages.dev%2Fauth%2Fshared%2Fcallback" in location


def test_origin_checks_accept_both_reviewed_hosts_only():
    flow = _flow(extra_origins=(PAGES,))
    assert flow.origin_allowed(_Request(origin=CANONICAL))
    assert flow.origin_allowed(_Request(origin=PAGES))
    assert not flow.origin_allowed(_Request(origin=UNREVIEWED))
    assert not flow.origin_allowed(_Request())
