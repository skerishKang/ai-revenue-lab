"""R7-2 _pc_write_command 단계 나누기 증거 시험 (#7814).

리팩터 전후 동일을 고정한다: 대표 입력마다 만든 PowerShell 명령 한 줄,
그 안에 남는 이유 코드와 단계 순서. 골든 표는 리팩터 전 origin/main (d3b00707)의 명령을 기준으로 한다.
#8953 2/5에서는 승인된 edit 동작 두 사례만 새 바이트·이유 코드로
갱신했다. 그 밖의 write/move/delete/mkdir 6행은 이전 바이트 그대로이며,
의도치 않게 바뀌면 이 시험이 실패한다.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

from app.oracle_mesh_read_return_routes import _pc_write_command

GOLDEN_PATH = Path(__file__).resolve().parent / "test_7814_pc_write_command_table_golden.json"

BS = chr(92)
ROOT = "C:" + BS + "work" + BS
BACKUP_DIR = "C:" + BS + "pc-backup" + BS + "2026-11-17"


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


CASES = [
    (
        "정상_쓰기",
        {
            "op": "write",
            "root": ROOT,
            "target": "C:" + BS + "work" + BS + "a.txt",
            "backup_dir": BACKUP_DIR,
            "relative": "a.txt",
            "content_b64": _b64("hello"),
        },
    ),
    (
        "범위_밖_쓰기",
        {
            "op": "write",
            "root": ROOT,
            "target": "C:" + BS + "outside" + BS + "a.txt",
            "backup_dir": BACKUP_DIR,
            "relative": "a.txt",
            "content_b64": _b64("hello"),
        },
    ),
    (
        "편집_한_곳",
        {
            "op": "edit",
            "root": ROOT,
            "target": "C:" + BS + "work" + BS + "a.txt",
            "backup_dir": BACKUP_DIR,
            "relative": "a.txt",
            "old_text_b64": _b64("old"),
            "new_text_b64": _b64("new"),
        },
    ),
    (
        "편집_전체",
        {
            "op": "edit",
            "root": ROOT,
            "target": "C:" + BS + "work" + BS + "a.txt",
            "backup_dir": BACKUP_DIR,
            "relative": "a.txt",
            "old_text_b64": _b64("old"),
            "new_text_b64": _b64("new"),
            "replace_all": True,
        },
    ),
    (
        "덧붙이기_쓰기",
        {
            "op": "write",
            "root": ROOT,
            "target": "C:" + BS + "work" + BS + "a.txt",
            "backup_dir": BACKUP_DIR,
            "relative": "a.txt",
            "content_b64": _b64("tail"),
            "append": True,
        },
    ),
    (
        "이동",
        {
            "op": "move",
            "root": ROOT,
            "target": "C:" + BS + "work" + BS + "a.txt",
            "backup_dir": BACKUP_DIR,
            "relative": "a.txt",
            "destination": "C:" + BS + "work" + BS + "b.txt",
        },
    ),
    (
        "삭제",
        {
            "op": "delete",
            "root": ROOT,
            "target": "C:" + BS + "work" + BS + "a.txt",
            "backup_dir": BACKUP_DIR,
            "relative": "a.txt",
        },
    ),
    (
        "폴더_만들기",
        {
            "op": "mkdir",
            "root": ROOT,
            "target": "C:" + BS + "work" + BS + "new",
            "backup_dir": BACKUP_DIR,
            "relative": "new",
        },
    ),
]

_STAGE_MARKERS = [
    ("initial", ("$ErrorActionPreference = 'Stop'",)),
    ("payload", ("$payload = [Convert]::FromBase64String",)),
    ("guard", ("$guardRoot =",)),
    ("backup", ("$backup = Join-Path $backupDir",)),
    (
        "operation",
        (
            "[IO.File]::WriteAllBytes",
            "Move-Item -LiteralPath $target -Destination $destination -Force",
            "Remove-Item -LiteralPath $target -Force",
            "New-Item -ItemType Directory -Force -Path $target",
        ),
    ),
    ("verification", ("$verification = [ordered]@{version=1; status='observed'",)),
    ("account", ("Write-Output ('PADIEM_PC_ACCOUNT='",)),
]

_REASON = re.compile(r"\$reason = '([^']+)'")


def _table_row(name: str, command: str) -> dict:
    found = []
    for stage, markers in _STAGE_MARKERS:
        positions = [command.find(marker) for marker in markers]
        positions = [at for at in positions if at != -1]
        if positions:
            found.append((min(positions), stage))
    lowered = command.lower()
    return {
        "case": name,
        "sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
        "reasons": _REASON.findall(command),
        "stages": [stage for _, stage in sorted(found)],
        "one_line": "\n" not in command and "\r" not in command,
        "account_count": command.count("Write-Output ('PADIEM_PC_ACCOUNT='"),
        "has_confirmation_prompt": any(
            prompt in lowered
            for prompt in ("read-host", "shouldcontinue", "-whatif")
        ),
    }


def test_pc_write_command_table_is_identical_to_golden() -> None:
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    rows = [_table_row(name, _pc_write_command(**kwargs)) for name, kwargs in CASES]
    assert rows == golden
