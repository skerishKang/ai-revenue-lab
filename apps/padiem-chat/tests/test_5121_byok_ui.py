"""#5121 PADIEM Custom (BYOK) customer UI: contract and direct-provider transport.

The browser transport is executed in a Node vm with an injected fetch stub, so
this test proves the custom lane skips B14 orchestration without contacting a
provider, Engine or B14 endpoint. No paid provider call is made.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

# R5 0단계(R-01): 함수 선언은 app.js든 분리 모듈이든 같은 도우미로 찾는다.
from _r5_function_source import definition_source
from _r5_product_capabilities_harness import run_capabilities_scenario

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
CAPABILITIES = (STATIC / "product-capabilities.js").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
STREAM = (STATIC / "chat-streaming-module.js").read_text(encoding="utf-8")
TRANSPORT = (STATIC / "chat-transport.js").read_text(encoding="utf-8")
CSS = (STATIC / "mode-presentation.css").read_text(encoding="utf-8")
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")

CUSTOM_PROVIDER = "opencode-go"
CUSTOM_MODEL = "opencode-go/beam-free"


def test_model_card_adds_a_custom_lane_separate_from_padiem_tiers() -> None:
    """모델 카드의 Custom 칩은 실제 렌더로 관찰한다(#7186)."""
    member = run_capabilities_scenario("mode_tiers")
    lane = member["customLane"]
    assert lane["classes"] == "mode-option mode-option--custom"
    assert lane["modeValue"] == "custom"
    assert lane["title"] == "Padiem Custom"
    # Custom 칩은 등급 칸(free·plus·pro·max)과 분리된 별도 칩으로 붙는다.
    assert member["optionValues"] == ["free", "plus", "pro", "max"]
    # 칩 위쪽 안내는 제목과 설명 두 요소뿐이다.
    assert member["customHeadingChildren"] == ["STRONG", "SMALL"]

    section = CSS.split(".mode-custom-section {", 1)[1].split("}", 1)[0]
    assert "border-top: 1px solid var(--line)" in section
    panel = CSS.split(".mode-presentation-panel {", 1)[1].split("}", 1)[0]
    assert "max-height: min(72vh, 640px)" in panel
    assert "overflow-y: auto" in panel
    assert "overscroll-behavior: contain" in panel


def test_custom_tier_row_shows_no_supplier_or_model_name() -> None:
    """#6828: a PADIEM grade row never names a supplier or an internal model id."""
    from app.byok_credentials import CUSTOM_PROVIDERS, DEFAULT_CUSTOM_PROVIDER

    spec = CUSTOM_PROVIDERS[DEFAULT_CUSTOM_PROVIDER]
    assert spec.display_name == "Padiem Custom"
    assert "(" not in spec.display_name
    assert spec.display_name == spec.display_name.replace("(", "").strip()

    # The rendered row text is built only from PADIEM copy: the supplier
    # display name and the model id are not interpolated into it. The rendered
    # chip shows the PADIEM lane name and, before a provider is chosen, no
    # model hint at all — observed from the real render.
    member = run_capabilities_scenario("mode_tiers")
    assert member["customLane"]["title"] == "Padiem Custom"
    assert member["customLane"]["modelText"] == ""
    # The whole grade-facing copy block is free of supplier and model ids.
    # 구조 계약(부재 금지): 문구 표 전체에 공급사 흔적이 없어야 한다는 것은
    # 소스에서만 증명할 수 있어 문자열로 남긴다.
    copy_block = _custom_copy_block().lower()
    assert "opencode" not in copy_block
    assert "beam" not in copy_block


def _custom_copy_block() -> str:
    return CAPABILITIES.split("const CUSTOM_COPY", 1)[1].split("let customSelection", 1)[0]


def _custom_section() -> str:
    return CAPABILITIES.split("function createCustomSection()", 1)[1].split(
        "function createModeOption", 1
    )[0]


def test_picker_title_and_byok_copy_match_the_owner_contract() -> None:
    # 패널 제목은 실제 렌더로 관찰한다(국어 화면 기준).
    member = run_capabilities_scenario("mode_tiers")
    assert member["panelTitle"] == "모델 선택"
    # 구조 계약(문구 표): BYOK 문구 표 자체는 데이터 계약이라 문자열로 남긴다.
    custom_copy = _custom_copy_block()
    assert 'heading: "내 API 키"' in custom_copy
    assert 'heading: "My API key"' in custom_copy
    assert "(Padiem Custom)" not in custom_copy.split('heading: "내 API 키"', 1)[1].split(
        "description", 1
    )[0]
    # One explanation per language, with no second copy of it on selection.
    assert custom_copy.count("description:") == 2
    assert "truth:" not in custom_copy
    assert "custom.truth" not in CAPABILITIES


def test_byok_heading_has_no_decorative_icon() -> None:
    # 제목 칸의 실제 구성은 실행으로 관찰한다: 제목+설명 두 요소뿐이다.
    member = run_capabilities_scenario("mode_tiers")
    assert member["customHeadingChildren"] == ["STRONG", "SMALL"]
    # 구조 계약(부재 금지): 장식 아이콘·이모지는 소스에 다시 생기면 안 된다.
    heading = _custom_section().split(
        'heading.className = "mode-custom-heading";', 1
    )[1].split("customOption = document.createElement", 1)[0]
    for forbidden in ("status-spark", "<svg", "<img", "createElementNS", "🔑"):
        assert forbidden not in heading, forbidden


def test_connection_test_is_real_and_only_shown_for_server_supported_providers() -> None:
    # No placeholder button and no client-side success claim: the control is
    # hidden unless the server advertises a model-list-backed test and a stored
    # credential exists, and the result comes from the server response —
    # observed from the real module with a fake server.
    flow = run_capabilities_scenario("custom_flow")
    assert flow["testHiddenWithCredential"] is False  # 능력 + 자격증명이 있으면 보인다
    assert flow["testCall"] == ["/api/chat/custom/credential/test?provider=prov-a"]
    assert flow["testOkMessage"] == "공급사 연결을 확인했습니다."
    assert flow["testOkState"] == "ok"
    assert flow["testFailMessage"] == "서버가 거절했습니다"
    assert flow["testFailState"] == "error"
    # 능력 플래그가 없는 공급자(prov-b)에게는 시험 단추가 아예 숨는다.
    assert flow["provB"]["testHidden"] is True
    # #5824: registration performs the check itself — one click runs
    # detect → register, observed as the actual request sequence.
    register = run_capabilities_scenario("register_flow")
    assert [c["url"] for c in register["registerCalls"]] == ["/api/byok/detect", "/api/byok/register"]
    # 구조 계약(부재 금지): 자동 확인 단추·PATCH·업데이트 내역 문구는
    # 소스에 다시 생기면 안 된다. 실행으로는 "없어야 할 것"을 증명할 수 없다.
    assert '"자동 확인"' not in CAPABILITIES
    assert 'method: "PATCH"' not in CAPABILITIES
    for forbidden in ("업데이트 내역", "Update history"):
        assert forbidden not in CAPABILITIES, forbidden


def test_picker_renders_only_server_reported_providers_models_and_capabilities() -> None:
    # The picker's provider/model options come only from the server payload —
    # observed as the actual rendered option values.
    flow = run_capabilities_scenario("custom_flow")
    assert flow["providerOptionValues"] == ["", "prov-a", "prov-b"]
    assert flow["modelOptionValues"] == ["", "m1", "m2"]
    # 능력 플래그가 없는 공급자(prov-b)는 모델 선택 대신 직접 입력 칸을 쓰고
    # 목록·주소·시험 통제가 모두 숨는다(서버가 알려 준 능력 그대로).
    assert flow["provB"] == {
        "modelSelectHidden": True, "modelInputHidden": False, "listButtonHidden": True,
        "endpointHidden": True, "testHidden": True, "deleteHidden": False,
    }
    # The browser still contains no provider inventory of its own.
    # 구조 계약(부재 금지): 클라이언트가 공급자 목록을 갖지 않는다는 것은
    # 소스에서만 증명할 수 있어 문자열로 남긴다.
    for provider in ("openai", "anthropic", "openrouter", "gemini", "opencode-go"):
        assert provider not in CAPABILITIES.lower(), provider


def test_manual_model_requires_an_explicit_model_before_custom_selection() -> None:
    # 모델 없는 Custom 선택은 실제 실행으로 거절된다: 안내·포커스·고급 칸
    # 펼침·선택 없음·요청 없음까지 관찰한다.
    gate = run_capabilities_scenario("manual_gate")
    assert gate["modelGateMessage"] == "모델 ID를 먼저 선택하거나 입력해 주세요."
    assert gate["modelGateMessageState"] == "error"
    assert gate["modelInputFocused"] >= 1
    assert gate["advancedOpenAfterGate"] is True
    assert gate["selectionStillNull"] is None
    assert gate["streamNotCalled"] is True
    # 기본 추론은 필드를 보내지 않고, 고른 추론은 그 값으로 실린다.
    assert gate["selectionWithModel"] == {
        "provider": "prov-m", "model": "my-model", "reasoning_effort": None}
    assert gate["selectionWithReasoning"] == {
        "provider": "prov-m", "model": "my-model", "reasoning_effort": "high"}
    # 모델 목록·연결 시험은 서버 주소 그대로 간다(실제 요청 관찰).
    flow = run_capabilities_scenario("custom_flow")
    assert flow["modelsCall"] == ["/api/chat/custom/models?provider=prov-a"]
    assert flow["testCall"] == ["/api/chat/custom/credential/test?provider=prov-a"]


def test_tier_rows_keep_existing_order_status_and_badges() -> None:
    # 등급 칸 순서와 배지는 실제 렌더로 관찰한다.
    member = run_capabilities_scenario("mode_tiers")
    assert member["optionValues"] == ["free", "plus", "pro", "max"]
    assert member["optionIcons"] == ["✓", "✓", "↑", "↑"]
    # 구조 계약(부재 금지): 상태 반짝이·이미지·브랜드 아이콘은 다시 생기면 안 된다.
    option = CAPABILITIES.split("function createModeOption", 1)[1].split(
        "function syncModeCopy", 1
    )[0]
    for forbidden in ("status-spark", "<img", "<svg", "brand-icon"):
        assert forbidden not in option, forbidden


def test_mobile_picker_scroll_stays_inside_the_panel() -> None:
    panel = CSS.split(".mode-presentation-panel {", 1)[1].split("}", 1)[0]
    assert "overflow-y: auto" in panel
    assert "overscroll-behavior: contain" in panel
    assert "-webkit-overflow-scrolling: touch" in panel
    assert "scroll-padding-block: 12px" in panel
    mobile = CSS.split("@media (max-width: 720px)", 1)[1]
    mobile_panel = mobile.split(".mode-presentation-panel {", 1)[1].split("}", 1)[0]
    assert "max-height: min(62dvh, 520px)" in mobile_panel


def test_customer_key_is_write_only_and_only_last_four_are_rendered() -> None:
    # 저장(PUT)·삭제(DELETE)는 실제 요청으로 관찰한다: 주소는 서버가 알려 준
    # 공급자와 함께 가고, 주소 칸은 적었을 때만 실린다.
    register = run_capabilities_scenario("register_flow")
    assert register["saveKeyPuts"] == [{
        "url": "/api/chat/custom/credential",
        "body": {"provider": "prov-x", "api_key": "k" * 20},
    }]
    assert register["saveKeyPutsWithEndpoint"] == [{
        "url": "/api/chat/custom/credential",
        "body": {"provider": "prov-x", "api_key": "k" * 20,
                 "endpoint": "https://relay.example/v1"},
    }]
    flow = run_capabilities_scenario("custom_flow")
    assert flow["deleteCall"] == [{
        "url": "/api/chat/custom/credential?provider=prov-a", "body": None}]
    # 성공한 저장 뒤에는 키 입력이 지워진다(클라이언트 보관 없음).
    assert register["keyClearedAfterRegister"] is True
    # 구조 계약(부재 금지): 키·쿠키·콘솔 저장과 마지막 4자 이상 렌더는
    # 소스에서만 증명할 수 있어 문자열로 남긴다.
    assert 'customInput' not in CAPABILITIES
    for forbidden in ("localStorage", "sessionStorage", "document.cookie", "console."):
        assert forbidden not in CAPABILITIES, forbidden
    assert 'copy.credential + String(credential.key_last4' not in CAPABILITIES
    # #5824: the registered state is one line; no key material is rendered and
    # the first open (no credential yet) shows no status line at all — observed.
    assert flow["statusText"] == "등록됨 · 사용 가능"
    assert flow["statusLeaksKeyFragment"] is False


def test_custom_endpoint_and_provider_model_controls_follow_server_capabilities() -> None:
    # 만들어진 통제의 실제 id·class와 숨김 규칙은 실행으로 관찰한다.
    flow = run_capabilities_scenario("custom_flow")
    assert flow["ids"] == {
        "providerSelect": "modeCustomProvider",
        "modelSelect": "modeCustomModelSelect",
        "modelInput": "modeCustomModelInput",
        "endpointInput": "modeCustomEndpoint",
        "testButtonClass": "mode-custom-action mode-custom-test",
        "keyInputId": "modeAutoByokKey",
        "registerButtonId": "modeAutoByokRegister",
    }
    # #5824: the address field never suggests a provider address by default.
    assert flow["endpointPlaceholder"] == "https://<your-endpoint>/v1"
    # 구조 계약(부재 금지): 서버가 준 기본 주소를 화면에 보여 주는 일은
    # 소스에서만 증명할 수 있어 문자열로 남긴다.
    assert "provider.default_endpoint" not in CAPABILITIES
    assert "stored.endpoint_is_default === false" in CAPABILITIES
    assert 'setCustomMessage(copy.keyRequired, "info");' in CAPABILITIES


def test_selected_custom_provider_model_goes_to_the_custom_field_without_tier() -> None:
    # Custom 선택의 실제 모양은 실행으로 관찰한다: 등급(tier) 대신 provider·model,
    # 기본 추론은 필드 없음, 고른 추론은 값으로 실린다.
    gate = run_capabilities_scenario("manual_gate")
    assert gate["selectionWithModel"] == {
        "provider": "prov-m", "model": "my-model", "reasoning_effort": None}
    assert gate["selectionWithReasoning"] == {
        "provider": "prov-m", "model": "my-model", "reasoning_effort": "high"}
    assert (
        'const payload = { messages: outboundMessages, tier: deps.selectedProductTier(), skill };'
        in STREAM
    )
    assert "const customSelection = window.PadiemCustomSelection?.get?.();" in STREAM
    assert "delete payload.tier;" in STREAM
    assert "payload.custom = { provider: customSelection.provider, model: customSelection.model };" in STREAM
    assert "if (customSelection.reasoning_effort) {" in STREAM
    assert "payload.custom.reasoning_effort = customSelection.reasoning_effort;" in STREAM
    # #7297: Custom is shared between Chat and Claw; text-only refusal preserves the typed prompt.
    assert 'setNote(uiT("custom-chat-only"), "error");' not in APP
    assert 'setNote(uiT("custom-text-only"), "error");' in APP
    assert LOCALE.count('"custom-text-only":') == 2


def test_custom_failures_reopen_the_existing_model_card() -> None:
    assert "function handleCustomRequestFailure(error)" in definition_source(
        "handleCustomRequestFailure"
    )
    assert 'const CUSTOM_AUTH_FAILURE_CODE = "custom_provider_auth_failed";' in APP
    assert 'code === "custom_credential_required" || code === CUSTOM_AUTH_FAILURE_CODE' in APP
    assert "window.PadiemCustomSelection?.open?.();" in APP
    assert 'code === "unauthorized" && window.PadiemCustomSelection?.get?.()' in APP
    assert "deps.handleCustomRequestFailure(error);" in STREAM


def test_custom_lane_keeps_direct_path_without_server_owned_byok_opt_in() -> None:
    assert "payload && payload.custom && !byokViaB14" in TRANSPORT
    assert "window.PadiemCustomSelection?.viaEngine?.() === true" in TRANSPORT


_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync(process.argv[2], "utf8");
const cases = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));

