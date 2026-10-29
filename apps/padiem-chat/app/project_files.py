from __future__ import annotations

import base64
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from .documents import validate_document_fields

PDF_MEDIA_TYPE = "application/pdf"
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
#: #5728 — SNS photo composition stores its images through the same
#: project-file channel. The set matches the chat attachment allow-list
#: (attachments.py); no new size or count limits are introduced, images reuse
#: the existing binary body bound (MAX_BINARY_DOCUMENT_BYTES).
IMAGE_PROJECT_FILE_MEDIA = frozenset({"image/png", "image/jpeg", "image/webp"})

#: #5731 — the writing tools that store text in a project file. The save stamps
#: this onto the row (migration 078), so a list can ask for its own kind instead
#: of guessing from a name prefix. `""` is every row written before the column
#: existed: the screens group those under 기타 and never hide them.
UTIL_DOC_KINDS = frozenset({"speech", "sns", "meeting", "book"})
BINARY_PROJECT_FILE_MEDIA = frozenset({PDF_MEDIA_TYPE, DOCX_MEDIA_TYPE} | IMAGE_PROJECT_FILE_MEDIA)

#: The stored ceiling of `project_files.content_text`, declared by migration 077
#: as `CHECK(length(CAST(content_text AS BLOB)) <= 2097152)`. 2 MiB is D1's
#: documented per-row limit — the platform's physical bound, not a product cap.
#: Until 077 the schema carried `CHECK(content_chars <= 40000)` instead, which
#: was arbitrary: 40,000 Korean characters is only ~117 KB of a ~2 MB row, so a
#: body D1 would hold was refused for its character count. Measuring bytes is
#: what D1 measures. Checking it before the INSERT turns a D1 constraint
#: violation into the route's own 422 with Korean guidance (#5882 PR-E).
PROJECT_FILE_MAX_TEXT_BYTES = 2_097_152

#: #5728 — the same honesty the document path enforces through its parser:
#: the declared image media type must match the bytes actually uploaded, so a
#: text payload renamed to .png can never masquerade as a stored original.
_IMAGE_MAGIC: dict[str, tuple[bytes, ...]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
}


def image_media_type_matches(media_type: str, head: bytes) -> bool:
    if media_type == "image/webp":
        # RIFF container: the WEBP form tag sits at offset 8.
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    signature = _IMAGE_MAGIC.get(media_type)
    if signature is None:
        return False
    return any(head.startswith(prefix) for prefix in signature)


def _extracted_media_type(original_media_type: str) -> str:
    # Canonicalize extracted media types: DOCX → extracted/docx, PDF → extracted/pdf
    ext = original_media_type.split("/")[-1]
    if ext.startswith("vnd.openxmlformats-officedocument.wordprocessingml.document"):
        return "extracted/docx"
    return "extracted/" + ext

#: #5882 PR-E — there is no per-project file-count or total-character cap. The
#: former `MAX_PROJECT_FILES = 12` / `MAX_PROJECT_TOTAL_CHARS = 160_000` pair was
#: never enforced on any path; it is gone rather than kept as a dead promise of
#: a limit the product does not make. Persisted rows are bounded by D1 itself
#: (PROJECT_FILE_MAX_TEXT_BYTES) and an ephemeral attachment by the browser.

#: #4489 — the Library browses every file an owner stored, one bounded keyset page at a
#: time. These are HTTP page bounds, not a record cap: no page may grow a response.
DEFAULT_OWNER_FILES_PAGE = 50
MAX_OWNER_FILES_PAGE = 100
_OWNER_FILE_CURSOR_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


class ProjectFileError(RuntimeError):
    pass


class ProjectFileFormatError(ProjectFileError):
    pass


class ProjectFileLimitError(ProjectFileError):
    pass


