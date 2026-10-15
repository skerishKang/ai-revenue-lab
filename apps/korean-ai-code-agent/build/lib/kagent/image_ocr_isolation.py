"""#2828: hard-timeout process isolation for the kagent-local OCR adapter.

Composition order — the gate and the Core transform still run before any OCR, and
the OCR runtime then runs in its own process:

.. code-block:: text

    caller filename + in-memory bytes
    -> kagent.file_intake_safety.inspect_file()      (gate, always first, #2824)
    -> admission decision must be SAFE_CANDIDATE and an image format
    -> padiem_ai_core.image_helpers.transform_image() (sanitized single-frame PNG, #3037)
    -> isolated OCR boundary                         (this module, kagent-local only)
    -> child: PaddleOCR against explicit local model dirs (orientation OFF)
    -> bounded result with provenance

Scope of this slice
-------------------
``OCR_TIMEOUT_OWNER=KAGENT_LOCAL_PROCESS_ISOLATION``. This module owns a **hard**
timeout for the local ``kagent`` route only. It is a bounded, non-Production
adapter: the heavy PaddleOCR/PaddleX stack is deliberately absent from the
product manifests, so an environment without the runtime and explicit local
model directories gets the bounded ``image_ocr_runtime_missing`` refusal rather
than a silent fallback or a download.

Hard timeout
------------
``OCR_TIMEOUT_ACTION=KILL``. The timeout is enforced by a real process boundary,
not by a cooperative cancel:

.. code-block:: text

    wait(timeout) -> terminate() -> bounded wait -> kill() -> bounded wait

``asyncio.wait_for``, ``ThreadPoolExecutor`` futures and any other
task/future/thread timeout are **not** used here and must never be reported as a
hard timeout: none of them can preempt synchronous CPU work inside one process,
so a hung model keeps the interpreter busy no matter how small the budget is.
This module therefore imports no ``asyncio`` and no executor.

``OCR_TIMEOUT_LIFECYCLE_BOUNDED=YES``. Bounding the OCR wait alone would not be
enough: a policy free to request a 600s terminate grace still has an effectively
unbounded hard timeout. Every stage of the ladder therefore has a canonical
ceiling, and :class:`OcrIsolationPolicy` refuses any value outside
``0 < value <= ceiling``. The byte ceilings are bounded the same way
(``IPC_MEMORY_POLICY_WIDENABLE=NO``): a policy may lower them for fail-closed
exercise but can never accept a larger child result than the contract allows.

``timeout != cancellation``: ``timed_out`` is a distinct outcome from ``failed``
and from ``rejected``, a terminated child reports no exit code, and this
boundary exposes **no** cancellation entry point at all.

Child authority
---------------
The parent starts exactly one reviewed module through the current interpreter
(``sys.executable -P -m kagent.image_ocr_child``). ``-P`` keeps the working
directory out of the child's ``sys.path``, so a directory containing a shadowing
``kagent`` package cannot be imported by accident. The command never contains the
caller's filename, the sanitized PNG or the model directories, the executable is
never caller-supplied, ``shell=False`` is explicit, no temporary file is created
by the parent, and the child receives a bounded environment built from this
module's own location rather than the caller's raw environment.

Authority boundaries
--------------------
- ``CORE != OCR_AUTHORITY``. No Core source gains OCR, process, thread or signal
  authority in this slice; the parent only calls the existing Core transform.
- ``ORIGINAL_SOURCE_BYTES_TO_OCR_CHILD=0``. The #2824 gate and the #3037 Core
  transform own every untrusted byte, and only the Core-produced canonical
  sanitized PNG is handed to the child. The caller's original payload is never
  part of the envelope, the command line, the environment or a temp file.
- ``SECOND_UNTRUSTED_IMAGE_DECODER=0``. This module does not decode pixels. The
  canonical PNG is validated by reading its signature and ``IHDR`` header bytes
  and hashing them — never by invoking a decoder on the child's behalf. The
  isolated PaddleOCR child *does* decode the canonical PNG inside its own
  process, which is explicitly allowed: that is the model's own pipeline over
  Core's output, not a second decoder for untrusted input.
- ``CHILD != UNTRUSTED_MODEL_AUTHORITY``. Both model manifests are checked for
  exact filenames, exact byte counts and exact SHA-256 digests, with a symlinked
  root refused, on the parent before a process exists and again in the child
  before PaddleOCR is imported or built.
- ``BOUNDARY != TRUSTING_CONSUMER``. A malformed, oversized, extra-keyed or
  unbounded-code child report fails closed; child stderr is drained and never
  surfaced, so a traceback cannot become a public note.
- ``OCR != PDF_AUTHORITY``. Nothing in this module reads, writes, parses or emits
  a PDF, and the model directories it forwards are never PDF paths.
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from padiem_ai_core.image_helpers import MAX_IMAGE_BYTES, MAX_OUTPUT_BYTES

from .image_ocr_contract import (
    CHILD_MODULE_NAME,
    DETECTOR_MODEL_MANIFEST,
    MAX_OCR_CHILD_ENVELOPE_BYTES,
    MAX_OCR_CHILD_ERROR_BYTES,
    MAX_OCR_CHILD_OUTPUT_BYTES,
    MAX_OCR_INPUT_PIXELS,
    MAX_OCR_MODEL_DIR_CHARS,
    OCR_INPUT_REASON_CODE,
    OCR_ISOLATION_FAILURE_REASON_CODE,
    OCR_RUNTIME_MISSING_REASON_CODE,
    OCR_TIMEOUT_REASON_CODE,
    RECOGNIZER_MODEL_MANIFEST,
    OcrProvenance,
    OcrReport,
    OcrResult,
    decode_report,
    encode_envelope,
    inspect_canonical_png,
    is_bounded_reason_code,
    validate_model_manifest,
)

__all__ = [
    "DEFAULT_OCR_ISOLATION_POLICY",
    "IMAGE_OCR_DRAIN_JOIN_MAX_SECONDS",
    "IMAGE_OCR_KILL_GRACE_MAX_SECONDS",
    "IMAGE_OCR_MAX_IMAGE_PIXELS",
    "IMAGE_OCR_MAX_INPUT_BYTES",
    "IMAGE_OCR_MAX_NORMALIZED_BYTES",
    "IMAGE_OCR_TERMINATE_GRACE_MAX_SECONDS",
    "IMAGE_OCR_TIMEOUT_MAX_SECONDS",
    "IMAGE_OCR_TIMEOUT_SECONDS",
    "OCR_TIMEOUT_ACTION",
    "IsolatedOcrResult",
    "OcrIsolationError",
    "OcrIsolationPolicy",
    "OcrOutcome",
    "child_import_roots",
    "model_manifests_present",
    "ocr_png_isolated",
]

#: CENTRAL decision for this slice. Bounded on both sides: the default is the
#: largest value a policy may request, so no caller can widen the ceiling.
#: OCR is slower than document parsing, so the budget is larger — but it is a
#: finite process budget, and a model that exceeds it is terminated and killed.
IMAGE_OCR_TIMEOUT_SECONDS = 120.0
IMAGE_OCR_TIMEOUT_MAX_SECONDS = 120.0

#: Canonical grace/join ceilings. ``OCR_TIMEOUT_LIFECYCLE_BOUNDED=YES`` only holds
#: if *every* stage of the ladder is bounded, not just the OCR wait: a policy
#: free to request a 600s terminate grace has an effectively unbounded hard
#: timeout while still passing a ``timeout_seconds <= 120`` check. The defaults
#: on :class:`OcrIsolationPolicy` are these ceilings, so a caller can only ever
#: narrow the lifecycle, never widen it.
IMAGE_OCR_TERMINATE_GRACE_MAX_SECONDS = 5.0
IMAGE_OCR_KILL_GRACE_MAX_SECONDS = 5.0
IMAGE_OCR_DRAIN_JOIN_MAX_SECONDS = 5.0

#: The action a timeout must take. A policy may not weaken this.
OCR_TIMEOUT_ACTION = "kill"

#: Image bounds the parent re-checks on the sanitized PNG. These are the existing
#: Core bounds, not new ones: the Core transform already refuses more, and the
#: re-check is defence in depth against a bound that drifted or was bypassed.
IMAGE_OCR_MAX_INPUT_BYTES = MAX_IMAGE_BYTES
IMAGE_OCR_MAX_NORMALIZED_BYTES = MAX_OUTPUT_BYTES
IMAGE_OCR_MAX_IMAGE_PIXELS = MAX_OCR_INPUT_PIXELS

#: Every bounded float knob and its inclusive ceiling. A policy value outside
#: ``0 < value <= ceiling`` is refused at construction, so no caller can convert
#: the bounded ladder into an unbounded wait.
_BOUNDED_SECONDS_CEILINGS = (
    ("timeout_seconds", IMAGE_OCR_TIMEOUT_MAX_SECONDS),
    ("terminate_grace_seconds", IMAGE_OCR_TERMINATE_GRACE_MAX_SECONDS),
    ("kill_grace_seconds", IMAGE_OCR_KILL_GRACE_MAX_SECONDS),
    ("drain_join_seconds", IMAGE_OCR_DRAIN_JOIN_MAX_SECONDS),
)

#: Every bounded byte knob and its inclusive ceiling. ``IPC_MEMORY_POLICY_WIDENABLE=NO``:
#: a policy may lower these for fail-closed exercise but can never accept a
#: larger child result than the contract already allows.
_BOUNDED_BYTES_CEILINGS = (
    ("max_envelope_bytes", MAX_OCR_CHILD_ENVELOPE_BYTES),
    ("max_output_bytes", MAX_OCR_CHILD_OUTPUT_BYTES),
    ("max_error_bytes", MAX_OCR_CHILD_ERROR_BYTES),
)

#: The only caller environment values the child inherits. They are OS-standard
#: process and user-profile locations, not caller input and not secrets:
#: ``SystemRoot``/``WINDIR``/``SystemDrive`` are needed for the interpreter to
#: start on Windows, and ``APPDATA``/``USERPROFILE``/``HOME`` are how the child's
#: own ``site`` module finds the same user site directory its parent used. That
#: matters because the OCR extra's dependencies live there in some environments,
#: and the alternative — putting the user site on ``PYTHONPATH`` — would place it
#: *ahead* of the standard library and let a stray module there shadow a stdlib
#: module. TEMP/TMP are not caller-controlled: the parent resolves its own OS
#: system temporary directory once and pins that value for the child. This keeps
#: a hard-killed child's derived canonical PNG out of the repository working
#: tree; the normal path still unlinks the file immediately.
_CHILD_ENV_NAMES = (
    "SystemRoot",
    "WINDIR",
    "SystemDrive",
    "APPDATA",
    "USERPROFILE",
    "HOME",
)

_DRAIN_CHUNK_BYTES = 4096


class OcrIsolationError(RuntimeError):
    """Programming-error signal. Policy outcomes are results, not exceptions."""


class OcrOutcome(str, Enum):
    """Bounded outcome vocabulary of the isolated OCR boundary.

    ``REJECTED`` means the child ran and the OCR step refused the image or its
    result with a bounded reason code. ``FAILED`` means the boundary could not
    produce a trustworthy result. There is deliberately no cancellation term:
    this boundary has no cancellation authority.
    """

    COMPLETED = "completed"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class OcrIsolationPolicy:
    """Bounded OCR-isolation policy, validated on construction."""

    timeout_seconds: float = IMAGE_OCR_TIMEOUT_SECONDS
    terminate_grace_seconds: float = IMAGE_OCR_TERMINATE_GRACE_MAX_SECONDS
    kill_grace_seconds: float = IMAGE_OCR_KILL_GRACE_MAX_SECONDS
    drain_join_seconds: float = IMAGE_OCR_DRAIN_JOIN_MAX_SECONDS
    timeout_action: str = OCR_TIMEOUT_ACTION
    max_envelope_bytes: int = MAX_OCR_CHILD_ENVELOPE_BYTES
    max_output_bytes: int = MAX_OCR_CHILD_OUTPUT_BYTES
    max_error_bytes: int = MAX_OCR_CHILD_ERROR_BYTES

    def __post_init__(self) -> None:
        # Positive-only validation is not enough: it would leave every knob
        # unbounded in practice. Each value is checked against its canonical
        # ceiling as well as its floor.
        for name, ceiling in _BOUNDED_SECONDS_CEILINGS:
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) <= 0
            ):
                raise OcrIsolationError(f"{name} must be a positive finite number")
            if float(value) > ceiling:
                raise OcrIsolationError(
                    f"{name} must be <= the canonical ceiling ({ceiling:g}s); "
                    "a bounded timeout lifecycle cannot be widened by a policy"
                )
        for name, ceiling in _BOUNDED_BYTES_CEILINGS:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise OcrIsolationError(f"{name} must be a positive integer")
            if value > ceiling:
                raise OcrIsolationError(
                    f"{name} must be <= the canonical ceiling ({ceiling} bytes); "
                    "the IPC memory policy cannot be widened by a policy"
                )
        if self.timeout_action != OCR_TIMEOUT_ACTION:
            raise OcrIsolationError(
                f"timeout_action must be {OCR_TIMEOUT_ACTION!r}; a timeout cannot be weakened"
            )


DEFAULT_OCR_ISOLATION_POLICY = OcrIsolationPolicy()


@dataclass(frozen=True, slots=True)
class IsolatedOcrResult:
    """Bounded result of one isolated OCR attempt.

    A result never carries payload bytes, a host path, a model directory, child
    stderr, exception text or a traceback. ``reason_code`` is a bounded
    identifier, so the public note the caller builds from it can only ever
    contain enumeration values. ``provenance`` reports the runtime and model
    revisions by name only — the model *directories* never cross back.
    """

    outcome: OcrOutcome
    reason_code: str
    provenance: OcrProvenance | None = None
    results: tuple[OcrResult, ...] = ()
    child_exit_code: int | None = None
    terminated_by_kill: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, OcrOutcome):
            raise OcrIsolationError("outcome must be an OcrOutcome")
        if not is_bounded_reason_code(self.reason_code):
            raise OcrIsolationError("reason_code must be a bounded reason identifier")
        if not isinstance(self.terminated_by_kill, bool):
            raise OcrIsolationError("terminated_by_kill must be boolean")
        if self.child_exit_code is not None and (
            isinstance(self.child_exit_code, bool) or not isinstance(self.child_exit_code, int)
        ):
            raise OcrIsolationError("child_exit_code must be an integer or None")
        if not isinstance(self.results, tuple):
            raise OcrIsolationError("results must be a tuple")

        if self.outcome is OcrOutcome.COMPLETED:
            if not isinstance(self.provenance, OcrProvenance):
                raise OcrIsolationError("a completed OCR must carry provenance")
            if self.reason_code != "ok":
                raise OcrIsolationError("a completed OCR uses the ok reason code")
        else:
            if self.provenance is not None or self.results:
                raise OcrIsolationError("only a completed OCR may carry provenance and results")

        if self.outcome is OcrOutcome.TIMED_OUT:
            # A terminated child has no meaningful exit code, and a timeout is
            # never reported as a cancel.
            if self.child_exit_code is not None:
                raise OcrIsolationError("a timed-out OCR must not report a child exit code")
            if self.reason_code != OCR_TIMEOUT_REASON_CODE:
                raise OcrIsolationError("a timed-out OCR must use the bounded timeout code")

    def safe_dict(self) -> dict[str, object]:
        """Bounded public projection.

        Contains no image bytes, no model directory, no child stderr and no
        exception text: the note a caller can build from this is bounded by
        construction, not by convention.
        """

        return {
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
            "provenance": self.provenance.safe_dict() if self.provenance is not None else None,
            "results": [result.safe_dict() for result in self.results],
            "child_exit_code": self.child_exit_code,
            "terminated_by_kill": self.terminated_by_kill,
        }


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

    The sanitized PNG, the caller's filename and the model directories never take
    part in command construction; they travel on stdin.
    """

    executable = sys.executable
    if not isinstance(executable, str) or not executable.strip():
        return None
    # ``-P`` keeps the working directory out of the child's ``sys.path`` so a
    # shadowing ``kagent`` package next to the caller's file cannot be imported.
    return [executable, "-P", "-m", CHILD_MODULE_NAME]


