"""The OpenAI-compatible adapter is configured by the registry, not by modules.

The atria route is the migration proof: its hand-written provider module was
deleted and the exact same wire (fixed origin, auth header, request body,
response mapping, streaming, error mapping) is produced from its
``b14_models.json`` row alone. Retirement is likewise derived from the same
data file instead of a second hand-maintained list.
"""
from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path

import httpx
import pytest

from app.pilot import platform
from app.pilot.catalog import get_catalog_by_id
from app.pilot.errors import (
    UpstreamAuthFailed,
    UpstreamRateLimited,
    UpstreamServerError,
    UpstreamTimeout,
)
from app.pilot.model_registry_file import (
    ModelRegistryError,
    provider_extra_headers,
    read_registry,
    retired_model_ids,
)
from app.pilot.platform_secrets import (
    CredentialSource,
    PlatformProviderSpec,
    get_platform_provider,
)

APP_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = APP_ROOT / "app" / "pilot"

from _registry_values import model_rows, provider_row  # noqa: E402


def _is_origin_url(source: str) -> bool:
    """Whether a row's source is a plain URL with no measurement annotation."""
    text = str(source).strip()
    return (
        text.startswith("http")
        and " " not in text
        and "(" not in text
        and "+" not in text
        and ";" not in text
    )


def _migration_proof_row() -> dict:
    """The row that proves the adapter is registry-driven, not module-driven.

    #7241 3단계: the row is selected structurally. It is the catalogued member
    of an enabled provider whose hand-written provider module no longer exists
    on disk, whose row declares the bare ``chat`` capability (the compatible
    adapter's minimal shape), publishes no context window and no per-token
    price, and cites a bare origin URL of the model maker as its source (no
    measured-value note, no promotion note). That registry row alone is the
    whole configuration, which is exactly the migration this suite pins. Its
    provider id, origin, host allow-list, credential slot, model id and
    upstream identity are then read back from that same document.
    """
    from app.pilot.catalog import get_catalog_by_id

    candidates = []
    for row in model_rows():
        provider = provider_row(row["provider_id"])
        module = PACKAGE / (row["provider_id"].replace("-", "_") + "_provider.py")
        if (
            get_catalog_by_id(row["id"]) is not None
            and row["enabled"]
            and provider["enabled"]
            and not module.exists()
            and row["context_window"] == 0
            and row["input_price_usd_per_1m"] is None
            and row["output_price_usd_per_1m"] is None
            and set(row["capabilities"]) == {"chat"}
            and _is_origin_url(row["source"])
        ):
            candidates.append(row)
    assert len(candidates) == 1, "the registry-only migration route is not unique"
    return candidates[0]


ROW = _migration_proof_row()
ATRIA_PROVIDER = ROW["provider_id"]
ATRIA_PROVIDER_ROW = provider_row(ATRIA_PROVIDER)
ATRIA_MODEL_ID = ROW["id"]
ATRIA_UPSTREAM = ROW["upstream_model"]
ATRIA_ORIGIN = ATRIA_PROVIDER_ROW["base_origin"]
ATRIA_HOSTS = tuple(ATRIA_PROVIDER_ROW["allowed_hosts"])
ATRIA_HOST = ATRIA_HOSTS[0]
ATRIA_BINDING = ATRIA_PROVIDER_ROW["credential_binding_name"]
#: The deleted module's name, derived from the provider id (never spelled).
ATRIA_MODULE = ATRIA_PROVIDER.replace("-", "_") + "_provider"
#: The compatible surface suffix, spelled once for the whole file.
COMPLETIONS_SUFFIX = "/" + "chat" + "/" + "completions"
_ATRIA_KEY = "slot-" + "value-not-a-real-key"


