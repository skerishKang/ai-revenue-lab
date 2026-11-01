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
    POST /api/pc/find    {link_id?, name, run_id?, folder?, remaining?}
                                            every file of that name, across every
                                            folder this account granted, one folder
                                            of the sweep per call
    POST /api/pc/fetch   {link_id?, path}    one file's content
    POST /api/pc/save    {link_id?, path, content|file_id|project_file_id,
                          project_id?}  #5573's write, with the backup it takes
                                             before anything changes; a
                                             project_file_id reads one of this
                                             owner's own project files (the
                                             council app's browser-built
                                             documents) — 2026-11-02
    POST /api/pc/cancel  {run_id}            stop this account's own operation, whether
                                             the PC has started it or not
    GET  /api/pc/result  ?dispatch_id=       the durable state of one of the four
    GET  /api/pc/file    ?dispatch_id=      the bytes, for what a text answer cannot
                                             carry — the "file id" a menu consumes

The POSTs stage a dispatch on the lane the PC tools already use and answer at
once with the dispatch and run identity. The screen then watches `GET /api/pc/result`
under the #5895 "PC에서 작업 중 — 경과 시간" display, so a PC that takes minutes is
the same operation rather than a failure, and a request that drops is re-read from the
server's own record. Nothing here adds a second byte or item ceiling and no
confirmation step: the only instants that can end a wait are the dispatch's own
existing expiry and the owner pressing 그만, and every wait is a read-only GET.

A search is the one operation that is spread over several dispatches, because one
whole-drive command answers only at its end and holds the PC until then. That is a
division of the work, not a limit on it: every folder the account granted is still
swept, and the owner can stop at any point.
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
from .claw_local_task_result_projection import result_message_id
from .history import HistoryError, validate_conversation_id
from .pc_device_pairing_store import is_pc_device_id

#: The lane modules this file speaks through, and every name it uses from them.
#:
#: None of them is imported at module load. ``worker.py`` imports ``app.main``, which
#: builds the app at module import, so every module the route table pulls in is compiled
#: before the first request — and this Worker's compat date (2026-08-25) still carries
#: the platform's cold-init NoGilError race, which is how a heavier cold init turns into
#: a 500 on every login and session request. Every other consumer of these modules
#: imports them inside the function that needs them for the same reason: ``app_factory``
#: mounts the mesh lane inside ``create_app``, ``worker.py`` composes it inside
#: ``fetch``, and ``chat_pc_drive``'s own helpers import the mesh lane per call.
_LAZY_LANE_MODULE = {
    **{name: ".chat_pc_drive" for name in (
        "_check_mesh_grant", "_new_lane_run_id", "_resolve_chat_owner",
    )},
    **{name: ".oracle_mesh_read_return_routes" for name in (
        "_engine_pc_files_target", "_error", "_pc_backup_dir", "_pc_files_command",
        "_pc_files_pick_root", "_pc_files_powershell_literal", "_pc_write_command",
        "_read_body", "_response", "_text_value",
        "dispatch_oracle_mesh_command_intent", "dispatch_oracle_mesh_file_read_intent",
    )},
}


def _lane_call(name: str):
    """A module-level stand-in that imports the real function on first call.

    The name stays in this module's globals, so a test can still replace it the way it
    replaces any other collaborator, while the import itself happens in a request.
    ``sys.modules`` caches the module, so only the first request per isolate pays.
    """

    def call(*args, **kwargs):
        from importlib import import_module

        target = getattr(import_module(_LAZY_LANE_MODULE[name], __package__), name)
        return target(*args, **kwargs)

    call.__name__ = name
    call.__qualname__ = name
    return call


