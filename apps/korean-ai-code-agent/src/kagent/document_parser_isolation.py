"""#2824-S3A: hard-timeout process isolation for the kagent document parser.

Composition order — the gate still runs before any parser, and the parser now
runs in its own process:

.. code-block:: text

    raw bytes
    -> inspect_file()                        (common pre-parser gate, #2824)
    -> admission decision                    (bounded note on refusal)
    -> isolated parser boundary              (this module, kagent-local only)
    -> child: extract_binary_document()      (Core parser, its own process)
    -> bounded result

Scope of this slice
-------------------
``TIMEOUT_OWNER=KAGENT_LOCAL_PROCESS_ISOLATION``. This module owns a **hard**
timeout for the local ``kagent`` route only. It is not the #2824 whole-issue
answer: the B62 Chat and Engine Worker routes reach the Core parser directly and
stay unbounded, so the honest global verdict after this slice is
``PARSER_TIMEOUT_BOUNDED=PARTIAL``. A Worker route cannot host this mechanism —
see the compatibility note below.

Hard timeout
------------
``PARSER_TIMEOUT_ACTION=KILL``. The timeout is enforced by a real process
boundary, not by a cooperative cancel:

.. code-block:: text

    wait(timeout) -> terminate() -> bounded wait -> kill() -> bounded wait

``asyncio.wait_for``, ``ThreadPoolExecutor`` futures and any other
task/future/thread timeout are **not** used here and must never be reported as a
hard timeout: none of them can preempt synchronous CPU work inside one process,
so a hung parser keeps the interpreter busy no matter how small the budget is.
This module therefore imports no ``asyncio`` and no executor.

``timeout != cancellation`` (semantic reference:
``kagent.windows_local_executor``): ``timed_out`` is a distinct outcome from
``failed`` and from ``rejected``, a terminated child reports no exit code, and
this boundary exposes **no** cancellation entry point at all.

Windows and Pyodide compatibility
---------------------------------
Windows and Linux both support the ladder above through ``subprocess``. Pyodide
/ Cloudflare Workers does **not** — ``subprocess`` and ``multiprocessing`` are
unavailable there — which is exactly why the Worker routes are out of scope for
this slice instead of being given a fake ``asyncio`` timeout. On Windows
``terminate()`` is an immediate ``TerminateProcess`` and on POSIX it is
``SIGTERM``; the child is written to start nothing (see
:mod:`kagent.document_parser_child`), so no grandchild survives either.

Child authority
---------------
The parent starts exactly one reviewed module through the current interpreter
(``sys.executable -P -m kagent.document_parser_child``). ``-P`` keeps the
working directory out of the child's ``sys.path``, so a directory containing a
shadowing ``kagent`` package cannot be imported by accident. The command never
contains the caller's filename, the executable is never caller-supplied,
``shell=False`` is explicit, no temporary file is created, and the child receives
a bounded environment built from this module's own location rather than the
caller's raw environment.

Authority boundaries
--------------------
- ``CORE != PROCESS_AUTHORITY``. No Core source gains process, thread or signal
  authority in this slice; the child only calls the existing Core parser.
- ``BOUNDARY != TRUSTING_CONSUMER``. A malformed, oversized, extra-keyed or
  unbounded-code child report fails closed; child stderr is drained and never
  surfaced, so a traceback cannot become a public note.
- ``ISOLATION != NEW_PARSER``. No format decision, no bound and no document
  semantics are re-implemented here; the gate decides admission and Core parses.
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from padiem_ai_core.document_normalization import MAX_BINARY_DOCUMENT_BYTES

from .document_parser_contract import (
    CHILD_MODULE_NAME,
    MAX_CHILD_ENVELOPE_BYTES,
    MAX_CHILD_ERROR_BYTES,
    MAX_CHILD_OUTPUT_BYTES,
    PARSER_INPUT_REASON_CODE,
    PARSER_ISOLATION_FAILURE_REASON_CODE,
    PARSER_TIMEOUT_REASON_CODE,
    ParserReport,
    decode_report,
    encode_envelope,
    is_bounded_reason_code,
)

__all__ = [
    "DEFAULT_PARSER_ISOLATION_POLICY",
    "DOCUMENT_PARSER_TIMEOUT_MAX_SECONDS",
    "DOCUMENT_PARSER_TIMEOUT_SECONDS",
    "PARSER_INPUT_REASON_CODE",
    "PARSER_ISOLATION_FAILURE_REASON_CODE",
    "PARSER_TIMEOUT_ACTION",
    "PARSER_TIMEOUT_REASON_CODE",
    "IsolatedParseResult",
    "ParserIsolationError",
    "ParserIsolationPolicy",
    "ParserOutcome",
    "child_import_roots",
    "extract_binary_document_isolated",
]

#: CENTRAL decision for this slice. Bounded on both sides: the default is the
#: largest value a policy may request, so no caller can widen the ceiling.
DOCUMENT_PARSER_TIMEOUT_SECONDS = 30.0
DOCUMENT_PARSER_TIMEOUT_MAX_SECONDS = 30.0

#: The action a timeout must take. A policy may not weaken this.
PARSER_TIMEOUT_ACTION = "kill"

#: The only caller environment values the child inherits. They are OS-standard
#: process and user-profile locations, not caller input and not secrets:
#: ``SystemRoot``/``WINDIR``/``SystemDrive`` are needed for the interpreter to
#: start on Windows, and ``APPDATA``/``USERPROFILE``/``HOME`` are how the child's
#: own ``site`` module finds the same user site directory its parent used. That
#: matters because the document extra's dependencies live there in some
#: environments, and the alternative — putting the user site on ``PYTHONPATH`` —
#: would place it *ahead* of the standard library and let a stray module there
#: shadow a stdlib module. No TEMP/TMP entry is granted: the child is not allowed
#: to create a temporary file.
_CHILD_ENV_NAMES = (
    "SystemRoot",
    "WINDIR",
    "SystemDrive",
    "APPDATA",
    "USERPROFILE",
    "HOME",
)

_DRAIN_CHUNK_BYTES = 4096


class ParserIsolationError(RuntimeError):
    """Programming-error signal. Policy outcomes are results, not exceptions."""


class ParserOutcome(str, Enum):
    """Bounded outcome vocabulary of the isolated parser boundary.

    ``REJECTED`` means the child ran and Core refused the document with a
    bounded reason code. ``FAILED`` means the boundary could not produce a
    trustworthy result. There is deliberately no cancellation term: this
    boundary has no cancellation authority.
    """

    COMPLETED = "completed"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ParserIsolationPolicy:
    """Bounded parser-isolation policy, validated on construction."""

    timeout_seconds: float = DOCUMENT_PARSER_TIMEOUT_SECONDS
    terminate_grace_seconds: float = 2.0
    kill_grace_seconds: float = 2.0
    drain_join_seconds: float = 2.0
    timeout_action: str = PARSER_TIMEOUT_ACTION
    max_envelope_bytes: int = MAX_CHILD_ENVELOPE_BYTES
    max_output_bytes: int = MAX_CHILD_OUTPUT_BYTES
    max_error_bytes: int = MAX_CHILD_ERROR_BYTES

    def __post_init__(self) -> None:
        for name in ("timeout_seconds", "terminate_grace_seconds", "kill_grace_seconds", "drain_join_seconds"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0
            ):
                raise ParserIsolationError(f"{name} must be a positive finite number")
        if float(self.timeout_seconds) > DOCUMENT_PARSER_TIMEOUT_MAX_SECONDS:
            raise ParserIsolationError(
                "timeout_seconds exceeds the bounded parser timeout ceiling "
                f"({DOCUMENT_PARSER_TIMEOUT_MAX_SECONDS:g})"
            )
        if self.timeout_action != PARSER_TIMEOUT_ACTION:
            raise ParserIsolationError(
                f"timeout_action must be {PARSER_TIMEOUT_ACTION!r}; a timeout cannot be weakened"
            )
        for name in ("max_envelope_bytes", "max_output_bytes", "max_error_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ParserIsolationError(f"{name} must be a positive integer")


DEFAULT_PARSER_ISOLATION_POLICY = ParserIsolationPolicy()


@dataclass(frozen=True, slots=True)
class IsolatedParseResult:
    """Bounded result of one isolated parse attempt.

    A result never carries payload bytes, a host path, child stderr, exception
    text or a traceback. ``reason_code`` is a bounded identifier, so the public
    note the caller builds from it can only ever contain enumeration values.
    """

    outcome: ParserOutcome
    reason_code: str
    text: str | None = None
    child_exit_code: int | None = None
    terminated_by_kill: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, ParserOutcome):
            raise ParserIsolationError("outcome must be a ParserOutcome")
        if not is_bounded_reason_code(self.reason_code):
            raise ParserIsolationError("reason_code must be a bounded reason identifier")
        if not isinstance(self.terminated_by_kill, bool):
            raise ParserIsolationError("terminated_by_kill must be boolean")
        if self.child_exit_code is not None and (
            isinstance(self.child_exit_code, bool) or not isinstance(self.child_exit_code, int)
        ):
            raise ParserIsolationError("child_exit_code must be an integer or None")

        if self.outcome is ParserOutcome.COMPLETED:
            if not isinstance(self.text, str) or self.text == "":
                raise ParserIsolationError("a completed parse must carry extracted text")
        elif self.text is not None:
            raise ParserIsolationError("only a completed parse may carry text")

        if self.outcome is ParserOutcome.TIMED_OUT:
            # A terminated child has no meaningful exit code, and a timeout is
            # never reported as a cancel.
            if self.child_exit_code is not None:
                raise ParserIsolationError("a timed-out parse must not report a child exit code")
            if self.reason_code != PARSER_TIMEOUT_REASON_CODE:
                raise ParserIsolationError("a timed-out parse must use the bounded timeout code")


class _ChildProcess(Protocol):
    """The slice of ``subprocess.Popen`` the boundary depends on."""

    stdin: Any
    stdout: Any
    stderr: Any
    returncode: int | None

    def wait(self, timeout: float | None = None) -> int | None: ...

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


SpawnChild = Callable[[list[str], dict[str, str]], _ChildProcess]


@dataclass(slots=True)
class _BoundedSink:
    """Bounded stream sink that still drains, so the pipe cannot fill.

    ``total`` counts everything seen, ``kept`` holds at most ``limit`` bytes and
    ``exceeded`` records that the child produced more than the boundary accepts.
    """

    limit: int
    kept: bytearray = field(default_factory=bytearray)
    total: int = 0
    exceeded: bool = False

    def feed(self, chunk: bytes) -> None:
        self.total += len(chunk)
        remaining = self.limit - len(self.kept)
        if remaining > 0:
            self.kept.extend(chunk[:remaining])
        if self.total > self.limit:
            self.exceeded = True


def _child_argv() -> list[str] | None:
    """The fixed command line, or ``None`` when no interpreter is available.

    The caller's filename, media type and payload never take part in command
    construction; they travel on stdin.
    """

    executable = sys.executable
    if not isinstance(executable, str) or not executable.strip():
        return None
    # ``-P`` keeps the working directory out of the child's ``sys.path`` so a
    # shadowing ``kagent`` package next to the parsed file cannot be imported.
    return [executable, "-P", "-m", CHILD_MODULE_NAME]


def child_import_roots() -> tuple[str, ...]:
    """The import roots the child is given, in precedence order.

    One root only: the reviewed ``kagent`` tree this module lives in, so the
    child always runs exactly the code its parent is running. Nothing from the
    caller's environment is added, and the root contains no stdlib module name,
    so a ``PYTHONPATH`` entry cannot shadow the standard library. Third-party
    dependencies resolve through the child's own ``site`` processing — the same
    mechanism its parent used.
    """

    return (str(Path(__file__).resolve().parent.parent),)


def _child_environment() -> dict[str, str]:
    """Bounded child environment derived from the reviewed module's own location.

    The child receives an explicit import root, a deterministic text encoding and
    the OS-standard user-profile locations its ``site`` module needs. Every other
    caller variable — including anything the caller supplied — is dropped.
    """

    environment = {
        "PYTHONPATH": os.pathsep.join(child_import_roots()),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    }
    for name in _CHILD_ENV_NAMES:
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


def _spawn_parser_child(argv: list[str], environment: dict[str, str]) -> _ChildProcess:
    """Start the reviewed child. No process group, no shell, no temp file."""

    return subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        env=environment,
        close_fds=True,
        # Windows only: hide the console window. Deliberately NOT
        # CREATE_NEW_PROCESS_GROUP — the child starts nothing, so direct-child
        # terminate/kill already covers the whole tree.
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _drain(stream: Any, sink: _BoundedSink) -> None:
    try:
        while True:
            chunk = stream.read(_DRAIN_CHUNK_BYTES)
            if not chunk:
                break
            sink.feed(chunk)
    except (OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _write_envelope(stream: Any, envelope: bytes) -> None:
    try:
        stream.write(envelope)
        stream.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except Exception:
            pass


def _failed(*, reason_code: str, exit_code: int | None = None, killed: bool = False) -> IsolatedParseResult:
    return IsolatedParseResult(
        outcome=ParserOutcome.FAILED,
        reason_code=reason_code,
        child_exit_code=exit_code,
        terminated_by_kill=killed,
    )


def extract_binary_document_isolated(
    *,
    name: str,
    media_type: str,
    payload: bytes,
    policy: ParserIsolationPolicy = DEFAULT_PARSER_ISOLATION_POLICY,
    spawn: SpawnChild | None = None,
) -> IsolatedParseResult:
    """Parse one admitted binary document in a dedicated, killable child process.

    The caller is responsible for the pre-parser gate: this function is only
    reached for input the gate already admitted. It still fails closed on its
    own input bound and never starts a process it cannot bound.

    ``spawn`` exists so the kill ladder can be exercised against a real process
    under test control without giving production code a bypass switch.
    """

    if not isinstance(policy, ParserIsolationPolicy):
        raise ParserIsolationError("policy must be a ParserIsolationPolicy")
    if not isinstance(name, str) or not isinstance(media_type, str):
        raise ParserIsolationError("name and media_type must be strings")
    if not isinstance(payload, (bytes, bytearray)):
        raise ParserIsolationError("payload must be bytes")

    if not payload or len(payload) > MAX_BINARY_DOCUMENT_BYTES:
        # Defence in depth: the gate refuses this first, so this path means the
        # caller bypassed the gate. Refuse it without spending a process.
        return _failed(reason_code=PARSER_INPUT_REASON_CODE)

    try:
        envelope = encode_envelope(name=name, media_type=media_type, payload=payload)
    except ValueError:
        return _failed(reason_code=PARSER_INPUT_REASON_CODE)
    if len(envelope) > policy.max_envelope_bytes:
        return _failed(reason_code=PARSER_INPUT_REASON_CODE)

    argv = _child_argv()
    if argv is None:
        return _failed(reason_code=PARSER_ISOLATION_FAILURE_REASON_CODE)

    spawn_child = spawn or _spawn_parser_child
    try:
        process = spawn_child(argv, _child_environment())
    except (OSError, ValueError):
        # A process that could not start is a bounded failure, never an
        # exception carrying a host path into the caller's note.
        return _failed(reason_code=PARSER_ISOLATION_FAILURE_REASON_CODE)

    if process.stdin is None or process.stdout is None or process.stderr is None:
        process.kill()
        return _failed(reason_code=PARSER_ISOLATION_FAILURE_REASON_CODE)

    stdout_sink = _BoundedSink(limit=policy.max_output_bytes)
    stderr_sink = _BoundedSink(limit=policy.max_error_bytes)
    writer = threading.Thread(target=_write_envelope, args=(process.stdin, envelope), daemon=True)
    stdout_thread = threading.Thread(target=_drain, args=(process.stdout, stdout_sink), daemon=True)
    stderr_thread = threading.Thread(target=_drain, args=(process.stderr, stderr_sink), daemon=True)
    writer.start()
    stdout_thread.start()
    stderr_thread.start()

    timed_out = False
    escalated = False
    try:
        try:
            process.wait(timeout=policy.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.terminate()
            try:
                process.wait(timeout=policy.terminate_grace_seconds)
            except subprocess.TimeoutExpired:
                escalated = True
                process.kill()
                try:
                    process.wait(timeout=policy.kill_grace_seconds)
                except subprocess.TimeoutExpired:
                    pass
    finally:
        writer.join(timeout=policy.drain_join_seconds)
        stdout_thread.join(timeout=policy.drain_join_seconds)
        stderr_thread.join(timeout=policy.drain_join_seconds)

    if timed_out:
        if process.poll() is None:
            # A child that outlived the full ladder is not a timeout we can
            # trust, so it fails closed instead of being reported as one.
            return _failed(
                reason_code=PARSER_ISOLATION_FAILURE_REASON_CODE,
                exit_code=process.returncode,
                killed=escalated,
            )
        return IsolatedParseResult(
            outcome=ParserOutcome.TIMED_OUT,
            reason_code=PARSER_TIMEOUT_REASON_CODE,
            child_exit_code=None,
            terminated_by_kill=escalated,
        )

    exit_code = process.returncode
    if process.poll() is None or exit_code != 0:
        return _failed(reason_code=PARSER_ISOLATION_FAILURE_REASON_CODE, exit_code=exit_code)
    if stdout_sink.exceeded:
        return _failed(reason_code=PARSER_ISOLATION_FAILURE_REASON_CODE, exit_code=exit_code)

    report: ParserReport | None = decode_report(bytes(stdout_sink.kept))
    if report is None:
        return _failed(reason_code=PARSER_ISOLATION_FAILURE_REASON_CODE, exit_code=exit_code)
    if report.ok:
        text = report.text
        if text is None:  # pragma: no cover - ParserReport guarantees the shape
            return _failed(reason_code=PARSER_ISOLATION_FAILURE_REASON_CODE, exit_code=exit_code)
        return IsolatedParseResult(
            outcome=ParserOutcome.COMPLETED,
            reason_code="ok",
            text=text,
            child_exit_code=exit_code,
        )
    code = report.code
    if code is None:  # pragma: no cover - ParserReport guarantees the shape
        return _failed(reason_code=PARSER_ISOLATION_FAILURE_REASON_CODE, exit_code=exit_code)
    return IsolatedParseResult(
        outcome=ParserOutcome.REJECTED,
        reason_code=code,
        child_exit_code=exit_code,
    )
