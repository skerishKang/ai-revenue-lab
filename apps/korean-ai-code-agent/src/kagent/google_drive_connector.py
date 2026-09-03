from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import quote

from .contracts import ContractError
from .connector_platform import (
    ConnectorCallResult,
    ConnectorConnection,
    ConnectorTool,
    bounded_connector_result,
)

REQUEST_TIMEOUT_SECONDS = 30
PAGE_SIZE = 25
FILE_FIELDS = "id,name,mimeType,modifiedTime,webViewLink,size,owners(emailAddress)"
EXPORTABLE_MIME: dict[str, str] = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}

_TEXTUAL_APPLICATION_MIME = frozenset(
    {
        "application/json",
        "application/xml",
        "application/xhtml+xml",
        "application/javascript",
        "application/x-ndjson",
        "application/yaml",
        "application/x-yaml",
        "application/sql",
        "application/toml",
    }
)

DRIVE_TOOLS: tuple[ConnectorTool, ...] = (
    ConnectorTool(
        name="search_files",
        description=(
            "Search the files in the connected Google Drive by name and full text. "
            "Returns matching files with names, types, modified times and links."
        ),
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "What to search for."}},
            "required": ["query"],
        },
    ),
    ConnectorTool(
        name="list_recent_files",
        description="List files changed most recently, newest first.",
        input_schema={"type": "object", "properties": {}},
    ),
    ConnectorTool(
        name="get_file_metadata",
        description="Get name, type, size, owner, modified time and link for one file.",
        input_schema={
            "type": "object",
            "properties": {"fileId": {"type": "string", "description": "Google Drive file id."}},
            "required": ["fileId"],
        },
    ),
    ConnectorTool(
        name="read_file_content",
        description=(
            "Read text from one file. Google Docs, Sheets and Slides are exported "
            "to bounded text-compatible formats."
        ),
        input_schema={
            "type": "object",
            "properties": {"fileId": {"type": "string", "description": "Google Drive file id."}},
            "required": ["fileId"],
        },
    ),
)