_check_mesh_grant = _lane_call("_check_mesh_grant")
_new_lane_run_id = _lane_call("_new_lane_run_id")
_resolve_chat_owner = _lane_call("_resolve_chat_owner")
_engine_pc_files_target = _lane_call("_engine_pc_files_target")
_error = _lane_call("_error")
_pc_backup_dir = _lane_call("_pc_backup_dir")
_pc_files_command = _lane_call("_pc_files_command")
_pc_files_pick_root = _lane_call("_pc_files_pick_root")
_pc_files_powershell_literal = _lane_call("_pc_files_powershell_literal")
_pc_write_command = _lane_call("_pc_write_command")
_read_body = _lane_call("_read_body")
_response = _lane_call("_response")
_text_value = _lane_call("_text_value")
dispatch_oracle_mesh_command_intent = _lane_call("dispatch_oracle_mesh_command_intent")
dispatch_oracle_mesh_file_read_intent = _lane_call("dispatch_oracle_mesh_file_read_intent")

#: The read-only status cadence the PC lane already uses: the Engine step driver and
#: the browser recovery both space their polls by 2 seconds. It spaces GETs and ends
#: nothing — the dispatch's own expiry is what can turn a wait into a named answer.
RESULT_POLL_SECONDS = 2.0
PC_BROWSE_PATH = "/api/pc/browse"
PC_FIND_PATH = "/api/pc/find"
PC_FETCH_PATH = "/api/pc/fetch"
PC_SAVE_PATH = "/api/pc/save"
PC_MOVE_PATH = "/api/pc/move"
PC_DELETE_PATH = "/api/pc/delete"
PC_CANCEL_PATH = "/api/pc/cancel"
PC_RESULT_PATH = "/api/pc/result"
PC_FILE_PATH = "/api/pc/file"
PC_REFERENCE_PATH = "/api/pc/reference"
LANE_FILE_ID = re.compile(r"\Afile_[0-9a-f]{32}\Z")
LINK_ID = re.compile(r"\Apclink_[0-9a-f]{32}\Z")
DISPATCH_ID = re.compile(r"\Adsp_[0-9a-f]{32}\Z")
#: The lane's own run identity, as `_new_lane_run_id` mints it. A screen may name a
#: run to continue its own sweep; it may not name one it does not own, and that is
#: decided by the owner-scoped read, not by this shape.
RUN_ID = re.compile(r"\Achat_pcq_[0-9a-f]{32}\Z")
#: PowerShell's `ConvertTo-Json -Compress` answers one object for one entry, an array
#: for several, and nothing at all for an empty folder. All three are the same answer.
_SEARCH_MARK = " -Recurse "
#: The two columns a search adds to a plain folder listing: the whole path, so one
#: name found in two folders can be told apart, and the folder rows themselves, which
#: are the next places to look.
_FOUND_MARK = "Select-Object FullName, Name"
#: The dispatch's own word for "the owner stopped this", written into the column that
#: already records how a command ended.
CANCELLED_TERMINATION = "cancelled"
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
    from .chat_pc_drive import ChatPCDriveError

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


async def _continued_run(
    request: Request, *, uid: str, workspace_id: str, run_id: Any,
) -> tuple[str, str] | JSONResponse:
    """The sweep the screen already started, proved again to be this account's.

    A search is one operation spread over many folders, so every step after the
    first lands on the run — and in the conversation — the first call made. Only
    the run id comes from the browser: the row, its owner and its workspace are
    read back here, so one account cannot queue work inside another account's
    picker operation, and a made-up id is simply not found.
    """

    if not isinstance(run_id, str) or RUN_ID.fullmatch(run_id) is None:
        return _error(400, "pc_exchange_run_id_invalid")
    store = getattr(request.app.state, "history_store", None)
    reader = getattr(store, "get_claw_run", None)
    if not callable(reader):
        return _error(503, "oracle_mesh_unconfigured")
    try:
        row = await reader(uid, run_id)
    except Exception:
        return _error(503, "chat_pc_store_unavailable")
    conversation_id = validate_conversation_id(
        row.get("conversation_id") if isinstance(row, dict) else None
    )
    if (
        not isinstance(row, dict) or row.get("run_id") != run_id
        or row.get("workspace_id") != workspace_id or not conversation_id
    ):
        return _error(404, "pc_run_not_found")
    return run_id, conversation_id


