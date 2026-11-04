"""#4379 follow-up: the Chat document path carries no fixed model-input char cap.

#6848 and #6853 moved input bounding to the model's registered context window,
measured once at B14 dispatch (`apps/korean-ai-platform/app/pilot/platform.py`
through `padiem_ai_core.conversation_bounds`). The Chat builders were already
uncapped; the three char ceilings that still appeared in `app/documents.py` were
retired definitions no app code read (2,800 / 2,600 / 8,000). They are removed
here so they cannot be re-wired, and this file pins both halves of the rule:

- model input totals: no PADIEM-side char ceiling — the model window is the only
  one, and an unknown window means no trimming;
- resource protection that #4379 explicitly keeps: the UTF-8 transport envelope
  for multi-attachment context, and a caller-requested presentation excerpt.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.documents import (
    DocumentAttachment,
    MAX_ATTACHMENTS_CONTEXT_TOTAL_BYTES,
    build_document_context,
    build_documents_context,
    build_project_files_context,
    combine_reference_context,
)


APP_DIR = Path(__file__).resolve().parents[1] / "app"
RETIRED_CHAR_CAPS = (
    "MAX_EPHEMERAL_DOCUMENT_CONTEXT_CHARS",
    "MAX_PROJECT_FILES_CONTEXT_CHARS",
    "MAX_REFERENCE_CONTEXT_CHARS",
)


@pytest.mark.parametrize("name", RETIRED_CHAR_CAPS)
def test_a_retired_char_ceiling_is_not_reintroduced_anywhere_in_the_app(name):
    offenders = [
        path.name for path in sorted(APP_DIR.glob("*.py"))
        if name in path.read_text(encoding="utf8")
    ]
    assert offenders == []


def test_documents_module_defines_no_fixed_model_input_char_ceiling():
    source = (APP_DIR / "documents.py").read_text(encoding="utf8")
    # The surviving ceilings are byte budgets and an excerpt length that only a
    # transport-envelope overflow selects; neither is a model-input total.
    assert "_CONTEXT_CHARS = " not in source
    assert "conversation_bounds" not in source  # no second trimming authority in Chat


def test_one_document_of_any_length_reaches_the_model_whole():
    long_text = "긴 계약 원문. " * 30_000 + "::TAIL"
    context = build_document_context(DocumentAttachment("contract.txt", "text/plain", long_text))
    assert len(context) > 200_000 and "::TAIL" in context


class SimpleFile:
    def __init__(self, *, name, media_type, content_text):
        self.name = name
        self.media_type = media_type
        self.content_text = content_text


def test_project_files_and_reference_combination_are_not_char_capped():
    files = [
        SimpleFile(name=f"note{index}.md", media_type="text/markdown",
                   content_text=("내용. " * 6_000) + f"::TAIL{index}")
        for index in range(1, 4)
    ]
    context, used = build_project_files_context(files)
    assert used == 3
    combined = combine_reference_context("지침 원문. " * 6_000, context, None)
    assert "::TAIL3" in combined and len(combined) > 60_000


def test_the_transport_envelope_is_still_enforced_and_pinned():
    # #4379 keeps HTTP/resource envelopes as a separate contract: this is a byte
    # budget, not a model-input char cap. Only the oversized file gives way, and
    # its stored original is named in the block.
    assert MAX_ATTACHMENTS_CONTEXT_TOTAL_BYTES == 5_500_000
    docs = [
        DocumentAttachment("big.txt", "text/plain", "a" * 10_000 + "::BIG_TAIL",
                           file_id="b66file_synthetic0"),
        DocumentAttachment("small1.txt", "text/plain", "b" * 100 + "::ONE_TAIL"),
        DocumentAttachment("small2.txt", "text/plain", "c" * 100 + "::TWO_TAIL"),
    ]
    context = build_documents_context(docs, max_total_bytes=8_000)
    assert len(context.encode("utf8")) <= 8_000
    assert "::BIG_TAIL" not in context
    assert "::ONE_TAIL" in context and "::TWO_TAIL" in context
    assert context.count("문서 요약") == 1
    assert "b66file_synthetic0" in context


def test_multi_attachment_context_under_the_envelope_survives_whole():
    # ~810KB of Hangul bodies sits well inside the 5.5MB transport envelope, so
    # nothing gives way: every file keeps its tail and no summary block appears.
    docs = [DocumentAttachment(f"d{index}.txt", "text/plain", "나" * 90_000 + f"::TAIL{index}")
            for index in range(3)]
    context = build_documents_context(docs)
    assert len(context.encode("utf8")) <= MAX_ATTACHMENTS_CONTEXT_TOTAL_BYTES
    for index in range(3):
        assert f"::TAIL{index}" in context
    assert "문서 요약" not in context


def test_default_path_still_fits_the_transport_envelope():
    docs = [DocumentAttachment(f"huge{index}.txt", "text/plain", "나" * 1_000_000 + f"::TAIL{index}")
            for index in range(3)]
    context = build_documents_context(docs)
    assert len(context.encode("utf8")) <= MAX_ATTACHMENTS_CONTEXT_TOTAL_BYTES
    assert "문서 요약" in context


def test_an_explicit_presentation_budget_is_still_honoured():
    item = DocumentAttachment("x.txt", "text/plain", "a" * 20_000)
    assert len(build_document_context(item, max_chars=2_800)) <= 2_800
    assert len(build_document_context(item)) > 20_000
