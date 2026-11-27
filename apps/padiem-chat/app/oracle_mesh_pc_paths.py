"""Oracle Mesh PC path and operation validation."""
from __future__ import annotations

import re
from typing import Any

from padiem_ai_core.powershell_literal import ps_literal

from .claw_pc_search_command import pc_search_mode, pc_search_path


PC_FILES_MAX_PATH_CHARS = 2048
#: One page of a folder listing is a transport unit, not a product ceiling: the
#: route keeps asking for the next page until the PC says there is nothing left, so
#: a folder of any size is fully reachable. Measured on 컴1's C:/Windows/System32
#: (4,925 entries) on 2026-10-29 through the real command lane: 200 rows = 20,647
#: transcript bytes in 1,240 ms; 500 rows = 53,979 bytes in 1,454 ms. 200 keeps one
#: page ~10x under the 6 MB result-body bound and ~100x under the 2 MiB D1 row
#: bound, and small enough that the Worker's parse of a page stays a fraction of its
#: 10 ms CPU budget. The old silent `-First 200` cut had no continuation; this
#: constant has one.
PC_FILES_LIST_PAGE_SIZE = 50
#: The read bound this deployment asks an installed connector for. It is the
#: connector's own read envelope (``MAX_READ_BYTES_ENVELOPE`` in kagent's
#: oracle-mesh executor), not a product cap on a file's size: a file larger than
#: this is answered with its first range and paged through read_file_chunk
#: (#5882 A). Raising or removing it needs a new connector version, because an
#: installed executor refuses a bound above its envelope.
PC_FILES_READ_MAX_BYTES = 20_000_000
PC_FILES_ERROR_PREFIX = "PADIEM_PC_FILE_ERROR:"
#: Stable per-call reference suffix the Engine uses for read_file. The poll
#: route reads it from the dispatch row (never from a caller) to decide the
#: bounded read size for this one call.
_PC_FILES_READ_TOOL_MARKER = ":read_file:"
#: Self-describing root for a PC-files read row. The real Windows path is in
#: ``file_path``; this value only marks which lane staged the row.
_PC_FILES_READ_ROOT_REF = "pc_files_read"
_PC_FILES_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,127}$")

def _pc_files_text(value: Any, *, limit: int) -> str | None:
    if not isinstance(value, str) or not value or len(value) > limit:
        return None
    if any(ord(ch) < 32 for ch in value):
        return None
    return value


def _pc_files_approved_root(file_path: Any) -> str | None:
    """The approved folder is the mapped file's parent, never a caller value.

    The ownership row already pins one real file on one real PC. Its parent is
    the smallest root that cannot widen the operator's grant to a whole drive.
    """
    if not isinstance(file_path, str) or not file_path:
        return None
    normalized = file_path.replace("\\", "/")
    if "/" not in normalized:
        return None
    root = normalized.rsplit("/", 1)[0]
    if not root or root.endswith(":") or len(root) > 32000:
        return None
    # At least one real folder component below the drive (C:/Users/...).
    if root.count("/") < 1:
        return None
    return root


def _pc_files_relative_path(value: Any) -> str | None:
    """A relative path inside the approved root, or None.

    ``""`` (and ``.``) means the root itself. Absolute paths, drive/ADS
    prefixes, empty segments and any ``..`` segment are refused here; the
    caller never joins an unvalidated value.
    """
    text = _pc_files_text(value, limit=PC_FILES_MAX_PATH_CHARS)
    if text is None:
        return None
    text = text.strip().replace("\\", "/")
    if text in ("", "."):
        return ""
    if text.startswith("/") or (len(text) >= 2 and text[1] == ":"):
        return None
    parts = text.split("/")
    if any(part in ("", ".", "..") or ":" in part for part in parts):
        return None
    return "/".join(parts)


def _pc_files_roots_of_map_row(file_path: Any) -> list[dict[str, Any]]:
    """The deployment map's one approved folder, in the directory's shape.

    The map pins a single real file, so its parent is the only root and the
    folder's own name is the only label. This keeps the fallback lane answering
    exactly what it answered before PR-2, through one shape.
    """
    root = _pc_files_approved_root(file_path)
    if root is None:
        return []
    return [{"root_ref": None, "label": root.rsplit("/", 1)[-1], "path": root}]


#: How an owner refers to a drive they did not name: `C`, `C:`, `C드라이브`,
#: `c drive` all mean the whole C drive, which is the scope a linked PC has by
#: default (#5573, Owner decision).
_DRIVE_REFERENCE = re.compile(r"([A-Za-z])(?: ?(?:드라이브|drive))?[:]?/?", re.IGNORECASE)
#: How an owner refers to the place they are already standing.
_ROOT_WORDS = frozenset({
    "루트", "여기", "최상위", "최 상위", "승인 폴더", "승인폴더", "root", "here",
})


def _drive_reference(text: str) -> str | None:
    """The drive root a reference names, or ``None`` when it names none."""
    match = _DRIVE_REFERENCE.fullmatch(text.strip())
    return None if match is None else match.group(1).upper() + ":"