async def _picker_run(
    request: Request, *, uid: str, workspace_id: str, body: dict[str, Any], note: str,
) -> tuple[str, str] | JSONResponse:
    """A new picker run, or the one this screen is already sweeping inside."""

    run_id = body.get("run_id")
    if run_id is None:
        return await _stage_run(request, uid=uid, workspace_id=workspace_id, note=note)
    return await _continued_run(request, uid=uid, workspace_id=workspace_id, run_id=run_id)


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

    return _items_from_rows(_rows(text), with_folder=with_folder)


def _items_from_rows(rows: list[dict[str, Any]], *,
                     with_folder: bool) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
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


def _listing_page(text: str) -> tuple[list[dict[str, Any]], int | None, bool, str | None]:
    """One page of a listing: the rows, the folder's total, whether more remains, next cursor.

    The PC answers with ``{offset, total, has_more, items}``. A listing stored before
    paging existed is a bare row array whose total is unknown: it is reported as one
    final page with no total rather than claiming the folder ended there.
    """

    try:
        decoded = json.loads(text)
    except (TypeError, ValueError):
        decoded = None
    if isinstance(decoded, dict) and isinstance(decoded.get("items"), list):
        rows = [row for row in decoded["items"] if isinstance(row, dict)]
        items = _items_from_rows(rows, with_folder=False)
        total = decoded.get("total")
        offset = decoded.get("offset")
        has_more = decoded.get("has_more")
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            total = None
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            offset = 0
        if not isinstance(has_more, bool):
            has_more = bool(total is not None and offset + len(rows) < total)
        next_cursor = str(offset + len(rows)) if has_more else None
        return items, total, has_more, next_cursor
    items = _items_from_rows(_rows(text), with_folder=False)
    return items, None, False, None


def _found_items(text: str) -> list[dict[str, Any]]:
    """The same rows plus the folder each name was found in.

    A search reports full paths because one name can live in several granted folders;
    the screen shows the folder as plain text and the follow-up fetch is addressed by
    that same path, so nothing has to be guessed afterwards.
    """

    return _items(text, with_folder=True)


def _page_size() -> int:
    """How many entries one listing request asks for — read where it is used."""

    from .oracle_mesh_read_return_routes import PC_FILES_LIST_PAGE_SIZE

    return PC_FILES_LIST_PAGE_SIZE


#: A cursor is the offset the client was handed, and nothing else. Digits only, and
#: bounded so a malformed or hostile value can never turn into a huge Skip on the PC.
_LISTING_CURSOR = re.compile(r"(?:0|[1-9][0-9]{0,9})\Z")
_LISTING_CURSOR_MAX = 1_000_000_000


def _listing_filter(raw: Any) -> tuple[str | None, JSONResponse | None]:
    """A name fragment, or nothing. Control characters are refused; length is not capped.

    The term is never a pattern: the PC escapes it and matches with -like. No product
    length limit is applied here — the executor's own argv guard is the only bound —
    but an empty or control-bearing value is refused before anything is staged.
    """

    if raw is None:
        return None, None
    if not isinstance(raw, str) or not raw:
        return None, _error(400, "pc_exchange_invalid_body")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        return None, _error(400, "pc_exchange_invalid_body")
    return raw, None


def _listing_cursor(raw: Any) -> tuple[int, JSONResponse | None]:
    if raw is None:
        return 0, None
    if isinstance(raw, str) and _LISTING_CURSOR.fullmatch(raw):
        value = int(raw)
        if value <= _LISTING_CURSOR_MAX:
            return value, None
    return 0, _error(400, "pc_exchange_invalid_body")


def _write_account(text: str) -> dict[str, Any] | None:
    """The one account line #5573's write step prints, or None when it is not there.

    The PC base64-encodes that line so no console code page can change what it says,
    which is also what makes it safe to read here: the answer stays the PC's own words
    about what it changed and where the original now sits.
    """

    from .oracle_mesh_read_return_routes import PC_WRITE_ACCOUNT_PREFIX

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


def _granted_folder(roots: list[dict[str, Any]], value: Any) -> str | None:
    """The PC path for one folder of the sweep, or None when it is outside every grant.

    The screen names the folder it is standing in and the folders still waiting; each
    of those is judged by the lane's own root rule. A queue entry that points outside
    what this account granted is therefore not a wider search — it is a refusal, the
    same way a typed path would be.
    """

    picked = _resolve_path(roots, value)
    if picked is None:
        return None
    root, relative = picked
    return root.rstrip("/") + ("/" + relative if relative else "")