def child_import_roots() -> tuple[str, ...]:
    """The import roots the child is given, in precedence order.

    Two roots: the reviewed ``kagent`` tree this module lives in, so the child
    always runs exactly the code its parent is running, and the ``padiem_ai_core``
    package directory the parent itself imported, so the child resolves the same
    Core image bounds rather than a second installed copy. Nothing from the
    caller's environment is added, and neither root contains a stdlib module
    name, so a ``PYTHONPATH`` entry cannot shadow the standard library.
    """

    kagent_root = Path(__file__).resolve().parent.parent
    repo_root = kagent_root.parent.parent.parent
    return (str(kagent_root), str(repo_root / "packages" / "padiem-ai-core"))


def _child_environment() -> dict[str, str]:
    """Bounded child environment derived from the reviewed module's own location.

    The child receives explicit import roots, a deterministic text encoding and
    the OS-standard user-profile locations its ``site`` module needs. Every other
    caller variable — including anything the caller supplied — is dropped.
    """

    environment = {
        "PYTHONPATH": os.pathsep.join(child_import_roots()),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
        # Resolve the system temp directory in the parent and pass only this
        # concrete value. The child therefore cannot fall back to its inherited
        # working directory when a hard kill prevents its normal unlink.
        "TEMP": str(Path(tempfile.gettempdir()).resolve()),
        "TMP": str(Path(tempfile.gettempdir()).resolve()),
    }
    for name in _CHILD_ENV_NAMES:
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


