"""#6828 stage 2 ①: identity-bearing model authority is a proven-caller surface.

`/api/pilot/models` and `/api/pilot/health` are reachable from the public
internet and, before this change, answered with provider ids, model ids and
registered routes. The owner's release tooling still needs that detail, so it
moves behind the existing B14 caller proof (#5224) on `/api/pilot/admin/...`
instead of gaining a second authority or a new secret.

Network-free: no Provider call, no real credential, no Production mutation.
"""
from __future__ import annotations

import json
import os
import time

import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot.service_proof import (
    PROOF_HEADER,
    PROOF_TIME_HEADER,
    SERVICE_PROOF_BINDING,
    compute_service_proof,
)

ADMIN_HEALTH = "/api/pilot/admin/health"
ADMIN_MODELS = "/api/pilot/admin/models"
PUBLIC_HEALTH = "/api/pilot/health"
PUBLIC_MODELS = "/api/pilot/models"
SECRET = "b14-test-service-proof-secret-0123456789abcdef"


@pytest.fixture()
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


def test_a_proven_caller_reads_the_authority_detail(client):
    """The release tooling keeps the exact detail it needs, names included."""
    health = client.get(ADMIN_HEALTH)
    models = client.get(ADMIN_MODELS)

    assert health.status_code == 200, health.text
    assert models.status_code == 200, models.text

    providers = health.json()["business14"]["providers"]
    assert isinstance(providers, list) and providers
    assert all(isinstance(row.get("id"), str) and row["id"] for row in providers)

    # Registration and execution are separate lists and both stay available.
    for key in ("catalog", "registered_routes"):
        assert isinstance(models.json().get(key), list), key
    assert isinstance(models.json().get("model_groups"), dict)
    assert models.json()["registered_routes"]


@pytest.mark.no_b14_service_proof
def test_an_unproven_caller_is_refused_before_any_detail(client):
    """No proof, no provider or model name — on both detail routes."""
    for path in (ADMIN_HEALTH, ADMIN_MODELS):
        result = client.get(path)
        assert result.status_code == 401, path
        assert result.json()["error"]["code"] == "b14_service_proof_required"
        assert SECRET not in result.text


@pytest.mark.no_b14_service_proof
def test_a_wrongly_signed_caller_is_refused(client):
    """A proof that does not match this exact request authorizes nothing."""
    timestamp = str(int(time.time()))
    for path in (ADMIN_HEALTH, ADMIN_MODELS):
        result = client.get(
            path,
            headers={
                PROOF_HEADER: compute_service_proof("not-the-secret-" + "x" * 32, timestamp, b""),
                PROOF_TIME_HEADER: timestamp,
            },
        )
        assert result.status_code == 401, path
        assert result.json()["error"]["code"] == "b14_service_proof_required"


@pytest.mark.no_b14_service_proof
def test_an_unconfigured_deployment_secret_fails_closed(client, monkeypatch):
    """Without the deployment binding the detail routes refuse, they do not open."""
    monkeypatch.delenv(SERVICE_PROOF_BINDING, raising=False)
    result = client.get(ADMIN_MODELS)
    assert result.status_code == 503
    assert result.json()["error"]["code"] == "b14_service_proof_unconfigured"


@pytest.mark.no_b14_service_proof
def test_the_public_read_surfaces_stay_open_without_a_proof(client):
    """Stage 1 keeps the public URLs answering; only the detail moved."""
    assert os.environ.get(SERVICE_PROOF_BINDING)
    for path in (PUBLIC_HEALTH, PUBLIC_MODELS):
        assert client.get(path).status_code == 200, path


# -- #7450: the serving grade routes are proven-caller detail -----------------

_GRADE_PRIMARY_A = "example-provider/example-model-1"
_GRADE_PRIMARY_B = "example-provider/example-model-2"


