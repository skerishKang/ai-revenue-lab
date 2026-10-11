"""Static/security contracts for the Padiem Chat -> canonical B66 UI bridge (#3313)."""

from pathlib import Path

import pytest

from app.config import ConfigError, Settings


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


def test_b66_quote_runtime_url_is_https_root_only_and_default_off() -> None:
    assert Settings.from_values().b66_quote_base_url is None
    configured = Settings.from_values(
        b66_quote_base_url="https://quick.example.test/"
    )
    assert configured.b66_quote_base_url == "https://quick.example.test"

    with pytest.raises(ConfigError, match="https"):
        Settings.from_values(b66_quote_base_url="http://quick.example.test")
    with pytest.raises(ConfigError, match="path"):
        Settings.from_values(
            b66_quote_base_url="https://quick.example.test/some/path"
        )
    with pytest.raises(ConfigError):
        Settings.from_values(
            b66_quote_base_url="https://user:pass@quick.example.test"
        )


def test_index_loads_hidden_quote_bridge_before_capability_projection() -> None:
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    assert './b66-quote-runtime.css' in index
    assert './b66-quote-runtime.js' in index
    assert index.index('./b66-quote-runtime.js') < index.index('./product-capabilities.js')
    # Manual merge-forward must preserve real HTML newlines. A literal "\\n"
    # becomes visible body text and can shift visual layout by one line.
    assert '</script>\\n' not in index
    assert '/>\\n  <link' not in index


def test_quote_ui_bridge_does_not_duplicate_quote_authorities_or_persist_skill() -> None:
    source = (STATIC / "b66-quote-runtime.js").read_text(encoding="utf-8")

    for forbidden in (
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "computeTotals",
        "buildRenderModel",
        "QuoteCore",
        "SavedQuoteSkill",
        "QuoteTemplateRenderer",
        "FileReader",
        "FormData",
    ):
        assert forbidden not in source

    assert "quick-quote-kr.pages.dev" not in source
    assert "PADIEM_CHAT_B66_QUOTE_BASE_URL" not in source
    assert '"/api/b66/runtime-config"' in source
    assert '"/api/b66/saved-skills?limit=20"' in source
    assert '"/api/b66/quote/interpret"' in source


def test_quote_ui_bridge_uses_exact_iframe_source_and_origin() -> None:
    source = (STATIC / "b66-quote-runtime.js").read_text(encoding="utf-8")
    assert "event.source !== frame.contentWindow" in source
    assert "event.origin !== runtime.origin" in source
    assert "}, runtime.origin);" in source
    assert 'type: "b66.embed.render.v1"' in source
    assert '"b66.embed.rendered.v1"' in source
    assert '"b66.embed.error.v1"' in source


def test_signed_out_startup_is_network_silent_for_b66() -> None:
    source = (STATIC / "b66-quote-runtime.js").read_text(encoding="utf-8")
    assert 'auth.authenticated === true) refresh()' in source
    assert "ensureUi();\n      refresh();" not in source
    # API access is centralized behind refresh/readJson rather than eager top-level fetch.
    assert source.count('readJson("/api/b66/runtime-config")') == 1


def test_launcher_remains_hidden_without_runtime_and_assigned_skills() -> None:
    source = (STATIC / "b66-quote-runtime.js").read_text(encoding="utf-8")
    assert "launcher.hidden = !(runtime && skills.length > 0)" in source
    assert "launcher.disabled = launcher.hidden" in source
    assert "skills = safeSkills(listResult.data)" in source

def test_quote_ui_bridge_loads_only_bounded_private_quote_assets() -> None:
    source = (STATIC / "b66-quote-runtime.js").read_text(encoding="utf-8")
    assert 'B66_ASSET_ID = /^b66asset_' in source
    assert '"/api/b66/assets/" + encodeURIComponent(assetId)' in source
    assert 'PRIVATE_ASSET_MEDIA = new Set(["image/png", "image/jpeg", "image/webp"])' in source
    assert "MAX_PRIVATE_ASSET_BYTES = 256 * 1024" in source
    assert "response.arrayBuffer()" in source
    assert "data:" in source and ";base64," in source
    assert "FileReader" not in source
    assert "FormData" not in source
