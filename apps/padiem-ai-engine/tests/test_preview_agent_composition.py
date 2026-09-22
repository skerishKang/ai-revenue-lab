"""Preview Agent lane composition tests (#2786 Stage 11-C).

M2 scope: an explicitly marked non-production isolate composes a *synthetic*
Agent authority -- no provider runtime, no D1, no session or caller registry, no
secret, no user data. Every other isolate, Production included, keeps the
resolver-less fail-closed composition the Engine has always had.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import sys
import types
from pathlib import Path
from typing import Any

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import app.agent_preview_authority as preview_authority  # noqa: E402
from app.agent_preview_authority import (  # noqa: E402
    DEPLOY_ENV_NAME,
    ENABLE_ENV_NAME,
    PREVIEW_AGENT_ID,
    PREVIEW_APP_ID,
    PREVIEW_ENABLE_MARKER,
    PREVIEW_RUNTIME_TOOL_ID,
    PREVIEW_SUBJECT_ID,
    build_preview_agent_lane,
    preview_task_payload,
)
from app.agent_skill_service import AgentSkillEngineService  # noqa: E402

PREVIEW_ENV = {
    DEPLOY_ENV_NAME: "preview",
    ENABLE_ENV_NAME: PREVIEW_ENABLE_MARKER,
}


class _FakeResponse:
    def __init__(self, body: Any = None, status: int = 200, headers: Any = None) -> None:
        self.body = body
        self.status = status
        self.headers = headers or {}


class _FakeWorkerEntrypoint:
    def __init__(self, ctx: Any = None, env: Any = None) -> None:
        self.ctx = ctx
        self.env = env


def _workers_stub() -> types.ModuleType:
    module = types.ModuleType("workers")
    module.Request = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    module.Response = _FakeResponse  # type: ignore[attr-defined]
    module.WorkerEntrypoint = _FakeWorkerEntrypoint  # type: ignore[attr-defined]
    return module


@pytest.fixture(scope="module")
def worker_module():
    saved = {name: sys.modules.get(name) for name in ("workers", "worker")}
    sys.modules["workers"] = _workers_stub()
    sys.modules.pop("worker", None)
    try:
        yield importlib.import_module("worker")
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _runtime_factory(_app_id: str) -> Any:
    raise AssertionError("the preview pilot must never build a provider runtime")


# --- T4: the guards -------------------------------------------------------


def test_lane_requires_all_three_guards() -> None:
    assert build_preview_agent_lane({}) is None
    assert build_preview_agent_lane({ENABLE_ENV_NAME: PREVIEW_ENABLE_MARKER}) is None
    assert build_preview_agent_lane({DEPLOY_ENV_NAME: "preview"}) is None
    assert (
        build_preview_agent_lane(
            {DEPLOY_ENV_NAME: "preview", ENABLE_ENV_NAME: "ENABLE_SOMETHING_ELSE"}
        )
        is None
    )
    for production_marker in ("production", "prod", "prd", "PRODUCTION"):
        assert (
            build_preview_agent_lane(
                {
                    DEPLOY_ENV_NAME: production_marker,
                    ENABLE_ENV_NAME: PREVIEW_ENABLE_MARKER,
                }
            )
            is None
        )
    for malformed_marker in ("", "   ", "not a valid env!!", "1leading-digit", "bad_env_name"):
        assert (
            build_preview_agent_lane(
                {
                    DEPLOY_ENV_NAME: malformed_marker,
                    ENABLE_ENV_NAME: PREVIEW_ENABLE_MARKER,
                }
            )
            is None
        )


def test_lane_is_built_for_a_marked_non_production_isolate() -> None:
    lane = build_preview_agent_lane(PREVIEW_ENV)
    assert lane is not None
    assert isinstance(lane.service, AgentSkillEngineService)
    assert lane.binding.app_id == PREVIEW_APP_ID
    assert lane.binding.subject_id == PREVIEW_SUBJECT_ID
    assert lane.provider_runtime_calls == 0


def test_identity_is_fixed_and_never_read_from_the_environment() -> None:
    hostile = dict(PREVIEW_ENV)
    hostile.update(
        {
            "ENGINE_AGENT_PREVIEW_APP_ID": "caller-chosen-app",
            "ENGINE_AGENT_PREVIEW_AGENT_ID": "agent:caller@1",
            "ENGINE_AGENT_PREVIEW_SUBJECT_ID": "actor:caller",
            "ENGINE_AGENT_PREVIEW_TOOL_ID": "caller.tool",
        }
    )
    lane = build_preview_agent_lane(hostile)
    assert lane is not None
    assert lane.binding.app_id == PREVIEW_APP_ID
    assert lane.binding.subject_id == PREVIEW_SUBJECT_ID


# --- T5/T6/T7: synthetic execution, provider calls, user data --------------


def test_preview_lane_executes_the_synthetic_task() -> None:
    lane = build_preview_agent_lane(PREVIEW_ENV)
    assert lane is not None

    response = _run(lane.service.run_payload(preview_task_payload()))

    assert response.status_code == 200
    body = response.body
    assert body["ok"] is True
    agent_skill = body["agent_skill"]
    assert agent_skill["agent_id"] == PREVIEW_AGENT_ID
    assert agent_skill["execution_state"] == "completed"
    assert agent_skill["resolved_tool_ids"] == [PREVIEW_RUNTIME_TOOL_ID]
    assert lane.tool_calls == 1
    assert lane.provider_runtime_calls == 0


def test_provider_and_user_data_counters_stay_zero() -> None:
    lane = build_preview_agent_lane(PREVIEW_ENV)
    assert lane is not None
    for _ in range(3):
        response = _run(lane.service.run_payload(preview_task_payload()))
        assert response.status_code == 200
    assert lane.provider_runtime_calls == 0
    assert lane.tool_calls == 3
    # No durable, session, provider or secret layer may be reachable from the lane.
    source = Path(preview_authority.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden_top_level = {"os", "socket", "subprocess", "shutil", "glob", "urllib"}
    assert not {name for name in imported if name.split(".")[0] in forbidden_top_level}
    assert not {
        name
        for name in imported
        if name
        in {
            "app.idempotency_binding",
            "app.engine_composition",
            "app.cloudflare_transport",
            "app.agent_skill_continuation_service",
        }
    }


# --- T8: caller authority boundary ---------------------------------------


@pytest.mark.parametrize(
    "overrides,expected_code",
    (
        ({"subject_id": "caller.subject"}, "caller_agent_authority_not_allowed"),
        ({"provider_route": "caller"}, "caller_agent_authority_not_allowed"),
        ({"authorization": "caller"}, "caller_agent_authority_not_allowed"),
        ({"connector_grants": "caller"}, "caller_agent_authority_not_allowed"),
        (
            {"skill_id": "skill:engine:deferred@1"},
            "skill_not_allowed",
        ),
    ),
)
def test_caller_authority_stays_rejected_in_the_preview_lane(
    overrides: dict[str, Any], expected_code: str
) -> None:
    lane = build_preview_agent_lane(PREVIEW_ENV)
    assert lane is not None
    payload = preview_task_payload()
    payload.update(overrides)

    response = _run(lane.service.run_payload(payload))

    assert response.body["error"]["code"] == expected_code
    assert lane.provider_runtime_calls == 0


def test_unknown_application_is_refused() -> None:
    lane = build_preview_agent_lane(PREVIEW_ENV)
    assert lane is not None
    payload = preview_task_payload()
    payload["app_id"] = "another-app"

    response = _run(lane.service.run_payload(payload))

    assert response.status_code == 503
    assert response.body["error"]["code"] == "agent_skill_runtime_unavailable"


# --- Production composition is unchanged ---------------------------------


def test_worker_factory_stays_fail_closed_without_the_marker(worker_module: Any) -> None:
    service = worker_module._agent_skill_service_for_env(
        {},
        runtime_factory=_runtime_factory,
    )
    assert isinstance(service, AgentSkillEngineService)

    response = _run(service.run_payload(preview_task_payload()))

    assert response.status_code == 503
    assert response.body["error"]["code"] == "agent_skill_runtime_unavailable"


def test_worker_factory_refuses_a_production_marker(worker_module: Any) -> None:
    for production_marker in ("production", "prod"):
        service = worker_module._agent_skill_service_for_env(
            {
                DEPLOY_ENV_NAME: production_marker,
                ENABLE_ENV_NAME: PREVIEW_ENABLE_MARKER,
            },
            runtime_factory=_runtime_factory,
        )
        response = _run(service.run_payload(preview_task_payload()))
        assert response.status_code == 503
        assert response.body["error"]["code"] == "agent_skill_runtime_unavailable"


def test_worker_factory_composes_the_preview_lane_when_marked(worker_module: Any) -> None:
    service = worker_module._agent_skill_service_for_env(
        PREVIEW_ENV,
        runtime_factory=_runtime_factory,
    )

    response = _run(service.run_payload(preview_task_payload()))

    assert response.status_code == 200
    assert response.body["ok"] is True
    assert response.body["agent_skill"]["resolved_tool_ids"] == [PREVIEW_RUNTIME_TOOL_ID]
