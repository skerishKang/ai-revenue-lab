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
#: meshctrl downloads are size-bounded by the same limit the server enforces.
MAX_READ_BYTES = 768


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


@dataclass(frozen=True, slots=True)
class OracleMeshExecutionOutcome:
    """What one real execution produced, already size-bounded and hashed."""

    termination: str
    exit_code: int
    body: bytes = b""


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
        timeout_seconds: int = 30,
        transport: Optional[Callable[..., tuple[int, dict[str, Any]]]] = None,
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
        self._origin = chat_origin
        self._secret = channel_secret
        self._read_port = read_port
        self._timeout = timeout_seconds
        self._transport = transport or self._https_post
        self._pending: Optional[tuple[OracleMeshDispatch, OracleMeshExecutionOutcome]] = None

    # ---- channel -------------------------------------------------------
    def _https_post(self, path: str, payload: Optional[dict[str, Any]]) -> tuple[int, dict[str, Any]]:
        """One verified HTTPS POST. Redirects are refused, not followed."""
        url = f"{self._origin}{path}"
        data = json.dumps(payload or {}).encode("utf-8")
        request = urllib.request.Request(
            url, data=data, method="POST",
            headers={
                "Content-Type": "application/json",
                CHANNEL_HEADER: self._secret,
                "Accept": "application/json",
            },
        )
        context = ssl.create_default_context()
        # urllib follows 30x by default; an executor channel must never be
        # silently moved to another origin, so redirects are refused outright.
        opener = urllib.request.build_opener(_NoRedirect())
        try:
            with opener.open(request, timeout=self._timeout) as response:
                raw = response.read(65536)
                status = int(getattr(response, "status", 0) or 0)
        except urllib.error.HTTPError as exc:
            raw = exc.read(4096)
            status = int(exc.code)
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
        return OracleMeshDispatch(
            dispatch_id=_require_text(dispatch.get("dispatch_id"), "dispatch_id"),
            nonce=_require_text(dispatch.get("nonce"), "nonce"),
            node_ref=_require_text(dispatch.get("node_ref"), "node_ref"),
            file_path=_require_text(dispatch.get("file_path"), "file_path"),
            command_id=_require_text(dispatch.get("command_id"), "command_id"),
            run_id=_require_text(dispatch.get("run_id"), "run_id"),
        )

    def execute(self, dispatch: OracleMeshDispatch) -> OracleMeshExecutionOutcome:
        """One real official-client read. Failures are outcomes, not exceptions."""
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

    def submit(
        self, dispatch: OracleMeshDispatch, outcome: OracleMeshExecutionOutcome
    ) -> dict[str, Any]:
        """Submit one outcome, and keep it until the server accepts it.

        A transient store failure answers 503. The exact bytes are then held in
        memory and resent on the next pass — the PC file is never read a second
        time. ``resend_pending`` reports that held outcome so the caller can
        drive the retry without touching the read port again.
        """
        try:
            text = outcome.body.decode("utf-8") if outcome.body else ""
        except UnicodeDecodeError:
            return {"ok": False, "error": {"code": "oracle_mesh_result_not_utf8"}}
        payload = {
            "dispatch_id": dispatch.dispatch_id,
            "nonce": dispatch.nonce,
            "termination": outcome.termination,
            "exit_code": outcome.exit_code,
            "content_utf8": text,
            "content_sha256": hashlib.sha256(outcome.body).hexdigest() if outcome.body else "",
            "content_bytes": len(outcome.body),
        }
        self._pending = (dispatch, outcome)
        status, data = self._post(RESULT_PATH, payload)
        if status == 503:
            # The server parked the verified result; keep the bytes for a resend.
            return {"ok": False, "retryable": True, "resend_pending": True}
        if status != 200 or data.get("ok") is not True:
            raise OracleMeshChannelRefused("chat channel refused the result")
        self._pending = None
        return data

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
    "MAX_READ_BYTES",
    "POLL_PATH",
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
    from .local_agent_meshcentral_private_reader import MeshCentralCliFileReadPort

    def _run(argv, **kwargs):
        import subprocess

        return subprocess.run(argv, capture_output=True, timeout=kwargs.get("timeout", 120))

    read_port = MeshCentralCliFileReadPort(
        command_runner=_run,
        meshctrl_js=meshctrl_js,
        login_user=login_user,
        password_provider=password_provider,
        url=mesh_url,
        work_dir=work_dir,
    )
    return OracleMeshExecutor(
        chat_origin=chat_origin,
        channel_secret=channel_secret,
        read_port=read_port,
        timeout_seconds=timeout_seconds,
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