#!/usr/bin/env python3
"""Read-only local inventory for the Dothome hosting cleanup (issue #2059).

Scope
-----
This tool inspects a directory that has ALREADY been copied down from the
Dothome hosting account onto the local machine. It never contacts the hosting
account: no remote login, no credential lookup, no HTTP call, no remote listing.

From local bytes only it reports:

* total size of the mirror and a per-directory size summary;
* files above a size threshold (default 10 MiB);
* archives, video, audio and image files;
* directories that look like old build output or tooling junk;
* byte-identical duplicate files and the space their extra copies occupy;
* the plausible CURRENT landing files (``index.html`` plus the CSS, JS and
  assets it references) so they can be protected;
* delete CANDIDATES, as a report only, grouped by reason.

Hard safety rules
-----------------
* ``MODE=REPORT_ONLY``. Nothing under the scan root is deleted, moved, renamed
  or rewritten. The only files this process writes are the ones explicitly
  requested through ``--out-json`` / ``--out-md``.
* No network use of any kind (``NETWORK_CALLS=0`` by construction).
* No credential is read from the environment, the command line or a config
  file, therefore no credential can be printed.
* Dangerous roots are refused: empty input, relative paths, a filesystem root,
  the user home directory and the user profile directory.
* Symlinks are recorded and skipped. They are never followed and never counted.
* Output is deterministic: no timestamp is emitted and every list is sorted, so
  two runs against an unchanged tree produce byte-identical reports.

Exit codes
----------
0  inventory produced
2  the scan root was refused or unusable
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Iterable, Sequence

TOOL_NAME = "dothome-inventory"
REPORT_VERSION = "1"

DEFAULT_LARGE_FILE_BYTES = 10 * 1024 * 1024
DEFAULT_HASH_MAX_BYTES = 256 * 1024 * 1024
HASH_CHUNK_BYTES = 1024 * 1024
MAX_PARSE_TEXT_BYTES = 4 * 1024 * 1024

ARCHIVE_SUFFIXES = frozenset(
    {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".iso", ".alz", ".jar", ".war"}
)
VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv", ".m4v", ".mpg", ".mpeg"})
AUDIO_SUFFIXES = frozenset({".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"})
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico", ".avif"})

BUILD_DIR_NAMES = frozenset(
    {
        "dist",
        "build",
        "out",
        "output",
        "_next",
        ".next",
        ".nuxt",
        ".output",
        ".svelte-kit",
        ".parcel-cache",
        "storybook-static",
        "target",
    }
)
JUNK_DIR_NAMES = frozenset(
    {
        "node_modules",
        "coverage",
        ".cache",
        "cache",
        ".turbo",
        "tmp",
        "temp",
        "bak",
        "backup",
        "old",
        "legacy",
        "dist_old",
        "build_old",
    }
)

LANDING_DOC_NAMES = frozenset({"index.html", "index.htm"})
STYLESHEET_SUFFIXES = frozenset({".css"})

_REF_ATTR_RE = re.compile(r"(?:src|href)\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
_SRCSET_ATTR_RE = re.compile(r"srcset\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
_CSS_URL_RE = re.compile(r"url\(\s*[\"']?([^\"')]+)[\"']?\s*\)", re.IGNORECASE)
_EXTERNAL_REF_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:)?//|^[a-z][a-z0-9+.-]*:|^#|^javascript:", re.IGNORECASE)


class InventoryError(Exception):
    """Raised when a scan root is refused or unusable."""


def _ancestors(rel: str) -> list[str]:
    """Return every directory key that contains ``rel``, deepest first."""
    parts = rel.split("/")[:-1]
    keys: list[str] = []
    prefix: list[str] = []
    for part in parts:
        prefix.append(part)
        keys.append("/".join(prefix))
    keys.append(".")
    return keys


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _dangerous_roots() -> tuple[Path, ...]:
    home = Path.home().resolve()
    items = [home]
    parent = home.parent
    if parent != home:
        items.append(parent)
    return tuple(items)


def validate_root(raw: Any) -> Path:
    """Return a resolved, safe scan root or raise :class:`InventoryError`."""
    if raw is None:
        raise InventoryError("ROOT_REQUIRED: an explicit --root is required")
    text = str(raw).strip()
    if not text:
        raise InventoryError("ROOT_REQUIRED: --root must not be empty")
    candidate = Path(text)
    if not candidate.is_absolute():
        raise InventoryError(f"ROOT_NOT_ABSOLUTE: {text!r} (pass an absolute path)")
    resolved = candidate.resolve()
    if resolved == Path(resolved.anchor):
        raise InventoryError(f"ROOT_IS_FILESYSTEM_ROOT: {resolved}")
    for dangerous in _dangerous_roots():
        if resolved == dangerous:
            raise InventoryError(f"ROOT_IS_HOME_OR_USER_ROOT: {resolved}")
    if resolved.is_symlink():
        raise InventoryError(f"ROOT_IS_SYMLINK: {resolved}")
    if not resolved.exists():
        raise InventoryError(f"ROOT_MISSING: {resolved}")
    if not resolved.is_dir():
        raise InventoryError(f"ROOT_NOT_DIRECTORY: {resolved}")
    return resolved


def _kind_for(suffix: str) -> str:
    if suffix in ARCHIVE_SUFFIXES:
        return "archive"
    if suffix in VIDEO_SUFFIXES:
        return "video"
    if suffix in AUDIO_SUFFIXES:
        return "audio"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    return "other"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _walk_files(root: Path) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, int], list[str], list[str], set[str]]:
    files: list[dict[str, Any]] = []
    dir_bytes: dict[str, int] = {".": 0}
    dir_file_counts: dict[str, int] = {".": 0}
    symlinks: list[str] = []
    errors: list[str] = []
    old_dirs: set[str] = set()

    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        kept_dirs: list[str] = []
        for name in sorted(dirnames):
            child = current_path / name
            rel_dir = _relative(root, child)
            if child.is_symlink():
                symlinks.append(rel_dir)
                continue
            if name.lower() in BUILD_DIR_NAMES or name.lower() in JUNK_DIR_NAMES:
                old_dirs.add(rel_dir)
            for key in _ancestors(rel_dir + "/."):
                dir_bytes.setdefault(key, 0)
                dir_file_counts.setdefault(key, 0)
            kept_dirs.append(name)
        dirnames[:] = kept_dirs

        for name in sorted(filenames):
            path = current_path / name
            rel = _relative(root, path)
            if path.is_symlink():
                symlinks.append(rel)
                continue
            try:
                info = path.stat()
            except OSError:
                errors.append(f"stat_failed:{rel}")
                continue
            if not stat.S_ISREG(info.st_mode):
                errors.append(f"not_regular_file:{rel}")
                continue
            size = int(info.st_size)
            suffix = path.suffix.lower()
            files.append({"path": rel, "bytes": size, "suffix": suffix, "kind": _kind_for(suffix)})
            for key in _ancestors(rel):
                dir_bytes[key] = dir_bytes.get(key, 0) + size
                dir_file_counts[key] = dir_file_counts.get(key, 0) + 1

    files.sort(key=lambda item: item["path"])
    return files, dir_bytes, dir_file_counts, sorted(symlinks), sorted(errors), old_dirs


def _directory_summary(dir_bytes: dict[str, int], dir_file_counts: dict[str, int]) -> list[dict[str, Any]]:
    rows = [
        {
            "path": key,
            "bytes": dir_bytes.get(key, 0),
            "files": dir_file_counts.get(key, 0),
        }
        for key in sorted(dir_bytes)
    ]
    rows.sort(key=lambda row: (-row["bytes"], row["path"]))
    return rows


def _duplicates(root: Path, files: Sequence[dict[str, Any]], hash_max_bytes: int, errors: list[str]) -> list[dict[str, Any]]:
    by_size: dict[int, list[str]] = {}
    for entry in files:
        by_size.setdefault(int(entry["bytes"]), []).append(str(entry["path"]))

    groups: list[dict[str, Any]] = []
    for size in sorted(by_size):
        paths = sorted(by_size[size])
        if len(paths) < 2:
            continue
        if size > hash_max_bytes:
            buckets: dict[str, list[str]] = {}
            for rel in paths:
                buckets.setdefault(Path(rel).name, []).append(rel)
            for name in sorted(buckets):
                members = buckets[name]
                if len(members) < 2:
                    continue
                groups.append(
                    {
                        "method": "size+name",
                        "sha256": None,
                        "bytes": size,
                        "count": len(members),
                        "paths": members,
                        "extra_copies": len(members) - 1,
                        "reclaimable_bytes": size * (len(members) - 1),
                    }
                )
            continue
        buckets = {}
        for rel in paths:
            try:
                digest = _sha256(root / rel)
            except OSError:
                errors.append(f"hash_failed:{rel}")
                continue
            buckets.setdefault(digest, []).append(rel)
        for digest in sorted(buckets):
            members = buckets[digest]
            if len(members) < 2:
                continue
            groups.append(
                {
                    "method": "sha256",
                    "sha256": digest,
                    "bytes": size,
                    "count": len(members),
                    "paths": members,
                    "extra_copies": len(members) - 1,
                    "reclaimable_bytes": size * (len(members) - 1),
                }
            )
    return groups


def _resolve_ref(root: Path, doc_rel: str, ref: str) -> str | None:
    cleaned = ref.strip().split("?")[0].split("#")[0]
    if not cleaned:
        return None
    bases: list[Path] = [root]
    if cleaned.startswith("/"):
        bases = [root / Path(doc_rel).parent, root]
    else:
        bases = [root / Path(doc_rel).parent]
    for base in bases:
        joined = base / cleaned.lstrip("/")
        normalized = Path(os.path.normpath(str(joined)))
        if not normalized.is_relative_to(root):
            continue
        if normalized.is_symlink() or not normalized.is_file():
            continue
        return _relative(root, normalized)
    return None


def _extract_refs(text: str) -> list[str]:
    refs: list[str] = []
    for pattern in (_REF_ATTR_RE, _SRCSET_ATTR_RE):
        for match in pattern.finditer(text):
            for token in match.group(1).split(","):
                candidate = token.strip().split(" ")[0]
                if candidate:
                    refs.append(candidate)
    for match in _CSS_URL_RE.finditer(text):
        refs.append(match.group(1).strip())
    return [ref for ref in refs if ref and not _EXTERNAL_REF_RE.match(ref)]


def _read_text(path: Path) -> str:
    if path.stat().st_size > MAX_PARSE_TEXT_BYTES:
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _landing(root: Path, files: Sequence[dict[str, Any]]) -> dict[str, Any]:
    documents = sorted(
        entry["path"] for entry in files if Path(entry["path"]).name.lower() in LANDING_DOC_NAMES
    )
    references: dict[str, str] = {}
    for doc in documents:
        text = _read_text(root / doc)
        for ref in _extract_refs(text):
            resolved = _resolve_ref(root, doc, ref)
            if resolved and resolved != doc and resolved not in references:
                references[resolved] = doc
    for css in sorted([rel for rel in references if Path(rel).suffix.lower() in STYLESHEET_SUFFIXES]):
        text = _read_text(root / css)
        for ref in _extract_refs(text):
            resolved = _resolve_ref(root, css, ref)
            if resolved and resolved not in references and resolved not in documents:
                references[resolved] = css
    protected = sorted(set(documents) | set(references))
    return {
        "documents": documents,
        "references": [{"path": rel, "referenced_by": references[rel]} for rel in sorted(references)],
        "protected": protected,
    }


def _delete_candidates(
    files: Sequence[dict[str, Any]],
    *,
    protected: Iterable[str],
    old_dirs: set[str],
    duplicate_groups: Sequence[dict[str, Any]],
    large_file_bytes: int,
) -> list[dict[str, Any]]:
    protected_set = set(protected)
    candidates: dict[str, dict[str, Any]] = {}

    def add(rel: str, size: int, category: str, reason: str) -> None:
        entry = candidates.get(rel)
        if entry is None:
            entry = {"path": rel, "bytes": size, "categories": [], "reasons": []}
            candidates[rel] = entry
        if category not in entry["categories"]:
            entry["categories"].append(category)
        if reason not in entry["reasons"]:
            entry["reasons"].append(reason)

    old_dir_list = sorted(old_dirs)
    for entry in files:
        rel = entry["path"]
        if rel in protected_set:
            continue
        kind = entry["kind"]
        if kind == "archive":
            add(rel, entry["bytes"], "archive", "archive_bundle_not_required_by_static_landing")
        elif kind == "video":
            add(rel, entry["bytes"], "media", "video_asset_not_referenced_by_landing")
        elif kind == "audio":
            add(rel, entry["bytes"], "media", "audio_asset_not_referenced_by_landing")
        if any(rel == old or rel.startswith(old + "/") for old in old_dir_list):
            add(rel, entry["bytes"], "old_directory", "file_lives_under_build_or_junk_directory")
        if entry["bytes"] >= large_file_bytes:
            add(rel, entry["bytes"], "oversized", "file_exceeds_size_threshold")

    for group in duplicate_groups:
        members = sorted(group["paths"], key=lambda rel: (rel.count("/"), rel))
        keeper = members[0]
        for extra in members[1:]:
            if extra in protected_set:
                continue
            add(extra, int(group["bytes"]), "duplicate", f"byte_identical_copy_of:{keeper}")

    rows = sorted(candidates.values(), key=lambda row: (-row["bytes"], row["path"]))
    return rows


def scan(
    root: Path,
    *,
    large_file_bytes: int = DEFAULT_LARGE_FILE_BYTES,
    hash_max_bytes: int = DEFAULT_HASH_MAX_BYTES,
    quota_bytes: int = 0,
) -> dict[str, Any]:
    """Build the full inventory report for ``root``. Never mutates ``root``."""
    files, dir_bytes, dir_file_counts, symlinks, errors, old_dirs = _walk_files(root)
    total_bytes = sum(int(entry["bytes"]) for entry in files)

    large_files = [entry for entry in files if entry["bytes"] >= large_file_bytes]
    archives = [entry for entry in files if entry["kind"] == "archive"]
    media = [entry for entry in files if entry["kind"] in {"video", "audio", "image"}]

    directory_rows = _directory_summary(dir_bytes, dir_file_counts)
    old_directory_rows = sorted(
        [
            {
                "path": rel,
                "kind": "build_output" if Path(rel).name.lower() in BUILD_DIR_NAMES else "junk",
                "bytes": dir_bytes.get(rel, 0),
                "files": dir_file_counts.get(rel, 0),
            }
            for rel in old_dirs
        ],
        key=lambda row: (-row["bytes"], row["path"]),
    )

    duplicate_groups = _duplicates(root, files, hash_max_bytes, errors)
    landing = _landing(root, files)
    candidates = _delete_candidates(
        files,
        protected=landing["protected"],
        old_dirs=old_dirs,
        duplicate_groups=duplicate_groups,
        large_file_bytes=large_file_bytes,
    )
    reclaimable_bytes = sum(int(row["bytes"]) for row in candidates)

    summary: dict[str, Any] = {
        "root": str(root),
        "files_scanned": len(files),
        "directories_scanned": len(directory_rows),
        "total_bytes": total_bytes,
        "large_files": len(large_files),
        "large_file_bytes": sum(int(entry["bytes"]) for entry in large_files),
        "archives": len(archives),
        "archive_bytes": sum(int(entry["bytes"]) for entry in archives),
        "media_files": len(media),
        "media_bytes": sum(int(entry["bytes"]) for entry in media),
        "old_directories": len(old_directory_rows),
        "old_directory_bytes": sum(int(row["bytes"]) for row in old_directory_rows),
        "duplicate_groups": len(duplicate_groups),
        "duplicate_reclaimable_bytes": sum(int(group["reclaimable_bytes"]) for group in duplicate_groups),
        "landing_documents": len(landing["documents"]),
        "landing_protected_files": len(landing["protected"]),
        "candidate_files": len(candidates),
        "reclaimable_bytes": reclaimable_bytes,
        "projected_remaining_bytes": total_bytes - reclaimable_bytes,
    }
    if quota_bytes > 0:
        summary["quota_bytes"] = quota_bytes
        summary["over_quota_bytes"] = max(0, total_bytes - quota_bytes)
        summary["projected_over_quota_bytes"] = max(0, total_bytes - reclaimable_bytes - quota_bytes)

    return {
        "tool": TOOL_NAME,
        "report_version": REPORT_VERSION,
        "mode": "REPORT_ONLY",
        "safety": {
            "delete_performed": "NO",
            "files_modified": 0,
            "network_calls": 0,
            "hosting_login": "NO",
            "credential_read": "NO",
            "symlink_following": "NO",
        },
        "parameters": {
            "large_file_bytes": large_file_bytes,
            "hash_max_bytes": hash_max_bytes,
        },
        "summary": summary,
        "directories": directory_rows,
        "large_files": large_files,
        "archives": archives,
        "media": media,
        "old_directories": old_directory_rows,
        "duplicates": duplicate_groups,
        "landing": landing,
        "delete_candidates": candidates,
        "symlinks_skipped": symlinks,
        "errors": sorted(set(errors)),
    }


def _human_mb(value: int) -> str:
    return f"{value / (1024 * 1024):.2f}MiB"


def render_summary(report: dict[str, Any]) -> str:
    summary = report["summary"]
    safety = report["safety"]
    lines = [
        "DOTHOME_INVENTORY=OK",
        "MODE=REPORT_ONLY",
        f"ROOT={summary['root']}",
        f"NETWORK_CALLS={safety['network_calls']}",
        f"HOSTING_LOGIN={safety['hosting_login']}",
        f"DELETE_PERFORMED={safety['delete_performed']}",
        f"FILES_SCANNED={summary['files_scanned']}",
        f"TOTAL_BYTES={summary['total_bytes']}",
        f"TOTAL_HUMAN={_human_mb(summary['total_bytes'])}",
        f"LARGE_FILES={summary['large_files']}",
        f"ARCHIVES={summary['archives']}",
        f"MEDIA_FILES={summary['media_files']}",
        f"OLD_DIRECTORIES={summary['old_directories']}",
        f"OLD_DIRECTORY_BYTES={summary['old_directory_bytes']}",
        f"DUPLICATE_GROUPS={summary['duplicate_groups']}",
        f"DUPLICATE_RECLAIMABLE_BYTES={summary['duplicate_reclaimable_bytes']}",
        f"LANDING_DOCUMENTS={summary['landing_documents']}",
        f"LANDING_PROTECTED_FILES={summary['landing_protected_files']}",
        f"CANDIDATE_FILES={summary['candidate_files']}",
        f"RECLAIMABLE_BYTES={summary['reclaimable_bytes']}",
        f"RECLAIMABLE_HUMAN={_human_mb(summary['reclaimable_bytes'])}",
        f"PROJECTED_REMAINING_BYTES={summary['projected_remaining_bytes']}",
    ]
    if "quota_bytes" in summary:
        lines.append(f"QUOTA_BYTES={summary['quota_bytes']}")
        lines.append(f"OVER_QUOTA_BYTES={summary['over_quota_bytes']}")
        lines.append(f"PROJECTED_OVER_QUOTA_BYTES={summary['projected_over_quota_bytes']}")
    lines.append("NEXT_STEP=REVIEW_REPORT_WITH_OWNER_BEFORE_ANY_DELETE")
    return "\n".join(lines)


def render_markdown(report: dict[str, Any], *, top: int = 25) -> str:
    summary = report["summary"]

    def table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
        out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
        if not rows:
            out.append("| " + " | ".join(["_none_"] * len(headers)) + " |")
        for row in rows:
            out.append("| " + " | ".join(str(cell) for cell in row) + " |")
        return out

    lines: list[str] = [
        "# Dothome inventory (issue #2059)",
        "",
        f"- Root: `{summary['root']}`",
        f"- Mode: `{report['mode']}` — `DELETE_PERFORMED={report['safety']['delete_performed']}`",
        f"- `NETWORK_CALLS={report['safety']['network_calls']}` / `HOSTING_LOGIN={report['safety']['hosting_login']}`",
        "",
        "## Summary",
        "",
        "| metric | value |",
        "| --- | --- |",
    ]
    for key, value in summary.items():
        if key == "root":
            continue
        rendered = f"{value} ({_human_mb(value)})" if key.endswith("_bytes") else str(value)
        lines.append(f"| {key} | {rendered} |")

    lines += ["", "## Largest directories", ""]
    lines += table(
        ["directory", "bytes", "human", "files"],
        [
            [f"`{row['path']}`", row["bytes"], _human_mb(row["bytes"]), row["files"]]
            for row in report["directories"][:top]
        ],
    )

    lines += ["", "## Old build / junk directories", ""]
    lines += table(
        ["directory", "kind", "bytes", "human", "files"],
        [
            [f"`{row['path']}`", row["kind"], row["bytes"], _human_mb(row["bytes"]), row["files"]]
            for row in report["old_directories"][:top]
        ],
    )

    lines += ["", "## Large files", ""]
    lines += table(
        ["file", "bytes", "human", "kind"],
        [
            [f"`{row['path']}`", row["bytes"], _human_mb(row["bytes"]), row["kind"]]
            for row in report["large_files"][:top]
        ],
    )

    lines += ["", "## Duplicates", ""]
    duplicate_rows = []
    for group in report["duplicates"][:top]:
        duplicate_rows.append(
            [
                group["method"],
                group["bytes"],
                group["count"],
                _human_mb(group["reclaimable_bytes"]),
                ", ".join(f"`{path}`" for path in group["paths"]),
            ]
        )
    lines += table(["method", "bytes", "copies", "reclaimable", "paths"], duplicate_rows)

    lines += ["", "## Current landing candidates (protected)", "", "### index documents", ""]
    lines += table(["file", "role"], [[f"`{path}`", "document"] for path in report["landing"]["documents"]])
    lines += ["", "### referenced css / js / assets", ""]
    lines += table(
        ["file", "role"],
        [[f"`{row['path']}`", f"referenced by `{row['referenced_by']}`"] for row in report["landing"]["references"][:top]],
    )

    lines += ["", "## Delete candidates (report only — nothing was deleted)", ""]
    lines += table(
        ["file", "bytes", "human", "categories", "reasons"],
        [
            [
                f"`{row['path']}`",
                row["bytes"],
                _human_mb(row["bytes"]),
                ", ".join(row["categories"]),
                ", ".join(row["reasons"]),
            ]
            for row in report["delete_candidates"][:top]
        ],
    )
    lines += [
        "",
        "## Owner decision required",
        "",
        "No file above has been deleted. Deletion is a separate, owner-approved step",
        "performed only after the backup in the runbook is verified.",
        "",
    ]
    return "\n".join(lines) + "\n"


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dothome_inventory.py",
        description="Read-only local inventory of an already-downloaded Dothome mirror (issue #2059).",
    )
    parser.add_argument("--root", required=True, help="absolute path of the local mirror to scan")
    parser.add_argument("--out-json", default=None, help="optional path for the JSON report")
    parser.add_argument("--out-md", default=None, help="optional path for the Markdown report")
    parser.add_argument("--large-threshold-mb", type=float, default=DEFAULT_LARGE_FILE_BYTES / (1024 * 1024))
    parser.add_argument("--hash-max-mb", type=float, default=DEFAULT_HASH_MAX_BYTES / (1024 * 1024))
    parser.add_argument("--quota-mb", type=float, default=0.0, help="optional hosting quota in MiB for the over-quota report")
    parser.add_argument("--top", type=int, default=25, help="rows per Markdown table")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        root = validate_root(args.root)
    except InventoryError as exc:
        print(f"DOTHOME_INVENTORY_ERROR={exc}", file=sys.stderr)
        return 2

    report = scan(
        root,
        large_file_bytes=int(args.large_threshold_mb * 1024 * 1024),
        hash_max_bytes=int(args.hash_max_mb * 1024 * 1024),
        quota_bytes=int(args.quota_mb * 1024 * 1024),
    )
    print(render_summary(report))
    if args.out_json:
        _write_text(Path(args.out_json), json.dumps(report, indent=2, sort_keys=False, ensure_ascii=False) + "\n")
        print(f"JSON_REPORT={args.out_json}")
    if args.out_md:
        _write_text(Path(args.out_md), render_markdown(report, top=args.top))
        print(f"MARKDOWN_REPORT={args.out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
