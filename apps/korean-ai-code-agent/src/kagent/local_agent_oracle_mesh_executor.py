"""#4139 — Oracle-side executor for the server-server MeshCentral read.

Runs on the Oracle management host. One loop: claim the oldest dispatch from
the Chat server over the deployment channel secret, read the named file with
the OFFICIAL ``meshctrl.js`` client, and submit the outcome back. The
executor never mints approval or broker evidence, never invents a binding,
and never re-reads the PC file on a retry: a transient store failure is
answered by resending the bytes it already holds.
"""
from __future__ import annotations

import hashlib
import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .contracts import ContractError

#: Same path the Chat worker mounts. Executor and server must agree exactly.
POLL_PATH = "/api/claw/connector/mesh-reads/poll"
RESULT_PATH = "/api/claw/connector/mesh-reads/result"
#: Header carrying the deployment channel secret on both legs.
CHANNEL_HEADER = "X-Oracle-Mesh-Secret"
#: Cloudflare's Browser Integrity Check blocks the default Python-urllib
#: signature (error 1010) at the edge, before the channel secret is ever
#: evaluated. This executor is a first-party product client, so it identifies
#: itself with the same product token the kagent transport already sends.
PRODUCT_USER_AGENT = "PadiemClaw/1.0 (kagent; oracle-mesh-executor)"
#: #4139 wire envelope shared by both lanes: the same 6 MB the Claw request
#: route already accepts for one user message. A command body above it is
#: reported as ``output_too_large`` and a file body is refused whole — neither
#: is truncated, and neither is buffered past this bound.
MAX_COMMAND_BYTES = 6_000_000
MAX_READ_BYTES_ENVELOPE = 6_000_000
#: Legacy alias for callers that still import it; the read port now takes its
#: bound from the shared envelope instead of a trial-era byte count.
MAX_READ_BYTES = MAX_READ_BYTES_ENVELOPE
#: A result the server refuses for a non-retryable reason is quarantined to
#: the pending dir instead of dropped: the bytes survive a restart, the cause
#: is recorded next to them, and the queue moves on. Retrying forever would
#: block the whole queue behind one dead result; dropping silently would lose
#: the only copy of an execution.
MAX_RESULT_REJECTIONS = 3
#: First resend wait and cap for transient failures. The wait grows per
#: consecutive transient refusal and resets on any decisive answer, so a
#: flapping channel is not hammered at the poll cadence.
_BACKOFF_FIRST_SECONDS = 5
_BACKOFF_MAX_SECONDS = 60
#: Pending-result files under the pending dir. The body travels as raw bytes
#: beside the JSON meta so no hex/base64 copy inflates a large output. A body
#: written by this revision is named after its own digest, so a new result
#: never truncates the body an existing manifest still points at.
_PENDING_META_NAME = "pending-result.json"
_PENDING_BODY_NAME = "pending-result.body"
_PENDING_BODY_PREFIX = "pending-result-"
_PENDING_BODY_SUFFIX = ".body"


