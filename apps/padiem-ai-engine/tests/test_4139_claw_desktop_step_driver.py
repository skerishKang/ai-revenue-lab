"""Focused structured desktop step contract, without provider or PC side effects."""
import asyncio
from types import SimpleNamespace

import pytest

from app.claw_desktop_step_driver import (
    DesktopStepContractError, StructuredDesktopStepDriver,
)


def test_model_selects_next_tool_from_real_jpeg_observation():
    calls = []
    async def image_loader(**args):
        assert args["receipt"] == "owned-capture"
        return b"\xff\xd8\xff\x00"
    async def model(**kwargs):
        calls.append(kwargs)
        assert kwargs["observations"][0]["image_jpeg"].startswith(b"\xff\xd8\xff")
        return {"action": "tool", "tool_id": "claw.desktop.click",
                "arguments": {"x": 42, "y": 80}}
    result = SimpleNamespace(
        tool_id="claw.desktop.capture",
        output_copy=lambda: {"capture_receipt": "owned-capture"},
        event=SimpleNamespace(to_public_dict=lambda: {"status": "succeeded"}),
    )
    driver = StructuredDesktopStepDriver(
        select_step=model, read_capture=image_loader,
        allowed_tool_ids=frozenset({"claw.desktop.click"}),
    )
    context = SimpleNamespace(tool_results=(result,))
    choice = asyncio.run(driver.next_step(context, compiled_profile=None))
    assert choice.invocation.tool_id == "claw.desktop.click"
    assert choice.invocation.arguments_copy() == {"x": 42, "y": 80}
    assert len(calls) == 1


def test_unowned_capture_does_not_invoke_model_or_tool():
    calls = []
    async def image_loader(**kwargs):
        return None
    async def model(**kwargs):
        calls.append(1)
        return {"action": "complete", "answer": "done"}
    result = SimpleNamespace(
        tool_id="claw.desktop.capture",
        output_copy=lambda: {"capture_receipt": "foreign"},
        event=SimpleNamespace(to_public_dict=lambda: {}),
    )
    driver = StructuredDesktopStepDriver(
        select_step=model, read_capture=image_loader,
        allowed_tool_ids=frozenset({"claw.desktop.click"}),
    )
    with pytest.raises(DesktopStepContractError, match="unavailable"):
        asyncio.run(driver.next_step(SimpleNamespace(tool_results=(result,)), None))
    assert calls == []



def test_admitted_owner_tool_runtime_calls_signed_chat():
    import hashlib
    import hmac
    import json
    from types import SimpleNamespace
    from app.claw_desktop_step_driver import (
        _ENGINE_DESKTOP_OWNER, build_claw_desktop_tool_binding,
        DESKTOP_AGENT_ID, DESKTOP_CANONICAL_CAPTURE, DESKTOP_CAPTURE_ID,
    )
    from padiem_ai_core.tool_runtime import ToolInvocation

    secret = "x" * 32
    seen = []

    class Request:
        def __init__(self, url, *, method, headers, body):
            self.url, self.method, self.headers, self.body = url, method, headers, body
            self.js_object = self

    class Service:
        async def fetch(self, request):
            assert request.url == "https://padiem-chat.internal/internal/claw/engine-desktop"
            assert request.method == "POST"
            proof = hmac.new(secret.encode(), (
                request.headers["X-Claw-Engine-Time"] + "."
            ).encode() + request.body.encode(), hashlib.sha256).hexdigest()
            assert hmac.compare_digest(proof, request.headers["X-Claw-Engine-Proof"])
            body = json.loads(request.body)
            if body.get("mode") == "status":
                assert body == {
                    "subject_id": "sub_verified",
                    "run_id": "run_verified",
                    "dispatch_id": "dispatch_once",
                    "mode": "status",
                }
                return SimpleNamespace(
                    status=200,
                    text=lambda: asyncio.sleep(0, result=json.dumps({
                        "ok": True, "dispatch": {
                            "dispatch_id": "dispatch_once",
                            "run_id": "run_verified", "kind": "desktop",
                            "state": "done", "result_sha256": "a" * 64,
                        },
                    })),
                )
            assert set(body) == {"subject_id", "run_id", "device_id", "desktop_op"}
            assert body == {
                "subject_id": "sub_verified", "run_id": "run_verified",
                "device_id": "device_verified", "desktop_op": "desktop:capture",
            }
            seen.append(body)
            return SimpleNamespace(
                status=200,
                text=lambda: asyncio.sleep(0, result=json.dumps({
                    "ok": True, "dispatch": {
                        "dispatch_id": "dispatch_once",
                        "run_id": "run_verified", "kind": "desktop", "state": "pending",
                    },
                })),
            )

    binding = build_claw_desktop_tool_binding(
        service=Service(), request_factory=Request, secret=secret,
    )
    authority = binding.resolve_authority(DESKTOP_AGENT_ID)
    invocation = ToolInvocation(
        tool_id=DESKTOP_CAPTURE_ID, arguments={"device_id": "device_verified"}
    )
    token = _ENGINE_DESKTOP_OWNER.set(("sub_verified", "run_verified"))
    try:
        result = asyncio.run(binding.tool_runtime.execute(
            invocation, authority.compiled.runtime_profile, authority.authorization,
        ))
    finally:
        _ENGINE_DESKTOP_OWNER.reset(token)
    assert result.output_copy()["dispatch_id"] == "dispatch_once"
    assert result.output_copy()["execution_confirmed"] is True
    assert result.output_copy()["capture_receipt"] == "dispatch_once"
    assert len(seen) == 1


