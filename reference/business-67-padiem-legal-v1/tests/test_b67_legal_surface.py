"""test_b67_legal_surface.py — static contract tests for the B67 Padiem Legal review surface.

Written in the same style as the canonical Claw UI tests
(apps/padiem-chat/tests/test_b62_*.py, test_claw_workspace_ui.py): they read the
static assets and assert on their exact text, so a contract cannot be dropped
without a test failing.

Three things are protected here:

1. CLAW CONTINUITY — the surface must keep using Claw's tokens, breakpoints,
   touch floors, type scale, and single-live-region rule, because it is a Claw
   vertical and not a fork.

2. LEGAL DOMAIN SEPARATION — the generic Claw layers must contain no
   legal-domain logic. Deleting legal/ must leave a working grounded-research
   surface. That is the property that makes absorption into Claw cheap.

3. HONESTY — the capability claims in the UI and README must not overstate what
   the repo actually has. These assertions encode the source audit, so a future
   edit that starts claiming live Drive, live OCR, or legacy HWP support fails.

Run:  python -m pytest reference/business-67-padiem-legal-v1/tests/ -q
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

INDEX = (ROOT / "index.html").read_text(encoding="utf-8")

TOKENS = (ROOT / "css" / "claw-tokens.css").read_text(encoding="utf-8")
SHELL = (ROOT / "css" / "claw-shell.css").read_text(encoding="utf-8")
CONV = (ROOT / "css" / "claw-conversation.css").read_text(encoding="utf-8")
EVID = (ROOT / "css" / "claw-evidence-card.css").read_text(encoding="utf-8")

AUTH = (ROOT / "legal" / "legal-authority.css").read_text(encoding="utf-8")
AUTH_JS = (ROOT / "legal" / "legal-authority.js").read_text(encoding="utf-8")
DEMO_JS = (ROOT / "legal" / "legal-demo.js").read_text(encoding="utf-8")
DECOR_JS = (ROOT / "legal" / "legal-evidence-provenance.js").read_text(encoding="utf-8")

CORPUS = (ROOT / "data" / "demo-corpus.js").read_text(encoding="utf-8")
CSHELL = (ROOT / "js" / "claw-shell.js").read_text(encoding="utf-8")
CEVID = (ROOT / "js" / "claw-evidence.js").read_text(encoding="utf-8")

SHARED_CSS = [TOKENS, SHELL, CONV, EVID]
SHARED_JS = [CSHELL, CEVID]
LEGAL_CSS = [AUTH]
LEGAL_JS = [AUTH_JS, DEMO_JS, DECOR_JS]
ALL_CSS = SHARED_CSS + LEGAL_CSS

README = (ROOT / "README.md").read_text(encoding="utf-8") if (ROOT / "README.md").exists() else ""


# ── 1. Claw continuity ────────────────────────────────────────────────────

CLAW_TOKENS = (
    "--text", "--muted", "--line", "--card-bg", "--accent",
    "--accent-soft", "--accent-contrast",
)


@pytest.mark.parametrize("token", CLAW_TOKENS)
def test_shared_layers_use_claw_theme_tokens(token: str) -> None:
    """Claw components inherit shared roles; they never hardcode a palette."""
    for source in (SHELL, CONV, EVID):
        assert f"var({token})" in source, f"{token} missing from a shared layer"


def test_no_legacy_token_aliases() -> None:
    """The canonical suite bans the old aliases outright."""
    banned = ("--ink", "--text-muted")
    for source in ALL_CSS + LEGAL_JS:
        for token in banned:
            assert token not in source, f"{token} reintroduced in {source[:40]}"


def test_no_var_fallbacks() -> None:
    """Claw writes bare var(--token); a fallback hides a missing theme role."""
    for source in ALL_CSS:
        for m in re.finditer(r"var\(--[a-z0-9-]+\s*,", source):
            fail = source[max(0, m.start() - 60):m.start() + 40]
            assert "claude" not in fail.lower(), f"unexpected var fallback: {m.group(0)}"


def test_token_file_transcribes_claw_values() -> None:
    """The dark block must match the canonical Padiem Chat dark theme values,
    so this surface inherits Claw rather than approximating it."""
    for value in (
        "--bg: #131417;",
        "--text: #e9eaec;",
        "--accent: #9fc0dd;",
        "--accent-contrast: #131417;",
        "--card-bg: #181a1e;",
    ):
        assert value in TOKENS, f"token drift: {value}"


def test_canonical_breakpoints() -> None:
    """920px / 620px are shared by CSS and matchMedia; a new breakpoint here
    would desynchronise the collapse from the controller."""
    assert "@media (max-width: 920px)" in SHELL
    assert "@media (max-width: 620px)" in SHELL
    assert 'matchMedia("(max-width: 920px)")' in DEMO_JS


def test_touch_target_floors() -> None:
    """44px standard, 48px primary — the canonical Claw floors."""
    assert "min-height: 44px" in SHELL
    assert "min-height: 48px" in SHELL
    assert "min-height: 44px" in CONV
    assert "min-height: 44px" in EVID
    assert "min-height: 44px" in AUTH


def test_ios_zoom_floor() -> None:
    """Text inputs stay at 16px so mobile focus does not zoom the viewport."""
    block = SHELL.split(".composer textarea {", 1)[1].split("}", 1)[0]
    assert "font-size: 16px" in block


def test_reduced_motion_per_layer() -> None:
    """Each layer that animates ships its own suppression block."""
    for name, source in (("shell", SHELL), ("conversation", CONV), ("evidence", EVID)):
        assert "prefers-reduced-motion" in source, f"{name} has no reduced-motion block"


def test_no_component_theme_overrides() -> None:
    """A component must not carry a theme-specific palette; Claw inherits.

    Comments are stripped first: this surface documents the rule in prose, and
    scanning the prose would make the contract unpassable.
    """
    pattern = r'html\[data-theme=[^\]]+\][^{]*\.(?:claw|ev|prov|auth|corpus|fmt)\s*\{'
    for name, source in (("shell", SHELL), ("conversation", CONV),
                         ("evidence", EVID), ("authority", AUTH)):
        code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
        assert not re.findall(pattern, code), \
            f"{name} CSS declares its own theme palette"


def test_single_live_region() -> None:
    """Exactly one polite live region, and it is not the result container."""
    polite = re.findall(r'aria-live="([^"]+)"', INDEX)
    assert polite.count("polite") == 1, f"expected 1 polite live region, found {polite}"
    composer_note = INDEX.split('id="runtimeNote"', 1)[1].split(">", 1)[0]
    assert 'aria-live="polite"' in composer_note
    # No nested live region inside the conversation.
    assert 'aria-live' not in INDEX.split('id="conversation"', 1)[1].split("</section>", 1)[0]


def test_single_h1() -> None:
    """Exactly one h1 must exist at a time.

    The home state is rendered by JS, so the static markup must contain no h1
    at all (any h1 there would become a second one in the DOM) and the renderer
    must create exactly one. The live count is asserted by verify_browser.py.
    """
    assert INDEX.count("<h1") == 0, \
        "h1 belongs to the rendered home state, not the static shell"
    assert DEMO_JS.count('"h1"') == 1, "the renderer must create exactly one h1"


def test_drawer_and_sidebar_dialog_semantics() -> None:
    drawer = INDEX.split('id="evidenceDrawer"', 1)[1].split(">", 1)[0]
    assert 'role="dialog"' in drawer
    assert 'aria-modal="true"' in drawer
    assert "inert" in drawer, "a closed sheet must be inert so it cannot trap focus"
    trigger = INDEX.split('id="evidenceTrigger"', 1)[1].split(">", 1)[0]
    assert 'aria-expanded="false"' in trigger
    assert 'aria-controls="evidenceDrawer"' in trigger
    menu = INDEX.split('id="mobileMenu"', 1)[1].split(">", 1)[0]
    assert 'aria-controls="sidebar"' in menu
    assert 'aria-expanded="false"' in menu


def test_focus_rings_never_removed() -> None:
    """No focus ring may be removed outright.

    One relocation is legitimate and canonical: the composer textarea drops its
    own outline and the ring is painted by `.composer:focus-within` on the
    wrapper instead. Assert both halves of that trade, and nothing else.
    """
    assert ":focus-visible" in SHELL
    assert ".composer:focus-within" in SHELL, \
        "the composer delegates its ring to :focus-within — that rule must exist"
    for name, source in (("shell", SHELL), ("conversation", CONV),
                         ("evidence", EVID), ("authority", AUTH)):
        code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
        code = re.sub(r"\.composer textarea:focus\s*\{[^}]*\}", "", code)
        assert "outline: none" not in code, f"{name}: a focus ring was removed outright"


# ── 2. Legal domain separation ────────────────────────────────────────────

LEGAL_VOCABULARY = (
    "authority_class", "authority_class", "source_type", "provenance",
    "statute", "법령", "판례", "근거", "사건", "법무",
)


def test_shared_layers_contain_no_legal_domain_logic() -> None:
    """This is the property that makes Claw absorption cheap: deleting legal/
    must leave a working, domain-free grounded-research surface."""
    offenders: list[str] = []
    for name, source in [
        ("claw-shell.css", SHELL),
        ("claw-conversation.css", CONV),
        ("claw-evidence-card.css", EVID),
        ("claw-shell.js", CSHELL),
        ("claw-evidence.js", CEVID),
    ]:
        for word in ("authority_class", "provenance", "법령", "판례", "사건"):
            # Comments may explain the seam; code may not carry the vocabulary.
            code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
            if word in code:
                offenders.append(f"{name} contains {word!r}")
    assert not offenders, offenders


def test_legal_logic_lives_under_legal_directory() -> None:
    """Authority classification, provenance, and the fail-closed predicate are
    all in legal/, and none of them is re-implemented in the shared layers."""
    for token in ("shouldFailClosed", "provenanceGaps", "sortEvidence", "AUTHORITY_RANK"):
        assert token in AUTH_JS, f"{token} missing from the Legal domain module"
    assert "shouldFailClosed" not in CSHELL
    assert "shouldFailClosed" not in CEVID


def test_evidence_card_has_a_decoration_seam() -> None:
    """The shared card must be extensible without being Legal-aware."""
    assert "setDecorator" in CEVID
    assert "decorator" in CEVID
    decor = DECOR_JS
    for token in ("authorityBadge", "provenanceBlock", "createDecorator"):
        assert token in decor


def test_legal_decorator_supplies_authority_and_provenance() -> None:
    assert 'data-authority' in DECOR_JS or "authorityBadge" in DECOR_JS
    assert "provenanceBlock" in DECOR_JS
    for field in ("document_id", "source_id", "retrieved_at",
                  "effective_date_or_version", "quote_span"):
        assert field in AUTH_JS or field in DECOR_JS, f"provenance field {field} not handled"


# ── 3. Honesty ────────────────────────────────────────────────────────────

def test_no_second_authority_implementation() -> None:
    """#3138 forbids re-implementing shared capability inside B67."""
    all_js = "\n".join(SHARED_JS + LEGAL_JS + [CORPUS])
    for banned in (
        "drive.search_files", "drive.read_file_content",  # Drive READ authority
        "EvidenceGraph", "ClaimEvidenceLink", "VerificationVerdict",  # evidence graph
        "compose_pdf_ocr_fallback", "render_pdf_pages",  # OCR engine
        "OAuth", "client_secret",
    ):
        assert banned not in all_js, f"second authority implemented: {banned}"


