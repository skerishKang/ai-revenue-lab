"""#6828: a user-facing B14 string or screen names no Provider or model identity.

Two surfaces are reachable by a visitor who holds no caller proof:

* ``/pilot`` renders ``error.message`` from the PilotError that failed a request
  (``app/pilot/ui.py`` → ``templates/pilot.html``), so an upstream failure
  message is page text.
* ``/workspace`` is served on a plain GET (``app/pilot/workspace.py``), so its
  picker labels and injected config are page text.

Neither may carry an identity. Which identities count is read from the effective
registry document and the platform Provider table, so this file writes no
Provider, host or model name of its own.
"""
from __future__ import annotations

import inspect
import json
import re

import pytest


def _provider_tokens() -> set[str]:
    """Provider identities the effective registry and Provider table declare."""
    from app.pilot.catalog import CATALOG_BY_ID
    from app.pilot.platform_secrets import list_platform_providers

    tokens: set[str] = set()
    for model in CATALOG_BY_ID.values():
        tokens |= {
            model.provider,
            model.platform_provider_id,
            model.credential_source,
        }
    for spec in list_platform_providers():
        tokens |= {spec.provider_id, spec.credential_binding_name}
    return {t for t in tokens if isinstance(t, str) and len(t) >= 4}


def _model_tokens() -> set[str]:
    """Model identities the effective registry declares."""
    from app.pilot.catalog import CATALOG_BY_ID

    tokens: set[str] = set()
    for model in CATALOG_BY_ID.values():
        tokens |= {model.model_id, model.upstream_model, model.display_name}
    return {t for t in tokens if isinstance(t, str) and len(t) >= 4}


def _leaks(text: str, tokens: set[str]) -> list[str]:
    lowered = text.casefold()
    return sorted(token for token in tokens if token.casefold() in lowered)


def _workspace_catalog_ids(client) -> list[str]:
    """The catalog ids the page itself hands the screen for one request."""
    response = client.get("/workspace")
    match = re.search(
        r'<script id="workspace-config" type="application/json">\s*(.*?)\s*</script>',
        response.text,
        re.DOTALL,
    )
    assert match
    entries = json.loads(match.group(1))["b14CatalogModels"]
    assert entries, "the workspace page renders no catalog entry"
    return [entry["model_id"] for entry in entries]


@pytest.fixture()
def live_mode():
    from app.pilot.b14_runtime_config import runtime_config

    previous = runtime_config.provider_mode
    runtime_config.provider_mode = "live"
    try:
        yield
    finally:
        runtime_config.provider_mode = previous


# ---------------------------------------------------------------------------
# 1. Error messages returned to a caller
# ---------------------------------------------------------------------------
def test_no_pilot_error_message_names_a_provider():
    """Every PilotError default message is safe to return as ``error.message``.

    The sweep is over the error classes themselves, so a new class with a
    Provider-specific default fails here without this file naming it.
    """
    from app.pilot import errors as error_module

    tokens = _provider_tokens()
    assert tokens, "the effective registry declares no Provider identity"
    checked = 0
    for name, error_class in vars(error_module).items():
        if not inspect.isclass(error_class):
            continue
        if not issubclass(error_class, error_module.PilotError):
            continue
        if error_class is error_module.PilotError:
            continue
        try:
            instance = error_class()
        except TypeError:
            continue  # a class that demands its own message is checked at its call site
        message = getattr(instance, "message", "")
        assert not _leaks(str(message), tokens), (
            f"{name} default message names a Provider identity"
        )
        checked += 1
    assert checked >= 5, "the error sweep installed no PilotError classes"


