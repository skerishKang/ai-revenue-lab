"""Attachment capability copy is derived from one browser truth source (#8060 51차).

Raw source reads live in _support(attachment_capability_source); the contracts
assert on the capability object evaluated in Node, parsed DOM attributes/text
and named source facts instead of pinning raw source substrings. Meaning is
preserved: every reviewed absence and every copy/display requirement is still
checked.
"""
from __future__ import annotations

from _android_handoff_storage_guard import assert_session_storage_is_handoff_only

# #8060 51차: 원문 read는 _support 헬퍼가 담당하고 단언은 파싱·계산 값·동작으로
# 확인한다(의미 약화 없음).
from _support.attachment_capability_source import (  # noqa: E402
    app_facts,
    binary_facts,
    capabilities_facts,
    capabilities_forbidden_tokens,
    combined_forbidden_tokens,
    combined_source,
    index_facts,
    index_forbidden_tokens,
    index_text,
    locale_facts,
    readme_facts,
)

EXPECTED_LABELS = (
    "JPEG", "PNG", "WebP", "TXT", "Markdown", "CSV", "JSON",
    "PDF", "DOCX", "PPTX", "XLSX",
)


def test_attachment_capabilities_are_single_browser_truth_source():
    facts = capabilities_facts()
    assert facts["exported"] is True
    labels = facts["image_labels"] + facts["text_labels"] + facts["binary_labels"]
    for label in EXPECTED_LABELS:
        assert label in labels
    # The browser truth object carries no byte/length limit of any kind.
    assert facts["size_fields"] == []
    assert facts["size_copy"] is False
    for key in ("idleNote", "fileButtonTitle", "unsupportedFormat"):
        assert key in facts["copy_keys"]
    assert capabilities_forbidden_tokens() == []


def test_capability_projection_loads_before_copy_and_attachment_consumers():
    scripts = index_facts()["script_sources"]
    positions = [
        scripts.index(name)
        for name in ("attachment-capabilities.js", "locale.js", "document-binary.js", "app.js")
    ]
    assert len(set(positions)) == 4
    assert positions == sorted(positions)


def test_composer_does_not_hard_code_format_truth_in_html():
    facts = index_facts()
    ids = facts["ids"]
    attrs = facts["attrs"]
    file_input = attrs["attachmentFileInput"]
    assert file_input["type"] == "file"
    assert "multiple" in file_input
    assert "hidden" in file_input
    assert "documentFormatsToggle" in ids
    assert "documentFormatsPanel" in ids
    assert index_forbidden_tokens() == []
    button = attrs["attachmentButton"]
    assert button["data-padiem-tooltip"] == "파일 붙이기"
    assert button["aria-label"] == "파일 붙이기"
    assert "title" not in button
    assert "shared-tooltip.js" in facts["script_sources"]
    assert "붙일 파일 형식을 확인하는 중입니다." in index_text()


def test_locale_derives_attachment_copy_without_clobbering_runtime_state():
    facts = locale_facts()
    for key in (
        "uses_capability_global", "uses_document_formats", "zero_width_join",
        "input_accept_assignment", "tooltip_label",
    ):
        assert facts[key] is True
    assert facts["title_assignment"] is False
    assert facts["forbidden_tokens"] == []


def test_app_uses_capabilities_for_formats_idle_copy_and_errors():
    facts = app_facts()
    for key in (
        "uses_capability_global", "image_flatmap", "text_flatmap",
        "active_project_branch", "idle_note_copy", "unsupported_throw",
        "localechange_listener", "set_note_idle",
    ):
        assert facts[key] is True
    assert facts["forbidden_tokens"] == []


def test_binary_reader_derives_formats_from_capabilities():
    facts = binary_facts()
    assert facts["uses_capability_global"] is True
    assert facts["binary_foreach"] is True
    assert facts["forbidden_tokens"] == []


def test_project_file_persistence_copy_remains_explicitly_distinct():
    text = index_text()
    assert "PDF·DOCX는 텍스트만 추출해 저장하며 원본은 저장하지 않습니다." in text
    assert "PPTX·XLSX는 미지원." in text
    accept = index_facts()["attrs"]["projectFileInput"]["accept"]
    assert accept == (
        "text/plain,text/markdown,text/csv,application/json,"
        ".txt,.md,.markdown,.csv,.json,application/pdf,.pdf,"
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document,.docx,"
        "application/hwp+zip,.hwpx,.hwp"
    )
    assert readme_facts()["persistence_missing"] == []


def test_readme_matches_current_ephemeral_composer_contract():
    facts = readme_facts()
    assert facts["missing"] == []
    assert facts["forbidden_tokens"] == []


def test_no_hidden_browser_persistence_or_interception_added():
    assert combined_forbidden_tokens() == []
    assert_session_storage_is_handoff_only(combined_source())


def test_document_starter_formats_break_only_at_explicit_separators():
    assert "documentStarterButton" in index_facts()["ids"]
    assert locale_facts()["zero_width_join"] is True
