"""#2299 KILO2 independent lane — Claw manual-intake MVP usability pass.

Focused, network-free, static-contract tests only. No backend, P01, Engine,
Cloudflare or browser-runtime mutation.

Covers #2299 acceptance:
- Claw first-class entry + manual-intake primary CTA
- Four actions clear
- Preview vs execute distinction (no technical jargon)
- Duplicate-submit guard / bounded states
- Result readability (textContent, separated from input, focusable)
- Safe artifact action (document_id / filename only, no bytes/keys)
- User-safe error copy (no provider/internal leak)
- KO/EN parity for touched strings
- Chat/settings/navigation non-regression
"""

from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")
WORKSPACE_CSS = (STATIC / "claw-workspace.css").read_text(encoding="utf-8")


# ── 1 · Claw is first-class, discoverable entry ────────────────────────────


def test_claw_first_class_entry_via_sidebar_workspace() -> None:
    assert 'id="clawNavButton"' in INDEX
    assert 'id="clawWorkspace"' in INDEX
    assert 'class="claw-workspace"' in INDEX
    assert 'shell.dataset.state = "claw"' in APP
    assert '.app-shell[data-state="claw"] .claw-workspace' in WORKSPACE_CSS
    # Chat/composer hidden when Claw owns the canvas
    assert '.app-shell[data-state="claw"] .conversation' in WORKSPACE_CSS
    assert '.app-shell[data-state="claw"] .composer-wrap' in WORKSPACE_CSS
    # Not a dialog anymore
    assert 'id="clawDialog"' not in INDEX
    assert "clawDialog" not in APP


# ── 2 · Manual intake is the primary CTA ───────────────────────────────────


def test_manual_intake_is_the_primary_cta() -> None:
    assert 'id="clawManualForm"' in INDEX
    assert 'id="clawRequestText"' in INDEX
    assert 'class="claw-intake-hero"' in INDEX
    assert 'data-locale-key="claw-field-request"' in INDEX
    # Two action buttons present, with hint text explaining their difference
    assert 'id="clawGenerateBtn"' in INDEX
    assert 'id="clawExecuteButton"' in INDEX
    assert 'data-locale-key="claw-btn-generate"' in INDEX
    assert 'data-locale-key="claw-btn-execute"' in INDEX
    assert 'id="clawActions"' not in INDEX  # no surprise containers
    assert "claw-workspace-help" in INDEX or "claw-actions-hint" in INDEX
    assert 'data-locale-key="claw-workspace-help"' in INDEX
    assert 'data-locale-key="claw-actions-hint"' in INDEX


# ── 3 · Four actions clearly available ─────────────────────────────────────


def test_four_actions_clear_and_understandable() -> None:
    assert INDEX.count('data-claw-action=') >= 4
    for action in ('quote', 'order', 'reply', 'summary'):
        assert f'data-claw-action="{action}"' in INDEX
    # Visible chips with locale keys, not hidden carrier only
    assert 'class="claw-chips" role="group"' in INDEX
    assert 'data-locale-key="claw-chip-quote"' in INDEX
    assert 'data-locale-key="claw-chip-order"' in INDEX
    assert 'data-locale-key="claw-chip-reply"' in INDEX
    assert 'data-locale-key="claw-chip-summary"' in INDEX


# ── 4 · Preview vs execute distinction without jargon ───────────────────────


def test_preview_execute_distinction_without_technical_jargon() -> None:
    # Distinct user-visible phrases for each button and badge
    assert 'data-locale-key="claw-btn-generate"' in INDEX
    assert 'data-locale-key="claw-btn-execute"' in INDEX
    assert 'data-locale-key="claw-result-badge"' in INDEX
    # executed badge is set via JS localeKey switch (no second static element)
    assert "claw-result-badge-run" in LOCALE
    assert '"claw-result-badge-run"' in APP
    # Expanded help/hints that explain without jargon
    assert 'data-locale-key="claw-workspace-help"' in INDEX
    assert 'data-locale-key="claw-actions-hint"' in INDEX
    assert 'data-locale-key="claw-preview-empty-hint"' in INDEX
    assert 'data-locale-key="claw-execute-hint"' in INDEX
    # Code must use distinct badge states and endpoints
    assert 'fetch("/api/claw/manual-intake/preview"' in APP
    assert 'fetch("/api/claw/manual-intake/execute"' in APP
    assert "revealClawCard(preview.title" in APP
    assert "revealClawCard(result.title, true)" in APP
    # No technical jargon leaks into user strings for the hints
    for bad in ("P01", "B14", "Service Binding", "D1", "R2 bucket"):
        assert bad not in LOCALE


