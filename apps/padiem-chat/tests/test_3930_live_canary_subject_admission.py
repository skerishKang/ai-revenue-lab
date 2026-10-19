"""#3930 public live SSE for all canonical signed-in USERs, no canary secret."""
from __future__ import annotations
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.claw_live_canary import live_stream_allowed, valid_canonical_subject
from test_b54_claw_general_p01_routing import _client, _make_adapter, _payload
from test_3930_b54_live_sse_relay import SUBJECT, HEADERS, _streaming_adapter

CAP = "/api/claw/general/capabilities"
GENERAL = "/api/claw/general"
OTHER = "sub_" + "8" * 32


def _session(subject):
    return SimpleNamespace(auth_session=SimpleNamespace(
        subject=SimpleNamespace(subject_id=subject)
    ))


def _probe(subject, *, requested=True, spoof=False, enabled=True, cp_valid=True):
    adapter = _streaming_adapter() if requested else _make_adapter(subject_lane=True)
    if not requested:
        adapter._runner = SimpleNamespace(run_stream=lambda *args, **kwargs: None)
    with patch(
        "app.b54_canonical_session.resolve_current_b54_canonical_session",
        new=AsyncMock(return_value=_session(subject) if cp_valid else None),
    ):
        with _client(adapter) as client:
            client.app.state.claw_live_sse_enabled = enabled
            cap = client.get(CAP, headers={
                "X-Padiem-Claw-Canary-Subject": SUBJECT,
                "X-Padiem-Claw-Live": "p01-events-v1",
            } if spoof else {})
            sent = client.post(
                GENERAL,
                json=_payload(subject_id=SUBJECT, user_id="spoof", canary=True)
                if spoof else _payload(),
                headers={**HEADERS, "X-Padiem-Claw-Canary-Subject": SUBJECT}
                if spoof else HEADERS if requested else {},
            )
    return adapter, cap, sent


def test_all_authenticated_canonical_users_have_capability_without_allowlist():
    for subject in (SUBJECT, OTHER):
        adapter, cap, response = _probe(subject)
        assert cap.json() == {"live_events_available": True}
        assert response.status_code == 200
        assert response.text.count("event: done") == 1
        adapter.execute.assert_awaited_once()
        assert adapter.execute.await_args.kwargs["subject_id"] == subject


def test_missing_or_invalid_canonical_subject_fails_closed_even_with_true_flag():
    for subject in (None, "", "not-a-subject"):
        adapter, cap, response = _probe(subject)
        assert cap.json() == {"live_events_available": False}
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "claw_live_stream_unavailable"
        adapter.execute.assert_not_awaited()


def test_unauthenticated_or_revoked_cp_session_never_dispatches():
    adapter, cap, response = _probe(SUBJECT, cp_valid=False)
    assert cap.json() == {"live_events_available": False}
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "canonical_b54_session_unavailable"
    adapter.execute.assert_not_awaited()


def test_other_authenticated_user_cannot_impersonate_via_body_or_headers():
    adapter, cap, response = _probe(OTHER, spoof=True)
    assert cap.json() == {"live_events_available": True}
    assert response.status_code == 200
    assert response.text.count("event: done") == 1
    adapter.execute.assert_awaited_once()
    assert adapter.execute.await_args.kwargs["subject_id"] == OTHER


def test_server_flag_is_global_but_disabled_flag_denies_before_dispatch():
    adapter, cap, response = _probe(OTHER, enabled=False)
    assert cap.json() == {"live_events_available": False}
    assert response.status_code == 503
    adapter.execute.assert_not_awaited()


def test_legacy_post_stays_legacy_for_any_authenticated_user():
    adapter, cap, response = _probe(OTHER, requested=False)
    assert cap.json() == {"live_events_available": True}
    assert response.status_code == 200
    assert "event: p01_event" not in response.text
    assert "event: done" in response.text
    adapter.execute.assert_awaited_once()
    assert "on_event" not in adapter.execute.await_args.kwargs


def test_canonical_subject_validation_and_server_flag_without_secret():
    assert live_stream_allowed(SimpleNamespace(claw_live_sse_enabled=True), SUBJECT)
    assert live_stream_allowed(SimpleNamespace(claw_live_sse_enabled=True), OTHER)
    for invalid in ("sub_", "sub_123", "sub_"+"a"*200, "sub_"+"0"*15+"!", 34, None):
        assert not valid_canonical_subject(invalid)
        assert not live_stream_allowed(SimpleNamespace(claw_live_sse_enabled=True), invalid)
    assert not live_stream_allowed(SimpleNamespace(claw_live_sse_enabled=False), SUBJECT)


def test_worker_does_not_depend_on_single_subject_secret():
    from pathlib import Path
    from app.app_factory import create_app
    app = create_app()
    assert app.state.claw_live_sse_enabled is False
    assert not hasattr(app.state, "claw_live_sse_canary_subject_id")
    worker = (Path(__file__).resolve().parents[1] / "worker.py").read_text(encoding="utf-8")
    assert "PADIEM_CLAW_P01_LIVE_CANARY_SUBJECT_ID" not in worker
    assert 'getattr(self.env, "PADIEM_CLAW_P01_LIVE_SSE_ENABLED", None) == "true"' in worker
    assert 'subject_identity_lane' in worker
