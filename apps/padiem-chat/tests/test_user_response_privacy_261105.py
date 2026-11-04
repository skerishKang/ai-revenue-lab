"""#6828 follow-up: user-facing responses stay free of model/provider names.

The 2026-11-05 sweep (follow-up to #6873/#6878/#6881) found the login state,
the chat error taxonomy and the voice error responses already clean, so this
module locks that state instead of changing behavior. Every needle is read
from the public B14 register (``b14_models.json``) at test time — no model or
provider name is written into this repository by these tests.

Scope decisions recorded here so the next sweep does not re-litigate them:

- ``google`` as a provider id is excluded from the needles: the same word is
  the user-facing login-method brand (the Google sign-in button) and the
  Drive connector brand, both of which are user-chosen services, not a model
  identity. Provider API hosts (``generativelanguage.googleapis.com`` …)
  stay in the needle set.
- The voice live-token SUCCESS response carries the model-locked session
  block on purpose (#6881): the browser opens the provider Live session
  directly and the ephemeral token is locked to that model. Removing it
  breaks voice; replacing the direct connection with a server relay is a
  separate design review, not this lock.
- BYOK (PADIEM Custom) surfaces are exempt: the names there are the user's
  own selection. Owner/admin screens are exempt by the same decision.
- ``/api/apps/ai`` is an HMAC service-to-server surface (BookAI b61), not a
  browser surface; it answers fixed codes and never echoes a model id.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.auth_abuse import InMemoryAuthAbuseStore
from app.b14_client import _chat_error
from app.main import create_app
from app.public_chat import public_chat_result
from app.voice_stt_routes import _error as voice_error
import app.voice_stt_routes as voice_routes
from test_password_auth import MemoryStore, password_settings

REGISTRY_PATH = (
    Path(__file__).resolve().parents[2]
    / "korean-ai-platform" / "app" / "pilot" / "b14_models.json"
)

#: The login-method brand shares its name with one registered provider id.
#: The brand is user-facing by design (sign-in button, Drive connector), so it
#: is not a model identity leak; everything else in the register is a needle.
LOGIN_BRAND_EXCEPTIONS = frozenset({"google"})


def _needles() -> list[str]:
    register = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    model_ids = [model["id"] for model in register.get("models", [])]
    upstream_names = [
        model["upstream_model"]
        for model in register.get("models", [])
        if isinstance(model.get("upstream_model"), str) and model["upstream_model"]
    ]
    provider_ids = [
        provider
        for provider in register.get("providers", {})
        if provider not in LOGIN_BRAND_EXCEPTIONS
    ]
    hosts: list[str] = []
    for config in register.get("providers", {}).values():
        origin = config.get("base_origin", "")
        if origin:
            hosts.append(origin.split("//", 1)[-1].split("/", 1)[0])
        hosts.extend(config.get("allowed_hosts", []))
    needles = sorted({n for n in (model_ids + upstream_names + provider_ids + hosts) if len(n) > 4})
    assert needles, "the B14 register must yield privacy needles"
    return needles


def _assert_private(text: str, needles: list[str], label: str) -> None:
    leaked = sorted(name for name in needles if name in text)
    assert not leaked, f"{label} leaks model/provider identifiers: {leaked}"


def _privacy_app():
    return create_app(
        password_settings(),
        history_store=MemoryStore(),
        auth_abuse_store=InMemoryAuthAbuseStore(),
    )


def test_auth_status_response_carries_no_model_or_provider_identifiers() -> None:
    """The login state answers flags only — never which model would serve."""
    client = TestClient(_privacy_app(), base_url="https://chat.example.test")
    response = client.get("/api/auth/status")
    assert response.status_code == 200
    _assert_private(response.text, _needles(), "GET /api/auth/status")


def test_password_login_failure_response_stays_generic() -> None:
    """A failed login answers the fixed nondisclosing copy, not identity text."""
    client = TestClient(_privacy_app(), base_url="https://chat.example.test")
    response = client.post(
        "/api/auth/password/login",
        json={"identifier": "nobody.example", "password": "wrong-password"},
    )
    assert response.status_code in (400, 401, 429)
    body = response.json()
    assert body["error"]["code"]
    assert body["error"]["message"]
    _assert_private(response.text, _needles(), "POST /api/auth/password/login (failure)")


def test_chat_error_taxonomy_messages_stay_generic() -> None:
    """Every chat runtime error keeps its fixed Korean copy, never upstream text."""
    source = Path(_chat_error.__code__.co_filename).read_text(encoding="utf-8")
    body = source[source.index("def _chat_error"):]
    codes = sorted(set(re.findall(r'code == "([a-z_]+)"', body)))
    assert len(codes) >= 8, codes
    for code in codes:
        error = _chat_error(code)
        # The external code may rename the trigger (execution_failed ->
        # upstream_execution_failed); the contract under test is the copy.
        assert error.user_message.strip()
        _assert_private(error.user_message, _needles(), f"chat error {code}")


def test_voice_error_responses_carry_only_their_bounded_code() -> None:
    """Voice refusals answer code-only; no provider name, host or raw body."""
    module_source = Path(voice_routes.__file__).read_text(encoding="utf-8")
    codes = sorted(set(re.findall(r'_error\("([a-z_]+)"', module_source)))
    assert len(codes) >= 10, codes
    for code in codes:
        response = voice_error(code, 503)
        body = json.loads(response.body)
        assert body["error"] == {"code": code, "message": code}
        _assert_private(response.body.decode("utf-8"), _needles(), f"voice error {code}")


def test_public_chat_projection_strips_registry_identities_nested() -> None:
    """#6878's boundary holds against the register's real values, nested deep."""
    register = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    first = register["models"][0]
    provider_id = first["provider_id"]
    leaky = {
        "answer": "답변 본문",
        "metadata": {
            "research": {
                "calls": [
                    {
                        "modelId": first["id"],
                        "providerName": provider_id,
                        "nested": {"upstream_model": first.get("upstream_model", first["id"])},
                    }
                ]
            },
            "routing": {
                "selected_model": first["id"],
                "hosts": [
                    config.get("base_origin", "")
                    for config in register.get("providers", {}).values()
                    if config.get("base_origin")
                ],
            },
        },
    }
    public = public_chat_result(leaky)
    text = json.dumps(public, ensure_ascii=False)
    assert public["answer"] == "답변 본문"
    for config in register.get("providers", {}).values():
        origin = config.get("base_origin", "")
        if origin:
            assert origin not in text
    assert first["id"] not in text
    assert provider_id not in text