function responseFor(behavior) {
  if (!behavior) return new Response("{}", { status: 404, headers: { "content-type": "application/json" } });
  if (behavior.sse) {
    return new Response("event: delta\ndata: {\"delta\":\"ok\"}\n\n", {
      status: 200,
      headers: { "content-type": "text/event-stream" },
    });
  }
  return new Response(JSON.stringify(behavior.json || {}), {
    status: behavior.status || 200,
    headers: { "content-type": "application/json" },
  });
}

async function runCase(testCase) {
  const calls = [];
  const sandbox = {
    window: { PadiemCustomSelection: { viaEngine: () => testCase.byokViaB14 === true } },
    console,
    Intl,
    Response,
    TextEncoder,
    TextDecoder,
    AbortController,
    setTimeout,
    clearTimeout,
    fetch: async (url, options = {}) => {
      calls.push({
        url: String(url),
        method: options.method || "GET",
        body: typeof options.body === "string" ? options.body : null,
      });
      const path = String(url).split("?")[0];
      return responseFor((testCase.responses || {})[path]);
    },
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox, { filename: "chat-transport.js" });
  let error = null;
  let ok = false;
  try {
    const response = await sandbox.window.PadiemChatTransport.requestStreaming(testCase.payload, undefined);
    ok = Boolean(response && response.ok);
  } catch (caught) {
    error = {
      message: String(caught && caught.message),
      code: caught && caught.code ? String(caught.code) : null,
    };
  }
  return { calls, ok, error };
}

