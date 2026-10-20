"""#4976 — PC file search adapter and result conversion.

The search runs on the owner's PC, inside the folder the server already
verified. This module is the product-side adapter for that search:

* it reuses the **existing local index** (Everything / the voidtools ES CLI)
  through an injected port — no new search engine and no new index is
  created here;
* it converts the matches into the **existing file item contract** (name,
  relative path, size, modification time, folder flag), so a chosen file can
  be handed to the existing read path unchanged;
* it never reads or downloads a file body: a filename/path search returns
  metadata only.

Distinct outcomes
-----------------
``not_installed``
    the local searcher is not present on this PC.
``index_not_ready``
    the searcher is present but its index cannot answer yet.
``search_failed``
    the searcher ran and failed.
``no_results``
    the searcher ran successfully and matched nothing inside the scope.
``ok``
    matches were converted and are inside the scope.

Scope
-----
The scope is the server-verified (device, allowed folder) pair. Results are
re-checked against that folder before they are returned: a path that escapes
the folder, a symlink/junction hop that resolves outside it, or a row that
belongs to another device is never part of the result. Out-of-scope rows are
excluded and counted, never silently mixed in.

This module is transport-agnostic: the searcher port is injected, so the same
adapter serves a local ES CLI on the PC and a remote device call elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import subprocess
from typing import Any, Callable, Mapping, Protocol, Sequence

# Bounded outcome codes. They are the only thing a caller may branch on.
SEARCH_OK = "ok"
SEARCH_NOT_INSTALLED = "not_installed"
SEARCH_INDEX_NOT_READY = "index_not_ready"
SEARCH_SEARCH_FAILED = "search_failed"
SEARCH_NO_RESULTS = "no_results"

#: The default ES CLI locations of the existing Everything installation.
DEFAULT_EVERYTHING_CLI_PATHS: tuple[str, ...] = (
    r"C:\Program Files\Everything\es.exe",
    r"C:\Program Files (x86)\Everything\es.exe",
)

#: Bounded ceiling for one search request. It bounds the *request*, never
#: the model input/output: the caller owns that limit, and the result reports
#: truncation truthfully instead of hiding it.
MAX_SEARCH_RESULTS = 500

#: How many rows beyond the caller's limit are fetched, to learn whether the
#: search space really holds more results than the request. One extra row is
#: enough and keeps the request bounded.
TRUNCATION_PROBE_ROWS = 1

#: The encoding the ES CLI writes its results in. ES writes UTF-8, so the
#: output is decoded as UTF-8 and never as the host's preferred encoding:
#: a Korean filename must survive the boundary unchanged, and a byte that is
#: not UTF-8 is a contract failure, never a mojibake name.
EVERYTHING_OUTPUT_ENCODING = "utf-8"


class PcFileSearchError(RuntimeError):
    """A search that could not be performed (never a result)."""


class PcFileSearchIndexNotReady(PcFileSearchError):
    """The local index exists but cannot answer yet (not an empty result)."""


@dataclass(frozen=True, slots=True)
class PcFileSearchScope:
    """The server-verified scope of one search."""

    root: str
    device_id: str
    local_device_id: str

    def __post_init__(self) -> None:
        for name in ("root", "device_id", "local_device_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise PcFileSearchError(f"{name} must be a non-empty string")
        if not os.path.isabs(self.root):
            raise PcFileSearchError("root must be an absolute folder path")
        if self.device_id != self.local_device_id:
            raise PcFileSearchError(
                "another device's results are never searched or returned"
            )


@dataclass(frozen=True, slots=True)
class PcFileSearcherStatus:
    """What the local searcher can tell us about itself."""

    installed: bool
    index_ready: bool


@dataclass(frozen=True, slots=True)
class PcFileSearchEntry:
    """One converted match, in the existing file item contract."""

    name: str
    relative_path: str
    size_bytes: int | None = None
    modified_at: str | None = None
    is_directory: bool = False

    def safe_dict(self) -> dict[str, Any]:
        """The existing file item contract (no body, no absolute path)."""
        return {
            "Name": self.name,
            "relative_path": self.relative_path,
            "Length": self.size_bytes,
            "LastWriteTimeUtc": self.modified_at,
            "PSIsContainer": self.is_directory,
        }

    def read_payload(self) -> dict[str, str]:
        """The payload the existing read path already accepts."""
        return {"op": "read", "path": self.relative_path}


@dataclass(frozen=True, slots=True)
class PcFileSearchResult:
    """The outcome of one search, in the existing file-list envelope."""

    status: str
    entries: tuple[PcFileSearchEntry, ...] = ()
    excluded_count: int = 0
    truncated: bool = False
    query: str = ""

    @property
    def ok(self) -> bool:
        return self.status == SEARCH_OK

    def safe_dict(self) -> dict[str, Any]:
        """The existing file-list envelope, extended with the search state."""
        return {
            "ok": self.ok,
            "path": "",
            "entries": [entry.safe_dict() for entry in self.entries],
            "truncated": self.truncated,
            "search_status": self.status,
            "excluded_count": self.excluded_count,
        }


class PcFileSearchPort(Protocol):
    """The local searcher (Everything ES CLI and equivalents)."""

    def status(self) -> PcFileSearcherStatus: ...

    def search(
        self, *, query: str, root: str, limit: int
    ) -> Sequence[str]: ...


#: How a searcher process is run. The timeout is keyword-only, so a caller
#: cannot pass it by accident and the default runner and an injected runner
#: share exactly one call shape.
ProcessRunner = Callable[..., "tuple[int, str, str]"]


def _default_process_runner(
    argv: Sequence[str], *, timeout: int
) -> tuple[int, str, str]:
    """Run a searcher process. Returns (exit code, stdout, stderr).

    The output is decoded as UTF-8, because that is what the ES CLI writes.
    Decoding with the host's preferred encoding would turn a Korean file name
    into mojibake on a non-UTF-8 host, so the encoding is fixed here instead
    of being inherited from the machine.
    """
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            list(argv),
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PcFileSearchError("the local searcher could not be executed") from exc
    return (
        completed.returncode,
        _decode_everything_output(completed.stdout),
        _decode_everything_output(completed.stderr),
    )


def _decode_everything_output(raw: bytes | str | None) -> str:
    """Decode ES output as UTF-8.

    A byte that is not UTF-8 is a contract failure: returning a mojibake
    name would be worse than reporting the search as failed.
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    try:
        return raw.decode(EVERYTHING_OUTPUT_ENCODING)
    except UnicodeDecodeError as exc:
        raise PcFileSearchError(
            "the local searcher returned output that is not valid UTF-8"
        ) from exc


