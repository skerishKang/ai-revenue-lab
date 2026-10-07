"""Central same-origin browser contract for cookie-authenticated mutations (#3476).

These tests pin the one reviewed origin-isolation policy in
``app.same_origin_guard``: exact same-origin enforcement (scheme + host +
port) for browser mutations authenticated by the Padiem Chat session cookie,
JSON content-type binding, explicit server-to-server exemptions, and the
preservation of every existing auth/error semantic around it.
"""

from __future__ import annotations

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.claw_local_task_result_routes import CLAW_LOCAL_TASK_RESULT_PATH
from app.config import Settings
from app.main import create_app
from app.orchestration_routes import install_orchestration_routes
from app.request_telemetry import RequestTelemetryMiddleware
from app.same_origin_guard import (
    JSON_CONTENT_TYPE_REQUIRED_CODE,
    ORIGIN_GUARD_UNAVAILABLE_CODE,
    ORIGIN_REJECTED_CODE,
    SameOriginGuardMiddleware,
    expected_browser_origin,
    is_local_runner_result_ingress,
)

ORIGIN = "https://chat.example.test"
# Same registrable domain, different origin: must be denied.
SAME_SITE_OTHER_ORIGIN = "https://app.example.test"
# Totally cross-site origin: must be denied.
CROSS_SITE_ORIGIN = "https://evil.example.test"

# Derived from the ingress route's own path template, so a route rename moves
# these paths too instead of stranding the exemption.
CANONICAL_LOCAL_RESULT_PATH = CLAW_LOCAL_TASK_RESULT_PATH.replace("{run_id}", "run_" + "0" * 32)

# conftest attaches the reviewed Origin to every ASGI mutation so unrelated
# tests keep representing real browser traffic; this marker opts out of that
# injection to observe a browser that sent no Origin.
SUPPRESS_ORIGIN_HEADER = "X-Test-No-Origin"

# ``/api/auth/logout`` answers 200 or the session's own 401 and never emits
# these, so any of them on a read method can only have come from the guard.
_GUARD_DENIAL_STATUSES = frozenset({403, 415, 503})

OWNER_ID = "usr_" + "4" * 32
SESSION_SECRET = "issue-3476-same-origin-guard-session-secret-000000000000"


def _settings(*, public_base_url: str | None = ORIGIN, auth_mode: str = "google") -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode=auth_mode,
        public_base_url=public_base_url,
        google_client_id="unit-test-client.apps.googleusercontent.com",
        google_client_secret="unit-test-secret",
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )


class _AuthReadyStore:
    """Minimal store: auth_ready() needs a non-None store; guarded routes
    answer with their own auth semantics before any store use."""

    async def get_user(self, user_id: str):
        return None

    async def list_projects(self, user_id: str):
        return []


def _app(settings: Settings | None = None):
    return create_app(settings=settings or _settings(), history_store=_AuthReadyStore())


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN)


def _authenticated(app) -> httpx.AsyncClient:
    client = _client(app)
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(_settings(), OWNER_ID),
        domain="chat.example.test",
        path="/",
    )
    return client


def _code(response: httpx.Response) -> str:
    return response.json()["error"]["code"]


async def test_exact_expected_origin_with_cookie_and_json_passes() -> None:
    app = _app()
    async with _authenticated(app) as client:
        response = await client.post(
            "/api/auth/logout",
            headers={"Origin": ORIGIN},
            json={},
        )
    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def test_same_site_but_cross_origin_mutation_is_denied() -> None:
    app = _app()
    async with _authenticated(app) as client:
        response = await client.post(
            "/api/auth/logout",
            headers={"Origin": SAME_SITE_OTHER_ORIGIN},
            json={},
        )
    assert response.status_code == 403
    assert _code(response) == ORIGIN_REJECTED_CODE
    assert response.json()["error"]["message"] == "요청 출처를 확인할 수 없습니다."


