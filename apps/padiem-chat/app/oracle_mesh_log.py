"""Shared Oracle Mesh result logging."""
from __future__ import annotations

import logging

from .journal_host import ensure_journal_visible
#: The result-leg stage lines (``pc_result stage=…``) and this module's own
#: bounded warnings share one logger; the host hook below is bound to it.
_RESULT_LOG = logging.getLogger("app.oracle_mesh_read_return_routes")


def ensure_result_log_host_visible() -> None:
    """Make the ``pc_result`` stage lines reach the COM2 journal (#7239 twin).

    Without it the result-ingest INFO records were created and then dropped,
    and the latency monitor could not split the result-receipt leg from the
    poll-wait leg. The fix lives in ``journal_host`` so every stage logger
    shares it (handler + INFO level gate + stand-aside).
    """
    ensure_journal_visible(_RESULT_LOG)

def _identity_bridge_failure_log_line(stage: str) -> str:
    if stage not in ("product_user", "b54_session"):
        stage = "unknown"
    return f"claw_engine_bridge_stage stage={stage} result=failed"


#: #7841 instrumentation — the store-stage word set. A refused append names why
#: it refused and what the run row looked like before it, in lower-case words
#: only: no id, body or path is added, and the stored line keeps its shape.
_PC_RESULT_ACTION_WORDS = frozenset(
    {"pc_drive_query", "pc_files_query", "pc_browser_query"}
)
_PC_RESULT_STATUS_WORDS = frozenset({"pending", "running", "completed", "failed"})
_PC_RESULT_REASON_WORDS = frozenset(
    {
        "stored", "already_completed", "same_message", "summary_same",
        "summary_guard", "other",
    }
)


def _pc_result_word(value: object, allowed: frozenset, fallback: str = "other") -> str:
    """One known lower-case word, or the fallback word for anything else."""

    return value if isinstance(value, str) and value in allowed else fallback


def log_pc_result_store_stage(
    logger, *, stage: str, run_hash: str, dispatch_id: str,
    reason: str | None = None, run_action: str = "other",
    run_status_before: str = "other", scoped: bool = False,
) -> None:
    """Write the one store-stage line; only a refusal carries the extra words."""

    if stage == "stored":
        logger.info(
            "pc_result stage=%s run_hash=%s dispatch_id=%s",
            stage, run_hash, dispatch_id,
        )
        return
    logger.info(
        "pc_result stage=%s run_hash=%s dispatch_id=%s reason=%s run_action=%s "
        "run_status_before=%s scoped=%d",
        stage, run_hash, dispatch_id,
        _pc_result_word(reason, _PC_RESULT_REASON_WORDS, "unknown"),
        _pc_result_word(run_action, _PC_RESULT_ACTION_WORDS),
        _pc_result_word(run_status_before, _PC_RESULT_STATUS_WORDS),
        1 if scoped else 0,
    )
