from __future__ import annotations

from pathlib import Path

from _r2_chat_transport_harness import observe


ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
STATIC = ROOT / "static"
APP = ROOT / "app"


def test_readme_matches_ephemeral_and_persistent_document_rules() -> None:
    capabilities = (STATIC / "attachment-capabilities.js").read_text(encoding="utf-8")
    assert "JPEG / PNG / WebP" in README
    assert "TXT / Markdown / CSV / JSON" in README
    assert "PDF / DOCX / PPTX / XLSX" in README
    assert "no PADIEM byte total" in README and "or character limit" in README
    assert "up to 96 KiB" not in README
    assert "Project files are a distinct persistence capability" in README
    for retired in ("textBytes: 96 * 1024", "textChars: 40000"):
        assert retired not in capabilities
    for removed in ("imageBytes", "binaryBytes", "1 GiB"):
        assert removed not in capabilities


def test_readme_matches_streaming_and_completed_transport_boundary() -> None:
    # README 금지·보장 문구는 문서 계약이라 글자로 남긴다. 전송 경계 자체는
    # 소스에 어떤 fetch가 적혀 있는지가 아니라 실제로 나가는 요청으로 본다.
    assert "attachment-free ordinary chat" in README
    assert "attachment-bearing composer request" in README
    assert "/api/chat/stream" in README and "/api/chat (JSON completion)" in README

    surface = observe()["request_surface"]
    paths = {(request["method"], request["url"]) for request in surface["requests"]}
    assert ("POST", "/api/chat/stream") in paths
    assert ("POST", "/api/chat") in paths
    assert ("GET", "/api/orchestration/status") in paths


def test_readme_matches_theme_and_locale_url_authority() -> None:
    theme_init = (STATIC / "theme-init.js").read_text(encoding="utf-8")
    theme = (STATIC / "theme.js").read_text(encoding="utf-8")
    locale = (STATIC / "locale.js").read_text(encoding="utf-8")
    assert "?theme=padiem-glass" in README
    assert "current default/fallback is `padiem-glass`" in README
    assert "?glass=female|male" in README
    assert "?lang=ko" in README and "?lang=en" in README
    assert "fallback is Korean (`ko`)" in README
    assert "localStorage" in README and "sessionStorage" in README
    assert 's="padiem-glass"' in theme_init
    assert 'url.searchParams.set("theme",theme)' in theme
    assert 'url.searchParams.set("lang", lang)' in locale


def test_readme_distinguishes_source_readiness_from_runtime_activation() -> None:
    factory = (APP / "app_factory.py").read_text(encoding="utf-8")
    worker = (ROOT / "worker.py").read_text(encoding="utf-8")
    capability = (STATIC / "product-capabilities.js").read_text(encoding="utf-8")
    assert "Source readiness is not Production activation" in README
    assert "Source presence alone is insufficient" in README
    assert "browser capability projection is presentation state only" in README
    for marker in ("projects_code_ready", "project_files_code_ready", "saved_outputs_code_ready", "web_tools_ready", "deep_research_ready"):
        assert marker in factory
        assert marker in README
    assert 'nativeFetch("/health"' in capability
    assert 'nativeFetch("/api/auth/status"' in capability
    assert "install_orchestration_routes" in worker


def test_readme_preserves_b14_core_engine_control_plane_ownership() -> None:
    worker = (ROOT / "worker.py").read_text(encoding="utf-8")
    canonical = (APP / "canonical_orchestration_bridge.py").read_text(encoding="utf-8")
    assert "Business 14 owns provider adapters, provider keys, model catalogs, exact routing and upstream transport" in README
    assert "Padiem AI Core owns the product-neutral execution request/result" in README
    assert "The browser does not mint approval evidence, canonical subject identity, provider selection or tool execution authority" in README
    assert "Shared Control Plane canonical subject" in canonical
    assert "build_orchestration_bridge" in worker
    assert "PRODUCTION_MUTATION = NO" in README
