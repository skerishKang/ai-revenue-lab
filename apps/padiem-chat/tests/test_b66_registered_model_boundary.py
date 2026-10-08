from __future__ import annotations

"""#3760 offline model decision boundary: no B14 transport/provider traffic."""

import asyncio
from dataclasses import replace

import pytest

from app.b66_registered_model_boundary import (
    B14AuthorizedModelRoute,
    B66ModelRouteError,
    B66QuoteTaskRequirements,
    B66RegisteredModelCompletion,
    validate_authorized_route,
)


def approved_route(**overrides) -> B14AuthorizedModelRoute:
    route = B14AuthorizedModelRoute(
        model_id="test-owner-catalog/quote-capable",
        route_id="platform:test-owner-catalog/quote-capable",
        owner_policy_id="owner-approved-b66-policy-v1",
        registered=True,
        enabled=True,
        authorized=True,
        credential_ready=True,
        route_count=1,
        capabilities=frozenset(("chat", "coding")),
    )
    return replace(route, **overrides)


class FakeTrustedResolver:
    def __init__(self, selected=None, raises=None):
        self.selected = selected
        self.raises = raises
        self.calls = []

    async def resolve_quote_model(self, requirements):
        self.calls.append(requirements)
        if self.raises is not None:
            raise self.raises
        return self.selected


class FakeB14Executor:
    def __init__(self, answer="{}", response=None, raises=None):
        self.answer = answer
        self.response = response
        self.raises = raises
        self.calls = []

    async def execute_quote_text(
        self, *, route, messages, additional_system_context, requirements
    ):
        self.calls.append((route, messages, additional_system_context, requirements))
        if self.raises is not None:
            raise self.raises
        return self.response if self.response is not None else {
            "answer": self.answer,
            "route": {"mode": "manual", "model": route.model_id},
        }


def run(client, text="?? ?? ?? ?? /model:a-private-key"):
    return asyncio.run(client.complete(
        [{"role": "user", "content": text}],
        additional_system_context="private saved skill prompt",
        attachments=(),
    ))


def fails(client, code, text="?? ?? ?? ??"):
    with pytest.raises(B66ModelRouteError) as caught:
        run(client, text)
    assert caught.value.code == code
    assert str(caught.value) == code
    assert "??" not in str(caught.value)
    assert "??" not in str(caught.value)


def test_default_lane_is_unconfigured_not_implicitly_b62_plus_or_b14_auto():
    fails(B66RegisteredModelCompletion(), "selection_unconfigured")
    resolver = FakeTrustedResolver(approved_route())
    fails(B66RegisteredModelCompletion(resolver=resolver), "selection_unconfigured")
    assert resolver.calls == []
    executor = FakeB14Executor()
    fails(B66RegisteredModelCompletion(executor=executor), "selection_unconfigured")
    assert executor.calls == []


def test_one_authorized_exact_model_through_b14_stub_preserves_b66_payload():
    resolver = FakeTrustedResolver(approved_route())
    executor = FakeB14Executor(answer='{"recipient":{"company":"???"}}')
    source = "?? ?? ??: /plus ??? ??? ???"
    output = run(B66RegisteredModelCompletion(
        resolver=resolver, executor=executor), source)
    assert output == {"answer": executor.answer}
    assert len(resolver.calls) == len(executor.calls) == 1
    request = resolver.calls[0]
    assert request == B66QuoteTaskRequirements()
    assert request.task_id == "b66.quote.variable_extraction.v1"
    assert request.task_type == "document"  # not Claw's coding profile
    assert request.required_capabilities == frozenset(("chat",))
    assert request.max_attempts == 1
    assert request.max_retries == 0
    assert request.allow_external_fallback is False
    # The owner-trusted resolver sees only the static task contract.
    assert source not in str(request)
    assert "private saved skill prompt" not in str(request)
    route, messages, context, execution_requirements = executor.calls[0]
    assert route.model_id == "test-owner-catalog/quote-capable"
    assert messages == [{"role": "user", "content": source}]
    assert context == "private saved skill prompt"
    assert execution_requirements is request


