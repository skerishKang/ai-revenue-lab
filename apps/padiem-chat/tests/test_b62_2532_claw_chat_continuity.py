"""#2532 KILO2 — Claw ↔ Chat visual continuity contracts (static, bounded).

Owner decision: Claw is a special working mode inside Padiem Chat, not a
separate app. These contracts lock the accepted slice:

- CLAW_BOTTOM_COMPOSER_VISIBLE: the shared composer stays visible in
  data-state="claw"; only the chat conversation column yields the canvas.
- CLAW_MESSAGE_INPUT_PRIMARY: #messageInput is the Claw request input;
  the old hero textarea (#clawRequestText) is gone and Enter in the
  composer routes to the preview flow.
- The workspace stacks above the fixed glass portrait layer (z-index).
- Contrast regressions from #2114 stay fixed (no stacked opacity, glass
  kicker uses the chat eyebrow ink).
- Typography reuses the chat scale (title/copy/body parity).
"""

from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
WORKSPACE_CSS = (STATIC / "claw-workspace.css").read_text(encoding="utf-8")
GLASS_CSS = (STATIC / "padiem-glass.css").read_text(encoding="utf-8")
PORTRAIT_CSS = (STATIC / "padiem-glass-portrait.css").read_text(encoding="utf-8")


# ── CLAW_BOTTOM_COMPOSER_VISIBLE ─────────────────────────────────────────────


def test_claw_bottom_composer_visible() -> None:
    # The composer is no longer hidden by the claw state.
    assert '.app-shell[data-state="claw"] .composer-wrap' not in WORKSPACE_CSS
    # R1: the shared conversation column stays VISIBLE in manual Claw — it is not
    # display:none. Only the generic chat empty-state is replaced.
    conv_rule = WORKSPACE_CSS.split('.app-shell[data-state="claw"] .conversation {', 1)[1].split("}", 1)[0]
    assert "display: block" in conv_rule
    assert "display: none" not in conv_rule
    empty_rule = WORKSPACE_CSS.split('.app-shell[data-state="claw"] .conversation .empty-state {', 1)[1].split("}", 1)[0]
    assert "display: none" in empty_rule
    # The workspace chrome yields to the conversation in manual view...
    manual_rule = WORKSPACE_CSS.split('.claw-workspace[data-view="manual"] {', 1)[1].split("}", 1)[0]
    assert "display: none" in manual_rule
    # ...and only the inbox (non-manual) subview hides the conversation.
    inbox_rule = WORKSPACE_CSS.split('.claw-workspace:not([data-view="manual"]) ~ .conversation {', 1)[1].split("}", 1)[0]
    assert "display: none !important" in inbox_rule
    # The intake form now lives inside the composer wrap, above #composerForm.
    wrap = INDEX.split('class="composer-wrap"', 1)[1]
    assert 'class="claw-mode-bar" id="clawManualForm"' in wrap
    assert wrap.index('class="claw-mode-bar"') < wrap.index('class="composer" id="composerForm"')
    # And it is a sibling, never nested inside the chat composer form.
    composer_form = wrap.split('class="composer" id="composerForm"', 1)[1].split("</form>", 1)[0]
    assert "clawManualForm" not in composer_form


# ── CLAW_MESSAGE_INPUT_PRIMARY ───────────────────────────────────────────────


def test_claw_message_input_primary() -> None:
    assert 'id="clawRequestText"' not in INDEX
    assert "clawRequestText" not in APP
    # Composer submit routes to the Claw preview flow while data-state="claw".
    assert 'shell.dataset.state === "claw" && clawManualForm' in APP
    assert "clawManualForm.requestSubmit()" in APP
    # Preview and execute read the composer value; the API contract is unchanged.
    assert APP.count('const body = (input.value || "").trim();') == 2
    assert 'fetch("/api/claw/manual-intake/preview"' in APP
    assert 'fetch("/api/claw/manual-intake/execute"' in APP
    # Placeholder/limit sync for the claw mode, re-applied on locale change.
    assert 'function syncComposerForClaw' in APP
    assert 'localeOr("claw-request-placeholder"' in APP
    assert "syncComposerForClaw(shell.dataset.state === \"claw\")" in APP


# ── stacking above the fixed portrait layer ──────────────────────────────────


def test_workspace_stacks_above_portrait_layer() -> None:
    block = WORKSPACE_CSS.split('.app-shell[data-state="claw"] .claw-workspace', 1)[1]
    block = block.split("}", 1)[0]
    assert "position: relative" in block
    assert "z-index: 2" in block
    assert 'html[data-theme="padiem-glass"] .claw-workspace' in PORTRAIT_CSS


# ── contrast regression guards ───────────────────────────────────────────────


def test_no_stacked_opacity_on_claw_surfaces() -> None:
    assert "opacity: 0.7" not in WORKSPACE_CSS
    assert "opacity: 0.85" not in WORKSPACE_CSS
    disabled = WORKSPACE_CSS.split(".claw-disabled-control", 1)[1].split("/*", 1)[0]
    assert "opacity" not in disabled


