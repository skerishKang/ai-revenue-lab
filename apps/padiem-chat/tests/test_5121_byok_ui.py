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

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
CAPABILITIES = (STATIC / "product-capabilities.js").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
TRANSPORT = (STATIC / "chat-transport.js").read_text(encoding="utf-8")
CSS = (STATIC / "mode-presentation.css").read_text(encoding="utf-8")
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")

CUSTOM_PROVIDER = "opencode-go"
CUSTOM_MODEL = "opencode-go/beam-free"


def test_model_card_adds_a_custom_lane_separate_from_padiem_tiers() -> None:
    assert 'TIER_LIST = Object.freeze(["free", "plus", "pro", "max"]);' in CAPABILITIES
    assert "list.append(...TIER_LIST.map((tier) => createModeOption(tier)));" in CAPABILITIES
    assert 'modePanel.append(header, list, truth, createCustomSection());' in CAPABILITIES
    assert 'customOption.dataset.modeValue = "custom";' in CAPABILITIES
    assert '"mode-option mode-option--custom"' in CAPABILITIES
    assert 'customOptionTitle.textContent = provider ? provider.display_name : copy.option;' in CAPABILITIES

    section = CSS.split(".mode-custom-section {", 1)[1].split("}", 1)[0]
    assert "border-top: 1px solid var(--line)" in section
    panel = CSS.split(".mode-presentation-panel {", 1)[1].split("}", 1)[0]
    assert "max-height: min(72vh, 640px)" in panel
    assert "overflow-y: auto" in panel
    assert "overscroll-behavior: contain" in panel


def _custom_copy_block() -> str:
    return CAPABILITIES.split("const CUSTOM_COPY", 1)[1].split("let customSelection", 1)[0]


def _custom_section() -> str:
    return CAPABILITIES.split("function createCustomSection()", 1)[1].split(
        "function createModeOption", 1
    )[0]


def test_picker_title_and_byok_copy_match_the_owner_contract() -> None:
    tier_ko = CAPABILITIES.split("const TIER_COPY", 1)[1].split("en: Object.freeze", 1)[0]
    assert 'title: "모델 선택"' in tier_ko
    assert 'title: "Choose model"' in CAPABILITIES

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
    heading = _custom_section().split(
        'heading.className = "mode-custom-heading";', 1
    )[1].split("customOption = document.createElement", 1)[0]
    assert "heading.append(title, description);" in heading
    for forbidden in ("status-spark", "<svg", "<img", "createElementNS", "🔑"):
        assert forbidden not in heading, forbidden


def test_connection_test_is_real_and_only_shown_for_server_supported_providers() -> None:
    # No placeholder button and no client-side success claim: the control is
    # hidden unless the server advertises a model-list-backed test and a stored
    # credential exists, and the result comes from the server response.
    assert (
        'customTestButton.hidden = !provider || !provider.supports_connection_test || !credential;'
        in CAPABILITIES
    )
    assert 'nativeFetch("/api/chat/custom/credential/test"' in CAPABILITIES
    assert 'body: JSON.stringify({ provider: provider.provider })' in CAPABILITIES
    assert "customTestState = \"testing\";" in CAPABILITIES
    assert "setCustomMessage(copy.testOk, \"ok\");" in CAPABILITIES
    assert "setCustomMessage(errorMessage(data) || copy.testFailed, \"error\");" in CAPABILITIES
    for forbidden in ("업데이트 내역", "Update history"):
        assert forbidden not in CAPABILITIES, forbidden


def test_picker_renders_only_server_reported_providers_models_and_capabilities() -> None:
    assert 'const providers = Array.isArray(data.providers) ? data.providers : [];' in CAPABILITIES
    assert "customProviderSelect.textContent = \"\";" in CAPABILITIES
    assert "customProviders.forEach((row) => {" in CAPABILITIES
    assert "option.value = row.provider;" in CAPABILITIES
    assert "manual_model: row.manual_model === true," in CAPABILITIES
    assert "supports_connection_test: row.supports_connection_test === true," in CAPABILITIES
    assert "supports_custom_endpoint: row.supports_custom_endpoint === true," in CAPABILITIES
    assert "customCopyBlock.append(customOptionTitle, customOptionModel);" in CAPABILITIES
    # The browser still contains no provider inventory of its own.
    for provider in ("openai", "anthropic", "openrouter", "gemini", "opencode-go"):
        assert provider not in CAPABILITIES.lower(), provider


def test_manual_model_requires_an_explicit_model_before_custom_selection() -> None:
    select_custom = CAPABILITIES.split("function selectCustom()", 1)[1].split(
        "function selectCustomProvider", 1
    )[0]
    assert "const model = customModelId();" in select_custom
    assert "if (!model) {" in select_custom
    assert "setCustomMessage(customCopy().modelRequired, \"error\");" in select_custom
    assert "focusCustomModel();" in select_custom
    assert "customSelection = { provider: provider.provider, model };" in select_custom
    # No automatic success for a typed-but-unverified model.
    assert "customSelection = { provider: provider.provider, model };" in CAPABILITIES
    assert 'body: JSON.stringify({ provider: provider.provider })' in CAPABILITIES
    assert '"/api/chat/custom/models?provider=" + encodeURIComponent(provider.provider)' in CAPABILITIES