def _private_document() -> dict:
    def row(model_id: str, upstream: str, caps: list[str]) -> dict:
        return {
            "id": model_id,
            "provider_id": "example-provider",
            "upstream_model": upstream,
            "capabilities": caps,
            "enabled": True,
            "display_name": upstream.replace("-", " ").title(),
            "provider_name": "Example Provider",
            "context_window": 128000,
            "input_price_usd_per_1m": 0.0,
            "output_price_usd_per_1m": 0.0,
            "source": "fixture",
            "source_checked_at": "2026-11-09",
        }

    return {
        "version": "padiem.models.private.v1",
        "providers": {
            "example-provider": {
                "base_origin": "https://api.example.invalid/v1",
                "allowed_hosts": ["api.example.invalid"],
                "credential_binding": "PADIEM_B14_CREDENTIAL_99",
            }
        },
        "models": [
            row(_GRADE_PRIMARY_A, "example-model-1", ["chat"]),
            row(_GRADE_PRIMARY_B, "example-model-2", ["chat", "tools"]),
        ],
        "tiers": {
            "free": {"primary": _GRADE_PRIMARY_A, "fallback": [_GRADE_PRIMARY_B]},
            "plus": {"primary": _GRADE_PRIMARY_B, "fallback": [_GRADE_PRIMARY_A]},
            "pro": {"primary": _GRADE_PRIMARY_B, "fallback": []},
            "max": {"primary": _GRADE_PRIMARY_B, "fallback": []},
        },
    }


def test_the_serving_grade_routes_travel_on_the_proven_detail_only(
    client, monkeypatch, tmp_path
):
    """#7450: the nightly grade smoke reads the serving route from this surface.

    With the registry switch on, the proven detail answers the primary serving
    each product grade — the same authority the dispatch resolves from. The
    public /models projection stays grade-availability only, and the unproven
    refusals above cover this field too.
    """
    from app.pilot import model_registry_file
    from app.pilot.config import pilot_settings
    from app.pilot.registry import reset_registry

    target = tmp_path / "models-private.json"
    target.write_text(json.dumps(_private_document()), encoding="utf-8")
    os.chmod(target, 0o600)
    providers_json = json.dumps([{
        "provider_id": "example-provider",
        "display_name": "Example Provider",
        "base_url": "https://api.example.invalid/v1",
        "timeout_seconds": 600,
        "models": [
            {"model_id": _GRADE_PRIMARY_A, "upstream_model": "example-model-1",
             "display_name": "Example Model 1", "enabled": True},
            {"model_id": _GRADE_PRIMARY_B, "upstream_model": "example-model-2",
             "display_name": "Example Model 2", "enabled": True},
        ],
    }])
    saved = {name: os.environ.get(name) for name in (
        "PADIEM_MODELS_REGISTRY", "PADIEM_MODELS_REGISTRY_OVERRIDE",
        "BUSINESS14_PROVIDER_REGISTRY_JSON")}
    saved_settings = pilot_settings.provider_registry_json
    try:
        os.environ["PADIEM_MODELS_REGISTRY"] = str(target)
        os.environ["BUSINESS14_PROVIDER_REGISTRY_JSON"] = providers_json
        # pilot_settings reads the environment once at import, so the singleton
        # itself carries the switch for this test (the wiring suites do the
        # same for the snapshot globals).
        pilot_settings.provider_registry_json = providers_json
        model_registry_file._PRIVATE_SNAPSHOT = None
        reset_registry()
        model_registry_file.install_models()

        models = client.get(ADMIN_MODELS)
        assert models.status_code == 200, models.text
        routes = models.json()["tier_routes"]
        assert routes["free"] == _GRADE_PRIMARY_A
        assert routes["plus"] == routes["pro"] == routes["max"] == _GRADE_PRIMARY_B

        public = client.get(PUBLIC_MODELS)
        assert public.status_code == 200
        assert "tier_routes" not in public.json()
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        pilot_settings.provider_registry_json = saved_settings
        model_registry_file._PRIVATE_SNAPSHOT = None
        reset_registry()
        model_registry_file.install_models()


