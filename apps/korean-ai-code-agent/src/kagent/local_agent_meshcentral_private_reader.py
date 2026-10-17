"""#4139 trial — MeshCentral private-read executor for the canonical TXT lane.

The trial PC reaches MeshCentral only through the dedicated private Cloudflare
tunnel (Claw Worker → Workers VPC Service → COM1 QUIC tunnel → local ssh -L →
the Oracle MeshCentral on 127.0.0.1:4443). There is no public inbound port and
no second PC protocol: the one real file read is performed by the OFFICIAL
MeshCentral client (``meshctrl.js download``) over that private path.

This module is the *executor half* between the canonical admitted command and
the canonical producer :mod:`kagent.local_agent_verified_text_result`. It hands
the *bytes actually read* to the existing bounded builder — nothing here mints
a credential, opens a route, or invents a second TXT upload path.

    OFFICIAL_MESHCTRL_CLIENT=1 · PUBLIC_INBOUND_PORT=0
    SECOND_PC_PROTOCOL=0 · SECOND_TXT_UPLOAD_PATH=0
    TRUNCATION_AS_COMPLETENESS=0 · PASSWORD_IN_MODULE_STATE=0

The canonical order (§4139 resident contract) is preserved by the call shape:

    declare pending (readable before the ACK) → real READ (bytes preserved)
      → [successful ACK: the command plane, not this module] → deliver

:meth:`MeshCentralVerifiedTextReader.execute_verified_read` performs the
declare + read and returns the preserved :class:`VerifiedTextResult`; the
caller delivers it after the canonical ACK. :meth:`deliver` and
:meth:`replay` re-send the *same* bytes — nothing here re-executes a task,
re-reads a file or answers a refused read with content.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from typing import Any, Callable, Protocol
from uuid import uuid4

from .contracts import ContractError
from .local_agent_verified_text_result import (
    MAX_VERIFIED_TEXT_RESULT_BYTES,
    LocalAgentTextResultPublisher,
    VerifiedTextResult,
    VerifiedTextResultRefused,
    build_verified_text_result,
)

#: #4139 wire envelope for one file body: the same 6 MB the Claw request
#: route already accepts for one user message. The former 768-byte trial cap
#: could not read a normal document.
MAX_READ_ENVELOPE_BYTES = 6_000_000

#: Byte-identical to the producer's own ``safe_ref`` pattern.
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_MAX_FILE_PATH_CHARS = 512

# The official MeshCtrl CLI remains unchanged. Inject the password via stdin
# inside a Node bootstrap, so the operating system argv never contains it.
_PASSWORD_MARKER = "__PADIEM_MESHCTRL_PASSWORD_FROM_STDIN__"
_MESHCTRL_STDIN_BOOTSTRAP = (
    "const fs=require('node:fs');"
    "const marker='__PADIEM_MESHCTRL_PASSWORD_FROM_STDIN__';"
    "const i=process.argv.indexOf(marker);"
    "if(i<0)process.exit(2);"
    "let secret=fs.readFileSync(0,'utf8');"
    "secret=secret.replace(/\\r?\\n$/,'');"
    "if(!secret)process.exit(3);"
    "process.argv[i]=secret;"
    "require(process.argv[1]);"
)



class MeshCentralReadRefused(ValueError):
    """Bounded refusal of one private read. Never carries content or secrets."""


def _safe_ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _SAFE_REF_RE.fullmatch(value) is None:
        raise MeshCentralReadRefused(f"{field_name} must be a bounded safe reference")
    return value


def _windows_file_path(value: Any) -> str:
    """The path asserted by the admitted plan, never chosen by this module.

    Windows paths contain ``\\`` and ``:``, so the safe-ref alphabet does not
    apply; the bound is length plus "no control characters".
    """

    if not isinstance(value, str) or not value.strip():
        raise MeshCentralReadRefused("file_path must be non-empty text")
    if len(value) > _MAX_FILE_PATH_CHARS:
        raise MeshCentralReadRefused("file_path exceeds the bounded length")
    if any(ord(character) < 32 for character in value):
        raise MeshCentralReadRefused("file_path carries a control character")
    return value


@dataclass(frozen=True, slots=True)
class MeshCentralFileReadRequest:
    """One read of one file on one MeshCentral node, over the private path."""

    node_ref: str
    file_path: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_ref", _safe_ref(self.node_ref, "node_ref"))
        object.__setattr__(self, "file_path", _windows_file_path(self.file_path))


class CommandResultLike(Protocol):
    returncode: int


class MeshCentralFileReadPort(Protocol):
    def read_bytes(
        self, *, node_ref: str, file_path: str, timeout_seconds: int
    ) -> bytes: ...


class MeshCentralCliFileReadPort:
    """The concrete private read over the official ``meshctrl.js`` client.

    ``command_runner`` is injected, so the process boundary is explicit and
    testable: it receives argv and a one-use ``input`` string and must return
    an object exposing ``returncode`` (a ``subprocess.run`` result fits).
    The password comes from ``password_provider`` at invocation time, travels
    over the child process's stdin, and is placed into the official MeshCtrl
    argument parser by a Node bootstrap inside the child. The OS command line
    carries only a public marker, never the password.
    """

    def __init__(
        self,
        *,
        command_runner: Callable[..., CommandResultLike],
        meshctrl_js: str,
        login_user: str,
        password_provider: Callable[[], str],
        url: str = "wss://127.0.0.1:4443",
        work_dir: str | None = None,
    ) -> None:
        if not callable(command_runner):
            raise ContractError("meshcentral read requires an injected command runner")
        if not isinstance(meshctrl_js, str) or not meshctrl_js.strip():
            raise ContractError("the official meshctrl.js path is required")
        self._meshctrl_js = meshctrl_js
        self._login_user = _safe_ref(login_user, "login_user")
        if not callable(password_provider):
            raise ContractError("the login password must be provided at call time")
        self._password_provider = password_provider
        if not isinstance(url, str) or not url.startswith("wss://") or "@" in url:
            raise ContractError("the private tunnel URL must be a wss:// endpoint")
        self._url = url
        self._work_dir = work_dir or tempfile.gettempdir()
        self._command_runner = command_runner

    def read_bytes(
        self,
        *,
        node_ref: str,
        file_path: str,
        timeout_seconds: int = 60,
        #: #4139: the read lane no longer carries a trial-era byte cap. The
        #: caller passes the wire envelope; an oversize read is refused whole
        #: (never truncated) so the caller can report it explicitly.
        max_bytes: int = MAX_READ_ENVELOPE_BYTES,
    ) -> bytes:
        request = MeshCentralFileReadRequest(node_ref=node_ref, file_path=file_path)
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
            raise MeshCentralReadRefused("timeout_seconds must be an integer")
        target = os.path.join(
            self._work_dir, f"padiem-mesh-read-{os.getpid()}-{uuid4().hex}.bin"
        )
        argv = [
            "node", "-e", _MESHCTRL_STDIN_BOOTSTRAP,
            self._meshctrl_js, "download",
            "--url", self._url,
            "--loginuser", self._login_user,
            "--loginpass", _PASSWORD_MARKER,
            "--id", request.node_ref,
            "--file", request.file_path,
            "--target", target,
        ]
        try:
            password = self._password_provider()
            if (not isinstance(password, str) or not password
                    or "\n" in password or "\r" in password):
                raise MeshCentralReadRefused(
                    "the protected MeshCentral operator credential is invalid"
                )
            # The official CLI parses the credential only inside the child;
            # neither the OS command line nor command logs contain it.
            completed = self._command_runner(
                argv, input=password + "\n",
                timeout=timeout_seconds,
            )
            if getattr(completed, "returncode", None) != 0:
                raise MeshCentralReadRefused(
                    "the official meshcentral client refused the private read"
                )
            try:
                if os.path.getsize(target) > max_bytes:
                    raise MeshCentralReadRefused(
                        "the read exceeds the bounded size and is refused, "
                        "never truncated"
                    )
                with open(target, "rb") as staged:
                    raw = staged.read(max_bytes + 1)
            except FileNotFoundError:
                raise MeshCentralReadRefused(
                    "the official meshcentral client wrote no staged read"
                ) from None
        finally:
            try:
                os.remove(target)
            except OSError:
                pass
        if len(raw) > max_bytes:
            raise MeshCentralReadRefused(
                "the read exceeds the bounded size and is refused, never truncated"
            )
        return raw


class MeshCentralVerifiedTextReader:
    """declare → real private read → preserved canonical result → deliver.

    The ACK sits between :meth:`execute_verified_read` and :meth:`deliver` and
    belongs to the canonical command plane; this class never issues it.
    """

    def __init__(
        self,
        *,
        publisher: LocalAgentTextResultPublisher,
        port: MeshCentralFileReadPort,
    ) -> None:
        if not isinstance(publisher, LocalAgentTextResultPublisher):
            raise ContractError("the canonical verified text publisher is required")
        if not callable(getattr(port, "read_bytes", None)):
            raise ContractError("a private MeshCentral file read port is required")
        self._publisher = publisher
        self._port = port

    def declare_pending(
        self,
        *,
        binding_ref: str,
        credential: bytes,
        command_id: str,
        run_id: str,
        request_fingerprint: str,
        timeout_seconds: int = 20,
    ) -> dict[str, Any]:
        """Register the intent before the read, so Claw holds the message id."""

        return self._publisher.declare_pending(
            binding_ref=binding_ref, credential=credential,
            command_id=command_id, run_id=run_id,
            request_fingerprint=request_fingerprint,
            timeout_seconds=timeout_seconds,
        )

    def read_verified_result(
        self,
        *,
        command_id: str,
        run_id: str,
        request_fingerprint: str,
        node_ref: str,
        file_path: str,
        timeout_seconds: int = 60,
        max_bytes: int = MAX_READ_ENVELOPE_BYTES,
    ) -> VerifiedTextResult:
        """The one real read. The bytes are the authority; oversize refuses."""

        raw = self._port.read_bytes(
            node_ref=_safe_ref(node_ref, "node_ref"),
            file_path=_windows_file_path(file_path),
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
        )
        if not isinstance(raw, (bytes, bytearray)) or not raw:
            raise MeshCentralReadRefused(
                "the private read returned no bytes; a bodyless success is "
                "never reported"
            )
        return build_verified_text_result(
            command_id=command_id, run_id=run_id,
            request_fingerprint=request_fingerprint, content=bytes(raw),
            max_bytes=max_bytes,
        )

    def execute_verified_read(
        self,
        *,
        binding_ref: str,
        credential: bytes,
        command_id: str,
        run_id: str,
        request_fingerprint: str,
        node_ref: str,
        file_path: str,
        declare_timeout_seconds: int = 20,
        read_timeout_seconds: int = 60,
        max_bytes: int = MAX_READ_ENVELOPE_BYTES,
    ) -> tuple[dict[str, Any], VerifiedTextResult]:
        """Declare pending first, then read and preserve the real bytes."""

        stored = self.declare_pending(
            binding_ref=binding_ref, credential=credential,
            command_id=command_id, run_id=run_id,
            request_fingerprint=request_fingerprint,
            timeout_seconds=declare_timeout_seconds,
        )
        result = self.read_verified_result(
            command_id=command_id, run_id=run_id,
            request_fingerprint=request_fingerprint,
            node_ref=node_ref, file_path=file_path,
            timeout_seconds=read_timeout_seconds,
            max_bytes=max_bytes,
        )
        return stored, result

    def deliver(
        self,
        *,
        binding_ref: str,
        credential: bytes,
        result: VerifiedTextResult,
        timeout_seconds: int = 20,
    ) -> dict[str, Any]:
        """Upload the preserved bytes. Success means the broker stored them."""

        return self._publisher.deliver(
            binding_ref=binding_ref, credential=credential,
            result=result, timeout_seconds=timeout_seconds,
        )

    def replay(
        self,
        *,
        binding_ref: str,
        credential: bytes,
        result: VerifiedTextResult,
        timeout_seconds: int = 20,
    ) -> dict[str, Any]:
        """Retry the identical upload; never a second read of the file."""

        return self._publisher.replay(
            binding_ref=binding_ref, credential=credential,
            result=result, timeout_seconds=timeout_seconds,
        )


__all__ = [
    "MeshCentralCliFileReadPort",
    "MeshCentralFileReadPort",
    "MeshCentralFileReadRequest",
    "MeshCentralReadRefused",
    "MeshCentralVerifiedTextReader",
]

SECOND_PC_PROTOCOL = False
SECOND_TXT_UPLOAD_PATH = False
PUBLIC_INBOUND_PORT = False
TRUNCATION_AS_COMPLETENESS = False
PASSWORD_IN_MODULE_STATE = False
OFFICIAL_MESHCTRL_CLIENT = True
