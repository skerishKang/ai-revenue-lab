"""pc_list depth and pc_search recursive run for real on this machine's PowerShell.

The server builds one command string for each call; these tests hand that exact
string to a real PowerShell against a temporary folder and read the JSON answer
back. What they hold, on every OS:

  * a depth-2 walk lists two levels and a depth-3 walk reaches the third, each
    row carrying its relative path and level;
  * a hidden folder and a folder shortcut are listed but never entered, so
    neither their children nor the shortcut target's children appear;
  * a recursive name search finds files in subfolders by relative path and
    never follows the shortcut;
  * a deep walk stops at 200 rows with ``truncated``;
  * a recursive search stops at 50 rows with ``has_more``.

The two OSes only differ in how a folder is made hidden and how a shortcut is
made:

  * Windows: ``attrib +H`` for the hidden attribute, a junction (which needs no
    elevation) with a symbolic link as fallback. These are the attributes the
    product actually meets, since it runs on the customer's Windows PC.
  * POSIX: a dot-prefixed folder and ``os.symlink``. PowerShell 7 on Unix maps
    dot names to the Hidden attribute and links to ReparsePoint, but the
    Windows attribute bit is not the same test, so the hidden-folder descent
    assertion runs on Windows only. Depth, the row cap, the result cap and
    shortcut non-descent are checked on both — the same command text and the
    same product rule.

If the shortcut cannot be created (no privilege, no junction support), only
the shortcut assertions are skipped; everything else still runs.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from app.oracle_mesh_read_return_routes import _pc_files_command

WINDOWS = sys.platform == "win32"


def _powershell() -> list[str]:
    """The real shell this machine has: Windows PowerShell 5.1 first."""
    if WINDOWS:
        five_one = Path(os.environ.get("SystemRoot", r"C:\Windows")) / (
            "System32/WindowsPowerShell/v1.0/powershell.exe")
        if five_one.is_file():
            return [str(five_one), "-NoProfile", "-NonInteractive", "-Command"]
    pwsh = shutil.which("pwsh")
    if pwsh:
        return [pwsh, "-NoProfile", "-NonInteractive", "-Command"]
    pytest.skip("no PowerShell on this machine")


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16-le", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _run(script: str) -> dict:
    # The walk sets the console encoding itself; the prefix makes the same
    # promise for the guard's early answer, so Korean names survive the pipe.
    prefix = "$OutputEncoding=[Text.UTF8Encoding]::new($false);" \
             "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"
    completed = subprocess.run(
        _powershell() + [prefix + script],
        capture_output=True, timeout=240,
    )
    text = _decode(completed.stdout).strip()
    assert completed.returncode == 0 and text, (
        f"PowerShell failed: rc={completed.returncode} "
        f"out={text[:400]!r} err={_decode(completed.stderr)[:400]!r}")
    lines = text.splitlines()
    # One JSON answer, one line: anything else is a caller's text escaping its
    # quoted literal and running as a statement of its own.
    assert len(lines) == 1, lines[:5]
    return json.loads(lines[0])


def _rel(*parts: str) -> str:
    """The product joins relative rows with a backslash; compare in OS form."""
    return os.sep.join(parts)


def _norm(value: str) -> str:
    return value.replace("\\", os.sep).replace("/", os.sep)


def _make_shortcut(target: Path, link: Path) -> bool:
    if WINDOWS:
        # A junction needs no elevation; a symbolic link may.
        made = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, text=True)
        if made.returncode == 0:
            return True
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        return False
    return True


def _tree(root: Path) -> dict:
    """The same shape on both OSes, built the way each OS hides and links."""
    (root / "sub" / "deep").mkdir(parents=True)
    (root / "sub" / "deep" / "target.txt").write_text("x", encoding="utf-8")
    (root / "sub" / "report.txt").write_text("y", encoding="utf-8")
    (root / "top.txt").write_text("z", encoding="utf-8")
    korean = root / "한글 폴더"
    korean.mkdir()
    (korean / "보고서.txt").write_text("가", encoding="utf-8")
    (root / "space 'quote'").mkdir()
    (root / "space 'quote'" / "quoted file.txt").write_text("q", encoding="utf-8")

    hidden = root / ("hidden_dir" if WINDOWS else ".hidden")
    hidden.mkdir()
    (hidden / "z.txt").write_text("z", encoding="utf-8")
    if WINDOWS:
        made = subprocess.run(["attrib", "+H", str(hidden)], capture_output=True)
        assert made.returncode == 0, "attrib +H must make the folder hidden here"

    target = root.parent / (root.name + "_shortcut_target")
    target.mkdir()
    (target / "inside_link.txt").write_text("l", encoding="utf-8")
    link = root / "escape"
    return {"hidden": hidden.name, "link": link.name,
            "link_made": _make_shortcut(target, link)}


def _rows(parsed: dict) -> list[tuple[str, int]]:
    return [(_norm(row["relative_path"]), row["depth"]) for row in parsed["items"]]


def test_depth_two_walk_and_recursive_search_execute():
    root = Path(tempfile.mkdtemp(prefix="padiem_pc_depth_"))
    try:
        shape = _tree(root)

        parsed = _run(_pc_files_command(
            op="list", root=str(root), relative="", depth=2))
        rows = _rows(parsed)
        assert (_rel("sub"), 1) in rows
        assert (_rel("sub", "deep"), 2) in rows
        assert (_rel("top.txt"), 1) in rows
        assert (_rel("한글 폴더"), 1) in rows
        assert (_rel("한글 폴더", "보고서.txt"), 2) in rows
        assert (_rel("space 'quote'", "quoted file.txt"), 2) in rows
        assert parsed["truncated"] is False and parsed["has_more"] is False
        # Two levels only: the third-level file is not in a depth-2 answer.
        assert not any(path.endswith(_rel("target.txt")) for path, _ in rows)

        deeper = _rows(_run(_pc_files_command(
            op="list", root=str(root), relative="", depth=3)))
        assert (_rel("sub", "deep", "target.txt"), 3) in deeper

        # Hidden and shortcut folders are listed at their own level...
        assert (shape["hidden"], 1) in rows
        if shape["link_made"]:
            assert (shape["link"], 1) in rows
        # ...but their children are never walked into.
        assert not any(path.startswith(shape["hidden"] + os.sep) for path, _ in rows)
        if shape["link_made"]:
            assert not any(path.startswith(shape["link"] + os.sep) for path, _ in rows)
            assert not any(path.endswith("inside_link.txt") for path, _ in rows)

        searched = _run(_pc_files_command(
            op="list", root=str(root), relative="",
            recursive=True, filter_term="target"))
        assert [_norm(row["relative_path"]) for row in searched["items"]] == [
            _rel("sub", "deep", "target.txt")]
        assert searched["has_more"] is False and searched["truncated"] is False

        korean = _run(_pc_files_command(
            op="list", root=str(root), relative="",
            recursive=True, filter_term="보고서"))
        assert [_norm(row["relative_path"]) for row in korean["items"]] == [
            _rel("한글 폴더", "보고서.txt")]
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(root.parent / (root.name + "_shortcut_target"), ignore_errors=True)


def test_the_deep_walk_stops_at_two_hundred_rows():
    root = Path(tempfile.mkdtemp(prefix="padiem_pc_cap_"))
    try:
        (root / "bulk").mkdir()
        for index in range(205):
            (root / "bulk" / f"file{index:03d}.txt").write_text("x", encoding="utf-8")
        parsed = _run(_pc_files_command(
            op="list", root=str(root), relative="", depth=2))
        assert len(parsed["items"]) == 200
        assert parsed["truncated"] is True
        # A deep walk is one bounded answer, never a first page.
        assert parsed["has_more"] is False
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_recursive_search_stops_at_fifty_rows_and_says_has_more():
    root = Path(tempfile.mkdtemp(prefix="padiem_pc_hits_"))
    try:
        (root / "hits").mkdir()
        for index in range(55):
            (root / "hits" / f"hit{index:02d}.txt").write_text("x", encoding="utf-8")
        parsed = _run(_pc_files_command(
            op="list", root=str(root), relative="",
            recursive=True, filter_term="hit"))
        paths = [_norm(row["relative_path"]) for row in parsed["items"]]
        assert len(paths) == 50
        assert parsed["has_more"] is True and parsed["truncated"] is True
        assert paths[0] == _rel("hits", "hit00.txt")
    finally:
        shutil.rmtree(root, ignore_errors=True)


@pytest.mark.parametrize("term", [
    "q'; Write-Output PWNED; '",
    "semi; Write-Output PWNED",
    "tick`nWrite-Output PWNED",
    "$(Write-Output PWNED)",
])
def test_a_hostile_search_term_is_only_ever_matched_as_text(term):
    root = Path(tempfile.mkdtemp(prefix="padiem_pc_term_"))
    try:
        name = "weird ' " + term.replace("/", "_").replace("\\", "_") + ".txt"
        (root / name).write_text("x", encoding="utf-8")
        (root / "plain.txt").write_text("x", encoding="utf-8")
        parsed = _run(_pc_files_command(
            op="list", root=str(root), relative="",
            recursive=True, filter_term=term))
        rows = parsed["items"]
        # The term is a name fragment: only the file whose name contains it is
        # returned, and no statement of the term ran beside the answer.
        assert [row["Name"] for row in rows] == [name]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_the_scan_stops_at_two_thousand_entries():
    root = Path(tempfile.mkdtemp(prefix="padiem_pc_scan_"))
    try:
        for index in range(2005):
            (root / f"n{index:04d}.txt").write_text("x", encoding="utf-8")
        parsed = _run(_pc_files_command(
            op="list", root=str(root), relative="",
            recursive=True, filter_term="absent"))
        assert parsed["items"] == []
        assert parsed["scan_truncated"] is True
        assert parsed["has_more"] is False
    finally:
        shutil.rmtree(root, ignore_errors=True)
