"""#3580 — server-only owner scoped private Broker Office byte retrieval.

The private Service Binding is NOT a browser route. It returns immutable,
bounded XLSX/PDF bytes from successful broker-correlated staging, never
Google Drive authorization or an arbitrary URL/path.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from hashlib import sha256
import inspect
import math
import re
from typing import Any

from kagent.xlsx_fidelity_route import classify_xlsx, XlsxRoute

MAX_OFFICE_BYTES = 8 * 1024 * 1024
OFFICE_CHUNK_BYTES = 48 * 1024
_SHA = re.compile(r"^[0-9a-f]{64}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_TYPES = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
_KEYS = frozenset({
    "contract_version", "artifact_id", "filename", "media_type",
    "size_bytes", "integrity_ref", "part_index", "part_count", "data_b64",
})


class OfficeBinaryReadRefused(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class VerifiedOfficeBinary:
    artifact_id: str
    filename: str
    kind: str
    media_type: str
    integrity_ref: str
    content: bytes

    @property
    def size_bytes(self) -> int:
        return len(self.content)

    def public_projection(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id, "filename": self.filename,
            "media_type": self.media_type, "size_bytes": self.size_bytes,
            "integrity_ref": self.integrity_ref,
            "private_staging_only": True,
            "drive_write_approval": False,
            "raw_bytes_in_projection": False,
        }


class BrokerOfficeBinaryReader:
    def __init__(self, *, private_binding: Any) -> None:
        method = getattr(private_binding, "read_office_artifact_part", None)
        if not callable(method):
            raise OfficeBinaryReadRefused("trusted private Broker Office read port required")
        self._read = method

    async def read(self, *, owner_id: str, workspace_ref: str,
                   run_ref: str, command_id: str, kind: str) -> VerifiedOfficeBinary:
        if (any(type(x) is not str or not _REF.fullmatch(x) for x in (
                owner_id, workspace_ref, run_ref, command_id,
            )) or type(kind) is not str or kind not in _TYPES):
            raise OfficeBinaryReadRefused("server-derived owner/run/scope required")
        chunks: list[bytes] = []
        expected = None
        index = 0
        while True:
            try:
                response = self._read({
                    "owner": owner_id, "workspace": workspace_ref,
                    "run_id": run_ref, "command_id": command_id,
                    "kind": kind, "part_index": index,
                })
                if inspect.isawaitable(response):
                    response = await response
                if type(response) is not dict or response.get("ok") is not True:
                    raise OfficeBinaryReadRefused("private Office stage unavailable")
                part = response.get("artifact_part")
                if type(part) is not dict or frozenset(part) != _KEYS:
                    raise OfficeBinaryReadRefused("private Office part schema invalid")
                if part["contract_version"] != "claw-office-artifact-read.v1":
                    raise OfficeBinaryReadRefused("private Office part version invalid")
                if (type(part["artifact_id"]) is not str or not _REF.fullmatch(part["artifact_id"])
                        or type(part["filename"]) is not str
                        or not 1 <= len(part["filename"]) <= 160
                        or "/" in part["filename"] or "\\" in part["filename"]
                        or not part["filename"].lower().endswith("."+kind)
                        or part["media_type"] != _TYPES[kind]
                        or type(part["size_bytes"]) is not int
                        or not 0 < part["size_bytes"] <= MAX_OFFICE_BYTES
                        or type(part["part_count"]) is not int
                        or part["part_count"] != math.ceil(part["size_bytes"] / OFFICE_CHUNK_BYTES)
                        or type(part["part_index"]) is not int
                        or part["part_index"] != index
                        or type(part["integrity_ref"]) is not str
                        or not _SHA.fullmatch(part["integrity_ref"])):
                    raise OfficeBinaryReadRefused("private Office material metadata invalid")
                metadata = (
                    part["artifact_id"], part["filename"], part["media_type"],
                    part["size_bytes"], part["integrity_ref"], part["part_count"],
                )
                if expected is None:
                    expected = metadata
                elif expected != metadata:
                    raise OfficeBinaryReadRefused("private Office material changed during read")
                raw = part["data_b64"]
                if (type(raw) is not str or len(raw) > 4*math.ceil(OFFICE_CHUNK_BYTES/3)):
                    raise OfficeBinaryReadRefused("unbounded private Office packet")
                data = base64.b64decode(raw, validate=True)
                if len(data) != min(
                    OFFICE_CHUNK_BYTES, part["size_bytes"] - index*OFFICE_CHUNK_BYTES
                ):
                    raise OfficeBinaryReadRefused("private Office packet size mismatch")
                chunks.append(data)
                index += 1
                if index == part["part_count"]:
                    break
            except Exception as exc:
                # Private bindings may raise provider/token/path exceptions;
                # never forward them to a future HTTP caller.
                if isinstance(exc, OfficeBinaryReadRefused):
                    raise
                raise OfficeBinaryReadRefused("private Office byte retrieval failed") from None
        content = b"".join(chunks)
        if (expected is None or len(content) != expected[3]
                or sha256(content).hexdigest() != expected[4]
                or (kind == "pdf" and (
                    not content.startswith(b"%PDF-")
                    or b"%%EOF" not in content[-1024:]
                ))
                or (kind == "xlsx" and not content.startswith(b"PK\x03\x04"))):
            raise OfficeBinaryReadRefused("private Office whole-file integrity failed")
        if kind == "xlsx" and classify_xlsx(content, local_only=True).route is XlsxRoute.REJECT:
            raise OfficeBinaryReadRefused("untrusted OOXML workbook refused")
        return VerifiedOfficeBinary(
            artifact_id=expected[0], filename=expected[1], kind=kind,
            media_type=expected[2], integrity_ref=expected[4], content=content,
        )


PRODUCTION_OFFICE_PRIVATE_READ_WIRED = False