def _spawn_ocr_child(argv: list[str], environment: dict[str, str]) -> _ChildProcess:
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


def _failed(
    *, reason_code: str, exit_code: int | None = None, killed: bool = False
) -> IsolatedOcrResult:
    return IsolatedOcrResult(
        outcome=OcrOutcome.FAILED,
        reason_code=reason_code,
        child_exit_code=exit_code,
        terminated_by_kill=killed,
    )


def _valid_model_dir(value: Any) -> bool:
    """Whether ``value`` is a bounded, absolute, existing local directory.

    Checked on the parent side as well as in the contract, so an unprovisioned or
    remote-looking model source is refused before a process is ever started.
    """

    if not isinstance(value, str) or not value or len(value) > MAX_OCR_MODEL_DIR_CHARS:
        return False
    if "\x00" in value or "\n" in value or "\r" in value:
        return False
    try:
        return os.path.isdir(value)
    except (OSError, ValueError):
        return False


def model_manifests_present(detector_dir: Any, recognizer_dir: Any) -> bool:
    """Whether both model roots hold exactly the reviewed official manifests.

    The parent runs this **before** it starts a process. A missing file, a wrong
    size, a wrong digest, an unrecognised extra file or a symlinked root is a
    bounded ``image_ocr_runtime_missing`` refusal, not a spawn followed by a
    child-side surprise. The child repeats the identical check before it imports
    or builds PaddleOCR, so neither side is trusting the other.
    """

    return bool(
        validate_model_manifest(detector_dir, DETECTOR_MODEL_MANIFEST)
        and validate_model_manifest(recognizer_dir, RECOGNIZER_MODEL_MANIFEST)
    )


