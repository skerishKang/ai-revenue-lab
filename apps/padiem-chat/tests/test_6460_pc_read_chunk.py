"""#6460-4: the one range-read script and the Chat-side range contract.

The builder is checked here on every platform. The executed script needs
PowerShell, so those cases run on Windows and skip elsewhere.
"""
from __future__ import annotations

import json
import shutil
import sys
import subprocess
from pathlib import Path

import pytest

from app import oracle_mesh_read_return_routes as routes
from app.claw_pc_read_command import (
    PC_READ_CHUNK_MAX_BYTES,
    PC_READ_OFFICE_MEDIA,
    PC_READ_OFFICE_PREFIX_BYTES,
    is_office_name,
    office_media_type,
    pc_read_chunk_command,
    pc_read_length,
    pc_read_offset,
)

POWERSHELL = shutil.which("powershell") or shutil.which("powershell.exe")
ROOT = "C:/Users/limone/Documents/견적"


def test_offsets_and_lengths_are_bounded():
    assert pc_read_offset(0) == 0
    assert pc_read_offset(1 << 30) == 1 << 30
    for bad in (-1, 1.5, True, "0", None, (1 << 40) + 1):
        assert pc_read_offset(bad) is None, bad
    assert pc_read_length(1) == 1
    assert pc_read_length(PC_READ_CHUNK_MAX_BYTES) == PC_READ_CHUNK_MAX_BYTES
    for bad in (0, PC_READ_CHUNK_MAX_BYTES + 1, -5, True, "5", None):
        assert pc_read_length(bad) is None, bad


def test_office_names_are_the_four_existing_formats():
    assert is_office_name("보고서.DOCX")
    assert office_media_type("보고서.docx") == PC_READ_OFFICE_MEDIA[".docx"]
    assert office_media_type("a.xlsx") == PC_READ_OFFICE_MEDIA[".xlsx"]
    assert office_media_type("a.pdf") == PC_READ_OFFICE_MEDIA[".pdf"]
    assert office_media_type("a.hwpx") == PC_READ_OFFICE_MEDIA[".hwpx"]
    assert not is_office_name("notes.txt")
    assert office_media_type("notes.txt") is None


def test_a_text_range_is_a_bounded_utf8_read():
    script = pc_read_chunk_command(
        root=ROOT, relative="큰 문서.txt", offset=1024, length=65536,
    )
    assert "\r" not in script
    assert "$offset=[int64]1024" in script and "$length=[int64]65536" in script
    assert "[IO.File]::OpenRead($path)" in script
    assert "[void]$fs.Seek($offset,[IO.SeekOrigin]::Begin)" in script
    # The cut walks whole UTF-8 sequences; a range never ends inside one.
    assert "($b -band 0xE0) -eq 0xC0" in script
    assert "($buf[$start] -band 0xC0) -eq 0x80" in script
    assert "unit='bytes'" in script
    assert "next_offset=$next" in script and "eof=$eof" in script
    assert "binary_text_rejected" in script


def test_a_document_range_uses_the_existing_parser_and_slices_text():
    script = pc_read_chunk_command(
        root=ROOT, relative="보고서.docx", offset=0, length=500,
    )
    assert "Get-Command python" in script
    assert "-P -m kagent.document_parser_child" in script
    assert "$partial=($size -gt $len)" in script
    assert "$prefix=[int64]" + str(PC_READ_OFFICE_PREFIX_BYTES) in script
    assert "$text.Substring([int]$offset,$take)" in script
    assert "unit='chars'" in script
    # Every document format names its real media type; no new parser exists.
    for name, media in (
        ("a.docx", PC_READ_OFFICE_MEDIA[".docx"]),
        ("a.xlsx", PC_READ_OFFICE_MEDIA[".xlsx"]),
        ("a.pdf", PC_READ_OFFICE_MEDIA[".pdf"]),
        ("a.hwpx", PC_READ_OFFICE_MEDIA[".hwpx"]),
    ):
        built = pc_read_chunk_command(root=ROOT, relative=name, offset=0, length=10)
        assert media in built


def test_paths_and_queries_are_single_quoted_literals():
    script = pc_read_chunk_command(
        root="C:/Users/O'Brien/Documents", relative="it's.txt", offset=0, length=10,
    )
    assert "$path='C:/Users/O''Brien/Documents/it''s.txt'" in script