def test_page_locators_are_never_presented_as_verified() -> None:
    """Verified audit finding: the evidence graph carries no page/section field.
    Page locators exist only in the document-segment subsystem, so no record
    here may claim a verified page link."""
    assert 'provenance_verified: false' in CORPUS
    assert '"data-verified": "false"' in DECOR_JS
    assert CORPUS.count("provenance_verified: false") >= len(
        re.findall(r"locator_action:", CORPUS)
    ), "every record with a locator must be marked unverified"
    assert "PROVENANCE_NOTE" in CORPUS


def test_legacy_hwp_is_declared_unsupported() -> None:
    """HWPX is not HWP. The UI must never imply legacy .hwp is supported."""
    assert "LEGACY_HWP" not in CORPUS
    assert 'support: "unsupported"' in CORPUS
    assert "미지원" in CORPUS
    # The demo corpus ships a .hwp entry explicitly marked unsupported.
    hwp = re.search(r'name: "구계약_레거시\.hwp".*?support: "(\w+)"', CORPUS, re.S)
    assert hwp, "no legacy .hwp entry in the demo corpus"
    assert hwp.group(1) == "unsupported"


def test_hwpx_is_not_claimed_as_fully_supported() -> None:
    """The shared HWPX module pins HWPX_FULL_SPEC_SUPPORT = NO."""
    for bad in ("HWPX 지원 완료", "HWP/HWPX 지원", "HWPX 완전 지원"):
        assert bad not in CORPUS
        assert bad not in README
    assert "텍스트 추출만" in CORPUS, "HWPX must be scoped to text extraction"


