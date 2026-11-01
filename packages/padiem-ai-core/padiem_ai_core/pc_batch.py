"""Batch existing PC operations without granting any new file authority.

The caller must bind an authorized PC executor and an owner-scoped output store
with bind_batch_services. No local filesystem operation is implemented here.
The executor's execute_authorized method must perform the same per-operation
admission and argument validation as an ordinary PC tool call. Services are
context-local and absent by default. This module does not wire a queue or engine.

The sequential tool orchestration and returning summaries of intermediate
results follow Hermes Agent's code-execution approach (MIT).
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from contextvars import ContextVar
import json
import math
from queue import Empty, Queue
from threading import Thread
import time

_READ_OPS = frozenset({"list", "search", "read", "stat"})
_RISKY_OPS = frozenset({"write", "move", "delete"})
_SERVICES = ContextVar("pc_batch_services", default=None)
_PREVIEW_CHARS = 4096


@contextmanager
def bind_batch_services(executor, output_store):
    """Bind trusted per-step authorization/execution and owner-scoped storage."""
    if not callable(getattr(executor, "execute_authorized", None)):
        raise TypeError("executor must provide execute_authorized")
    if not callable(getattr(output_store, "store", None)):
        raise TypeError("output_store must provide store")
    token = _SERVICES.set((executor, output_store))
    try:
        yield
    finally:
        _SERVICES.reset(token)


def _result(index, ok, summary, handle=None):
    return {"step": index, "ok": ok, "summary": summary, "output_handle": handle}


def _run_step(index, step, owner, services):
    executor, output_store = services
    try:
        # The existing PC adapter is responsible for validating args and grants.
        result = executor.execute_authorized(step["op"], step["args"], owner=owner)
        if not isinstance(result, dict) or type(result.get("ok")) is not bool:
            raise ValueError("invalid PC operation result")
        if not result["ok"]:
            return _result(index, False, str(result.get("error") or "PC operation failed"))
        output = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        if len(output) <= _PREVIEW_CHARS:
            return _result(index, True, output)
        saved = output_store.store(output, owner=owner, source="pc_batch")
        if not isinstance(saved, dict) or not isinstance(saved.get("handle"), str):
            raise ValueError("output store did not return a handle")
        # The store controls its own preview and preserves the complete output.
        summary = saved["head"] + "\n… [output truncated; full result in output_handle] …\n" + saved["tail"]
        return _result(index, True, summary, saved["handle"])
    except Exception as exc:
        return _result(index, False, str(exc) or type(exc).__name__)


def run_batch(steps, *, owner, stop_on_error=True, total_timeout):
    """Run authorized steps sequentially; timeout never starts another step.

    A trusted bound executor may provide confirm_batch after the shared harness
    has authorized every mutation. Without it, the whole batch is held before
    any read or write. Per-step authorization still belongs to the executor.
    A timed-out in-flight operation may finish later; it is never replayed here.
    Results use zero-based step indexes.
    """
    if not isinstance(owner, str) or not owner:
        raise ValueError("owner must be a non-empty string")
    if not isinstance(steps, (list, tuple)):
        raise ValueError("steps must be a list")
    if type(stop_on_error) is not bool:
        raise ValueError("stop_on_error must be boolean")
    if total_timeout is not None and (
            isinstance(total_timeout, bool) or not isinstance(total_timeout, (int, float))
            or not math.isfinite(total_timeout) or total_timeout <= 0):
        raise ValueError("total_timeout must be None or finite and positive")
    # Scan the entire batch before executing even a read, so a later mutation
    # cannot partially run and cannot be hidden by stop_on_error or timeout.
    steps = deepcopy(steps)
    for step in steps:
        if not isinstance(step, dict) or set(step) != {"op", "args"}:
            raise ValueError("each step must contain op and args")
        if (not isinstance(step["op"], str) or step["op"] not in _READ_OPS | _RISKY_OPS
                or not isinstance(step["args"], dict)):
            raise ValueError("unsupported operation or invalid args")
    services = _SERVICES.get()
    if any(step["op"] in _RISKY_OPS for step in steps):
        confirm = getattr(services[0], "confirm_batch", None) if services else None
        if not callable(confirm) or confirm(deepcopy(steps), owner=owner) is not True:
            return {"results": [], "completed": 0, "requires_confirmation": True}
    if services is None:
        raise RuntimeError("authorized PC executor and output store are not bound")
    deadline = None if total_timeout is None else time.monotonic() + total_timeout
    results = []
    completed = 0
    for index, step in enumerate(steps):
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            results.append(_result(index, False, "batch timeout"))
            break
        mailbox = Queue(maxsize=1)
        worker = Thread(
            target=lambda i=index, s=step: mailbox.put(_run_step(i, s, owner, services)),
            daemon=True,
        )
        worker.start()
        try:
            outcome = mailbox.get(timeout=None if deadline is None else max(0, deadline - time.monotonic()))
        except Empty:
            results.append(_result(index, False, "batch timeout"))
            break
        results.append(outcome)
        if outcome["ok"]:
            completed += 1
        elif stop_on_error:
            break
    return {"results": results, "completed": completed}