@pytest.mark.parametrize(("overrides", "expected"), [
    ({"registered": False}, "model_not_registered"),
    ({"enabled": False}, "model_not_enabled"),
    ({"authorized": False}, "model_not_authorized"),
    ({"credential_ready": False}, "model_credential_unavailable"),
    ({"route_count": 0}, "selection_ambiguous"),
    ({"route_count": 2}, "selection_ambiguous"),
    ({"route_count": True}, "selection_ambiguous"),
    ({"capabilities": frozenset(("coding",))}, "model_capability_unavailable"),
    ({"model_id": "b14/auto"}, "model_identity_invalid"),
    ({"model_id": "padiem-profile/plus-hold"}, "model_identity_invalid"),
    ({"model_id": "padiem-profile/pro-hold"}, "model_identity_invalid"),
    ({"model_id": "padiem-profile/max-hold"}, "model_identity_invalid"),
    ({"model_id": "x with spaces"}, "model_identity_invalid"),
    ({"model_id": "../private-key"}, "model_identity_invalid"),
    ({"route_id": ""}, "model_identity_invalid"),
    ({"owner_policy_id": ""}, "model_identity_invalid"),
])
def test_b14_unregistered_disabled_disallowed_missing_credential_never_dispatches(
    overrides, expected
):
    resolver = FakeTrustedResolver(approved_route(**overrides))
    executor = FakeB14Executor()
    fails(B66RegisteredModelCompletion(
        resolver=resolver, executor=executor), expected)
    assert len(resolver.calls) == 1
    assert executor.calls == []


@pytest.mark.parametrize("selection", [None, {"model_id": "pretend"}, "b14/auto"])
def test_missing_or_untrusted_resolver_shape_fails_closed(selection):
    resolver = FakeTrustedResolver(selection)
    executor = FakeB14Executor()
    fails(B66RegisteredModelCompletion(resolver=resolver, executor=executor),
          "selection_unavailable")
    assert len(resolver.calls) == 1
    assert executor.calls == []


def test_resolver_error_never_reflects_raw_info_or_dispatches():
    resolver = FakeTrustedResolver(raises=RuntimeError("SECRET login key"))
    executor = FakeB14Executor()
    fails(B66RegisteredModelCompletion(resolver=resolver, executor=executor),
          "selection_unavailable")
    assert executor.calls == []


@pytest.mark.parametrize(("kwargs", "expected"), [
    ({"skill": {"model_id": "attacker"}}, "selection_unavailable"),
    ({"attachments": ("image",)}, "selection_unavailable"),
    ({"messages": [{"role": "user", "content": ""}]}, "selection_unavailable"),
    ({"messages": [{"role": "assistant", "content": "model override"}]}, "selection_unavailable"),
    ({"messages": [{"role": "user", "content": "ok", "model_id": "attacker"}]}, "selection_unavailable"),
    ({"messages": [{"role": "user", "content": "ok"}] * 2}, "selection_unavailable"),
])
def test_arbitrary_untrusted_messages_cannot_add_model_choices(kwargs, expected):
    resolver = FakeTrustedResolver(approved_route())
    executor = FakeB14Executor()
    args = {
        "messages": [{"role": "user", "content": "valid text"}],
        "additional_system_context": "trusted quote prompt",
        "attachments": (),
    }
    args.update(kwargs)
    client = B66RegisteredModelCompletion(resolver=resolver, executor=executor)
    with pytest.raises(B66ModelRouteError) as caught:
        asyncio.run(client.complete(**args))
    assert caught.value.code == expected
    assert resolver.calls == []
    assert executor.calls == []