def test_no_live_capability_claims() -> None:
    """The static surface must not imply anything is connected.

    Only USER-VISIBLE strings are scanned. Comments legitimately say things
    like "used to live here", and scanning prose produced a false positive on
    a word that says nothing to a user.
    """
    visible = " ".join(re.findall(r'"([^"\\\n]{2,})"', INDEX + DEMO_JS)) + CORPUS
    for bad in (
        "연결되었습니다", "실제 검색 결과", "실시간 연동", "자동 연결",
        "live", "LIVE",
    ):
        assert bad not in visible, f"live capability claimed in UI copy: {bad}"


def test_demo_state_is_marked_everywhere() -> None:
    assert 'data-b67-preview="synthetic"' in INDEX
    assert "MOCK: true" in CORPUS
    assert "DEMO" in INDEX
    assert "실제 검색" in INDEX or "실제 동작하지 않습니다" in INDEX
    assert "샘플" in CORPUS


def test_format_matrix_matches_source_audit() -> None:
    """PDF OCR exists in KAgent but has no production call site; the binary
    document path fails closed on the deployed Worker without an installed
    isolated parser. The UI must not overstate either."""
    assert "KAgent 구현됨 · 호출 지점 없음" in CORPUS
    assert "Worker 격리 파서 미설치" in CORPUS