def everything_search_argument(text: str) -> str:
    """The search text in the official ES command-line form.

    The official CLI documents that a double quote in the search text is
    written as a triple quote: one pair of double quotes only escapes spaces
    and is stripped again by ES. A newline or a NUL would end the argument
    and is refused outright.

    The official ``-search*`` form makes **the rest of the command line** a
    literal search, so it only holds while the search text is the last
    argument. The caller therefore puts it last, and this helper only makes
    the text itself safe.
    """
    if not isinstance(text, str):
        raise PcFileSearchError("the search text must be a string")
    if "\n" in text or "\r" in text or "\x00" in text:
        raise PcFileSearchError("the search text must be a single line")
    return text.replace('"', '"""')


class EverythingEsCliSearchPort:
    """The existing Everything index through the voidtools ES CLI.

    The CLI is the documented way to query the index that Everything already
    maintains; this adapter adds no index and no search engine. The CLI must be
    installed and its service running, otherwise the index cannot answer —
    that is reported as ``not_installed`` / ``index_not_ready`` instead of an
    empty result.

    The switches are the documented ES ones:

    * ``-get-everything-version`` — the service answers, so the index is
      reachable. ES exit code 8 means the Everything window was not found,
      i.e. the client is not running.
    * ``-path <folder>`` — search inside the verified folder only.
    * ``-n <count>`` — the request's result limit.
    * ``-full-path`` — the results are printed as full paths.
    * ``-timeout <ms>`` — wait for the Everything database to load before
      searching. Without it ES silently returns no results when the database
      is not loaded, which would look like an empty match.
    * ``-search*`` — the **rest of the command line** is a literal search
      text. That is the official form, and it has two preconditions this
      adapter enforces rather than assumes: the switch has to be the last
      one, so no later switch can be swallowed as search text, and the text
      itself has to be quoted the way the official syntax requires. The
      literal form is what keeps a user query from turning into an
      Everything filter; it is not a licence to treat the text as safe
      input without the escaping below.

    ES exit code 7 (the IPC query failed) is an index that cannot answer, not
    a failed match.
    """

    #: ES exit code: the Everything window was not found (client not running).
    ES_EXIT_NO_WINDOW = 8
    #: ES exit code: the IPC query failed or the reply was invalid.
    ES_EXIT_IPC_FAILED = 7

    def __init__(
        self,
        *,
        executable: str | None = None,
        runner: ProcessRunner | None = None,
        timeout: int = 10,
        index_wait_ms: int = 2000,
    ) -> None:
        self._executable = executable
        self._runner = runner or _default_process_runner
        self._timeout = timeout
        self._index_wait_ms = index_wait_ms

    def _resolve_executable(self) -> str | None:
        if self._executable:
            return self._executable if os.path.isfile(self._executable) else None
        for candidate in DEFAULT_EVERYTHING_CLI_PATHS:
            if os.path.isfile(candidate):
                return candidate
        return None

    def status(self) -> PcFileSearcherStatus:
        executable = self._resolve_executable()
        if executable is None:
            return PcFileSearcherStatus(installed=False, index_ready=False)
        try:
            code, _stdout, _stderr = self._runner(
                [executable, "-get-everything-version"], timeout=self._timeout,
            )
        except PcFileSearchError:
            return PcFileSearcherStatus(installed=True, index_ready=False)
        # The service must answer for the index to be queryable at all.
        return PcFileSearcherStatus(installed=True, index_ready=code == 0)

    def search(
        self, *, query: str, root: str, limit: int
    ) -> Sequence[str]:
        """Query the index and return the raw result rows.

        ``limit`` is the maximum number of rows to fetch, not the number of
        results the caller will keep: the caller asks for one row more than
        it needs, so it can tell whether more results exist.
        """
        executable = self._resolve_executable()
        if executable is None:
            raise PcFileSearchError("the local searcher is not installed")
        search_text = everything_search_argument(query)
        argv = [
            executable,
            "-path", root,
            "-n", str(max(1, limit)),
            "-full-path",
            "-timeout", str(self._index_wait_ms),
            # The literal form only holds while it is the last switch.
            "-search*", search_text,
        ]
        code, stdout, _stderr = self._runner(argv, timeout=self._timeout)
        if code == self.ES_EXIT_IPC_FAILED:
            raise PcFileSearchIndexNotReady(
                "the local index could not answer the query"
            )
        if code != 0:
            raise PcFileSearchError("the local searcher failed")
        rows: list[str] = []
        for line in stdout.splitlines():
            candidate = line.strip()
            if candidate:
                rows.append(candidate)
        return rows