def test_upstream_failure_messages_stay_neutral_per_provider():
    """401/403/429 mapping must not echo the Provider the route belonged to."""
    import pytest as _pytest

    from app.pilot.errors import PilotError
    from app.pilot.platform import _raise_upstream_error
    from app.pilot.platform_secrets import list_platform_providers

    tokens = _provider_tokens()
    providers = [spec.provider_id for spec in list_platform_providers()]
    assert providers, "the Provider table is empty; nothing to check"
    for provider_id in providers:
        for status in (401, 403, 429, 503):
            with _pytest.raises(PilotError) as raised:
                _raise_upstream_error(status, provider_id=provider_id, body_text="", model_id="m")
            message = str(raised.value.message)
            assert message.strip(), "an upstream failure returned an empty message"
            assert not _leaks(message, tokens), (
                f"status {status} for one Provider echoes an identity"
            )


# ---------------------------------------------------------------------------
# 2. Workspace picker
# ---------------------------------------------------------------------------
def test_workspace_picker_labels_are_padiem_grades(client):
    """The picker is page text: no Provider or model identity may be rendered."""
    response = client.get("/workspace")
    assert response.status_code == 200
    labels = re.findall(r"<option[^>]*>([^<]*)</option>", response.text)
    assert labels, "the workspace page renders no picker option"
    picker = [label for label in labels if "PADIEM" in label]
    assert picker, "the catalog picker renders no PADIEM label"
    forbidden = _provider_tokens() | _model_tokens()
    for label in picker:
        assert not _leaks(label, forbidden), "a picker label names an identity"
    assert len(picker) >= 1


def test_workspace_config_carries_no_identity_fields(client):
    """The injected config hands the screen a label, not a Provider or model name."""
    response = client.get("/workspace")
    match = re.search(
        r'<script id="workspace-config" type="application/json">\s*(.*?)\s*</script>',
        response.text,
        re.DOTALL,
    )
    assert match
    config = json.loads(match.group(1))
    entries = config["b14CatalogModels"]
    assert entries, "the workspace config carries no catalog entry"
    for entry in entries:
        assert set(entry) == {"model_id", "label", "korean_score"}, (
            "a catalog entry hands the page a field it must not have"
        )
        assert entry["label"].startswith("PADIEM")
        assert not _leaks(entry["label"], _provider_tokens() | _model_tokens())


def test_preview_metadata_carries_no_provider_identity():
    """The stream preview body is returned to the caller: no Provider identity."""
    from app.pilot.router_core import RouteDecision
    from app.pilot.stream_gateway import _route_metadata

    model_id = "padiem/fixture-model"
    decision = RouteDecision(
        route_mode="manual",
        selected_provider="fixture-provider",
        selected_model=model_id,
        selected_upstream_model="fixture-upstream-model",
        selected_route_id=f"platform:{model_id}",
        reason_codes=["manual:pinned"],
        fallback_allowed=False,
        eligible_fallback=[],
        excluded_candidates=[],
        credential_available=True,
        credential_status="key_available",
        evidence_status="configured",
        request_id="b14req_fixture",
        provider_mode="live",
    )
    metadata = _route_metadata(request_id="b14req_fixture", decision=decision)
    assert metadata["selected_model"] == model_id
    assert "selected_provider" not in metadata
    assert "selected_upstream_model" not in metadata
    serialized = json.dumps(metadata)
    assert not _leaks(serialized, _provider_tokens() | {"fixture-upstream-model"})


# ---------------------------------------------------------------------------
# 3. Why the screen had to change rather than be exempted
# ---------------------------------------------------------------------------
@pytest.mark.no_b14_service_proof
def test_workspace_page_is_public_while_catalog_chat_needs_a_proof(client, live_mode):
    """The screen answers anyone; only the proof-bearing response lane is gated.

    That asymmetry is why #6828 fixed the screen instead of treating it as an
    owner-only surface: a visitor reads the page, so the page names no identity,
    while the routing evidence that does name identities stays on the lane the
    caller proof already restricts.
    """
    page = client.get("/workspace")
    assert page.status_code == 200

    chat = client.post(
        "/api/pilot/v1/chat/completions",
        json={"model": _workspace_catalog_ids(client)[0],
              "messages": [{"role": "user", "content": "안녕"}]},
    )
    assert chat.status_code == 401
    assert chat.json()["error"]["code"] == "b14_service_proof_required"