def test_fail_closed_is_implemented_not_just_documented() -> None:
    assert "shouldFailClosed" in AUTH_JS
    assert "fail-closed" in DEMO_JS
    assert "검증 가능한 근거를 찾지 못했습니다" in CORPUS
    for action in ("검색 범위 바꾸기", "내 Drive 확인"):
        assert action in CORPUS


def test_no_console_errors_from_bare_identifiers() -> None:
    """Cheap guard against the class of bug that aborted init(): every
    getElementById result used must be assigned to the dom map."""
    init_block = DEMO_JS.split("function init()", 1)[1]
    ids_in_markup = set(re.findall(r'id="([\w-]+)"', INDEX))
    for found in re.findall(r'document\.getElementById\("([\w-]+)"\)', init_block):
        assert found in ids_in_markup, f"getElementById({found!r}) has no matching element"


def test_store_drives_rendering() -> None:
    """A handler that only calls store.set() must still re-render, otherwise a
    click silently does nothing."""
    assert "store.subscribe" in DEMO_JS
    assert "applyState" in DEMO_JS


def test_idempotent_class_writes() -> None:
    """DOMTokenList.remove() calls setAttribute, which fires a mutation record
    even when the value is unchanged. An unconditional remove() inside a class
    MutationObserver deadlocks the renderer — this surface hit exactly that."""
    assert "classList.remove(\"sidebar-open\")" in DEMO_JS
    guard = DEMO_JS.split('function syncSidebar()', 1)[1].split("function", 1)[0]
    assert "classList.contains(\"sidebar-open\")" in guard, \
        "class write must be guarded so the observer cannot re-trigger itself"
    assert "syncing" in guard, "syncSidebar must be re-entrancy guarded"


# ── 4. README contract ────────────────────────────────────────────────────

def test_readme_documents_the_honest_matrix() -> None:
    if not README:
        pytest.skip("README.md not written yet")
    for required in (
        "3138", "Claw", "MOCK", "NOT WIRED", "UNSUPPORTED",
        "grounding", "evidence", "Drive", "OCR", "HWPX",
    ):
        assert required in README, f"README does not document {required!r}"


def test_readme_has_run_and_verify_instructions() -> None:
    if not README:
        pytest.skip("README.md not written yet")
    assert "serve.py" in README
    assert "verify_browser.py" in README
    assert "verify_visual.py" in README


def test_no_unsafe_dom_sinks() -> None:
    """No innerHTML anywhere: every string here is sample or backend data, so an
    HTML sink would be a markup-injection surface for no benefit."""
    for name, source in (("claw-shell.js", CSHELL), ("claw-evidence.js", CEVID),
                         ("legal-authority.js", AUTH_JS), ("legal-demo.js", DEMO_JS),
                         ("legal-evidence-provenance.js", DECOR_JS),
                         ("demo-corpus.js", CORPUS)):
        code = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
        assert "innerHTML" not in code, f"{name} uses an innerHTML sink"


def test_no_window_confirm() -> None:
    """Banned repo-wide; this surface has real recovery actions instead."""
    for source in (CSHELL, CEVID, AUTH_JS, DEMO_JS, DECOR_JS):
        assert "window.confirm" not in source


# ── 5. Legal-accuracy guards (CENTRAL review, PR #3161) ──────────────────

