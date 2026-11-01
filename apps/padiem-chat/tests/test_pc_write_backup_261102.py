"""#5994/#6460 PC 쓰기·이동·삭제 + 쓰기 전 백업 — 컴1 로컬 실사용 실측.

서버가 만든 **실제 명령 바이트**(_pc_write_command)를 PC 에이전트와 같은 호출
(``powershell -NoProfile -NonInteractive -nologo -command -`` 표준 입력)로
E:\\pc-write-sandbox-261102\\work 안에서 실행한다. 실제 파일시스템 효과(백업
생성·내용·이름·복구)가 이 시험의 본체다. 페어링·디스패치 스테이징은 기존 레인
시험이 고정하고, 이 파일은 명령 실행 계층의 파일시스템 계약을 고정한다.

- 백업 위치: <루트 드라이브>:\\.padiem-backup\\<YYYY-MM-DD>\\<스탬프>-<relative 정화>
  (PC_BACKUP_FOLDER — 같은 드라이브의 숨은 폴더. 이 폴더가 생기는 것 자체가
  #5994의 설계이며, 시험 후에도 증거로 남겨 둔다.)
- 지우지 않는 것: 샌드박스와 .padiem-backup 증거. 지운 것: 시험 주입물(실패 주입용
  파일, 정션)만.
"""
from __future__ import annotations

import base64
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.oracle_mesh_read_return_routes import (
    PC_BACKUP_FOLDER,
    PC_WRITE_ACCOUNT_PREFIX,
    _pc_backup_dir,
    _pc_files_relative_path,
    _pc_write_command,
)

SANDBOX = Path(r"E:\pc-write-sandbox-261102")
ROOT = SANDBOX / "work"
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
BACKUP_DIR = _pc_backup_dir(str(ROOT) + "\\", TODAY)
POWERSHELL = ["powershell", "-NoProfile", "-NonInteractive", "-nologo", "-command", "-"]


def run_pc(command: str, timeout: int = 240) -> dict:
    """PC 에이전트와 같은 호출: 한 줄 명령을 stdin으로 PowerShell 5.1에 흘인니다."""
    raw = subprocess.run(POWERSHELL, input=command.encode("utf-8"),
                         capture_output=True, timeout=timeout)
    text = raw.stdout.decode("utf-8", errors="replace")
    lines = [line for line in text.splitlines()
             if line.startswith(PC_WRITE_ACCOUNT_PREFIX)]
    assert lines, f"account line missing: rc={raw.returncode} out={text[:300]!r}"
    return json.loads(base64.b64decode(lines[-1][len(PC_WRITE_ACCOUNT_PREFIX):]))


def write_command(root: Path, relative: str, content: bytes) -> str:
    return _pc_write_command(
        op="write", target=str(root / relative), relative=relative,
        backup_dir=_pc_backup_dir(str(root) + "\\", TODAY),
        content_b64=base64.b64encode(content).decode("ascii"),
    )


def backups_for(relative: str) -> list[Path]:
    sanitized = re_sub(relative)
    folder = Path(BACKUP_DIR)
    return sorted(folder.glob("*-" + sanitized)) if folder.exists() else []


def re_sub(relative: str) -> str:
    import re
    return re.sub(r"[^\w.-]", "_", relative)


@pytest.fixture(scope="module", autouse=True)
def sandbox():
    ROOT.mkdir(parents=True, exist_ok=True)
    yield


# ── 쓰기 ────────────────────────────────────────────────────────────────────


def test_write_new_file_creates_bytes_without_backup():
    target = ROOT / "새파일.txt"
    target.unlink(missing_ok=True)  # 재실행: 이전 실행의 파일이 있으면 덮어쓰기가 된다
    content = "새 내용 — PADIEM".encode("utf-8")
    account = run_pc(write_command(ROOT, "새파일.txt", content))
    assert account["ok"] is True and account["op"] == "write"
    assert account["backup"] is None            # 새 파일은 백업이 없다
    assert account["bytes"] == len(content)
    assert account["verification"]["target_sha256"] == __import__("hashlib").sha256(
        content).hexdigest()
    assert target.read_bytes() == content


