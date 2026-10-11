"""#3566 — B54 read-only pre-dispatch isolation without provider calls.

This GET-only diagnostic does not submit a Claw task, access quotas, issue
a CP Admission request, read history, or call a model.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.auth import SESSION_COOKIE
from app.b54_canonical_session import resolve_current_b54_canonical_session

import test_b54_claw_general_p01_routing as base


CAPABILITY = "/api/claw/general/capabilities"
DIAGNOSTIC = CAPABILITY + "?diagnostic=pre_dispatch_v1"
EXPECTED_SCOPE = "auth_adapter_session_only"


def _assert_bounded(result, expected):
    assert result.status_code == 200
    data = result.json()
    assert data == {
        "live_events_available": False,
        "pre_dispatch_status": expected,
        "pre_dispatch_scope": EXPECTED_SCOPE,
    }
    assert result.headers["cache-control"].startswith("no-store")
    for private in ("usr_", "sub_", "tenant_", "secret", "token", "exception"):
        assert private not in result.text


def test_default_browser_get_remains_byte_shape_and_does_not_query_cp():
    adapter = base._make_adapter(subject_lane=True)
    with patch("app.b54_canonical_session.resolve_current_b54_canonical_session",
               new_callable=AsyncMock) as cp:
        with base._client(adapter) as client:
            result = client.get(CAPABILITY)
    assert result.status_code == 200
    assert result.json() == {"live_events_available": False}
    cp.assert_not_awaited()
    adapter.execute.assert_not_awaited()


def test_anonymous_diagnostic_never_queries_cp_or_dispatches():
    adapter = base._make_adapter(subject_lane=True)
    with patch("app.b54_canonical_session.resolve_current_b54_canonical_session",
               new_callable=AsyncMock) as cp:
        with base._client(adapter) as client:
            client.cookies.clear()
            result = client.get(DIAGNOSTIC)
    _assert_bounded(result, "authentication_required")
    cp.assert_not_awaited()
    adapter.execute.assert_not_awaited()


def test_authenticated_missing_adapter_diagnostic():
    with base._client(None) as client:
        result = client.get(DIAGNOSTIC)
    _assert_bounded(result, "p01_adapter_unavailable")


def test_noncanonical_adapter_not_called_and_not_claimed_ready():
    adapter = base._make_adapter(subject_lane=False)
    with patch("app.b54_canonical_session.resolve_current_b54_canonical_session",
               new_callable=AsyncMock) as cp:
        with base._client(adapter) as client:
            result = client.get(DIAGNOSTIC)
    _assert_bounded(result, "canonical_subject_lane_unverified")
    cp.assert_not_awaited()
    adapter.execute.assert_not_awaited()


def test_missing_canonical_session_is_visible_only_as_safe_fixed_class():
    adapter = base._make_adapter(subject_lane=True)
    resolver = AsyncMock(return_value=None)
    with patch("app.b54_canonical_session.resolve_current_b54_canonical_session", resolver):
        with base._client(adapter) as client:
            result = client.get(DIAGNOSTIC + "&subject_id=sub_forged&user_id=usr_forged")
    _assert_bounded(result, "canonical_b54_session_unavailable")
    resolver.assert_awaited_once()
    adapter.execute.assert_not_awaited()


def test_control_plane_exception_is_bounded_and_not_leaked():
    adapter = base._make_adapter(subject_lane=True)
    resolver = AsyncMock(side_effect=RuntimeError("private-control-plane-token-42"))
    with patch("app.b54_canonical_session.resolve_current_b54_canonical_session", resolver):
        with base._client(adapter) as client:
            result = client.get(DIAGNOSTIC)
    _assert_bounded(result, "canonical_b54_session_unavailable")
    resolver.assert_awaited_once()
    adapter.execute.assert_not_awaited()


def test_valid_canonical_session_is_pre_quota_only_not_provider_ready():
    adapter = base._make_adapter(subject_lane=True)
    session = SimpleNamespace(
        auth_session=SimpleNamespace(subject=SimpleNamespace(subject_id="sub_private"))
    )
    resolver = AsyncMock(return_value=session)
    with patch("app.b54_canonical_session.resolve_current_b54_canonical_session", resolver):
        with base._client(adapter) as client:
            result = client.get(DIAGNOSTIC)
    _assert_bounded(result, "pre_quota_ready")
    resolver.assert_awaited_once()
    adapter.execute.assert_not_awaited()


def test_readonly_capability_resolves_cp_at_most_once_with_live_flag():
    adapter = base._make_adapter(subject_lane=True)
    session = SimpleNamespace(
        auth_session=SimpleNamespace(subject=SimpleNamespace(subject_id="sub_safe"))
    )
    resolver = AsyncMock(return_value=session)
    with patch("app.b54_canonical_session.resolve_current_b54_canonical_session", resolver):
        with patch("app.claw_general_routes.live_stream_allowed", return_value=False) as allowed:
            with base._client(adapter) as client:
                client.app.state.claw_live_sse_enabled = True
                result = client.get(DIAGNOSTIC)
    _assert_bounded(result, "pre_quota_ready")
    resolver.assert_awaited_once()
    allowed.assert_called_once()
    adapter.execute.assert_not_awaited()


def test_unrequested_other_query_does_not_trigger_diagnostic():
    adapter = base._make_adapter(subject_lane=True)
    with patch("app.b54_canonical_session.resolve_current_b54_canonical_session",
               new_callable=AsyncMock) as cp:
        with base._client(adapter) as client:
            result = client.get(CAPABILITY + "?diagnostic=unknown")
    assert result.json() == {"live_events_available": False}
    cp.assert_not_awaited()