def test_demo_corpus_uses_no_real_statute_identifier() -> None:
    """A legal product must not pair a REAL statute identifier with invented
    text. `민법 제581조` is a real Korean Civil Code article; rendering it with
    synthetic content teaches the reader that a confident-looking citation is
    cheap, which is the exact failure this product exists to prevent.

    Official-looking sample records must therefore be marked fictional.
    """
    # No real Korean statute names.
    for law in ("민법", "상법", "형법", "민사소송법", "형사소송법",
                "자유토지법", "부동산", "근로기준법"):
        assert law not in CORPUS, f"real statute name {law!r} in the demo corpus"

    # No real article-number shape attached to official records.
    for m in re.finditer(r"제\s?\d{2,4}\s?조", CORPUS):
        ctx = CORPUS[max(0, m.start() - 220):m.start() + 40]
        assert "가상" in ctx, f"article-shaped identifier {m.group(0)!r} is not marked fictional"

    # No real official publisher implied for a mock source.
    for publisher in ("국가법령정보센터", "법제처"):
        assert publisher not in CORPUS, f"real official publisher {publisher!r} implied"

    # Every official record must be explicitly flagged fictional.
    for block in re.findall(r"\{\s*n: \d+,\s*source_type: \"official\".*?\n    \}", CORPUS, re.S):
        assert "fictional: true" in block, "an official sample record is not flagged fictional"
        assert "official://" not in block, "a fictional record must not use an official:// ref"


def test_state_is_the_single_routing_authority() -> None:
    """CENTRAL BLOCKER 4: `state` and `scope` were two authorities that
    drifted. There must be no `scope` field on the store at all, and title /
    scope chip / evidence must all be derived from `state`."""
    store_block = DEMO_JS.split("createStore({", 1)[1].split("});", 1)[0]
    assert "scope:" not in store_block, "the store still holds a second `scope` authority"
    assert "scopeForState" in DEMO_JS
    assert "titleForState" in DEMO_JS
    # No handler may pass `scope` into applyState.
    for m in re.finditer(r"applyState\(\{[^}]*\}\)", DEMO_JS):
        assert "scope" not in m.group(0), f"applyState still receives a scope: {m.group(0)}"


def test_scope_chips_have_a_single_handler_path() -> None:
    """CENTRAL ADD-2: the chips had both a per-button onClick and a delegated
    handler, so one click could render twice with a stale value in between."""
    scope_block = DEMO_JS.split("var chips = el(\"div\"", 1)[1].split("});", 1)[0]
    assert "onClick" not in scope_block, "scope chips still carry a per-button onClick"
    assert "dom.conversation.addEventListener" in DEMO_JS
    # Every scope state change must funnel through the one delegated path.
    assert DEMO_JS.count(".claw-chip[data-value]") == 1


def test_evidence_open_follows_the_viewport() -> None:
    """CENTRAL BLOCKER 2: a citation opened the mobile sheet on desktop too."""
    assert "function openEvidence" in DEMO_JS
    open_block = DEMO_JS.split("function openEvidence", 1)[1].split("\n  }", 1)[0]
    assert "isSheetViewport()" in open_block
    assert "drawerOpen: true" in open_block
    assert "drawerOpen: false" in open_block
    # No citation may hardcode the sheet open any more.
    assert "drawerOpen: true" not in DEMO_JS.split("openEvidence", 1)[0]


def test_desktop_sidebar_is_never_inert() -> None:
    """CENTRAL BLOCKER 1: the visible desktop sidebar was permanently inert."""
    sync = DEMO_JS.split("function syncSidebar()", 1)[1].split("\n  }", 1)[0]
    assert "if (!mobile)" in sync
    desktop_block = sync.split("if (!mobile)", 1)[1].split("} else", 1)[0]
    assert "dom.sidebar.inert = false" in desktop_block
    assert "dom.mainPanel.inert = false" in desktop_block
    # The old derived form must be gone.
    assert "dom.sidebar.inert = !open" not in sync


def test_drive_connection_filters_evidence() -> None:
    """CENTRAL BLOCKER 3: Drive evidence reappeared while disconnected."""
    fn = DEMO_JS.split("function evidenceForState", 1)[1].split("\n  }", 1)[0]
    assert "driveConnected" in fn
    assert 'source_type !== "drive"' in fn, "Drive records are not filtered when disconnected"
    # Every call site must pass the connection state. Comments are stripped
    # first: this file discusses evidenceForState() in prose. The call
    # expression is read to the end of its statement rather than to the first
    # ')', because arguments contain nested calls (store.get().driveConnected).
    code = re.sub(r"/\*.*?\*/", "", DEMO_JS, flags=re.S)
    for m in re.finditer(r"(?<![\w])evidenceForState\(", code):
        tail = code[m.start():m.start() + 140]
        statement = re.split(r"[;\n]", tail)[0]
        if statement.startswith("evidenceForState(stateId"):  # the definition
            continue
        assert "driveConnected" in statement or "driveAfter" in statement, \
            f"evidenceForState called without the connection state: {statement[:90]}"
    assert "driveRequired" in DEMO_JS


