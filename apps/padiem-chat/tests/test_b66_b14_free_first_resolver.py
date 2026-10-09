"""#3760 B66 owner-allowed B14 registered selection, NO provider calls."""
import asyncio
from dataclasses import replace
import json

import pytest

from app.b66_b14_free_first_resolver import B14FreeFirstQuoteModelResolver
from app.b66_registered_model_boundary import (
    B66ModelRouteError,
    B66QuoteTaskRequirements,
)


# Test-only synthetic route: no real provider/model is selected by fixtures.
MODEL = "test-fixture/eligible-registered-chat"
PID = "test-fixture"


def records(*, free=True, auto_eligible=True, credential=True, enabled=True,
            ready=True, provider_mode="live", owner_excluded=False,
            capabilities=("chat", "coding", "free")):
    return (
        {
            "registered_routes": [{
                "id": MODEL,
                "provider_id": PID,
                "free": free,
                "owner_excluded": owner_excluded,
                "capabilities": list(capabilities),
                "explicit_only": not auto_eligible,
                "auto_eligible": auto_eligible,
            }],
            "catalog": [{
                "id": MODEL,
                "provider_id": PID,
                "tags": ["alpha", *capabilities],
            }],
        },
        {
            "provider_mode": provider_mode,
            "providers": [{
                "provider_id": PID,
                "enabled": enabled,
                "credential_ready": credential,
                "route_ready": ready,
                "models": [MODEL],
            }],
        },
    )


class FakeB14ReadOnlyRegistry:
    def __init__(self, models, readiness, *,
                 first_status=200, second_status=200, raises=False):
        self.models = models
        self.readiness = readiness
        self.first_status = first_status
        self.second_status = second_status
        self.raises = raises
        self.paths = []
        self.provider_execution_calls = 0

    async def get_json(self, path):
        self.paths.append(path)
        if self.raises:
            raise RuntimeError("PRIVATE B14 READ ERROR: token=secret")
        if path == "/api/pilot/models":
            return self.first_status, json.dumps(self.models).encode("utf-8")
        if path == "/api/pilot/provider-readiness":
            return self.second_status, json.dumps(self.readiness).encode("utf-8")
        raise AssertionError("unknown path")


def select(fake, requirements=None, model_id=MODEL):
    request = requirements or B66QuoteTaskRequirements()
    request = replace(request, selected_model_id=model_id)
    return asyncio.run(B14FreeFirstQuoteModelResolver(fake).resolve_quote_model(request))


def deny(fake, expected="selection_unavailable"):
    with pytest.raises(B66ModelRouteError) as err:
        select(fake)
    assert err.value.code == expected
    assert "secret" not in str(err.value)
    assert fake.provider_execution_calls == 0




@pytest.mark.parametrize(("excluded_model", "provider_id"), [
    ("kilo/nvidia-nemotron-3-ultra-550b-a55b-free", "kilo"),
    ("kilo/nvidia-nemotron-new-variant-free", "kilo"),
    ("kilo/poolside-laguna-s-2.1-free", "kilo"),
    ("b-ai/qwen3.8-flash", "b-ai"),
    ("infron/motif/motif-3", "infron"),
    ("experiential/gpt-5.6-luna", "experiential"),
])
def test_owner_excluded_registered_free_ready_route_never_selected(
    excluded_model, provider_id
):
    registry, readiness = records()
    registry["registered_routes"][0]["id"] = excluded_model
    registry["registered_routes"][0]["provider_id"] = provider_id
    registry["catalog"][0]["id"] = excluded_model
    registry["catalog"][0]["provider_id"] = provider_id
    readiness["providers"][0]["provider_id"] = provider_id
    readiness["providers"][0]["models"] = [excluded_model]
    fake = FakeB14ReadOnlyRegistry(registry, readiness)
    deny(fake, "selection_unavailable")
    assert fake.paths == ["/api/pilot/models", "/api/pilot/provider-readiness"]


def test_excluded_candidate_cannot_poison_single_allowed_fixture_selection():
    registry, readiness = records()
    excluded = "kilo/nvidia-nemotron-3-ultra-550b-a55b-free"
    registry["registered_routes"].append({
        "id": excluded, "provider_id": "kilo", "free": True,
        "owner_excluded": True,
        "capabilities": ["chat"],
        "auto_eligible": True, "explicit_only": False,
    })
    registry["catalog"].append({
        "id": excluded, "provider_id": "kilo", "tags": ["alpha", "chat", "free"],
    })
    readiness["providers"].append({
        "provider_id": "kilo", "enabled": True, "credential_ready": True,
        "route_ready": True, "models": [excluded],
    })
    fake = FakeB14ReadOnlyRegistry(registry, readiness)
    selected = select(fake)
    assert selected.model_id == MODEL
    assert selected.model_id != excluded
    assert fake.provider_execution_calls == 0

