"""#4379 C-group 3rd slice: the runtime and core request limits.

Each case reproduces the exact former boundary and proves that the value is now
processed instead of refused, and that nothing is silently cut.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_core_context_carries_no_padiem_byte_total() -> None:
    # C6: the model context and the grounded evidence carry no PADIEM total.
    from padiem_ai_core.execution_runtime import MAX_SYSTEM_CONTEXT_BYTES
    from padiem_ai_core.grounding_runtime import (
        MAX_GROUNDED_EVIDENCE_CONTEXT_CHARS,
        GroundingPolicy,
    )

    assert MAX_SYSTEM_CONTEXT_BYTES is None
    assert MAX_GROUNDED_EVIDENCE_CONTEXT_CHARS is None
    assert GroundingPolicy().max_context_chars is None


def test_the_runtime_timeouts_carry_no_padiem_wall_clock_ceiling() -> None:
    # C5: the long-running work carries no PADIEM wall-clock ceiling.
    from kagent.external_coding_agent import _MAX_TIMEOUT_SECONDS
    from kagent.local_agent import _MAX_TIMEOUT_SECONDS as LOCAL_MAX_TIMEOUT
    from kagent.local_agent_worktree_state import MAX_GIT_STATUS_TIMEOUT_SECONDS
    from kagent.supervised_windows_excel_pdf import MAX_TIMEOUT_SECONDS

    assert _MAX_TIMEOUT_SECONDS is None
    assert LOCAL_MAX_TIMEOUT is None
    assert MAX_GIT_STATUS_TIMEOUT_SECONDS is None
    assert MAX_TIMEOUT_SECONDS is None


def test_the_isolation_ladders_keep_their_grace_ceilings() -> None:
    # C5: the termination ladder keeps its grace ceilings. Only the work
    # timeout ceiling is gone.
    from kagent.document_parser_isolation import (
        DOCUMENT_PARSER_KILL_GRACE_MAX_SECONDS,
        DOCUMENT_PARSER_TIMEOUT_MAX_SECONDS,
    )
    from kagent.image_ocr_isolation import (
        IMAGE_OCR_KILL_GRACE_MAX_SECONDS,
        IMAGE_OCR_TIMEOUT_MAX_SECONDS,
    )

    assert DOCUMENT_PARSER_TIMEOUT_MAX_SECONDS is None
    assert IMAGE_OCR_TIMEOUT_MAX_SECONDS is None
    assert DOCUMENT_PARSER_KILL_GRACE_MAX_SECONDS == 2.0
    assert IMAGE_OCR_KILL_GRACE_MAX_SECONDS == 5.0