class OracleMeshChannelRefused(RuntimeError):
    """Bounded refusal of one executor/server exchange. Never carries content."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuses 30x instead of following it.

    ``urllib.request.urlopen`` builds a default opener that *follows* redirects.
    An executor channel carrying the deployment secret must never be replayed to
    another origin, so the redirect is surfaced as an ordinary refusal.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        del req, fp, code, msg, headers, newurl
        return None


@dataclass(frozen=True, slots=True)
class OracleMeshDispatch:
    """One claimed dispatch: exactly what the server authorized, nothing more."""

    dispatch_id: str
    nonce: str
    node_ref: str
    file_path: str
    command_id: str
    run_id: str
    #: #4139: "read" (the 047 file lane) or "command" (the 048 terminal lane).
    kind: str = "read"
    #: The exact single-line command for kind="command"; never used for a read.
    command_text: str | None = None


@dataclass(frozen=True, slots=True)
class OracleMeshExecutionOutcome:
    """What one real execution produced, already size-bounded and hashed.

    ``exit_code`` is ``None`` only when the PC never reported one (a console
    that never answered, or a run that hit the time limit). It is never
    defaulted to 0: an unobserved exit code is not a successful one.
    """

    termination: str
    exit_code: int | None
    body: bytes = b""
    #: Human-readable observation for lanes whose evidence is not the body
    #: itself (desktop notes and screenshot descriptions). Always text-safe.
    note: str = ""


def _require_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise OracleMeshChannelRefused(f"{name} is not a bounded reference")
    return value


class OracleMeshExecutor:
    """Single-thread executor over one authenticated Chat channel.

    ``read_port`` is the merged private MeshCentral port: it owns the operator
    credential (call-time provider, stdin only, marker on argv) and runs the
    official client. ``transport`` is injected so the network boundary is
    explicit and testable; the default performs a verified HTTPS request with
    redirects explicitly refused.
    """

    def __init__(
        self,
        *,
        chat_origin: str,
        channel_secret: str,
        read_port: Any,
        command_port: Any = None,
        desktop_port: Any = None,
        timeout_seconds: int = 30,
        transport: Optional[Callable[..., tuple[int, dict[str, Any]]]] = None,
        pending_dir: Optional[str] = None,
    ) -> None:
        if not isinstance(chat_origin, str) or not chat_origin.startswith("https://"):
            raise ContractError("the chat channel must be an https origin")
        if len(chat_origin) > 300 or chat_origin.rstrip("/") != chat_origin:
            raise ContractError("the chat origin must be a bare https origin")
        if (
            not isinstance(channel_secret, str)
            or not 16 <= len(channel_secret) <= 256
            or any(ord(ch) < 33 or ord(ch) > 126 for ch in channel_secret)
        ):
            raise ContractError("the deployment channel secret is required")
        if not callable(getattr(read_port, "read_bytes", None)):
            raise ContractError("a private MeshCentral file read port is required")
        if command_port is not None and not callable(
            getattr(command_port, "run_command", None)
        ):
            raise ContractError("a MeshCentral command port must expose run_command")
        if desktop_port is not None and not callable(
            getattr(desktop_port, "run_desktop_op", None)
        ):
            raise ContractError("a MeshCentral desktop port must expose run_desktop_op")
        self._origin = chat_origin
        self._secret = channel_secret
        self._read_port = read_port
        self._command_port = command_port
        self._desktop_port = desktop_port
        self._timeout = timeout_seconds
        self._transport = transport or self._https_post
        self._pending: Optional[tuple[OracleMeshDispatch, OracleMeshExecutionOutcome]] = None
        self._rejections = 0
        self._transients = 0
        self._pending_dir = pending_dir
        #: The body file the current manifest points at, once durable.
        self._pending_body: Optional[str] = None

    # ---- channel -------------------------------------------------------
    def _https_post(self, path: str, payload: Optional[dict[str, Any]]) -> tuple[int, dict[str, Any]]:
        """One verified HTTPS POST. Redirects are refused, not followed."""
        url = f"{self._origin}{path}"
        # UTF-8 as JSON permits: escaping every non-ASCII byte would inflate a
        # Korean command output about six times, so a body far below the wire
        # envelope would still be refused as too large and quarantined.
        data = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url, data=data, method="POST",
            headers={
                "Content-Type": "application/json",
                CHANNEL_HEADER: self._secret,
                "Accept": "application/json",
                "User-Agent": PRODUCT_USER_AGENT,
            },
        )
        context = ssl.create_default_context()
        # urllib follows 30x by default; an executor channel must never be
        # silently moved to another origin, so redirects are refused outright.
        opener = urllib.request.build_opener(_NoRedirect())
        try:
            with opener.open(request, timeout=self._timeout) as response:
                # One extra byte is the overflow detector, never content: a
                # poll response carries the command it wants run, so reading a
                # fixed 64 KiB used to truncate a long command's JSON and make
                # the dispatch look absent. The bound is the same wire envelope
                # the submit leg is held to.
                raw = response.read(MAX_COMMAND_BYTES + 1)
                status = int(getattr(response, "status", 0) or 0)
                if len(raw) > MAX_COMMAND_BYTES:
                    raise OracleMeshChannelRefused(
                        "chat channel response exceeds the wire envelope"
                    )
        except urllib.error.HTTPError as exc:
            raw = exc.read(4096)
            status = int(exc.code)
        except OracleMeshChannelRefused:
            raise
        except Exception as exc:  # transport refused/unreachable
            raise OracleMeshChannelRefused("chat channel transport refused") from exc
        try:
            decoded = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            decoded = {}
        if not isinstance(decoded, dict):
            decoded = {}
        return status, decoded

    def _post(self, path: str, payload: Optional[dict[str, Any]]) -> tuple[int, dict[str, Any]]:
        try:
            return self._transport(path, payload)
        except OracleMeshChannelRefused:
            raise
        except Exception as exc:
            raise OracleMeshChannelRefused("chat channel transport refused") from exc

    # ---- legs ----------------------------------------------------------
    def poll_once(self) -> Optional[OracleMeshDispatch]:
        """Claim the oldest dispatch, or None when the queue is empty."""
        status, data = self._post(POLL_PATH, None)
        if status != 200 or data.get("ok") is not True:
            raise OracleMeshChannelRefused("chat channel refused the poll")
        dispatch = data.get("dispatch")
        if dispatch is None:
            return None
        if not isinstance(dispatch, dict):
            raise OracleMeshChannelRefused("chat channel returned a malformed dispatch")
        kind = dispatch.get("kind") or "read"
        if kind not in ("read", "command", "desktop"):
            raise OracleMeshChannelRefused("chat channel returned an unknown dispatch kind")
        command_text = dispatch.get("command_text")
        if kind in ("command", "desktop"):
            # The server owns the command; the executor never invents one and
            # never falls back to the file lane when it is missing.
            if not isinstance(command_text, str) or not command_text.strip():
                raise OracleMeshChannelRefused("chat channel returned a command dispatch without a command")
        else:
            command_text = None
        return OracleMeshDispatch(
            dispatch_id=_require_text(dispatch.get("dispatch_id"), "dispatch_id"),
            nonce=_require_text(dispatch.get("nonce"), "nonce"),
            node_ref=_require_text(dispatch.get("node_ref"), "node_ref"),
            file_path=_require_text(dispatch.get("file_path"), "file_path"),
            command_id=_require_text(dispatch.get("command_id"), "command_id"),
            run_id=_require_text(dispatch.get("run_id"), "run_id"),
            kind=kind,
            command_text=command_text,
        )

    def execute(self, dispatch: OracleMeshDispatch) -> OracleMeshExecutionOutcome:
        """One real official-client execution. Failures are outcomes, not exceptions."""
        if dispatch.kind == "command":
            return self._execute_command(dispatch)
        if dispatch.kind == "desktop":
            return self._execute_desktop(dispatch)
        try:
            body = self._read_port.read_bytes(
                node_ref=dispatch.node_ref,
                file_path=dispatch.file_path,
                timeout_seconds=self._timeout * 4,
            )
        except Exception:
            return OracleMeshExecutionOutcome(termination="exited", exit_code=1, body=b"")
        if not isinstance(body, (bytes, bytearray)):
            return OracleMeshExecutionOutcome(termination="exited", exit_code=1, body=b"")
        raw = bytes(body)
        if len(raw) > MAX_READ_BYTES:
            # Oversize is refused, never truncated.
            return OracleMeshExecutionOutcome(termination="exited", exit_code=1, body=b"")
        return OracleMeshExecutionOutcome(termination="exited", exit_code=0, body=raw)

    def _execute_command(
        self, dispatch: OracleMeshDispatch
    ) -> OracleMeshExecutionOutcome:
        """#4139 terminal lane: run the command the server put in the dispatch.

        The exit code is whatever the PC reported through the sentinel. When no
        code was observed the outcome says so (``no_reply`` for no console
        answer, ``timed_out`` for a wait that expired, ``no_exit_code`` for a
        complete console answer whose ``$LASTEXITCODE`` was empty) instead of
        borrowing the shell's own success.
        """
        if self._command_port is None:
            # A command dispatch on an executor that was not composed with a
            # command port is a misconfiguration, not a silent no-op.
            raise OracleMeshChannelRefused("command execution is not configured")
        try:
            observed = self._command_port.run_command(
                node_ref=dispatch.node_ref,
                command=dispatch.command_text or "",
                timeout_seconds=max(1, self._timeout * 2),
            )
        except Exception as exc:
            if type(exc).__name__ == "MeshCentralCommandRefused":
                # The port refused before the PC was asked. Collapsing that into
                # ``no_reply`` would report a silent console for a command that
                # never ran, so the two observations stay separate.
                return OracleMeshExecutionOutcome(
                    termination="not_executed", exit_code=None, body=b"",
                )
            return OracleMeshExecutionOutcome(termination="no_reply", exit_code=None, body=b"")
        termination = getattr(observed, "termination", "no_reply")
        if termination not in (
            "exited", "timed_out", "no_reply", "no_exit_code", "not_executed",
            "output_too_large",
        ):
            termination = "no_reply"
        exit_code = getattr(observed, "exit_code", None)
        if isinstance(exit_code, bool) or not isinstance(exit_code, int):
            exit_code = None
        if termination in ("exited", "output_too_large") and exit_code is None:
            # The sentinel line arrived without a number: the exit code is not
            # observed, so the run cannot claim a clean exit.
            termination = "no_reply"
        body = getattr(observed, "output", b"")
        if not isinstance(body, (bytes, bytearray)):
            body = b""
        raw = bytes(body)
        if len(raw) > MAX_COMMAND_BYTES:
            # Oversize output is never truncated; the body is withheld and the
            # observed exit code is still carried.
            return OracleMeshExecutionOutcome(
                termination="output_too_large", exit_code=exit_code, body=b"",
            )
        return OracleMeshExecutionOutcome(
            termination=termination, exit_code=exit_code, body=raw,
        )

    def _execute_desktop(
        self, dispatch: OracleMeshDispatch
    ) -> OracleMeshExecutionOutcome:
        """#4139 desktop lane: one relay observation or input on the PC.

        The op grammar is parsed before the PC is asked: an unknown op is
        ``not_executed``, never a guessed click. A capture returns the JPEG
        bytes as the body with the observation as the note; an input op
        returns an empty body with its note. Oversize bodies are withheld,
        never truncated.
        """
        from .local_agent_meshcentral_desktop_port import parse_desktop_op

        if self._desktop_port is None:
            raise OracleMeshChannelRefused("desktop execution is not configured")
        try:
            op, arg = parse_desktop_op(dispatch.command_text or "")
        except Exception:
            return OracleMeshExecutionOutcome(
                termination="not_executed", exit_code=None, body=b"",
                note="the desktop op was refused before the PC was asked",
            )
        try:
            observed = self._desktop_port.run_desktop_op(
                node_ref=dispatch.node_ref,
                op=op,
                arg=arg,
                # A full multi-monitor redraw moves megabytes of tiles; the
                # read lane already waits timeout*4 for the same reason.
                timeout_seconds=max(1, self._timeout * 4),
            )
        except Exception as exc:
            if type(exc).__name__ == "MeshCentralDesktopRefused":
                return OracleMeshExecutionOutcome(
                    termination="not_executed", exit_code=None, body=b"",
                    note="the desktop relay was refused before the PC was asked",
                )
            return OracleMeshExecutionOutcome(
                termination="desktop_unavailable", exit_code=None, body=b"",
                note="the desktop session did not answer",
            )
        termination = getattr(observed, "termination", "desktop_unavailable")
        if termination not in (
            "captured", "acted", "desktop_unavailable", "timed_out",
            "not_executed", "output_too_large",
        ):
            termination = "desktop_unavailable"
        note = getattr(observed, "note", "")
        if not isinstance(note, str):
            note = ""
        body = getattr(observed, "image", b"")
        if not isinstance(body, (bytes, bytearray)):
            body = b""
        raw = bytes(body)
        if termination == "captured" and not raw:
            termination = "desktop_unavailable"
            note = (note + "; no image bytes" if note else "no image bytes")
        if len(raw) > MAX_COMMAND_BYTES:
            # Oversize evidence is never truncated; the observation note is
            # still carried so the turn is not silent.
            return OracleMeshExecutionOutcome(
                termination="output_too_large", exit_code=None, body=b"",
                note=note,
            )
        return OracleMeshExecutionOutcome(
            termination=termination, exit_code=None, body=raw, note=note,
        )

    # ---- held-result persistence -------------------------------------
    def _pending_dir_path(self) -> Optional[str]:
        import os

        if not isinstance(self._pending_dir, str) or not self._pending_dir:
            return None
        return self._pending_dir

    def _pending_meta_path(self) -> Optional[str]:
        import os

        directory = self._pending_dir_path()
        if directory is None:
            return None
        return os.path.join(directory, _PENDING_META_NAME)

    @staticmethod
    def _pending_body_name(digest: str) -> str:
        """The body file is named after its own digest.

        A new held result therefore lands in a new file instead of truncating
        the body an existing manifest still points at, which is what makes the
        two-step commit below safe.
        """
        return _PENDING_BODY_PREFIX + digest[:32] + _PENDING_BODY_SUFFIX

    @staticmethod
    def _atomic_write(directory: str, name: str, payload: bytes) -> None:
        """Create-or-replace one file, fully written, or leave the old one alone.

        Node/POSIX guarantee ``os.replace`` is atomic within a directory, and
        the fsyncs put both the bytes and the rename on disk before the executor
        posts. The previous code opened the live file with ``O_TRUNC`` and
        ignored the error, so a full disk or a crash mid-write destroyed the
        only copy of an execution the PC had already performed.
        """
        import os
        import tempfile

        fd, temp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".part")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, os.path.join(directory, name))
        except BaseException:
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise
        try:
            dir_fd = os.open(directory, os.O_RDONLY)
        except OSError:
            return  # not every platform lets a directory be fsynced
        try:
            os.fsync(dir_fd)
        except OSError:
            pass
        finally:
            os.close(dir_fd)

    def _persist_pending(self) -> Optional[str]:
        """Make the held result durable before submitting it.

        Returns ``None`` when the result is durable (or already was), and the
        OSError name when it is not — the caller reports that instead of
        pretending a write that failed happened. A crash between a real
        execution and the server's acceptance must never re-execute the PC
        command on restart, so recovery only resends these exact bytes.

        Commit order: the content-addressed body first, then the manifest that
        names it. A crash between the two leaves the previous complete pair
        readable and the new body unreferenced, never a manifest whose bytes
        are gone.
        """
        import os

        directory = self._pending_dir_path()
        if directory is None or self._pending is None:
            return None
        dispatch, outcome = self._pending
        digest = hashlib.sha256(outcome.body).hexdigest()
        body_name = self._pending_body_name(digest)
        meta = {
            "dispatch_id": dispatch.dispatch_id,
            "nonce": dispatch.nonce,
            "node_ref": dispatch.node_ref,
            "file_path": dispatch.file_path,
            "command_id": dispatch.command_id,
            "run_id": dispatch.run_id,
            "kind": dispatch.kind,
            "command_text": dispatch.command_text,
            "termination": outcome.termination,
            "exit_code": outcome.exit_code,
            "note": outcome.note if isinstance(outcome.note, str) else "",
            "content_sha256": digest,
            "content_bytes": len(outcome.body),
            "body_name": body_name,
        }
        encoded = json.dumps(meta).encode("utf-8")
        meta_path = os.path.join(directory, _PENDING_META_NAME)
        if self._pending_body_name_matches(meta_path, encoded):
            # The exact same held result is already durable. A plain resend
            # rewrites nothing, so the good copy is never exposed to a write
            # that cannot change it.
            self._pending_body = body_name
            return None
        try:
            if not os.path.exists(os.path.join(directory, body_name)):
                self._atomic_write(directory, body_name, outcome.body)
            self._atomic_write(directory, _PENDING_META_NAME, encoded)
        except OSError as exc:
            return type(exc).__name__
        previous = self._pending_body
        if previous is not None and previous != body_name:
            try:
                os.remove(os.path.join(directory, previous))
            except OSError:
                pass  # an unreferenced body is harmless; the manifest is current
        self._pending_body = body_name
        return None

    def _pending_body_name_matches(self, meta_path: str, encoded: bytes) -> bool:
        import os

        try:
            with open(meta_path, "rb") as handle:
                current = handle.read()
        except OSError:
            return False
        if current != encoded:
            return False
        try:
            manifest = json.loads(current.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return False
        name = manifest.get("body_name") if isinstance(manifest, dict) else None
        if not isinstance(name, str) or not name:
            return False
        return os.path.exists(os.path.join(os.path.dirname(meta_path), name))

    @staticmethod
    def _safe_quarantine_stem(dispatch_id: str) -> str:
        import hashlib as _hashlib

        if (
            isinstance(dispatch_id, str)
            and dispatch_id
            and len(dispatch_id) <= 128
            and all(ch.isalnum() or ch in "-_." for ch in dispatch_id)
        ):
            return dispatch_id
        return "id-" + _hashlib.sha256(str(dispatch_id).encode("utf-8")).hexdigest()[:16]

    def _clear_persisted_pending(self) -> None:
        """Drop the accepted manifest and the body it names, nothing newer.

        Bodies are removed through the manifest that references them, so an
        accepted result cannot delete a body another result still points at.
        """
        import os

        directory = self._pending_dir_path()
        if directory is None:
            return
        meta_path = os.path.join(directory, _PENDING_META_NAME)
        names = [_PENDING_META_NAME]
        try:
            with open(meta_path, "rb") as handle:
                manifest = json.loads(handle.read().decode("utf-8"))
            if isinstance(manifest, dict) and isinstance(manifest.get("body_name"), str):
                names.append(manifest["body_name"])
        except (OSError, ValueError, UnicodeDecodeError):
            pass
        if self._pending_body:
            names.append(self._pending_body)
        names.append(_PENDING_BODY_NAME)  # pre-content-addressed layout
        for name in dict.fromkeys(names):
            try:
                os.remove(os.path.join(directory, name))
            except OSError:
                pass
        self._pending_body = None

    def _quarantine_pending(self, *, reason: str, status: Any = None, code: Any = None) -> dict[str, Any]:
        """Preserve a permanently refused result and release the queue.

        The bytes, the dispatch identity and the refusal cause stay on disk
        under a dispatch-derived name; nothing is re-executed and nothing is
        silently discarded.
        """
        import os
        import time

        dispatch, outcome = self._pending if self._pending is not None else (None, None)
        stem = self._safe_quarantine_stem(
            dispatch.dispatch_id if dispatch is not None else "unknown"
        )
        record: dict[str, Any] = {
            "reason": reason,
            "status": status,
            "code": code,
            "quarantined_at": int(time.time()),
        }
        quarantine_path: Any = None
        persist_error: Any = None
        if self._pending is not None and self._pending_dir:
            body = outcome.body if outcome is not None else b""
            record.update({
                "dispatch_id": dispatch.dispatch_id,
                "nonce_sha256": hashlib.sha256(dispatch.nonce.encode("utf-8")).hexdigest(),
                "node_ref": dispatch.node_ref,
                "run_id": dispatch.run_id,
                "kind": dispatch.kind,
                "termination": outcome.termination,
                "exit_code": outcome.exit_code,
                "note": outcome.note if isinstance(outcome.note, str) else "",
                "content_sha256": hashlib.sha256(body).hexdigest(),
                "content_bytes": len(body),
            })
            base = os.path.join(self._pending_dir, "quarantine-" + stem)
            quarantine_path = base + ".json"
            body_name = os.path.basename(base) + ".body"
            record["body_name"] = body_name
            persist_error: Any = None
            try:
                if not os.path.exists(base + ".body"):
                    self._atomic_write(self._pending_dir, body_name, body)
                if not os.path.exists(quarantine_path):
                    self._atomic_write(
                        self._pending_dir, os.path.basename(quarantine_path),
                        json.dumps(record).encode("utf-8"),
                    )
            except OSError as exc:
                # The cause is reported instead of swallowed: a quarantine that
                # could not be written must not look like preserved evidence.
                persist_error = type(exc).__name__
                record["persist_error"] = persist_error
                try:
                    self._atomic_write(
                        self._pending_dir, os.path.basename(quarantine_path),
                        json.dumps(record).encode("utf-8"),
                    )
                except OSError:
                    quarantine_path = None
        self._pending = None
        self._rejections = 0
        self._transients = 0
        self._clear_persisted_pending()
        report: dict[str, Any] = {
            "ok": False, "dropped": True, "quarantined": True,
            "quarantine_path": quarantine_path, "status": status, "code": code,
            "reason": reason,
        }
        if persist_error is not None:
            report["persist_error"] = persist_error
        return report

    def load_pending(self) -> bool:
        """Recover a result held across a restart: resend-only, never re-run.

        Returns True when a held result was restored. A corrupt or foreign
        file is quarantined aside, never executed: recovery resends bytes the
        PC really produced, nothing else.
        """
        import os

        directory = self._pending_dir_path()
        if directory is None:
            return False
        meta_path = os.path.join(directory, _PENDING_META_NAME)
        if not os.path.exists(meta_path):
            return False
        try:
            with open(meta_path, "r", encoding="utf-8") as handle:
                meta = json.load(handle)
        except OSError:
            return False
        except (ValueError, UnicodeDecodeError):
            stem = "corrupt-" + str(os.getpid())
            try:
                os.replace(meta_path, os.path.join(directory, "quarantine-" + stem + ".json"))
            except OSError:
                pass
            return False
        # The manifest names its own body, so a body is only ever read through
        # the manifest that describes it. The fixed legacy name is still
        # accepted: a result held by the previous executor revision must not be
        # lost across this upgrade.
        name = meta.get("body_name") if isinstance(meta, dict) else None
        if not isinstance(name, str) or not name or os.path.dirname(name):
            name = _PENDING_BODY_NAME
        body_path = os.path.join(directory, name)
        try:
            with open(body_path, "rb") as handle:
                body = handle.read()
        except OSError:
            return False
        self._pending_body = name
        try:
            if not isinstance(meta, dict):
                raise ValueError("pending meta is not an object")
            body_hash = hashlib.sha256(body).hexdigest()
            if meta.get("content_sha256") != body_hash or meta.get("content_bytes") != len(body):
                raise ValueError("pending body does not match its manifest")
            dispatch = OracleMeshDispatch(
                dispatch_id=_require_text(meta.get("dispatch_id"), "dispatch_id"),
                nonce=_require_text(meta.get("nonce"), "nonce"),
                node_ref=_require_text(meta.get("node_ref"), "node_ref"),
                file_path=_require_text(meta.get("file_path"), "file_path"),
                command_id=_require_text(meta.get("command_id"), "command_id"),
                run_id=_require_text(meta.get("run_id"), "run_id"),
                kind=meta.get("kind") or "read",
                command_text=meta.get("command_text"),
            )
            if dispatch.kind not in ("read", "command", "desktop"):
                raise ValueError("pending kind is unknown")
            if dispatch.kind in ("command", "desktop") and (
                not isinstance(dispatch.command_text, str) or not dispatch.command_text.strip()
            ):
                raise ValueError("pending command has no command")
            termination = meta.get("termination")
            if termination not in (
                "exited", "cancelled", "timed_out", "no_reply", "no_exit_code",
                "not_executed", "output_too_large",
                "captured", "acted", "desktop_unavailable",
            ):
                raise ValueError("pending termination is unknown")
            exit_code = meta.get("exit_code")
            if exit_code is not None and (
                isinstance(exit_code, bool) or not isinstance(exit_code, int)
            ):
                raise ValueError("pending exit code is not an integer")
            if len(body) > MAX_COMMAND_BYTES:
                raise ValueError("pending body exceeds the wire envelope")
            note = meta.get("note", "")
            if not isinstance(note, str):
                raise ValueError("pending note is not text")
            outcome = OracleMeshExecutionOutcome(
                termination=termination, exit_code=exit_code, body=body,
                note=note,
            )
        except (ValueError, OracleMeshChannelRefused, ContractError):
            stem = "corrupt-" + str(os.getpid())
            # Both halves move together, so a restart cannot re-quarantine the
            # same unreadable pair over and over. A missing half is not an
            # error: only the manifest is a commit marker.
            for source, suffix in ((meta_path, ".json"), (body_path, ".body")):
                try:
                    os.replace(source, os.path.join(directory, "quarantine-" + stem + suffix))
                except OSError:
                    pass
            self._pending = None
            self._pending_body = None
            return False
        self._pending = (dispatch, outcome)
        self._rejections = 0
        self._transients = 0
        return True

    def _transient_wait_seconds(self) -> int:
        wait = _BACKOFF_FIRST_SECONDS * (2 ** min(self._transients, 4))
        return max(1, min(_BACKOFF_MAX_SECONDS, wait))

    def _submit_desktop(
        self, dispatch: OracleMeshDispatch, outcome: OracleMeshExecutionOutcome
    ) -> dict[str, Any]:
        """Submit one desktop observation or input.

        The note travels as the UTF-8 text; a screenshot travels beside it
        as base64 JPEG evidence with its own digest. The dispatch pin covers
        the JPEG when one is present, else the note — so a resend is compared
        against the same bytes the server pinned first.
        """
        import base64

        note = outcome.note if isinstance(outcome.note, str) else ""
        try:
            note_raw = note.encode("utf-8")
        except (UnicodeEncodeError, ValueError):
            note_raw = b""
        if (
            len(note_raw) > MAX_COMMAND_BYTES
            or any(ord(ch) < 32 and ch not in "\n\r\t" for ch in note)
            or "\x7f" in note
        ):
            self._pending = (dispatch, outcome)
            self._persist_pending()
            return self._quarantine_pending(reason="desktop_note_invalid")
        body = bytes(outcome.body) if isinstance(outcome.body, (bytes, bytearray)) else b""
        payload = {
            "dispatch_id": dispatch.dispatch_id,
            "nonce": dispatch.nonce,
            "termination": outcome.termination,
            "exit_code": outcome.exit_code,
            "content_utf8": note,
            "content_sha256": hashlib.sha256(body).hexdigest() if body else hashlib.sha256(note_raw).hexdigest(),
            "content_bytes": len(body) if body else len(note_raw),
        }
        if body:
            payload["content_blob_base64"] = base64.b64encode(body).decode("ascii")
            payload["content_blob_sha256"] = hashlib.sha256(body).hexdigest()
            payload["content_blob_bytes"] = len(body)
            payload["content_blob_media_type"] = "image/jpeg"
        # The channel envelope limits the serialized UTF-8 JSON, not raw JPEG.
        # Persist the immutable screenshot before reporting an unshippable outcome.
        wire_bytes = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        if wire_bytes > MAX_COMMAND_BYTES:
            self._pending = (dispatch, outcome)
            persist_error = self._persist_pending()
            return self._with_persist_warning(
                {"ok": False, "retryable": False, "resend_pending": False,
                 "reason": "desktop_result_wire_envelope_exceeded",
                 "serialized_bytes": wire_bytes,
                 "envelope_bytes": MAX_COMMAND_BYTES,
                 "outcome_preserved": True}, persist_error)
        self._pending = (dispatch, outcome)
        persist_error = self._persist_pending()
        try:
            status, data = self._post(RESULT_PATH, payload)
        except OracleMeshChannelRefused:
            wait = self._transient_wait_seconds()
            self._transients += 1
            return self._with_persist_warning(
                {"ok": False, "retryable": True, "resend_pending": True,
                 "wait_seconds": wait}, persist_error)
        if status == 200 and data.get("ok") is True:
            self._pending = None
            self._rejections = 0
            self._transients = 0
            self._clear_persisted_pending()
            return data
        return self._submit_refused(status, data, persist_error)

    def _submit_refused(
        self, status: Any, data: dict[str, Any], persist_error: Optional[str]
    ) -> dict[str, Any]:
        """Share one refusal policy between the text and desktop submit legs.

        A transient store/channel failure keeps the exact bytes for a resend;
        an ambiguous 409 is retried boundedly, then quarantined; ownership and
        malformed-body refusals quarantine at once. Nothing is re-executed and
        nothing is dropped silently on any leg.
        """
        error = data.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        if status == 503 or status == 429 or status >= 500:
            self._rejections = 0
            wait = self._transient_wait_seconds()
            self._transients += 1
            return self._with_persist_warning(
                {"ok": False, "retryable": True, "resend_pending": True,
                 "status": status, "code": code, "wait_seconds": wait}, persist_error)
        if status == 409 and code == "oracle_mesh_result_fingerprint_mismatch":
            return self._quarantine_pending(
                reason="result_fingerprint_mismatch", status=status, code=code)
        if status in (400, 403):
            return self._quarantine_pending(
                reason="result_refused", status=status, code=code)
        self._rejections += 1
        if self._rejections < MAX_RESULT_REJECTIONS:
            wait = self._transient_wait_seconds()
            self._transients += 1
            return self._with_persist_warning(
                {"ok": False, "retryable": True, "resend_pending": True,
                 "status": status, "code": code, "wait_seconds": wait}, persist_error)
        return self._quarantine_pending(
            reason="dispatch_rejected", status=status, code=code)

    def submit(
        self, dispatch: OracleMeshDispatch, outcome: OracleMeshExecutionOutcome
    ) -> dict[str, Any]:
        """Submit one outcome, and keep it until the server decides it.

        The bytes are persisted before the post and resent unchanged on a
        transient refusal — the PC file is never read a second time and a
        held command is never re-executed. ``resend_pending`` reports that
        held outcome so the caller can drive the retry without touching
        either port.
        """
        if dispatch.kind == "desktop":
            return self._submit_desktop(dispatch, outcome)
        try:
            text = outcome.body.decode("utf-8") if outcome.body else ""
        except UnicodeDecodeError:
            # Not submittable on the UTF-8 wire, but still a real outcome:
            # preserve it instead of dropping it on the floor.
            self._pending = (dispatch, outcome)
            self._persist_pending()
            return self._quarantine_pending(reason="result_not_utf8")
        payload = {
            "dispatch_id": dispatch.dispatch_id,
            "nonce": dispatch.nonce,
            "termination": outcome.termination,
            "exit_code": outcome.exit_code,
            "content_utf8": text,
            "content_sha256": hashlib.sha256(outcome.body).hexdigest(),
            "content_bytes": len(outcome.body),
        }
        self._pending = (dispatch, outcome)
        # A persistence failure is reported, never hidden: the bytes stay in
        # memory and are still submitted, but the operator must be able to see
        # that this result is not durable across a restart.
        persist_error = self._persist_pending()
        try:
            status, data = self._post(RESULT_PATH, payload)
        except OracleMeshChannelRefused:
            # Transport down: same bytes, backed off, never re-executed.
            wait = self._transient_wait_seconds()
            self._transients += 1
            return self._with_persist_warning(
                {"ok": False, "retryable": True, "resend_pending": True,
                 "wait_seconds": wait}, persist_error)
        if status == 200 and data.get("ok") is True:
            self._pending = None
            self._rejections = 0
            self._transients = 0
            self._clear_persisted_pending()
            return data
        return self._submit_refused(status, data, persist_error)

    @staticmethod
    def _with_persist_warning(report: dict[str, Any], persist_error: Optional[str]):
        if persist_error is not None:
            report["persist_error"] = persist_error
        return report

    @property
    def resend_pending(self) -> bool:
        """True while an accepted-by-execution result still awaits delivery."""
        return self._pending is not None

    def resend_pending_result(self) -> Optional[dict[str, Any]]:
        """Deliver the already-executed result again, without re-reading."""
        if self._pending is None:
            return None
        dispatch, outcome = self._pending
        return self.submit(dispatch, outcome)

    def run_once(self) -> Optional[dict[str, Any]]:
        """Retry a held result if any; otherwise poll, execute and submit."""
        if self._pending is not None:
            return self.resend_pending_result()
        dispatch = self.poll_once()
        if dispatch is None:
            return None
        return self.submit(dispatch, self.execute(dispatch))


__all__ = [
    "CHANNEL_HEADER",
    "MAX_COMMAND_BYTES",
    "MAX_READ_BYTES",
    "POLL_PATH",
    "PRODUCT_USER_AGENT",
    "RESULT_PATH",
    "OracleMeshChannelRefused",
    "OracleMeshDispatch",
    "OracleMeshExecutionOutcome",
    "OracleMeshExecutor",
    "deployment_secret_password_provider",
    "make_oracle_mesh_executor",
]

def make_oracle_mesh_executor(
    *,
    chat_origin: str,
    channel_secret: str,
    meshctrl_js: str,
    login_user: str,
    password_provider: Callable[[], str],
    mesh_url: str = "wss://127.0.0.1:4443",
    work_dir: str | None = None,
    timeout_seconds: int = 30,
) -> OracleMeshExecutor:
    """Build the executor with the REAL official meshctrl read port.

    This is the operational composition: ``meshctrl_js`` is the official
    ``meshctrl.js`` shipped with the MeshCentral server, ``password_provider``
    yields the operator credential at call time (on this host it is the
    mode-0600 deployment secret file), and every read runs that client. No
    stand-in port is constructible from here.
    """
    from .local_agent_meshcentral_command_port import MeshCentralCliCommandPort
    from .local_agent_meshcentral_desktop_port import MeshCentralDesktopPort
    from .local_agent_meshcentral_private_reader import MeshCentralCliFileReadPort

    def _popen(argv, **kwargs):
        import subprocess

        return subprocess.Popen(argv, **kwargs)

    def _run(argv, **kwargs):
        # The merged private read port hands the operator credential to the
        # child on STDIN ("<password>\n"); the OS argv carries only the public
        # marker. Dropping that input here would leave the official client
        # waiting on a prompt it can never answer, so it is passed through
        # verbatim as UTF-8 text.
        import subprocess

        supplied = kwargs.get("input")
        call: dict = {
            "capture_output": True,
            "text": True,
            "encoding": "utf-8",
            "timeout": kwargs.get("timeout", 120),
        }
        if supplied is not None:
            call["input"] = supplied
        return subprocess.run(argv, **call)

    read_port = MeshCentralCliFileReadPort(
        command_runner=_run,
        meshctrl_js=meshctrl_js,
        login_user=login_user,
        password_provider=password_provider,
        url=mesh_url,
        work_dir=work_dir,
    )
    # The terminal lane reuses the SAME official client, operator credential and
    # private tunnel; nothing new is opened for commands.
    command_port = MeshCentralCliCommandPort(
        command_runner=_run,
        meshctrl_js=meshctrl_js,
        login_user=login_user,
        password_provider=password_provider,
        url=mesh_url,
        work_dir=work_dir,
        # #4139: the command lane reads the child incrementally so a runaway
        # command can never be buffered whole before it is size-checked.
        popen_factory=_popen,
    )
    # The desktop lane reuses the SAME operator credential and private tunnel
    # over the official relay protocol; only the wire changes (MSC frames),
    # never the trust basis.
    desktop_port = MeshCentralDesktopPort(
        login_user=login_user,
        password_provider=password_provider,
        url=mesh_url,
    )
    return OracleMeshExecutor(
        chat_origin=chat_origin,
        channel_secret=channel_secret,
        read_port=read_port,
        command_port=command_port,
        desktop_port=desktop_port,
        timeout_seconds=timeout_seconds,
        pending_dir=work_dir,
    )


def deployment_secret_password_provider(path: str) -> Callable[[], str]:
    """Read the mode-restricted deployment secret file at call time only."""
    import os

    if not isinstance(path, str) or not path.strip():
        raise ContractError("the deployment secret path is required")
    if not os.path.isfile(path):
        raise ContractError("the deployment secret file is missing")

    def provider() -> str:
        with open(path, "r", encoding="utf-8") as handle:
            secret = handle.read().strip()
        if not secret:
            raise OracleMeshChannelRefused("the deployment secret file is empty")
        return secret

    return provider


def _read_secret_file(path: str, name: str) -> str:
    import os

    if not isinstance(path, str) or not path.strip() or not os.path.isfile(path):
        raise ContractError(f"the {name} file is missing")
    with open(path, "r", encoding="utf-8") as handle:
        value = handle.read().strip()
    if not value:
        raise ContractError(f"the {name} file is empty")
    return value


def main(environ: Optional[dict[str, str]] = None) -> int:
    """Startup entrypoint: one poll/execute/submit loop on the Oracle host.

    Configuration is environment-only and bounded:
      ORACLE_MESH_CHAT_ORIGIN       https origin of the Chat worker (bare)
      ORACLE_MESH_CHANNEL_SECRET_FILE  mode-0600 file holding the channel secret
      ORACLE_MESH_MESHCTRL_JS       path to the official meshctrl.js
      ORACLE_MESH_LOGIN_USER        MeshCentral operator account
      ORACLE_MESH_PASSWORD_FILE     mode-0600 file holding the operator password
      ORACLE_MESH_URL               optional, default wss://127.0.0.1:4443
      ORACLE_MESH_WORK_DIR          optional scratch directory
      ORACLE_MESH_POLL_SECONDS      optional idle interval, default 5
    Secrets are read from files at call time; they never appear on argv.
    """
    import os
    import sys
    import time

    env = dict(os.environ if environ is None else environ)

    def need(key: str) -> str:
        value = env.get(key, "").strip()
        if not value:
            raise ContractError(f"{key} is required")
        return value

    try:
        executor = make_oracle_mesh_executor(
            chat_origin=need("ORACLE_MESH_CHAT_ORIGIN"),
            channel_secret=_read_secret_file(
                need("ORACLE_MESH_CHANNEL_SECRET_FILE"), "channel secret"
            ),
            meshctrl_js=need("ORACLE_MESH_MESHCTRL_JS"),
            login_user=need("ORACLE_MESH_LOGIN_USER"),
            password_provider=deployment_secret_password_provider(
                need("ORACLE_MESH_PASSWORD_FILE")
            ),
            mesh_url=env.get("ORACLE_MESH_URL", "").strip() or "wss://127.0.0.1:4443",
            work_dir=env.get("ORACLE_MESH_WORK_DIR", "").strip() or None,
        )
        idle = max(1, min(int(env.get("ORACLE_MESH_POLL_SECONDS", "5") or 5), 300))
    except (ContractError, ValueError) as exc:
        print(f"oracle-mesh-executor refused to start: {exc}", file=sys.stderr)
        return 2

    # A restart never re-executes: a persisted held result is resent as-is.
    try:
        if executor.load_pending():
            print("oracle-mesh-executor restored a held result; resending only",
                  file=sys.stderr)
    except OSError as exc:
        print(f"oracle-mesh-executor pending restore refused: {exc}", file=sys.stderr)

    while True:
        try:
            result = executor.run_once()
        except OracleMeshChannelRefused as exc:
            # Bounded: the message never carries dispatch content or secrets.
            print(f"oracle-mesh-executor channel refusal: {exc}", file=sys.stderr)
            time.sleep(idle)
            continue
        if result is None:
            time.sleep(idle)
            continue
        print(
            f"oracle-mesh-executor result ok={result.get('ok')} "
            f"retryable={result.get('retryable', False)} "
            f"quarantined={result.get('quarantined', False)}",
            flush=True,
        )
        if result.get("ok") is True:
            continue
        wait = result.get("wait_seconds") if isinstance(result, dict) else None
        if not isinstance(wait, int) or isinstance(wait, bool):
            wait = idle
        time.sleep(max(1, min(wait, 300)))


if __name__ == "__main__":
    raise SystemExit(main())