def test_unadmitted_owner_cannot_trigger_chat_transport():
    from app.claw_desktop_step_driver import (
        _ENGINE_DESKTOP_OWNER, build_claw_desktop_tool_binding,
        DESKTOP_AGENT_ID, DESKTOP_CAPTURE_ID,
    )
    from padiem_ai_core.tool_runtime import ToolInvocation
    from padiem_ai_core.tool_runtime import ToolRuntimeError

    class NoService:
        async def fetch(self, request):
            raise AssertionError("unauthorized transport called")

    binding = build_claw_desktop_tool_binding(
        service=NoService(), request_factory=lambda *a, **k: None,
        secret="x" * 32,
    )
    authority = binding.resolve_authority(DESKTOP_AGENT_ID)
    token = _ENGINE_DESKTOP_OWNER.set(None)
    try:
        with pytest.raises(ToolRuntimeError):
            asyncio.run(binding.tool_runtime.execute(
                ToolInvocation(
                    tool_id=DESKTOP_CAPTURE_ID,
                    arguments={"device_id": "device_verified"},
                ),
                authority.compiled.runtime_profile, authority.authorization,
            ))
    finally:
        _ENGINE_DESKTOP_OWNER.reset(token)



def test_production_desktop_driver_feeds_jpeg_to_b14_and_selects_pc_input():
    import hashlib
    import json
    from types import SimpleNamespace
    from app.claw_desktop_step_driver import (
        _ENGINE_DESKTOP_OWNER, build_live_desktop_driver,
    )

    jpeg = b"\xff\xd8\xff\x00"
    digest = hashlib.sha256(jpeg).hexdigest()
    requests = []

    class Buffer:
        def to_py(self):
            return jpeg

    class Request:
        def __init__(self, url, *, method, headers, body):
            self.js_object = self
            self.body = body
            self.headers = headers

    class Chat:
        async def fetch(self, request):
            assert json.loads(request.body) == {
                "mode": "image", "dispatch_id": "dispatch_current",
                "run_id": "run_current", "subject_id": "subject_current",
            }
            return SimpleNamespace(
                status=200,
                arrayBuffer=lambda: asyncio.sleep(0, result=Buffer()),
            )

    class Model:
        async def execute(self, request):
            payload = request.to_payload()
            requests.append(payload)
            assert payload["model"] == "existing/registered"
            assert "max_tokens" not in payload
            images = [p for p in payload["messages"][0]["content"]
                      if p["type"] == "image_url"]
            assert len(images) == 1
            assert images[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
            return SimpleNamespace(answer=json.dumps({
                "action": "tool", "tool_id": "claw.desktop.click",
                "arguments": {"x": 32, "y": 56},
            }))

    driver = build_live_desktop_driver(
        b14_client=Model(), chat_service=Chat(),
        request_factory=Request, secret="s" * 32,
        model_id="existing/registered",
    )
    result = SimpleNamespace(
        tool_id="claw.desktop.capture",
        output_copy=lambda: {
            "capture_receipt": "dispatch_current",
            "dispatch_id": "dispatch_current",
            "result_sha256": digest,
            "run_id": "run_current",
            "execution_confirmed": True,
        },
        event=SimpleNamespace(to_public_dict=lambda: {"status": "succeeded"}),
    )
    token = _ENGINE_DESKTOP_OWNER.set(("subject_current", "run_current"))
    try:
        decision = asyncio.run(driver.next_step(
            SimpleNamespace(
                input_text="Open Notepad", tool_results=(result,),
            ), compiled_profile=None,
        ))
    finally:
        _ENGINE_DESKTOP_OWNER.reset(token)
    assert decision.invocation.tool_id == "claw.desktop.click"
    assert decision.invocation.arguments_copy() == {"x": 32, "y": 56}
    assert len(requests) == 1



def test_engine_service_composes_real_desktop_driver_with_model_choice_and_reobservation():
    """Regression: real Engine->Core ToolRuntime path, not driver constructed by test."""
    import hashlib
    import json
    from app.claw_desktop_step_driver import (
        build_live_desktop_driver, build_claw_desktop_tool_binding,
        _ENGINE_DESKTOP_OWNER, CLAW_APP_ID,
    )
    from app.orchestration_service import OrchestrationEngineService
    from types import SimpleNamespace

    jpeg = b"\xff\xd8\xff\x00"
    digest = hashlib.sha256(jpeg).hexdigest()
    dispatched = {}
    selected_steps = []

    class Request:
        def __init__(self, url, *, method, headers, body):
            self.url, self.body, self.headers = url, body, headers
            self.js_object = self

    class Response:
        def __init__(self, data):
            self.status = 200
            self._data = data

        async def text(self):
            return json.dumps(self._data)

        async def arrayBuffer(self):
            return SimpleNamespace(to_py=lambda: jpeg)

    class Chat:
        async def fetch(self, request):
            payload = json.loads(request.body)
            mode = payload.get("mode")
            if mode == "image":
                assert dispatched[payload["dispatch_id"]] == "desktop:capture"
                return Response({})
            if mode == "status":
                op = dispatched[payload["dispatch_id"]]
                return Response({
                    "ok": True,
                    "dispatch": {
                        "dispatch_id": payload["dispatch_id"],
                        "run_id": payload["run_id"],
                        "kind": "desktop",
                        "state": "done",
                        "result_sha256": digest if op == "desktop:capture" else "b" * 64,
                    },
                })
            dispatch_id = "dispatch_" + str(len(dispatched) + 1)
            dispatched[dispatch_id] = payload["desktop_op"].split("\n")[0]
            return Response({
                "ok": True,
                "dispatch": {
                    "dispatch_id": dispatch_id, "run_id": payload["run_id"],
                    "kind": "desktop", "state": "pending",
                },
            })

    class Model:
        async def execute(self, request):
            payload = request.to_payload()
            assert payload["model"] == "existing/model"
            assert "max_tokens" not in payload
            parts = payload["messages"][0]["content"]
            assert sum(p["type"] == "image_url" for p in parts) == 1
            selected_steps.append(parts)
            if len(selected_steps) == 1:
                return SimpleNamespace(answer=json.dumps({
                    "action": "tool", "tool_id": "claw.desktop.click",
                    "arguments": {"x": 24, "y": 32},
                }))
            return SimpleNamespace(answer=json.dumps({
                "action": "complete", "answer": "Screen observed",
            }))

    class NoGenericRuntime:
        async def run(self, request):
            raise AssertionError("generic provider path must not execute a tool plan")

    chat, model = Chat(), Model()
    binding = build_claw_desktop_tool_binding(
        service=chat, request_factory=Request, secret="s" * 32,
    )
    service = OrchestrationEngineService(
        runtime_factory=lambda _: NoGenericRuntime(),
        b14_service_bound=True,
        tool_binding_resolver=lambda app: binding if app == CLAW_APP_ID else None,
        desktop_step_driver_factory=lambda model_id, model_policy, task_type, optimize_for: build_live_desktop_driver(
            b14_client=model, chat_service=chat, request_factory=Request,
            secret="s" * 32, model_id=model_id, model_policy=model_policy,
            task_type=task_type, optimize_for=optimize_for,
        ),
    )
    run_id = "run_" + "a" * 24
    subject_id = "sub_" + "b" * 32
    payload = {
        "app_id": CLAW_APP_ID,
        "agent": {
            "id": CLAW_APP_ID, "title": "Padiem Claw",
            "description": "B54 task",
            "system_instruction": None, "task_type": "coding",
            "optimize_for": "balanced", "max_tokens": None,
            "required_capabilities": [],
            "model_policy": {"model": "existing/model", "max_retries": 0,
                             "product_tier": "free"},
        },
        "messages": [{"role": "user", "content": "Observe my PC and click"}],
        "trace_id": "tr_" + "c" * 24,
        "execution_context": {"trace_id": "tr_" + "c" * 24},
        "session_id": run_id,
        "subject_id": subject_id,
        "agent_plan": {
            "agent_id": "agent:padiem:claw-desktop@1",
            "steps": [{"step_id": "capture",
                       "objective": "Observe verified PC",
                       "tool_id": "claw.desktop.capture",
                       "depends_on": []}],
        },
        "tool_arguments": {"capture": {"use_pinned_device": True}},
    }
    token = _ENGINE_DESKTOP_OWNER.set((subject_id, run_id))
    try:
        result = asyncio.run(service.orchestrate_payload(payload))
    finally:
        _ENGINE_DESKTOP_OWNER.reset(token)
    assert result.status_code == 200, result.body
    assert list(dispatched.values()) == [
        "desktop:capture", "desktop:click", "desktop:capture",
    ]
    assert len(selected_steps) == 2



def test_claw_secret_store_is_shared_and_client_composition_is_live():
    """Detect a source-only binding or a split Engine/Chat secret."""
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    engine_config = tomllib.loads(
        (root / "apps/padiem-ai-engine/wrangler.toml").read_text("utf8")
    )
    chat_config = tomllib.loads(
        (root / "apps/padiem-chat/wrangler.toml").read_text("utf8")
    )
    def bound(config):
        rows = [row for row in config["secrets_store_secrets"]
                if row["binding"] == "CLAW_ENGINE_DESKTOP_SECRET"]
        assert len(rows) == 1
        return (rows[0]["store_id"], rows[0]["secret_name"])
    assert bound(engine_config) == bound(chat_config)
    assert bound(engine_config)[1] == "CLAW_ENGINE_DESKTOP_SECRET"
    assert any(
        row.get("binding") == "PADIEM_CHAT_SERVICE"
        and row.get("service") == "padiem-chat"
        for row in engine_config["services"]
    )
    worker = (root / "apps/padiem-ai-engine/worker_identity.py").read_text("utf8")
    orchestrator = (root / "apps/padiem-ai-engine/app/orchestration_service.py").read_text("utf8")
    assert "build_live_desktop_driver" in worker
    assert "desktop_step_driver_factory=" in worker
    assert "agent_step_driver=self._desktop_step_driver_factory(" in orchestrator


def test_registered_type_and_keys_are_signed_and_never_replayed():
    from app.claw_desktop_step_driver import (
        _ENGINE_DESKTOP_OWNER, build_claw_desktop_tool_binding, DESKTOP_AGENT_ID,
    )
    from padiem_ai_core.tool_runtime import ToolInvocation
    from types import SimpleNamespace
    import json
    seen = []
    class Request:
        def __init__(self, url, *, method, headers, body):
            self.js_object = self
            self.body = body
    class Chat:
        async def fetch(self, request):
            row = json.loads(request.body)
            if row.get("mode") == "status":
                return SimpleNamespace(
                    status=200,
                    text=lambda: asyncio.sleep(0, result=json.dumps({
                        "ok": True, "dispatch": {
                            "dispatch_id": row["dispatch_id"],
                            "run_id": row["run_id"],
                            "kind": "desktop", "state": "done",
                            "result_sha256": "a" * 64,
                        },
                    })),
                )
            seen.append(row["desktop_op"])
            return SimpleNamespace(
                status=200,
                text=lambda: asyncio.sleep(0, result=json.dumps({
                    "ok": True, "dispatch": {
                        "dispatch_id": "dsp_" + str(len(seen)),
                        "run_id": row["run_id"],
                        "kind": "desktop", "state": "pending",
                    },
                })),
            )
    binding = build_claw_desktop_tool_binding(
        service=Chat(), request_factory=Request, secret="s" * 32,
    )
    authority = binding.resolve_authority(DESKTOP_AGENT_ID)
    token = _ENGINE_DESKTOP_OWNER.set(("verified_subject", "verified_run"))
    try:
        for name, args in (
            ("type", {"text": "PADIEM-GUI-E2E-261017-OK"}),
            ("keys", {"combo": "ctrl+s"}),
        ):
            result = asyncio.run(binding.tool_runtime.execute(
                ToolInvocation(tool_id="claw.desktop." + name, arguments=args),
                authority.compiled.runtime_profile,
                authority.authorization,
            ))
            assert result.output_copy()["execution_confirmed"] is True
    finally:
        _ENGINE_DESKTOP_OWNER.reset(token)
    assert seen == ["desktop:type\nPADIEM-GUI-E2E-261017-OK",
                    "desktop:keys\nctrl+s"]


def test_secret_store_binding_is_resolved_for_the_desktop_driver():
    """A Secrets Store binding is an object with async .get(), not a string.

    Accepting only ``str`` silently disabled both the desktop tool binding and
    the live step driver in Production, where the shared secret is stored in
    the account Secrets Store.
    """
    import importlib
    import sys
    import types
    from contextlib import contextmanager

    @contextmanager
    def composed_identity():
        saved = {
            name: sys.modules.get(name)
            for name in ("workers", "worker", "worker_identity")
        }
        stub = types.ModuleType("workers")
        stub.Request = lambda *args, **kwargs: None
        stub.Response = lambda *args, **kwargs: None
        stub.WorkerEntrypoint = object
        sys.modules["workers"] = stub
        for name in ("worker", "worker_identity"):
            sys.modules.pop(name, None)
        try:
            yield importlib.import_module("worker_identity")
        finally:
            for name, module in saved.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

    class SecretBinding:
        def __init__(self, value):
            self._value = value

        async def get(self):
            return self._value

    class BrokenBinding:
        async def get(self):
            raise RuntimeError("secret unavailable")

    class StoreEnv:
        B14_SERVICE = object()
        PADIEM_CHAT_SERVICE = object()
        CLAW_ENGINE_DESKTOP_SECRET = SecretBinding("s" * 64)

    class PlainEnv:
        B14_SERVICE = object()
        PADIEM_CHAT_SERVICE = object()
        CLAW_ENGINE_DESKTOP_SECRET = "s" * 64

    class BrokenEnv:
        B14_SERVICE = object()
        PADIEM_CHAT_SERVICE = object()
        CLAW_ENGINE_DESKTOP_SECRET = BrokenBinding()

    with composed_identity() as identity:
        def driver_factory(env):
            services = asyncio.run(identity._engine_services_for_env(env))
            return services.orchestration._desktop_step_driver_factory

        assert callable(driver_factory(StoreEnv()))
        assert callable(driver_factory(PlainEnv()))
        assert driver_factory(BrokenEnv()) is None
