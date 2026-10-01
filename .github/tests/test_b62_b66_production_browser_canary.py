from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/b62_b66_production_browser_canary.py"
WORKFLOW = ROOT / ".github/workflows/b62-b66-production-browser-canary-contract.yml"
CONVERSATION = ROOT / "apps/padiem-chat/app/b66_quote_conversation.py"
ROUTES = ROOT / "apps/padiem-chat/app/b66_quote_routes.py"
RUNTIME = ROOT / "apps/padiem-chat/static/b66-quote-runtime.js"
EMBED = ROOT / "reference/business-66-padiem-quote-v1/embed.html"
EMBED_BRIDGE = ROOT / "reference/business-66-padiem-quote-v1/quote-embed-bridge.js"
EMBED_BROWSER = ROOT / "reference/business-66-padiem-quote-v1/quote-embed-browser.js"


def _load():
    spec = importlib.util.spec_from_file_location("b62_b66_production_browser_canary", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _good_body():
    return {
        "ok": True,
        "saved_skill": {
            "saved_skill_id": "b66skill_" + "a" * 32,
            "skill_id": "b66-e2e-canonical-v1",
            "skill_name": "B66 E2E 견적서",
            "skill_fingerprint": "b" * 64,
            "skill_version": 1,
        },
        "candidate": {
            "recipient": {"company": "대한건설", "person": None, "address": None, "email": None},
            "quoteNo": None,
            "issueDate": None,
            "items": [{"name": "배관", "qty": 100, "unitPrice": 18000}],
            "memo": None,
            "taxMode": None,
            "missing": [],
        },
        "execution": {
            "source_document_parse_calls": 0,
            "server_total_calculation": False,
            "server_rendering": False,
            "browser_quote_core_required": True,
            "browser_approved_renderer_required": True,
        },
    }


def test_cdp_endpoints_are_loopback_only_and_distinct() -> None:
    helper = _load()
    assert helper.validate_cdp_url("http://127.0.0.1:9222") == "http://127.0.0.1:9222"
    assert helper.validate_cdp_url("http://localhost:9223/") == "http://localhost:9223/"
    helper.ensure_distinct_cdp_urls(
        "http://127.0.0.1:9222",
        "http://127.0.0.1:9223",
        "http://127.0.0.1:9224",
    )
    for bad in (
        "https://127.0.0.1:9222",
        "http://example.com:9222",
        "http://user:pass@127.0.0.1:9222",
        "http://127.0.0.1:9222/path",
        "http://127.0.0.1:9222/?token=x",
    ):
        with pytest.raises(helper.CanaryFailure):
            helper.validate_cdp_url(bad)
    with pytest.raises(helper.CanaryFailure, match="distinct"):
        helper.ensure_distinct_cdp_urls(
            "http://127.0.0.1:9222",
            "http://127.0.0.1:9222",
            None,
        )


def test_interpret_projection_accepts_only_exact_variable_request() -> None:
    helper = _load()
    candidate = helper.validate_interpret_projection(_good_body())
    assert candidate["recipient"]["company"] == "대한건설"
    assert candidate["items"] == [{"name": "배관", "qty": 100, "unitPrice": 18000}]

    wrong = _good_body()
    wrong["candidate"]["items"][0]["unitPrice"] = 18001
    with pytest.raises(helper.CanaryFailure, match="values"):
        helper.validate_interpret_projection(wrong)

    forbidden = _good_body()
    forbidden["candidate"]["grandTotal"] = 1980000
    with pytest.raises(helper.CanaryFailure, match="forbidden"):
        helper.validate_interpret_projection(forbidden)


def test_canary_is_local_session_only_and_never_handles_credentials() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'TARGET_URL = "https://chat.padiem.net/"' in source
    assert 'B66_RUNTIME_HOST = "quick-quote-kr.pages.dev"' in source
    assert 'ALLOWED_CDP_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})' in source
    assert "--authorized-live-run" in source
    assert "DEFAULT_LIVE_EXECUTION=BLOCKED" in source
    assert "--secondary-cdp-url" in source
    assert "--foreign-cdp-url" in source
    assert "COOKIE_OUTPUT=0" in source
    assert "TOKEN_OUTPUT=0" in source
    assert "RAW_USER_OUTPUT=0" in source
    assert "RAW_TENANT_OUTPUT=0" in source
    assert "RAW_WORKSPACE_OUTPUT=0" in source
    assert "RAW_SKILL_OUTPUT=0" in source
    for forbidden in (
        "password=",
        "Authorization:",
        "Cookie:",
        "document.cookie",
        "storage_state",
        "context.cookies",
        "localStorage",
        "sessionStorage",
    ):
        assert forbidden not in source


def test_canary_pins_representative_request_and_expected_values() -> None:
    helper = _load()
    assert helper.REQUEST_TEXT == "대한건설에 배관 100m, 미터당 18,000원"
    assert helper.EXPECTED_CUSTOMER == "대한건설"
    assert helper.EXPECTED_ITEM == "배관"
    assert helper.EXPECTED_QTY == 100
    assert helper.EXPECTED_UNIT_PRICE == 18000
    source = SCRIPT.read_text(encoding="utf-8")
    for marker in (
        "BOUNDED_MODEL_CALL_COUNT=1",
        "SOURCE_DOCUMENT_PARSE_CALLS=0",
        "FULL_DOCUMENT_MODEL_REGENERATION=0",
        "QUOTECORE_MODEL_CALLS=0",
        "RENDERER_MODEL_CALLS=0",
        "QUOTECORE_CALCULATION=PASS",
        "CANONICAL_RENDERER=PASS",
        "PREVIEW=PASS",
        "PRINT_OR_PDF=PASS",
        "SAME_ACCOUNT_RELOGIN_PERSISTENCE=PASS",
        "FOREIGN_ACCOUNT_ACCESS=DENIED_OR_NONDISCLOSING",
        "CLIENT_OWNERSHIP_OVERRIDE=DENIED",
    ):
        assert marker in source


def test_deployed_b66_source_has_one_bounded_interpreter_call_and_no_server_render_math() -> None:
    conversation = CONVERSATION.read_text(encoding="utf-8")
    routes = ROUTES.read_text(encoding="utf-8")
    assert conversation.count("self._client.complete(") == 1
    assert "attachments=()," in conversation
    assert "금액 합계" in conversation
    assert '"subtotal"' in conversation
    assert 'browser_quote_core_required": True' in routes
    assert 'browser_approved_renderer_required": True' in routes
    assert 'source_document_parse_calls": 0' in routes
    assert 'server_total_calculation": False' in routes
    assert 'server_rendering": False' in routes


def test_browser_runtime_delegates_to_canonical_embed_and_print_path() -> None:
    runtime = RUNTIME.read_text(encoding="utf-8")
    embed = EMBED.read_text(encoding="utf-8")
    bridge = EMBED_BRIDGE.read_text(encoding="utf-8")
    embed_browser = EMBED_BROWSER.read_text(encoding="utf-8")

    assert '"/api/b66/saved-skills?limit=20"' in runtime
    assert '"/api/b66/quote/interpret"' in runtime
    assert 'type: "b66.embed.render.v1"' in runtime
    for script in (
        "quote-core.js",
        "quote-template.js",
        "quote-template-renderer.js",
        "quote-skill.js",
        "quote-embed-bridge.js",
        "quote-embed-browser.js",
    ):
        assert f'<script src="{script}" defer></script>' in embed
    assert "runtime.SavedSkill.buildRenderModel" in bridge
    assert "runtime.Renderer.applyRenderModel" in bridge
    assert "runtime.Core.printReadiness" in bridge
    assert "window.print()" in embed_browser


def test_workflow_is_source_contract_only() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m pytest -q .github/tests/test_b62_b66_production_browser_canary.py" in workflow
    assert "LIVE_BROWSER_SESSION=0" in workflow
    assert "PRODUCTION_MUTATION=0" in workflow
    assert "COOKIE_EXPORT=0" in workflow
    assert "TOKEN_EXPORT=0" in workflow
    assert "workflow_dispatch:" in workflow
    for forbidden in (
        "--authorized-live-run",
        "playwright install",
        "gh workflow run",
        "wrangler deploy",
        "curl -X POST",
        "CLOUDFLARE_API_TOKEN",
        "B62_B66_E2E_TARGET_USER_ID",
    ):
        assert forbidden not in workflow
