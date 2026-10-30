from __future__ import annotations

import ast
from importlib.metadata import distribution
import json
from pathlib import Path
import tomllib

import httpx
import pytest

from app.b14_client import B14Client, ChatRuntimeError
from app.config import Settings
from app.model_policy import DEFAULT_B14_MODEL_ID
from app.worker_config import B14_SERVICE_BINDING_NAME

USER_MESSAGES = [{"role": "user", "content": "안녕하세요"}]


def _success_payload() -> dict:
    return {
        "choices": [
            {"message": {"role": "assistant", "content": "서비스 바인딩 응답입니다."}}
        ],
        "business14": {
            "request_id": "b14req_service_binding",
            "route_mode": "manual",
            "selected_model": DEFAULT_B14_MODEL_ID,
            "selected_provider": "Agnes AI",
        },
    }


class FakeServiceTransport:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def post_json(self, url: str, payload: dict) -> tuple[int, bytes]:
        self.calls.append((url, payload))
        return 200, json.dumps(_success_payload()).encode("utf-8")


@pytest.mark.asyncio
async def test_service_binding_transport_wins_and_preserves_explicit_agnes_payload():
    public_http_calls = 0

    async def public_handler(request):
        nonlocal public_http_calls
        public_http_calls += 1
        return httpx.Response(500)

    service = FakeServiceTransport()
    client = B14Client(
        Settings(runtime_mode="b14", b14_base_url="https://b14.internal"),
        transport=httpx.MockTransport(public_handler),
        service_transport=service,
        require_service_binding=True,
    )

    result = await client.complete(USER_MESSAGES)

    assert public_http_calls == 0
    assert len(service.calls) == 1
    url, payload = service.calls[0]
    assert url == "https://b14.internal/api/pilot/v1/chat/completions"
    assert payload["model"] == DEFAULT_B14_MODEL_ID
    assert payload["business14"]["required_capabilities"] == ["chat"]
    assert "allow_external_fallback" not in payload["business14"]
    assert "max_attempts" not in payload["business14"]
    assert "provider" not in payload
    assert "authorization" not in {key.lower() for key in payload}
    assert result["runtime"] == "b14"
    assert result["route"] == {
        "mode": "manual",
        "model": DEFAULT_B14_MODEL_ID,
        "provider": "Agnes AI",
    }


@pytest.mark.asyncio
async def test_live_production_contract_fails_closed_without_service_binding():
    public_http_calls = 0

    async def public_handler(request):
        nonlocal public_http_calls
        public_http_calls += 1
        return httpx.Response(200, json=_success_payload())

    client = B14Client(
        Settings(runtime_mode="b14", b14_base_url="https://public-workers-dev.example"),
        transport=httpx.MockTransport(public_handler),
        require_service_binding=True,
    )

    with pytest.raises(ChatRuntimeError) as info:
        await client.complete(USER_MESSAGES)

    assert info.value.status_code == 503
    assert info.value.code == "upstream_binding_unavailable"
    assert public_http_calls == 0


@pytest.mark.asyncio
async def test_mock_runtime_never_calls_service_binding():
    service = FakeServiceTransport()
    result = await B14Client(
        Settings(runtime_mode="mock"),
        service_transport=service,
        require_service_binding=True,
    ).complete(USER_MESSAGES)

    assert service.calls == []
    assert result["runtime"] == "mock"
    assert result["route"]["model"] == DEFAULT_B14_MODEL_ID