def test_composer_uses_form_submit() -> None:
    """CENTRAL review comment: the send button is type=submit inside a form, so
    the form submit event must be the canonical path with preventDefault()."""
    fn = CSHELL.split("function bindComposer", 1)[1]
    assert "form.addEventListener(\"submit\"" in fn
    assert "event.preventDefault()" in fn
    # No click handler on the submit button any more.
    assert "sendButton.addEventListener(\"click\"" not in fn
    # IME composition must not submit.
    assert "isComposing" in fn
    assert "event.shiftKey" in fn, "Shift+Enter must not submit"
    assert 'if (event.key !== "Enter") return;' in fn
    assert "dom.composerForm," in DEMO_JS, "the composer must bind the form, not just the button"


def test_no_chinese_characters_in_user_visible_korean() -> None:
    """A stray CJK ideograph in Korean copy (출처 was written 出处) is a typo
    that no functional test would catch."""
    for name, source in (("demo-corpus.js", CORPUS), ("legal-demo.js", DEMO_JS)):
        body = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
        for ch in ("出处", "证拠", "证据"):
            assert ch not in body, f"{name} contains the Chinese form {ch!r}"
    assert "출처를 붙입니다" in DEMO_JS
    assert "샘플 위치" in DEMO_JS


# ── 6. CENTRAL round-2 contracts (#3161) ─────────────────────────────────

def test_sidebar_has_one_open_and_one_close_path() -> None:
    """CENTRAL BLOCKER A: the three close paths (Escape, ×, scrim) each removed
    the class and re-synced inert state but none closed the focus trap, so the
    drawer could look closed while a document-level keydown listener stayed
    installed. Every close path must route through one function."""
    assert "function closeSidebar" in DEMO_JS
    assert "function openSidebar" in DEMO_JS

    close = DEMO_JS.split("function closeSidebar", 1)[1].split("\n  }", 1)[0]
    assert "traps.sidebar.close()" in close, "closeSidebar must release the trap"
    assert "classList.remove" in close

    # No ad-hoc sidebar teardown may survive anywhere in the file.
    code = re.sub(r"/\*.*?\*/", "", DEMO_JS, flags=re.S)
    stray = [m for m in re.finditer(r'classList\.remove\("sidebar-open"\)', code)]
    # Exactly the two allowed sites: closeSidebar() and the idempotent
    # viewport-collapse guard inside syncSidebar().
    assert len(stray) == 2, f"sidebar teardown happens in {len(stray)} places; route through closeSidebar()"

    for handler in ("traps.sidebar = ", "dom.sidebarClose.addEventListener",
                    "dom.sidebarScrim.addEventListener"):
        idx = DEMO_JS.index(handler)
        block = DEMO_JS[idx:idx + 400]
        assert "closeSidebar()" in block, f"{handler} does not route through closeSidebar()"

    # The breakpoint collapse must also release the trap.
    assert "closeSidebar()" in DEMO_JS.split('addEventListener("change"', 1)[1][:400]


def test_web_is_a_real_routing_state() -> None:
    """CENTRAL BLOCKER B: the 웹 chip was visible but collapsed to 통합 on click,
    because the handler mapped anything that was not official/drive to unified."""
    assert "var ROUTABLE_STATES" in DEMO_JS
    block = DEMO_JS.split("var ROUTABLE_STATES", 1)[1].split(";", 1)[0]
    for st in ("unified", "official", "drive", "web"):
        assert f'"{st}"' in block, f"{st} is not a routable state"
    assert 'case "web": return "웹";' in DEMO_JS, "web has no title"
    ev = DEMO_JS.split("function evidenceForState", 1)[1].split("\n  }", 1)[0]
    assert 'case "web"' in ev and 'source_type === "web"' in ev, "web has no evidence set"
    # The scope handler must not hardcode an official/drive allowlist any more.
    handler = DEMO_JS.split("dom.conversation.addEventListener", 1)[1][:500]
    assert "ROUTABLE_STATES" in handler, "the scope click handler still collapses web to unified"


