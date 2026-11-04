"""261105: the listing command must send a readable time, not `/Date(...)/`.

PowerShell's ConvertTo-Json serializes a DateTime as `/Date(1793821590883)/`,
which reached the MCP caller verbatim. The command now formats the same instant
as ISO-8601 UTC, so the field means the same thing on the wire and in the answer.
"""
from __future__ import annotations

from app.oracle_mesh_read_return_routes import _pc_files_command


def test_a_listing_command_writes_an_iso_modified_time():
    command = _pc_files_command(op="list", root="C:\\", relative="", page_size=50)

    assert "ToString('o')" in command
    assert "Modified" in command
    # The DateTime-shaped column that serialized as /Date(...)/ is gone.
    assert "LastWriteTimeUtc, PSIsContainer" not in command


def test_the_page_still_carries_its_total_and_more_flag():
    command = _pc_files_command(op="list", root="C:\\", relative="", page_size=50)

    assert "@{offset=" in command and "total=$n" in command
    assert "has_more=" in command
    assert "-Skip 0 -First 50" in command
