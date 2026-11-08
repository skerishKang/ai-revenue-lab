"""#6828 stage 1: user paths answer with a PADIEM grade, never a model id.

The 2026-11-08 sweep found the browser surfaces already clean (login state,
chat error taxonomy, voice refusals, the Claw grade line, the shipped static
scripts) and one remaining product leak: the two B66 browser replies echoed the
resolved ``model_id``. This module locks the clean state and the new reply
shape.

Needles are read from the B14 register at test time, so no model or provider
name is written into this repository by the test itself.

Recorded exemptions (they are decisions, not oversights):

- PADIEM Custom (BYOK): the model id is the customer's own explicit selection,
  so the custom reply still carries it.
- Owner/admin screens: ``static/admin*`` and ``/api/b66/admin/*``.
- Voice live session: the browser opens the provider Live session directly
  (#6881), so ``voice-live-session.js`` and the voice token success block keep
  that provider host. Replacing the direct connection with a server relay is a
  separate design review.
"""
from __future__ import annotations

import json
from pathlib import Path

from starlette.testclient import TestClient

from test_b66_ai_chat_routes_4466 import payload, setup, sign_in
from test_user_response_privacy_261105 import _assert_private, _needles, _privacy_app

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
REGISTRY_PATH = (
    Path(__file__).resolve().parents[2]
    / "korean-ai-platform" / "app" / "pilot" / "b14_models.json"
)

#: The login-method brand shares one registered provider id (see the voice and
#: sign-in surfaces), so it is not a model identity.
LOGIN_BRAND_EXCEPTIONS = frozenset({"google"})


def _identity_needles() -> list[str]:
    """Model, upstream and provider identifiers — hosts are a response check."""
    register = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    names = [model["id"] for model in register.get("models", [])]
    names += [
        model["upstream_model"]
        for model in register.get("models", [])
        if isinstance(model.get("upstream_model"), str) and model["upstream_model"]
    ]
    names += [
        provider
        for provider in register.get("providers", {})
        if provider not in LOGIN_BRAND_EXCEPTIONS
    ]
    needles = sorted({name for name in names if len(name) > 4})
    assert needles, "the B14 register must yield identity needles"
    return needles


def _offenders(path: Path, needles: list[str]) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return sorted(name for name in needles if name in text)


def test_user_static_scripts_carry_no_registry_identity() -> None:
    """The shipped browser scripts never name a managed model or provider.

    A user can read every one of these files, so a name here is a product
    leak no matter what the API answers. Admin screens are owner-only and are
    out of this contract.
    """
    needles = _identity_needles()
    offenders: dict[str, list[str]] = {}
    for path in sorted(STATIC_DIR.glob("*.js")):
        if path.name.startswith("admin"):
            continue
        leaked = _offenders(path, needles)
        if leaked:
            offenders[path.name] = leaked
    for name in ("index.html", "locale.js"):
        path = STATIC_DIR / name
        if path.is_file():
            leaked = _offenders(path, needles)
            if leaked:
                offenders[name] = leaked
    assert not offenders, f"user-facing static files leak identities: {offenders}"


def test_health_response_carries_no_registry_identity() -> None:
    """The public readiness answer is flags only — it names no model."""
    client = TestClient(_privacy_app(), base_url="https://chat.example.test")
    response = client.get("/health")
    assert response.status_code == 200
    _assert_private(response.text, _needles(), "GET /health")


def test_managed_chat_reply_carries_no_model_identity() -> None:
    """A tier answer names the grade only; the id stays server-side."""
    settings, client, resolver, model = setup()
    sign_in(settings, client)
    response = client.post("/api/b66/ai/chat", json=payload())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["model_origin"] == "registered_model_completion"
    assert "model_id" not in body
    assert len(resolver.calls) == 1 and len(model.calls) == 1
    _assert_private(response.text, _needles(), "POST /api/b66/ai/chat")