# ── 5 · Duplicate-submit guard / guarded primary action ────────────────────


def test_duplicate_submit_guard_and_bounded_states() -> None:
    # Single in-flight flag gates both actions
    assert "clawInFlight" in APP
    assert "setClawButtonsBusy" in APP
    assert "aria-busy" in APP
    assert 'data-claw-state' in INDEX or 'clawStatus' in INDEX or 'claw-status' in WORKSPACE_CSS.lower()
    # Buttons disabled via JS when busy
    assert "clawGenerateBtn" in APP
    assert "clawExecuteButton" in APP
    assert ".disabled = busy" in APP or "disabled = true" in APP
    # CSS treats disabled/blocked state as not-allowed
    assert "cursor: not-allowed" in WORKSPACE_CSS
    # States: idle/submitting/success/failure must exist as data attributes/classes
    assert "setClawAreaState" in APP
    assert '"idle"' in APP or "'idle'" in APP
    assert '"submitting"' in APP or "'submitting'" in APP
    assert '"success"' in APP or "'success'" in APP
    assert '"error"' in APP or "'error'" in APP


# ── 6 · Clear bounded states exist (idle/submitting/success/failure) ───────


def test_idle_submitting_success_failure_states_bounded() -> None:
    assert 'data-claw-state="idle"' in INDEX
    assert "claw-status" in INDEX or "clawStatus" in INDEX
    assert 'role="status"' in INDEX
    assert 'aria-live="polite"' in INDEX
    # Status region exists and is used for all transitions
    assert 'id="clawStatus"' in INDEX
    assert "setClawStatus" in APP
    assert "claw-status-preview-running" in LOCALE
    assert "claw-status-execute-running" in LOCALE
    assert "claw-status-error" in LOCALE


# ── 7 · Result is readable and separated from input ────────────────────────


def test_result_text_is_readable_and_separated_from_input() -> None:
    assert 'id="clawResultArea"' in INDEX
    assert 'id="clawResultCard"' in INDEX
    assert 'id="clawResultPreview"' in INDEX
    assert 'class="claw-result-body"' in INDEX
    # Result region is aria-live with a card, not the same textarea
    assert 'id="clawRequestText"' in INDEX
    assert "max-height: 320px" in WORKSPACE_CSS
    # Safe sink only
    assert "clawResultPreview.textContent =" in APP
    assert "clawResultPreview.innerHTML" not in APP
    assert "clawResultPreview.focus" in APP  # focus moves to result after success


# ── 8 · Artifact descriptor only safe fields, no raw bytes / keys ──────────


def test_safe_artifact_action_without_raw_bytes_or_secrets() -> None:
    # Single handler per button, reading dataset at click time (no per-result leak)
    assert INDEX.count('id="clawResultDocx"') == 1
    assert INDEX.count('id="clawResultOpen"') == 1
    # Download uses /artifact/{documentId} with encoded id, blob, object URL, anchor
    assert "/api/claw/manual-intake/artifact/" in APP
    assert "URL.createObjectURL" in APP
    assert "URL.revokeObjectURL" in APP
    assert "encodeURIComponent(documentId)" in APP or "encodeURIComponent" in APP
    # Only safe descriptor fields rendered in meta
    assert 'id="clawArtifactMeta"' in INDEX
    assert 'id="clawArtifactName"' in INDEX
    assert "is-prominent" in WORKSPACE_CSS
    # No raw bytes / keys / private URLs in static source or locale
    for bad in ("object_key", "r2_key", "privateUrl", "presigned", "bytes", "base64"):
        assert bad not in LOCALE
        # app.js may contain blob/bytes mechanics but must not render private object keys
        if bad in ("object_key", "r2_key", "privateUrl", "presigned"):
            assert bad not in APP
    # Locale artifact label is safe and user-facing only
    assert "claw-artifact-ready" in LOCALE


# ── 9 · Error messages are user-facing, no provider/internal leak ──────────


