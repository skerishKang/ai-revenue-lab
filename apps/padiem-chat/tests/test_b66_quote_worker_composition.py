"""Focused regression (#3391): the B66 quote interpreter must ride the
Production-composed B14 client, never the stale pre-composition one.

worker.py replaces ``app.state.b14_client`` with the Production
``DispatchAwareB14Client`` after ``create_app``. The B66 quote interpreter was
composed inside ``create_app`` against that pre-composition client and was
never rebound, so Production quote interpretation could bypass the composed
authority entirely. This test replays the exact worker.py composition seam and
proves the real call boundary.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.b66_quote_conversation import B66QuoteConversationInterpreter
from app.config import Settings

USER = "usr_" + "a" * 32
SAVED_ID = "b66skill_" + "c" * 32
PARTIAL_MESSAGE = "대한건설에 배관 100미터, 부가세 별도"


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url="https://chat.example.test",
        session_secret="b66-b14-composition-session-secret-not-real",
        session_max_age_seconds=3600,
        live_enabled="false",
    )


def _skill() -> dict:
    return {
        "schemaVersion": 1,
        "id": "saved-skill-1",
        "name": "우리 견적서",
        "fixedDefaults": {
            "sender": {"company": "테스트상사"},
            "validDays": 30,
            "taxMode": "EXCLUSIVE",
            "memo": "",
        },
        "variableSchema": {
            "recipient": True,
            "quoteNo": True,
            "issueDate": True,
            "items": True,
            "memo": True,
            "taxMode": True,
        },
        "internalTemplate": {
            "id": "template-private",
            "title": {"text": "견 적 서"},
        },
        "approval": {"status": "approved"},
        "fingerprint": "d" * 64,
        "rendererContract": "quote-template-renderer.v1",
        "calculationAuthority": "quote-core",
    }


class _Store:
    def get_skill(self, *, user_id, workspace_id, saved_skill_id):
        if saved_skill_id != SAVED_ID or user_id != USER:
            return None
        return {
            "saved_skill_id": SAVED_ID,
            "skill_id": "saved-skill-1",
            "skill_name": "우리 견적서",
            "skill_fingerprint": "d" * 64,
            "skill_version": 1,
            "skill": _skill(),
        }


class _RecordingComposedClient:
    """DispatchAwareB14Client 자리의 호출 기록 스텁 — seam 계약은 complete 뿐."""

    def __init__(self):
        self.calls = []

    async def complete(
        self,
        messages,
        skill=None,
        additional_system_context=None,
        attachments=(),
    ):
        self.calls.append(messages)
        return {
            "answer": json.dumps(
                {
                    "recipient": {"company": "대한건설"},
                    "items": [{"name": "배관", "qty": 100}],
                    "taxMode": "EXCLUSIVE",
                    "detailGroups": [],
                },
                ensure_ascii=False,
            )
        }


def test_worker_composition_rebinds_b66_interpreter_to_production_client():
    settings = _settings()
    app = create_app(
        settings=settings,
        history_store=MagicMock(),
        b66_saved_quote_skill_store=_Store(),
    )

    pre_client = app.state.b14_client  # pre-composition client from create_app
    pre_calls = []
    original_complete = pre_client.complete

    async def record_pre(*args, **kwargs):
        pre_calls.append(args)
        return await original_complete(*args, **kwargs)

    pre_client.complete = record_pre

    # Bug condition being fixed: before the worker rebind, the interpreter
    # still holds the pre-composition client instance.
    assert app.state.b66_quote_interpreter._client is pre_client

    prod_client = _RecordingComposedClient()

    # --- verbatim worker.py composition lines (fix/3391 seam) ---
    app.state.b14_client = prod_client
    app.state.b66_quote_interpreter = B66QuoteConversationInterpreter(
        app.state.b14_client
    )
    # --- end verbatim lines ---

    assert app.state.b66_quote_interpreter._client is prod_client

    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(settings, USER),
        domain="chat.example.test",
        path="/",
    )
    response = client.post(
        "/api/b66/quote/interpret",
        json={"saved_skill_id": SAVED_ID, "message": PARTIAL_MESSAGE},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True

    candidate = body["candidate"]
    assert candidate["recipient"]["company"] == "대한건설"
    assert candidate["items"] == [{"name": "배관", "qty": 100}]
    assert "unitPrice" not in candidate["items"][0]
    assert candidate["items"][0].get("unitPrice") != 0
    assert candidate["missing"] == ["unitPrice"]

    assert len(prod_client.calls) == 1
    assert pre_calls == []
    assert app.state.b66_quote_interpreter._client is prod_client

    print("B66_INTERPRETER_USES_PRODUCTION_B14_CLIENT=YES")
    print("PRECOMPOSITION_CLIENT_CALLS=0")
    print("PRODUCTION_COMPOSED_CLIENT_CALLS=1")
    print("PARTIAL_FACTS_PRESERVED=PASS")
    print("SERVER_MISSING_UNIT_PRICE=PASS")
    print("MODEL_GUESSED_PRICE=0")


def test_worker_source_keeps_the_interpreter_rebind_in_the_composition_seam():
    """The behavioral proof above replays the seam; this keeps worker.py itself
    from drifting away from it (same source-lockstep pattern as the #3094
    composition tests)."""
    from pathlib import Path

    worker_source = (Path(__file__).resolve().parents[1] / "worker.py").read_text(encoding="utf-8")
    assert "_worker_app.state.b14_client = DispatchAwareB14Client(" in worker_source
    assert (
        "_worker_app.state.b66_quote_interpreter = B66QuoteConversationInterpreter("
        in worker_source
    )
    rebind_at = worker_source.index("_worker_app.state.b66_quote_interpreter = B66QuoteConversationInterpreter(")
    composed_at = worker_source.index("_worker_app.state.b14_client = DispatchAwareB14Client(")
    assert composed_at < rebind_at, "rebind must follow the Production client composition"
    print("WORKER_SOURCE_SEAM_LOCKSTEP=PASS")