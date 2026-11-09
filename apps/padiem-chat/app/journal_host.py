"""One place that makes a stage logger reach the COM2 journal.

The serving CPython host configures no logging (``local_cpython`` says so
explicitly): the root logger has no handler and Python's fallback carries
WARNING and above, so an application INFO record is created and then dropped.
Every stage line this deployment relies on — orchestration timing, stream
timing, the queue marker (#7239), the result marker (#7243) — needed the same
two-line fix, and six more loggers still lacked it (2026-11-09 audit). Keeping
one implementation here means a new stage line cannot half-arrive.

Rules, unchanged from the first fixes:
  * bind one message-only stderr handler, exactly once;
  * raise the logger's own level to INFO when it would filter INFO out
    (``NOTSET`` inherits the root's WARNING — the handler alone is not enough);
  * stop propagation so a root handler configured later cannot duplicate it;
  * stand aside entirely when the host (or another module) already configured
    logging, because then the record already reaches stderr.
"""
from __future__ import annotations

import logging
import sys


def ensure_journal_visible(logger: logging.Logger) -> bool:
    """Make ``logger``'s INFO lines reach stderr; ``True`` when this call bound it.

    Idempotent: a second call on the same logger does nothing. A caller that
    only wants the guarantee can ignore the return value.
    """
    if not isinstance(logger, logging.Logger):
        raise TypeError("a logger is required")
    if logger.handlers or logging.getLogger().handlers:
        # The host already configured logging (uvicorn, request_telemetry, an
        # embedding test): its handler is the one that must write this line.
        return False
    if logger.level == logging.NOTSET or logger.level > logging.INFO:
        logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return True


__all__ = ["ensure_journal_visible"]
