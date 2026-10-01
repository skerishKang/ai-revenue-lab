"""Private B67 selected-case-folder PDF acquisition service (#3350).

This service does not add a generic Drive binary tool. It composes only the
existing workspace-scoped Drive grant, durable selected-folder authority,
Core case-folder admission contract, and Engine's bounded readonly Drive port.

The first slice is deliberately direct-child only. A provider result must carry
the selected folder in its own parent facts before this service mints a trusted
direct-parent proof and calls the existing Engine admission seam.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from inspect import isawaitable
from typing import Any
from urllib.parse import quote

from padiem_ai_core.drive_capability import (
    DRIVE_BASE_URL,
    DRIVE_READONLY_SCOPE,
    FILE_FIELDS,
    MAX_PROVIDER_LIST_BYTES,
    MAX_PROVIDER_METADATA_BYTES,
)
from padiem_ai_core.drive_case_folder_scope import (
    DriveCaseFolderScope,
    DriveCaseResource,
    DriveCaseResourceKind,
    DriveTrustedAncestryProof,
)

from app.connector_bindings import DriveGrant
from app.drive_case_folder_binding import (
    DriveCaseFolderBindingAuthority,
    DriveCaseFolderBindingError,
)
from app.drive_case_folder_scope_projection import (
    EngineDriveCaseFolderScopeError,
    admit_case_folder_resource,
    case_folder_provider_params,
)
from app.drive_case_folder_service import DriveCaseFolderGrantProvider
from app.drive_port_cp_lease import MAX_GOOGLE_API_RESPONSE_BYTES
from padiem_ai_core.tool_runtime import ToolHandlerError

B67_CASE_PDF_SERVICE_VERSION = "engine-b67-case-pdf.v1"
PDF_MIME_TYPE = "application/pdf"
MAX_B67_CASE_PDF_BYTES = MAX_GOOGLE_API_RESPONSE_BYTES
MAX_B67_PDF_QUERY_CHARS = 200
MAX_B67_PDF_CANDIDATES = 25
_DIRECT_PARENT_RESOLVER_REF = "b67-direct-parent-query-v1"


class DriveCasePdfError(ValueError):
    """Bounded first-party error; never includes Drive ids or provider bodies."""

    def __init__(self, code: str, safe_message: str, *, status_code: int = 400) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


def _bounded(value: object, *, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > limit:
        return None
    return normalized


async def _await(value: Any) -> Any:
    return await value if isawaitable(value) else value


class DriveCasePdfService:
    """Acquire direct-child case PDFs after canonical selected-folder admission."""

    def __init__(
        self,
        *,
        grant_provider: DriveCaseFolderGrantProvider | None,
        drive_port: object | None,
        binding_authority: DriveCaseFolderBindingAuthority | None,
    ) -> None:
        self._grant_provider = grant_provider
        self._drive_port = drive_port
        self._binding_authority = binding_authority

    def __repr__(self) -> str:
        return "DriveCasePdfService(configured)"

    async def _scope(
        self, *, workspace_ref: str, project_id: str
    ) -> tuple[DriveGrant, DriveCaseFolderScope]:
        if self._grant_provider is None:
            raise DriveCasePdfError(
                "drive_authority_unavailable",
                "Drive authority is unavailable.",
                status_code=503,
            )
        if self._binding_authority is None:
            raise DriveCasePdfError(
                "binding_authority_unavailable",
                "Selected-folder authority is unavailable.",
                status_code=503,
            )
        grant = await self._grant_provider.current_drive_grant(workspace_ref=workspace_ref)
        if not isinstance(grant, DriveGrant):
            raise DriveCasePdfError(
                "drive_not_connected",
                "Google Drive is not connected for this workspace.",
                status_code=409,
            )
        try:
            scope = await self._binding_authority.load_case_folder_scope(
                workspace_ref=workspace_ref,
                project_id=project_id,
                drive_grant=grant,
            )
        except DriveCaseFolderBindingError:
            raise
        if not isinstance(scope, DriveCaseFolderScope):
            raise DriveCasePdfError(
                "drive_case_folder_unavailable",
                "Selected case-folder authority is unavailable.",
                status_code=503,
            )
        return grant, scope

    def _port_method(self, name: str):
        method = getattr(self._drive_port, name, None) if self._drive_port is not None else None
        if not callable(method):
            raise DriveCasePdfError(
                "drive_port_unavailable",
                "Trusted Drive read authority is unavailable.",
                status_code=503,
            )
        return method

    async def _json(
        self,
        grant: DriveGrant,
        *,
        path: str,
        query: dict[str, str],
        max_response_bytes: int,
    ) -> Mapping[str, Any]:
        method = self._port_method("get_json")
        try:
            result = await _await(
                method(
                    binding_ref=grant.binding_ref,
                    actor_ref=grant.actor_ref,
                    required_scopes=(DRIVE_READONLY_SCOPE,),
                    base_url=DRIVE_BASE_URL,
                    path=path,
                    query=query,
                    timeout_seconds=30,
                    max_response_bytes=max_response_bytes,
                )
            )
        except (ToolHandlerError, ValueError):
            raise DriveCasePdfError(
                "drive_provider_unavailable",
                "Drive provider read is unavailable.",
                status_code=502,
            ) from None
        if not isinstance(result, Mapping):
            raise DriveCasePdfError(
                "drive_provider_contract_failed",
                "Drive provider metadata did not match the reviewed contract.",
                status_code=502,
            )
        return result

    async def _bytes(
        self,
        grant: DriveGrant,
        *,
        file_id: str,
    ) -> bytes:
        method = self._port_method("get_bytes")
        try:
            result = await _await(
                method(
                    binding_ref=grant.binding_ref,
                    actor_ref=grant.actor_ref,
                    required_scopes=(DRIVE_READONLY_SCOPE,),
                    base_url=DRIVE_BASE_URL,
                    path=f"/files/{quote(file_id, safe='')}",
                    query={"alt": "media", "supportsAllDrives": "true"},
                    timeout_seconds=30,
                    max_response_bytes=MAX_B67_CASE_PDF_BYTES,
                )
            )
        except (ToolHandlerError, ValueError):
            raise DriveCasePdfError(
                "drive_provider_unavailable",
                "Drive PDF content is unavailable.",
                status_code=502,
            ) from None
        if not isinstance(result, bytes):
            raise DriveCasePdfError(
                "drive_provider_contract_failed",
                "Drive PDF content did not match the reviewed contract.",
                status_code=502,
            )
        return result

    @staticmethod
    def _admit_direct_child(
        scope: DriveCaseFolderScope,
        grant: DriveGrant,
        metadata: Mapping[str, Any],
    ) -> tuple[DriveCaseResource, dict[str, Any]]:
        try:
            resource = DriveCaseResource.from_provider(
                binding_ref=grant.binding_ref,
                metadata=metadata,
            )
        except Exception:
            raise DriveCasePdfError(
                "drive_provider_contract_failed",
                "Drive provider metadata did not match the reviewed contract.",
                status_code=502,
            ) from None
        if scope.selected_folder_id not in resource.observed_parent_ids:
            raise DriveCasePdfError(
                "drive_parent_contract_failed",
                "Drive resource did not confirm the selected case folder as its parent.",
                status_code=502,
            )
        proof = DriveTrustedAncestryProof(
            binding_ref=grant.binding_ref,
            resource_id=resource.resource_id,
            ancestor_folder_ids=(scope.selected_folder_id,),
            resolver_ref=_DIRECT_PARENT_RESOLVER_REF,
        )
        try:
            admission = admit_case_folder_resource(scope, resource, ancestry=proof)
        except EngineDriveCaseFolderScopeError:
            raise DriveCasePdfError(
                "drive_case_folder_scope_denied",
                "Drive resource is outside the selected case folder.",
                status_code=403,
            ) from None
        return resource, admission

    @staticmethod
    def _pdf_projection(resource: DriveCaseResource) -> dict[str, Any] | None:
        if resource.kind is not DriveCaseResourceKind.FILE:
            return None
        if resource.mime_type.split(";", 1)[0].strip().lower() != PDF_MIME_TYPE:
            return None
        projection = resource.evidence
        if projection is None:
            return None
        size = projection.size_bytes
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            intake_state = "size_unverified"
        elif size > MAX_B67_CASE_PDF_BYTES:
            intake_state = "execution_fallback_required"
        else:
            intake_state = "browser_pdf_ready"
        return {
            "file_id": resource.resource_id,
            "name": projection.name,
            "mime_type": PDF_MIME_TYPE,
            "size_bytes": size,
            "modified_time": projection.modified_time,
            "space_kind": resource.space_kind,
            "intake_state": intake_state,
        }

    async def candidates(
        self,
        *,
        workspace_ref: str,
        project_id: str,
        query: str | None = None,
    ) -> dict[str, Any]:
        normalized_query = None
        if query is not None:
            normalized_query = _bounded(query, limit=MAX_B67_PDF_QUERY_CHARS)
            if normalized_query is None:
                raise DriveCasePdfError("invalid_query", "PDF search query is invalid.")
        grant, scope = await self._scope(
            workspace_ref=workspace_ref,
            project_id=project_id,
        )
        params = case_folder_provider_params(scope, text_query=normalized_query)
        # MIME predicate is a trusted constant and can only narrow the Core
        # selected-folder query.
        params["q"] = f"({params['q']}) and mimeType = '{PDF_MIME_TYPE}'"
        params["fields"] = f"nextPageToken,files({FILE_FIELDS})"
        if normalized_query is None:
            params["orderBy"] = "modifiedTime desc"
        body = await self._json(
            grant,
            path="/files",
            query=params,
            max_response_bytes=MAX_PROVIDER_LIST_BYTES,
        )
        raw_files = body.get("files", [])
        if not isinstance(raw_files, list):
            raise DriveCasePdfError(
                "drive_provider_contract_failed",
                "Drive provider file list is invalid.",
                status_code=502,
            )
        candidates: list[dict[str, Any]] = []
        for raw in raw_files[:MAX_B67_PDF_CANDIDATES]:
            if not isinstance(raw, Mapping):
                raise DriveCasePdfError(
                    "drive_provider_contract_failed",
                    "Drive provider file list is invalid.",
                    status_code=502,
                )
            resource, _admission = self._admit_direct_child(scope, grant, raw)
            projected = self._pdf_projection(resource)
            if projected is not None:
                candidates.append(projected)
        return {
            "ok": True,
            "files": candidates,
            "more": bool(body.get("nextPageToken")),
            "direct_child_only": True,
            "contract_version": B67_CASE_PDF_SERVICE_VERSION,
        }

    async def read(
        self,
        *,
        workspace_ref: str,
        project_id: str,
        file_id: object,
    ) -> dict[str, Any]:
        intent = _bounded(file_id, limit=200)
        if intent is None:
            raise DriveCasePdfError("invalid_file_id", "PDF selection intent is invalid.")

        grant, scope = await self._scope(
            workspace_ref=workspace_ref,
            project_id=project_id,
        )
        metadata = await self._json(
            grant,
            path=f"/files/{quote(intent, safe='')}",
            query={"fields": FILE_FIELDS, "supportsAllDrives": "true"},
            max_response_bytes=MAX_PROVIDER_METADATA_BYTES,
        )
        resource, admission = self._admit_direct_child(scope, grant, metadata)
        projected = self._pdf_projection(resource)
        if projected is None:
            raise DriveCasePdfError(
                "not_pdf",
                "Selected Drive resource is not an eligible PDF.",
                status_code=415,
            )
        size = projected["size_bytes"]
        if not isinstance(size, int) or isinstance(size, bool) or size < 1:
            raise DriveCasePdfError(
                "pdf_size_unverifiable",
                "Selected PDF size could not be verified.",
                status_code=422,
            )
        if size > MAX_B67_CASE_PDF_BYTES:
            raise DriveCasePdfError(
                "execution_fallback_required",
                "Selected PDF exceeds the browser acquisition byte limit.",
                status_code=413,
            )

        payload = await self._bytes(grant, file_id=resource.resource_id)
        if not payload or len(payload) != size:
            raise DriveCasePdfError(
                "pdf_integrity_mismatch",
                "Selected PDF bytes do not match provider metadata.",
                status_code=502,
            )
        if not payload.startswith(b"%PDF-"):
            raise DriveCasePdfError(
                "pdf_signature_mismatch",
                "Selected Drive content is not a PDF payload.",
                status_code=415,
            )

        source = resource.evidence
        version = (
            {
                "version": source.version,
                "modified_time": source.modified_time,
                "md5_checksum": source.md5_checksum,
                "sha256_checksum": source.sha256_checksum,
                "head_revision_id": source.head_revision_id,
            }
            if source is not None
            else {}
        )
        return {
            "ok": True,
            "file": projected,
            "content_base64": base64.b64encode(payload).decode("ascii"),
            "byte_size": len(payload),
            "version_evidence": version,
            "authorization": {
                "direct_parent_proof": admission.get("ancestry_proof_trusted") is True,
                "source_type": "drive",
            },
            "contract_version": B67_CASE_PDF_SERVICE_VERSION,
        }


def drive_case_pdf_service_snapshot() -> dict[str, Any]:
    return {
        "service_version": B67_CASE_PDF_SERVICE_VERSION,
        "pdf_mime": PDF_MIME_TYPE,
        "max_pdf_bytes": MAX_B67_CASE_PDF_BYTES,
        "direct_child_only": True,
        "generic_drive_binary_tool": False,
        "canonical_selected_folder_authority_reused": True,
        "canonical_workspace_grant_reused": True,
        "cp_access_lease_reused": True,
        "file_id_is_selection_intent": True,
        "metadata_refetch_before_bytes": True,
        "raw_refresh_token": False,
        "drive_write": False,
        "public_fetch_route": False,
        "production_mutation": False,
    }


__all__ = [
    "B67_CASE_PDF_SERVICE_VERSION",
    "PDF_MIME_TYPE",
    "MAX_B67_CASE_PDF_BYTES",
    "MAX_B67_PDF_QUERY_CHARS",
    "MAX_B67_PDF_CANDIDATES",
    "DriveCasePdfError",
    "DriveCasePdfService",
    "drive_case_pdf_service_snapshot",
]