def test_user_safe_error_copy_without_provider_details() -> None:
    assert "safeClawErrorMessage" in APP or "safeError" in APP or "claw-error" in LOCALE
    # KO/EN error set present
    for key in (
        '"claw-error-empty"',
        '"claw-error-too-large"',
        '"claw-error-invalid"',
        '"claw-error-rate-limited"',
        '"claw-error-generic"',
    ):
        assert key in LOCALE
    # Must not expose provider/internal strings as user error copy
    for bad in ("P01_ENGINE", "b14", "provider_unavailable", "stack", "traceback"):
        assert bad not in LOCALE
    # app.js helper maps raw error codes to locale strings rather than showing raw message
    assert "claw-error-empty" in APP or "safeClawErrorMessage" in APP


# ── 10 · Keyboard / mobile / basic a11y for primary flow ────────────────────


def test_keyboard_mobile_a11y_primary_flow() -> None:
    assert 'role="group" aria-label="Claw 작업 선택"' in INDEX
    # Chips are buttons (keyboard operable), textarea focusable, result aria-live
    assert 'class="claw-chip"' in INDEX
    assert 'id="clawRequestText"' in INDEX
    assert 'aria-live="polite"' in INDEX
    # 16px input avoids iOS zoom, touch targets >=44px
    assert "font-size: 16px" in WORKSPACE_CSS
    assert "min-height: 44px" in WORKSPACE_CSS
    assert "min-height: 48px" in WORKSPACE_CSS
    # Mobile single-column behavior
    assert "@media (max-width:" in WORKSPACE_CSS


# ── 11 · KO/EN parity for touched strings ───────────────────────────────────


def test_ko_en_parity_for_touched_strings() -> None:
    touched = [
        "claw-workspace-help",
        "claw-actions-hint",
        "claw-preview-empty-hint",
        "claw-execute-hint",
        "claw-artifact-ready",
        "claw-status-preview-running",
        "claw-status-execute-running",
        "claw-status-preview-success",
        "claw-status-execute-success",
        "claw-status-error",
        "claw-error-empty",
        "claw-error-too-large",
        "claw-error-invalid",
        "claw-error-rate-limited",
        "claw-error-auth-needed",
        "claw-error-storage",
        "claw-error-generic",
        # existing keys must still have parity
        "claw-btn-generate",
        "claw-btn-execute",
        "claw-result-badge",
        "claw-result-badge-run",
    ]
    for key in touched:
        assert f'"{key}": "' in LOCALE, f"missing key {key}"
        # Each key appears at least twice (ko + en blocks)
        assert LOCALE.count(f'"{key}": "') >= 2, f"no EN parity for {key}"


# ── 12 · Chat / Settings / navigation not regressed ─────────────────────────


def test_chat_settings_nav_not_regressed() -> None:
    assert 'id="newChatButton"' in INDEX
    assert 'id="settingsButton"' in INDEX
    assert 'id="settingsDialog"' in INDEX
    assert 'id="messageInput"' in INDEX
    assert 'id="composerForm"' in INDEX
    assert "settingsButton.addEventListener" in APP or 'getElementById("settingsButton")' in APP
    assert INDEX.count("<h1") == 1
    assert 'class="claw-workspace-title" id="clawWorkspaceTitle"' in INDEX


# ── 13 · No forbidden browser persistence / unsafe sink regression ───────────


def test_no_forbidden_persistence_or_unsafe_sink_regression() -> None:
    for token in ("localStorage", "sessionStorage", "indexedDB", "cookieStore", "caches.open"):
        assert token not in APP
    for sink in ("innerHTML", "outerHTML", "document.write"):
        # claw result section must specifically not use innerHTML
        assert "clawResultPreview.innerHTML" not in APP
        if sink == "document.write":
            assert "document.write" not in APP


# ── 14 · No provider/internal endpoint / secret leak in static ───────────────


def test_no_provider_secret_or_internal_endpoint_in_static() -> None:
    html_and_js = INDEX + "\n" + APP + "\n" + LOCALE
    for bad in (
        "P01_ENGINE_CREDENTIAL",
        "P01_ENGINE_SERVICE",
        "openai_api_key",
        "anthropic_api_key",
        "padiem-ai-engine.internal",
        "api_key",
        "Bearer sk-",
    ):
        assert bad not in html_and_js


# ── 15 · Existing navigation shell contract preserved ────────────────────────


def test_sidebar_and_shell_contracts_preserved() -> None:
    assert 'id="sidebar"' in INDEX
    assert 'class="app-shell"' in INDEX
    assert "setNavActive" in APP
    assert 'setAttribute("aria-current"' in APP