@dataclass(frozen=True, slots=True)
class ProjectFileRecord:
    id: str
    project_id: str
    name: str
    media_type: str
    content_text: str = field(repr=False)
    content_chars: int = 0
    created_at: str = ""
    updated_at: str = ""
    # #6046 — 기본값이 곧 기존 문서의 호환 규칙이다(컬럼 추가 시 DEFAULT 'kr').
    country: str = "kr"
    # #5731 — what the save itself recorded about this row (migration 078).
    # An empty kind is a pre-0731 document, not a damaged one.
    doc_kind: str = ""
    # When set, this row holds the body a later save displaced from that file.
    doc_version_of: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "media_type": self.media_type,
            "content_chars": self.content_chars,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "country": self.country,
            "doc_kind": self.doc_kind,
            "doc_version_of": self.doc_version_of,
        }


class ProjectFileStore(Protocol):
    async def list_files(self, user_id: str, project_id: str, country: str | None = None) -> list[ProjectFileRecord]: ...
    async def get_file(self, user_id: str, project_id: str, file_id: str) -> ProjectFileRecord | None: ...
    async def create_file(self, user_id: str, project_id: str, name: str, media_type: str, text: str, country: str = "kr") -> ProjectFileRecord: ...
    async def delete_file(self, user_id: str, project_id: str, file_id: str) -> bool: ...


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _file_id() -> str:
    return "file_" + uuid.uuid4().hex


def _version_name(name: str, number: int) -> str:
    """`행사.txt` -> `행사 (이전 1).txt` for the nth displaced body.

    The displaced body keeps a name a person can recognise in the same list it
    came from, and the number comes from the versions already linked to the same
    document, so a second overwrite never reuses a name.
    """
    stem, dot, suffix = name.rpartition(".")
    if not dot or not stem:
        return name + f" (이전 {number})"
    return stem + f" (이전 {number})" + "." + suffix