async def test_totally_cross_site_origin_mutation_is_denied() -> None:
    app = _app()
    async with _authenticated(app) as client:
        response = await client.post(
            "/api/auth/logout",
            headers={"Origin": CROSS_SITE_ORIGIN},
            json={},
        )
    assert response.status_code == 403
    assert _code(response) == ORIGIN_REJECTED_CODE


async def test_missing_origin_on_cookie_authenticated_mutation_is_denied() -> None:
    app = _app()
    async with _authenticated(app) as client:
        response = await client.post(
            "/api/auth/logout",
            headers={SUPPRESS_ORIGIN_HEADER: "1"},
            json={},
        )
    assert response.status_code == 403
    assert _code(response) == ORIGIN_REJECTED_CODE


async def test_non_json_content_type_on_json_mutation_is_denied() -> None:
    app = _app()
    async with _authenticated(app) as client:
        response = await client.post(
            "/api/auth/logout",
            headers={"Origin": ORIGIN, "Content-Type": "text/plain"},
            content=b"{}",
        )
    assert response.status_code == 415
    assert _code(response) == JSON_CONTENT_TYPE_REQUIRED_CODE


async def test_server_to_server_telegram_ingress_is_explicitly_exempt() -> None:
    """The Telegram webhook keeps its own proof authority: no browser Origin."""
    app = _app()
    async with _authenticated(app) as client:
        response = await client.post(
            "/api/claw/telegram/ingest/test-binding-ref",
            headers={SUPPRESS_ORIGIN_HEADER: "1"},
            json={"update_id": 1},
        )
    assert response.status_code == 503
    assert _code(response) == "telegram_ingest_not_configured"
    assert _code(response) != ORIGIN_REJECTED_CODE


async def test_server_to_server_local_runner_ingress_is_explicitly_exempt() -> None:
    """Trusted Local Runner result ingress keeps its own run/owner authority.

    The path is the canonical family built from the route template: the narrowing
    must remove unrelated suffix matches without closing this ingress off.
    """
    app = _app()
    async with _authenticated(app) as client:
        response = await client.post(
            CANONICAL_LOCAL_RESULT_PATH,
            headers={SUPPRESS_ORIGIN_HEADER: "1"},
            json={"status": "succeeded"},
        )
    assert response.status_code == 503
    assert _code(response) == "local_runner_result_unconfigured"
    assert _code(response) != ORIGIN_REJECTED_CODE


async def test_route_auth_failure_semantics_are_unchanged_after_the_guard() -> None:
    """Guard first, then the route's existing auth answer — unchanged 401."""
    app = _app()
    async with _client(app) as client:
        client.cookies.set(
            SESSION_COOKIE,
            "forged.session.token",
            domain="chat.example.test",
            path="/",
        )
        response = await client.post(
            "/api/projects",
            headers={"Origin": ORIGIN},
            json={"name": "보안 점검"},
        )
    assert response.status_code == 401
    assert _code(response) == "unauthorized"


async def test_unauthenticated_mutation_keeps_existing_auth_semantics() -> None:
    """No session cookie means no ambient authority: the route, not the guard,
    answers with its existing vocabulary."""
    app = _app()
    async with _client(app) as client:
        response = await client.post(
            "/api/projects",
            headers={SUPPRESS_ORIGIN_HEADER: "1"},
            json={"name": "익명 요청"},
        )
    assert response.status_code == 401
    assert _code(response) == "unauthorized"


async def test_read_only_route_is_not_blocked_without_origin() -> None:
    app = _app()
    async with _authenticated(app) as client:
        response = await client.get(
            "/api/auth/status",
            headers={SUPPRESS_ORIGIN_HEADER: "1"},
        )
    assert response.status_code == 200


async def test_guard_fails_closed_when_expected_origin_is_unconfigured() -> None:
    """No reviewed expectation (auth off + no public_base_url) never degrades
    into an implicit allow."""
    settings = _settings(public_base_url=None, auth_mode="off")
    app = _app(settings)
    async with _authenticated(app) as client:
        response = await client.post(
            "/api/auth/logout",
            headers={"Origin": ORIGIN},
            json={},
        )
    assert response.status_code == 503
    assert _code(response) == ORIGIN_GUARD_UNAVAILABLE_CODE


