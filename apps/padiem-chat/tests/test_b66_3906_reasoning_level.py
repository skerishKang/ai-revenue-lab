"""B66 per-model reasoning-level selection contract (#3906).

Network-free tests that never call a provider. They prove the customer's
explicit reasoning choice is honoured exactly, rejected with an explainable
4xx, or omitted so the pre-#3906 request shape is preserved -- and that B66
never guesses an upstream provider parameter (#3977 dependency).
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

import pytest

from app.b66_grade_models import B66_GRADE_MODEL_IDS
from app.b66_reasoning_level import (
    DEFAULT_REASONING_LEVEL,
    DEFAULT_REASONING_LABEL,
    is_supported_reasoning_level,
    reasoning_levels_for_model,
    reasoning_options_for_model,
    reasoning_parameter_for_request,
    validate_reasoning_level,
)
from test_b66_quote_runtime import _client, _Interpreter, _Store, SAVED_ID

MODEL = "test-fixture/registered-model"
LEVEL_OPTION = {"value": "default", "label": "기본(제공자 기본값)"}
BODY = {"saved_skill_id": SAVED_ID, "message": "synthetic quote"}
ORIGIN = {"Origin": "https://chat.example.test"}

# The transport probe runs a real interpreter against apps/korean-ai-platform,
# so pass this checkout's package sources explicitly (same set as #7322)
# instead of relying on ambient interpreter paths.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SUBPROCESS_SOURCE_PATHS = (
    _REPO_ROOT / "apps" / "padiem-chat",
    _REPO_ROOT / "apps" / "korean-ai-code-agent" / "src",
    _REPO_ROOT / "packages" / "padiem-ai-core",
    _REPO_ROOT / "packages" / "padiem-control-plane",
    _REPO_ROOT / "apps" / "padiem-ai-engine" / "clients" / "python",
)

# The two Gemini Flash Lite serving IDs and the one Atria serving ID that the
# merged B14 authority documents. Both are real registry IDs, never fixtures.
# 261109 · #6828 3단계: the repository ships no model value, so the three
# distinct fixtures identities come from the placeholder registry document.
from padiem_control_plane.product_tier_routes_private import (
    free_fallback_model_id,
    free_primary_model_id,
    paid_primary_model_id,
)
GEMINI_35 = paid_primary_model_id()
GEMINI_31 = free_primary_model_id()
ATRIA = free_fallback_model_id()


@pytest.fixture(autouse=True)
def _fixture_reasoning_capability(monkeypatch: pytest.MonkeyPatch):
    """The capability table is a B14 truth source outside this PR's scope;
    the placeholder fixture identities register their documented levels here
    so the real-adapter contract tests exercise the same code paths."""
    from app import b66_reasoning_level as _mod

    table = dict(_mod._VERIFIED_REASONING_EFFORT)
    for model_id in (GEMINI_35, GEMINI_31, ATRIA):
        table[model_id] = frozenset({"minimal", "low", "medium", "high"})
    monkeypatch.setattr(_mod, "_VERIFIED_REASONING_EFFORT", table)


def _B66_TABLE() -> dict[str, frozenset]:
    """B66's published per-exact-model capability, read from the module."""
    from app import b66_reasoning_level as module

    return dict(module._VERIFIED_REASONING_EFFORT)


# Import-time snapshot: the autouse fixture registers the placeholder fixture
# identities into the live table, while the authority mirror contract below
# compares the repository's own published table.
_UNPATCHED_B66_TABLE = dict(_B66_TABLE())



def _options_client(levels_by_model: dict[str, list[dict[str, str]]]):
    """Authenticated client whose /quote/models advertises reasoning options."""

    class Options:
        async def list_selectable_models(self):
            return [
                {
                    "model_id": model_id,
                    "name": model_id.split("/")[-1],
                    "reasoning_levels": levels_by_model.get(model_id, []),
                }
                for model_id in sorted(levels_by_model)
            ]

    client = _client(_Store(), _Interpreter())
    client.app.state.b66_quote_model_resolver = Options()
    return client


def _capture() -> tuple[list[dict], type]:
    seen: list[dict] = []

    class Recording:
        async def interpret(self, **kwargs):
            seen.append(kwargs)
            raise RuntimeError("stop-after-capture")

    return seen, Recording()


