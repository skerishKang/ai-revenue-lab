"""#7187 R3 — the primary navy lives in one token file.

대표 결정 #7162 put one shared primary rule in the override layer; the same
four numbers were still pasted as literals across voice-composer.css,
voice-ui.css, meeting-capture.css and help.css. This pins the R3 tokenization
step: the numbers exist only in ``padiem-tokens.css``, every consumer names
the token, and the token file is loaded ahead of the sheets that read it.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from css_rules import parse_rules, find_rules_with_selector, declaration

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

TOKENS = STATIC / "padiem-tokens.css"

#: The shared primary family (#7162 대표 결정): fill, border, hover pair and
#: the focus ring. Measured identical in every theme, so the token file keeps
#: one default and no per-theme override.
PRIMARY_NUMBERS = {
    "--primary-bg": "#355977",
    "--primary-border": "#294b64",
    "--primary-hover-bg": "#2e4d67",
    "--primary-hover-border": "#23445d",
    "--primary-focus": "#6a9abc",
}

RAW_NUMBERS = tuple(PRIMARY_NUMBERS.values())


def _custom_properties(block) -> dict[str, str]:
    return {name: value for name, value in block.declarations.items()
            if name.startswith("--")}


class TestPrimaryTokens(unittest.TestCase):
    def test_the_token_file_defines_exactly_the_shared_numbers(self) -> None:
        rules = parse_rules(TOKENS.read_text(encoding="utf-8"))
        roots = [r for r in rules if r.selectors == [":root"] and r.media is None]
        self.assertEqual(len(roots), 1, "one :root block carries the defaults")
        props = _custom_properties(roots[0])
        for name, number in PRIMARY_NUMBERS.items():
            self.assertEqual(props.get(name), number, name)
        # #7187 R3 2차: the line / input-border / focus-ring / surface-border
        # tokens joined the same file; their values are pinned by
        # test_261109_line_input_focus_tokens_7187.py.
        # #7187 R3 3차: the accent family and --card-border joined too;
        # their values are pinned by test_261109_card_accent_tokens_7187.py.
        # #7187 R3 4차: the PC connection cluster's local palette joined;
        # its values are pinned by test_261111_pc_cluster_tokens_7187.py.
        self.assertEqual(
            set(props),
            set(PRIMARY_NUMBERS)
            | {"--sidebar-control-inset", "--sidebar-control-radius",
               "--sidebar-control-height"}
            | {"--line", "--input-border-strong", "--focus-ring", "--surface-border"}
            | {"--accent", "--accent-contrast", "--accent-soft", "--accent-strong",
               "--card-border"}
            | {"--pc-focus", "--pc-warning", "--pc-ack-surface",
               "--pc-connect-surface", "--pc-consent-veil", "--pc-consent-panel",
               "--pc-device-veil", "--pc-device-panel", "--pc-device-solid",
               "--pc-device-tint", "--pc-text-dim", "--pc-text-dim-soft",
               "--pc-text-dim-muted", "--pc-consent-text-dim",
               "--claw-local-focus", "--claw-local-surface",
               "--claw-local-surface-ghost", "--claw-local-text-dim",
               "--claw-local-border", "--claw-local-border-strong",
               "--claw-local-border-soft"}
            # #7817: the first screen's second headline line reads one theme
            # token; its defaults and per-theme values are pinned by
            # test_7817_first_screen_contrast.py.
            | {"--hero-sub-color"}
            # #7829: the code header (language label, copy button) reads
            # two theme tokens; their defaults and per-theme values are
            # pinned by test_7829_code_header_contrast.py.
            | {"--code-header-text", "--code-header-button-text"}
            | {"--radius-xs", "--radius-sm", "--radius-lg", "--radius-pill",
               "--radius-circle"}
            # #7187 1차(261118): the white veil role/intensity tokens joined;
            # their values are pinned by test_261118_white_veil_tokens_7187.py.
            | {"--surface-veil-faint", "--surface-veil-soft", "--surface-veil-strong",
               "--line-veil-faint", "--line-veil-soft", "--line-veil-strong"}
            # #7187 2차(261118): the white text-veil tokens joined; their
            # values are pinned by test_261118_white_veil_text_tokens_7187.py.
            | {"--text-veil-faint", "--text-veil-strong"}
            # #7187 3차: 아주 옅은 칸 바탕 씻김과 얇은 상단 하이라이트 선.
            | {"--surface-veil-ghost", "--inset-veil-ghost"}
            # #7187 4차: 패널면 씻김과 패널 상단 하이라이트 선.
            | {"--surface-veil-panel", "--inset-veil-panel"}
            # #7187 5차: 엷은 구분선·칸 바탕·인셋 하이라이트.
            | {"--line-veil-dim", "--surface-veil-dim", "--inset-veil-dim"}
            # #7187 6차: 짙은 남 잉크(글자/선택 칸) 역할 토큰.
            | {"--text-deep-ink", "--swatch-deep-ink"}
            # #7187 7차: 옅은 안개(면·글자·선·하이라이트) 역할 토큰.
            | {"--surface-veil-mist", "--text-veil-mist", "--line-veil-mist",
               "--inset-veil-mist"}
            # #7187 8차: 옅은 흰 안개(면·선·글자) 역할 토큰.
            | {"--surface-veil-haze", "--line-veil-haze", "--text-veil-haze"}
            # #7187 9차: 유리 패널·대화상자·설정 머리 글자의 짙은 잉크.
            # 값·소비 선언은 test_261119_panel_ink_tokens_7187.py가 고정한다.
            | {"--text-panel-ink"}
            # #7811 C2(261118): history.css 바탕 색 토큰이 가족으로 합류했다.
            # --dialog-dim은 #5666 공유 대화상자 딤(padiem-settings.css가 같은
            # 값을 쓴다). 값들은 test_261118_history_bg_tokens_7811.py가 고정.
            | {"--dialog-dim", "--control-wash-faint", "--control-wash-soft",
               "--control-wash-strong", "--control-wash-hover",
               "--danger-wash-soft", "--danger-wash-strong",
               # #7811 C2b(261118): 로그인 창 패널·주 단추 쓰임새 토큰.
               # 값·테마 덮개·시스템 다크 분기는
               # test_261118_auth_panel_tokens_7811.py가 고정한다.
               "--auth-panel-bg", "--auth-panel-text", "--auth-panel-border",
               "--auth-primary-bg", "--auth-primary-text",
               # #7811 C2(261118): 첫 화면 입력창 그림자 쓰임새 토큰.
               # 값은 test_261118_first_use_composer_shadow_7811.py가 고정한다.
               "--composer-home-shadow",
               # #7811 C2 foundation(261118): 바탕·크롬 색 토큰. 값·테마
               # 덮개·소비 선언은
               # test_261118_foundation_chrome_tokens_7811.py가 고정한다.
               "--app-root-bg", "--app-grid-line", "--app-grid-fade",
               "--app-selection-text", "--app-selection-bg",
               "--app-focus-outline", "--brand-mark-glow",
               "--side-icon-text", "--sidebar-footer-border",
               # #8020(261118): Claw 요청 말풍선 글자·배경. 값·테마 덮개·
               # 소비 선언은 test_8020_claw_bubble_contrast.py가 고정한다.
               "--claw-request-bubble-text", "--claw-request-bubble-bg",
               # #8024: usage tokens for theme-agnostic panel skins.
               "--surface-panel-deep",
               "--surface-panel-solid",
               "--surface-panel-dim",
               "--surface-card-deep",
               "--surface-card-solid",
               "--surface-panel-veil",
               "--surface-ink-deep",
               "--surface-fade-deep",
               "--surface-fade-solid",
                "--panel-text-faint",
                "--panel-text-soft",
                "--panel-text-strong",
                "--panel-text-max",
                # #7811 C2 calendar(261122): calendar.css 고정 팔레트 색 토큰.
                # 값·소비 선언은 test_261122_calendar_palette_tokens_7811.py가 고정.
                "--calendar-paper", "--calendar-error-border", "--calendar-error-bg",
                "--calendar-error-compact-bg", "--calendar-error-compact-border",
                "--calendar-error-text", "--calendar-status-invalid-text",
                "--calendar-delete-text", "--calendar-item-type-bg",
                "--calendar-submit-bg", "--calendar-nav-current-bg",
                "--calendar-focus-outline", "--calendar-editor-outline",
                "--calendar-today-text", "--calendar-visual-border",
                "--calendar-visual-bg", "--calendar-weekday-bg",
                "--calendar-weekday-border", "--calendar-weekday-text",
                "--calendar-grid-bg", "--calendar-day-text",
                "--calendar-day-outside-text", "--calendar-event-bg",
                "--calendar-event-text", "--calendar-worklog-bg",
                "--calendar-worklog-text", "--calendar-alert-bg",
                "--calendar-alert-text", "--calendar-more-text",
                "--calendar-week-date-text", "--calendar-allday-bg",
                "--calendar-allday-border", "--calendar-allday-label-text",
                "--calendar-hour-border", "--calendar-hour-label-text",
                "--calendar-overlay-border", "--calendar-overlay-bg",
                "--calendar-overlay-shadow", "--calendar-editor-border",
                "--calendar-editor-bg", "--calendar-editor-text",
                "--calendar-unknown-type-bg",
                "--editorial-glow-top", "--editorial-glow-bottom",
                "--editorial-copy-text", "--editorial-bubble-border",
                "--editorial-bubble-wash-strong", "--editorial-bubble-wash",
                "--editorial-bubble-bg", "--editorial-bubble-text",
                "--editorial-bubble-shadow", "--editorial-meta-edge",
                "--editorial-meta-text", "--editorial-line-accent",
                "--editorial-avatar-hi", "--editorial-avatar-ring",
                "--editorial-avatar-shadow", "--editorial-assistant-text",
                "--editorial-chip-edge", "--editorial-route-edge",
                "--editorial-route-note", "--editorial-typing-glow",
                "--editorial-typing-dot", "--editorial-gold-glow",
                "--editorial-pill-edge", "--editorial-faint-text",
                "--editorial-summary-text", "--editorial-note-text",
                "--standalone-nav-bg", "--standalone-card-bg",
                "--standalone-card-hairline", "--standalone-retry-border",
                "--standalone-subtle-text", "--standalone-connected-text",
                "--standalone-state-pending", "--standalone-state-activating",
                "--standalone-state-active", "--standalone-state-failed",
                "--standalone-scrollbar-thumb", "--standalone-scrollbar-track",
                "--standalone-panel-border", "--standalone-panel-bg",
                "--standalone-card-soft-bg",
                "--rich-text", "--rich-heading-text", "--rich-quote-border",
                "--rich-code-border", "--rich-code-bg", "--rich-edge",
                "--rich-code-pre-bg", "--rich-code-text", "--rich-table-bg",
                "--rich-table-text", "--rich-table-edge", "--rich-table-head-text",
                "--rich-research-text", "--rich-link-hover-bg",
                "--rich-source-number", "--rich-source-strong",
                "--rich-source-small", "--rich-card-hover-border",
                "--rich-composer-fade", "--rich-composer-border",
                "--rich-composer-bg-wash", "--rich-composer-bg-end", "--rich-composer-shadow",
                "--rich-composer-note",
                # #7811 C2 rich-response.css(261124): 밝은 고정 팔레트 9개.
                # 값·소비 선언은 test_261124_rich_response_tokens_7811.py가 고정한다.
                "--rich-response-quote-edge", "--rich-response-quote-bg",
                "--rich-response-rule-edge", "--rich-response-block-edge",
                "--rich-response-inner-edge", "--rich-response-control-edge",
                "--rich-response-hover-bg", "--rich-response-code-bg",
                "--rich-response-code-text",
                # #7811 C2 pc-pairing-card.css(261124): 상태 팔레트 13개.
                # 값·소비 선언은 test_261124_pc_pairing_tokens_7811.py가 고정한다.
                "--pc-pairing-active-text", "--pc-pairing-active-edge",
                "--pc-pairing-active-bg", "--pc-pairing-offline-edge",
                "--pc-pairing-offline-bg", "--pc-pairing-paused-text",
                "--pc-pairing-paused-edge", "--pc-pairing-paused-bg",
                "--pc-pairing-pending-edge", "--pc-pairing-pending-bg",
                "--pc-pairing-revoked-edge", "--pc-pairing-revoked-bg",
                "--pc-pairing-menu-shadow",
                # #7811 C2 answer-actions.css(261124): 고정 보라 팔레트 9개.
                # 값·소비 선언은 test_261124_answer_actions_tokens_7811.py가 고정한다.
                "--answer-actions-avatar-wash", "--answer-actions-avatar-edge",
                "--answer-actions-time-text", "--answer-actions-edge",
                "--answer-actions-bg", "--answer-actions-text",
                "--answer-actions-hover-edge", "--answer-actions-pressed-bg",
                "--answer-actions-more-bg",
                }
             | {"--ws-item-text", "--ws-current-wash", "--ws-current-glow",
                "--ws-soft-wash", "--ws-control-hover-edge",
                "--ws-control-hover-wash", "--ws-control-hover-text",
                "--ws-control-muted-text", "--ws-control-hover-edge-strong",
                "--ws-divider", "--ws-banner-edge", "--ws-banner-accent",
                "--ws-banner-wash-end", "--ws-banner-shadow", "--ws-form-wash",
                "--ws-dialog-edge", "--ws-dialog-kicker-text", "--ws-input-edge",
                "--ws-input-wash", "--ws-input-text", "--ws-input-focus-edge",
                "--ws-input-focus-glow", "--ws-danger-text", "--ws-secondary-text",
                "--ws-primary-hover-wash", "--ws-file-add-text",
                "--ws-file-row-edge", "--ws-card-wash", "--ws-danger-hover-text",
                "--ws-attachment-edge", "--ws-attachment-text",
                "--ws-answer-hover-edge", "--ws-output-text", "--ws-label-text"}
             | {"--voice-control-border", "--voice-accent", "--voice-btn-idle-bg",
                "--voice-btn-idle-shadow", "--voice-btn-hover-text",
                "--voice-btn-hover-bg", "--voice-btn-hover-border",
                "--voice-btn-active-text", "--voice-btn-active-bg",
                "--voice-btn-active-border", "--voice-assistant-role-text",
                "--voice-btn-active-ring", "--voice-unavailable-text",
                "--voice-unavailable-bg", "--voice-unavailable-border",
                "--voice-panel-bg", "--voice-menu-shadow", "--voice-subtle-bg",
                "--voice-menu-active-bg", "--voice-panel-shadow", "--voice-danger",
                "--voice-secondary-text", "--voice-assistant-text",
                "--voice-transcript-border"}
             | {"--foundation-account-text", "--foundation-badge-edge",
                "--foundation-badge-text", "--foundation-body-spot-a",
                "--foundation-body-spot-b", "--foundation-body-stop-1",
                "--foundation-body-stop-2", "--foundation-body-stop-3",
                "--foundation-control-edge", "--foundation-control-hover-edge",
                "--foundation-control-hover-wash", "--foundation-control-inset",
                "--foundation-control-wash", "--foundation-hairline",
                "--foundation-item-hover-wash", "--foundation-item-text",
                "--foundation-mark-base", "--foundation-mark-edge",
                "--foundation-mark-shadow", "--foundation-pill-hover-edge",
                "--foundation-pill-text", "--foundation-preview-glow",
                "--foundation-scrim-bottom", "--foundation-scrim-mid",
                "--foundation-scrim-top", "--foundation-sidebar-base",
                "--foundation-sidebar-shadow", "--foundation-sidebar-stop-1",
                "--foundation-sidebar-stop-2", "--foundation-strong-text",
                "--foundation-subtle-wash", "--foundation-top-rim",
                "--foundation-top-rim-glow", "--foundation-topbar-stop-1",
                "--foundation-topbar-stop-2", "--foundation-vignette"}
             # #7811 C2 styles(261123): styles.css 남은 바탕·크롬 색 토큰.
             # 값·소비 선언은 test_261123_styles_tokens_7811.py가 고정한다.
             | {
                "--styles-assistant-content-text",
                "--styles-attachment-chip-bg",
                "--styles-attachment-chip-file-icon-bg",
                "--styles-attachment-chip-shadow",
                "--styles-brand-mark-bg",
                "--styles-brand-mark-shadow",
                "--styles-brand-mark-text",
                "--styles-button-focus",
                "--styles-composer-bg",
                "--styles-composer-edge",
                "--styles-composer-edge-2",
                "--styles-composer-note-text",
                "--styles-composer-shadow",
                "--styles-composer-textarea-text",
                "--styles-demo-label-bg",
                "--styles-error-box-bg",
                "--styles-error-box-edge",
                "--styles-login-button-bg",
                "--styles-message-bubble-bg",
                "--styles-mini-badge-bg",
                "--styles-model-pill-bg",
                "--styles-model-pill-text",
                "--styles-new-chat-bg",
                "--styles-new-chat-shadow",
                "--styles-preview-dot-bg",
                "--styles-retry-button-bg",
                "--styles-retry-button-edge",
                "--styles-send-button-text",
                "--styles-side-item-bg",
                "--styles-sidebar-scrim-bg",
                "--styles-sidebar-shadow",
                "--styles-source-card-bg",
                "--styles-starter-bg",
                "--styles-starter-bg-2",
                "--styles-starter-edge",
                "--styles-tool-button-bg",
                "--styles-tool-button-text",
                "--styles-topbar-bg",
                "--styles-topbar-bg-2",
                "--styles-typing-i-bg",
                }
             | {"--project-border", "--project-danger-border", "--project-danger-text",
                "--project-dim", "--project-error-text", "--project-focus-outline",
                "--project-hairline", "--project-hover-border", "--project-ink",
                "--project-muted-text", "--project-note-text", "--project-on-ink-text",
                "--project-panel-bg", "--project-secondary-text",
                "--project-select-text", "--project-shadow", "--project-solid-bg",
                "--project-strong-text", "--project-subtle-wash"}
             # #7811 C2 outputs(261123): 저장한 답변 창의 고정 팔레트. 나머지
             # 값은 위 --project-* 토큰을 재사용하고, 새 값 둘만 여기서 소유한다.
             | {"--outputs-action-hover-wash", "--outputs-content-bg",
                "--outputs-dialog-shadow"}
             # 대비 수리(261124): 저장한 답변 창이 읽는 스킨 잉크·선의 판 추종
             # 토큰. 기본값은 창 스킨의 --ws-* 값을 그대로 가리키고 밝은 판 세
             # 테마만 덮는다. 값·테마 덮개·소비 선언·대비는
             # test_261124_saved_output_connector_contrast.py가 고정한다.
             | {"--outputs-kicker-text", "--outputs-control-text",
                "--outputs-control-hover-text", "--outputs-input-text",
                "--outputs-content-text", "--outputs-secondary-text",
                "--outputs-primary-text", "--outputs-danger-text",
                "--outputs-rule-edge", "--outputs-content-edge",
                "--outputs-control-edge", "--outputs-control-focus-edge",
                "--outputs-primary-edge", "--outputs-primary-hover-edge"}
             # #7811 C2 capability-nav(261124): 내비 칩·기능 대화상자·
             # Connectors 카드의 고정 팔레트. 재사용 토큰은 위 --settings-*·
             # --project-* 가 이미 고정한다.
             | {"--capability-nav-claw-edge", "--capability-nav-claw-wash",
                "--capability-nav-claw-badge-bg", "--capability-nav-dialog-shadow",
                "--capability-nav-dialog-dim", "--capability-nav-connectors-dim",
                "--capability-nav-connectors-surface", "--capability-nav-connectors-edge",
                "--capability-nav-connectors-edge-strong",
                "--capability-nav-connectors-ink",
                "--capability-nav-connectors-connected-ink",
                "--capability-nav-read-pending-ink",
                "--capability-nav-read-activating-ink",
                "--capability-nav-read-active-ink"}
             # #7811 C2 attachments(261124): 첨부 미리보기·칩의 고정 팔레트.
             # 오류 글자는 위 --project-error-text를 재사용한다.
             | {"--attachments-card-edge", "--attachments-card-wash",
                "--attachments-icon-bg", "--attachments-preview-note-ink",
                "--attachments-remove-hover-wash", "--attachments-chip-icon-ink",
                "--attachments-chip-title-ink", "--attachments-chip-meta-ink",
                "--attachments-invalid-edge", "--attachments-invalid-wash",
                "--attachments-invalid-note-ink", "--attachments-chip-remove-ink"}
             # #7811 C2 documents(261124): 문서·프로젝트 파일 패널의 고정 팔레트.
             # 흰 판/배경은 위 --settings-choice-fallback·--project-solid-bg 재사용.
             | {"--documents-icon-wash", "--documents-icon-ink",
                "--documents-reference-note", "--documents-banner-note",
                "--documents-panel-edge", "--documents-muted-text",
                "--documents-usage-text", "--documents-add-edge",
                "--documents-selection-outline"}
             # #7811 C2 b66-quote-runtime(261124): 견적 대화상자 고정 팔레트.
             # 흰 표면(.05/.04)·초점·입력 판(.8)은 위 기존 토큰을 재사용한다.
             | {"--b66-quote-hairline", "--b66-quote-dialog-dim",
                "--b66-quote-edge", "--b66-quote-faint-edge",
                "--b66-quote-review-surface"}
             # #7811 C2 search-sources(261124): 검색 출처 카드의 고정 남 잉크.
             # .1 헤어라인은 위 --rich-response-inner-edge를 재사용한다.
             | {"--search-sources-active-edge", "--search-sources-active-wash",
                "--search-sources-summary-bg", "--search-sources-summary-ink",
                "--search-sources-answer-edge", "--search-sources-link-wash",
                "--search-sources-link-hover-wash", "--search-sources-number-ink",
                "--search-sources-copy-ink"}
             # 대비 수리(261124): 연결 화면의 밝은 카드 판 위 잉크. 기본값은 테마
             # 글자색이고 dark·cinematic만 덮는다. 같은 시험 파일이 고정한다.
             | {"--connector-card-ink", "--connector-card-muted-ink"}
             # 대비 수리 후속(261124): 프로젝트 창에만 있는 창 스킨 역할의 잉크와
             # 독립 화면 공통 머리(kicker·설명 문구) 잉크. 기본값은 지금 읽는 토큰을
             # 가리키고, 밝은 판 세 테마(프로젝트 창)와 padiem-home(머리)만 덮는다.
             # test_261124_project_form_standalone_header_contrast.py 가 고정한다.
             | {"--project-form-text", "--project-file-add-text",
                "--project-file-remove-text", "--project-file-remove-hover-text",
                "--project-file-row-edge",
                "--standalone-kicker-text", "--standalone-tagline-text"}
             | {"--voice-mic-active-bg", "--voice-mic-active-edge",
                "--voice-mic-active-ring", "--voice-mic-active-hover-bg",
                "--voice-mic-active-hover-edge", "--composer-send-text",
                "--composer-send-shadow", "--composer-send-hover-shadow",
                "--composer-send-disabled-bg", "--composer-send-disabled-edge",
                "--voice-interim-text", "--voice-notice-text",
                "--voice-inline-hint-text", "--starter-toggle-edge",
                "--starter-toggle-bg", "--starter-toggle-text",
                "--starter-toggle-hover-bg", "--starter-panel-bg",
                "--starter-panel-text", "--starter-panel-edge",
                "--starter-panel-shadow"}
             # #7811 C2 admin-models(261123): 관리 모델 시트 색 토큰.
             # 값·소비 선언은 test_261123_admin_models_tokens_7811.py가 고정한다.
             | {
                "--admin-models--focus",
                "--admin-models-advanced-meta-text",
                "--admin-models-advanced-summary-text",
                "--admin-models-advanced-summary-text-2",
                "--admin-models-advanced-summary-text-3",
                "--admin-models-body-image",
                "--admin-models-brand-symbol-bg",
                "--admin-models-brand-symbol-bg-2",
                "--admin-models-brand-symbol-bg-3",
                "--admin-models-brand-symbol-bg-4",
                "--admin-models-brand-symbol-edge",
                "--admin-models-brand-symbol-shadow",
                "--admin-models-brand-symbol-text",
                "--admin-models-btn-bg",
                "--admin-models-btn-bg-2",
                "--admin-models-btn-edge",
                "--admin-models-btn-primary-bg",
                "--admin-models-btn-primary-bg-2",
                "--admin-models-btn-primary-bg-3",
                "--admin-models-btn-primary-bg-4",
                "--admin-models-btn-primary-bg-5",
                "--admin-models-btn-primary-text",
                "--admin-models-button-route-row-bg",
                "--admin-models-caption-note-text",
                "--admin-models-caption-note-text-2",
                "--admin-models-chosen-bg",
                "--admin-models-chosen-bg-2",
                "--admin-models-chosen-edge",
                "--admin-models-chosen-edge-2",
                "--admin-models-chosen-small-text",
                "--admin-models-chosen-small-text-2",
                "--admin-models-chosen-strong-text",
                "--admin-models-footer-text",
                "--admin-models-footer-text-2",
                "--admin-models-header-actions-icon-button-edge",
                "--admin-models-header-actions-icon-button-shadow",
                "--admin-models-header-bg",
                "--admin-models-header-bg-2",
                "--admin-models-header-text",
                "--admin-models-help-body-p-text",
                "--admin-models-help-body-p-text-2",
                "--admin-models-help-dialog-bg",
                "--admin-models-help-dialog-bg-2",
                "--admin-models-help-dialog-edge",
                "--admin-models-help-dialog-edge-2",
                "--admin-models-help-dialog-shadow",
                "--admin-models-help-dialog-shadow-2",
                "--admin-models-help-head-icon-button-bg",
                "--admin-models-help-head-icon-button-edge",
                "--admin-models-help-head-icon-button-text",
                "--admin-models-icon-button-bg",
                "--admin-models-icon-button-bg-2",
                "--admin-models-icon-button-bg-3",
                "--admin-models-icon-button-edge",
                "--admin-models-icon-button-text",
                "--admin-models-icon-button-text-2",
                "--admin-models-intro-h1-text",
                "--admin-models-intro-p-text",
                "--admin-models-intro-p-text-2",
                "--admin-models-mode-label-bg",
                "--admin-models-mode-label-text",
                "--admin-models-model-chevron-text",
                "--admin-models-model-chevron-text-2",
                "--admin-models-model-dot-text",
                "--admin-models-model-dot-text-2",
                "--admin-models-model-item-aria-pressed-tr-bg",
                "--admin-models-model-item-aria-pressed-tr-bg-2",
                "--admin-models-model-item-aria-pressed-tr-edge",
                "--admin-models-model-item-aria-pressed-tr-edge-2",
                "--admin-models-model-item-aria-pressed-tr-text",
                "--admin-models-model-item-aria-pressed-tr-text-2",
                "--admin-models-model-item-bg",
                "--admin-models-model-item-bg-2",
                "--admin-models-model-item-bg-3",
                "--admin-models-model-item-edge",
                "--admin-models-model-item-edge-2",
                "--admin-models-model-item-edge-3",
                "--admin-models-model-item-edge-4",
                "--admin-models-model-item-model-inactive--bg",
                "--admin-models-model-item-model-inactive--edge",
                "--admin-models-model-item-model-inactive--text",
                "--admin-models-model-item-model-inactive--text-2",
                "--admin-models-model-item-model-inactive--text-3",
                "--admin-models-model-item-text",
                "--admin-models-model-list-scrollbar",
                "--admin-models-model-state-bg",
                "--admin-models-model-state-edge",
                "--admin-models-model-state-text",
                "--admin-models-model-words-small-text",
                "--admin-models-model-words-small-text-2",
                "--admin-models-muted-text",
                "--admin-models-muted-text-2",
                "--admin-models-nav-link-bg",
                "--admin-models-nav-link-bg-2",
                "--admin-models-nav-link-bg-3",
                "--admin-models-nav-link-bg-4",
                "--admin-models-nav-link-edge",
                "--admin-models-nav-link-selected-bg",
                "--admin-models-nav-link-selected-bg-2",
                "--admin-models-nav-link-selected-edge",
                "--admin-models-nav-link-selected-nav-icon-text",
                "--admin-models-nav-link-selected-shadow",
                "--admin-models-nav-link-selected-text",
                "--admin-models-nav-link-shadow",
                "--admin-models-nav-link-text",
                "--admin-models-nav-link-text-2",
                "--admin-models-nav-link-text-3",
                "--admin-models-notice-bg",
                "--admin-models-notice-bg-2",
                "--admin-models-notice-edge",
                "--admin-models-notice-edge-2",
                "--admin-models-notice-text",
                "--admin-models-notice-text-2",
                "--admin-models-placeholder-text",
                "--admin-models-placement-item-bg",
                "--admin-models-placement-item-blocked-pos-text",
                "--admin-models-placement-item-blocked-pos-text-2",
                "--admin-models-placement-item-ready-posit-text",
                "--admin-models-placement-item-ready-posit-text-2",
                "--admin-models-position-status-text",
                "--admin-models-position-status-text-2",
                "--admin-models-preview-bg",
                "--admin-models-preview-bg-2",
                "--admin-models-preview-edge",
                "--admin-models-preview-edge-2",
                "--admin-models-preview-error-bg",
                "--admin-models-preview-error-bg-2",
                "--admin-models-preview-error-edge",
                "--admin-models-preview-pill-bg",
                "--admin-models-preview-pill-bg-2",
                "--admin-models-preview-pill-edge",
                "--admin-models-preview-pill-edge-2",
                "--admin-models-preview-pill-text",
                "--admin-models-preview-pill-text-2",
                "--admin-models-preview-small-text",
                "--admin-models-preview-strong-text",
                "--admin-models-preview-text",
                "--admin-models-product-icon-bg",
                "--admin-models-product-icon-text",
                "--admin-models-route-arrow-text",
                "--admin-models-route-arrow-text-2",
                "--admin-models-route-form-setting-item-se-bg",
                "--admin-models-route-form-setting-item-se-edge",
                "--admin-models-route-history-summary-text",
                "--admin-models-route-icon-bg",
                "--admin-models-route-icon-bg-2",
                "--admin-models-route-icon-text",
                "--admin-models-route-icon-text-2",
                "--admin-models-route-icon-text-3",
                "--admin-models-route-panel-bg",
                "--admin-models-route-panel-edge",
                "--admin-models-route-panel-shadow",
                "--admin-models-route-panel-shadow-2",
                "--admin-models-route-row-central-text",
                "--admin-models-route-row-head-bg",
                "--admin-models-route-row-head-text",
                "--admin-models-route-row-off-text",
                "--admin-models-route-row-static-text",
                "--admin-models-route-row-top-edge",
                "--admin-models-route-step-bg",
                "--admin-models-route-step-bg-2",
                "--admin-models-route-step-edge",
                "--admin-models-route-step-edge-2",
                "--admin-models-route-step-small-text",
                "--admin-models-route-step-small-text-2",
                "--admin-models-route-table-bg",
                "--admin-models-route-table-edge",
                "--admin-models-route-toggle-input-accent",
                "--admin-models-route-toggle-text",
                "--admin-models-routeevents-source-card-bg",
                "--admin-models-routeevents-source-card-edge",
                "--admin-models-search-bg",
                "--admin-models-search-bg-2",
                "--admin-models-search-edge",
                "--admin-models-search-edge-2",
                "--admin-models-search-edge-3",
                "--admin-models-search-edge-4",
                "--admin-models-search-input-text",
                "--admin-models-search-input-text-2",
                "--admin-models-search-shadow",
                "--admin-models-search-shadow-2",
                "--admin-models-search-text",
                "--admin-models-search-text-2",
                "--admin-models-section-head-h2-text",
                "--admin-models-segmented-bg",
                "--admin-models-segmented-bg-2",
                "--admin-models-segmented-edge",
                "--admin-models-segmented-input-bg",
                "--admin-models-segmented-input-focus",
                "--admin-models-segmented-input-shadow",
                "--admin-models-segmented-input-shadow-2",
                "--admin-models-segmented-input-text",
                "--admin-models-segmented-input-text-2",
                "--admin-models-segmented-span-text",
                "--admin-models-segmented-span-text-2",
                "--admin-models-setting-item-label-text",
                "--admin-models-setting-item-label-text-2",
                "--admin-models-setting-item-select-bg",
                "--admin-models-setting-item-select-edge",
                "--admin-models-setting-item-select-edge-2",
                "--admin-models-setting-item-select-text",
                "--admin-models-setting-item-select-text-2",
                "--admin-models-side-bg",
                "--admin-models-side-bg-2",
                "--admin-models-side-bg-3",
                "--admin-models-side-bottom-text",
                "--admin-models-side-bottom-text-2",
                "--admin-models-side-caption-text",
                "--admin-models-side-caption-text-2",
                "--admin-models-side-edge",
                "--admin-models-side-edge-2",
                "--admin-models-side-text",
                "--admin-models-small-count-bg",
                "--admin-models-small-count-edge",
                "--admin-models-small-count-shadow",
                "--admin-models-small-count-strong-text",
                "--admin-models-small-count-text",
                "--admin-models-small-count-text-2",
                "--admin-models-source-card-bg",
                "--admin-models-source-card-small-text",
                "--admin-models-source-card-small-text-2",
                "--admin-models-source-card-unknown-text",
                "--admin-models-source-card-unknown-text-2",
                "--admin-models-switch-track-bg",
                "--admin-models-switch-track-bg-2",
                "--admin-models-switch-track-shadow",
                "--admin-models-target-bg",
                "--admin-models-target-bg-2",
                "--admin-models-target-bg-3",
                "--admin-models-target-bg-4",
                "--admin-models-target-bg-5",
                "--admin-models-target-edge",
                "--admin-models-target-edge-2",
                "--admin-models-target-edge-3",
                "--admin-models-target-edge-4",
                "--admin-models-target-edge-5",
                "--admin-models-target-edge-6",
                "--admin-models-target-focus",
                "--admin-models-target-input-bg",
                "--admin-models-target-input-bg-2",
                "--admin-models-target-text",
                "--admin-models-text-button-text",
                "--admin-models-text-button-text-2",
                "--admin-models-tiny-status-bg",
                "--admin-models-tiny-status-bg-2",
                "--admin-models-tiny-status-text",
                "--admin-models-tiny-status-text-2",
                }
             | {"--settings-selected-text", "--settings-selected-shadow",
                "--settings-dialog-dim", "--settings-panel-edge",
                "--settings-panel-bg", "--settings-panel-shadow",
                "--settings-header-edge", "--settings-label-text",
                "--settings-close-edge", "--settings-close-text",
                "--settings-section-edge", "--settings-heading-text",
                "--settings-choice-fallback", "--settings-switch-track",
                "--settings-switch-knob", "--settings-switch-knob-shadow",
                "--settings-primary-text", "--settings-action-edge",
                "--settings-action-bg", "--settings-action-text",
                "--settings-focus-outline", "--settings-danger-desc-text",
                "--settings-input-edge", "--settings-input-bg",
                "--settings-action-hover-bg", "--settings-action-hover-edge",
                "--settings-guide-bg"}
              # #7811 C2 surfaces(261124): 1차 50개 + 2차 신규 3개. 재사용 14개는
              # 기존 가족에 이미 들어 있다. 값·소비 선언은
              # test_261124_surfaces_palette_tokens_7811.py가 고정한다.
              | {
                 "--surfaces-eyebrow-glow",
                 "--surfaces-hero-title-shadow",
                 "--surfaces-starter-border",
                 "--surfaces-starter-wash-start",
                 "--surfaces-starter-wash-end",
                 "--surfaces-starter-text",
                 "--surfaces-starter-highlight",
                 "--surfaces-starter-hover-border",
                 "--surfaces-starter-hover-wash",
                 "--surfaces-starter-hover-shadow",
                 "--surfaces-starter-icon-border",
                 "--surfaces-starter-icon-bg",
                 "--surfaces-starter-icon-highlight",
                 "--surfaces-bubble-border",
                 "--surfaces-bubble-bg",
                 "--surfaces-demo-label-border",
                 "--surfaces-assistant-text",
                 "--surfaces-answer-link-text",
                 "--surfaces-card-border",
                 "--surfaces-card-bg",
                 "--surfaces-card-text",
                 "--surfaces-source-index-bg",
                 "--surfaces-card-muted-text",
                 "--surfaces-error-border",
                 "--surfaces-error-bg",
                 "--surfaces-error-text",
                 "--surfaces-retry-border",
                 "--surfaces-retry-text",
                 "--surfaces-composer-border",
                 "--surfaces-composer-wash-start",
                 "--surfaces-composer-wash-end",
                 "--surfaces-composer-highlight",
                 "--surfaces-composer-shadow",
                 "--surfaces-composer-focus-border",
                 "--surfaces-composer-focus-highlight",
                 "--surfaces-composer-focus-shadow",
                 "--surfaces-composer-focus-glow",
                 "--surfaces-composer-text",
                 "--surfaces-tool-hover-bg",
                 "--surfaces-tool-pressed-border",
                 "--surfaces-tool-pressed-bg",
                 "--surfaces-send-border",
                 "--surfaces-send-text",
                 "--surfaces-send-bg",
                 "--surfaces-send-shadow",
                 "--surfaces-send-hover-border",
                 "--surfaces-send-hover-text",
                 "--surfaces-send-hover-bg",
                 "--surfaces-send-hover-shadow",
                 "--surfaces-note-text",
                 "--surfaces-attachment-edge",
                 "--surfaces-project-shadow",
                 "--surfaces-form-edge",
                 "--surfaces-scrollbar-thumb",
                 },
            "no stray token: the file holds the documented families only")
        # #7187 반경 스케일(261115): the border-radius scale joined the token
        # file; its values are the replaced use-site values, pinned here.
        for name, value in (("--radius-xs", "8px"), ("--radius-sm", "10px"),
                            ("--radius-lg", "20px"), ("--radius-pill", "999px"),
                            ("--radius-circle", "50%")):
            self.assertEqual(props.get(name), value, name)

    def test_no_other_sheet_carries_the_primary_numbers(self) -> None:
        """The completion criterion: the numbers exist in one file only.

        Read through the css_rules helper (#7186), so a number inside a
        comment or a selector does not count — only a declaration that would
        actually paint does.
        """
        offenders = []
        for sheet in sorted(STATIC.glob("*.css")):
            if sheet == TOKENS:
                continue
            for rule in parse_rules(sheet.read_text(encoding="utf-8")):
                for name, value in rule.declarations.items():
                    if any(number in value for number in RAW_NUMBERS):
                        offenders.append((sheet.name, name, value))
        self.assertEqual(offenders, [], offenders)

    def test_the_shared_primary_rule_names_the_tokens(self) -> None:
        polish = parse_rules((STATIC / "padiem-chat-ui-polish.css").read_text(encoding="utf-8"))
        blocks = find_rules_with_selector(polish, ".claw-generate-button")
        self.assertEqual(len(blocks), 3, "base, hover and focus-visible")
        base = next(r for r in blocks
                    if not any(s.endswith((":hover", ":focus-visible"))
                               for s in r.selectors))
        hover = next(r for r in blocks
                     if any(s.endswith(":hover") for s in r.selectors))
        focus = next(r for r in blocks
                     if any(s.endswith(":focus-visible") for s in r.selectors))
        self.assertEqual(declaration(base, "background"), "var(--primary-bg)")
        self.assertEqual(declaration(base, "border-color"), "var(--primary-border)")
        self.assertEqual(declaration(hover, "background"), "var(--primary-hover-bg)")
        self.assertEqual(declaration(hover, "border-color"), "var(--primary-hover-border)")
        self.assertEqual(declaration(focus, "outline"), "3px solid var(--primary-focus)")

    def test_the_composer_send_button_names_the_tokens(self) -> None:
        composer = parse_rules((STATIC / "voice-composer.css").read_text(encoding="utf-8"))
        send = [r for r in composer
                if any("#composerForm .send-button" == s for s in r.selectors)
                or any(s.startswith("#composerForm .send-button:") for s in r.selectors)]
        base = next(r for r in send
                    if all(":" not in s for s in r.selectors))
        self.assertEqual(declaration(base, "background"), "var(--primary-bg)")
        self.assertEqual(declaration(base, "border"), "1px solid var(--primary-border)")
        hover = next(r for r in send if any(s.endswith(":hover") for s in r.selectors))
        self.assertEqual(declaration(hover, "background"), "var(--primary-hover-bg)")
        self.assertEqual(declaration(hover, "border-color"), "var(--primary-hover-border)")
        focus = next(r for r in send if any(s.endswith(":focus-visible") for s in r.selectors))
        self.assertEqual(declaration(focus, "outline"), "3px solid var(--primary-focus)")
        # The legacy white-fill override keeps its !important (it beats the
        # frozen styles.css copy, a specificity reason unrelated to tokens).
        override = next(r for r in send
                        if any(s.endswith(":not(:disabled)") for s in r.selectors))
        self.assertEqual(declaration(override, "background"),
                         "var(--primary-bg) !important")

    def test_help_pages_alias_the_tokens_without_a_second_copy(self) -> None:
        help_css = parse_rules((STATIC / "help.css").read_text(encoding="utf-8"))
        body = find_rules_with_selector(help_css, ".chat-help-body")
        self.assertEqual(len(body), 1)
        props = _custom_properties(body[0])
        self.assertEqual(props.get("--help-navy"), "var(--primary-bg)")
        self.assertEqual(props.get("--help-navy-line"), "var(--primary-border)")
        self.assertEqual(props.get("--help-navy-hover"), "var(--primary-hover-bg)")
        self.assertEqual(props.get("--help-focus"), "var(--primary-focus)")

    def test_every_consuming_page_loads_the_token_file(self) -> None:
        for page in ("index.html", "help.html", "install.html"):
            html = (STATIC / page).read_text(encoding="utf-8")
            links = re.findall(r'<link rel="stylesheet" href="\./([^"]+\.css)"', html)
            self.assertIn("padiem-tokens.css", links, page)
            self.assertLess(links.index("padiem-tokens.css"),
                            next(i for i, name in enumerate(links)
                                 if name in ("padiem-chat-ui-polish.css", "help.css")),
                            f"{page}: tokens must load before their consumers")


if __name__ == "__main__":
    unittest.main()