def test_expected_origin_derives_only_from_reviewed_server_config() -> None:
    # Direct dataclass construction: this pins the guard's own derivation,
    # independent of Settings.from_values config validation.
    assert expected_browser_origin(Settings(public_base_url=ORIGIN)) == ORIGIN
    # Non-https or empty values are not a usable reviewed expectation.
    assert expected_browser_origin(Settings(public_base_url="http://chat.example.test")) is None
    assert expected_browser_origin(Settings(public_base_url="")) is None
    assert expected_browser_origin(Settings()) is None
    # Only the configured origin root counts; a path can never widen it.
    assert (
        expected_browser_origin(Settings(public_base_url="https://chat.example.test/path"))
        == ORIGIN
    )


def test_guard_is_installed_by_the_composition_root() -> None:
    """The real #3476 defect was an unwired guard: the module existed but nothing
    installed it, so every denial below would have passed in Production.
    Starlette prepends middleware, so telemetry must be added last to stay
    outermost and still observe guard rejections.
    """
    assert [layer.cls for layer in _app().user_middleware] == [
        RequestTelemetryMiddleware,
        SameOriginGuardMiddleware,
    ]


async def test_guard_rejection_is_recorded_by_telemetry() -> None:
    events: list[dict[str, object]] = []
    app = create_app(
        settings=_settings(),
        history_store=_AuthReadyStore(),
        telemetry_emitter=events.append,
    )
    async with _authenticated(app) as client:
        response = await client.post(
            "/api/projects",
            headers={"Origin": SAME_SITE_OTHER_ORIGIN},
            json={"name": "보안 점검"},
        )
    assert response.status_code == 403
    assert any(event.get("status") == 403 for event in events)


async def test_denial_is_not_limited_to_the_logout_route() -> None:
    """One middleware covers the mutation surface, not one reviewed route."""
    app = _app()
    async with _authenticated(app) as client:
        response = await client.post(
            "/api/projects",
            headers={"Origin": SAME_SITE_OTHER_ORIGIN},
            json={"name": "보안 점검"},
        )
    assert response.status_code == 403
    assert _code(response) == ORIGIN_REJECTED_CODE


async def test_json_media_type_with_charset_is_accepted() -> None:
    app = _app()
    async with _authenticated(app) as client:
        response = await client.post(
            "/api/auth/logout",
            headers={"Origin": ORIGIN, "Content-Type": "application/json; charset=utf-8"},
            content=b"{}",
        )
    assert response.status_code == 200


async def test_form_encoded_mutation_is_denied_without_reaching_the_route() -> None:
    app = _app()
    async with _authenticated(app) as client:
        response = await client.post(
            "/api/projects",
            headers={"Origin": ORIGIN},
            data={"name": "폼 요청"},
        )
    assert response.status_code == 415
    assert _code(response) == JSON_CONTENT_TYPE_REQUIRED_CODE


@pytest.mark.parametrize(
    "origin",
    [
        "http://chat.example.test",  # scheme downgrade
        "https://chat.example.test.attacker.example",  # lookalike suffix
        "https://chat.example.test:8443",  # port mismatch
        "https://chat.example.test/",  # trailing path separator
        "null",  # opaque origin
    ],
)
async def test_only_the_exact_reviewed_origin_is_accepted(origin: str) -> None:
    app = _app()
    async with _authenticated(app) as client:
        response = await client.post(
            "/api/auth/logout",
            headers={"Origin": origin},
            json={},
        )
    assert response.status_code == 403
    assert _code(response) == ORIGIN_REJECTED_CODE


