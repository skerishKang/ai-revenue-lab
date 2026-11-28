"""#8953 3a — real isolated PowerShell text line paging and interface limits."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.claw_pc_read_command import (
    pc_read_chunk_command, PC_READ_CHUNK_MAX_BYTES,
)
from app.claw_pc_line_read import PC_READ_LINE_MAX_BYTES, PC_READ_LINE_MAX_COUNT

POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")


def _page(tmp_path: Path, content: bytes, start: int, count: int) -> dict:
    file = tmp_path / "sample.txt"
    file.write_bytes(content)
    script = pc_read_chunk_command(
        root=tmp_path.as_posix(), relative="sample.txt",
        start_line=start, line_count=count,
    )
    assert "ReparsePoint" in script
    script_file = tmp_path / "read-lines.ps1"
    script_file.write_text(script, encoding="utf-8-sig")
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(script_file)],
        capture_output=True, timeout=90, check=True,
    )
    lines = result.stdout.decode("utf-8-sig").strip().splitlines()
    assert len(lines) == 1, (lines[-3:], result.stderr[:400])
    assert len(lines[0].encode("utf-8")) <= PC_READ_LINE_MAX_BYTES
    return json.loads(lines[0])


def test_line_bounds_and_existing_byte_mode_are_mutually_exclusive():
    assert PC_READ_LINE_MAX_COUNT == 1000
    assert PC_READ_LINE_MAX_BYTES == 256 * 1024
    assert PC_READ_CHUNK_MAX_BYTES == 1_000_000
    args = dict(root="C:/trial", relative="a.txt")
    for bad in ((0, 1), (1, 0), (1, 1001), (True, 1), (1, 1.2)):
        with pytest.raises(ValueError):
            pc_read_chunk_command(**args, start_line=bad[0], line_count=bad[1])
    with pytest.raises(ValueError):
        pc_read_chunk_command(**args, start_line=2, line_count=4, offset=0, length=10)
    with pytest.raises(ValueError):
        pc_read_chunk_command(root="C:/trial", relative="a.xlsx", start_line=1, line_count=1)
    original = pc_read_chunk_command(**args, offset=0, length=4096)
    assert "$offset=[int64]0" in original
    assert "$length=[int64]4096" in original
    assert "IO.StreamReader" not in original


@pytest.mark.skipif(not POWERSHELL, reason="Windows PowerShell required")
@pytest.mark.parametrize("newline,bom", [
    (b"\n", b""), (b"\r\n", b""), (b"\n", b"\xef\xbb\xbf"),
    (b"\r\n", b"\xef\xbb\xbf"),
])
def test_korean_utf8_bom_crlf_lf_and_one_based_line_cursor(tmp_path, newline, bom):
    original = bom + newline.join(f"행{i:03d} 가나다".encode() for i in range(1, 301)) + newline
    output = _page(tmp_path, original, 100, 50)
    assert output["ok"] is True, output
    assert output["unit"] == "lines"
    assert output["start_line"] == 100
    assert output["line_count"] == 50
    assert output["text"].split("\n") == [f"행{i:03d} 가나다" for i in range(100, 150)]
    assert output["next_cursor"] == 150
    assert output["has_more"] is True and output["truncated"] is True
    assert output["truncation_reason"] == "line_count_limit"
    assert output["source_complete"] is True and output["eof"] is False
    assert (tmp_path/"sample.txt").read_bytes() == original
    last = _page(tmp_path, original, 299, 50)
    assert last["text"].split("\n") == ["행299 가나다", "행300 가나다"]
    assert last["has_more"] is False and last["eof"] is True
    assert last["next_cursor"] is None and last["truncation_reason"] is None


@pytest.mark.skipif(not POWERSHELL, reason="Windows PowerShell required")
def test_one_thousand_lines_and_response_byte_bound(tmp_path):
    rows = [f"행{i:04d} 가나다" for i in range(1, 1003)]
    output = _page(tmp_path, "\n".join(rows).encode(), 1, 1000)
    assert output["line_count"] == 1000
    assert output["truncation_reason"] == "line_count_limit"
    assert output["next_cursor"] == 1001
    # Individual lines fit, but the requested page exceeds the 256 KiB JSON
    # limit. Do not drop a line without a usable continuation cursor.
    text = "\n".join(["가" * 30000] * 8).encode()
    output = _page(tmp_path, text, 1, 8)
    assert output["truncated"] is True and output["has_more"] is True
    assert output["truncation_reason"] == "response_bytes_limit"
    assert 1 <= output["line_count"] < 8
    assert output["next_cursor"] == 1 + output["line_count"]
    assert len(output["text"].encode()) <= PC_READ_LINE_MAX_BYTES
    giant = _page(tmp_path, ("가"*110000).encode(), 1, 1)
    assert giant == {"ok":False, "error":"line_too_large"}


@pytest.mark.skipif(not POWERSHELL, reason="Windows PowerShell required")
def test_mixed_newlines_and_empty_end(tmp_path):
    data = "첫째\r\n둘째\n셋째\r\n넷째".encode()
    row = _page(tmp_path, data, 2, 2)
    assert row["text"] == "둘째\n셋째"
    assert row["next_cursor"] == 4
    after = _page(tmp_path, data, 5, 10)
    assert after["text"] == "" and after["line_count"] == 0
    assert after["eof"] is True and after["truncated"] is False


@pytest.mark.skipif(not POWERSHELL, reason="Windows PowerShell required")
def test_large_100mb_file_only_returns_one_bounded_page(tmp_path):
    file = tmp_path/"sample.txt"
    row = b"a"*9999 + b"\n"
    with file.open("wb") as f:
        for _ in range(10_000):
            f.write(row)
    assert file.stat().st_size == 100_000_000
    script = pc_read_chunk_command(
        root=tmp_path.as_posix(),relative="sample.txt",start_line=100,line_count=3,
    )
    ps=tmp_path/"read-lines.ps1"
    ps.write_text(script,encoding="utf-8-sig")
    result=subprocess.run([POWERSHELL,"-NoProfile","-NonInteractive",
        "-ExecutionPolicy","Bypass","-File",str(ps)],
        capture_output=True,timeout=90,check=True)
    page=json.loads(result.stdout.decode("utf-8-sig"))
    assert page["line_count"] == 3 and page["next_cursor"] == 103
    assert len(page["text"].encode()) < 256*1024
    assert page["has_more"] is True
