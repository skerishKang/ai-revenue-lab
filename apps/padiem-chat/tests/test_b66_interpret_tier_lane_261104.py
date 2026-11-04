"""B66 interpret must dispatch on a grade key alone, on both hosts (#6835 follow-up).

#6828 removed the model identity from the browser, #6835 made the grade key the
user path, and #6838 keeps reasoning decisions inside B14. Those three leave the
chat server as the only place a grade may be paired with a model, so this file
drives the outermost boundary — the HTTP route and the composed host lane — and
never a hand-assembled interpreter.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from app.b66_grade_models import B66_ADMIN_GRADE, B66_GRADE_MODEL_IDS
from app.b66_quote_conversation import B66QuoteConversationInterpreter
from app.b66_registered_model_boundary import (
    B14AuthorizedModelRoute,
    B14QuoteExactModelExecutor,
    B66ModelRouteError,
    B66RegisteredModelCompletion,
)

from test_b66_quote_runtime import SAVED_ID, _Store, _client

CANDIDATE = {
    "recipient": {"company": "대한건설"},
    "items": [{"name": "배관", "qty": 100}],
    "missing": ["unitPrice"],
}


class _RecordingExecutor:
    """Stands in for the B14 exact-model executor and records each dispatch."""

    supports_native_parameters = False

    def __init__(self):
        self.calls = []

    def ensure_runtime_available(self):
        return None

    async def execute_quote_text(self, *, route, messages, additional_system_context,
                                 requirements, model_parameters=None, product_tier=None):
        self.calls.append({"model_id": route.model_id, "product_tier": product_tier,
                           "max_retries": requirements.max_retries,
                           "allow_external_fallback": requirements.allow_external_fallback})
        # The real executor echoes the model that answered; the boundary refuses
        # any answer that names a different route than the one it selected.
        return {"answer": json.dumps(CANDIDATE, ensure_ascii=False),
                "request_id": "synthetic-b14-request",
                "route": {"mode": "manual", "model": route.model_id}}


class _RouteResolver:
    def __init__(self):
        self.requests = []

    async def resolve_quote_model(self, requirements):
        self.requests.append(requirements.selected_model_id)
        return B14AuthorizedModelRoute(
            model_id=requirements.selected_model_id,
            route_id="test-fixture/route",
            owner_policy_id="test-fixture/policy",
            registered=True, enabled=True, authorized=True, credential_ready=True,
            route_count=1, capabilities=frozenset(("chat",)),
        )


class _HostLegacyClient:
    """The signature the CPython host left in front of the interpreter."""

    async def complete(self, messages, skill=None, additional_system_context=None,
                       attachments=()):
        raise AssertionError("unreachable: the caller cannot pass a model selection")


def _lane():
    resolver = _RouteResolver()
    executor = _RecordingExecutor()
    refunds = []

    async def refund():
        refunds.append(1)
        return True

    interpreter = B66QuoteConversationInterpreter(B66RegisteredModelCompletion(
        resolver=resolver, executor=executor, refund_pre_dispatch=refund,
    ))
    return interpreter, resolver, executor, refunds


def _app(*, member_tier=None):
    interpreter, _resolver, executor, refunds = _lane()
    client = _client(_Store(), interpreter)

    class _MemberStore:
        async def runtime_access(self, user_id):
            return None if member_tier is None else {
                "status": "approved", "tier": member_tier,
                "active_policy": False, "model_ids": [], "disabled_models": [],
            }

        async def is_google_admin(self, user_id):
            return False

    client.app.state.b66_member_admin_store = _MemberStore()
    return client, executor, refunds


def _interpret(client, tier):
    return client.post(
        "/api/b66/quote/interpret",
        json={"saved_skill_id": SAVED_ID,
              "message": "대한건설에 배관 100미터, 부가세 별도",
              "tier": tier},
    )


@pytest.mark.parametrize("grade", ("free", "plus"))
def test_grade_key_alone_dispatches_exactly_once_to_the_registered_lane(grade):
    client, executor, _refunds = _app()
    response = _interpret(client, grade)
    assert response.status_code == 200, response.text
    assert len(executor.calls) == 1
    assert executor.calls[0]["product_tier"] == grade
    # The grade resolves through the single shared map, not a local table.
    assert executor.calls[0]["model_id"] == B66_GRADE_MODEL_IDS[grade]
    assert executor.calls[0]["max_retries"] == 0
    assert executor.calls[0]["allow_external_fallback"] is False
    assert response.json()["candidate"]["items"][0]["qty"] == 100
    # #6828: no model identity crosses back to the browser.
    assert "model_id" not in json.dumps(response.json())


def test_admin_grade_is_refused_without_an_admin_authority():
    client, executor, _refunds = _app()
    response = _interpret(client, B66_ADMIN_GRADE)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "admin_forbidden"
    assert executor.calls == []


def test_a_grade_above_the_verified_member_grade_is_refused_before_dispatch():
    client, executor, _refunds = _app(member_tier="PLUS")
    allowed = _interpret(client, "plus")
    assert allowed.status_code == 200, allowed.text
    assert len(executor.calls) == 1

    refused = _interpret(client, "max")
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "tier_not_available"
    assert len(executor.calls) == 1


def test_a_paid_grade_is_not_rejected_by_the_free_primary_guard():
    """#6835 sends a tier label for every grade; #2505 only binds the free one."""
    for grade in ("plus", "pro", "max"):
        resolver, executor = _RouteResolver(), _RecordingExecutor()
        completion = B66RegisteredModelCompletion(
            resolver=resolver, executor=executor, refund_pre_dispatch=None,
        )
        result = asyncio.run(completion.complete(
            [{"role": "user", "content": "배관 100미터"}],
            None, None, (),
            model_id=B66_GRADE_MODEL_IDS[grade], product_tier=grade,
        ))
        assert json.loads(result["answer"])["items"][0]["qty"] == 100
        assert executor.calls[-1]["product_tier"] == grade

    for bad in (
        {"model_id": B66_GRADE_MODEL_IDS["plus"], "product_tier": "free"},
        {"model_id": B66_GRADE_MODEL_IDS["free"], "product_tier": "not-a-grade"},
    ):
        completion = B66RegisteredModelCompletion(
            resolver=_RouteResolver(), executor=_RecordingExecutor(), refund_pre_dispatch=None,
        )
        with pytest.raises(B66ModelRouteError) as caught:
            asyncio.run(completion.complete(
                [{"role": "user", "content": "배관 100미터"}], None, None, (), **bad))
        assert caught.value.code == "model_identity_invalid"