def test_overwrite_backs_up_the_original_first():
    target = ROOT / "덮어쓰기.txt"
    original = "원본 내용 v1 — 복구 근거".encode("utf-8")
    target.write_bytes(original)
    updated = "덮어쓴 내용 v2".encode("utf-8")

    account = run_pc(write_command(ROOT, "덮어쓰기.txt", updated))
    assert account["ok"] is True
    assert account["verification"]["backup_exists"] is True
    backup = Path(account["backup"])
    # 백업은 같은 드라이브의 숨은 폴더, 날짜 폴더 아래 스탬프+정화된 이름으로 생긴다.
    assert backup.is_relative_to(Path("E:\\") / PC_BACKUP_FOLDER)
    assert backup.parent == Path(BACKUP_DIR)
    assert backup.read_bytes() == original      # 백업 내용 == 원본
    assert target.read_bytes() == updated       # 본문은 새 내용


def test_failed_backup_stops_the_change():
    target = ROOT / "백업실패.txt"
    original = "바뀌면 안 되는 원본".encode("utf-8")
    target.write_bytes(original)
    # 백업 폴더 자리를 파일로 미리 점거해 New-Item(Directory)을 실패시킨다.
    # 공용 .padiem-backup을 만지지 않도록 주입 위치도 샌드박스 안으로 둔다.
    blocker = SANDBOX / "backup-blocker-file"
    blocker.write_bytes(b"not a directory")
    command = _pc_write_command(
        op="write", target=str(target), relative="백업실패.txt",
        backup_dir=str(blocker),
        content_b64=base64.b64encode("새 내용".encode("utf-8")).decode("ascii"),
    )
    try:
        account = run_pc(command)
        assert account["ok"] is False
        assert account["reason"] == "backup_failed"
        assert account["backup"] is None
        assert target.read_bytes() == original  # 아무것도 바뀌지 않았다
    finally:
        blocker.unlink(missing_ok=True)


# ── 이동·이름 바꾸기 ────────────────────────────────────────────────────────


def _move_command(root: Path, relative: str, destination: str) -> str:
    return _pc_write_command(
        op="move", target=str(root / relative), relative=relative,
        backup_dir=_pc_backup_dir(str(root) + "\\", TODAY),
        destination=str(root / destination),
    )


def test_move_renames_and_backs_up_the_source():
    source = ROOT / "이동전.txt"
    source.write_bytes("이동되는 파일".encode("utf-8"))
    account = run_pc(_move_command(ROOT, "이동전.txt", "이동후.txt"))
    assert account["ok"] is True
    assert not source.exists()
    assert (ROOT / "이동후.txt").read_bytes() == "이동되는 파일".encode("utf-8")
    assert Path(account["backup"]).read_bytes() == "이동되는 파일".encode("utf-8")


def test_move_onto_existing_destination_backs_up_the_destination():
    source = ROOT / "원본위치.txt"
    source.write_bytes("이동하는 내용".encode("utf-8"))
    destination = ROOT / "덮어쓰이는 위치.txt"
    destination.write_bytes("사라질 기존 내용".encode("utf-8"))
    account = run_pc(_move_command(ROOT, "원본위치.txt", "덮어쓰이는 위치.txt"))
    assert account["ok"] is True
    backup = Path(account["backup"])
    assert backup.read_bytes() == "사라질 기존 내용".encode("utf-8")  # 덮인 쪽 백업
    assert (ROOT / "덮어쓰이는 위치.txt").read_bytes() == "이동하는 내용".encode("utf-8")


# ── 삭제: 휴지통 역할 백업 ──────────────────────────────────────────────────


def test_delete_backs_up_then_removes_and_is_restorable():
    target = ROOT / "삭제되는 파일.txt"
    content = "삭제해도 백업으로 돌아올 수 있는 내용".encode("utf-8")
    target.write_bytes(content)
    account = run_pc(_pc_write_command(
        op="delete", target=str(target), relative="삭제되는 파일.txt",
        backup_dir=_pc_backup_dir(str(ROOT) + "\\", TODAY)))
    assert account["ok"] is True
    assert account["verification"]["source_exists"] is False   # 원본 자리는 비었다
    backup = Path(account["backup"])
    assert backup.is_file() and backup.read_bytes() == content
    restored = ROOT / "복구된 파일.txt"
    restored.write_bytes(backup.read_bytes())                  # 되돌리기 = 백업 복사
    assert restored.read_bytes() == content