def _pc_files_pick_root(
    roots: Any, value: Any,
) -> tuple[str, str] | None:
    """``(approved folder, relative path)`` for one requested path, or None.

    (A) from the owner's decision: an account's PC can carry several approved
    folders, and the model sees their labels and never a real path. With exactly
    one folder a plain relative path still means what it meant before — that
    folder — so the existing Engine calls are unaffected. With two or more, the
    label is the namespace and is required: choosing between two of the owner's
    folders by guessing is not authority.
    """
    if not isinstance(roots, list) or not roots:
        return None
    if any(
        not isinstance(root, dict)
        or not isinstance(root.get("label"), str) or not root["label"]
        or not isinstance(root.get("path"), str) or not root["path"]
        for root in roots
    ):
        return None
    if isinstance(value, str) and not value.strip():
        # An empty path and "." are the same request: the granted root itself.
        # With several grants the label rule below is what makes the owner name
        # one of them, so nothing is ever chosen for them.
        text = "."
    else:
        text = _pc_files_text(value, limit=PC_FILES_MAX_PATH_CHARS)
        if text is None:
            return None
        text = text.strip().replace("\\", "/")
    drive = _drive_reference(text)
    if drive is not None and any(
        str(root["path"]).replace("\\", "/").rstrip("/").upper() == drive
        for root in roots
    ):
        # A drive the account granted means that drive, the whole of it - not a
        # folder inside another grant. Anything else stays ordinary path text, so
        # a file actually named `C` is still reachable.
        return drive, ""
    if text in _ROOT_WORDS and len(roots) == 1:
        # "여기·루트·최상위" means the granted place. With one grant that is
        # unambiguous; with several the owner has to say which one, and the label
        # rule below is what makes them say it.
        return roots[0]["path"], ""
    if len(roots) == 1:
        label, separator, remainder = text.partition("/")
        # One folder means the label is redundant, not forbidden: a caller that
        # names it gets the same folder either way.
        if separator and label == roots[0]["label"]:
            text = remainder
        relative = _pc_files_relative_path(text or ".")
        return None if relative is None else (roots[0]["path"], relative)
    label, separator, remainder = text.partition("/")
    if not separator:
        return None
    named = [root for root in roots if root["label"] == label]
    if len(named) != 1:
        return None
    relative = _pc_files_relative_path(remainder or ".")
    return None if relative is None else (named[0]["path"], relative)


def _pc_files_powershell_literal(value: str) -> str:
    # #7559: PowerShell closes a single-quoted string on five quote characters,
    # so doubling only ``'`` was not a boundary. The shared literal doubles all
    # five (PowerShell's own escaping rule).
    return ps_literal(value)


#: The closed operation set this lane serves: readers, one search, four writers.
_PC_FILES_OPS = ("list", "read", "read_chunk", "search", "write", "edit", "move", "delete",
                 "mkdir")

#: #7602 — the file operations that only read. A run-out lease hands these out
#: again because a second run cannot change the PC; every other op writes.
_PC_FILES_READ_OPS = frozenset({"list", "read", "read_chunk", "search"})


def _pc_files_read_only(op: Any) -> bool:
    """The server's own read/write word for one resolved file operation.

    A request never supplies it: the body's key set is closed, and this is
    computed from the operation the route itself resolved.
    """
    return isinstance(op, str) and op in _PC_FILES_READ_OPS
#: #7065: an edit changes bytes exactly like a write, so it carries the same
#: backup-before-change rule, the same reparse-point guard and the same one-line
#: account. It is only the input that differs: the caller names the old text
#: instead of the whole new file. A mkdir changes the tree the same way; it has
#: no original, so its backup leg answers none, the way a write to a new file
#: already does.
_PC_WRITE_OPS = ("write", "edit", "move", "delete", "mkdir")


def _pc_files_claim_op(op: Any, search_mode: Any) -> str | None:
    """The scope-ceiling operation one dispatch needs, or None when invalid.

    A search names which half of the file it reads, so the signed ceiling is
    checked against ``search_name`` or ``search_content`` rather than the one
    wire-level word both tools share.
    """
    if op == "read_chunk":
        # A range read is the same read authority as read_file; the file is
        # never sent whole, and the claim's `read` already covers it.
        return "read"
    if op != "search":
        return op if op in _PC_FILES_OPS else None
    mode = pc_search_mode(search_mode)
    if mode is None:
        return None
    return "search_content" if mode == "content" else "search_name"

def _pc_files_search_roots(roots: Any, value: Any) -> list[dict[str, str]] | None:
    """Resolve the optional search folder to the roots the command may scan.

    A label or relative folder uses ``pc_search_path`` as before. #8048: an
    external connector names a recursive search folder as an absolute path
    inside an owner's registered drive, which Engine folds to the same
    ``<drive>:/<relative>`` shape the list route already accepts. Fall back to
    that route's ``_pc_files_pick_root`` for those paths; an unregistered drive
    is still refused there, so no grant is widened.
    """
    if not isinstance(roots, list) or not roots:
        return None
    path = pc_search_path(value)
    if path is None:
        path = value
    if not path:
        return [{"label": entry["label"], "path": entry["path"]} for entry in roots]
    picked = _pc_files_pick_root(roots, path)
    if picked is None:
        return None
    root, relative = picked
    label = next((entry["label"] for entry in roots if entry["path"] == root), None)
    if label is None:
        return None
    return [{"label": label,
             "path": root.rstrip("/") + ("/" + relative if relative else "")}]