(async () => {
  const result = {};
  for (const testCase of cases) result[testCase.name] = await runCase(testCase);
  process.stdout.write(JSON.stringify(result));
})().catch((error) => {
  process.stderr.write(String(error && error.stack ? error.stack : error));
  process.exit(1);
});
"""


def _run_transport_cases() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available for the browser transport harness")
    base = {
        "messages": [{"role": "user", "content": "테스트 질문"}],
        "skill": "auto",
        "timezone": "Asia/Seoul",
        "calendar_turn_id": "turn-5121",
    }
    cases = [
        {
            "name": "byok_auth_error", "byokViaB14": True,
            "payload": {**base, "custom": {"provider": CUSTOM_PROVIDER, "model": CUSTOM_MODEL}},
            "responses": {
                "/api/orchestration/status": {"json": {"orchestration_ready": True, "authenticated": True}},
                "/api/orchestration": {"status": 403, "json": {"error": {"code":"byok_auth_failed", "message":"키를 확인해 주세요."}}},
                "/api/chat/stream": {"sse": True},
            },
        },
        {
            "name": "byok_engine_enabled", "byokViaB14": True,
            "payload": {**base, "custom": {"provider": CUSTOM_PROVIDER, "model": CUSTOM_MODEL}},
            "responses": {
                "/api/orchestration/status": {"json": {"orchestration_ready": True, "authenticated": True}},
                "/api/orchestration": {"sse": True},
            },
        },
        {
            "name": "custom",
            "payload": {
                **base,
                "custom": {"provider": CUSTOM_PROVIDER, "model": CUSTOM_MODEL},
            },
            "responses": {"/api/chat/stream": {"sse": True}},
        },
        {
            "name": "control",
            "payload": {**base, "tier": "free"},
            "responses": {
                "/api/orchestration/status": {"json": {"orchestration_ready": False, "authenticated": True}},
                "/api/chat/stream": {"sse": True},
            },
        },
        {
            "name": "custom_error",
            "payload": {
                **base,
                "custom": {"provider": CUSTOM_PROVIDER, "model": CUSTOM_MODEL},
            },
            "responses": {
                "/api/chat/stream": {
                    "status": 409,
                    "json": {
                        "error": {
                            "code": "custom_credential_required",
                            "message": "PADIEM Custom API 키를 먼저 등록해 주세요.",
                        }
                    },
                }
            },
        },
    ]
    with tempfile.TemporaryDirectory() as tmp:
        harness = Path(tmp) / "harness.js"
        payload = Path(tmp) / "cases.json"
        harness.write_text(_HARNESS, encoding="utf-8", newline="\n")
        payload.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8", newline="\n")
        completed = subprocess.run(
            [node, str(harness), str(STATIC / "chat-transport.js"), str(payload)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
        )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_custom_request_skips_orchestration_and_control_still_probes_it() -> None:
    result = _run_transport_cases()

    custom = result["custom"]
    assert custom["ok"] is True
    assert [call["url"] for call in custom["calls"]] == ["/api/chat/stream"]
    custom_body = json.loads(custom["calls"][0]["body"])
    assert custom_body["custom"] == {"provider": CUSTOM_PROVIDER, "model": CUSTOM_MODEL}
    assert "tier" not in custom_body
    assert "api_key" not in custom_body

    control = result["control"]
    assert control["ok"] is True
    assert [call["url"] for call in control["calls"]] == [
        "/api/orchestration/status",
        "/api/chat/stream",
    ]
    control_body = json.loads(control["calls"][1]["body"])
    assert control_body["tier"] == "free"
    assert "custom" not in control_body


def test_custom_error_code_reaches_the_existing_error_ui() -> None:
    result = _run_transport_cases()
    failure = result["custom_error"]
    assert failure["ok"] is False
    assert failure["error"]["code"] == "custom_credential_required"
    assert "API 키" in failure["error"]["message"]
    assert [call["url"] for call in failure["calls"]] == ["/api/chat/stream"]


def test_byok_single_register_flow_includes_the_check_and_never_renders_key():
    """#5824: one key input + one 등록 button; the click performs the check —
    observed as the real click flow (detect → register, key cleared, advanced
    section opens only when detection fails)."""
    register = run_capabilities_scenario("register_flow")
    assert register["keyInputType"] == "password"
    assert register["advancedOpenByDefault"] is False  # 접힘 기본
    assert [c["url"] for c in register["registerCalls"]] == ["/api/byok/detect", "/api/byok/register"]
    assert register["keyClearedAfterRegister"] is True
    assert register["detectFailMessage"] == "못 알아봄"
    assert register["advancedOpenAfterDetectFail"] is True  # 자동 인식 실패 때만 펼침
    assert register["detectCallCount"] == 1  # 실패 뒤 추가 등록 시도 없음
    # 구조 계약(부재 금지): 자동 확인 단축·결과 카드·키 보관은 다시 생기면 안 된다.
    section = _custom_section()
    assert 'autoKeyInput.addEventListener("input", invalidate)' in section
    assert '"자동 확인"' not in section
    assert 'autoDetectButton' not in section
    assert 'autoCard' not in section
    flow = CAPABILITIES.split('async function detectAndRegister', 1)[1].split('async function saveCustomKey', 1)[0]
    assert 'innerHTML' not in flow
    assert 'localStorage' not in flow and 'sessionStorage' not in flow


def test_byok_enabled_browser_uses_orchestration_once_and_never_direct_fallback():
    case = _run_transport_cases()["byok_engine_enabled"]
    assert case["ok"] is True
    assert [row["url"] for row in case["calls"]] == ["/api/orchestration/status", "/api/orchestration"]
    body = json.loads(case["calls"][1]["body"])
    assert body["custom"] == {"provider": CUSTOM_PROVIDER, "model": CUSTOM_MODEL}
    assert "user_credential_ref" not in body


def test_byok_engine_error_is_terminal_without_direct_or_provider_fallback():
    case = _run_transport_cases()["byok_auth_error"]
    assert case["ok"] is False and case["error"]["code"] == "byok_auth_failed"
    assert [row["url"] for row in case["calls"]] == ["/api/orchestration/status", "/api/orchestration"]
