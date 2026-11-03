"""Chat message UI + sidebar single-cell regression guard (2026-10-20).

Owner decision (2026-10-20) covered three surfaces in one change:

1. The user turn shows `name -> initial avatar` with the same 32x32 geometry as
   the Padiem "P" avatar, and the copy/edit affordances are always visible.
2. The answer turn carries its completion time, and a restored turn never
   invents one.
3. Every hover hint uses the shared PADIEM chip tooltip instead of the
   browser's own popup.

The sidebar single-cell design (#4890/#4894/#4897) is guarded here because the
`sidebar-section-polish.css` link was dropped from index.html by #5219 while
that commit added the composer clearance sheet. Without the link the glass
`.recent-item` blur stayed on the title half of every project/conversation
row, so the approved single cell split into two boxes.

These are focused static checks. They do not start a server, call a model or
touch auth, and they do not replace the browser verification.
"""
from pathlib import Path
import re

STATIC = Path(__file__).resolve().parents[1] / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
OUTPUTS = (STATIC / "outputs.js").read_text(encoding="utf-8")
GLASS = (STATIC / "padiem-glass-portrait.css").read_text(encoding="utf-8")
ANSWER_ACTIONS = (STATIC / "answer-actions.css").read_text(encoding="utf-8")
SURFACES = (STATIC / "padiem-surfaces.css").read_text(encoding="utf-8")
TOOLTIP_CSS = (STATIC / "shared-tooltip.css").read_text(encoding="utf-8")
TOOLTIP_JS = (STATIC / "shared-tooltip.js").read_text(encoding="utf-8")


def test_sidebar_single_cell_sheet_is_linked_and_cascades_last():
    """#5219 dropped this link. The approved single-cell design needs it back."""
    assert 'href="./sidebar-section-polish.css"' in HTML
    assert 'href="./sidebar-section-polish.css"' in HTML
    assert HTML.index('href="./sidebar-section-polish.css"') > HTML.index(
        'href="./shared-six-panel-frame.css"'
    )
    # The sheet still carries the title-only-blur reset that keeps one cell.
    assert re.search(
        r"project-row > \.project-item, \.history-row > \.history-item\) \{[^}]*"
        r"backdrop-filter: none !important",
        (STATIC / "sidebar-section-polish.css").read_text(encoding="utf-8"),
        re.S,
    )


def test_user_avatar_uses_the_account_initial_and_keeps_name_first():
    assert "function accountInitial(name)" in APP
    assert "avatar.textContent = accountInitial(name)" in APP
    # The DOM order stays name -> avatar.
    template = HTML[HTML.index('id="userMessageTemplate"'):]
    template = template[: template.index("</template>")]
    assert template.index("user-profile-chip") < template.index("user-avatar")


def test_user_and_answer_avatars_share_one_size():
    for sheet, selector in (
        (ANSWER_ACTIONS, r"\.user-avatar \{[^}]*width: 32px;[^}]*height: 32px;[^}]*border-radius: 10px;"),
        (SURFACES, r"\.assistant-avatar \{[^}]*width: 32px;[^}]*height: 32px;[^}]*border-radius: 10px;"),
        (GLASS, r"\.assistant-avatar \{[^}]*width: 32px;[^}]*height: 32px;"),
        (GLASS, r"\.user-avatar \{[^}]*width: 32px !important;[^}]*height: 32px !important;[^}]*border-radius: 10px !important;"),
    ):
        assert re.search(selector, sheet, re.S), f"avatar geometry missing in {selector}"


def test_user_actions_are_always_visible_without_hover():
    block = GLASS[GLASS.index("#messageList .user-message .user-actions {"):]
    block = block[: block.index("}")]
    assert "display: flex !important" in block
    # No hover-only reveal is left behind.
    assert "#messageList .user-message:hover .user-actions" not in GLASS
    assert "@media (hover: none)" not in GLASS


def test_answer_carries_a_completion_time_and_restored_turns_invent_none():
    assert "article.dataset.completedAt" in APP
    assert 'clock.className = "answer-action-time"' in OUTPUTS
    assert "const completedAt = article.dataset.completedAt" in OUTPUTS
    # A restored conversation is rendered without a live stamp.
    assert "addUserMessage(item.content, null, { restored: true })" in APP
    assert "if (restored) {" in APP


def test_hover_hints_use_the_shared_chip_tooltip_not_the_native_title():
    assert 'href="./shared-tooltip.css"' in HTML
    assert 'src="./shared-tooltip.js"' in HTML
    assert "window.PadiemSharedTooltip" in TOOLTIP_JS
    # The chip is a small rounded pill with the 12px / 500 label type.
    assert "border-radius: 999px" in TOOLTIP_CSS
    assert "font-size: 12px" in TOOLTIP_CSS
    assert "font-weight: 500" in TOOLTIP_CSS
    # The answer action buttons carry the chip label, not a native title.
    assert 'button.setAttribute("data-padiem-tooltip", label);' in OUTPUTS
    assert "button.title = label;" not in OUTPUTS
    # The composer action icons moved to the same chip.
    assert 'data-padiem-tooltip="파일 첨부"' in HTML
    assert 'data-padiem-tooltip="웹 검색"' in HTML
    assert 'data-padiem-tooltip="모델 선택"' in HTML
    assert 'data-padiem-tooltip="메시지 전송"' in HTML


def test_static_reference_mirror_stays_byte_pinned():
    """static/styles.css is pinned to the product reference mirror."""
    repo = STATIC.parents[2]
    assert (STATIC / "styles.css").read_bytes() == (
        repo / "reference/business-62-padiem-chat-v1/styles.css"
    ).read_bytes()
