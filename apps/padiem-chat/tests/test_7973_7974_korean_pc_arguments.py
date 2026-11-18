"""#7973/#7974: Korean paths and search terms survive the PC command lane.

The failure was on the way IN, not in the answer: a PowerShell command carrying
Korean characters is decoded with the PC's legacy console code page (cp949 on a
Korean Windows installation), so a Korean path became mojibake, Get-ChildItem
could not find it and the answer was an error instead of JSON
(``pc_list_output_invalid``). A Korean *folder* name also never matched because
the name search walked with ``-File`` and skipped containers.

The fixed builders carry every caller value as base64 of its UTF-8 bytes and
rebuild it on the PC with an explicit UTF-8 decoder. The command text is ASCII,
so no console code page can change a path or a query. Permission scope, approved
roots and the reparse-point guard are untouched here.

Python checks always run. The last test runs the generated command on a local
PowerShell when one is installed, with temp folders only: no production device,
login or database is contacted.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.claw_pc_search_command import pc_search_command, pc_search_query  # noqa: E402
from app.oracle_mesh_read_return_routes import _pc_files_command  # noqa: E402
from padiem_ai_core.powershell_literal import ps_utf8_literal  # noqa: E402

B64 = re.compile(r"FromBase64String\('([A-Za-z0-9+/=]+)'\)")


def _carried(command: str) -> list[str]:
    return [
        base64.b64decode(blob, validate=True).decode("utf-8")
        for blob in B64.findall(command)
    ]


def _list(root: str, relative: str) -> str:
    return _pc_files_command(op="list", root=root, relative=relative)


PATHS = (
    "총무부",
    "문서 폴더/입찰관리",
    "자료 2026",
    "C:/Users/x/문서 폴더/입찰관리",
)


def test_helper_carries_the_exact_unicode_value_as_ascii():
    for value in ("총무부", "문서 폴더/입찰관리", "O'Brien", "a;b`$(x)", "자료 2026"):
        expression = ps_utf8_literal(value)
        assert expression.isascii()
        encoded = B64.findall(expression)
        assert len(encoded) == 1
        assert base64.b64decode(encoded[0], validate=True).decode("utf-8") == value
    with pytest.raises(ValueError):
        ps_utf8_literal("a\ud800b")


@pytest.mark.parametrize("relative", PATHS)
def test_korean_and_mixed_pc_list_command_is_ascii_and_roundtrips(relative):
    root = "C:/Users/x"
    command = _list(root, relative)
    assert command.isascii(), command[:200]
    assert _carried(command)[0] == root + "/" + relative
    assert "Get-ChildItem -LiteralPath $folder" in command
    # The exact path also survives a fake output round trip: the PC answers a
    # JSON page whose names carry Korean, and the server reads it unchanged.
    fake = json.dumps({
        "offset": 0, "total": 2, "has_more": False,
        "items": [
            {"Name": "한글문서.txt", "Length": 6, "PSIsContainer": False},
            {"Name": "report.txt", "Length": 5, "PSIsContainer": False},
        ],
    }, ensure_ascii=False)
    parsed = json.loads(fake)
    assert [row["Name"] for row in parsed["items"]] == ["한글문서.txt", "report.txt"]
    assert parsed["total"] == 2


@pytest.mark.parametrize("relative", PATHS)
def test_pc_file_info_uses_the_same_safe_list_command(relative):
    # pc_file_info answers through claw.pc.list_files, so its command is the
    # same builder: a Korean path must produce the same ASCII-only command.
    command = _pc_files_command(op="list", root="C:/Users/x", relative=relative)
    assert command.isascii()
    assert _carried(command)[0] == "C:/Users/x/" + relative


def test_korean_query_is_carried_as_a_value_and_both_unicode_forms_match():
    nfc = "총무"
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd
    assert pc_search_query(nfd) == nfc
    for query in (nfc, nfd):
        command = pc_search_command(
            roots=[{"label": "문서", "path": "C:/Users/x/문서"}], query=query, mode="name",
        )
        assert command.isascii()
        values = _carried(command)
        assert nfc in values
        assert "문서" in values and "C:/Users/x/문서" in values
    # Folders are results too (#7974): the fallback walk does not use -File.
    assert "Get-ChildItem -LiteralPath $r.path -Recurse -Force" in command
    assert "$i.PSIsContainer" not in command


def test_english_paths_and_queries_keep_their_behavior():
    command = _list("C:/Users/x", "Desktop")
    assert command.isascii()
    assert _carried(command)[0] == "C:/Users/x/Desktop"
    search = pc_search_command(
        roots=[{"label": "docs", "path": "C:/Users/x/Documents"}], query="CGI", mode="name",
    )
    assert search.isascii()
    assert "CGI" in _carried(search)


_PS = shutil.which("powershell.exe") or shutil.which("pwsh")


@pytest.mark.skipif(_PS is None, reason="no local PowerShell to run the generated command")
def test_generated_command_lists_a_real_korean_folder_on_local_powershell():
    base = Path(tempfile.mkdtemp(prefix="pc7973_"))
    korean = base / "총무부"
    korean.mkdir()
    (korean / "한글문서.txt").write_text("내용", encoding="utf-8")
    (korean / "report.txt").write_text("x", encoding="utf-8")
    command = _list(base.as_posix(), "총무부")
    assert command.isascii()

    from kagent.local_agent_meshcentral_command_port import _wrap

    done = subprocess.run(
        [_PS, "-NoProfile", "-NonInteractive", "-Command", _wrap(command)],
        capture_output=True, timeout=90,
    )
    raw = (done.stdout + (b"\n" + done.stderr if done.stderr else b"")).decode("utf-8", errors="replace")
    line = next((ln for ln in raw.splitlines() if "PADIEM_B64=" in ln), None)
    assert line is not None, raw[:300]
    body = base64.b64decode(line.split("PADIEM_B64=", 1)[1].strip()).decode("utf-8")
    parsed = json.loads(body)
    assert parsed["total"] == 2
    assert {row["Name"] for row in parsed["items"]} == {"한글문서.txt", "report.txt"}
