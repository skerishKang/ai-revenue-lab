"""#2114 ACT-1 — Claw first-class workspace UI contracts (static, bounded).

These guard the design decisions accepted in the ACT-0 review:
- the modal is no longer the primary Claw surface;
- a data-state="claw" workspace replaces it inside the shared shell;
- natural-language input is the hero and is sized to avoid iOS focus zoom;
- results render as a compact card, never a raw inline document;
- document/DOCX affordances stay honestly disabled (no fake success);
- Chat vs Claw navigation exposes aria-current active state.
"""

from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
WORKSPACE_CSS = (STATIC / "claw-workspace.css").read_text(encoding="utf-8")
INTAKE_CSS = (STATIC / "claw-manual-intake.css").read_text(encoding="utf-8")


def test_modal_is_no_longer_the_primary_claw_surface() -> None:
    assert 'id="clawDialog"' not in INDEX
    assert "clawDialog" not in APP
    assert 'id="clawWorkspace"' in INDEX
    # The sidebar button is now a workspace destination, not a dialog trigger.
    claw_button = next(line for line in INDEX.splitlines() if 'id="clawNavButton"' in line)
    assert "aria-controls=\"clawDialog\"" not in claw_button
    assert "aria-haspopup=\"dialog\"" not in claw_button


def test_workspace_is_a_first_class_shell_state() -> None:
    assert 'shell.dataset.state = "claw"' in APP
    assert ".app-shell[data-state=\"claw\"] .claw-workspace" in WORKSPACE_CSS
    # Chat/home canvas is hidden while the Claw workspace owns the panel.
    assert ".app-shell[data-state=\"claw\"] .conversation" in WORKSPACE_CSS
    assert ".app-shell[data-state=\"claw\"] .composer-wrap" in WORKSPACE_CSS


def test_natural_language_input_is_the_hero_and_zoom_safe() -> None:
    assert 'class="claw-intake-hero"' in INDEX
    assert 'id="clawRequestText"' in INDEX
    assert "font-size: 16px" in WORKSPACE_CSS
    # The disclosure fields must not regress to the old 13.6px form controls.
    assert "font-size: 16px" in INTAKE_CSS
    assert "0.85rem" not in INTAKE_CSS


def test_actions_are_optional_overrides_not_mandatory_cards() -> None:
    assert 'class="claw-chips"' in INDEX
    assert INDEX.count('data-claw-action=') >= 4
    assert 'aria-pressed="false"' in INDEX
    # The old mandatory action-card grid is gone.
    assert 'claw-actions-grid' not in INDEX


def test_result_is_a_compact_card_not_raw_inline_document() -> None:
    assert 'id="clawResultCard"' in INDEX
    assert 'id="clawResultKind"' in INDEX
    assert 'class="claw-result-body"' in INDEX
    # The result body is capped and scrollable rather than expanding a full doc.
    assert "max-height: 320px" in WORKSPACE_CSS


def test_document_affordances_stay_honestly_disabled() -> None:
    # No fabricated download/open success: the result actions render disabled.
    assert 'class="claw-result-action" disabled aria-disabled="true"' in INDEX
    # The five coming-soon controls remain present and disabled.
    assert INDEX.count('claw-disabled-control" disabled aria-disabled="true"') == 5


def test_chat_claw_active_navigation_state() -> None:
    assert 'setAttribute("aria-current"' in APP
    assert '#clawNavButton[aria-current="page"]' in WORKSPACE_CSS
    assert '#newChatButton[aria-current="page"]' in WORKSPACE_CSS


def test_primary_touch_targets_are_at_least_44px() -> None:
    assert "min-height: 44px" in WORKSPACE_CSS
    assert "min-height: 48px" in WORKSPACE_CSS  # generate button


def test_workspace_preserves_single_h1_contract() -> None:
    # The canonical accessibility QA uses a strict locator("h1"); the Claw
    # workspace title must not introduce a second h1 alongside the home h1.
    assert INDEX.count("<h1") == 1
    assert 'class="claw-workspace-title" id="clawWorkspaceTitle"' in INDEX
    assert 'aria-labelledby="clawWorkspaceTitle"' in INDEX


def test_preview_endpoint_and_safe_dom_sinks_preserved() -> None:
    assert "/api/claw/manual-intake/preview" in APP
    assert "clawResultPreview.textContent =" in APP
    assert "clawResultPreview.innerHTML" not in APP
    for token in ("localStorage", "sessionStorage", "indexedDB", "cookieStore", "caches.open"):
        assert token not in APP