def _sweep_step(
    roots: list[dict[str, Any]], body: dict[str, Any],
) -> tuple[str | None, list[str], JSONResponse | None]:
    """(folder to sweep now, folders still waiting, refusal).

    A call with neither `folder` nor `remaining` is the first look: the granted
    folders themselves. After that the queue travels with the request, because the
    sweep belongs to the screen that started it — and every entry in it is checked
    against the grants, so a queue can never grow past what the owner allowed.
    """

    folder = body.get("folder")
    remaining = body.get("remaining")
    if folder is None and remaining is None:
        return None, [], None
    if folder is None:
        return None, [], _error(422, "oracle_mesh_file_path_invalid")
    if not isinstance(remaining, list):
        return None, [], _error(422, "pc_exchange_queue_required")
    swept = _granted_folder(roots, folder)
    if swept is None:
        return None, [], _error(422, "oracle_mesh_file_path_invalid")
    waiting: list[str] = []
    for entry in remaining:
        path = _granted_folder(roots, entry)
        if path is None:
            return None, [], _error(422, "oracle_mesh_file_path_invalid")
        waiting.append(path)
    return swept, waiting, None


def _ps_like(name: str) -> str:
    """A name typed with `*`, `?` or `[` is that literal name: `-like` wildcards are
    escaped so the owner's own characters cannot widen the search."""

    return "".join(("`" + ch) if ch in "*?[`" else ch for ch in name)


_FOUND_TAIL = (" | Select-Object FullName, Name, Length, LastWriteTimeUtc, PSIsContainer"
               " | ConvertTo-Json -Compress")


def _seed_search_command(roots: list[dict[str, Any]], name: str) -> str:
    """The granted folders one level deep: what matches here, and what is left to look in.

    The cmdlet-only shape the existing listing command uses — no native program, so the
    reply keeps reporting no exit code — and deliberately no `-First`: an owner asking
    where a file is must not get an answer that silently stops at a number. The folder
    rows are the plan for the rest of the sweep, which is why they come back with the
    matches rather than being filtered away.
    """

    paths = ", ".join(_pc_files_powershell_literal(str(root["path"])) for root in roots)
    return (
        "Get-ChildItem -LiteralPath " + paths
        + " -Force -ErrorAction SilentlyContinue"
        + " | Where-Object { $_.PSIsContainer -or $_.Name -like '*" + _ps_like(name) + "*' }"
        + _FOUND_TAIL
    )


def _sweep_command(folder: str, name: str) -> str:
    """One whole subtree, by name — the next call asks for the next folder.

    Splitting the search this way is what keeps a PC usable: a single whole-drive
    command answers only at its end and nothing else runs on that PC until then, while
    every folder here is still swept, so no match is left out and no count is capped.
    """

    return (
        "Get-ChildItem -LiteralPath " + _pc_files_powershell_literal(folder)
        + " -Recurse -Force -ErrorAction SilentlyContinue"
        + " | Where-Object { $_.Name -like '*" + _ps_like(name) + "*' }"
        + _FOUND_TAIL
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

    body = await _read_body(request, frozenset(),
                            optional=frozenset({"link_id", "path", "cursor", "filter"}))
    if body is None:
        return _error(400, "pc_exchange_invalid_body")
    offset, refusal = _listing_cursor(body.get("cursor"))
    if refusal is not None:
        return refusal
    term, refusal = _listing_filter(body.get("filter"))
    if refusal is not None:
        return refusal
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
            op="list", root=root, relative=relative,
            offset=offset, page_size=_page_size(), filter_term=term,
        ),
        wire={"run_id": run[0], "device_id": link.get("mesh_node_id"), "confirmed": True},
        trusted_owner=(session, uid, workspace_id),
        # A name search is its own call: the same folder asked twice for the same
        # word is the same call, a different word is not.
        tool_call_ref=_call_ref(run[0], "browse", root, relative, term or ""),
        files_target=target,
    )
    return await _staged(answer, run=run,
                         extra={"path": path, "cursor": str(offset), "filter": term})