# --------------------------------------------------------------------------
# 1. The exact model the user chose is preserved end to end.
# --------------------------------------------------------------------------

def test_quote_models_api_advertises_grade_options_without_naming_a_model():
    free_model = B66_GRADE_MODEL_IDS["free"]
    client = _options_client({free_model: [LEVEL_OPTION]})
    response = client.get("/api/b66/quote/models")
    assert response.status_code == 200
    data = response.json()
    # #6828: the customer sees grade keys and the reasoning options that grade's
    # model can actually carry today. Nothing names the model behind it, and the
    # endpoint still never chooses a grade for the customer.
    assert set(data) == {"ok", "tiers", "default_tier"}
    free = next(row for row in data["tiers"] if row["tier"] == "free")
    # #6838: no reasoning menu and no model identity cross to the browser.
    assert set(free) == {"tier", "name"}
    assert all(set(row) == {"tier", "name"} for row in data["tiers"])


def test_interpret_forwards_exact_model_id_unchanged():
    seen, recording = _capture()
    client = _client(_Store(), recording)
    client.post(
        "/api/b66/quote/interpret", json={**BODY, "model_id": MODEL}, headers=ORIGIN
    )
    assert seen and seen[0]["model_id"] == MODEL


# --------------------------------------------------------------------------
# 2. Omitting the level keeps the existing behaviour byte for byte.
# --------------------------------------------------------------------------

def test_omitted_reasoning_level_is_not_forwarded_as_a_keyword():
    seen, recording = _capture()
    client = _client(_Store(), recording)
    client.post(
        "/api/b66/quote/interpret", json={**BODY, "model_id": MODEL}, headers=ORIGIN
    )
    assert "reasoning_level" not in seen[0]


def test_omitted_reasoning_level_reaches_interpreter_in_previous_shape():
    calls: list[dict] = []

    class Interpreter:
        async def interpret(self, *, message, skill, model_id=None):
            calls.append({"model_id": model_id})
            return None

    client = _client(_Store(), Interpreter())
    response = client.post(
        "/api/b66/quote/interpret", json={**BODY, "model_id": MODEL}, headers=ORIGIN
    )
    assert response.status_code != 400
    assert calls == [{"model_id": MODEL}]


def test_default_level_is_transmitted_as_no_provider_argument():
    """`default` means "use the provider default": zero upstream arguments."""
    assert reasoning_parameter_for_request(MODEL, DEFAULT_REASONING_LEVEL) == {}
    assert reasoning_parameter_for_request(MODEL, None) == {}


# --------------------------------------------------------------------------
# 3 & 4. Supported level reaches the request; unsupported is blocked.
# --------------------------------------------------------------------------

def test_supported_level_is_validated():
    assert validate_reasoning_level(MODEL, DEFAULT_REASONING_LEVEL) == DEFAULT_REASONING_LEVEL


def test_an_incoming_level_is_ignored_before_any_dispatch():
    """#6838: the level is B14's decision, so the route neither validates nor
    forwards one. It is dropped exactly like a browser-chosen model_id."""
    seen, recording = _capture()
    client = _client(_Store(), recording)
    client.post(
        "/api/b66/quote/interpret",
        json={**BODY, "model_id": MODEL, "reasoning_level": "ultra"},
        headers=ORIGIN,
    )
    assert seen and "reasoning_level" not in seen[0]
    assert seen[0]["model_id"] == MODEL


@pytest.mark.parametrize(
    "bad",
    [
        "ultra",
        "DEFAULT",
        "default ",
        "de",
        "de" + "f" * 40,
        "de:ault",
        "de_fault",
        "../default",
    ],
)
def test_malformed_or_unknown_levels_are_rejected(bad):
    assert is_supported_reasoning_level(bad) is False
    with pytest.raises(ValueError):
        validate_reasoning_level(MODEL, bad)


def test_known_b14_vocabulary_is_still_rejected_for_an_unverified_model():
    """`high` is a real B14 value, but not for a model B14 has not verified.

    Grammar-valid vocabulary must not become a per-model permission: the exact
    served model ID, not the word itself, decides what is offered.
    """
    assert is_supported_reasoning_level("high") is True
    with pytest.raises(ValueError, match="unsupported_reasoning_level"):
        validate_reasoning_level(MODEL, "high")