def ocr_png_isolated(
    *,
    png: bytes,
    width: int,
    height: int,
    detector_dir: str,
    recognizer_dir: str,
    policy: OcrIsolationPolicy = DEFAULT_OCR_ISOLATION_POLICY,
) -> IsolatedOcrResult:
    """OCR one already-sanitized single-frame PNG in a dedicated child process.

    The caller owns admission and normalization: this function is only reached
    for a PNG the #2824 gate admitted and the existing Core ``transform_image``
    produced. It still fails closed on its own input bounds and never starts a
    process it cannot bound.

    ``FIXED_CHILD_LAUNCH_AUTHORITY=YES``: this function takes no launcher,
    factory, executor or ``spawn`` hook. It always starts the one reviewed
    module through :func:`_spawn_ocr_child`, so no caller can substitute an
    interpreter, an executable or a command line. The ladder is tested by
    patching that private function, which keeps the seam private and the public
    signature unable to widen process authority.
    """

    if not isinstance(policy, OcrIsolationPolicy):
        raise OcrIsolationError("policy must be an OcrIsolationPolicy")
    if not isinstance(png, (bytes, bytearray)):
        raise OcrIsolationError("png must be bytes")
    for name, value in (("width", width), ("height", height)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise OcrIsolationError(f"{name} must be a positive integer")

    if not _valid_model_dir(detector_dir) or not _valid_model_dir(recognizer_dir):
        # An unprovisioned runtime is a bounded refusal, not a download and not a
        # silent fallback. No process is started for it.
        return _failed(reason_code=OCR_RUNTIME_MISSING_REASON_CODE)

    body = bytes(png)
    facts = inspect_canonical_png(body, width=width, height=height)
    if facts is None:
        # Defence in depth: the Core transform refuses a non-PNG, a wrong
        # signature and a mismatched header first, so this path means the caller
        # bypassed the transform or a bound drifted. The refusal is structural and
        # spends no image decoder and no process.
        return _failed(reason_code=OCR_INPUT_REASON_CODE)
    if (
        len(body) > IMAGE_OCR_MAX_NORMALIZED_BYTES
        or facts.width * facts.height > IMAGE_OCR_MAX_IMAGE_PIXELS
    ):
        return _failed(reason_code=OCR_INPUT_REASON_CODE)

    if not model_manifests_present(detector_dir, recognizer_dir):
        # The exact official manifests are a preflight condition, not a
        # post-spawn surprise: no process is started for a missing, extra,
        # oversized, mis-hashed or symlinked model file.
        return _failed(reason_code=OCR_RUNTIME_MISSING_REASON_CODE)

    try:
        envelope = encode_envelope(
            detector_dir=detector_dir,
            recognizer_dir=recognizer_dir,
            payload=body,
            width=facts.width,
            height=facts.height,
        )
    except ValueError:
        return _failed(reason_code=OCR_INPUT_REASON_CODE)
    if len(envelope) > policy.max_envelope_bytes:
        return _failed(reason_code=OCR_INPUT_REASON_CODE)

    argv = _child_argv()
    if argv is None:
        return _failed(reason_code=OCR_ISOLATION_FAILURE_REASON_CODE)

    try:
        process = _spawn_ocr_child(argv, _child_environment())
    except (OSError, ValueError):
        # A process that could not start is a bounded failure, never an
        # exception carrying a host path into the caller's note.
        return _failed(reason_code=OCR_ISOLATION_FAILURE_REASON_CODE)

    if process.stdin is None or process.stdout is None or process.stderr is None:
        process.kill()
        return _failed(reason_code=OCR_ISOLATION_FAILURE_REASON_CODE)

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
                reason_code=OCR_ISOLATION_FAILURE_REASON_CODE,
                exit_code=process.returncode,
                killed=escalated,
            )
        return IsolatedOcrResult(
            outcome=OcrOutcome.TIMED_OUT,
            reason_code=OCR_TIMEOUT_REASON_CODE,
            child_exit_code=None,
            terminated_by_kill=escalated,
        )

    exit_code = process.returncode
    if process.poll() is None or exit_code != 0:
        return _failed(reason_code=OCR_ISOLATION_FAILURE_REASON_CODE, exit_code=exit_code)
    if stdout_sink.exceeded:
        return _failed(reason_code=OCR_ISOLATION_FAILURE_REASON_CODE, exit_code=exit_code)

    report: OcrReport | None = decode_report(bytes(stdout_sink.kept))
    if report is None:
        return _failed(reason_code=OCR_ISOLATION_FAILURE_REASON_CODE, exit_code=exit_code)
    if report.ok:
        if report.provenance is None:  # pragma: no cover - OcrReport guarantees the shape
            return _failed(reason_code=OCR_ISOLATION_FAILURE_REASON_CODE, exit_code=exit_code)
        return IsolatedOcrResult(
            outcome=OcrOutcome.COMPLETED,
            reason_code="ok",
            provenance=report.provenance,
            results=report.results,
            child_exit_code=exit_code,
        )
    code = report.code
    if code is None:  # pragma: no cover - OcrReport guarantees the shape
        return _failed(reason_code=OCR_ISOLATION_FAILURE_REASON_CODE, exit_code=exit_code)
    return IsolatedOcrResult(
        outcome=OcrOutcome.REJECTED,
        reason_code=code,
        child_exit_code=exit_code,
    )