async def pc_file_exchange_find(request: Request) -> JSONResponse:
    """Every file of one name, across every folder this account granted.

    The sweep is spread over calls instead of run as one command, because a single
    whole-drive command answers only when it ends and nothing else runs on that PC
    until then. The first call looks at the granted folders themselves and reports the
    folders left to look in; each next call takes the folder the screen is now at and
    the list of the ones still waiting. Every granted folder is still swept — no match
    is left out and no count is capped — but each answer arrives on its own, so the
    screen shows what has been found so far and a short request waits behind one
    folder rather than behind a whole drive. The screen also stops asking whenever the
    owner presses 그만, and `/api/pc/cancel` takes the folder that has not reached a
    PC yet out of the queue.
    """

    body = await _read_body(
        request, frozenset({"name"}),
        optional=frozenset({"link_id", "run_id", "folder", "remaining"}),
    )
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
    folder, waiting, refusal = _sweep_step(link["roots"], body)
    if refusal is not None:
        return refusal
    run = await _picker_run(request, uid=uid, workspace_id=workspace_id, body=body,
                            note="내 PC에서 파일을 찾습니다: " + name)
    if isinstance(run, JSONResponse):
        return run
    command = (_seed_search_command(link["roots"], name) if folder is None
               else _sweep_command(folder, name))
    answer = await dispatch_oracle_mesh_command_intent(
        request,
        command=command,
        wire={"run_id": run[0], "device_id": link.get("mesh_node_id"), "confirmed": True},
        trusted_owner=(session, uid, workspace_id),
        tool_call_ref=_call_ref(run[0], "find", name, folder or "."),
        files_target=target,
    )
    return await _staged(answer, run=run, extra={
        "name": name, "folder": folder, "remaining": waiting,
    })


async def pc_file_exchange_cancel(request: Request) -> JSONResponse:
    """Stop one of this account's own picker operations.

    Work the PC has not started is taken out of the queue, and work the executor
    already holds is stopped too: the row carries the owner's stop, the executor
    reads it through its own channel while the command runs, and ending it is what
    frees that PC - #5995 removed the client deadline, and a command the PC never
    answers would otherwise hold every later operation behind it. The stopped row
    keeps its claim, so the result the executor still owes lands as a stop rather
    than being resent. The answer is the count of rows stopped, because the owner
    pressed one button and is owed to know whether anything actually stopped. No
    confirmation step precedes it.
    """

    body = await _read_body(request, frozenset({"run_id"}))
    if body is None:
        return _error(400, "pc_exchange_invalid_body")
    owner = await _owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    _session, uid, workspace_id = owner
    run = await _continued_run(request, uid=uid, workspace_id=workspace_id,
                               run_id=body.get("run_id"))
    if isinstance(run, JSONResponse):
        return run
    store = getattr(request.app.state, "history_store", None)
    canceller = getattr(store, "cancel_oracle_mesh_dispatches_for_run", None)
    if not callable(canceller):
        return _error(503, "oracle_mesh_unconfigured")
    try:
        stopped = await canceller(user_id=uid, run_id=run[0])
    except Exception:
        return _error(503, "oracle_mesh_dispatch_unavailable")
    if not isinstance(stopped, int) or stopped < 0:
        return _error(503, "oracle_mesh_dispatch_unavailable")
    return _response({"ok": True, "state": "cancelled", "run_id": run[0],
                      "stopped": stopped, "poll_seconds": RESULT_POLL_SECONDS})


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
        optional=frozenset({"link_id", "content", "file_id", "project_id", "project_file_id"}),
    )
    if body is None:
        return _error(400, "pc_exchange_invalid_body")
    content = body.get("content")
    file_id = body.get("file_id")
    project_file_id = body.get("project_file_id")
    if len([s for s in (content, file_id, project_file_id) if s is not None]) != 1:
        # Exactly one source: a menu either holds the text it wrote, a file the
        # lane made, or one of this owner's own project files — never two at
        # once under two names.
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
    elif isinstance(file_id, str) and LANE_FILE_ID.fullmatch(file_id):
        # A file the lane already holds — the filled Excel form the quote menu just
        # made. The bytes are read with this owner's own read ticket; the Worker
        # never parses them, it only hands them to the PC write below.
        payload, refusal = await _lane_file_bytes(request, uid, file_id)
        if refusal is not None:
            return refusal
    elif project_file_id is not None:
        # 2026-11-02: one of this owner's own project files. The council app
        # builds documents in the browser (한글/HWPX·워드/DOCX), stores them as
        # project files first, and moves those exact bytes to the PC here. The
        # row is read owner+project scoped exactly like the /original route.
        payload, refusal = await _project_file_bytes(
            request, uid, body.get("project_id"), project_file_id)
        if refusal is not None:
            return refusal
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
            root=root,
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


