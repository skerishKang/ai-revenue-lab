"""#5882 PR-E — every loaded ceiling states the limit that actually causes it.

The policy is that a product-side number standing in for a platform's limit is not
allowed: an arbitrary cap refuses work the platform would accept. Each test below
pins one loaded cap to its real cause, and pins the two that survive to the
platform or provider numbers they are derived from.

| Cap | Verdict | Cause |
| --- | --- | --- |
| `project_files.content_text` | removed (character count) | D1 per-row size (~2 MB), now measured in bytes (migration 077) |
| project file request body | derived | one row's text + a bounded JSON envelope |
| `MAX_PROJECT_FILES` / `MAX_PROJECT_TOTAL_CHARS` | removed | never enforced |
| Drive case PDF | derived | Workers memory limit (128 MB) at ~2.33x peak |
| voice STT envelope | kept + rationale | the STT contract's own 3 MiB decoded-audio ceiling |
"""
from __future__ import annotations

import re
from pathlib import Path

from app import drive_case_folder_engine, project_file_routes, project_files, voice_stt_routes

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
REPO = ROOT.parents[1]

D1_ROW_LIMIT_BYTES = 2 * 1024 * 1024
WORKER_MEMORY_LIMIT_BYTES = 128 * 1024 * 1024


def test_the_stored_text_ceiling_is_the_d1_row_limit_in_bytes() -> None:
    """A row's ceiling is what D1 stores, so it is the row size, measured in bytes."""

    assert project_files.PROJECT_FILE_MAX_TEXT_BYTES == D1_ROW_LIMIT_BYTES


def test_the_request_body_bound_follows_the_row_plus_a_bounded_envelope() -> None:
    envelope = project_file_routes.MAX_PROJECT_FILE_BODY_BYTES - project_files.PROJECT_FILE_MAX_TEXT_BYTES
    assert 0 < envelope <= 256 * 1024, envelope
    assert project_file_routes.MAX_PROJECT_FILE_BODY_BYTES != 160_000, "the arbitrary body cap is retired"


def test_no_per_project_file_count_or_total_character_cap_is_declared() -> None:
    """The retired pair was never enforced; a declared-but-unenforced cap is a lie."""

    source = (APP / "project_files.py").read_text(encoding="utf-8")
    assert not re.search(r"^MAX_PROJECT_FILES\s*=", source, re.M)
    assert not re.search(r"^MAX_PROJECT_TOTAL_CHARS\s*=", source, re.M)
    assert not hasattr(project_files, "MAX_PROJECT_FILES")
    assert not hasattr(project_files, "MAX_PROJECT_TOTAL_CHARS")


def test_a_refused_body_states_the_bound_and_the_way_out_in_korean() -> None:
    source = (APP / "project_files.py").read_text(encoding="utf-8")
    assert "본문이 너무 길어요" in source
    assert "나눠서" in source
    # The route's 413 for an over-large request body carries the same guidance
    # instead of a bare "too large".
    routes = (APP / "project_file_routes.py").read_text(encoding="utf-8")
    assert "본문이 너무 길어요" in routes
    assert "문서 요청이 너무 큽니다" not in routes


def test_the_drive_pdf_bound_is_the_workers_memory_and_admits_a_scanned_pdf() -> None:
    """Peak ≈ 2.33x the PDF (engine base64, decoded bytes, framed response)."""

    peak_ratio = 1 + (4 / 3) + 0.25
    peak = drive_case_folder_engine.MAX_PDF_BYTES * peak_ratio
    assert peak < WORKER_MEMORY_LIMIT_BYTES / 2, peak
    # The retired 4 MB refused ordinary scanned PDFs; this bound does not.
    assert drive_case_folder_engine.MAX_PDF_BYTES > 10 * 1024 * 1024
    # The base64 ceiling is still derived from the byte ceiling, not restated.
    assert (
        drive_case_folder_engine.MAX_PDF_BASE64_CHARS
        == ((drive_case_folder_engine.MAX_PDF_BYTES + 2) // 3) * 4
    )


def test_the_voice_stt_envelope_still_covers_the_provider_audio_ceiling() -> None:
    """Kept, not removed: the STT contract refuses more than 3 MiB of decoded audio."""

    contract = (REPO / "apps/padiem-voice-stt/voice_stt_contract.py").read_text(encoding="utf-8")
    match = re.search(r"^MAX_AUDIO_BYTES = (\d+) \* (\d+) \* (\d+)", contract, re.M)
    assert match is not None, "the STT contract's decoded-audio ceiling moved or was renamed"
    first, second, third = (int(value) for value in match.groups())
    decoded_ceiling = first * second * third
    assert decoded_ceiling == 3 * 1024 * 1024

    # base64 inflates by 4/3, so this envelope must be able to carry the ceiling.
    carryable = voice_stt_routes.MAX_AUDIO_BASE64_CHARS * 3 // 4
    assert carryable >= decoded_ceiling
    # And it must not be an unbounded multiple of it.
    assert carryable < decoded_ceiling * 2