# ── 경계 ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("value", [
    "../샌드박스밖.txt", "../../샌드박스밖.txt", "sub/../../../밖.txt",
    "C:/Windows/win.ini", "C:\\Windows\\win.ini", "/Windows/win.ini",
    "link/x.txt",
])
def test_server_boundary_refuses_paths_outside_the_grant(value):
    """서버 경계: ..·절대경로·드라이브 접두는 거부. 링크는 문자층에서는 상대로
    보이므로 링크 자체의 집행 차단은 아래 정션 시험(xfail)이 다룬다."""
    if value == "link/x.txt":
        assert _pc_files_relative_path(value) == "link/x.txt"  # 문자층 통과 → 집행 차단 필요
        return
    assert _pc_files_relative_path(value) is None


def test_8_3_and_case_variants_stay_inside_the_grant():
    # 8.3 짧은 이름과 대소문자 변형은 루트 밖으로 나가는 수단이 아니다 —
    # 상대 경로로 남으며(루트 안), 실제 쓰기도 루트 안에서 일어난다.
    assert _pc_files_relative_path("워크~1/파일.txt") == "워크~1/파일.txt"
    short = ROOT / "WORK" / "case.txt"
    short.parent.mkdir(parents=True, exist_ok=True)
    command = write_command(ROOT, "work/../work/CASE.txt", "case".encode("utf-8"))
    # work/../work 는 '..' 세그먼트라 서버 경계에서 None으로 거부된다
    # (명령 자체가 만들어지지 않는다).
    assert _pc_files_relative_path("work/../work/CASE.txt") is None
    account = run_pc(write_command(ROOT, "WORK/case.txt", "case".encode("utf-8")))
    assert account["ok"] is True
    assert short.read_bytes() == b"case"  # 대소문자 변형은 같은 루트 안


@pytest.mark.xfail(reason=(
    "결함 D3(중간): 허용 루트 안의 정션/링크를 통한 루트 밖 쓰기가 차단되지 않는다 — "
    "서버 경계(_pc_files_relative_path)는 문자층이라 정션을 모르고, _pc_write_command "
    "(app/oracle_mesh_read_return_routes.py:3698)의 집행문에도 링크(reparse point) "
    "검사가 없어 Copy-Item/Move-Item이 대상을 따라간다. 재현: 루트 안 정션을 만들고 "
    "link/escape.txt 쓰기 → 허용 루트 밖(대상 폴더)에 파일이 생긴다. 수정은 CTO 배정"
    " (명령에 LinkType 검사 추가 또는 PC 자식 검증)."
), strict=True)
def test_junction_escape_is_refused_by_the_command():
    """정션으로 허용 루트 밖에 쓰기 — 결함 D3(중간) xfail 관측.

    서버 경계는 문자층이라 정션을 모르고, 명령도 링크 검사 없이 Copy/Move를
    집행한다. 정션 대상은 샌드박스 안의 통제된 폴더로 두어 실제 밖 파일을 만들지
    않는다. 수정은 CTO 배정(명령에 링크 검사 추가 또는 PC 자식 검증).
    """
    outside = SANDBOX / "outside-sim"
    outside.mkdir(exist_ok=True)
    link = ROOT / "link"
    if not link.exists():
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                       capture_output=True, check=True)
    escaped = link / "escape.txt"
    try:
        account = run_pc(write_command(ROOT, "link/escape.txt", "탈출".encode("utf-8")))
        assert account["ok"] is False            # 결함: 현재는 True로 통과한다
        assert escaped.exists() is False
    finally:
        if escaped.exists():
            escaped.unlink()
        if link.exists():
            link.rmtree = None
            subprocess.run(["cmd", "/c", "rmdir", str(link)], capture_output=True)


# ── 크기 ────────────────────────────────────────────────────────────────────


def test_large_overwrite_backs_up_and_times():
    """수백 MB 덮어쓰기: 백업 + 새 내용이 모두 검증되고 시간을 기록한다."""
    import hashlib
    original = bytes(n % 251 for n in range(200 * 1024 * 1024))
    target = ROOT / "큰파일.bin"
    target.write_bytes(original)
    updated = bytes((n * 7) % 251 for n in range(200 * 1024 * 1024))
    started = time.monotonic()
    account = run_pc(write_command(ROOT, "큰파일.bin", updated), timeout=600)
    elapsed = time.monotonic() - started
    assert account["ok"] is True
    assert account["bytes"] == len(updated)
    backup = Path(account["backup"])
    assert backup.stat().st_size == len(original)
    digest = hashlib.sha256()
    with backup.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    assert digest.hexdigest() == hashlib.sha256(original).hexdigest()
    assert target.stat().st_size == len(updated)
    print(f"large overwrite 200MB: {elapsed:.1f}s (backup+write)")
