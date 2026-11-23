"""#7779 — '내 의견' 창 디자인 계약 (시안 확정분)."""
from __future__ import annotations

# #8060: shipped-source reads live in _support; assertions stay here.
from _support.feedback_design_7779_source import (
    feedback_css,
    feedback_module_js,
    index_html,
    tokens_css,
)

JS = feedback_module_js()
CSS = feedback_css()
TOKENS = tokens_css()


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


def test_internal_id_at_card_bottom_small_and_copyable_full() -> None:
    assert 'element("code", "feedback-id", item.id)' in JS
    assert "idNode.title = item.id" in JS
    assert "white-space: nowrap" in CSS and "text-overflow: ellipsis" in CSS
    # id는 제목 뒤가 아니라 카드 맨 아래다.
    assert JS.index("row.append(thread(item, admin))") < JS.index("row.append(idNode)")


def test_body_excludes_title_first_line_and_single_line_has_no_body() -> None:
    assert "restLines(item.body)" in JS
    assert "if (rest)" in JS
    assert 'element("p", "feedback-body", item.body)' not in JS


def test_tabs_use_aria_selected_with_visible_state() -> None:
    assert 'setAttribute("aria-selected"' in JS
    assert '[aria-selected="true"]' in CSS
    assert "role=\"tablist\"" in index_html()


def test_glass_primary_button_keeps_accent() -> None:
    block = CSS.split('html[data-theme="padiem-glass"] .feedback-dialog .feedback-button-primary', 1)[1].split("}", 1)[0]
    assert "var(--accent)" in block


def test_failed_message_only_on_request_failure() -> None:
    # 정상 200에서는 message가 비어 오류 줄이 뜨지 않는다. failed는 failure() 경로뿐이다.
    assert 'state.message = failure(reply)' in JS
    assert 'nodes.status.textContent = state.receipt ?' in JS