@pytest.mark.parametrize(("response", "code"), [
    ({"answer": "valid", "route": {"mode": "auto", "model": "test-owner-catalog/quote-capable"}},
     "provider_route_mismatch"),
    ({"answer": "valid", "route": {"mode": "manual", "model": "other-model"}},
     "provider_route_mismatch"),
    ({"answer": "valid"}, "provider_route_mismatch"),
    ({"answer": None, "route": {}}, "provider_response_invalid"),
    ("raw private provider data", "provider_response_invalid"),
])
def test_no_hidden_route_substitution_or_broken_response(response, code):
    resolver = FakeTrustedResolver(approved_route())
    executor = FakeB14Executor(response=response)
    fails(B66RegisteredModelCompletion(resolver=resolver, executor=executor), code)
    assert len(executor.calls) == 1


def test_provider_exception_has_bounded_error_and_no_second_attempt():
    resolver = FakeTrustedResolver(approved_route())
    executor = FakeB14Executor(raises=RuntimeError("PRIVATE PROVIDER KEY"))
    fails(B66RegisteredModelCompletion(
        resolver=resolver, executor=executor), "provider_execution_failed")
    assert len(executor.calls) == 1
    assert len(resolver.calls) == 1


def test_validate_authority_does_not_invent_any_model_for_empty_selection():
    with pytest.raises(B66ModelRouteError, match="selection_unavailable"):
        validate_authorized_route(None, B66QuoteTaskRequirements())


def test_module_has_no_worker_or_automatic_policy_runtime_imports():
    import inspect
    from app import b66_registered_model_boundary as source
    code = inspect.getsource(source)
    assert "b14/auto" in code  # explicit rejection, not dispatch
    for forbidden in (
        "from app.model_policy import",
        "from app.pilot.routing_policy import",
        "from app.b14_client import",
        "os.environ",
        "httpx",
        "ChatRuntimeError(",
    ):
        assert forbidden not in code


def test_b14_explicit_quote_route_calls_core_once_without_b62_default(monkeypatch):
    from app.b14_client import B14Client
    from app.config import Settings
    client = B14Client(Settings(runtime_mode="b14", b14_base_url="https://b14.internal"))
    calls = []
    async def fake_complete(messages, *, skill, model, additional_system_context):
        calls.append((skill.task_type,model))
        return {"answer":"{}","route":{"mode":"manual","model":model}}
    monkeypatch.setattr(client,"_complete_text",fake_complete)
    result = asyncio.run(client.complete_registered_quote_model(
        [{"role":"user","content":"견적"}],
        model="test-owner/quote-1",
    ))
    assert result["route"]["model"] == "test-owner/quote-1"
    assert calls == [("document","test-owner/quote-1")]


@pytest.mark.parametrize("model",["","b14/auto","padiem-profile/plus-hold","bad space"])
def test_b14_explicit_quote_route_does_not_dispatch_invalid_models(monkeypatch,model):
    from app.b14_client import B14Client, ChatRuntimeError
    from app.config import Settings
    client = B14Client(Settings(runtime_mode="b14", b14_base_url="https://b14.internal"))
    calls=[]
    async def bad(*a,**kw):
        calls.append(True)
    monkeypatch.setattr(client,"_complete_text",bad)
    with pytest.raises(ChatRuntimeError) as e:
        asyncio.run(client.complete_registered_quote_model(
            [{"role":"user","content":"견적"}],model=model,
        ))
    assert e.value.code=="model_route_unavailable"
    assert calls==[]


def test_exact_selected_route_adapter_only_uses_explicit_b14_method():
    from app.b66_registered_model_boundary import B14QuoteExactModelExecutor
    class Fake:
        def __init__(self):
            self.calls=[]
        async def complete_registered_quote_model(self,messages,*,model,additional_system_context):
            self.calls.append(model)
            return {"answer":"{}","route":{"mode":"manual","model":model}}
        async def complete(self,*a,**kw):
            raise AssertionError("B62 tier policy used unexpectedly")
    fake=Fake()
    response=run(B66RegisteredModelCompletion(
        resolver=FakeTrustedResolver(approved_route()),
        executor=B14QuoteExactModelExecutor(fake),
    ))
    assert response=={"answer":"{}"}
    assert fake.calls==["test-owner-catalog/quote-capable"]