def test_every_sidebar_close_path_goes_through_one_routine() -> None:
    """CENTRAL blocker 1: a second close path is how the trap outlives the drawer.

    The behaviour is covered in a browser at mobile width; this pins the
    STRUCTURE, so a future edit cannot reintroduce a path that removes the open
    class (or releases the trap) without going through the one close routine.
    """
    demo = DEMO_JS
    assert demo.count("function closeSidebar()") == 1, "there must be exactly one close routine"

    # Every way the user (or the viewport) can close the drawer routes into it.
    for fragment in (
        # the focus trap's Escape
        "traps.sidebar = global.ClawShell.createFocusTrap(dom.sidebar, function () {" + chr(10) + "      closeSidebar();",
        # the × control
        'dom.sidebarClose.addEventListener("click", function () { closeSidebar(); });',
        # the scrim
        'dom.sidebarScrim.addEventListener("click", function () { closeSidebar(); });',
        # the hamburger toggle, when already open
        "if (sidebarIsOpen()) closeSidebar();",
        # crossing the breakpoint while open
        'if (!window.matchMedia("(max-width: 920px)").matches) closeSidebar();',
    ):
        assert fragment in demo, f"close path bypasses closeSidebar(): {fragment}"

    # The open class is removed in exactly two places: the close routine, and
    # the sync pass that only runs inside it behind the `syncing` guard.
    removals = [line for line in demo.splitlines() if 'classList.remove("sidebar-open")' in line]
    assert len(removals) == 2, f"unexpected number of class removals: {removals}"

    # inert/aria sync and the trap release stay with the one routine + the sync.
    assert "traps.sidebar.close()" in demo
    assert 'dom.menuButton.setAttribute("aria-expanded"' in demo
    assert "dom.sidebarScrim.hidden = !open;" in demo


def test_every_scope_has_a_grounded_answer() -> None:
    """CENTRAL BLOCKER C: one global answer citing [1][2][3][4] could not be
    grounded in `official` ([4]) or `drive` ([1][2][3]), so both intended result
    states silently fell into fail-closed."""
    assert "var ANSWERS = {" in CORPUS
    assert "SAMPLE_ANSWER = ANSWERS.unified" in CORPUS
    for scope in ("unified", "official", "drive", "web"):
        assert f"    {scope}: {{" in CORPUS, f"no demo answer for scope {scope}"
    assert "Demo.ANSWERS[scopeForState(state.state)]" in DEMO_JS, \
        "the conversation does not select the scope's answer"

    # The gate itself must survive — this is the part CENTRAL told us to keep.
    assert "function citationsResolve" in DEMO_JS
    guard = DEMO_JS.split("if (!citationsResolve", 1)[1][:200]
    assert "renderFailClosed" in guard, "the citation-integrity gate was weakened"


def test_scope_answers_only_cite_their_own_evidence() -> None:
    """Statically cross-check each answer's citations against its evidence set."""
    by_type: dict[str, set[int]] = {}
    # Parse the record list as n/source_type pairs.
    records = re.findall(r"n: (\d+),\s*source_type: \"(\w+)\"", CORPUS)
    assert records, "no evidence records parsed from the corpus"
    for n, t in records:
        by_type.setdefault(t, set()).add(int(n))
    all_nums = {int(n) for n, _ in records}
    by_type["unified"] = all_nums

    for scope, expect in (("official", "official"), ("drive", "drive"), ("web", "web"),
                          ("unified", "unified")):
        block = CORPUS.split(f"    {scope}: {{", 1)[1]
        block = block.split("\n    },", 1)[0]
        cited = {int(x) for x in re.findall(r"\{ cite: (\d+) \}", block)}
        declared = {int(x) for x in re.findall(r"evidence_nums: \[([^\]]*)\]", block)[0].split(",") if x.strip()}
        allowed = by_type[expect]
        if cited != declared:
            pytest.fail(f"{scope}: paragraphs cite {sorted(cited)} but evidence_nums says {sorted(declared)}")
        if not cited:
            pytest.fail(f"{scope}: answer cites nothing")
        if not cited <= allowed:
            pytest.fail(f"{scope}: cites {sorted(cited - allowed)} outside its evidence set {sorted(allowed)}")


def test_web_answer_states_its_secondary_limit() -> None:
    """The web corpus is secondary-only, and the limit must be in the answer
    body so it survives a screenshot of the answer alone."""
    block = CORPUS.split("    web: {", 1)[1].split("\n    }", 1)[0]
    for phrase in ("2차자료", "참고자료", "단독 사용하지 마십시오"):
        assert phrase in block, f"web answer does not state {phrase!r}"


