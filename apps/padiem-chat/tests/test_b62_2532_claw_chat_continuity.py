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
    # The conversation column still yields to the workspace.
    rule = WORKSPACE_CSS.split('.app-shell[data-state="claw"] .conversation', 1)[1]
    assert "display: none !important" in rule.split("}", 1)[0]
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