def test_one_owner_allowed_registered_chat_and_live_credential_selects_exact_id():
    fake = FakeB14ReadOnlyRegistry(*records())
    selected = select(fake)
    assert selected.model_id == MODEL
    assert selected.route_id == MODEL
    assert selected.route_count == 1
    assert selected.owner_policy_id == "OWNER_REGISTERED_AND_ALLOWED"
    assert selected.credential_ready is True
    assert selected.capabilities.issuperset(frozenset(("chat",)))
    assert fake.paths == [
        "/api/pilot/models", "/api/pilot/provider-readiness",
    ]
    assert fake.provider_execution_calls == 0


@pytest.mark.parametrize("changes", [
    {"free": False},
    {"auto_eligible": False},
    {"free": False, "auto_eligible": False, "capabilities": ("chat",)},
    {"capabilities": ("chat", "coding")},
])
def test_registered_paid_unknown_price_or_manual_pin_is_eligible_when_unique(changes):
    registry, readiness = records(**changes)
    # A trusted B14 manual-pin route is valid for the B66 owner-approved
    # product lane. This does NOT change B14's generic auto-eligible source.
    fake = FakeB14ReadOnlyRegistry(registry, readiness)
    selected = select(fake)
    assert selected.model_id == MODEL
    assert selected.owner_policy_id == "OWNER_REGISTERED_AND_ALLOWED"
    assert fake.provider_execution_calls == 0


@pytest.mark.parametrize(("changes", "expected"), [
    ({"credential": False}, "selection_unavailable"),
    ({"enabled": False}, "selection_unavailable"),
    ({"ready": False}, "selection_unavailable"),
    ({"provider_mode": "mock"}, "selection_unavailable"),
    ({"capabilities": ("coding", "free")}, "selection_unavailable"),
    ({"owner_excluded": True}, "selection_unavailable"),
])
def test_unready_unqualified_or_owner_excluded_is_never_selected(changes, expected):
    deny(FakeB14ReadOnlyRegistry(*records(**changes)), expected)


def test_missing_b14_owner_exclusion_attestation_fails_closed():
    registry, readiness = records()
    registry["registered_routes"][0].pop("owner_excluded")
    deny(FakeB14ReadOnlyRegistry(registry, readiness))


def test_missing_registered_capabilities_fails_closed():
    registry, readiness = records()
    registry["registered_routes"][0].pop("capabilities")
    deny(FakeB14ReadOnlyRegistry(registry, readiness))


def test_manual_pin_without_public_catalog_is_valid_if_single_ready():
    registry, readiness = records(free=False, auto_eligible=False, capabilities=("chat",))
    registry["catalog"] = []
    selected = select(FakeB14ReadOnlyRegistry(registry, readiness))
    assert selected.model_id == MODEL


def test_b14_credentials_are_not_a_user_quote_or_model_hint():
    fake = FakeB14ReadOnlyRegistry(*records())
    selected = select(fake)
    assert selected.model_id == MODEL
    assert "password" not in str(fake.paths)
    assert "company" not in str(fake.paths)


def test_multiple_paid_and_manual_routes_have_no_arbitrary_order_or_fallback():
    registry, readiness = records()
    twin = "test-fixture/another-paid-chat"
    registry["registered_routes"].append({
        "id": twin, "provider_id": PID, "free": False,
        "owner_excluded": False,
        "capabilities": ["chat"],
        "auto_eligible": False, "explicit_only": True,
    })
    registry["catalog"].append({
        "id": twin, "provider_id": PID, "tags": ["alpha", "chat"],
    })
    readiness["providers"][0]["models"].append(twin)
    # User-selected exact model remains valid even with other ready models.
    chosen = select(FakeB14ReadOnlyRegistry(registry, readiness))
    assert chosen.model_id == MODEL
    chosen_twin = select(FakeB14ReadOnlyRegistry(registry, readiness), model_id=twin)
    assert chosen_twin.model_id == twin