def test_unsupported_field_guard_still_rejects_unknown_fields():
    client = _client(_Store(), _Interpreter())
    response = client.post(
        "/api/b66/quote/interpret",
        json={**BODY, "model_id": MODEL, "reasoning_effort": "high"},
        headers=ORIGIN,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_field"


def test_absent_model_id_still_reports_model_error_not_reasoning_error():
    """The model boundary is unchanged: reasoning never masks a bad model."""
    client = _client(_Store(), _Interpreter())
    response = client.post(
        "/api/b66/quote/interpret",
        json={
            "saved_skill_id": SAVED_ID,
            "message": "synthetic",
            "reasoning_level": DEFAULT_REASONING_LEVEL,
        },
        headers=ORIGIN,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "model_selection_required"


# --------------------------------------------------------------------------
# 5. Capability comes only from the B66 model registry, never from guesses.
# --------------------------------------------------------------------------

def test_unverified_model_offers_the_default_option_only():
    """A model without proven reasoning support must not advertise extra levels."""
    # The Free grade row is the customer's only view of this. With no transport
    # wired, its sole offered option is the provider default; #6828 removed the
    # model row that used to carry the same fact.
    client = _options_client({B66_GRADE_MODEL_IDS["free"]: []})
    tiers = client.get("/api/b66/quote/models").json()["tiers"]
    free = next(row for row in tiers if row["tier"] == "free")
    assert set(free) == {"tier", "name"}
    assert reasoning_options_for_model(MODEL) == [
        {"value": DEFAULT_REASONING_LEVEL, "label": DEFAULT_REASONING_LABEL}
    ]
    # The closed set is exactly the provider default; nothing else is offered.
    assert reasoning_levels_for_model(MODEL) == frozenset({DEFAULT_REASONING_LEVEL})


def test_capability_table_equals_the_b14_native_parameter_authority():
    """B66 mirrors B14's merged source authority (#3977 / PR #3984) exactly.

    The real B14 module is imported and compared, so a B14 capability change
    that is not propagated here fails CI instead of silently diverging. B66
    never becomes a second source of truth.
    """
    root = Path(__file__).resolve().parents[3]
    # Load by path: both apps use the package name `app`, so a normal import
    # would resolve to whichever app this test session is running.
    source_path = root / "apps/korean-ai-platform/app/pilot/model_native_parameters.py"
    spec = importlib.util.spec_from_file_location(
        "b14_model_native_parameters_authority", source_path
    )
    authority = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(authority)

    expected = {
        model_id: frozenset(spec["reasoning_effort"])
        for model_id, spec in authority._SUPPORTED.items()
        if isinstance(spec, dict) and "reasoning_effort" in spec
    }
    assert _UNPATCHED_B66_TABLE == expected
    # Every B66 option is exactly the documented B14 field name.
    for model_id in expected:
        for level in expected[model_id]:
            assert reasoning_parameter_for_request(model_id, level) == {
                "reasoning_effort": level
            }
    # A model B14 documents without reasoning support stays default-only.
    sampling_only = [
        model_id
        for model_id, spec in authority._SUPPORTED.items()
        if isinstance(spec, dict) and "reasoning_effort" not in spec
    ]
    assert sampling_only, "the B14 authority fixture must contain a sampling-only model"
    for model_id in sampling_only:
        assert reasoning_levels_for_model(model_id) == frozenset(
            {DEFAULT_REASONING_LEVEL}
        )
    # Anything B14 does not list is default-only. No family/alias inference.
    assert reasoning_levels_for_model("google/gemini-3.5-flash") == frozenset(
        {DEFAULT_REASONING_LEVEL}
    )
    assert reasoning_levels_for_model("google/gemini-9-ultra-thinking") == frozenset(
        {DEFAULT_REASONING_LEVEL}
    )


def test_b66_never_invents_a_provider_parameter_name():
    """Only the B14-documented native field may appear in the B66 layer."""
    module = Path(__file__).resolve().parents[1] / "app" / "b66_reasoning_level.py"
    source = module.read_text(encoding="utf-8")
    for forbidden in (
        "thinkingConfig",
        "thinking_budget",
        "reasoning_tokens",
        "max_reasoning",
        "enable_thinking",
        "chat_template_kwargs",
    ):
        assert forbidden not in source
    # `reasoning_effort` is legitimate only as the emitted argument key.
    emitted = {
        tuple(sorted(parameters))
        for model_id in _B66_TABLE()
        for parameters in (
            reasoning_parameter_for_request(model_id, level)
            for level in _B66_TABLE()[model_id]
        )
    }
    assert emitted == {("reasoning_effort",)}


def test_no_parameter_is_emitted_for_any_unproven_level():
    """Fail closed: nothing is ever invented for the provider to consume."""
    assert reasoning_parameter_for_request(MODEL, DEFAULT_REASONING_LEVEL) == {}
    assert reasoning_parameter_for_request(MODEL, None) == {}
    with pytest.raises(ValueError):
        reasoning_parameter_for_request(MODEL, "high")


def test_default_option_is_the_sole_builtin_option_constant():
    assert reasoning_options_for_model(MODEL) == [
        {"value": DEFAULT_REASONING_LEVEL, "label": DEFAULT_REASONING_LABEL}
    ]


# --------------------------------------------------------------------------
# 6. Both B66 UI surfaces share one contract; no hidden model replacement.
# --------------------------------------------------------------------------

def test_the_quote_ui_offers_a_grade_and_no_reasoning_control():
    """#6838: the customer chooses a grade; the level is B14's decision.

    The grade picker stays (it carries no model identity), and the per-model
    reasoning control and its bookkeeping are gone from the shipped runtime.
    """
    root = Path(__file__).resolve().parents[3]
    runtime = (
        root / "apps/padiem-chat/static/b66-quote-runtime.js"
    ).read_text(encoding="utf-8")
    assert "b66QuoteModelSelect" in runtime
    assert "b66QuoteReasoningSelect" not in runtime
    assert "b66QuoteReasoningField" not in runtime
    assert "reasoning_levels" not in runtime
    assert "reasoning_level" not in runtime
    assert "syncReasoningOptions" not in runtime


def test_no_automatic_model_substitution_or_fallback_in_b66_sources():
    root = Path(__file__).resolve().parents[3]
    sources = [
        root / "apps/padiem-chat/app/b66_quote_routes.py",
        root / "apps/padiem-chat/app/b66_reasoning_level.py",
        root / "reference/business-66-padiem-quote-v1/padiem-account.js",
        root / "apps/padiem-chat/static/b66-quote-runtime.js",
    ]
    for src in sources:
        content = src.read_text(encoding="utf-8")
        assert "fallback_model" not in content
        assert "model_fallback" not in content
        assert "auto_select" not in content
        # An unsupported level must never be silently coerced to another one:
        # no code path may replace a rejected level with a different value.
        assert "downgrade_to" not in content
        assert "reasoning_level = reasoning_level" not in content


# --------------------------------------------------------------------------
# 7. The existing quote extraction -> QuoteCore -> Sol PDF path is untouched.
# --------------------------------------------------------------------------

def test_interpret_still_returns_the_candidate_and_totals_shape():
    """The pre-existing projection shape is unchanged by the new keyword."""
    from app.b66_quote_conversation import B66QuoteConversationProjection

    seen: list[dict] = []

    class Interpreter:
        async def interpret(self, **kwargs):
            seen.append(kwargs)
            return B66QuoteConversationProjection(
                recipient={
                    "company": "ABC상사",
                    "person": None,
                    "address": None,
                    "email": None,
                },
                quote_no=None,
                issue_date=None,
                items=({"name": "상품", "qty": 20, "unitPrice": 30000},),
                memo=None,
                tax_mode=None,
                missing=(),
            )

    client = _client(_Store(), Interpreter())
    response = client.post(
        "/api/b66/quote/interpret",
        json={
            **BODY,
            "model_id": MODEL,
        },
        headers=ORIGIN,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    # QuoteCore remains the only calculation authority for totals.
    assert "candidate" in body
    assert isinstance(body["candidate"].get("missing"), list)
    # The resolved model reaches the interpreter; no level travels with it.
    assert seen[0]["model_id"] == MODEL
    assert "reasoning_level" not in seen[0]


def test_interpret_reserved_forwards_no_reasoning_keyword():
    """Both call shapes send message/skill/model only; the keyword is gone."""
    from app.b66_quote_routes import _interpret_reserved

    seen: list[dict] = []

    class Recording:
        async def interpret(self, **kwargs):
            seen.append(kwargs)
            return None

    asyncio.run(
        _interpret_reserved(
            Recording().interpret,
            message="synthetic quote",
            skill={"variableSchema": {}},
            model_id=MODEL,
        )
    )
    assert seen == [{
        "message": "synthetic quote",
        "skill": {"variableSchema": {}},
        "model_id": MODEL,
    }]
    # A caller that still passes the removed keyword fails loudly instead of
    # having it silently dropped.
    with pytest.raises(TypeError):
        asyncio.run(
            _interpret_reserved(
                Recording().interpret,
                message="synthetic quote",
                skill={"variableSchema": {}},
                model_id=MODEL,
                reasoning_level="low",
            )
        )


# --------------------------------------------------------------------------
# 8. The REAL B66 adapter, not a **kwargs double.
#
#    A permissive mock hides the defect this section exists for: propagating
#    reasoning_level="default" into B66RegisteredModelCompletion.complete(),
#    whose signature does not accept that keyword, raised
#    `TypeError: unexpected keyword argument 'reasoning_level'` in production.
# --------------------------------------------------------------------------

def _route(model_id):
    from app.b66_registered_model_boundary import B14AuthorizedModelRoute

    return B14AuthorizedModelRoute(
        model_id=model_id,
        route_id=f"route-{model_id}",
        owner_policy_id="owner-policy-b66",
        registered=True,
        enabled=True,
        authorized=True,
        credential_ready=True,
        route_count=1,
        capabilities=frozenset({"chat"}),
    )


def _real_adapter(model_id, *, refunds=None, transport: bool = False):
    """Real B66RegisteredModelCompletion with only resolver/executor injected.

    ``transport`` is the capability the Core-owning executor declares; False is
    today's real state, because the shared Core opt-in (#3977) is not merged.
    """
    from app.b66_registered_model_boundary import B66RegisteredModelCompletion

    calls: list[dict] = []

    class Resolver:
        async def resolve_quote_model(self, requirements):
            return _route(requirements.selected_model_id)

    class Executor:
        supports_native_parameters = transport

        async def execute_quote_text(self, **kwargs):
            calls.append(kwargs)
            return {
                "answer": '{"recipient": {}, "items": []}',
                "route": {"model": model_id, "mode": "manual"},
            }

    async def refund():
        if refunds is not None:
            refunds.append("refunded")

    completion = B66RegisteredModelCompletion(
        resolver=Resolver(), executor=Executor(), refund_pre_dispatch=refund
    )
    return completion, calls


MESSAGES = [{"role": "user", "content": "synthetic quote"}]


def test_real_adapter_accepts_default_level_without_typeerror():
    """The production blocker: `default` must reach the real adapter safely."""
    completion, calls = _real_adapter(GEMINI_35)
    result = asyncio.run(
        completion.complete(MESSAGES, model_id=GEMINI_35, reasoning_level="default")
    )
    assert result == {"answer": '{"recipient": {}, "items": []}'}
    assert len(calls) == 1
    # Provider-native omission: the executor is told to send nothing extra.
    assert calls[0]["model_parameters"] is None


def test_real_adapter_omission_path_is_byte_identical_to_pre_3906():
    completion, calls = _real_adapter(GEMINI_35)
    asyncio.run(completion.complete(MESSAGES, model_id=GEMINI_35))
    assert calls[0]["model_parameters"] is None
    assert "model_parameters" not in calls[0] or calls[0]["model_parameters"] is None


def test_real_adapter_forwards_explicit_verified_level_when_core_transports_it():
    completion, calls = _real_adapter(GEMINI_35, transport=True)
    asyncio.run(
        completion.complete(MESSAGES, model_id=GEMINI_35, reasoning_level="low")
    )
    # Exactly one documented native field. No temperature, no budget, no alias.
    assert calls[0]["model_parameters"] == {"reasoning_effort": "low"}
    assert calls[0]["route"].model_id == GEMINI_35


def test_real_adapter_refuses_explicit_level_until_core_transport_exists():
    """No silent drop: refused before dispatch, and the usage is refunded."""
    refunds: list[str] = []
    completion, calls = _real_adapter(GEMINI_35, refunds=refunds)
    with pytest.raises(Exception) as excinfo:
        asyncio.run(
            completion.complete(MESSAGES, model_id=GEMINI_35, reasoning_level="high")
        )
    assert getattr(excinfo.value, "code", None) == "model_capability_unavailable"
    assert calls == []          # never dispatched
    assert refunds == ["refunded"]


def test_real_adapter_refuses_a_level_not_verified_for_that_exact_model():
    refunds: list[str] = []
    # Gemma is registered at B14 but has no documented reasoning_effort.
    completion, calls = _real_adapter("google/gemma-4-26b-a4b-it", refunds=refunds)
    with pytest.raises(Exception) as excinfo:
        asyncio.run(
            completion.complete(
                MESSAGES, model_id="google/gemma-4-26b-a4b-it", reasoning_level="high"
            )
        )
    assert getattr(excinfo.value, "code", None) == "model_capability_unavailable"
    assert calls == []
    assert refunds == ["refunded"]


def test_real_adapter_never_changes_the_selected_model_id():
    completion, calls = _real_adapter(ATRIA, transport=True)
    asyncio.run(completion.complete(MESSAGES, model_id=ATRIA, reasoning_level="medium"))
    assert calls[0]["route"].model_id == ATRIA
    assert calls[0]["requirements"].selected_model_id == ATRIA


# --------------------------------------------------------------------------
# 9. The B14 side accepts exactly what B66 emits -- real B14 code, mock network.
# --------------------------------------------------------------------------

def _b14_authority():
    root = Path(__file__).resolve().parents[3]
    source_path = root / "apps/korean-ai-platform/app/pilot/model_native_parameters.py"
    spec = importlib.util.spec_from_file_location(
        "b14_authority_for_b66", source_path
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("model_id", "level"),
    [
        (GEMINI_35, "minimal"),
        (GEMINI_35, "low"),
        (GEMINI_35, "medium"),
        (GEMINI_35, "high"),
        (GEMINI_31, "high"),
        (ATRIA, "low"),
        (ATRIA, "high"),
    ],
)
def test_b14_authority_accepts_the_exact_object_b66_emits(model_id, level):
    """B66's emitted request object is accepted verbatim by the B14 authority."""
    authority = _b14_authority()
    # The placeholder fixture identities are not in the repository's real
    # authority table (which keeps real served IDs out of this PR's scope);
    # register their documented levels so the emit/accept contract is tested
    # against the same code path.
    authority._SUPPORTED.setdefault(model_id, {})["reasoning_effort"] = frozenset(
        {"minimal", "low", "medium", "high"}
    )
    emitted = reasoning_parameter_for_request(model_id, level)
    assert authority.validate_native_parameters(model_id, emitted) == emitted
    assert tuple(emitted) == ("reasoning_effort",)


def test_b14_authority_rejects_what_b66_would_never_emit():
    """Negative control: B14 refuses unverified values and fields."""
    authority = _b14_authority()
    with pytest.raises(authority.UnsupportedModelParameter):
        authority.validate_native_parameters(
            "experiential/qwen3.8-flash-next-uncensored", {"reasoning_effort": "high"}
        )
    with pytest.raises(authority.UnsupportedModelParameter):
        authority.validate_native_parameters(GEMINI_35, {"thinking_budget": 1024})


_B14_DRIVER = """
import asyncio, json, sys
sys.path.insert(0, ".")
from app.pilot import platform as plt
from app.pilot.platform import (
    call_platform_chat_completions,
    stream_platform_chat_completions,
)
from app.pilot import platform_secrets as ps
import os

os.environ["B14_PROVIDER_MODE"] = "live"
ps.resolve_secret = lambda spec: "synthetic-placeholder-for-mock-123456"
plt._request_headers = lambda spec, model_id=None: {"Content-Type": "application/json"}

import httpx

seen = {}

async def nonstream():
    async def handler(req):
        seen["nonstream"] = json.loads(req.content)
        return httpx.Response(200, json={
            "id": "synthetic", "model": "gemini-3.5-flash-lite",
            "choices": [{"message": {"role": "assistant", "content": "ok"},
                         "finish_reason": "stop"}],
        })
    await call_platform_chat_completions(
        model_id="google/gemini-3.5-flash-lite",
        upstream_model="gemini-3.5-flash-lite",
        provider="Google AI Studio",
        platform_provider_id="google",
        messages=[{"role": "user", "content": "hi"}],
        model_parameters=json.loads(sys.argv[1]),
        transport=httpx.MockTransport(handler),
    )

async def stream():
    async def handler(req):
        seen["stream"] = json.loads(req.content)
        sse = (
            'data: {"id":"s","model":"gemini-3.5-flash-lite",'
            '"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\\n\\n'
            'data: [DONE]\\n\\n'
        )
        return httpx.Response(
            200, content=sse.encode("utf-8"),
            headers={"content-type": "text/event-stream"},
        )
    async for _ in stream_platform_chat_completions(
        model_id="google/gemini-3.5-flash-lite",
        upstream_model="gemini-3.5-flash-lite",
        provider="Google AI Studio",
        platform_provider_id="google",
        messages=[{"role": "user", "content": "hi"}],
        model_parameters=json.loads(sys.argv[1]),
        transport=httpx.MockTransport(handler),
    ):
        pass

async def default_case():
    # Provider-native omission: no reasoning key at all on the wire.
    async def handler(req):
        seen["default"] = json.loads(req.content)
        return httpx.Response(200, json={
            "id": "synthetic", "model": "gemini-3.5-flash-lite",
            "choices": [{"message": {"role": "assistant", "content": "ok"},
                         "finish_reason": "stop"}],
        })
    await call_platform_chat_completions(
        model_id="google/gemini-3.5-flash-lite",
        upstream_model="gemini-3.5-flash-lite",
        provider="Google AI Studio",
        platform_provider_id="google",
        messages=[{"role": "user", "content": "hi"}],
        transport=httpx.MockTransport(handler),
    )

async def main():
    await nonstream()
    await stream()
    await default_case()
    print(json.dumps(seen))

asyncio.run(main())
"""


def test_b66_level_never_leaks_into_the_platform_request_json():
    """#6838: the platform lane decides the level, never the caller.

    This used to pin the opposite: the object B66 emitted (#3906) became a
    TOP-LEVEL `reasoning_effort` on the provider request. #6838 moved the
    decision into the model registry, and the public registry carries no
    values at all, so the far side of the contract is now that a caller
    supplied level is dropped in both streaming and non-streaming shapes while
    the rest of the request shape stays unchanged.
    """
    import json
    import os
    import subprocess
    import sys
    import tempfile

    emitted = reasoning_parameter_for_request(GEMINI_35, "low")
    assert emitted == {"reasoning_effort": "low"}
    platform = Path(__file__).resolve().parents[3] / "apps" / "korean-ai-platform"
    # #4070 race fix: this driver used to be written INTO the repository tree
    # (`apps/korean-ai-platform/b66_reasoning_transport_probe.py`) and deleted in
    # `finally`. The Core suite runs concurrently on the same runner
    # (`.github/scripts/b62_host_pytest_overlap_4070.sh`), and
    # `test_package_root_consumer_inventory` walks the whole repo with
    # `REPO_ROOT.rglob("*.py")` before reading each file. When the unlink landed
    # between its listing pass and its read pass, that unrelated test died with
    # `FileNotFoundError` and took `b62-test` (and therefore `main`) red.
    # Writing the driver to a temp directory outside the repo removes the shared
    # mutable path entirely. The subprocess still runs with `cwd=platform`,
    # because the driver does `sys.path.insert(0, ".")` to import `app.pilot`.
    with tempfile.TemporaryDirectory(prefix="b66-reasoning-probe-") as tmpdir:
        driver = Path(tmpdir) / "b66_reasoning_transport_probe.py"
        try:
            driver.write_text(_B14_DRIVER, encoding="utf-8")
            env = os.environ.copy()
            existing_path = env.get("PYTHONPATH")
            env["PYTHONPATH"] = os.pathsep.join(str(p) for p in _SUBPROCESS_SOURCE_PATHS) + (
                os.pathsep + existing_path if existing_path else "")
            completed = subprocess.run(
                [sys.executable, str(driver), json.dumps(emitted)],
                cwd=platform,
                env=env,
                capture_output=True,
                text=True, encoding="utf-8",
                timeout=120,
            )
        except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
            pytest.skip(f"B14 probe transport unavailable: {exc}")
    assert completed.returncode == 0, completed.stderr[-2000:]
    seen = json.loads(completed.stdout.strip().splitlines()[-1])

    assert seen["stream"]["stream"] is True
    assert seen["nonstream"]["model"] == "gemini-3.5-flash-lite"
    # #6838: the caller's level is stripped and the public registry declares no
    # reasoning block, so no shape may carry the option.
    for shape in ("nonstream", "stream"):
        assert "reasoning_effort" not in seen[shape]
        assert "temperature" not in seen[shape]
        assert "max_tokens" not in seen[shape]
        assert "model_parameters" not in seen[shape]
    # Provider-native omission stays omission on the wire.
    assert "reasoning_effort" not in seen["default"]
    assert "temperature" not in seen["default"]


# --------------------------------------------------------------------------
# 10. The transport gate is real, not an assumption.
# --------------------------------------------------------------------------

def test_transport_gate_fails_closed_without_an_injected_capability():
    """No capability from the Core owner means "cannot carry", never "assume"."""
    from app.b66_reasoning_level import reasoning_transport_available

    assert reasoning_transport_available(GEMINI_35) is False
    assert reasoning_transport_available(GEMINI_35, transport_supported=False) is False
    assert reasoning_transport_available(GEMINI_35, transport_supported=None) is False
    assert reasoning_transport_available(GEMINI_35, transport_supported=True) is True
    # An unverified model stays untransportable even with the Core present.
    assert (
        reasoning_transport_available("google/gemma-4-26b-a4b-it", transport_supported=True)
        is False
    )


def test_b66_never_imports_the_shared_core_package_directly():
    """B14/Core owns the transport; B66 must not become a second Core client."""
    root = Path(__file__).resolve().parents[3]
    for relative in (
        "apps/padiem-chat/app/b66_reasoning_level.py",
        "apps/padiem-chat/app/b66_registered_model_boundary.py",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        assert "import padiem_ai_core" not in source
        assert "from padiem_ai_core" not in source


def test_grade_rows_carry_a_grade_and_no_reasoning_menu():
    """#6838: even with the Core transport present, the browser sees no menu."""
    client = _options_client({GEMINI_35: [], GEMINI_31: [], ATRIA: []})
    client.app.state.b66_reasoning_transport_supported = True
    rows = client.get("/api/b66/quote/models").json()["tiers"]
    assert rows
    for row in rows:
        assert set(row) == {"tier", "name"}
    # The capability vocabulary itself stays a B14 decision, not a UI option.
    assert reasoning_options_for_model(GEMINI_35, transport_supported=True)


def test_api_ignores_an_explicit_level_the_transport_cannot_carry():
    """#6838: no 422 gate remains; the level simply never reaches dispatch."""
    seen, recording = _capture()
    client = _client(_Store(), recording)
    response = client.post(
        "/api/b66/quote/interpret",
        json={**BODY, "model_id": GEMINI_35, "reasoning_level": "low"},
        headers=ORIGIN,
    )
    assert response.status_code != 422
    assert seen and "reasoning_level" not in seen[0]


def test_grade_rows_never_mention_a_level():
    client = _options_client({GEMINI_35: [], GEMINI_31: [], ATRIA: []})
    tiers = client.get("/api/b66/quote/models").json()["tiers"]
    assert tiers, "the grade rows are the customer's only view of this"
    for row in tiers:
        assert "reasoning_levels" not in row


def test_api_does_not_forward_even_the_default_level():
    seen, recording = _capture()
    client = _client(_Store(), recording)
    client.post(
        "/api/b66/quote/interpret",
        json={**BODY, "model_id": GEMINI_35, "reasoning_level": "default"},
        headers=ORIGIN,
    )
    assert seen and seen[0]["model_id"] == GEMINI_35
    assert "reasoning_level" not in seen[0]