def _override_only_environment(tmp_path):
    """Serve from the private document through the OVERRIDE alone.

    The production shape for the live branch: the primary switch is unset, the
    OVERRIDE names the document, and the BYOK pilot registry JSON is absent so
    the pilot state machine answers NOT_CONFIGURED. Returns the saved
    environment for `_restore_registry_environment`.
    """
    from app.pilot.config import pilot_settings

    target = tmp_path / "models-private-override.json"
    target.write_text(json.dumps(_private_document()), encoding="utf-8")
    os.chmod(target, 0o600)
    saved = {name: os.environ.get(name) for name in (
        "PADIEM_MODELS_REGISTRY", "PADIEM_MODELS_REGISTRY_OVERRIDE",
        "BUSINESS14_PROVIDER_REGISTRY_JSON")}
    saved_settings = pilot_settings.provider_registry_json
    os.environ.pop("PADIEM_MODELS_REGISTRY", None)
    os.environ.pop("BUSINESS14_PROVIDER_REGISTRY_JSON", None)
    os.environ["PADIEM_MODELS_REGISTRY_OVERRIDE"] = str(target)
    pilot_settings.provider_registry_json = ""
    return saved, saved_settings


def _restore_registry_environment(saved, saved_settings):
    """Undo `_override_only_environment` and reinstall the ambient catalog."""
    from app.pilot import model_registry_file
    from app.pilot.config import pilot_settings
    from app.pilot.registry import reset_registry

    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    pilot_settings.provider_registry_json = saved_settings
    model_registry_file._PRIVATE_SNAPSHOT = None
    reset_registry()
    model_registry_file.install_models()


def test_the_live_branch_also_answers_serving_grade_routes(
    client, monkeypatch, tmp_path
):
    """#7450: a host serving live through the OVERRIDE keeps the same detail.

    The private model registry is on (OVERRIDE included) while the BYOK pilot
    registry JSON is absent, so the pilot state machine answers NOT_CONFIGURED
    and the proven model detail falls to its final branch. The serving grade
    routes must travel there too, from the same installed document — not a
    second authority, and empty without a usable document.
    """
    from app.pilot import model_registry_file
    from app.pilot.registry import reset_registry

    saved, saved_settings = _override_only_environment(tmp_path)
    try:
        model_registry_file._PRIVATE_SNAPSHOT = None
        reset_registry()
        model_registry_file.install_models()

        models = client.get(ADMIN_MODELS)
        assert models.status_code == 200, models.text
        body = models.json()
        # The live-branch shape: the pilot JSON is absent, the catalog is not.
        assert body["configured"] is False
        assert {row["id"] for row in body["catalog"]} == {
            _GRADE_PRIMARY_A, _GRADE_PRIMARY_B}
        routes = body["tier_routes"]
        assert routes["free"] == _GRADE_PRIMARY_A
        assert routes["plus"] == routes["pro"] == routes["max"] == _GRADE_PRIMARY_B
        # Exact ids only: no origin, no credential name, no fallback roster.
        assert set(routes) == {"free", "plus", "pro", "max"}
    finally:
        _restore_registry_environment(saved, saved_settings)


def test_the_live_branch_public_projection_stays_identity_free(
    client, monkeypatch, tmp_path
):
    """#7450: the OVERRIDE-live state adds nothing to the public projection.

    The public /models wrapper builds its own body, so the serving grade routes
    the proven detail now carries in this state must not leak through it: no
    field and no fixture identity anywhere on the public surface.
    """
    from app.pilot import model_registry_file
    from app.pilot.registry import reset_registry

    saved, saved_settings = _override_only_environment(tmp_path)
    try:
        model_registry_file._PRIVATE_SNAPSHOT = None
        reset_registry()
        model_registry_file.install_models()

        public = client.get(PUBLIC_MODELS)
        assert public.status_code == 200, public.text
        assert "tier_routes" not in public.json()
        for identity in (_GRADE_PRIMARY_A, _GRADE_PRIMARY_B, "example-provider",
                         "Example Provider", "Example Model"):
            assert identity not in public.text
        health = client.get(PUBLIC_HEALTH)
        assert health.status_code == 200, health.text
        assert "example-provider" not in health.text
    finally:
        _restore_registry_environment(saved, saved_settings)