def test_tier_rows_keep_existing_order_status_and_badges() -> None:
    assert 'TIER_LIST = Object.freeze(["free", "plus", "pro", "max"]);' in CAPABILITIES
    assert 'status === "available" ? "✓" : status === "upgrade" ? "↑" : "—"' in CAPABILITIES
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
    assert 'nativeFetch("/api/chat/custom/credential", {' in CAPABILITIES
    assert 'method: "PUT"' in CAPABILITIES
    assert "const payload = { provider: provider.provider, api_key: key };" in CAPABILITIES
    assert "if (endpoint) payload.endpoint = endpoint;" in CAPABILITIES
    assert "body: JSON.stringify(payload)" in CAPABILITIES
    assert 'method: "DELETE"' in CAPABILITIES
    assert (
        '"/api/chat/custom/credential?provider=" + encodeURIComponent(provider.provider)'
        in CAPABILITIES
    )
    delete_call = CAPABILITIES.split('method: "DELETE"', 1)[1].split("});", 1)[0]
    assert "body:" not in delete_call
    # The raw key is cleared on a successful write and never stored client-side.
    assert 'customInput.value = "";' in CAPABILITIES
    assert "credential.key_last4" in CAPABILITIES
    for forbidden in ("localStorage", "sessionStorage", "document.cookie", "console."):
        assert forbidden not in CAPABILITIES, forbidden
    # Only the server-provided last four characters are rendered.
    assert 'copy.credential + String(credential.key_last4 || "")' in CAPABILITIES


def test_custom_endpoint_and_provider_model_controls_follow_server_capabilities() -> None:
    assert 'customProviderSelect.id = "modeCustomProvider";' in CAPABILITIES
    assert 'customModelSelect.id = "modeCustomModelSelect";' in CAPABILITIES
    assert 'customModelInput.id = "modeCustomModelInput";' in CAPABILITIES
    assert 'customEndpointInput.id = "modeCustomEndpoint";' in CAPABILITIES
    assert 'customTestButton.className = "mode-custom-action mode-custom-test";' in CAPABILITIES
    assert 'customModelListButton.hidden = !provider || !provider.supports_model_listing;' in CAPABILITIES
    assert 'customEndpointInput.hidden = !provider || !provider.supports_custom_endpoint;' in CAPABILITIES
    assert 'customEndpointInput.placeholder = provider && provider.default_endpoint' in CAPABILITIES
    # The default endpoint is presented, and a key is never sent to an endpoint
    # the server did not store for this provider.
    assert "credential.endpoint_is_default === false" in CAPABILITIES
    assert "if (endpoint) payload.endpoint = endpoint;" in CAPABILITIES
    assert 'setCustomMessage(copy.keyRequired, "info");' in CAPABILITIES


def test_selected_custom_provider_model_goes_to_the_custom_field_without_tier() -> None:
    assert (
        'const payload = { messages: outboundMessages, mode: "auto", tier: selectedProductTier(), skill };'
        in APP
    )
    assert "const customSelection = !clawGeneralRequest && window.PadiemCustomSelection?.get?.();" in APP
    assert "delete payload.tier;" in APP
    assert "payload.custom = { provider: customSelection.provider, model: customSelection.model };" in APP
    assert "window.PadiemCustomSelection = Object.freeze({" in CAPABILITIES
    assert 'Object.freeze({ provider: customSelection.provider, model: customSelection.model })' in CAPABILITIES
    # Custom is Chat-only and text-only; both refusals preserve the typed prompt.
    assert 'setNote(uiT("custom-chat-only"), "error");' in APP
    assert 'setNote(uiT("custom-text-only"), "error");' in APP
    assert LOCALE.count('"custom-chat-only":') == 2
    assert LOCALE.count('"custom-text-only":') == 2


def test_custom_failures_reopen_the_existing_model_card() -> None:
    assert "function handleCustomRequestFailure(error)" in APP
    assert 'const CUSTOM_AUTH_FAILURE_CODE = "custom_provider_auth_failed";' in APP
    assert 'code === "custom_credential_required" || code === CUSTOM_AUTH_FAILURE_CODE' in APP
    assert "window.PadiemCustomSelection?.open?.();" in APP
    assert 'code === "unauthorized" && window.PadiemCustomSelection?.get?.()' in APP
    assert "handleCustomRequestFailure(error);" in APP


def test_custom_lane_never_routes_through_b14_orchestration() -> None:
    assert "payload && payload.custom ? null : await tryOrchestration(payload, signal)" in TRANSPORT


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
    window: {},
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
        "mode": "auto",
        "skill": "auto",
        "timezone": "Asia/Seoul",
        "calendar_turn_id": "turn-5121",
    }
    cases = [
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