def test_bad_shapes_are_refused_before_a_command_exists():
    with pytest.raises(ValueError):
        pc_read_chunk_command(root=ROOT, relative="", offset=0, length=10)
    with pytest.raises(ValueError):
        pc_read_chunk_command(root=ROOT, relative="a.txt", offset=-1, length=10)
    with pytest.raises(ValueError):
        pc_read_chunk_command(root=ROOT, relative="a.txt", offset=0, length=0)
    with pytest.raises(ValueError):
        pc_read_chunk_command(
            root=ROOT, relative="a.txt", offset=0, length=PC_READ_CHUNK_MAX_BYTES + 1,
        )
    with pytest.raises(ValueError):
        pc_read_chunk_command(root="", relative="a.txt", offset=0, length=10)


def test_a_range_read_is_the_existing_read_authority():
    assert "read_chunk" in routes._PC_FILES_OPS
    assert routes._pc_files_claim_op("read_chunk", None) == "read"
    assert routes._pc_files_claim_op("read_chunk", "content") == "read"


def _run(script: str, tmp_path: Path) -> dict:
    target = tmp_path / "read.ps1"
    target.write_text(script, encoding="utf-8-sig")
    run = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(target)],
        capture_output=True,
    )
    assert run.returncode == 0, run.stderr.decode("utf-8", "replace")[:400]
    return json.loads(run.stdout.decode("utf-8"))


def _utf8_sample(size: int) -> bytes:
    block = ("가나다라마바사 " * 512).encode("utf-8")
    return (block * (size // len(block) + 1))[:size]


@pytest.mark.skipif(sys.platform != "win32" or not POWERSHELL,
            reason="the range script runs on the PC's own Windows PowerShell")
def test_a_small_file_reads_end_to_end_on_character_boundaries(tmp_path):
    data = ("가" * 20 + "abc" + "나" * 20).encode("utf-8")
    (tmp_path / "sample.txt").write_bytes(data)
    first = _run(pc_read_chunk_command(
        root=str(tmp_path).replace("\\", "/"), relative="sample.txt",
        offset=0, length=10,
    ), tmp_path)
    assert first["ok"] is True and first["unit"] == "bytes"
    assert first["size_bytes"] == len(data)
    # 10 bytes cannot hold a whole Korean character plus one more, so the
    # answer stops at the last complete character and says where it stopped.
    assert first["next_offset"] == len(first["text"].encode("utf-8"))
    assert first["next_offset"] <= 13
    assert first["eof"] is False
    rest = []
    offset = first["next_offset"]
    while not first["eof"] and len(rest) < 20:
        first = _run(pc_read_chunk_command(
            root=str(tmp_path).replace("\\", "/"), relative="sample.txt",
            offset=offset, length=7,
        ), tmp_path)
        rest.append(first["text"])
        offset = first["next_offset"]
    text = None
    assert offset == len(data)


@pytest.mark.skipif(sys.platform != "win32" or not POWERSHELL,
            reason="the range script runs on the PC's own Windows PowerShell")
def test_a_hundred_megabyte_file_reads_head_middle_and_tail(tmp_path):
    path = tmp_path / "huge.txt"
    block = _utf8_sample(1024 * 1024)
    with path.open("wb") as handle:
        for _ in range(100):
            handle.write(block)
    size = path.stat().st_size
    assert size >= 100 * 1024 * 1024
    root = str(tmp_path).replace("\\", "/")

    head = _run(pc_read_chunk_command(
        root=root, relative="huge.txt", offset=0, length=65_536,
    ), tmp_path)
    assert head["ok"] is True and head["size_bytes"] == size
    assert head["offset"] == 0 and head["eof"] is False
    assert 65_536 <= head["next_offset"] <= 65_539
    assert len(head["text"].encode("utf-8")) == head["next_offset"]

    middle = _run(pc_read_chunk_command(
        root=root, relative="huge.txt", offset=size // 2, length=4096,
    ), tmp_path)
    assert middle["ok"] is True and middle["offset"] == size // 2
    # The requested offset can land inside a character; the answer starts at
    # the next whole character and never returns a broken one.
    assert middle["next_offset"] > size // 2
    assert isinstance(middle["text"], str)

    tail = _run(pc_read_chunk_command(
        root=root, relative="huge.txt", offset=size - 1000, length=4096,
    ), tmp_path)
    assert tail["ok"] is True and tail["eof"] is True
    assert tail["next_offset"] == size