@pytest.mark.parametrize("malformation", [
    "duplicated_model",
    "missing_capabilities",
    "duplicate_provider",
    "provider_mismatch",
    "bad_readiness_models",
])
def test_registry_contradiction_never_dispatches(malformation):
    registry, readiness = records()
    if malformation == "duplicated_model":
        registry["registered_routes"].append(registry["registered_routes"][0].copy())
    elif malformation == "missing_capabilities":
        registry["registered_routes"][0].pop("capabilities")
    elif malformation == "duplicate_provider":
        readiness["providers"].append(readiness["providers"][0].copy())
    elif malformation == "provider_mismatch":
        registry["catalog"][0]["provider_id"] = "untrusted"
    else:
        readiness["providers"][0]["models"] = None
    deny(FakeB14ReadOnlyRegistry(registry, readiness),
         "selection_ambiguous" if malformation == "duplicated_model"
         else "selection_unavailable")


@pytest.mark.parametrize("first_status,second_status", [
    (503, 200), (200, 500), (401, 200),
])
def test_registry_and_readiness_must_both_be_http_200(first_status, second_status):
    deny(FakeB14ReadOnlyRegistry(
        *records(), first_status=first_status, second_status=second_status,
    ))


def test_b14_service_read_exception_does_not_leak_or_retry():
    fake = FakeB14ReadOnlyRegistry(*records(), raises=True)
    deny(fake)
    assert fake.paths == ["/api/pilot/models"]


def test_unconfigured_resolver_never_dispatches():
    with pytest.raises(B66ModelRouteError, match="selection_unconfigured"):
        select(None)


def test_untrusted_task_contract_denied_before_registry():
    fake = FakeB14ReadOnlyRegistry(*records())
    from dataclasses import replace
    with pytest.raises(B66ModelRouteError, match="selection_unavailable"):
        select(fake, replace(B66QuoteTaskRequirements(), task_type="coding"))
    assert fake.paths == []


def test_quote_text_is_not_part_of_trusted_resolver_api():
    import inspect
    signature = inspect.signature(B14FreeFirstQuoteModelResolver.resolve_quote_model)
    assert tuple(signature.parameters) == ("self", "requirements")
    assert "message" not in signature.parameters
    assert "model_id" not in signature.parameters


def test_cloudflare_service_binding_uses_only_two_exact_get_read_paths():
    """Execute the actual worker transport class in isolation; zero Internet."""
    import ast
    from pathlib import Path

    worker_path = Path(__file__).resolve().parents[1] / "worker.py"
    tree = ast.parse(worker_path.read_text("utf-8"))
    node = next(
        item for item in tree.body
        if isinstance(item, ast.ClassDef)
        and item.name == "CloudflareB14ServiceTransport"
    )
    captured = []

    class Request:
        def __init__(self, url, **kwargs):
            captured.append((url, kwargs))
            self.js_object = self

    class Response:
        status = 200

    class Binding:
        async def fetch(self, request):
            return Response()

    async def read_body(response, *, max_bytes):
        assert max_bytes == 131072
        return b'{"registered_routes":[],"catalog":[]}'

    class TooLarge(Exception):
        pass

    class BadRead(Exception):
        pass

    module = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[
            ast.alias(name="annotations")], level=0),
        node,
    ], type_ignores=[])
    ns = {
        "Request": Request,
        "json": json,
        "MAX_B14_RESPONSE_BYTES": 1024 * 1024,
        "read_bounded_service_binding_body": read_body,
        "ServiceBindingResponseTooLarge": TooLarge,
        "ServiceBindingResponseError": BadRead,
    }
    exec(compile(ast.fix_missing_locations(module), str(worker_path), "exec"), ns)
    transport = ns["CloudflareB14ServiceTransport"](Binding())

    async def scenario():
        for path in ("/api/pilot/models", "/api/pilot/provider-readiness"):
            status, raw = await transport.get_json(path)
            assert status == 200
            assert b"registered_routes" in raw
        for path in ("https://attacker.invalid", "/api/pilot/admin", "/"):
            with pytest.raises(ValueError):
                await transport.get_json(path)
    asyncio.run(scenario())
    assert captured == [
        ("https://b14.internal/api/pilot/models", {"method": "GET"}),
        ("https://b14.internal/api/pilot/provider-readiness", {"method": "GET"}),
    ]


def test_production_worker_b66_wiring_uses_owner_allowed_authority_not_b62_tier():
    from pathlib import Path
    worker = (Path(__file__).resolve().parents[1] / "worker.py").read_text("utf-8")
    assert "B66ExplicitQuoteModelResolver(service_transport)" in worker
    assert "B14QuoteExactModelExecutor(" in worker
    assert "refund_pre_dispatch=_refund_active_reservation" in worker
    assert "B66RegisteredModelCompletion(" in worker