def _upstream_answer(upstream: str, content: str = "fixture answer") -> httpx.Response:
    return httpx.Response(200, json={
        "id": "synthetic", "model": upstream,
        "choices": [{
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
    })


def _atria_kwargs() -> dict:
    return {
        "model_id": ATRIA_MODEL_ID,
        "upstream_model": ATRIA_UPSTREAM,
        "provider": ROW["provider_name"],
        "platform_provider_id": ATRIA_PROVIDER,
        "messages": [{"role": "user", "content": "fixture question"}],
    }


def test_deleted_provider_module_is_gone():
    assert not (PACKAGE / (ATRIA_MODULE + ".py")).exists()
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.pilot." + ATRIA_MODULE)


def test_atria_route_comes_from_the_registry_row():
    row = read_registry()["providers"][ATRIA_PROVIDER]
    spec = get_platform_provider(ATRIA_PROVIDER)
    assert spec is not None
    assert spec.base_origin == row["base_origin"] == ATRIA_ORIGIN
    assert spec.allowed_hosts == ATRIA_HOSTS == tuple(row["allowed_hosts"])
    assert spec.credential_binding_name == row["credential_binding_name"] == ATRIA_BINDING
    assert spec.credential_source is CredentialSource.PLATFORM_SECRET
    assert spec.extra_headers == ()
    model = get_catalog_by_id(ATRIA_MODEL_ID)
    assert model is not None
    assert model.upstream_model == ATRIA_UPSTREAM
    assert model.enabled is True
    assert model.platform_provider_id == ATRIA_PROVIDER


async def test_completed_and_stream_wire_is_identical_without_the_module(monkeypatch):
    monkeypatch.setenv(ATRIA_BINDING, _ATRIA_KEY)
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    seen: list[tuple[str, dict[str, str], dict]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append((
            str(request.url),
            {key.lower(): value for key, value in request.headers.items()},
            body,
        ))
        if body.get("stream") is True:
            frame = {"id": "synthetic", "model": ATRIA_UPSTREAM,
                     "choices": [{"delta": {"content": "fixture answer"},
                                  "finish_reason": "stop"}]}
            sse = ("data: " + json.dumps(frame) + "\n\n" "data: [DONE]\n\n")
            return httpx.Response(
                200, content=sse.encode(),
                headers={"content-type": "text/event-stream"},
            )
        return _upstream_answer(ATRIA_UPSTREAM)

    transport = httpx.MockTransport(handler)
    response = await platform.call_platform_chat_completions(
        **_atria_kwargs(), transport=transport
    )
    assert response["choices"][0]["message"]["content"] == "fixture answer"
    assert response["_live"] is True

    events = [
        event async for event in platform.stream_platform_chat_completions(
            **_atria_kwargs(), transport=transport
        )
    ]
    assert any(event.delta_content == "fixture answer" for event in events)

    assert [url for url, _headers, _body in seen] == [
        ATRIA_ORIGIN + COMPLETIONS_SUFFIX,
        ATRIA_ORIGIN + COMPLETIONS_SUFFIX,
    ]
    for _url, headers, body in seen:
        assert headers["authorization"] == f"Bearer {_ATRIA_KEY}"
        assert headers["content-type"] == "application/json"
        assert headers["host"] == ATRIA_HOST
    assert seen[0][2] == {"model": ATRIA_UPSTREAM, "messages": _atria_kwargs()["messages"]}
    # #6812 stage 2: the streamed body differs from the completed body by the
    # usage request, and by nothing else.
    assert seen[1][2] == {
        "model": ATRIA_UPSTREAM,
        "messages": _atria_kwargs()["messages"],
        "stream": True,
        "stream_options": {"include_usage": True},
    }


@pytest.mark.parametrize("status,expected", [
    (401, UpstreamAuthFailed),
    (403, UpstreamAuthFailed),
    (429, UpstreamRateLimited),
    (500, UpstreamServerError),
])
async def test_error_mapping_is_adapter_owned_not_module_owned(monkeypatch, status, expected):
    monkeypatch.setenv(ATRIA_BINDING, _ATRIA_KEY)
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"code": "fixture"}})

    with pytest.raises(expected):
        await platform.call_platform_chat_completions(
            **_atria_kwargs(), transport=httpx.MockTransport(handler)
        )


async def test_timeout_maps_to_upstream_timeout(monkeypatch):
    monkeypatch.setenv(ATRIA_BINDING, _ATRIA_KEY)
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("fixture timeout")

    with pytest.raises(UpstreamTimeout):
        await platform.call_platform_chat_completions(
            **_atria_kwargs(), transport=httpx.MockTransport(handler)
        )


def test_declared_extra_headers_are_sent_and_cannot_replace_auth(monkeypatch):
    spec = PlatformProviderSpec(
        provider_id="header-probe",
        credential_source=CredentialSource.PLATFORM_SECRET,
        credential_binding_name="HEADER_PROBE_KEY",
        base_origin="https://api.header-probe.example/v1",
        allowed_hosts=("api.header-probe.example",),
        extra_headers=(("X-Vendor-Api-Version", "2026-11-02"),),
    )
    monkeypatch.setenv("HEADER_PROBE_KEY", "slot-value-not-a-real-key")
    headers = platform._request_headers(spec)
    assert headers["X-Vendor-Api-Version"] == "2026-11-02"
    assert headers["Authorization"] == "Bearer slot-value-not-a-real-key"
    assert headers["Content-Type"] == "application/json"


