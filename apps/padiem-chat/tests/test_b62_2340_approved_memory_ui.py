from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APP_JS = ROOT / "apps/padiem-chat/static/app.js"
INDEX_HTML = ROOT / "apps/padiem-chat/static/index.html"
CSS = ROOT / "apps/padiem-chat/static/claw-workspace.css"


def _load_app_js():
    source = APP_JS.read_text(encoding="utf-8")
    return source


def test_approved_memory_ui_references_exist() -> None:
    source = _load_app_js()
    assert "clawApprovedMemory" in source
    assert "clawApprovedRefresh" in source
    assert "clawApprovedLoading" in source
    assert "clawApprovedError" in source
    assert "clawApprovedList" in source
    assert "clawApprovedEmpty" in source
    assert "loadApprovedMemoryList" in source
    assert "loadApprovedMemoryDetail" in source
    assert "approveApprovedMemory" in source
    assert "rejectApprovedMemory" in source


def test_approved_memory_api_endpoints() -> None:
    source = _load_app_js()
    assert '"/api/claw/memory"' in source
    assert '"/api/claw/memory/approve"' in source
    assert '"/api/claw/memory/reject"' in source


def test_approved_memory_public_safe_projection_only() -> None:
    source = _load_app_js()
    assert "user_id" not in source
    assert "owner" not in source


def test_approved_memory_no_raw_prompt_or_secret() -> None:
    source = _load_app_js()
    lines = source.split("\n")
    for token in ("raw_prompt", "provider_secret", "object_key"):
        for line in lines:
            if token in line and "memory" in line:
                assert False, f"{token} found in memory context: {line}"


def test_approved_memory_explicit_approval_required() -> None:
    source = _load_app_js()
    assert "approved: true" in source


def test_approved_memory_reject_no_durable_row() -> None:
    source = _load_app_js()
    assert '"/api/claw/memory/reject"' in source


def test_approved_memory_loading_state() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert "clawApprovedLoading" in html
    source = _load_app_js()
    assert "clawApprovedLoading" in source


def test_approved_memory_error_state() -> None:
    source = _load_app_js()
    assert "clawApprovedError" in source
    assert "setApprovedMemoryStatus" in source


def test_approved_memory_retry_action() -> None:
    source = _load_app_js()
    assert "clawApprovedRefresh" in source
    assert "loadApprovedMemoryList" in source


def test_approved_memory_keyboard_focus() -> None:
    source = _load_app_js()
    assert "focus" in source


def test_approved_memory_non_disclosing_detail() -> None:
    source = _load_app_js()
    assert "safeClawErrorMessage" in source


def test_html_has_approved_memory_section() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert "clawApprovedMemory" in html
    assert "clawApprovedMemoryTitle" in html
    assert "clawApprovedList" in html
    assert "clawApprovedRefresh" in html


def test_css_has_approved_memory_styles() -> None:
    css = CSS.read_text(encoding="utf-8")
    assert ".claw-approved-memory" in css
    assert ".claw-approved-card" in css
    assert ".claw-approved-detail" in css
    assert ".claw-approved-error" in css


def test_gate_is_migration_011_only() -> None:
    workflow = ROOT / ".github/workflows/b62-claw-d1-migration-011-gate.yml"
    helper = ROOT / ".github/scripts/b62_d1_migration_011_schema.py"
    workflow_text = workflow.read_text(encoding="utf-8")
    helper_text = helper.read_text(encoding="utf-8")
    for token in ("008", "009", "010"):
        assert token not in workflow_text
        assert token not in helper_text


if __name__ == "__main__":
    test_approved_memory_ui_references_exist()
    test_approved_memory_api_endpoints()
    test_approved_memory_public_safe_projection_only()
    test_approved_memory_no_raw_prompt_or_secret()
    test_approved_memory_explicit_approval_required()
    test_approved_memory_reject_no_durable_row()
    test_approved_memory_loading_state()
    test_approved_memory_error_state()
    test_approved_memory_retry_action()
    test_approved_memory_keyboard_focus()
    test_approved_memory_non_disclosing_detail()
    test_html_has_approved_memory_section()
    test_css_has_approved_memory_styles()
    test_gate_is_migration_011_only()
    print("B62_APPROVED_MEMORY_UI_TESTS=PASS")