"""#8727 — the answer for one dispatch whose execution raised unexpectedly.

``OracleMeshExecutor.execute`` reports failures as outcomes, not exceptions, but
a defect (or a misconfigured lane) can still raise out of it. Before this, that
exception left ``run_once`` with the dispatch claimed and unanswered and ended
the worker thread; its watchdog then restarted the whole service 300 s later and
cut every other PC's running work with it.

Now the exception ends only that dispatch: the lane's own failure shape goes back
through the normal submit path, so the server settles the dispatch at once and the
worker carries on. The shapes are the ones each lane already returns for a known
failure, so nothing new is introduced for the server to interpret.

Nothing here reads the exception message: it can carry a path or a value, so only
the class name is ever recorded by the caller.
"""
from __future__ import annotations

from typing import Any, Callable


def refused_before_the_pc(exc: BaseException) -> bool:
    """True when the exception is a refusal raised before any PC was asked.

    Matched by class name through the MRO, the same way the executor tells
    ``MeshCentralCommandRefused`` apart: the service runs from a ``__main__``
    copy of its own module, so identity checks on its classes are unreliable.
    """

    return any(cls.__name__.endswith("Refused") for cls in type(exc).__mro__)


def unexpected_failure_outcome(
    kind: str,
    exc: BaseException,
    *,
    outcome_type: Callable[..., Any],
    read_failed_body: bytes,
) -> Any:
    """The lane's own failure outcome for a dispatch whose execution raised.

    * ``read``: the ``read_failed`` marker, ``exited`` with exit code 1, exactly
      what the read lane returns when the download fails.
    * ``desktop``: ``not_executed`` for a refusal before the PC, else
      ``desktop_unavailable``.
    * ``command`` (and anything else): ``not_executed`` for a refusal before the
      PC, else ``no_reply`` — the command may have run, and ``no_reply`` is how
      the command lane already reports "unknown", never a clean exit.
    """

    refused = refused_before_the_pc(exc)
    if kind == "desktop":
        return outcome_type(
            termination="not_executed" if refused else "desktop_unavailable",
            exit_code=None, body=b"",
            note="the desktop dispatch failed before an answer was produced",
        )
    if kind == "command":
        return outcome_type(
            termination="not_executed" if refused else "no_reply",
            exit_code=None, body=b"",
        )
    return outcome_type(termination="exited", exit_code=1, body=read_failed_body)