def validate_file_id(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("file_id 형식이 올바르지 않습니다.")
    text = value.strip()
    if len(text) != 37 or not text.startswith("file_"):
        raise ValueError("file_id 형식이 올바르지 않습니다.")
    if any(ch not in "0123456789abcdef" for ch in text[5:]):
        raise ValueError("file_id 형식이 올바르지 않습니다.")
    return text


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    to_py = getattr(row, "to_py", None)
    if callable(to_py):
        converted = to_py()
        if isinstance(converted, dict):
            return dict(converted)
    try:
        return dict(row)
    except (TypeError, ValueError):
        return None


def _rows_from_result(result: Any) -> list[dict[str, Any]]:
    if result is None:
        return []
    rows = getattr(result, "results", None)
    if rows is None and isinstance(result, dict):
        rows = result.get("results")
    if rows is None:
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        converted = _row_to_dict(row)
        if converted is not None:
            out.append(converted)
    return out


def _from_row(row: dict[str, Any]) -> ProjectFileRecord:
    text = str(row.get("content_text", ""))
    return ProjectFileRecord(
        id=str(row.get("id", "")),
        project_id=str(row.get("project_id", "")),
        name=str(row.get("name", "")),
        media_type=str(row.get("media_type", "")),
        content_text=text,
        content_chars=int(row.get("content_chars") or len(text)),
        created_at=str(row.get("created_at", "")),
        updated_at=str(row.get("updated_at", "")),
        country=str(row.get("country") or "kr"),   # 컬럼이 없는 예전 행도 kr
        doc_kind=str(row.get("doc_kind") or ""),   # 078 이전 행은 기타('')
        doc_version_of=(str(row["doc_version_of"]) if row.get("doc_version_of") else None),
    )


@dataclass(frozen=True, slots=True)
class OwnerFileProjection:
    """One stored file plus its project label. It never carries file content."""

    id: str
    project_id: str
    project_name: str
    name: str
    media_type: str
    content_chars: int
    created_at: str
    updated_at: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "name": self.name,
            "media_type": self.media_type,
            "content_chars": self.content_chars,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class OwnerFileCursorError(ValueError):
    """Raised for any cursor a caller invented, truncated or replayed across scopes."""


def encode_owner_file_cursor(record: OwnerFileProjection) -> str:
    """Keyset position ``(updated_at, id)`` as an opaque token.

    Deliberately not a caller-composable scope: it carries no user id, no project id
    list and no limit, so it can never widen whose files a page returns.
    """
    raw = f"{record.updated_at}|{record.id}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_owner_file_cursor(value: object) -> tuple[str, str]:
    if not isinstance(value, str) or not value.strip():
        raise OwnerFileCursorError("cursor 형식이 올바르지 않습니다.")
    text = value.strip()
    if len(text) > 256:
        raise OwnerFileCursorError("cursor 형식이 올바르지 않습니다.")
    try:
        raw = base64.urlsafe_b64decode((text + "=" * (-len(text) % 4)).encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise OwnerFileCursorError("cursor 형식이 올바르지 않습니다.") from exc
    updated_at, separator, file_id = raw.partition("|")
    if not separator or _OWNER_FILE_CURSOR_TIME_RE.fullmatch(updated_at) is None:
        raise OwnerFileCursorError("cursor 형식이 올바르지 않습니다.")
    try:
        validated = validate_file_id(file_id)
    except ValueError as exc:
        raise OwnerFileCursorError("cursor 형식이 올바르지 않습니다.") from exc
    if validated is None:
        raise OwnerFileCursorError("cursor 형식이 올바르지 않습니다.")
    return updated_at, validated


def _owner_projection_from_row(row: dict[str, Any]) -> OwnerFileProjection:
    return OwnerFileProjection(
        id=str(row.get("id", "")),
        project_id=str(row.get("project_id", "")),
        project_name=str(row.get("project_name") or ""),
        name=str(row.get("name", "")),
        media_type=str(row.get("media_type", "")),
        content_chars=int(row.get("content_chars") or 0),
        created_at=str(row.get("created_at", "")),
        updated_at=str(row.get("updated_at", "")),
    )


class D1ProjectFileStore:
    """D1-backed bounded text-file store. Dynamic values always use binds."""

    def __init__(self, db: Any):
        if db is None:
            raise ValueError("D1 binding is required")
        self.db = db

    async def _first(self, sql: str, *values: Any) -> dict[str, Any] | None:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return _row_to_dict(await statement.first())

    async def _run(self, sql: str, *values: Any) -> Any:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return await statement.run()

    async def _all(self, sql: str, *values: Any) -> list[dict[str, Any]]:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return _rows_from_result(await statement.run())

    async def list_files(self, user_id: str, project_id: str, country: str | None = None) -> list[ProjectFileRecord]:
        # D1 queries must remain page-sized; project ownership is bound on every page.
        # No artificial total file count: retrieve all pages with stable keyset ordering.
        records: list[ProjectFileRecord] = []
        after: tuple[str, str] | None = None
        while True:
            if after is None:
                rows = await self._all(
                    "SELECT id, project_id, name, media_type, content_text, content_chars, created_at, updated_at, country, "
                    "doc_kind, doc_version_of "
                    "FROM project_files WHERE user_id=? AND project_id=? "
                    + ("AND country=? " if country else "")
                    + "ORDER BY created_at ASC, id ASC LIMIT ?",
                    *((user_id, project_id, country, MAX_OWNER_FILES_PAGE) if country else (user_id, project_id, MAX_OWNER_FILES_PAGE)),
                )
            else:
                rows = await self._all(
                    "SELECT id, project_id, name, media_type, content_text, content_chars, created_at, updated_at, country, "
                    "doc_kind, doc_version_of "
                    "FROM project_files WHERE user_id=? AND project_id=? "
                    + ("AND country=? " if country else "")
                    + "AND (created_at > ? OR (created_at = ? AND id > ?)) "
                    + "ORDER BY created_at ASC, id ASC LIMIT ?",
                    *((user_id, project_id, country, after[0], after[0], after[1], MAX_OWNER_FILES_PAGE)
                      if country else (user_id, project_id, after[0], after[0], after[1], MAX_OWNER_FILES_PAGE)),
                )
            records.extend(_from_row(row) for row in rows)
            if len(rows) < MAX_OWNER_FILES_PAGE:
                return records
            after = (str(rows[-1]["created_at"]), str(rows[-1]["id"]))

    async def list_owner_files(
        self, user_id: str, *, after: tuple[str, str] | None = None, limit: int
    ) -> list[OwnerFileProjection]:
        """One keyset page over every file this owner stored, newest update first.

        The position is ``(updated_at, id)``, so a page can neither repeat nor skip a
        row when writes land between requests. Files are selected by ``f.user_id`` only;
        the project label joins on the same owner, which keeps another account's project
        name out of the result and still lists a file whose project row is missing.
        Content is never selected.
        """
        head = (
            "SELECT f.id AS id, f.project_id AS project_id, f.name AS name, "
            "f.media_type AS media_type, f.content_chars AS content_chars, "
            "f.created_at AS created_at, f.updated_at AS updated_at, "
            "COALESCE(p.name, '') AS project_name "
            "FROM project_files AS f "
            "LEFT JOIN projects AS p ON p.id = f.project_id AND p.user_id = f.user_id "
        )
        tail = " ORDER BY f.updated_at DESC, f.id DESC LIMIT ?"
        if after is None:
            rows = await self._all(head + "WHERE f.user_id = ?" + tail, user_id, limit)
            return [_owner_projection_from_row(row) for row in rows]
        after_updated_at, after_id = after
        rows = await self._all(
            head
            + "WHERE f.user_id = ? AND (f.updated_at < ? OR (f.updated_at = ? AND f.id < ?))"
            + tail,
            user_id,
            after_updated_at,
            after_updated_at,
            after_id,
            limit,
        )
        return [_owner_projection_from_row(row) for row in rows]

    async def get_file(self, user_id: str, project_id: str, file_id: str) -> ProjectFileRecord | None:
        row = await self._first(
            "SELECT id, project_id, name, media_type, content_text, content_chars, created_at, updated_at, country, "
            "doc_kind, doc_version_of "
            "FROM project_files WHERE id=? AND user_id=? AND project_id=?",
            file_id, user_id, project_id,
        )
        return _from_row(row) if row else None

    async def find_current_by_name(
        self, user_id: str, project_id: str, name: str, doc_kind: str,
    ) -> ProjectFileRecord | None:
        """The current document this save would replace, if the name is taken.

        Only a row of the same kind and not itself a version can be overwritten:
        a speech must never overwrite the meeting record that happens to share
        its name, and a version row is history, not a target.
        """
        row = await self._first(
            "SELECT id, project_id, name, media_type, content_text, content_chars, created_at, updated_at, country, "
            "doc_kind, doc_version_of "
            "FROM project_files WHERE user_id=? AND project_id=? AND name=? AND doc_kind=? "
            "AND (doc_version_of IS NULL OR doc_version_of='') "
            "ORDER BY created_at ASC LIMIT 1",
            user_id, project_id, name, doc_kind,
        )
        return _from_row(row) if row else None

    async def replace_text(
        self, user_id: str, project_id: str, file_id: str, text: str, *,
        doc_kind: str = "",
    ) -> tuple[ProjectFileRecord, ProjectFileRecord | None] | None:
        """Overwrite one document and keep the body it displaced.

        The previous text becomes its own project file (`<name> (이전 N)`) that
        links back through `doc_version_of` — the same channel, owner and project
        scope, so nothing new is introduced and nothing is destroyed. Returns
        (updated, previous-version) or None when the owner/file does not match.
        """
        existing = await self.get_file(user_id, project_id, file_id)
        if existing is None:
            return None
        if len(text.encode("utf-8")) > PROJECT_FILE_MAX_TEXT_BYTES:
            raise ProjectFileLimitError(
                f"본문이 너무 길어요 — 저장 한도(D1 한 행 약 {PROJECT_FILE_MAX_TEXT_BYTES // 1024 // 1024}MB)를 "
                "넘었습니다. 내용을 나눠서 올리거나, 원본 파일을 첨부로 올려 주세요."
            )
        validate_document_fields(existing.name, existing.media_type, text)
        now = _now_iso()
        await self._run(
            "UPDATE project_files SET content_text=?, content_chars=?, updated_at=? "
            "WHERE id=? AND user_id=? AND project_id=?",
            text, len(text), now, file_id, user_id, project_id,
        )
        kept = await self._first(
            "SELECT count(*) AS n FROM project_files "
            "WHERE user_id=? AND project_id=? AND doc_version_of=?",
            user_id, project_id, file_id,
        )
        number = int((kept or {}).get("n") or 0) + 1
        version = await self.create_file(
            user_id, project_id, _version_name(existing.name, number),
            existing.media_type, existing.content_text,
            doc_kind=doc_kind or existing.doc_kind, doc_version_of=file_id,
        )
        updated = await self.get_file(user_id, project_id, file_id)
        return (updated or existing, version)

    async def create_file(
        self,
        user_id: str,
        project_id: str,
        name: str,
        media_type: str,
        text: str,
        *,
        source_media_type: str | None = None,
        country: str = "kr",
        doc_kind: str = "",
        doc_version_of: str | None = None,
    ) -> ProjectFileRecord:
        if len(text.encode("utf-8")) > PROJECT_FILE_MAX_TEXT_BYTES:
            raise ProjectFileLimitError(
                f"본문이 너무 길어요 — 저장 한도(D1 한 행 약 {PROJECT_FILE_MAX_TEXT_BYTES // 1024 // 1024}MB)를 "
                "넘었습니다. 내용을 나눠서 올리거나, 원본 파일을 첨부로 올려 주세요."
            )
        if source_media_type is not None and source_media_type != media_type:
            raise ProjectFileFormatError("source_media_type must match media_type")
        if media_type in IMAGE_PROJECT_FILE_MEDIA:
            # #5728: photos carry no extractable text — the record keeps the
            # declared image media type with an empty body. Routing them
            # through validate_document_fields would 422 every upload on the
            # real store (the in-memory fakes bypass this branch, which is
            # how the merged slice shipped without seeing it).
            document = type("Doc", (), {"name": name, "media_type": media_type, "text": text})()
        elif media_type.startswith("extracted/"):

            document = type("Doc", (), {"name": name, "media_type": media_type, "text": text})()
        else:
            document = validate_document_fields(name, media_type, text)
        fid = _file_id()
        now = _now_iso()
        # #5226: the project-ownership condition is part of the INSERT itself.
        # A separate read-then-write pair leaves a window in which a project
        # that is not this owner's (or no longer exists) could still receive the
        # row. Selecting the project row inside the same statement keeps the
        # save-time condition and the write in one atomic step, so a concurrent
        # add can never bypass it.
        # #6046 — 기본값(kr)은 컬럼을 아예 쓰지 않는다: DB DEFAULT 가 'kr' 이므로
        # 기존 스키마·기존 테스트 대역에서도 INSERT 문이 오늘과 문자 그대로 같고,
        # 마이그레이션 전 스키마에서도 한국어 저장이 계속 동작한다.
        # The default save writes exactly the columns it always wrote; a kind or
        # a version link only adds its own column. The schema itself comes from
        # the migration ledger (078), never from this statement.
        optional: list[tuple[str, Any]] = []
        if country != "kr":
            optional.append(("country", country))
        if doc_kind:
            optional.append(("doc_kind", doc_kind))
        if doc_version_of:
            optional.append(("doc_version_of", doc_version_of))
        sql = (
            "INSERT INTO project_files (id, project_id, user_id, name, media_type, "
            "content_text, content_chars, created_at, updated_at"
            + "".join(", " + column for column, _ in optional)
            + ") SELECT ?, p.id, ?, ?, ?, ?, ?, ?, ?"
            + ", ?" * len(optional)
            + " FROM projects p WHERE p.id = ? AND p.user_id = ? RETURNING id"
        )
        written = await self._run(
            sql,
            fid, user_id, document.name, document.media_type, document.text, len(document.text), now, now,
            *(value for _, value in optional), project_id, user_id,
        )
        if not _rows_from_result(written):
            raise ProjectFileError("project is not owned by current user")
        return ProjectFileRecord(
            id=fid, project_id=project_id, name=document.name, media_type=document.media_type,
            content_text=document.text, content_chars=len(document.text), created_at=now, updated_at=now,
            country=country, doc_kind=doc_kind, doc_version_of=doc_version_of,
        )

    async def delete_file(self, user_id: str, project_id: str, file_id: str) -> bool:
        existing = await self.get_file(user_id, project_id, file_id)
        if existing is None:
            return False
        await self._run(
            "DELETE FROM project_files WHERE id=? AND user_id=? AND project_id=?",
            file_id, user_id, project_id,
        )
        return True
