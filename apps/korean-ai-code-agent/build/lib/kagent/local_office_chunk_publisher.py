"""#3580: real outbound HTTPS body transfer for an *already-approved* Office run.

This publishes immutable private staging material via the canonical pinned
TLS broker client. It never grants an Office execute/Google Drive WRITE/READ
permission, and it does not activate itself in the resident process.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from hashlib import sha256
from math import ceil
import re

from .contracts import ContractError
from .local_agent_control_plane_https import (
    ControlPlaneHttpsOperation, PinnedHttpsJsonRequestPort,
)
from .local_agent_secure_transport import OutboundTransportConfig
from .xlsx_fidelity_route import classify_xlsx, XlsxRoute

MAX_OFFICE_OUTPUT_BYTES = 8 * 1024 * 1024
OFFICE_TRANSFER_CHUNK_BYTES = 48 * 1024
_FILENAME = re.compile(r"^[^/\\\\\x00-\x1f\x7f]{1,160}$")
_MIME = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


@dataclass(frozen=True, slots=True)
class PrivateOfficeStagingReceipt:
    artifact_id: str
    integrity_ref: str
    part_count: int
    private_staging_only: bool = True
    drive_upload_granted: bool = False


class LocalOfficeChunkPublisher:
    """One explicit outbound invocation using the existing HTTPS/443 transport."""

    def __init__(self, *, transport: PinnedHttpsJsonRequestPort,
                 config: OutboundTransportConfig) -> None:
        if not callable(getattr(transport, "post", None)) or not isinstance(config, OutboundTransportConfig):
            raise ContractError("trusted pinned HTTPS transport and config required")
        self._transport = transport
        self._config = config

    def publish(self, *, binding_ref: str, credential: bytes,
                command_id: str, run_id: str, artifact_id: str, filename: str,
                media_type: str, content: bytes, kind: str,
                timeout_seconds: int = 20) -> PrivateOfficeStagingReceipt:
        # These are only staging packets. The canonical broker verifies exact
        # binding / command ACK and success independently; no client assertion
        # may supply user/workspace, consent, or a Drive destination.
        if (kind not in _MIME or type(kind) is not str
                or type(filename) is not str or not _FILENAME.fullmatch(filename)
                or filename in (".", "..") or not filename.lower().endswith("."+kind)
                or media_type != _MIME[kind]
                or type(content) is not bytes
                or not 0 < len(content) <= MAX_OFFICE_OUTPUT_BYTES
                or type(credential) is not bytes or not credential
                or any(type(ref) is not str or not re.fullmatch(
                    r"[A-Za-z0-9][A-Za-z0-9._:@+\\-]{0,255}", ref
                ) for ref in (binding_ref, command_id, run_id, artifact_id))
                or type(timeout_seconds) is not int
                or not 1 <= timeout_seconds <= 60):
            raise ContractError("approved bounded Office staging material required")
        if ((kind == "pdf" and (
                not content.startswith(b"%PDF-") or b"%%EOF" not in content[-1024:]
            )) or (kind == "xlsx" and not content.startswith(b"PK\x03\x04"))):
            raise ContractError("Office output binary signature is not supported")
        if kind == "xlsx" and classify_xlsx(content, local_only=True).route is XlsxRoute.REJECT:
            raise ContractError("untrusted OOXML workbook rejected before staging")
        count = ceil(len(content) / OFFICE_TRANSFER_CHUNK_BYTES)
        integrity = sha256(content).hexdigest()
        token = base64.b64encode(credential).decode("ascii")
        for index in range(count):
            part = content[index*OFFICE_TRANSFER_CHUNK_BYTES:(index+1)*OFFICE_TRANSFER_CHUNK_BYTES]
            wire = {
                "binding_ref": binding_ref,
                "credential_b64": token,
                "contract_version": "claw-office-artifact-chunk.v1",
                "command_id": command_id, "run_id": run_id,
                "kind": kind, "artifact_id": artifact_id,
                "filename": filename, "media_type": media_type,
                "size_bytes": len(content), "integrity_ref": integrity,
                "part_index": index, "part_count": count,
                "part_sha256": sha256(part).hexdigest(),
                "data_b64": base64.b64encode(part).decode("ascii"),
            }
            response = self._transport.post(
                config=self._config, operation=ControlPlaneHttpsOperation.OFFICE_PART,
                payload=wire, timeout_seconds=timeout_seconds,
            )
            if (type(response) is not dict or response.get("ok") is not True
                    or type(response.get("office_part")) is not dict
                    or response["office_part"].get("stored") is not True
                    or response["office_part"].get("kind") != kind
                    or response["office_part"].get("part_index") != index):
                # No transparent retry: re-invocation must be explicit. Exact
                # part replay is safe server-side; provider WRITE is unrelated.
                raise ContractError("broker refused authenticated Office part")
        return PrivateOfficeStagingReceipt(
            artifact_id=artifact_id, integrity_ref=integrity, part_count=count,
        )


LOCAL_OFFICE_CHUNK_PUBLISHER_RESIDENT_COMPOSED = False