def test_glass_kicker_uses_chat_eyebrow_ink() -> None:
    eyebrow = GLASS_CSS.split("html[data-theme=\"padiem-glass\"] .eyebrow {", 1)[1].split("}", 1)[0]
    kicker = GLASS_CSS.split('html[data-theme="padiem-glass"] .claw-workspace-kicker {', 1)[1].split("}", 1)[0]
    assert "#334a5b" in eyebrow
    assert "#334a5b" in kicker


def test_glass_mode_bar_matches_composer_surface() -> None:
    mode_bar = GLASS_CSS.split('html[data-theme="padiem-glass"] .claw-mode-bar {', 1)[1].split("}", 1)[0]
    assert "rgba(255, 255, 255, .64)" in mode_bar
    assert "backdrop-filter" in mode_bar


# ── typography parity with chat ──────────────────────────────────────────────


def test_typography_reuses_chat_scale() -> None:
    title = WORKSPACE_CSS.split(".claw-workspace-title", 1)[1].split("}", 1)[0]
    assert "clamp(26px, 4vw, 34px)" in title
    assert "font-weight: 770" in title
    assert "letter-spacing: -0.045em" in title
    body = WORKSPACE_CSS.split(".claw-result-body {", 1)[1].split("}", 1)[0]
    assert "font-size: 16px" in body


def test_workspace_reserves_room_for_fixed_composer() -> None:
    layout = WORKSPACE_CSS.split("/* ── Workspace layout", 1)[1]
    assert "padding: clamp(20px, 5vh, 48px) 0 280px" in layout.split("}", 1)[0]
    mobile = WORKSPACE_CSS.split("@media (max-width: 720px)", 1)[1]
    assert "padding: 16px 0 260px" in mobile


# ── R2: Claw result surfaces render inside the shared conversation column ─────


def _conversation_inner() -> str:
    return INDEX.split('class="conversation"', 1)[1].split('class="composer-wrap"', 1)[0]


def _workspace_inner() -> str:
    return INDEX.split('id="clawWorkspace"', 1)[1].split('class="conversation"', 1)[0]


def test_claw_surfaces_render_in_conversation_not_workspace() -> None:
    # R2: request echo, result, memory review and approved memory read as part of
    # the Chat thread — they live between the conversation and composer markers,
    # never inside the workspace canvas again.
    conv = _conversation_inner()
    ws = _workspace_inner()
    for marker in (
        'id="clawRequestEcho"',
        'id="clawResultArea"',
        'id="clawMemoryReview"',
        'id="clawApprovedMemory"',
    ):
        assert marker in conv, marker
        assert marker not in ws, marker


def test_claw_status_lives_in_mode_bar_not_conversation() -> None:
    # The single canonical status region sits in the compact mode bar (composer
    # area), keeping the conversation's polite live region free of a nested one.
    assert 'id="clawStatus"' not in _conversation_inner()
    wrap = INDEX.split('class="composer-wrap"', 1)[1]
    assert 'id="clawStatus"' in wrap


def test_request_echo_is_plain_user_message() -> None:
    # The echo reuses the message primitives (no admin-form framing, no source
    # label — see also #2483 which bans "요청 원문:" / "Source text" in app.js).
    # It must NOT carry the generic .user-message class: the shared gutter QA
    # selects ".user-message" / ".user-message .message-bubble" in strict mode.
    conv = _conversation_inner()
    assert 'class="message claw-request-echo"' in conv
    assert 'class="message user-message claw-request-echo"' not in conv
    assert "요청 원문:" not in conv
    assert "Source text" not in conv


# ── R3: disabled capabilities demote to a collapsed disclosure ────────────────


def test_disabled_controls_are_collapsed_disclosure() -> None:
    conv = _conversation_inner()
    assert "<details" in conv and 'class="claw-disabled-controls"' in conv
    assert "<summary" in conv
    assert conv.count('class="claw-disabled-control"') == 5
    # no longer a top-level block inside the workspace canvas
    assert 'class="claw-disabled-controls"' not in _workspace_inner()


# ── R4: auth-unavailable copy is separated from re-login copy ─────────────────


def test_auth_unavailable_copy_distinct_from_relogin() -> None:
    locale = (STATIC / "locale.js").read_text(encoding="utf-8")
    # KO + EN parity for the new key.
    assert locale.count('"claw-error-auth-unavailable"') == 2
    assert locale.count('"claw-error-auth-needed"') == 2
    # The unavailable copy must NOT tell the user to sign in again; the re-login
    # copy must.
    unavailable_ko = locale.split('"claw-error-auth-unavailable":', 1)[1].split("\n", 1)[0]
    needed_ko = locale.split('"claw-error-auth-needed":', 1)[1].split("\n", 1)[0]
    assert "다시 로그인" not in unavailable_ko
    assert "다시 로그인" in needed_ko
    # safeClawErrorMessage routes scope/identity failures to the unavailable key
    # and 401 / auth_required to the re-login key — two distinct branches.
    scope_line = next(l for l in APP.splitlines() if "workspace_scope_unavailable" in l)
    assert "claw-error-auth-unavailable" in scope_line
    assert "claw-error-auth-needed" not in scope_line
    auth_line = next(l for l in APP.splitlines() if 'code === "auth_required"' in l)
    assert "claw-error-auth-needed" in auth_line
    assert "claw-error-auth-unavailable" not in auth_line
