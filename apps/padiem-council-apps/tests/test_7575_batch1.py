# -*- coding: utf-8 -*-
"""#7575 batch 1 — fact boundaries, document structure, and flow repairs.

Each test pins one repaired number from the issue. The static contracts read the
shipped files; the export contracts read the bytes the real buttons produce in
the module harness.
"""
from __future__ import annotations

import base64
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from _council_module import load_council_module, run

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "static" / "council-app.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "council-app.css").read_text(encoding="utf-8")
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
EXPORT_JS = (ROOT / "static" / "document-export.js").read_text(encoding="utf-8")


def _zip(detail):
    return zipfile.ZipFile(io.BytesIO(base64.b64decode(detail["bytes"])))


def test_24_book_prompt_states_the_fact_boundary():
    prompt = load_council_module().meeting.buildBookPrompt(["[기록: 10월 주민 민원 회의.txt]\n본문"])
    assert "선택한 기록에 있는 사실만 쓸 것" in prompt
    assert "'검토·예정'은 '검토·예정'으로 그대로 쓸 것" in prompt
    assert "기간·횟수·성과를 부풀리지 말 것" in prompt


def test_24_result_shows_a_fact_check_line():
    assert "councilBookFactCheck" in JS
    assert "선택한 기록에 없는 내용이 없는지 사실관계를 확인해 주세요." in JS


def test_23_markdown_export_uses_document_styles():
    seen = run("export")
    hwpx = _zip(seen["markdown"]["hwpx"])
    section = hwpx.read("Contents/section0.xml").decode("utf-8")
    assert "###" not in section and "**" not in section and "* 신호등" not in section
    assert 'charPrIDRef="2"' in section, "제목/소제목 스타일이 쓰여야 한다"
    assert 'charPrIDRef="3"' in section, "굵게가 남아야 한다"
    ET.fromstring(section)
    header = hwpx.read("Contents/header.xml").decode("utf-8")
    assert header.count("<hh:charPr ") == 4, "본문·제목·소제목·굵은 글자 네 가지"
    docx = _zip(seen["markdown"]["docx"]).read("word/document.xml").decode("utf-8")
    assert "###" not in docx and "**" not in docx
    assert "Heading2" in docx and "ListParagraph" in docx


def test_23_every_export_rides_the_same_converter():
    assert "lib.blocksFromText(text, { firstLineTitle: kind === \"book\", headings: true })" in JS
    assert "function inlineRuns(text)" in EXPORT_JS
    assert "mdList" in EXPORT_JS


def test_1_home_clears_the_tool_hash_and_memory():
    assert 'removeItem("padiem-council-tool")' in JS
    assert 'history.replaceState(null, "", (loc.pathname || "/") + (loc.search || ""))' in JS


def test_2_the_whole_card_opens_the_tool():
    assert 'document.querySelectorAll(".council-card").forEach((card)' in JS
    assert 'const tags = ["BUTTON", "A", "INPUT", "TEXTAREA", "SELECT", "LABEL"]' in JS


def test_3_pc_save_notice_sits_next_to_the_button():
    assert "council-pc-save-hint" in JS
    assert "hint.parentElement" not in JS  # the hint is appended to the button's own row
    assert "button.parentElement.appendChild(hint)" in JS


def test_5_and_25_empty_selection_uses_an_in_screen_notice():
    assert 'setNotice(bookNotice, "기록을 하나 이상 골라 주세요.", "error")' in JS
    assert 'alert("선택된 기록이 없습니다.")' not in JS


def test_6_login_button_is_always_visible_and_the_panel_is_centered():
    assert 'id="councilAuthAction">로그인</button>' in HTML
    assert "councilSignupLink" in HTML
    assert "/auth/shared/start?return_to=%2Fapps%2Fcouncil%2F" in HTML
    assert ".council-auth:not([hidden])" in CSS
    assert "transform: translate(-50%, -50%)" in CSS


def test_7_narrow_screens_get_a_tool_switcher():
    assert 'id="councilToolNav"' in HTML
    assert ".council-tool-nav { display: flex; }" in CSS


def test_8_the_current_tool_is_marked_in_the_header():
    assert "function paintNavCurrent(tool)" in JS
    assert 'item.setAttribute("aria-current", "page")' in JS
    assert '.council-nav-item[aria-current="page"]' in CSS


def test_12_reference_button_has_a_readable_foreground():
    assert "color: var(--council-text); background: var(--council-surface);" in CSS


def test_13_tier_label_is_visible_in_the_workspace():
    assert "html.council-in-workspace .council-tier { color: var(--text); }" in CSS


def test_17_completion_is_announced_and_scrolled_on_a_phone():
    assert 'setNotice(line, "초안이 준비됐습니다", "success")' in JS
    assert "window.innerWidth <= 768" in JS


def test_18_unsaved_results_warn_before_unload():
    assert 'addEventListener("beforeunload"' in JS
    assert "저장하지 않은 결과가 있습니다." in JS
    assert "function markUnsaved()" in JS and "function markSaved()" in JS


def test_19_one_sns_tone_value_survives_platform_switches():
    assert "tone: toneSel.value" in JS
    assert "savedDraft.tone" in JS
    assert "문체는 탭마다 두지 않는다" in JS


def test_20_sns_saved_name_carries_the_platform():
    assert 'return "SNS_" + tabNames[platform] + "_"' in JS


def test_22_meeting_save_refreshes_the_activity_list():
    assert "await refreshArchive(archive);" in JS


def test_26_pc_import_explains_the_program():
    assert "PADIEM PC 연결 프로그램으로 이 컴퓨터에 있는 예전 글을 가져옵니다." in JS


def test_27_activity_rows_show_meeting_name_and_date():
    assert "meetingMeta[file.id]" in JS
    assert "회의\\s*일시" in JS
    assert "council-archive-count" in JS


def test_4_copy_feedback_still_exists():
    assert "function wireCopy(" in JS
    assert "복사됨" in JS