async def pc_file_exchange_move(request: Request) -> JSONResponse:
    """Move or rename one file on the owner's PC through #5573's write.

    The destination stays inside the folder this same link granted: moving one
    file is never a way to reach a folder the link did not. The builder copies
    what the move would replace before anything changes, and a backup that
    fails stops the step there.
    """

    body = await _read_body(
        request, frozenset({"path", "destination"}), optional=frozenset({"link_id"}),
    )
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
        return _error(422, "oracle_mesh_file_path_invalid")
    picked_destination = _resolve_path(link["roots"], body.get("destination"))
    if picked_destination is None:
        return _error(422, "oracle_mesh_file_path_invalid")
    destination_root, destination_relative = picked_destination
    if destination_root != root or not destination_relative:
        return _error(422, "oracle_mesh_file_path_invalid")
    name = destination_relative.rsplit("/", 1)[-1]
    run = await _stage_run(request, uid=uid, workspace_id=workspace_id,
                           note="내 PC에서 파일을 옮겼습니다: " + name)
    if isinstance(run, JSONResponse):
        return run
    answer = await dispatch_oracle_mesh_command_intent(
        request,
        command=_pc_write_command(
            op="move",
            root=root,
            target=root.rstrip("/") + "/" + relative,
            backup_dir=_pc_backup_dir(root, datetime.now(timezone.utc).strftime("%Y-%m-%d")),
            relative=relative,
            destination=destination_root.rstrip("/") + "/" + destination_relative,
        ),
        wire={"run_id": run[0], "device_id": link.get("mesh_node_id"), "confirmed": True},
        trusted_owner=(session, uid, workspace_id),
        tool_call_ref=_call_ref(run[0], "move", root, relative, destination_relative),
        files_target=target,
    )
    return await _staged(answer, run=run, extra={"name": name})


