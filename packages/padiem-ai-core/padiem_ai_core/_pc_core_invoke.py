"""Read-only PC decision/invoke diagnostics; never an execution policy.

The observer task sleeps once and only prints. It never awaits, cancels, or
changes the deadline/progress of the operation being observed. Finishing a
boundary (including an exception/cancellation) cancels only its own observer.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager

_PC_TOOLS = frozenset({
    "claw.pc.query_drives", "claw.pc.list_files", "claw.pc.read_file",
    "claw.pc.write_file", "claw.pc.move_file", "claw.pc.delete_file",
})
_STAGES = frozenset({"decision", "run_active", "run_guard", "tool_runtime_wait_for",
                     "runtime_checks", "handler_wait_for", "permissions_passed",
                     "schema_passed", "input_schema_rejected", "invocation", "drives_branch"})
_sleep = asyncio.sleep


def pc_core_log(stage: str, tool_id: str | None, state: str, **metadata) -> None:
    # Never interpolate model/tool arguments, arbitrary identifiers or errors.
    if not isinstance(tool_id, str) or tool_id not in _PC_TOOLS or stage not in _STAGES:
        return
    if state not in {"enter", "done", "still_waiting"}:
        return
    try:
        suffix = ""
        if type(metadata.get("guard_injected")) is bool:
            suffix += f" guard_injected={str(metadata['guard_injected']).lower()}"
        if "timeout" in metadata:
            timeout = metadata["timeout"]
            if timeout is None or type(timeout) in (int, float):
                suffix += f" timeout={timeout}"
        print(f"pc_core_invoke stage={stage} tool={tool_id} state={state}{suffix}", flush=True)
    except Exception:
        pass  # Diagnostics cannot break a successful answer or mask a failure.


async def _observe(stage: str, tool_id: str, metadata) -> None:
    try:
        await _sleep(30.0)
        pc_core_log(stage, tool_id, "still_waiting", **metadata)
    except asyncio.CancelledError:
        pass  # Only this diagnostic task is cancelled by boundary completion.


@contextmanager
def pc_core_stage(stage: str, tool_id: str | None, **metadata):
    if not isinstance(tool_id, str) or tool_id not in _PC_TOOLS or stage not in _STAGES:
        yield
        return
    pc_core_log(stage, tool_id, "enter", **metadata)
    observer = _observe(stage, tool_id, metadata)
    try:
        watcher = asyncio.create_task(observer)
    except Exception:
        observer.close()
        watcher = None
    try:
        yield
    finally:
        if watcher is not None:
            watcher.cancel()
        pc_core_log(stage, tool_id, "done", **metadata)