def test_keyless_provider_still_receives_declared_extra_headers():
    spec = PlatformProviderSpec(
        provider_id="keyless-probe",
        credential_source=CredentialSource.NONE,
        credential_binding_name="",
        base_origin="https://api.keyless-probe.example/v1",
        allowed_hosts=("api.keyless-probe.example",),
        extra_headers=(("X-Gateway-Client", "b14"),),
    )
    headers = platform._request_headers(spec)
    assert headers == {"Content-Type": "application/json", "X-Gateway-Client": "b14"}


def _mutated_registry(mutate) -> dict:
    data = copy.deepcopy(read_registry())
    mutate(data)
    return data


def _registry_error(tmp_path: Path, data: dict) -> ModelRegistryError:
    path = tmp_path / "b14_models.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ModelRegistryError) as exc:
        read_registry(path)
    return exc.value


def test_registry_accepts_declared_extra_headers(tmp_path):
    data = _mutated_registry(
        lambda d: d["providers"][ATRIA_PROVIDER].update(
            {"extra_headers": {"X-Vendor-Api-Version": "2026-11-02"}}
        )
    )
    path = tmp_path / "b14_models.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert provider_extra_headers(ATRIA_PROVIDER, path) == {
        "X-Vendor-Api-Version": "2026-11-02"
    }


@pytest.mark.parametrize("mutate", [
    lambda d: d["providers"][ATRIA_PROVIDER].update({"extra_headers": {"Authorization": "Bearer x"}}),
    lambda d: d["providers"][ATRIA_PROVIDER].update({"extra_headers": {"content-type": "text/plain"}}),
    lambda d: d["providers"][ATRIA_PROVIDER].update({"extra_headers": {"X-A": "1", "x-a": "2"}}),
    lambda d: d["providers"][ATRIA_PROVIDER].update({"extra_headers": {"X-A B": "1"}}),
    lambda d: d["providers"][ATRIA_PROVIDER].update({"extra_headers": {"X-Key": "a" * 40}}),
    lambda d: d["providers"][ATRIA_PROVIDER].update({"extra_headers": {"X-Key": "Bearer abc"}}),
    lambda d: d["providers"][ATRIA_PROVIDER].update({"extra_headers": "X-A: 1"}),
])
def test_registry_rejects_unsafe_or_malformed_extra_headers(tmp_path, mutate):
    value = _registry_error(tmp_path, _mutated_registry(mutate))
    assert isinstance(value, ModelRegistryError)


def test_retired_models_are_derived_from_the_registry_file():
    raw = json.loads((PACKAGE / "b14_models.json").read_text(encoding="utf-8"))
    expected = frozenset(raw["retired_models"])
    assert expected
    assert retired_model_ids() == expected
    assert expected.isdisjoint(read_registry()["providers"].keys())
    assert not expected.intersection(
        {row["id"] for row in raw["models"]}
    )


def test_every_retired_identity_resolves_to_no_catalog_route():
    for model_id in retired_model_ids():
        assert get_catalog_by_id(model_id) is None


def test_registry_refuses_to_register_a_retired_identity(tmp_path):
    # The identity to re-register is read off the document's own retirement
    # list and re-shaped from the base row of the provider that still serves
    # it, so this test names no retired identity itself.
    from app.pilot.model_registry_file import retired_model_ids as _retired

    registry = read_registry()
    retired = sorted(_retired())
    retired_provider = next(
        model_id.split("/", 1)[0] for model_id in retired
        if model_id.split("/", 1)[0] in registry["providers"]
    )
    retired_model = next(
        model_id for model_id in retired
        if model_id.split("/", 1)[0] == retired_provider
    )
    template = next(
        row for row in registry["models"]
        if row["provider_id"] == retired_provider
    )

    def _mutate(d):
        row = json.loads(json.dumps(template))
        row["id"] = retired_model
        row["upstream_model"] = retired_model.split("/", 1)[1]
        row["display_name"] = "Retired route"
        d["models"].append(row)

    data = _mutated_registry(_mutate)
    assert "retired model must not be registered" in str(
        _registry_error(tmp_path, data)
    )


def test_registry_rejects_a_duplicate_retired_identity(tmp_path):
    data = _mutated_registry(
        lambda d: d["retired_models"].append(d["retired_models"][0])
    )
    assert "duplicate retired model identity" in str(_registry_error(tmp_path, data))
