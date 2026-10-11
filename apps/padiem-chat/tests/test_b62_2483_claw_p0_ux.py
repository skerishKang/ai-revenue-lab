"""#2483 — bounded Claw P0 UX source contracts.

These checks stay at the static/UI boundary. They prove that shared theme
tokens are used, preview transport failures are retryable errors rather than
synthetic successes, and the approved-memory surface has complete KO/EN copy.
"""

from __future__ import annotations

import re
from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")
WORKSPACE_CSS = (STATIC / "claw-workspace.css").read_text(encoding="utf-8")
INTAKE_CSS = (STATIC / "claw-manual-intake.css").read_text(encoding="utf-8")


APPROVED_MEMORY_KEYS = (
    "claw-approved-kicker",
    "claw-approved-title",
    "claw-approved-tagline",
    "claw-approved-refresh-aria",
    "claw-memory-review-aria",
    "claw-approved-loading",
    "claw-approved-empty",
    "claw-memory-review-title",
    "claw-memory-approve",
    "claw-memory-reject",
    "claw-memory-detail",
    "claw-memory-close",
    "claw-memory-type",
    "claw-memory-name",
    "claw-memory-note",
    "claw-memory-channel",
    "claw-memory-status",
    "claw-memory-created",
    "claw-memory-updated",
    "claw-memory-status-approved",
    "claw-memory-type-customer_contact_candidate",
    "claw-memory-error-approval",
    "claw-memory-error-invalid",
    "claw-memory-error-auth",
    "claw-memory-error-unavailable",
    "claw-memory-error-not-found",
    "claw-memory-error-generic",
)


def test_claw_uses_shared_theme_tokens_for_all_typography() -> None:
    for source in (WORKSPACE_CSS, INTAKE_CSS):
        assert "--ink" not in source
        assert "--text-muted" not in source
    assert "var(--text" in WORKSPACE_CSS
    assert "var(--muted" in WORKSPACE_CSS
    assert "var(--text" in INTAKE_CSS
    assert "var(--muted" in INTAKE_CSS


def test_preview_transport_failures_are_retryable_errors() -> None:
    assert "renderFallback" not in APP
    assert "renderPreviewError" in APP
    assert APP.count("renderPreviewError();") == 3
    assert 'setClawStatus(clawT("claw-error-preview"), "error", "claw-error-preview")' in APP
    assert 'setClawAreaState("error")' in APP
    assert APP.count('setClawStatus(clawT("claw-status-preview-success"), "success", "claw-status-preview-success")') == 1
    assert 'setClawAreaState("success")' in APP


def test_preview_failure_does_not_echo_input_as_ai_result() -> None:
    assert "clipped" not in APP
    assert "Source text" not in APP
    assert "요청 원문:" not in APP
    assert 'data-locale-key="claw-error-preview"' not in INDEX
    assert "claw-error-preview" in LOCALE


def test_approved_memory_has_complete_ko_en_locale_parity() -> None:
    for key in APPROVED_MEMORY_KEYS:
        assert LOCALE.count(f'"{key}"') == 2, f"expected KO/EN values for {key}"


def test_approved_memory_dynamic_controls_do_not_use_hardcoded_korean() -> None:
    start = APP.index("function renderMemoryProposalReview")
    end = APP.index("function proposalBody", start)
    review_source = APP[start:end]
    for phrase in ("메모리 저장 후보", "승인", "거절", "상세", "닫기"):
        assert f'"{phrase}"' not in review_source

    detail_start = APP.index("function renderApprovedMemoryDetail")
    detail_end = APP.index("// Unguarded fetch", detail_start)
    detail_source = APP[detail_start:detail_end]
    for phrase in ("유형", "이름", "노트", "채널", "상태", "생성", "수정", "닫기"):
        assert f'"{phrase}"' not in detail_source


def test_claw_approved_memory_markup_is_locale_bound() -> None:
    for key in (
        "claw-approved-kicker",
        "claw-approved-title",
        "claw-approved-tagline",
        "claw-approved-loading",
        "claw-approved-empty",
    ):
        assert f'data-locale-key="{key}"' in INDEX
    assert 'data-locale-aria-label="claw-approved-refresh-aria"' in INDEX
    assert 'data-locale-aria-label="claw-memory-review-aria"' in INDEX
    assert "data-locale-aria-label" in LOCALE


def test_stale_claw_product_truth_copy_is_removed() -> None:
    for source in (INDEX, LOCALE):
        assert "백엔드 연결 전까지 미리보기 텍스트만 표시됩니다." not in source
        assert "백엔드 연결 전까지 비활성화" not in source
        assert "Only preview text is shown until the backend is connected." not in source
        assert "Disabled until backend wiring" not in source
        assert "미리보기 · 읽기 전용" not in source
        assert "Preview · read-only" not in source


def test_locale_keys_are_not_rendered_when_claw_locale_is_missing() -> None:
    fallback = APP[APP.index("const clawFallbackCopy"):APP.index("function setClawStatus")]
    assert '"claw-memory-approve": "Approve"' in fallback
    assert 'return clawFallbackCopy[key] ||' in APP
    assert re.search(r"textContent = clawT\(\"claw-memory-(approve|reject|detail|close)\"\)", APP)