async def pc_file_exchange_delete(request: Request) -> JSONResponse:
    """Delete one file on the owner's PC, after #5573's builder copies it first."""

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
        # Deleting the granted folder itself is not one file, and a backup of it
        # would be a second copy of everything inside.
        return _error(422, "oracle_mesh_file_path_invalid")
    name = relative.rsplit("/", 1)[-1]
    run = await _stage_run(request, uid=uid, workspace_id=workspace_id,
                           note="내 PC에서 파일을 지웠습니다: " + name)
    if isinstance(run, JSONResponse):
        return run
    answer = await dispatch_oracle_mesh_command_intent(
        request,
        command=_pc_write_command(
            op="delete",
            root=root,
            target=root.rstrip("/") + "/" + relative,
            backup_dir=_pc_backup_dir(root, datetime.now(timezone.utc).strftime("%Y-%m-%d")),
            relative=relative,
        ),
        wire={"run_id": run[0], "device_id": link.get("mesh_node_id"), "confirmed": True},
        trusted_owner=(session, uid, workspace_id),
        tool_call_ref=_call_ref(run[0], "delete", root, relative),
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
        if dispatch.get("termination") == CANCELLED_TERMINATION:
            # The owner stopped this. It is a state of the operation, not a PC that
            # failed, and the screen says so in those words.
            return _response({"ok": True, "state": "cancelled", "dispatch_id": dispatch_id})
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
        command_text = str(dispatch.get("command_text") or "")
        if _FOUND_MARK in command_text:
            rows = _found_items(text)
            if _SEARCH_MARK in command_text:
                return _response({"ok": True, "state": "ready", "dispatch_id": dispatch_id,
                                  "found": rows})
            # The first look: what matched in the granted folders themselves, and the
            # folders the sweep has still to go through.
            return _response({
                "ok": True, "state": "ready", "dispatch_id": dispatch_id,
                "found": [row for row in rows if row["kind"] == "file"],
                "folders": [row["path"] for row in rows if row["kind"] == "folder"],
            })
        items, total, has_more, next_cursor = _listing_page(text)
        return _response({"ok": True, "state": "ready", "dispatch_id": dispatch_id,
                          "items": items, "total": total, "has_more": has_more,
                          "next_cursor": next_cursor})
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


async def _lane_file_bytes(
    request: Request, uid: str, file_id: str,
) -> tuple[bytes | None, JSONResponse | None]:
    """One file the COM2 lane already holds, read with the owner's own read ticket.

    The lane owns the bytes (it made the filled workbook), so the Worker asks for
    them with the same signed read ticket the document lane already uses. Nothing
    here parses a workbook: the bytes go straight into the PC write.
    """

    client = getattr(request.app.state, "file_lane_client", None)
    if client is None or getattr(client, "ready", False) is not True:
        return None, _error(503, "file_lane_unavailable")
    try:
        headers, _expires = client.read_ticket(uid)
    except Exception:
        return None, _error(503, "file_lane_unavailable")
    try:
        import httpx

        async with httpx.AsyncClient(
            transport=getattr(client, "_transport", None), timeout=None,
            follow_redirects=False, trust_env=False,
        ) as http:
            async with http.stream(
                "GET", client.origin + "/files/" + file_id + "/raw", headers=headers,
            ) as response:
                if response.status_code != 200:
                    return None, _error(502, "file_lane_read_failed")
                data = b"".join([chunk async for chunk in response.aiter_bytes()])
    except Exception:
        return None, _error(503, "file_lane_unavailable")
    if not data:
        return None, _error(502, "file_lane_read_failed")
    return data, None


async def _project_file_bytes(
    request: Request, uid: str, project_id: object, file_id: object,
) -> tuple[bytes | None, JSONResponse | None]:
    """One of this owner's own project files, read like the /original route.

    The council app builds documents in the browser (한글/HWPX·워드/DOCX) and
    stores them as project files first (the binary upload path already admits
    those media types); the PC write then moves those exact bytes. The row must
    belong to this owner AND this project, and the bytes come from the same
    originals object /original serves — never a guessed R2 key.
    """

    # Imported here, not at module load: the cold-init rule every lane consumer
    # in this file follows (worker.py compiles the route table at import).
    from .project_file_routes import _project_original_object_key, _r2_call
    from .project_files import IMAGE_PROJECT_FILE_MEDIA, validate_file_id

    store = getattr(request.app.state, "project_file_store", None)
    if store is None or not hasattr(store, "get_file"):
        return None, _error(503, "pc_project_file_unavailable")
    if not isinstance(project_id, str) or not project_id:
        return None, _error(404, "pc_project_file_not_found")
    try:
        fid = validate_file_id(file_id)
    except ValueError:
        return None, _error(404, "pc_project_file_not_found")
    if fid is None:
        return None, _error(404, "pc_project_file_not_found")
    try:
        record = await store.get_file(uid, project_id, fid)
    except Exception:
        return None, _error(503, "pc_project_file_unavailable")
    if record is None or (
        record.media_type not in {"extracted/pdf", "extracted/docx", "extracted/hwpx"}
        and record.media_type not in IMAGE_PROJECT_FILE_MEDIA
    ):
        return None, _error(404, "pc_project_file_not_found")
    workspace_store = getattr(request.app.state, "workspace_document_store", None)
    bucket = getattr(workspace_store, "r2_bucket", None)
    if bucket is None:
        return None, _error(503, "pc_project_file_unavailable")
    obj = await _r2_call(bucket, "get", _project_original_object_key(uid, project_id, fid))
    if obj is None:
        return None, _error(404, "pc_project_file_not_found")
    body = getattr(obj, "body", None)
    try:
        if body is not None and hasattr(body, "__aiter__"):
            data = b"".join([chunk async for chunk in body])
        elif hasattr(body, "read"):
            data = body.read()
        elif hasattr(obj, "read"):
            data = obj.read()
        else:
            data = bytes(obj)
    except Exception:
        return None, _error(502, "pc_project_file_read_failed")
    if not data:
        return None, _error(502, "pc_project_file_read_failed")
    return data, None


def _reference_text(name: str, content: bytes) -> str | None:
    """The words inside one owner-verified PC file, or None when they cannot be read.

    The extractors are the same pure-Python ones the document lane already uses (no
    external parser, no second authority), and they are imported here — inside the
    request — so no document parser joins the Worker's cold init (#6034). A file this
    build cannot read is refused by name; nothing is guessed at or passed through raw.
    """

    if _is_text(content):
        return content.decode("utf-8")
    suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    try:
        if suffix == ".docx":
            from padiem_ai_core.document_normalization import extract_docx_text

            return extract_docx_text(content)
        if suffix in (".hwpx", ".hwp"):
            # .hwp reaches here only when its bytes are a real HWPX (ZIP)
            # package (#6126): the OLE2 legacy binary is refused upstream by
            # its own signature, so both names take the one HWPX reader.
            from padiem_ai_core.document_normalization import extract_hwpx_text

            return extract_hwpx_text(content)
        if suffix == ".pdf":
            # The core keeps one PDF text path and the document lane is its only
            # public entry today; the reference read reuses that one parser rather
            # than growing a second copy of it.
            from padiem_ai_core.document_normalization import _extract_pdf_text

            return _extract_pdf_text(content)
    except Exception:
        return None
    return None


# #6126: the file's own first bytes decide what a picked .hwp document is —
# the OLE2 compound signature means the older binary Hangul format (never
# converted, one guidance code), and the ZIP local-header signatures mean a
# mislabeled file that is really an HWPX package and keeps working as HWPX.
_HWP_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_ZIP_LOCAL_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


async def pc_file_exchange_reference(request: Request) -> JSONResponse:
    """One PC file as the owner can read it — the words a menu uses as reference.

    Only the fetch's dispatch id comes from the browser; the bytes are re-read through
    the same owner-verified, digest-pinned path `/api/pc/file` uses. There is no count
    or length ceiling here: the owner's own files are handed back whole, and a format
    this build cannot read is refused plainly instead of being guessed at.
    """

    body = await _read_body(request, frozenset({"file_id"}))
    if body is None:
        return _error(400, "pc_exchange_invalid_body")
    file_id = body.get("file_id")
    if not isinstance(file_id, str) or DISPATCH_ID.fullmatch(file_id) is None:
        return _error(404, "pc_dispatch_not_found")
    owner = await _readable_owner(request)
    if isinstance(owner, JSONResponse):
        return owner
    uid, _store = owner
    dispatch = await _dispatch_row(request, uid, file_id)
    if isinstance(dispatch, JSONResponse):
        return dispatch
    if dispatch.get("state") != "done":
        return _error(409, "oracle_mesh_result_not_ready")
    content, refusal = await _stored_output(request, uid, dispatch)
    if refusal is not None:
        return refusal
    name = str(dispatch.get("file_path") or "").replace("\\", "/").rsplit("/", 1)[-1] or "파일"
    if name.lower().endswith(".hwp") and content[:8] == _HWP_OLE_MAGIC:
        # #6126: the older binary Hangul format is never converted. The bytes
        # answer first — an OLE2 compound document is refused with the one
        # save-as-HWPX guidance code every screen speaks (#2824's lane), so
        # the owner gets an instruction instead of an error. A mislabeled
        # .hwp whose bytes are a real HWPX (ZIP) package falls through and is
        # read as HWPX below, exactly like a .hwpx upload.
        return _error(422, "legacy_hwp_unsupported")
    text = _reference_text(name, content)
    if not isinstance(text, str) or not text.strip():
        return _error(422, "pc_reference_unreadable")
    return _response({"ok": True, "name": name, "text": text, "chars": len(text)})


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
