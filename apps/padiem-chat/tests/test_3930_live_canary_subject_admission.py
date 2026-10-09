"""#3930 single-CP-subject live SSE rollout: no broad-user activation."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.claw_live_canary import canary_allowed, valid_canonical_subject
from test_b54_claw_general_p01_routing import _client, _make_adapter, _payload
from test_3930_b54_live_sse_relay import (
    SUBJECT, HEADERS, _streaming_adapter,
)

CAP="/api/claw/general/capabilities"
GENERAL="/api/claw/general"
OTHER="sub_"+"8"*32


def _session(subject):
    return SimpleNamespace(auth_session=SimpleNamespace(
        subject=SimpleNamespace(subject_id=subject)
    ))


def _probe(subject, allowlisted, *, requested=True, spoof=False):
    adapter=_streaming_adapter() if requested else _make_adapter(subject_lane=True)
    if not requested:
        adapter._runner=SimpleNamespace(run_stream=lambda *args, **kwargs: None)
    with patch(
        "app.b54_canonical_session.resolve_current_b54_canonical_session",
        new=AsyncMock(return_value=_session(subject)),
    ):
        with _client(adapter) as client:
            client.app.state.claw_live_sse_enabled=True
            client.app.state.claw_live_sse_canary_subject_id=allowlisted
            cap=client.get(CAP, headers={
                "X-Padiem-Claw-Canary-Subject":SUBJECT,
                "X-Padiem-Claw-Live":"p01-events-v1",
            } if spoof else {})
            sent=client.post(
                GENERAL,
                json=_payload(subject_id=SUBJECT, user_id="canary", canary=True)
                if spoof else _payload(),
                headers={**HEADERS, "X-Padiem-Claw-Canary-Subject":SUBJECT}
                if spoof else HEADERS if requested else {},
            )
    return adapter,cap,sent


def test_selected_subject_is_only_true_capability_and_live_runner():
    adapter,cap,response=_probe(SUBJECT,SUBJECT)
    assert cap.json()=={"live_events_available":True}
    assert response.status_code==200
    assert response.text.count("event: done")==1
    adapter.execute.assert_awaited_once()
    assert adapter.execute.await_args.kwargs["subject_id"]==SUBJECT


def test_missing_canary_subject_fails_closed_even_with_true_live_flag():
    for missing in (None,"", "not-a-subject"):
        adapter,cap,response=_probe(SUBJECT,missing)
        assert cap.json()=={"live_events_available":False}
        assert response.status_code==503
        assert response.json()["error"]["code"]=="claw_live_stream_unavailable"
        adapter.execute.assert_not_awaited()


def test_unselected_authenticated_subject_gets_legacy_answer_not_live():
    # Pre-dispatch probe is negative; the browser therefore uses its old POST.
    adapter,cap,response=_probe(OTHER,SUBJECT,requested=False)
    assert cap.json()=={"live_events_available":False}
    assert response.status_code==200
    assert "event: delta" in response.text
    assert "event: p01_event" not in response.text
    assert "event: done" in response.text
    adapter.execute.assert_awaited_once()
    assert "on_event" not in adapter.execute.await_args.kwargs


def test_other_user_forging_live_header_body_or_canary_header_gets_zero_dispatch():
    adapter,cap,response=_probe(OTHER,SUBJECT,spoof=True)
    assert cap.json()=={"live_events_available":False}
    assert response.status_code==503
    assert "sub_" not in response.text
    adapter.execute.assert_not_awaited()


def test_allowlist_mismatch_cannot_reach_stream_even_if_get_preflight_is_stale():
    adapter,cap,response=_probe(OTHER,SUBJECT)
    assert cap.json()=={"live_events_available":False}
    assert response.status_code==503
    adapter.execute.assert_not_awaited()


def test_server_secret_validation_and_constant_time_match_are_bounded():
    assert canary_allowed(SimpleNamespace(
        claw_live_sse_enabled=True,
        claw_live_sse_canary_subject_id=SUBJECT,
    ),SUBJECT)
    for fake in ("sub_", "sub_123", "sub_"+"a"*200, "sub_"+"0"*15+"!", 34, None):
        assert not valid_canonical_subject(fake)
        assert not canary_allowed(SimpleNamespace(
            claw_live_sse_enabled=True,
            claw_live_sse_canary_subject_id=SUBJECT,
        ),fake)
    assert not canary_allowed(SimpleNamespace(
        claw_live_sse_enabled=False,
        claw_live_sse_canary_subject_id=SUBJECT,
    ),SUBJECT)


def test_plain_flag_never_admits_a_user_without_secret_allowlist():
    from app.app_factory import create_app
    app=create_app()
    assert app.state.claw_live_sse_enabled is False
    assert app.state.claw_live_sse_canary_subject_id is None


def test_worker_requires_server_owned_secret_and_exact_flag():
    from pathlib import Path
    worker=(Path(__file__).resolve().parents[1]/"worker.py").read_text(encoding="utf-8")
    assert 'getattr(self.env, "PADIEM_CLAW_P01_LIVE_CANARY_SUBJECT_ID", None)' in worker
    assert 'getattr(self.env, "PADIEM_CLAW_P01_LIVE_SSE_ENABLED", None) == "true"' in worker
    assert '_worker_app.state.claw_live_sse_canary_subject_id is not None' in worker