def test_service_binding_target_is_fixed_in_repository_config():
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / "wrangler.toml").read_text(encoding="utf-8"))

    assert B14_SERVICE_BINDING_NAME == "B14_SERVICE"
    assert config["services"] == [
        {
            "binding": "B14_SERVICE",
            "service": "ai-revenue-korean-ai-platform",
        },
        {
            "binding": "IDENTITY_AUTHORITY_SERVICE",
            "service": "padiem-control-plane-identity",
        },
        {
            "binding": "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE",
            "service": "padiem-local-agent-broker-state",
        },
        {
            "binding": "VOICE_STT_SERVICE",
            "service": "padiem-voice-stt",
        },
        {
            "binding": "B66_PDF_RENDERER_SERVICE",
            "service": "padiem-b66-pdf-renderer",
        },
        {
            "binding": "GOOGLE_OAUTH_STATE_SERVICE",
            "service": "padiem-google-oauth-state",
        },
        {
            "binding": "P01_ENGINE_SERVICE",
            "service": "padiem-ai-engine",
        },
    ]
    assert "DOCUMENT_PARSER_SERVICE" not in {item["binding"] for item in config["services"]}
    assert config["vars"]["PADIEM_CHAT_RUNTIME_MODE"] == "mock"
    assert config["vars"]["PADIEM_CHAT_LIVE_ENABLED"] == "false"


def test_installed_workers_request_wrapper_contract_matches_service_bridge():
    dist = distribution("workers-runtime-sdk")
    request_files = [
        item
        for item in (dist.files or ())
        if str(item).replace("\\", "/").endswith("workers/request.py")
    ]
    assert len(request_files) == 1

    request_source = Path(dist.locate_file(request_files[0])).read_text(encoding="utf-8")
    tree = ast.parse(request_source)
    request_class = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Request"
    )
    methods = {
        node.name: node
        for node in request_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "__init__" in methods
    assert "new" not in methods
    assert "js_object" in methods

    init = methods["__init__"]
    assert [arg.arg for arg in init.args.args[:2]] == ["self", "input"]
    assert init.args.kwarg is not None
    assert init.args.kwarg.arg == "other_options"


def test_worker_uses_python_request_constructor_and_js_fetch_argument():
    root = Path(__file__).resolve().parents[1]
    worker = (root / "worker.py").read_text(encoding="utf-8")

    assert "Request.new(" not in worker
    assert "request = Request(" in worker
    assert 'method="POST"' in worker
    assert 'headers={"Content-Type": "application/json"}' in worker
    assert "raw_body = json.dumps(payload, ensure_ascii=False)" in worker
    assert "response = await self.binding.fetch(request.js_object)" in worker
    assert "response = await self.binding.fetch(request)" not in worker
    assert "_to_js_object" not in worker


def test_worker_wires_service_binding_and_browser_cannot_choose_target():
    root = Path(__file__).resolve().parents[1]
    worker = (root / "worker.py").read_text(encoding="utf-8")
    main = (root / "app/main.py").read_text(encoding="utf-8")

    assert "binding_value(self.env, B14_SERVICE_BINDING_NAME)" in worker
    # #5784 PR-2: the Worker now hands the two binding transports to one composer
    # instead of building them inline, so what is pinned here is that the exact
    # binding transport types still reach that composer.
    assert "service_transport, stream_transport = _compose_b14_transports(" in worker
    assert "service_binding_factory=CloudflareB14ServiceTransport," in worker
    assert "stream_binding_factory=CloudflareB14StreamingServiceTransport," in worker
    # #5899 guard pin, ported: the fail-closed flag is composed only from
    # server-side settings, so neither the browser nor a request value can widen it.
    assert 'require_service_binding=settings.runtime_mode == "b14"' in worker
    assert "require_service_binding=request" not in worker
    assert 'B14_SERVICE' not in main
    assert '"B14_SERVICE"' not in main


def test_existing_provisioned_worker_is_never_auto_overwritten_by_mock_workflow():
    repo = Path(__file__).resolve().parents[3]
    workflow = (
        repo / ".github/workflows/b62-cloudflare-worker-deploy.yml"
    ).read_text(encoding="utf-8")

    assert "needs.preflight.outputs.worker_state == 'absent'" in workflow
    assert "Refusing repository mock deploy over an existing provisioned Worker." in workflow
    assert "Deploy initial mock-only Python Worker" in workflow


