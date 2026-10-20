"""#5015: the Chat PC file lane composes from the one canonical Engine authority.

The bridge used to require its own caller id/credential pair that no activation
authority provisions, so it stayed None in Production and every Chat file
request answered "PC 파일 도구를 현재 사용할 수 없습니다" before a run existed.
These tests pin the reuse and the fail-closed posture.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.worker_orchestration import (
    ORCHESTRATION_ENABLED_ENV,
    build_orchestration_bridge,
)
from app.worker_config import P01_ENGINE_SERVICE_BINDING_NAME

VALID_CALLER = "b54-p01-overlay-20260914-a1"
VALID_CREDENTIAL = "c" * 48
LIVE = SimpleNamespace(runtime_mode="b14")
MOCK = SimpleNamespace(runtime_mode="mock")


def _env(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        ORCHESTRATION_ENABLED_ENV: "true",
        P01_ENGINE_SERVICE_BINDING_NAME: SimpleNamespace(name="engine-service"),
        "P01_ENGINE_CALLER_ID": VALID_CALLER,
        "P01_ENGINE_CREDENTIAL": VALID_CREDENTIAL,
    }
    values.update(overrides)
    return values


def _request_factory(url: str, **kwargs: object) -> object:  # pragma: no cover
    raise AssertionError("composition must not perform network transport")


def _build(env: dict[str, object], **overrides: object):
    options: dict[str, object] = {
        "settings": LIVE,
        "db_binding": object(),
        "request_factory": _request_factory,
    }
    options.update(overrides)
    return build_orchestration_bridge(env, **options)  # type: ignore[arg-type]


def test_armed_bridge_composes_from_the_canonical_p01_engine_binding() -> None:
    env = _env()
    bridge = _build(env)

    assert bridge is not None
    assert bridge.ready is True
    client = bridge._client
    assert client.app_id == "padiem-chat"
    assert client.caller_id == VALID_CALLER
    assert client._transport._binding is env[P01_ENGINE_SERVICE_BINDING_NAME]


def test_bridge_never_requires_a_second_caller_credential_pair() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "app" / "worker_orchestration.py"
    ).read_text(encoding="utf-8")

    assert "PADIEM_CHAT_ENGINE_CALLER_ID" not in source
    assert "PADIEM_CHAT_ENGINE_CALLER_SECRET" not in source
    # The armed composition above succeeds with no such values in the env.
    assert _build(_env()) is not None


def test_bridge_stays_none_while_the_activation_flag_is_off() -> None:
    assert _build(_env(**{ORCHESTRATION_ENABLED_ENV: "false"})) is None


def test_bridge_stays_none_while_the_worker_is_not_live_b14() -> None:
    assert _build(_env(), settings=MOCK) is None


def test_bridge_stays_none_without_the_canonical_engine_binding() -> None:
    assert _build(_env(**{P01_ENGINE_SERVICE_BINDING_NAME: None})) is None


def test_bridge_stays_none_without_a_d1_binding() -> None:
    assert _build(_env(), db_binding=None) is None


def test_bridge_stays_none_on_a_malformed_canonical_credential() -> None:
    assert _build(_env(**{"P01_ENGINE_CREDENTIAL": "short"})) is None