def test_authority_ordering_is_actually_applied() -> None:
    """AUTHORITY_RANK/sortEvidence was documented as a contract but the renderer
    received raw array order, so a secondary source could sit above official
    primary authority."""
    assert "AUTHORITY_RANK" in AUTH_JS
    assert "function sortEvidence" in AUTH_JS
    assert "Legal.sortEvidence(records)" in DEMO_JS, \
        "sortEvidence is documented but never applied in render"
    # Ordering must not renumber records: the [n] identity must survive.
    sort_fn = AUTH_JS.split("function sortEvidence", 1)[1].split("\n  }", 1)[0]
    assert "a.n - b.n" in sort_fn, "the tie-break must keep the original evidence number"


def test_legal_authority_rank_orders_all_four_classes() -> None:
    rank_block = AUTH_JS.split("var AUTHORITY_RANK", 1)[1].split("};", 1)[0]
    order = re.findall(r"(\w+):", rank_block)
    assert order == ["primary", "party", "internal", "secondary"], \
        f"authority ranking order changed: {order}"


# ── 7. Persistable-state authority (CENTRAL final blocker) ───────────────

def test_persistable_states_are_derived_not_hand_maintained() -> None:
    """The persistable set must be DERIVED from the routable + review lists.

    It used to be the review-switcher list, which made `web` — a real routable
    scope with no top-bar chip — persistable but unrestorable, so it silently
    reverted to 통합 on reload. Deriving it means a new routable scope is
    restorable the moment it becomes routable.
    """
    assert "var PERSISTABLE_STATES = ROUTABLE_STATES.concat(" in DEMO_JS, \
        "PERSISTABLE_STATES must be derived, not a hand-written literal"
    assert "var PERSISTABLE_STATES = [" not in DEMO_JS, \
        "PERSISTABLE_STATES is still a hand-maintained list"
    assert "REVIEW_STATES.map" in DEMO_JS, \
        "PERSISTABLE_STATES must also absorb the review-only states"


def test_no_state_is_persistable_but_unrestorable() -> None:
    """The invariant, checked structurally: every routable state and every
    review state must be inside the persistable set, and both persist() and
    restore() must validate through the single isPersistable() predicate."""
    # A routable state is restorable the moment it is routable.
    routable = DEMO_JS.split("var ROUTABLE_STATES = [", 1)[1].split("]", 1)[0]
    routable_ids = re.findall(r'"([\w-]+)"', routable)
    assert "web" in routable_ids, "web must be a routable state"

    review_block = DEMO_JS.split("var REVIEW_STATES = [", 1)[1].split("\n  ];", 1)[0]
    review_ids = re.findall(r'id: "([\w-]+)"', review_block)
    assert review_ids, "the review switcher list is empty"

    # The derived expression must union both, de-duplicating the shared ones.
    derived = DEMO_JS.split("var PERSISTABLE_STATES = ", 1)[1].split("\n\n", 1)[0]
    assert "ROUTABLE_STATES.concat(" in derived
    assert 'ROUTABLE_STATES.indexOf(id) === -1' in derived, \
        "the shared ids must be de-duplicated or a routable state could be missed"

    # Both write and read validate through the one predicate.
    persist = DEMO_JS.split("function persist()", 1)[1].split("\n  }", 1)[0]
    restore = DEMO_JS.split("function restore()", 1)[1].split("\n  }", 1)[0]
    assert "isPersistable(stateId)" in persist, "persist must not write an unrestorable state"
    assert "isPersistable(saved)" in restore, "restore must validate via isPersistable"
    # The old conflation must be gone.
    assert "STATES.some(" not in restore, "restore still validates against the review list"
    assert "REVIEW_STATES.some(" not in restore


def test_review_switcher_is_not_the_state_authority() -> None:
    """The top-bar switcher is a UI affordance; it must not be used to decide
    what a valid state is. `web` legitimately has no chip."""
    assert "var REVIEW_STATES = [" in DEMO_JS
    assert "var PERSISTABLE_STATES" in DEMO_JS
    # persist/restore must not reference the review list at all.
    for fn in ("function persist()", "function restore()"):
        block = DEMO_JS.split(fn, 1)[1].split("\n  }", 1)[0]
        assert "REVIEW_STATES" not in block, f"{fn} still depends on the review switcher"
