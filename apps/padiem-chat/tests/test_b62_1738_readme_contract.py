from __future__ import annotations

from _r2_chat_transport_harness import observe

# #8060: 원문 read는 파일 전용 _support가 담당하고 시험은 토큰 존재로 단언한다.
from _support.readme_contract_source import (
    app_has,
    locale_has,
    readme_has,
    root_has,
    sheet_has,
)


def test_readme_matches_ephemeral_and_persistent_document_rules() -> None:
    assert readme_has("JPEG / PNG / WebP")
    assert readme_has("TXT / Markdown / CSV / JSON")
    assert readme_has("PDF / DOCX / PPTX / XLSX")
    assert readme_has("no PADIEM byte total") and readme_has("or character limit")
    assert not readme_has("up to 96 KiB")
    assert readme_has("Project files are a distinct persistence capability")
    for retired in ("textBytes: 96 * 1024", "textChars: 40000"):
        assert not sheet_has("attachment-capabilities.js", retired)
    for removed in ("imageBytes", "binaryBytes", "1 GiB"):
        assert not sheet_has("attachment-capabilities.js", removed)


def test_readme_matches_streaming_and_completed_transport_boundary() -> None:
    # README 금지·보장 문구는 문서 계약이라 글자로 남긴다. 전송 경계 자체는
    # 소스에 어떤 fetch가 적혀 있는지가 아니라 실제로 나가는 요청으로 본다.
    assert readme_has("attachment-free ordinary chat")
    assert readme_has("attachment-bearing composer request")
    assert readme_has("/api/chat/stream") and readme_has("/api/chat (JSON completion)")

    surface = observe()["request_surface"]
    paths = {(request["method"], request["url"]) for request in surface["requests"]}
    assert ("POST", "/api/chat/stream") in paths
    assert ("POST", "/api/chat") in paths
    assert ("GET", "/api/orchestration/status") in paths


def test_readme_matches_theme_and_locale_url_authority() -> None:
    assert readme_has("?theme=padiem-glass")
    assert readme_has("current default/fallback is `padiem-glass`")
    assert readme_has("?glass=female|male")
    assert readme_has("?lang=ko") and readme_has("?lang=en")
    assert readme_has("fallback is Korean (`ko`)")
    assert readme_has("localStorage") and readme_has("sessionStorage")
    assert sheet_has("theme-init.js", 's="padiem-glass"')
    assert sheet_has("theme.js", 'url.searchParams.set("theme",theme)')
    assert locale_has('url.searchParams.set("lang", lang)')


def test_readme_distinguishes_source_readiness_from_runtime_activation() -> None:
    assert readme_has("Source readiness is not Production activation")
    assert readme_has("Source presence alone is insufficient")
    assert readme_has("browser capability projection is presentation state only")
    for marker in ("projects_code_ready", "project_files_code_ready", "saved_outputs_code_ready", "web_tools_ready", "deep_research_ready"):
        assert app_has("app_factory.py", marker)
        assert readme_has(marker)
    assert sheet_has("product-capabilities.js", 'nativeFetch("/health"')
    assert sheet_has("product-capabilities.js", 'nativeFetch("/api/auth/status"')
    assert root_has("worker.py", "install_orchestration_routes")


def test_readme_preserves_b14_core_engine_control_plane_ownership() -> None:
    assert readme_has("Business 14 owns provider adapters, provider keys, model catalogs, exact routing and upstream transport")
    assert readme_has("Padiem AI Core owns the product-neutral execution request/result")
    assert readme_has("The browser does not mint approval evidence, canonical subject identity, provider selection or tool execution authority")
    assert app_has("canonical_orchestration_bridge.py", "Shared Control Plane canonical subject")
    assert root_has("worker.py", "build_orchestration_bridge")
    assert readme_has("PRODUCTION_MUTATION = NO")
