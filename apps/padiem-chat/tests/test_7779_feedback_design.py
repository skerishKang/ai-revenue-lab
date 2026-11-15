"""#7779 — '내 의견' 창 디자인 계약 (시안 확정분)."""
from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
JS = (STATIC / "chat-feedback-module.js").read_text(encoding="utf-8")
CSS = (STATIC / "chat-feedback.css").read_text(encoding="utf-8")
TOKENS = (STATIC / "padiem-tokens.css").read_text(encoding="utf-8")


def test_card_heading_is_date_and_first_line_not_internal_id() -> None:
    assert 'element("span", "feedback-date", date(item.created_at))' in JS
    assert 'element("span", "feedback-summary", firstLine(item.body))' in JS
    # 내부 id는 제목이 아니라 카드 아래 작은 글씨다.
    assert 'element("code", "feedback-id", item.id)' in JS
    assert 'heading.append(element("code", "", item.id)' not in JS


def test_status_badges_four_kinds_with_color_classes() -> None:
    assert '"feedback-status feedback-status-" + item.status' in JS
    for name in ("new", "reviewing", "fixed", "deferred"):
        assert f".feedback-status-{name}" in CSS
    for token in ("--accent-soft", "--accent-strong", "--gold", "--success", "--success-surface", "--gold-soft"):
        assert token in TOKENS


def test_scroll_area_and_gradient_visible() -> None:
    assert "#feedbackOwnPanel" in CSS and "overflow-y: auto" in CSS
    assert "scrollbar-color:" in CSS
    assert ".feedback-dialog::after" in CSS and "linear-gradient" in CSS


def test_reply_bubbles_and_primary_send_button() -> None:
    assert '"feedback-reply feedback-reply-" + reply.side' in JS
    assert ".feedback-reply-ops" in CSS and ".feedback-reply-user" in CSS
    assert "feedback-button-primary" in JS and ".feedback-button-primary" in CSS
    assert "var(--accent)" in CSS


def test_glass_opaque_surface_and_tokens_only() -> None:
    assert 'html[data-theme="padiem-glass"] .feedback-dialog' in CSS
    assert "linear-gradient(155deg" in CSS
    for token in ("--panel", "--line", "--input-border-strong", "--card-bg", "--user-bubble-bg"):
        assert token in CSS
    # 새 리터럴 폴백 금지
    assert "var(--text, #" not in CSS and "#151820" not in CSS
