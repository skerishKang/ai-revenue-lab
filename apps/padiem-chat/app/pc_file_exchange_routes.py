"""#5895: the shared "bring a file from my PC" / "save it back" server surface.

Three menus — the stable-writing and social screens, the B66 quote sheet, and the
PDF/Markdown conversion menu — need the same two things: pick a file that lives on the
owner's own PC, and put a result back on that PC. This module is the server half of
that shared part; the menus are connected to it in the following PR.

Every route is an owner-session call, and the account's own PC links decide what it
may touch. No model turn and no tool choice is involved, and no browser field names an
account, a device or a folder: the canonical session, the account scope, the link and
the approved roots are all re-read server-side through the authorities the composer's
PC lane already uses.

    POST /api/pc/browse  {link_id?, path?}   one folder's entries
    POST /api/pc/find    {link_id?, name}    every file of that name, across every
                                             folder this account granted
    POST /api/pc/fetch   {link_id?, path}    one file's content
    POST /api/pc/save    {link_id?, path, content|file_id}   #5573's write, with the
                                             backup it takes before anything changes
    GET  /api/pc/result  ?dispatch_id=       the durable state of one of the four
    GET  /api/pc/file    ?dispatch_id=      the bytes, for what a text answer cannot
                                             carry — the "file id" a menu consumes

The four POSTs stage a dispatch on the lane the PC tools already use and answer at
once with the dispatch and run identity. The screen then watches `GET /api/pc/result`
under the #5895 "PC에서 작업 중 — 경과 시간" display, so a PC that takes minutes is
the same operation rather than a failure, and a request that drops is re-read from the
server's own record. Nothing here adds a second byte or item ceiling and no
confirmation step: the only instant that can end a wait is the dispatch's own existing
expiry, and every wait is a read-only GET.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .auth_routes import auth_ready, current_user_id
from .chat_pc_drive import (ChatPCDriveError, _check_mesh_grant, _new_lane_run_id,
                            _resolve_chat_owner)
from .claw_local_task_result_projection import result_message_id
from .history import HistoryError, validate_conversation_id
from .oracle_mesh_read_return_routes import (
    PC_FILES_LIST_DEFAULT_LIMIT,
    PC_WRITE_ACCOUNT_PREFIX,
    _engine_pc_files_target,
    _error,
    _pc_backup_dir,
    _pc_files_command,
    _pc_files_pick_root,
    _pc_files_powershell_literal,
    _pc_write_command,
    _read_body,
    _response,
    _text_value,
    dispatch_oracle_mesh_command_intent,
    dispatch_oracle_mesh_file_read_intent,
)
from .pc_device_pairing_store import is_pc_device_id

#: The read-only status cadence the PC lane already uses: the Engine step driver and
#: the browser recovery both space their polls by 2 seconds. It spaces GETs and ends
#: nothing — the dispatch's own expiry is what can turn a wait into a named answer.
RESULT_POLL_SECONDS = 2.0
PC_BROWSE_PATH = "/api/pc/browse"
PC_FIND_PATH = "/api/pc/find"
PC_FETCH_PATH = "/api/pc/fetch"
PC_SAVE_PATH = "/api/pc/save"
PC_RESULT_PATH = "/api/pc/result"
PC_FILE_PATH = "/api/pc/file"
LINK_ID = re.compile(r"\Apclink_[0-9a-f]{32}\Z")
DISPATCH_ID = re.compile(r"\Adsp_[0-9a-f]{32}\Z")
#: PowerShell's `ConvertTo-Json -Compress` answers one object for one entry, an array
#: for several, and nothing at all for an empty folder. All three are the same answer.
_SEARCH_MARK = " -Recurse "
_MAX_LABEL_CHARS = 200
_MAX_FIND_NAME_CHARS = 255
_TEXT_SUFFIXES = (
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml",
    ".xml", ".ini", ".log", ".html", ".srt",
)
_MEDIA_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".zip": "application/zip",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


async def _owner(request: Request) -> tuple[Any, str, str] | JSONResponse:
    """The signed-in owner's canonical session, id and workspace — or why not.

    The composer's PC lane resolves this exact triple; using another owner path here
    is how a picker and a chat turn could end up speaking about different accounts.
    """

    if not auth_ready(request):
        return _error(401, "canonical_session_required")
    uid = current_user_id(request)
    if not isinstance(uid, str) or not uid:
        return _error(401, "canonical_session_required")
    try:
        session, _subject_id, workspace_id = await _resolve_chat_owner(request, uid)
    except ChatPCDriveError as exc:
        return _error(exc.status_code or 503, exc.code)
    if session is None or not workspace_id:
        return _error(503, "chat_pc_identity_unavailable")
    return session, uid, workspace_id


async def _live_links(request: Request, uid: str) -> list[dict[str, Any]] | JSONResponse:
    """The PCs this account linked itself, with the folders each one granted."""

    store = getattr(request.app.state, "pc_device_pairing_store", None)
    if not callable(getattr(store, "links_for_owner", None)):
        return _error(503, "pc_pairing_not_ready")
    try:
        links = await store.links_for_owner(user_id=uid)
    except Exception:
        return _error(503, "pc_pairing_unavailable")
    if not isinstance(links, list):
        return _error(503, "pc_pairing_unavailable")
    return [link for link in links if isinstance(link, dict)]


def _link_choices(links: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Plain names for the owner's own PCs — never a node id or a real path."""

    return [{
        "link_id": str(link.get("link_id")),
        "label": (str(link.get("label") or "").strip() or "내 PC")[:_MAX_LABEL_CHARS],
    } for link in links if link.get("link_id")]