def test_an_interpreter_failure_leaves_server_stage_evidence(monkeypatch):
    from app import request_telemetry

    events = []
    # Capture what the log channel actually receives, through the real
    # emit_stage_event path rather than by stubbing the caller's reference.
    monkeypatch.setattr(request_telemetry, "default_emitter", events.append)

    # Exactly the host shape that produced the Production 502: a client whose
    # .complete cannot carry an exact model selection.
    interpreter = B66QuoteConversationInterpreter(_HostLegacyClient())
    client = _client(_Store(), interpreter)
    response = _interpret(client, "free")
    assert response.status_code == 502
    assert response.headers["x-b66-interpret-failure-stage"] == "interpreter_exception"
    assert response.headers["x-b66-interpret-exception-family"] == "type_error"
    stages = [event for event in events if event.get("event") == "ai_stage"]
    assert [event["stage"] for event in stages] == ["b66.interpret.interpreter_exception"]
    assert stages[0]["outcome"] == "error"
    # The log carries the closed labels only — never an exception message.
    assert stages[0]["code"] == "type_error"
    assert stages[0]["model"] is None and stages[0]["provider"] is None
    assert all("message" not in event and "detail" not in event for event in stages)


def test_cpython_host_composes_the_same_trusted_facade_as_the_worker(monkeypatch, tmp_path):
    from app import local_cpython
    from app.dispatch_quota import DispatchAwareB14Client, _refund_active_reservation

    class _Transport:
        pass

    monkeypatch.setattr(local_cpython, "compose_local_b14_transports",
                        lambda settings, proof: (_Transport(), _Transport()))
    monkeypatch.setenv("PADIEM_CHAT_CPYTHON_HOST", "1")
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "b14")
    monkeypatch.setenv("PADIEM_CHAT_AUTH_MODE", "off")
    monkeypatch.setenv("PADIEM_CHAT_WEB_PROVIDER", "off")
    monkeypatch.setenv("PADIEM_CHAT_PUBLIC_BASE_URL", "https://chat-com2-staging.padiem.net")
    monkeypatch.setenv("PADIEM_CHAT_B14_BASE_URL", "https://b14.example")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PADIEM_CHAT_SESSION_SECRET", "test-local-secret-0123456789abcdef")

    app = local_cpython.build_app()

    assert isinstance(app.state.b14_client, DispatchAwareB14Client)
    facade = app.state.b66_quote_interpreter._client
    assert isinstance(facade, B66RegisteredModelCompletion)
    assert facade._resolver is app.state.b66_quote_model_resolver
    assert isinstance(facade._executor, B14QuoteExactModelExecutor)
    assert facade._executor._client is app.state.b14_client
    assert facade._refund_pre_dispatch is _refund_active_reservation
    assert app.state.b66_reasoning_transport_supported is bool(
        facade._executor.supports_native_parameters
    )
    # The client the host captured while building the app could not carry an
    # exact model selection; the facade is what makes the grade path execute.
    assert not isinstance(facade, type(app.state.b14_client))


def test_interpret_host_lane_reaches_the_registered_executor(monkeypatch, tmp_path):
    """End to end on the host composition with a fake B14 transport."""
    from app import local_cpython

    recorded = []

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            recorded.append(url)
            raise AssertionError("the synthetic transport never dispatches")

        async def aclose(self):
            return None

    monkeypatch.setattr(local_cpython, "compose_local_b14_transports",
                        lambda settings, proof: (_FakeAsyncClient(), _FakeAsyncClient()))
    monkeypatch.setenv("PADIEM_CHAT_CPYTHON_HOST", "1")
    monkeypatch.setenv("PADIEM_CHAT_RUNTIME_MODE", "b14")
    monkeypatch.setenv("PADIEM_CHAT_AUTH_MODE", "off")
    monkeypatch.setenv("PADIEM_CHAT_WEB_PROVIDER", "off")
    monkeypatch.setenv("PADIEM_CHAT_PUBLIC_BASE_URL", "https://chat-com2-staging.padiem.net")
    monkeypatch.setenv("PADIEM_CHAT_B14_BASE_URL", "https://b14.example")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PADIEM_CHAT_SESSION_SECRET", "test-local-secret-0123456789abcdef")

    app = local_cpython.build_app()
    facade = app.state.b66_quote_interpreter._client
    assert isinstance(facade, B66RegisteredModelCompletion)

    # A grade-resolved interpret on the host must fail inside the B14 execution
    # attempt, not while calling an object that cannot accept the selection.
    with pytest.raises(B66ModelRouteError) as caught:
        asyncio.run(facade.complete(
            [{"role": "user", "content": "배관 100미터"}], None, None, (),
            model_id=B66_GRADE_MODEL_IDS["free"], product_tier="free",
        ))
    assert caught.value.code != "model_identity_invalid"