def _resolve_inside(root: str, candidate: str) -> str | None:
    """Resolve a match and prove it stays inside the allowed folder.

    The real path is used on both sides, so a symlink or a Windows junction
    that points outside the folder resolves outside it and is refused.
    """
    if not isinstance(candidate, str) or not candidate.strip():
        return None
    if not os.path.isabs(candidate):
        return None
    try:
        resolved_root = os.path.realpath(root)
        resolved = os.path.realpath(candidate)
    except OSError:
        return None
    if resolved == resolved_root:
        return None
    prefix = resolved_root if resolved_root.endswith(os.sep) else resolved_root + os.sep
    if not resolved.startswith(prefix):
        return None
    return resolved


def _relative_to_root(resolved_root: str, resolved: str) -> str | None:
    try:
        relative = os.path.relpath(resolved, resolved_root)
    except ValueError:
        return None
    if relative in (".", os.curdir) or relative.startswith(".."):
        return None
    parts = [part for part in relative.replace("\\", "/").split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    return "/".join(parts)


def _entry_metadata(path: str) -> tuple[int | None, str | None, bool]:
    """Size, modification time and the folder flag — never the body."""
    try:
        stat_result = os.stat(path)
    except OSError:
        return None, None, False
    modified = getattr(stat_result, "st_mtime", None)
    modified_at = None
    if isinstance(modified, (int, float)):
        import datetime

        modified_at = (
            datetime.datetime.fromtimestamp(
                modified, tz=datetime.timezone.utc,
            ).isoformat().replace("+00:00", "Z")
        )
    return int(stat_result.st_size), modified_at, os.path.isdir(path)


def search_pc_files(
    *,
    scope: PcFileSearchScope,
    query: str,
    port: PcFileSearchPort,
    limit: int = MAX_SEARCH_RESULTS,
) -> PcFileSearchResult:
    """Search the verified folder and return the existing file item contract.

    The result never holds more than ``limit`` entries, and ``truncated`` is
    true only when the search space really holds more results than the
    request: the port is asked for one row beyond the limit, so "more
    results" is an observation and never an assumption.
    """
    if not isinstance(scope, PcFileSearchScope):
        raise PcFileSearchError("scope must be PcFileSearchScope")
    if not isinstance(query, str) or not query.strip():
        raise PcFileSearchError("query must be a non-empty string")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise PcFileSearchError("limit must be a positive integer")

    status = port.status()
    if not status.installed:
        return PcFileSearchResult(status=SEARCH_NOT_INSTALLED, query=query)
    if not status.index_ready:
        return PcFileSearchResult(status=SEARCH_INDEX_NOT_READY, query=query)

    probe_limit = limit + TRUNCATION_PROBE_ROWS
    try:
        rows = port.search(query=query, root=scope.root, limit=probe_limit)
    except PcFileSearchIndexNotReady:
        return PcFileSearchResult(status=SEARCH_INDEX_NOT_READY, query=query)
    except PcFileSearchError:
        return PcFileSearchResult(status=SEARCH_SEARCH_FAILED, query=query)
    except Exception:
        return PcFileSearchResult(status=SEARCH_SEARCH_FAILED, query=query)

    rows = list(rows or ())
    resolved_root = os.path.realpath(scope.root)
    entries: list[PcFileSearchEntry] = []
    excluded = 0
    for row in rows:
        resolved = _resolve_inside(scope.root, row if isinstance(row, str) else "")
        if resolved is None:
            excluded += 1
            continue
        relative = _relative_to_root(resolved_root, resolved)
        if relative is None:
            excluded += 1
            continue
        size_bytes, modified_at, is_directory = _entry_metadata(resolved)
        entries.append(PcFileSearchEntry(
            name=relative.rsplit("/", 1)[-1],
            relative_path=relative,
            size_bytes=size_bytes,
            modified_at=modified_at,
            is_directory=is_directory,
        ))

    if not entries:
        return PcFileSearchResult(
            status=SEARCH_NO_RESULTS, excluded_count=excluded, query=query,
        )
    # The caller asked for `limit` rows; the extra probe row only proves
    # whether more results exist.
    kept = entries[:limit]
    return PcFileSearchResult(
        status=SEARCH_OK,
        entries=tuple(kept),
        excluded_count=excluded,
        truncated=len(entries) > limit or len(rows) >= probe_limit,
        query=query,
    )


__all__ = [
    "DEFAULT_EVERYTHING_CLI_PATHS",
    "EVERYTHING_OUTPUT_ENCODING",
    "EverythingEsCliSearchPort",
    "MAX_SEARCH_RESULTS",
    "PcFileSearchEntry",
    "PcFileSearchError",
    "PcFileSearchIndexNotReady",
    "PcFileSearchPort",
    "PcFileSearchResult",
    "PcFileSearchScope",
    "PcFileSearcherStatus",
    "ProcessRunner",
    "SEARCH_INDEX_NOT_READY",
    "SEARCH_NOT_INSTALLED",
    "SEARCH_NO_RESULTS",
    "SEARCH_OK",
    "SEARCH_SEARCH_FAILED",
    "TRUNCATION_PROBE_ROWS",
    "everything_search_argument",
    "search_pc_files",
]