def _choose_link(
    links: list[dict[str, Any]], link_id: str | None,
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    """The one PC this call belongs to, or the answer that asks the owner to say.

    No link id with one PC means that PC. With several it is a choice, and picking
    between two of the owner's own machines is not authority: the plain list comes
    back and the screen asks. A link id this account does not hold is a 404, so a
    foreign PC is never even confirmed to exist.
    """

    live = [link for link in links if link.get("state") == "active" and link.get("link_id")]
    if link_id is not None:
        named = [link for link in live if link.get("link_id") == link_id]
        if len(named) != 1:
            return None, _error(404, "pc_link_not_found")
        link = named[0]
    else:
        if not live:
            return None, _error(404, "pc_not_linked")
        if len(live) > 1:
            return None, _response(
                {"ok": False, "error": {"code": "pc_link_selection_required"},
                 "links": _link_choices(live)},
                status=409,
            )
        link = live[0]
    roots = [
        root for root in (link.get("roots") or [])
        if isinstance(root, dict) and root.get("state") == "active" and root.get("path")
    ]
    if not roots:
        return None, _error(403, "pc_folder_not_approved")
    return {**link, "roots": roots}, None


async def _dispatch_target(
    request: Request, *, session: Any, uid: str, link: dict[str, Any],
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    """The lane's own target for this account's link, proved to be the same PC.

    The lane resolver is asked with the link's device as the narrowing hint and the
    answer must still name that link and that device. A resolution that lands
    anywhere else is refused: a command meant for one machine is never delivered to
    another.
    """

    device = link.get("mesh_node_id")
    if not is_pc_device_id(device) or not await _check_mesh_grant(request, session, device_id=device):
        return None, _error(403, "oracle_mesh_device_unverified")
    resolved, refusal = await _engine_pc_files_target(
        request, session=session, selected_device_id=device, user_id=uid,
    )
    if refusal is not None:
        return None, refusal
    target = resolved.get("target") if isinstance(resolved, dict) else None
    if (
        not isinstance(resolved, dict) or resolved.get("authorized") is not True
        or not isinstance(target, dict)
        or not is_pc_device_id(target.get("node_ref"))
        or target.get("device_id") not in (None, device)
        or target.get("link_id") not in (None, link.get("link_id"))
    ):
        return None, _error(403, "oracle_mesh_device_unverified")
    return target, None


async def _stage_run(
    request: Request, *, uid: str, workspace_id: str, note: str,
) -> tuple[str, str] | JSONResponse:
    """One real Chat run for one picker operation, so the record is durable.

    A picker operation is a PC turn like any other: it owns a run row and a
    conversation, which is what lets the #5895 progress display and the server's own
    read-back work unchanged when a minute passes or the tab moves on.
    """

    store = getattr(request.app.state, "history_store", None)
    recorder = getattr(store, "record_chat_pc_drive_run", None)
    if not callable(recorder):
        return _error(503, "oracle_mesh_unconfigured")
    run_id = _new_lane_run_id()
    try:
        conversation_id = await recorder(
            user_id=uid, run_id=run_id, workspace_id=workspace_id,
            user_text=note, conversation_id=None,
            action="pc_files_query", title_prefix="내 PC 파일: ",
        )
    except Exception:
        return _error(503, "chat_pc_store_unavailable")
    if not validate_conversation_id(conversation_id):
        return _error(503, "chat_pc_store_unavailable")
    return run_id, str(conversation_id)


async def _staged(answer: JSONResponse, *, run: tuple[str, str], extra: dict[str, Any] | None = None) -> JSONResponse:
    """Pass the lane's own refusal through, or answer with the staged dispatch."""

    try:
        body = json.loads(answer.body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, TypeError):
        return answer
    dispatch = body.get("dispatch") if isinstance(body, dict) else None
    if (
        not isinstance(dispatch, dict)
        or not isinstance(dispatch.get("dispatch_id"), str)
        or DISPATCH_ID.fullmatch(dispatch["dispatch_id"]) is None
    ):
        return answer
    payload: dict[str, Any] = {
        "ok": True,
        "state": "working",
        "dispatch_id": dispatch["dispatch_id"],
        "run_id": run[0],
        "conversation_id": run[1],
        "expires_at": dispatch.get("expires_at"),
        "poll_seconds": RESULT_POLL_SECONDS,
    }
    payload.update(extra or {})
    return _response(payload)


def _call_ref(run_id: str, *parts: str) -> str:
    """A stable per-call correlation, in the shape the dispatch row already accepts."""

    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:24]
    return (run_id + ":pc_file_exchange:" + digest)[:128]


def _rows(text: str) -> list[dict[str, Any]]:
    try:
        decoded = json.loads(text)
    except (ValueError, TypeError):
        return []
    if isinstance(decoded, dict):
        return [decoded]
    if isinstance(decoded, list):
        return [row for row in decoded if isinstance(row, dict)]
    return []


def _items(text: str, *, with_folder: bool) -> list[dict[str, Any]]:
    """The PC's own rows, one entry per row the command actually reported.

    A search lists the same name in several folders, so the folder travels with the
    row it belongs to rather than being looked up by name afterwards.
    """

    items: list[dict[str, Any]] = []
    for row in _rows(text):
        name = row.get("Name")
        if not isinstance(name, str) or not name.strip():
            continue
        if with_folder:
            full = row.get("FullName")
            if not isinstance(full, str) or not full:
                continue
        size = row.get("Length")
        modified = row.get("LastWriteTimeUtc")
        item: dict[str, Any] = {
            "name": name,
            "kind": "folder" if row.get("PSIsContainer") is True else "file",
            "size_bytes": size if isinstance(size, int) and not isinstance(size, bool) else None,
            "modified_at": modified if isinstance(modified, str) else None,
        }
        if with_folder:
            item["path"] = full
            item["folder"] = full.replace("\\", "/").rstrip("/").rpartition("/")[0]
        items.append(item)
    return items


def _listing_items(text: str) -> list[dict[str, Any]]:
    return _items(text, with_folder=False)


def _found_items(text: str) -> list[dict[str, Any]]:
    """The same rows plus the folder each name was found in.

    A search reports full paths because one name can live in several granted folders;
    the screen shows the folder as plain text and the follow-up fetch is addressed by
    that same path, so nothing has to be guessed afterwards.
    """

    return _items(text, with_folder=True)


def _write_account(text: str) -> dict[str, Any] | None:
    """The one account line #5573's write step prints, or None when it is not there.

    The PC base64-encodes that line so no console code page can change what it says,
    which is also what makes it safe to read here: the answer stays the PC's own words
    about what it changed and where the original now sits.
    """

    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if not stripped.startswith(PC_WRITE_ACCOUNT_PREFIX):
            continue
        try:
            decoded = json.loads(base64.b64decode(
                stripped[len(PC_WRITE_ACCOUNT_PREFIX):], validate=True,
            ).decode("utf-8"))
        except (ValueError, TypeError, UnicodeDecodeError):
            return None
        return decoded if isinstance(decoded, dict) else None
    return None


def _resolve_path(roots: list[dict[str, Any]], value: Any) -> tuple[str, str] | None:
    """``(approved folder, path inside it)`` for what the screen sent back.

    A search answers with the PC's own full path, because one name can live in more
    than one granted folder. Fetching the file the owner just chose must not depend on
    how many folders the account granted, so the full path is matched back to the
    grant it sits inside and the lane's own root rule then judges the part below it.
    Anything that is not inside a grant stays exactly as unreadable as it was before.
    """

    if isinstance(value, str) and value.strip():
        text = value.strip().replace("\\", "/")
        for root in roots:
            base = str(root["path"]).replace("\\", "/").rstrip("/")
            if not base:
                continue
            if text.upper() == base.upper():
                return _pc_files_pick_root(roots, f"{root['label']}/")
            if text.upper().startswith(base.upper() + "/"):
                return _pc_files_pick_root(
                    roots, f"{root['label']}/{text[len(base) + 1:]}",
                )
    return _pc_files_pick_root(roots, value)


def _folder_choices(roots: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The granted folders by their own plain labels, for the screen to offer.

    With more than one folder on one PC, "." names none of them, so the owner says
    which. The label is the address the next call sends back, never a real path.
    """

    return [
        {"label": str(root["label"])[:_MAX_LABEL_CHARS], "path": f"{root['label']}/"}
        for root in roots
    ]


def _search_command(roots: list[dict[str, Any]], name: str) -> str:
    """Every file of one name inside the folders this account granted.

    The cmdlet-only shape the existing listing command uses — no native program, so
    the reply keeps reporting no exit code — and deliberately no `-First`: an owner
    asking where a file is must not get an answer that silently stops at a number,
    so the screen splits the list instead.
    """

    paths = ", ".join(_pc_files_powershell_literal(str(root["path"])) for root in roots)
    # A name typed with `*`, `?` or `[` is that literal name: `-like` wildcards are
    # escaped so the owner's own characters cannot widen the search.
    literal = "".join(("`" + ch) if ch in "*?[`" else ch for ch in name)
    return (
        "Get-ChildItem -LiteralPath " + paths
        + " -Recurse -Force -ErrorAction SilentlyContinue"
        + " | Where-Object { $_.Name -like '*" + literal + "*' }"
        + " | Select-Object FullName, Name, Length, LastWriteTimeUtc, PSIsContainer"
        + " | ConvertTo-Json -Compress"
    )


async def _dispatch_row(request: Request, uid: str, dispatch_id: str) -> dict[str, Any] | JSONResponse:
    store = getattr(request.app.state, "history_store", None)
    reader = getattr(store, "get_oracle_mesh_dispatch_for_owner", None)
    if not callable(reader):
        return _error(503, "oracle_mesh_unconfigured")
    try:
        dispatch = await reader(user_id=uid, dispatch_id=dispatch_id)
    except Exception:
        return _error(503, "oracle_mesh_dispatch_unavailable")
    return dispatch if isinstance(dispatch, dict) else _error(404, "pc_dispatch_not_found")


def _expired(dispatch: dict[str, Any]) -> bool:
    expires = dispatch.get("expires_at")
    return (
        isinstance(expires, str) and bool(expires)
        and expires <= datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


async def _stored_output(
    request: Request, uid: str, dispatch: dict[str, Any],
) -> tuple[bytes | None, JSONResponse | None]:
    """The verified bytes of one finished dispatch, re-derived from the row alone."""

    store = getattr(request.app.state, "history_store", None)
    run_reader = getattr(store, "get_claw_run", None)
    read_original = getattr(store, "read_oracle_mesh_original", None)
    if not callable(run_reader) or not callable(read_original):
        return None, _error(503, "oracle_mesh_unconfigured")
    try:
        run = await run_reader(uid, dispatch.get("run_id"))
    except Exception:
        return None, _error(503, "oracle_mesh_run_unavailable")
    conversation_id = validate_conversation_id(
        run.get("conversation_id") if isinstance(run, dict) else None
    )
    if not conversation_id:
        return None, _error(404, "pc_dispatch_not_found")
    try:
        message_id = result_message_id(
            conversation_id=conversation_id,
            command_id=dispatch.get("command_id"),
            revision_ref=dispatch.get("revision_ref"),
        )
        stored = await read_original(
            user_id=uid, dispatch_id=dispatch.get("dispatch_id"),
            conversation_id=conversation_id, message_id=message_id,
        )
    except HistoryError:
        return None, _error(503, "oracle_mesh_original_unavailable")
    except Exception:
        return None, _error(503, "oracle_mesh_original_unavailable")
    if stored is None:
        return None, _error(404, "pc_result_missing")
    content, digest = stored
    if (
        not isinstance(content, bytes)
        or hashlib.sha256(content).hexdigest() != digest
        or digest != dispatch.get("result_sha256")
    ):
        return None, _error(503, "oracle_mesh_original_unavailable")
    return content, None


def _query_dispatch_id(request: Request) -> str | JSONResponse:
    dispatch_id = request.query_params.get("dispatch_id") or ""
    return dispatch_id if DISPATCH_ID.fullmatch(dispatch_id) else _error(404, "pc_dispatch_not_found")


async def _readable_owner(request: Request) -> tuple[str, Any] | JSONResponse:
    """Owner id and history store for the two read-only GETs."""

    if not auth_ready(request):
        return _error(401, "canonical_session_required")
    uid = current_user_id(request)
    if not isinstance(uid, str) or not uid:
        return _error(401, "canonical_session_required")
    store = getattr(request.app.state, "history_store", None)
    if store is None:
        return _error(503, "oracle_mesh_unconfigured")
    return uid, store


async def pc_file_exchange_browse(request: Request) -> JSONResponse:
    """One folder's entries on the owner's own PC."""

    body = await _read_body(request, frozenset(), optional=frozenset({"link_id", "path"}))
    if body is None:
        return _error(400, "pc_exchange_invalid_body")
    owner = await _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    session, uid, workspace_id = owner
    links = await _live_links(request, uid)
    if isinstance(links, JSONResponse):
        return links
    link_id, refusal = _link_id(body.get("link_id"))
    if refusal is not None:
        return refusal
    link, refusal = _choose_link(links, link_id)
    if refusal is not None:
        return refusal
    target, refusal = await _dispatch_target(request, session=session, uid=uid, link=link)
    if refusal is not None:
        return refusal
    path = body.get("path") or "."
    picked = _resolve_path(link["roots"], path)
    if picked is None:
        if len(link["roots"]) > 1 and path == ".":
            # Several folders on one PC: "." is not a choice, so the screen is given
            # the plain labels and the owner makes the choice itself.
            return _response(
                {"ok": False, "error": {"code": "pc_folder_selection_required"},
                 "folders": _folder_choices(link["roots"])},
                status=409,
            )
        return _error(422, "oracle_mesh_file_path_invalid")
    root, relative = picked
    run = await _stage_run(request, uid=uid, workspace_id=workspace_id, note="내 PC 폴더를 둘러봤습니다.")
    if isinstance(run, JSONResponse):
        return run
    answer = await dispatch_oracle_mesh_command_intent(
        request,
        command=_pc_files_command(
            op="list", root=root, relative=relative, limit=PC_FILES_LIST_DEFAULT_LIMIT,
        ),
        wire={"run_id": run[0], "device_id": link.get("mesh_node_id"), "confirmed": True},
        trusted_owner=(session, uid, workspace_id),
        tool_call_ref=_call_ref(run[0], "browse", root, relative),
        files_target=target,
    )
    return await _staged(answer, run=run, extra={"path": path})


async def pc_file_exchange_find(request: Request) -> JSONResponse:
    """Every file of one name, across every folder this account granted."""

    body = await _read_body(request, frozenset({"name"}), optional=frozenset({"link_id"}))
    if body is None:
        return _error(400, "pc_exchange_invalid_body")
    name = _text_value(body.get("name"), limit=_MAX_FIND_NAME_CHARS)
    if name is None or not name.strip():
        return _error(422, "pc_exchange_name_required")
    name = name.strip()
    owner = await _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    session, uid, workspace_id = owner
    links = await _live_links(request, uid)
    if isinstance(links, JSONResponse):
        return links
    link_id, refusal = _link_id(body.get("link_id"))
    if refusal is not None:
        return refusal
    link, refusal = _choose_link(links, link_id)
    if refusal is not None:
        return refusal
    target, refusal = await _dispatch_target(request, session=session, uid=uid, link=link)
    if refusal is not None:
        return refusal
    run = await _stage_run(request, uid=uid, workspace_id=workspace_id,
                           note="내 PC에서 파일을 찾았습니다: " + name)
    if isinstance(run, JSONResponse):
        return run
    answer = await dispatch_oracle_mesh_command_intent(
        request,
        command=_search_command(link["roots"], name),
        wire={"run_id": run[0], "device_id": link.get("mesh_node_id"), "confirmed": True},
        trusted_owner=(session, uid, workspace_id),
        tool_call_ref=_call_ref(run[0], "find", name),
        files_target=target,
    )
    return await _staged(answer, run=run, extra={"name": name})


async def pc_file_exchange_fetch(request: Request) -> JSONResponse:
    """One file's content, on the read lane the PC tools already use."""

    body = await _read_body(request, frozenset({"path"}), optional=frozenset({"link_id"}))
    if body is None:
        return _error(400, "pc_exchange_invalid_body")
    owner = await _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    session, uid, workspace_id = owner
    links = await _live_links(request, uid)
    if isinstance(links, JSONResponse):
        return links
    link_id, refusal = _link_id(body.get("link_id"))
    if refusal is not None:
        return refusal
    link, refusal = _choose_link(links, link_id)
    if refusal is not None:
        return refusal
    target, refusal = await _dispatch_target(request, session=session, uid=uid, link=link)
    if refusal is not None:
        return refusal
    picked = _resolve_path(link["roots"], body.get("path"))
    if picked is None:
        return _error(422, "oracle_mesh_file_path_invalid")
    root, relative = picked
    if not relative:
        # A folder is not a file: the screen asks for a file rather than reading a
        # directory into an answer that cannot show one.
        return _error(422, "oracle_mesh_file_path_invalid")
    name = relative.rsplit("/", 1)[-1]
    run = await _stage_run(request, uid=uid, workspace_id=workspace_id,
                           note="내 PC에서 파일을 가져왔습니다: " + name)
    if isinstance(run, JSONResponse):
        return run
    answer = await dispatch_oracle_mesh_file_read_intent(
        request,
        wire={"run_id": run[0], "device_id": link.get("mesh_node_id"), "confirmed": True},
        trusted_owner=(session, uid, workspace_id),
        tool_call_ref=_call_ref(run[0], "fetch", root, relative),
        target=target,
        root=root,
        relative=relative,
    )
    return await _staged(answer, run=run, extra={"name": name})


async def pc_file_exchange_save(request: Request) -> JSONResponse:
    """Put one answer back on the owner's PC through #5573's write, backup first.

    The bytes come from the menu's own text or from a file this same part fetched a
    moment ago, and the target is a file the owner named inside their own grant. The
    command is #5573's own builder, so the original is copied to the hidden per-drive
    backup folder before anything changes and a backup that fails stops the step
    there. This route adds no second write path and asks the owner no confirmation.
    """

    body = await _read_body(
        request, frozenset({"path"}),
        optional=frozenset({"link_id", "content", "file_id"}),
    )
    if body is None:
        return _error(400, "pc_exchange_invalid_body")
    content = body.get("content")
    file_id = body.get("file_id")
    if (content is None) == (file_id is None):
        # Exactly one source: a menu either holds the text it wrote or the file it
        # brought over, and never both under two names.
        return _error(422, "pc_exchange_content_required")
    owner = await _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    session, uid, workspace_id = owner
    links = await _live_links(request, uid)
    if isinstance(links, JSONResponse):
        return links
    link_id, refusal = _link_id(body.get("link_id"))
    if refusal is not None:
        return refusal
    link, refusal = _choose_link(links, link_id)
    if refusal is not None:
        return refusal
    target, refusal = await _dispatch_target(request, session=session, uid=uid, link=link)
    if refusal is not None:
        return refusal
    picked = _resolve_path(link["roots"], body.get("path"))
    if picked is None:
        return _error(422, "oracle_mesh_file_path_invalid")
    root, relative = picked
    if not relative:
        # Saving onto the granted folder itself would replace a folder with a file.
        return _error(422, "oracle_mesh_file_path_invalid")
    if content is not None:
        if not isinstance(content, str):
            return _error(422, "oracle_mesh_file_content_invalid")
        payload = content.encode("utf-8")
    else:
        if not isinstance(file_id, str) or DISPATCH_ID.fullmatch(file_id) is None:
            return _error(404, "pc_dispatch_not_found")
        source = await _dispatch_row(request, uid, file_id)
        if isinstance(source, JSONResponse):
            return source
        if source.get("state") != "done":
            return _error(409, "oracle_mesh_result_not_ready")
        stored, refusal = await _stored_output(request, uid, source)
        if refusal is not None:
            return refusal
        payload = stored
    name = relative.rsplit("/", 1)[-1]
    run = await _stage_run(request, uid=uid, workspace_id=workspace_id,
                           note="내 PC에 파일을 저장했습니다: " + name)
    if isinstance(run, JSONResponse):
        return run
    answer = await dispatch_oracle_mesh_command_intent(
        request,
        command=_pc_write_command(
            op="write",
            target=root.rstrip("/") + "/" + relative,
            backup_dir=_pc_backup_dir(root, datetime.now(timezone.utc).strftime("%Y-%m-%d")),
            relative=relative,
            content_b64=base64.b64encode(payload).decode("ascii"),
        ),
        wire={"run_id": run[0], "device_id": link.get("mesh_node_id"), "confirmed": True},
        trusted_owner=(session, uid, workspace_id),
        tool_call_ref=_call_ref(run[0], "save", root, relative),
        files_target=target,
    )
    return await _staged(answer, run=run, extra={"name": name})


async def pc_file_exchange_result(request: Request) -> JSONResponse:
    """The durable state of one picker operation, addressed only by its dispatch id.

    While the PC is still working the answer is `working` — a state, never a failure —
    and the screen keeps its elapsed clock on it. Only after the row says finished is
    the stored output read, and it is read through the pin the executor's own result
    carried.
    """

    dispatch_id = _query_dispatch_id(request)
    if isinstance(dispatch_id, JSONResponse):
        return dispatch_id
    owner = await _readable_owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    uid, _store = owner
    dispatch = await _dispatch_row(request, uid, dispatch_id)
    if isinstance(dispatch, JSONResponse):
        return dispatch
    state = dispatch.get("state")
    if state not in ("done", "failed"):
        if _expired(dispatch):
            return _error(410, "pc_dispatch_expired")
        return _response({"ok": True, "state": "working", "dispatch_id": dispatch_id,
                          "poll_seconds": RESULT_POLL_SECONDS})
    if state == "failed":
        return _error(502, "pc_dispatch_failed")
    content, refusal = await _stored_output(request, uid, dispatch)
    if refusal is not None:
        return refusal
    text = content.decode("utf-8", errors="replace")
    if dispatch.get("kind") == "command":
        account = _write_account(text)
        if account is not None:
            # The PC's own line is the answer: what it wrote, where, and where the
            # original now sits. A write the PC refused stays refused, not rewritten.
            return _response({"ok": account.get("ok") is True, "state": "ready",
                              "dispatch_id": dispatch_id, "saved": account})
        if _SEARCH_MARK in str(dispatch.get("command_text") or ""):
            return _response({"ok": True, "state": "ready", "dispatch_id": dispatch_id,
                              "found": _found_items(text)})
        return _response({"ok": True, "state": "ready", "dispatch_id": dispatch_id,
                          "items": _listing_items(text)})
    readable = _is_text(content)
    return _response({
        "ok": True, "state": "ready", "dispatch_id": dispatch_id,
        "content_kind": "text" if readable else "file",
        "content": text if readable else None,
        # The address a menu hands back to /api/pc/file; the id is the dispatch, and
        # reading it re-proves the owner, the run and the digest.
        "file_id": dispatch_id,
        "name": str(dispatch.get("file_path") or "").replace("\\", "/").rsplit("/", 1)[-1] or "파일",
        "size_bytes": len(content),
        "sha256": dispatch.get("result_sha256"),
    })


async def pc_file_exchange_file(request: Request) -> Response:
    """The bytes of one fetched PC file, for the formats a text answer cannot carry."""

    dispatch_id = _query_dispatch_id(request)
    if isinstance(dispatch_id, JSONResponse):
        return dispatch_id
    owner = await _readable_owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    uid, _store = owner
    dispatch = await _dispatch_row(request, uid, dispatch_id)
    if isinstance(dispatch, JSONResponse):
        return dispatch
    if dispatch.get("state") != "done":
        return _error(409, "oracle_mesh_result_not_ready")
    content, refusal = await _stored_output(request, uid, dispatch)
    if refusal is not None:
        return refusal
    name = str(dispatch.get("file_path") or "").replace("\\", "/").rsplit("/", 1)[-1] or "파일"
    return Response(
        content,
        media_type=_media_type(name, content),
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(name, safe=""),
            "X-Padiem-PC-Content-SHA256": str(dispatch.get("result_sha256")),
        },
    )


def _link_id(value: Any) -> tuple[str | None, JSONResponse | None]:
    """The PC the caller named, or the refusal that says it named none of that shape.

    A present-but-malformed id is not quietly dropped: dropping it would turn a
    mistyped or tampered choice into "whichever PC this account happens to have",
    which is exactly the guessing this call must never do.
    """

    if value is None or value == "":
        return None, None
    if not isinstance(value, str) or LINK_ID.fullmatch(value) is None:
        return None, _error(400, "pc_exchange_link_id_invalid")
    return value, None


def _is_text(content: bytes) -> bool:
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _media_type(name: str, content: bytes) -> str:
    lowered = name.lower()
    if _is_text(content):
        return "text/plain; charset=utf-8"
    for suffix, media in _MEDIA_BY_SUFFIX.items():
        if lowered.endswith(suffix):
            return media
    return "application/octet-stream"
