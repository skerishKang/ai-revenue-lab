"""Provider-facing attachments and evidence must not be clipped to UI excerpts."""
from types import SimpleNamespace

import pytest

from app.documents import (
    DocumentAttachment, build_document_context, build_project_files_context,
    combine_reference_context, MAX_REFERENCE_CONTEXT_CHARS,
)
from app.b14_client import _bounded_context
from padiem_ai_core.execution_runtime import (
    _normalize_additional_system_context, _compose_system_instruction,
)


def test_attached_document_and_project_files_survive_legacy_context_windows():
    document_text = "긴 첨부 원문. " * 8500 + "::DOCUMENT_TAIL"
    project_text = "긴 프로젝트 기록. " * 7500 + "::PROJECT_TAIL"
    document = DocumentAttachment("contract.txt", "text/plain", document_text)
    doc_context = build_document_context(document)
    files_context, used = build_project_files_context(
        [SimpleNamespace(name="notes.md", media_type="text/markdown", content_text=project_text)]
    )
    assert used == 1
    assert "::DOCUMENT_TAIL" in doc_context
    assert "::PROJECT_TAIL" in files_context
    combined = combine_reference_context("project instructions", files_context, doc_context)
    assert "::DOCUMENT_TAIL" in combined and "::PROJECT_TAIL" in combined
    assert len(combined) > MAX_REFERENCE_CONTEXT_CHARS
    assert _bounded_context(combined) == combined
    assert _normalize_additional_system_context(combined) == combined
    composed = _compose_system_instruction(SimpleNamespace(
        agent=SimpleNamespace(system_instruction="system instruction"),
        additional_system_context=combined,
    ))
    assert "::DOCUMENT_TAIL" in composed and "::PROJECT_TAIL" in composed


def test_reference_over_the_old_transport_bytes_is_not_rejected_not_truncated():
    # #4379: the model reference context carries no PADIEM byte total, so a
    # large reference is neither refused nor cut.
    too_big = "한" * 2_000_000
    assert _normalize_additional_system_context(too_big) == too_big
    assert _bounded_context(too_big) == too_big


def test_explicit_preview_budget_is_separate_from_provider_context():
    item = DocumentAttachment("x.txt", "text/plain", "a" * 20_000)
    assert len(build_document_context(item, max_chars=2800)) <= 2800
    assert len(build_document_context(item)) > 20_000
