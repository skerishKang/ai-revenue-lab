"""Host orchestration bridge: the Worker's own gate, the host's transport.

Two claims are under test:

* the Worker and the CPython host compose the *same* bridge from the *same*
  function, so a host cannot activate on a different switch or skip the D1
  state store;
* the host installs the routes only together with a real bridge, so a host that
  is not configured keeps today's direct-B14 behaviour untouched.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from padiem_control_plane import AuthSessionSnapshot, AuthSessionState, CanonicalSubjectRef, SubjectType
from starlette.applications import Starlette

from app import orchestration_composition as composition
from app.canonical_orchestration_bridge import CanonicalSubjectB62EngineOrchestrationBridge
from app.control_plane_identity import IdentityBridgeError
from app.local_cpython import CurrentCanonicalSubjectResolver, compose_host_orchestration
from app.orchestration_bridge import B62EngineOrchestrationBridge, D1OrchestrationStateStore
from app.worker_orchestration import build_orchestration_bridge

ENABLED = {"PADIEM_CHAT_ORCHESTRATION_ENABLED": "true"}
ORCHESTRATION_PATHS = {
    "/api/orchestration",
    "/api/orchestration/status",
    "/api/orchestration/resume",
    "/api/orchestration/cancel",
}


class _Db:
    """A D1-shaped stand-in; composition never runs SQL."""

    def prepare(self, sql):  # pragma: no cover - composition only stores it
        raise AssertionError("no SQL runs while composing the bridge")


class _Engine:
    """A client stand-in. Composition must not call the Engine."""

    async def orchestrate(self, *args, **kwargs):  # pragma: no cover - never called
        raise AssertionError("composition must not call the Engine")


def _b14() -> SimpleNamespace:
    return SimpleNamespace(runtime_mode="b14")


def _paths(app: Starlette) -> set[str]:
    return {getattr(route, "path", "") for route in app.router.routes}


def test_the_bridge_is_off_without_the_worker_switch() -> None:
    assert composition.compose_orchestration_bridge(
        env={},
        settings=_b14(),
        db_binding=_Db(),
        build_client=lambda: _Engine(),
    ) is None


def test_an_unreadable_switch_value_stays_off() -> None:
    assert composition.compose_orchestration_bridge(
        env={"PADIEM_CHAT_ORCHESTRATION_ENABLED": "yes"},
        settings=_b14(),
        db_binding=_Db(),
        build_client=lambda: _Engine(),
    ) is None


def test_the_bridge_requires_the_b14_runtime_mode() -> None:
    assert composition.compose_orchestration_bridge(
        env=ENABLED,
        settings=SimpleNamespace(runtime_mode="mock"),
        db_binding=_Db(),
        build_client=lambda: _Engine(),
    ) is None


def test_the_bridge_requires_a_state_store_binding() -> None:
    assert composition.compose_orchestration_bridge(
        env=ENABLED,
        settings=_b14(),
        db_binding=None,
        build_client=lambda: _Engine(),
    ) is None


def test_one_client_and_one_d1_store_when_every_prerequisite_holds() -> None:
    built: list[str] = []
    engine = _Engine()

    def build_client():
        built.append("built")
        return engine

    bridge = composition.compose_orchestration_bridge(
        env=ENABLED, settings=_b14(), db_binding=_Db(), build_client=build_client
    )

    assert isinstance(bridge, B62EngineOrchestrationBridge)
    assert bridge.ready is True
    assert built == ["built"]
    assert isinstance(bridge._store, D1OrchestrationStateStore)


def test_a_client_that_cannot_be_built_leaves_the_bridge_off() -> None:
    assert composition.compose_orchestration_bridge(
        env=ENABLED,
        settings=_b14(),
        db_binding=_Db(),
        build_client=lambda: None,
    ) is None


def test_the_canonical_subject_variant_reuses_the_same_composition() -> None:
    bridge = composition.compose_orchestration_bridge(
        env=ENABLED,
        settings=_b14(),
        db_binding=_Db(),
        build_client=lambda: _Engine(),
        canonical_subject_resolver=lambda *args, **kwargs: None,
    )

    assert isinstance(bridge, CanonicalSubjectB62EngineOrchestrationBridge)


def test_the_worker_composes_through_the_shared_gate(monkeypatch) -> None:
    """The Worker path still builds its Service Binding client, unchanged."""

    worker_env = {
        "PADIEM_CHAT_ORCHESTRATION_ENABLED": "true",
        "P01_ENGINE_SERVICE": object(),
        "P01_ENGINE_CALLER_ID": "b62-chat",
        "P01_ENGINE_CREDENTIAL": "y" * 40,
    }
    requests: list[tuple] = []

    def request_factory(url, *, method=None, headers=None, body=None):
        requests.append((url, method, dict(headers or {}), body))
        return SimpleNamespace(js_object=SimpleNamespace())

    bridge = build_orchestration_bridge(
        worker_env,
        settings=_b14(),
        db_binding=_Db(),
        request_factory=request_factory,
    )

    assert isinstance(bridge, B62EngineOrchestrationBridge)
    # Composition builds the client, not a request.
    assert requests == []
    transport = bridge._client._transport
    assert type(transport).__name__ == "CloudflareEngineServiceTransport"


def test_the_worker_and_the_host_share_one_gate_function() -> None:
    import app.worker_orchestration as worker_orchestration

    assert (
        worker_orchestration.compose_orchestration_bridge
        is composition.compose_orchestration_bridge
    )
    assert (
        worker_orchestration.ORCHESTRATION_ENABLED_ENV
        == composition.ORCHESTRATION_ENABLED_ENV
    )


def test_the_host_installs_nothing_when_it_is_not_configured() -> None:
    app = Starlette(routes=[])

    bridge = compose_host_orchestration(
        app, env={}, settings=_b14(), db_binding=_Db(), client=_Engine()
    )

    assert bridge is None
    assert getattr(app.state, "orchestration_bridge", None) is None
    assert not (_paths(app) & ORCHESTRATION_PATHS)


def test_the_host_installs_the_bridge_and_its_routes_when_configured() -> None:
    app = Starlette(routes=[])
    env = {
        **ENABLED,
        "PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN": "http://127.0.0.1:8811",
        "PADIEM_CHAT_LOCAL_P01_CALLER_ID": "b62-chat",
        "PADIEM_CHAT_LOCAL_P01_ENGINE_CREDENTIAL": "z" * 40,
    }

    bridge = compose_host_orchestration(
        app, env=env, settings=_b14(), db_binding=_Db(), client=_Engine()
    )

    assert isinstance(bridge, B62EngineOrchestrationBridge)
    assert getattr(app.state, "orchestration_bridge", None) is bridge
    assert _paths(app) >= ORCHESTRATION_PATHS
    assert type(bridge._client._transport).__name__ == "LocalEngineHttpTransport"


def test_a_malformed_host_origin_leaves_the_bridge_off() -> None:
    app = Starlette(routes=[])
    env = {
        **ENABLED,
        "PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN": "https://engine.padiem.net",
        "PADIEM_CHAT_LOCAL_P01_CALLER_ID": "b62-chat",
        "PADIEM_CHAT_LOCAL_P01_ENGINE_CREDENTIAL": "z" * 40,
    }

    assert compose_host_orchestration(
        app, env=env, settings=_b14(), db_binding=_Db()
    ) is None
    assert not (_paths(app) & ORCHESTRATION_PATHS)


def test_a_short_host_credential_leaves_the_bridge_off() -> None:
    app = Starlette(routes=[])
    env = {
        **ENABLED,
        "PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN": "http://127.0.0.1:8811",
        "PADIEM_CHAT_LOCAL_P01_CALLER_ID": "b62-chat",
        "PADIEM_CHAT_LOCAL_P01_ENGINE_CREDENTIAL": "z",
    }

    assert compose_host_orchestration(
        app, env=env, settings=_b14(), db_binding=_Db()
    ) is None


def _canonical_session():
    now = datetime.now(timezone.utc)
    return AuthSessionSnapshot(
        session_id="session-host-test", product_id="b62",
        subject=CanonicalSubjectRef(SubjectType.USER, "sub_host_test"),
        issued_at=now - timedelta(minutes=5), expires_at=now + timedelta(minutes=5),
    )


class _CurrentAuthority:
    def __init__(self, session):
        self.session = session
        self.calls = []

    async def resolve_current_auth_session(self, **kwargs):
        self.calls.append(kwargs)
        return self.session


def test_host_resolves_current_canonical_subject_without_a_shadow_row():
    app = Starlette(routes=[])
    authority = _CurrentAuthority(_canonical_session())
    app.state.control_plane_identity_authority = authority
    env = {
        **ENABLED,
        "PADIEM_CHAT_LOCAL_P01_ENGINE_ORIGIN": "http://127.0.0.1:8811",
        "PADIEM_CHAT_LOCAL_P01_CALLER_ID": "b62-chat",
        "PADIEM_CHAT_LOCAL_P01_ENGINE_CREDENTIAL": "z" * 40,
    }
    bridge = compose_host_orchestration(
        app, env=env, settings=_b14(), db_binding=_Db(), client=_Engine(),
    )
    assert isinstance(bridge, CanonicalSubjectB62EngineOrchestrationBridge)
    assert asyncio.run(bridge._resolve_engine_subject("usr_host_test")) == "sub_host_test"
    assert authority.calls == [{"product_id": "b62", "product_user_id": "usr_host_test"}]


@pytest.mark.parametrize("variant,code", [
    ("untyped", "control_plane_session_invalid"),
    ("product", "control_plane_session_mismatch"),
    ("account", "control_plane_session_mismatch"),
    ("revoked", "control_plane_session_inactive"),
    ("expired", "control_plane_session_inactive"),
])
def test_host_subject_resolution_rejects_invalid_current_sessions(variant, code):
    session = _canonical_session()
    if variant == "untyped":
        session = session.to_public_dict()
    elif variant == "product":
        session = replace(session, product_id="b54-padiem-claw")
    elif variant == "account":
        session = replace(session, subject=CanonicalSubjectRef(SubjectType.ACCOUNT, "account-host"))
    elif variant == "revoked":
        session = replace(session, state=AuthSessionState.REVOKED)
    elif variant == "expired":
        session = replace(session, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    resolver = CurrentCanonicalSubjectResolver(_CurrentAuthority(session))
    with pytest.raises(IdentityBridgeError) as refused:
        asyncio.run(resolver.resolve_subject_id(product_user_id="usr_host_test"))
    assert refused.value.code == code
