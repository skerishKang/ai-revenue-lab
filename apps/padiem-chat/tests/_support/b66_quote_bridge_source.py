"""Parsed facts for the #3313 B66 quote UI bridge static contracts.

Raw shipped-source reads live here (reusing claw_static); each test receives
named booleans, counts, missing-token lists and parsed block order instead of
pinning raw source text.
"""
from __future__ import annotations

from _support.claw_static import sheet


def _source() -> str:
    return sheet("b66-quote-runtime.js")


def _block(source: str, start: str, end: str) -> str:
    return source.split(start, 1)[1].split(end, 1)[0]


def _present(value: str, needles: tuple[str, ...]) -> list[str]:
    return [needle for needle in needles if needle in value]


def _absent(value: str, needles: tuple[str, ...]) -> list[str]:
    return [needle for needle in needles if needle not in value]


def index_facts() -> dict:
    html = sheet("index.html")
    return {
        "css_ref": "./b66-quote-runtime.css" in html,
        "js_ref": "./b66-quote-runtime.js" in html,
        "js_before_capabilities": (
            html.index("./b66-quote-runtime.js") < html.index("./product-capabilities.js")
        ),
        "newline_artifacts": _present(html, ("</script>\\n", "/>\\n  <link")),
    }


def authority_facts() -> dict:
    source = _source()
    return {
        "forbidden_tokens": _present(source, (
            "localStorage", "sessionStorage", "indexedDB", "computeTotals", "buildRenderModel",
            "QuoteCore", "SavedQuoteSkill", "QuoteTemplateRenderer", "FileReader", "FormData",
        )),
        "hardcoded_host": "quick-quote-kr.pages.dev" in source,
        "env_var": "PADIEM_CHAT_B66_QUOTE_BASE_URL" in source,
        "missing_endpoints": _absent(source, (
            '"/api/b66/runtime-config"',
            '"/api/b66/saved-skills?limit=20"',
            '"/api/b66/quote/interpret"',
        )),
    }


def iframe_guard_facts() -> dict:
    source = _source()
    return {
        "missing_guards": _absent(source, (
            "event.source !== frame.contentWindow",
            "event.origin !== runtime.origin",
            "}, runtime.origin);",
            'type: "b66.embed.render.v1"',
            '"b66.embed.rendered.v1"',
            '"b66.embed.error.v1"',
        )),
    }


def startup_facts() -> dict:
    source = _source()
    return {
        "signed_in_assignment": "signedIn = !!(auth && auth.authenticated === true);" in source,
        "refresh_on_signed_in": "if (signedIn) refresh();" in source,
        "eager_startup": "ensureUi();\n      refresh();" in source,
        "runtime_config_reads": source.count('readJson("/api/b66/runtime-config")'),
    }


def launcher_facts() -> dict:
    source = _source()
    return {
        "hidden_rule": "launcher.hidden = !(runtime && (skills.length > 0 || pcAccountLinked));" in source,
        "disabled_rule": "launcher.disabled = launcher.hidden" in source,
        "skills_assignment": "skills = safeSkills(listResult.data)" in source,
        "pc_flag_init": "let pcAccountLinked = false;" in source,
        "linked_flag_rule": "const next = linked === true;" in source,
    }


def linked_pc_facts() -> dict:
    source = _source()
    return {
        "missing_rules": _absent(source, (
            "const entryOnly = skills.length === 0 && pcAccountLinked;",
            "launcherLabel.textContent = entryOnly ? pcCopy().entry : copy().launcher;",
            "selectLabelNode.hidden = entryOnly",
            "generateButton.hidden = entryOnly",
            "void refreshPcAccount();",
        )),
    }


def asset_facts() -> dict:
    source = _source()
    return {
        "missing_rules": _absent(source, (
            "B66_ASSET_ID = /^b66asset_",
            '"/api/b66/assets/" + encodeURIComponent(assetId)',
            'PRIVATE_ASSET_MEDIA = new Set(["image/png", "image/jpeg", "image/webp"])',
            "MAX_PRIVATE_ASSET_BYTES = 256 * 1024",
            "response.arrayBuffer()",
        )),
        "data_uri": "data:" in source and ";base64," in source,
        "forbidden_tokens": _present(source, ("FileReader", "FormData")),
    }


def preview_facts() -> dict:
    source = _source()
    ensure = _block(source, "  function ensureUi() {", "  function ensurePreviewFrame()")
    creation = _block(source, "  function ensurePreviewFrame() {", "  function waitForFrame(")
    render = _block(source, "  async function generate(event)", "  function receiveEmbedMessage(")
    return {
        "iframe_in_ensure": 'document.createElement("iframe")' in ensure,
        "iframe_in_creation": 'document.createElement("iframe")' in creation,
        "referrer_policy": 'frame.referrerPolicy = "no-referrer"' in creation,
        "sandbox": 'frame.setAttribute("sandbox", "allow-scripts allow-same-origin allow-modals")' in creation,
        "assets_before_frame": (
            render.index("const assets = await loadPrivateAssets(skill)")
            < render.index("const frame = ensurePreviewFrame()")
        ),
        "frame_before_wait": (
            render.index("const frame = ensurePreviewFrame()")
            < render.index("await waitForFrame(frame, runtime.embedUrl)")
        ),
        "same_origin_guard": "if (embed.origin === window.location.origin) return null" in source,
        "source_guard": "event.source !== frame.contentWindow" in source,
        "origin_guard": "event.origin !== runtime.origin" in source,
    }