class AuthorizedGoogleDriveHttpPort(Protocol):
    """Trusted HTTP/OAuth boundary.

    B54 passes only connector binding + actor refs. Implementations resolve and
    refresh credentials outside task/model state and return bounded provider data.
    """

    def get_json(
        self,
        *,
        binding_ref: str,
        actor_ref: str,
        base_url: str,
        path: str,
        query: dict[str, str],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        ...

    def get_text(
        self,
        *,
        binding_ref: str,
        actor_ref: str,
        base_url: str,
        path: str,
        query: dict[str, str],
        timeout_seconds: int,
    ) -> str:
        ...


def drive_query(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError("Drive search query is required")
    normalized = value.strip()
    if len(normalized) > 1_000:
        raise ContractError("Drive search query exceeds 1000 characters")
    escaped = normalized.replace("\\", "\\\\").replace("'", "\\'")
    return f"name contains '{escaped}' or fullText contains '{escaped}'"


def is_textual_mime(mime_type: str | None) -> bool:
    if not mime_type:
        return False
    normalized = mime_type.split(";", 1)[0].strip().lower()
    return normalized.startswith("text/") or normalized in _TEXTUAL_APPLICATION_MIME


def _string_arg(args: dict[str, Any], key: str) -> str | None:
    value = args.get(key)
    if isinstance(value, str) and value.strip():
        normalized = value.strip()
        if len(normalized) > 1_024:
            raise ContractError(f"{key} exceeds 1024 characters")
        return normalized
    return None


def _file_line(file: dict[str, Any]) -> str:
    name = str(file.get("name") or "(untitled)")
    link = file.get("webViewLink")
    if isinstance(link, str) and link.startswith("https://"):
        escaped_name = name.replace("[", r"\[").replace("]", r"\]")
        first = f"[{escaped_name}]({link})"
    else:
        first = name
    parts = [first]
    mime = file.get("mimeType")
    modified = file.get("modifiedTime")
    file_id = file.get("id")
    if isinstance(mime, str) and mime:
        parts.append(mime)
    if isinstance(modified, str) and modified:
        parts.append(f"modified {modified}")
    if isinstance(file_id, str) and file_id:
        parts.append(f"id: {file_id}")
    return "- " + " · ".join(parts)


class GoogleDriveReadTransport:
    """OpenBot-derived Google Drive read transport adapted to B54 boundaries."""

    list_needs_credential = False
    base_url = "https://www.googleapis.com/drive/v3"

    def __init__(self, http: AuthorizedGoogleDriveHttpPort) -> None:
        self._http = http

    def list_tools(self, connection: ConnectorConnection) -> tuple[ConnectorTool, ...]:
        if not isinstance(connection, ConnectorConnection):
            raise ContractError("connection must be ConnectorConnection")
        if connection.connector_id != "google-drive":
            raise ContractError("Google Drive transport requires google-drive connection")
        return DRIVE_TOOLS

    def _json(
        self,
        connection: ConnectorConnection,
        path: str,
        query: dict[str, str],
    ) -> dict[str, Any]:
        return self._http.get_json(
            binding_ref=connection.binding_ref,
            actor_ref=connection.actor_ref,
            base_url=self.base_url,
            path=path,
            query=dict(query),
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
        )

    def _text(
        self,
        connection: ConnectorConnection,
        path: str,
        query: dict[str, str],
    ) -> str:
        return self._http.get_text(
            binding_ref=connection.binding_ref,
            actor_ref=connection.actor_ref,
            base_url=self.base_url,
            path=path,
            query=dict(query),
            timeout_seconds=REQUEST_TIMEOUT_SECONDS,
        )

    def call_tool(
        self,
        connection: ConnectorConnection,
        tool_name: str,
        args: dict[str, Any],
    ) -> ConnectorCallResult:
        if not isinstance(connection, ConnectorConnection):
            raise ContractError("connection must be ConnectorConnection")
        if connection.connector_id != "google-drive":
            raise ContractError("Google Drive transport requires google-drive connection")
        if not isinstance(args, dict):
            raise ContractError("Google Drive args must be an object")

        if tool_name in {"search_files", "list_recent_files"}:
            query = _string_arg(args, "query")
            if tool_name == "search_files" and not query:
                return bounded_connector_result("A search needs something to search for.", is_error=True)
            params = {
                "pageSize": str(PAGE_SIZE),
                "fields": f"files({FILE_FIELDS})",
            }
            if query:
                params["q"] = drive_query(query)
            else:
                params["orderBy"] = "modifiedTime desc"
            body = self._json(connection, "/files", params)
            files = body.get("files", [])
            if not isinstance(files, list):
                return bounded_connector_result("Google Drive returned an invalid file list.", is_error=True)
            return bounded_connector_result(
                "\n".join(_file_line(item) for item in files if isinstance(item, dict))
            )

        if tool_name == "get_file_metadata":
            file_id = _string_arg(args, "fileId")
            if not file_id:
                return bounded_connector_result("A file id is needed to look a file up.", is_error=True)
            file = self._json(
                connection,
                f"/files/{quote(file_id, safe='')}",
                {"fields": FILE_FIELDS},
            )
            owner = None
            owners = file.get("owners")
            if isinstance(owners, list) and owners and isinstance(owners[0], dict):
                candidate = owners[0].get("emailAddress")
                if isinstance(candidate, str):
                    owner = candidate
            lines = [_file_line(file)]
            size = file.get("size")
            if isinstance(size, str) and size:
                lines.append(f"size: {size} bytes")
            if owner:
                lines.append(f"owner: {owner}")
            return bounded_connector_result("\n".join(lines))

        if tool_name == "read_file_content":
            file_id = _string_arg(args, "fileId")
            if not file_id:
                return bounded_connector_result("A file id is needed to read a file.", is_error=True)
            encoded = quote(file_id, safe="")
            metadata = self._json(
                connection,
                f"/files/{encoded}",
                {"fields": "id,name,mimeType"},
            )
            name = metadata.get("name") if isinstance(metadata.get("name"), str) else file_id
            mime = metadata.get("mimeType") if isinstance(metadata.get("mimeType"), str) else None
            export_as = EXPORTABLE_MIME.get(mime or "")
            if not export_as and not is_textual_mime(mime):
                return bounded_connector_result(
                    f"{name} is a {mime or 'binary'} file, which this connector cannot read as text. "
                    "Its metadata and link can still be used.",
                    is_error=True,
                )
            if export_as:
                text = self._text(
                    connection,
                    f"/files/{encoded}/export",
                    {"mimeType": export_as},
                )
            else:
                text = self._text(
                    connection,
                    f"/files/{encoded}",
                    {"alt": "media"},
                )
            return bounded_connector_result(f"{name}\n\n{text}")

        return bounded_connector_result(
            f"{tool_name} is not a tool this connector implements. The reviewed tool list is out of date.",
            is_error=True,
        )


REAL_GOOGLE_DRIVE_CONNECTOR_CONFIGURED = False
GOOGLE_DRIVE_WRITE_SUPPORTED = False
GOOGLE_DRIVE_RAW_CREDENTIAL_IN_B54 = False
