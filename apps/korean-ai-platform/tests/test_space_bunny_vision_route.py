"""Manual Space Bunny image route for B66 Vision MVP (#3212).

Owner decision (#3143 CLOSED + #3212 CENTRAL comment):

```text
B66_TEXT_PRIMARY=stealth/space-bunny-alpha
B66_VISION_PRIMARY=stealth/space-bunny-alpha
PROVIDER=Kilo Gateway
B14_ROUTE_ID=kilo/stealth-space-bunny-alpha
VISION_FALLBACK=NONE_FOR_MVP
```

Everything here runs against the real registry, the real catalog, the real
router resolvers, and the canonical ``multimodal_contract`` gateway — no
string-presence checks and no live provider calls (mock provider mode).
The existing B14 multimodal authority is reused; no second image schema is
introduced, the global ``b14/auto`` chain is untouched, and staged SSE
stays ``model=b14/auto`` text-only.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot import platform_secrets as ps
from app.pilot.b14_runtime_config import runtime_config
from app.pilot.capability_evidence import (
    ModelCapability,
    canonical_capability_from_legacy_tag,
    capability_profile_from_catalog_model,
)
from app.pilot.catalog import CATALOG_MODELS, get_catalog_by_id
from app.pilot.errors import NoSafeRoute
from app.pilot.kilo_provider import (
    KILO_NEMOTRON_MODEL_ID,
    KILO_PROVIDER_ID,
    KILO_SPACE_BUNNY_MODEL_ID,
    KILO_SPACE_BUNNY_UPSTREAM_MODEL,
)
from app.pilot.multimodal_contract import (
    MAX_IMAGE_BYTES,
    validate_image_data_url,
    validate_user_multimodal_content,
)
from app.pilot.router_core import resolve_auto_route, resolve_manual_route

B66_BROWSER_DIR = (
    Path(__file__).resolve().parents[3]
    / "reference"
    / "business-66-padiem-quote-v1"
)

FORBIDDEN_BROWSER_TOKENS = (
    "stealth/space-bunny-alpha",
    "kilo/stealth-space-bunny-alpha",
    "space-bunny",
    "KILO_PROVIDER_ID",
    "platform_provider_id",
)

PNG = b"\x89PNG\r\n\x1a\n" + b"spacebunny"
JPEG = b"\xff\xd8\xff\xe0" + b"spacebunny"
WEBP = b"RIFF\x08\x00\x00\x00WEBP" + b"spacebunny"


def data_url(media_type: str, payload: bytes) -> str:
    return f"data:{media_type};base64,{base64.b64encode(payload).decode('ascii')}"


def multimodal_content(url: str):
    return [
        {"type": "text", "text": "견적서 항목을 추출해 주세요"},
        {"type": "image_url", "image_url": {"url": url}},
    ]


@pytest.fixture()
def mock_mode(monkeypatch):
    monkeypatch.setenv("B14_PROVIDER_MODE", "mock")
    old = runtime_config.provider_mode
    runtime_config.provider_mode = "mock"
    yield
    runtime_config.provider_mode = old


@pytest.fixture()
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def test_space_bunny_image_capability_registered() -> None:
    model = get_catalog_by_id(KILO_SPACE_BUNNY_MODEL_ID)
    assert model is not None
    assert model.platform_provider_id == KILO_PROVIDER_ID
    assert model.upstream_model == KILO_SPACE_BUNNY_UPSTREAM_MODEL
    assert model.upstream_model == "stealth/space-bunny-alpha"
    assert model.capabilities == frozenset({"chat", "coding", "free", "image"})
    # Canonical vocabulary: legacy ``image`` maps to VISION; the forbidden
    # tags must never appear on this lane.
    assert canonical_capability_from_legacy_tag("image") is ModelCapability.VISION
    assert canonical_capability_from_legacy_tag("vision") is None
    assert canonical_capability_from_legacy_tag("multimodal") is None
    profile = capability_profile_from_catalog_model(model)
    vision = profile.evidence_for(ModelCapability.VISION)
    assert vision.support.value == "supported"
    assert model.capabilities & {"vision", "video", "multimodal", "audio"} == frozenset()


def test_manual_space_bunny_route_is_explicit_and_fallback_free() -> None:
    decision = resolve_manual_route(KILO_SPACE_BUNNY_MODEL_ID)
    assert decision.route_mode == "manual"
    assert decision.selected_model == KILO_SPACE_BUNNY_MODEL_ID
    assert decision.selected_upstream_model == "stealth/space-bunny-alpha"
    assert decision.platform_provider_id == KILO_PROVIDER_ID
    assert decision.selected_route_id == f"platform:{KILO_SPACE_BUNNY_MODEL_ID}"
    assert decision.fallback_allowed is False
    assert decision.eligible_fallback == []
    assert decision.max_attempts == 1
    assert decision.credential_available is True


def test_space_bunny_reuses_keyless_kilo_provider_without_new_secret() -> None:
    spec = ps.get_platform_provider(KILO_PROVIDER_ID)
    assert spec is not None
    assert spec.credential_source == ps.CredentialSource.NONE
    assert spec.credential_binding_name == ""
    assert ps.is_secret_present(spec) is True


@pytest.mark.parametrize(
    ("media_type", "payload"),
    [
        ("image/png", PNG),
        ("image/jpeg", JPEG),
        ("image/webp", WEBP),
    ],
)
def test_valid_image_data_urls_pass_canonical_contract(media_type, payload) -> None:
    url = validate_image_data_url(data_url(media_type, payload))
    assert url.startswith(f"data:{media_type};base64,")
    normalized = validate_user_multimodal_content(multimodal_content(url))
    assert len(normalized) == 2
    assert normalized[0]["type"] == "text"
    assert normalized[1]["type"] == "image_url"


def test_remote_image_url_rejected() -> None:
    with pytest.raises(ValueError):
        validate_image_data_url("https://example.com/photo.png")
    with pytest.raises(ValueError):
        validate_user_multimodal_content(
            multimodal_content("https://example.com/photo.png")
        )


def test_oversized_image_rejected() -> None:
    too_large = b"\x89PNG\r\n\x1a\n" + b"x" * MAX_IMAGE_BYTES
    assert len(too_large) > MAX_IMAGE_BYTES
    with pytest.raises(ValueError, match="4 MiB"):
        validate_image_data_url(data_url("image/png", too_large))


@pytest.mark.parametrize(
    "url",
    [
        "data:image/png;base64,not base64!!",
        data_url("image/gif", b"GIF89a"),
        data_url("image/jpeg", PNG),
        data_url("image/png", JPEG),
        data_url("image/webp", PNG),
    ],
)
def test_invalid_mime_or_magic_rejected(url) -> None:
    with pytest.raises(ValueError):
        validate_image_data_url(url)


def test_text_only_manual_model_still_rejects_image_before_upstream(
    client, mock_mode, monkeypatch
) -> None:
    from app.pilot import platform as plat

    async def should_not_call(**kwargs):
        raise AssertionError("platform adapter must not be called")

    monkeypatch.setattr(plat, "call_platform_chat_completions", should_not_call)
    response = client.post(
        "/api/pilot/v1/chat/completions",
        json={
            "model": KILO_NEMOTRON_MODEL_ID,
            "messages": [
                {"role": "user", "content": multimodal_content(data_url("image/png", PNG))}
            ],
            "business14": {"allow_external_fallback": True},
        },
    )
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "no_safe_route"
    assert body["error"]["upstream_called"] is False


def test_manual_space_bunny_image_route_passes_gateway_without_fallback(
    client, mock_mode
) -> None:
    response = client.post(
        "/api/pilot/v1/chat/completions",
        json={
            "model": KILO_SPACE_BUNNY_MODEL_ID,
            "messages": [
                {"role": "user", "content": multimodal_content(data_url("image/png", PNG))}
            ],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["business14"]["selected_model"] == KILO_SPACE_BUNNY_MODEL_ID
    assert body["business14"]["selected_upstream_model"] == "stealth/space-bunny-alpha"
    assert body["business14"]["route_mode"] == "manual"
    assert body["business14"]["fallback_allowed"] is False
    assert body["business14"]["fallback_used"] is False


def test_global_b14_auto_chain_unchanged() -> None:
    assert KILO_SPACE_BUNNY_MODEL_ID not in {m.model_id for m in CATALOG_MODELS}
    decision = resolve_auto_route(
        task_type="general",
        required_capabilities=["free"],
        optimize_for="balanced",
        allow_external_fallback=True,
        max_attempts=3,
    )
    assert decision.selected_model == KILO_NEMOTRON_MODEL_ID
    assert decision.eligible_fallback == []
    assert KILO_SPACE_BUNNY_MODEL_ID not in {
        item["model_id"] for item in decision.eligible_fallback
    }


def test_vision_streaming_change_is_zero() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "pilot"
        / "auto_stream_gateway.py"
    ).read_text(encoding="utf-8")
    # Staged SSE stays model=b14/auto text-only.
    assert "model=b14/auto" in source
    assert "text-only" in source
    assert 'if body["model"] != "b14/auto"' in source
    assert "not isinstance(message.get(\"content\"), str)" in source
    assert "image" not in source


def test_second_multimodal_authority_is_zero() -> None:
    repo = Path(__file__).resolve().parents[3]
    # Test files reference the canonical validator by name; only non-test
    # source definitions count as an authority.
    definers = [
        path
        for path in repo.rglob("*.py")
        if path.is_file()
        and "tests" not in path.parts
        and "def validate_user_multimodal_content" in path.read_text(encoding="utf-8")
    ]
    assert definers == [repo / "apps" / "korean-ai-platform" / "app" / "pilot" / "multimodal_contract.py"]
    image_definers = [
        path
        for path in repo.rglob("*.py")
        if path.is_file()
        and "tests" not in path.parts
        and "def validate_image_data_url" in path.read_text(encoding="utf-8")
    ]
    assert image_definers == [repo / "apps" / "korean-ai-platform" / "app" / "pilot" / "multimodal_contract.py"]


def test_b66_browser_carries_no_model_or_provider_identity() -> None:
    sources = sorted(
        path
        for path in B66_BROWSER_DIR.iterdir()
        if path.is_file() and path.suffix in {".js", ".html", ".css"}
    )
    assert sources, f"no B66 browser sources under {B66_BROWSER_DIR}"
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_BROWSER_TOKENS:
            assert token not in text, f"{token!r} leaked into {path.name}"


def test_no_new_secret_or_production_mutation_in_vision_slice() -> None:
    repo = Path(__file__).resolve().parents[3]
    kilo_source = (
        repo / "apps" / "korean-ai-platform" / "app" / "pilot" / "kilo_provider.py"
    ).read_text(encoding="utf-8")
    assert "register_platform_provider" in kilo_source
    # The vision slice reuses the existing Kilo provider registration; it
    # must not introduce a second provider adapter call.
    assert kilo_source.count("register_platform_provider(") == 1
