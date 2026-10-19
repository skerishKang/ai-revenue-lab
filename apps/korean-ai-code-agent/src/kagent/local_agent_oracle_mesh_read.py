"""#4139 — Oracle management-host MeshCentral read executor (product path).

The Windows Resident trial (``local_agent_meshcentral_resident_lane``) stays a
separate Draft experiment: it executes on the trial PC and is not run here.
This module is the product integration, and it executes on the Oracle
management host, where the official ``meshctrl.js`` client talks to the local
MeshCentral server directly. It never runs on, and never requires, the trial PC.

Authority discipline (what this module does NOT do):

* It mints no approval, no receipt and no evidence. The Claw TXT approval
  receipt stays minted by the Chat issuance module, and broker admission stays
  the broker's. This module only executes an already-authorized read and
  packages its bytes with the exact broker correlation the Chat trigger bound
  to the run.
* It writes no broker state, no conversation and no credential. The result
  package is verified and appended by the Chat return route through the
  existing projection; raw device credentials never cross this boundary.
* It chooses no file and no device. The single authorized target
  (account, device binding, Mesh node, root/pair) comes from deployment-owned
  material, and anything else fails closed — including a receipt-equivalent
  naming any other file.

Ownership is verified, not asserted: the request's (account, device binding,
Mesh node, root/path) quadruple must exactly match one deployment-owned
target row. A partial match is a refusal, never a fallback.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Callable

from .contracts import ContractError
from .local_agent_meshcentral_private_reader import (
    MeshCentralFileReadPort,
    MeshCentralReadRefused,
)

#: Contract markers. This module executes on the Oracle management host only,
#: through the injected official-client port. It never touches a device
#: credential, never writes broker or conversation state, and never mints
#: approval material.
ORACLE_MANAGEMENT_HOST_ONLY = True
OFFICIAL_MESHCTRL_CLIENT = True
DEVICE_CREDENTIAL_TOUCHED = False
BROKER_STATE_WRITTEN = False
CONVERSATION_WRITTEN = False
APPROVAL_MINTED = False
#: The one execution outcome this module can package. Anything else
#: (cancelled, timed out, non-zero exit) is a refusal, never a result.
PACKAGED_TERMINATION = "exited"
PACKAGED_EXIT_CODE = 0
#: Same bound as the broker text results and the conversation projection:
#: oversize is refused, never truncated.
MAX_ORACLE_MESH_READ_BYTES = 768
#: Wire identity of the result package consumed by the Chat return route.
ORACLE_MESH_RESULT_WIRE_VERSION = "claw-oracle-mesh-result.v1"

_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_TEXT_SUFFIX = ".txt"

_CONTRACT_VERSION = "claw-oracle-mesh-read.v1"


def _safe_ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _SAFE_REF_RE.fullmatch(value) is None:
        raise ContractError(f"{field_name} must be a bounded safe reference")
    return value


def _digest(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise ContractError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _windows_file_path(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("file_path must be non-empty text")
    if len(value) > 512:
        raise ContractError("file_path exceeds the bounded length")
    if any(ord(character) < 32 for character in value):
        raise ContractError("file_path carries a control character")
    return value


def _relative_txt_path(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 256
        or any(ord(character) < 32 for character in value)
        or not value.lower().endswith(_TEXT_SUFFIX)
    ):
        raise ContractError("path_relative must be a bounded relative .txt path")
    return value


def _verified_text_bytes(raw: bytes) -> str:
    """Decode bounded file bytes exactly like the broker text gate."""
    if len(raw) > MAX_ORACLE_MESH_READ_BYTES:
        raise MeshCentralReadRefused(
            "the read exceeds the bounded size and is refused, never truncated"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MeshCentralReadRefused("the read is not UTF-8 text") from exc
    if any(ord(character) < 32 and character not in "\n\r\t" for character in text):
        raise MeshCentralReadRefused("the read carries a control character")
    return text


@dataclass(frozen=True, slots=True)
class OracleMeshReadTarget:
    """One deployment-owned authorized read: who, which binding, which node, which file.

    ``account_ref`` is the PADIEM account that owns the Mesh device usage;
    ``device_id``/``binding_ref`` name the canonical broker binding of that
    account's PC; ``node_ref`` is the MeshCentral node this account may read;
    ``root_ref``/``path_relative`` is the single file this target answers.
    All six come from deployment material, never from a request.
    """

    account_ref: str
    device_id: str
    binding_ref: str
    node_ref: str
    root_ref: str
    path_relative: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "account_ref", _safe_ref(self.account_ref, "account_ref"))
        object.__setattr__(self, "device_id", _safe_ref(self.device_id, "device_id"))
        object.__setattr__(self, "binding_ref", _safe_ref(self.binding_ref, "binding_ref"))
        object.__setattr__(self, "node_ref", _safe_ref(self.node_ref, "node_ref"))
        object.__setattr__(self, "root_ref", _safe_ref(self.root_ref, "root_ref"))
        object.__setattr__(
            self, "path_relative", _relative_txt_path(self.path_relative)
        )


@dataclass(frozen=True, slots=True)
class OracleMeshReadCommand:
    """The exact broker-bound correlation this execution answers.

    Every field echoes the Chat trigger's stored correlation for the run.
    The executor never invents one: a package whose fields disagree with the
    stored correlation is refused by the return route, not repaired here.
    """

    command_id: str
    run_id: str
    tool_request_ref: str
    request_id: str
    revision_ref: str
    evidence_ref: str
    request_fingerprint: str

    def __post_init__(self) -> None:
        for name in (
            "command_id", "run_id", "tool_request_ref", "request_id",
            "revision_ref", "evidence_ref",
        ):
            object.__setattr__(self, name, _safe_ref(getattr(self, name), name))
        object.__setattr__(
            self, "request_fingerprint",
            _digest(self.request_fingerprint, "request_fingerprint"),
        )


def verify_oracle_mesh_ownership(
    *,
    targets: Any,
    account_ref: str,
    device_id: str,
    binding_ref: str,
    node_ref: str,
    root_ref: str,
    path_relative: str,
) -> OracleMeshReadTarget:
    """Match the request quadruple against exactly one deployment-owned target.

    All six facts must agree on a single target row. A partial match (right
    account on the wrong node, right node for the wrong file, or a binding
    the deployment never authorized) fails closed: there is no fallback row
    and no nearest match.
    """
    if not isinstance(targets, (list, tuple)) or not targets:
        raise ContractError("deployment mesh targets are required")
    matches = [
        target
        for target in targets
        if isinstance(target, OracleMeshReadTarget)
        and target.account_ref == account_ref
        and target.device_id == device_id
        and target.binding_ref == binding_ref
        and target.node_ref == node_ref
        and target.root_ref == root_ref
        and target.path_relative == path_relative
    ]
    if len(matches) != 1:
        raise ContractError("no single authorized mesh target for this request")
    return matches[0]


def execute_oracle_mesh_read(
    *,
    port: MeshCentralFileReadPort,
    node_ref: str,
    file_path: str,
    timeout_seconds: int = 120,
) -> bytes:
    """Run the authorized read through the injected official-client port.

    The port carries the MeshCentral operator credential the same way the
    merged private reader does (call-time provider, stdin only, marker on
    argv); this module never sees it.
    """
    if not callable(getattr(port, "read_bytes", None)):
        raise ContractError("a private MeshCentral file read port is required")
    return port.read_bytes(
        node_ref=_safe_ref(node_ref, "node_ref"),
        file_path=_windows_file_path(file_path),
        timeout_seconds=timeout_seconds,
    )


def build_oracle_mesh_result_package(
    *,
    command: OracleMeshReadCommand,
    content: bytes,
    termination: str = PACKAGED_TERMINATION,
    exit_code: int = PACKAGED_EXIT_CODE,
) -> dict[str, Any]:
    """Package verified bytes with the exact bound correlation.

    Only a clean ``exited/0`` execution becomes a package. The content gate
    mirrors the broker text gate byte for byte: bounded size, UTF-8, no
    control characters, SHA-256 over the exact bytes.
    """
    if not isinstance(command, OracleMeshReadCommand):
        raise ContractError("the bound broker correlation is required")
    if termination != PACKAGED_TERMINATION or exit_code != PACKAGED_EXIT_CODE:
        raise MeshCentralReadRefused(
            "only a clean exited/0 execution becomes a result package"
        )
    text = _verified_text_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    return {
        "contract_version": ORACLE_MESH_RESULT_WIRE_VERSION,
        "command_id": command.command_id,
        "run_id": command.run_id,
        "tool_request_ref": command.tool_request_ref,
        "request_id": command.request_id,
        "revision_ref": command.revision_ref,
        "evidence_ref": command.evidence_ref,
        "request_fingerprint": command.request_fingerprint,
        "termination": termination,
        "exit_code": exit_code,
        "content_utf8": text,
        "content_sha256": digest,
        "content_bytes": len(content),
    }


def verify_oracle_mesh_result_package(
    *, package: Any, command: OracleMeshReadCommand
) -> str:
    """Revalidate a package against the bound correlation; return the text.

    The Chat return route calls this before appending anything: correlation
    equality, wire identity, execution outcome, size, UTF-8, control
    characters and digest are all rechecked here, so a tampered or
    cross-command package fails closed at the gate.
    """
    if not isinstance(command, OracleMeshReadCommand):
        raise ContractError("the bound broker correlation is required")
    if type(package) is not dict:
        raise ContractError("result package must be a mapping")
    expected_keys = frozenset({
        "contract_version", "command_id", "run_id", "tool_request_ref",
        "request_id", "revision_ref", "evidence_ref", "request_fingerprint",
        "termination", "exit_code", "content_utf8", "content_sha256",
        "content_bytes",
    })
    if frozenset(package) != expected_keys:
        raise ContractError("result package schema mismatch")
    if package["contract_version"] != ORACLE_MESH_RESULT_WIRE_VERSION:
        raise ContractError("result package version mismatch")
    for name in (
        "command_id", "run_id", "tool_request_ref", "request_id",
        "revision_ref", "evidence_ref", "request_fingerprint",
    ):
        if package[name] != getattr(command, name):
            raise ContractError("result package does not match the bound command")
    if package["termination"] != PACKAGED_TERMINATION or package["exit_code"] != PACKAGED_EXIT_CODE:
        raise ContractError("result package carries no clean execution")
    text = package["content_utf8"]
    if type(text) is not str:
        raise ContractError("result package content type invalid")
    try:
        raw = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContractError("result package UTF-8 malformed") from exc
    if (
        len(raw) > MAX_ORACLE_MESH_READ_BYTES
        or package["content_bytes"] != len(raw)
        or any(ord(character) < 32 and character not in "\n\r\t" for character in text)
        or package["content_sha256"] != hashlib.sha256(raw).hexdigest()
    ):
        raise ContractError("result package integrity invalid")
    return text


__all__ = [
    "APPROVAL_MINTED",
    "BROKER_STATE_WRITTEN",
    "CONVERSATION_WRITTEN",
    "DEVICE_CREDENTIAL_TOUCHED",
    "MAX_ORACLE_MESH_READ_BYTES",
    "OFFICIAL_MESHCTRL_CLIENT",
    "ORACLE_MANAGEMENT_HOST_ONLY",
    "ORACLE_MESH_RESULT_WIRE_VERSION",
    "OracleMeshReadCommand",
    "OracleMeshReadTarget",
    "build_oracle_mesh_result_package",
    "execute_oracle_mesh_read",
    "verify_oracle_mesh_ownership",
    "verify_oracle_mesh_result_package",
]
