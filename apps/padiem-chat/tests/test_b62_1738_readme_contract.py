from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
STATIC = ROOT / "static"
APP = ROOT / "app"


def test_readme_matches_ephemeral_and_persistent_document_boundaries() -> None:
    capabilities = (STATIC / "attachment-capabilities.js").read_text(encoding="utf-8")
    assert "JPEG / PNG / WebP" in README
    assert "TXT / Markdown / CSV / JSON" in README
    assert "PDF / DOCX / PPTX / XLSX" in README
    assert "4 MiB" in README and "96 KiB" in README and "40,000" in README and "2 MiB" in README
    assert "Project files are a distinct persistence capability" in README
    for token in ("imageBytes: 4 * 1024 * 1024", "textBytes: 96 * 1024", "textChars: 40000", "binaryBytes: 2 * 1024 * 1024"):
        assert token in capabilities


def test_readme_matches_streaming_and_completed_transport_boundary() -> None:
    transport = (STATIC / "chat-transport.js").read_text(encoding="utf-8")
    assert "attachment-free ordinary chat" in README
    assert "attachment-bearing composer request" in README
    assert "/api/chat/stream" in README and "/api/chat (JSON completion)" in README
    assert 'fetch("/api/chat/stream"' in transport
    assert 'fetch("/api/chat"' in transport
    assert 'fetch("/api/orchestration/status"' in transport


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