async def test_read_only_methods_keep_route_semantics_without_origin() -> None:
    """HEAD/OPTIONS are not mutation subjects. The exact status belongs to the
    router (the static Mount answers an unmatched HEAD with 404), so the
    load-bearing claim is that the guard never answers a read method — a denial
    on OPTIONS would break every browser preflight. The same request shape as a
    POST is denied, which is what keeps this assertion from being vacuous."""
    app = _app()
    async with _authenticated(app) as client:
        head = await client.head("/api/auth/logout", headers={SUPPRESS_ORIGIN_HEADER: "1"})
        options = await client.options("/api/auth/logout", headers={SUPPRESS_ORIGIN_HEADER: "1"})
        post = await client.post(
            "/api/auth/logout",
            headers={SUPPRESS_ORIGIN_HEADER: "1"},
            json={},
        )
    assert head.status_code not in _GUARD_DENIAL_STATUSES
    assert options.status_code not in _GUARD_DENIAL_STATUSES
    assert post.status_code == 403
    assert _code(post) == ORIGIN_REJECTED_CODE


async def test_routes_installed_after_create_app_are_also_guarded() -> None:
    """``install_orchestration_routes`` inserts into the router after the app is
    built; the router sits inside the guard, so a late mutation route cannot
    escape the policy."""
    app = _app()
    install_orchestration_routes(app, None)
    async with _authenticated(app) as client:
        response = await client.post(
            "/api/orchestration",
            headers={SUPPRESS_ORIGIN_HEADER: "1"},
            json={},
        )
    assert response.status_code == 403
    assert _code(response) == ORIGIN_REJECTED_CODE


async def test_exempt_ingress_is_path_specific_not_a_blanket_bypass() -> None:
    """Same app and same session cookie: the named ingress route keeps its own
    proof authority, while a non-exempt mutation is still denied."""
    app = _app()
    async with _authenticated(app) as client:
        exempt = await client.post(
            "/api/claw/telegram/ingest/test-binding-ref",
            headers={SUPPRESS_ORIGIN_HEADER: "1"},
            json={"update_id": 1},
        )
        guarded = await client.post(
            "/api/claw/automation/rules",
            headers={SUPPRESS_ORIGIN_HEADER: "1"},
            json={},
        )
    assert exempt.status_code == 503
    assert _code(exempt) == "telegram_ingest_not_configured"
    assert guarded.status_code == 403
    assert _code(guarded) == ORIGIN_REJECTED_CODE


@pytest.mark.parametrize(
    ("path", "exempt"),
    [
        (CANONICAL_LOCAL_RESULT_PATH, True),
        ("/api/projects/proj_1/local-result", False),
        ("/api/claw/local-result", False),
        ("/local-result", False),
        ("/api/claw/runs//local-result", False),
        ("/api/claw/runs/run_1/children/local-result", False),
        ("/api/claw/runs/run_1/local-results", False),
    ],
)
def test_local_result_exemption_is_the_canonical_route_family_only(
    path: str,
    exempt: bool,
) -> None:
    """The exemption used to be a bare ``endswith("/local-result")``, which let
    any unrelated cookie-authenticated route sharing that last segment escape the
    origin check. Only one non-empty run-id segment inside the canonical family
    is exempt; the run-id shape itself stays the route's authority."""
    assert is_local_runner_result_ingress(path) is exempt


def test_local_result_exemption_follows_the_route_path_template() -> None:
    """The family is derived from ``CLAW_LOCAL_TASK_RESULT_PATH`` rather than a
    second hardcoded literal, so a route rename cannot silently widen or strand
    the exemption."""
    assert CLAW_LOCAL_TASK_RESULT_PATH.count("{run_id}") == 1
    assert is_local_runner_result_ingress(
        CLAW_LOCAL_TASK_RESULT_PATH.replace("{run_id}", "any-single-segment")
    )


async def test_unrelated_local_result_suffix_mutation_is_denied() -> None:
    """End-to-end proof of the narrowing: before it this path was exempt and fell
    through to the router (404); now the guard denies the cookie mutation."""
    app = _app()
    async with _authenticated(app) as client:
        response = await client.post(
            "/api/projects/proj_1/local-result",
            headers={SUPPRESS_ORIGIN_HEADER: "1"},
            json={},
        )
    assert response.status_code == 403
    assert _code(response) == ORIGIN_REJECTED_CODE

