"""#5994 D3 후속 — PC 읽기(청크)가 정션/링크를 따라 허용 폴더 밖을 읽지 못한다.

실제 PowerShell로 샌드박스의 실제 정션을 통과하려는 청크 읽기를 실행해
{"ok":false,"error":"link_refused"} 로 거부되고 바깥 내용이 그대로인지
파일시스템 증거로 고정한다. 일반(정션 없는) 읽기 회귀도 함께.
"""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from app.claw_pc_read_command import pc_read_chunk_command

SANDBOX = Path(r"E:\pc-write-sandbox-261102")
WORK = SANDBOX / "read-work"
OUTSIDE = SANDBOX / "read-outside-sim"

# The fixtures are real Windows junctions driven by real PowerShell: the Linux
# runner has no powershell/cmd, so the machine-level tests run on Windows only.
pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                reason="real Windows junction + PowerShell run")

POWERSHELL = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]


def run_ps(script: str, timeout: int = 120) -> dict:
    # 청크 읽기 레인은 임시 .ps1을 -File 로 실행한다(다중 줄·return 계약).
    # 임시 파일도 지정 샌드박스 안에만 만든다.
    path = SANDBOX / f"read-{uuid.uuid4().hex}.ps1"
    path.write_text(script, encoding="utf-8-sig")
    try:
        raw = subprocess.run(POWERSHELL + [str(path)], capture_output=True,
                             timeout=timeout)
    finally:
        path.unlink(missing_ok=True)
    text = raw.stdout.decode("utf-8", errors="replace").strip()
    assert text, f"empty answer: rc={raw.returncode} err={raw.stderr[:200]!r}"
    # 첫 비어있지 않은 JSON 줄을 답으로 파싱한다(가드 거부는 단일 문서다).
    return json.loads(text)


def _junction(link: Path, target: Path) -> bool:
    if link.exists() or link.is_symlink():
        subprocess.run(["cmd", "/c", "rmdir", str(link)], capture_output=True)
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                            capture_output=True)
    return result.returncode == 0


@pytest.fixture(scope="module", autouse=True)
def sandbox():
    WORK.mkdir(parents=True, exist_ok=True)
    OUTSIDE.mkdir(parents=True, exist_ok=True)
    (OUTSIDE / "밖비밀문서.txt").write_text("허용 폴더 밖의 내용 — 읽히면 유출", encoding="utf-8")
    yield
    # 통제된 증거는 남긴다: 정션과 바깥 시뮬 폴더는 시험 산출물이다.


def _chunk(root: Path, relative: str) -> dict:
    script = pc_read_chunk_command(root=str(root), relative=relative,
                                   offset=0, length=1000)
    return run_ps(script)


def test_junction_read_is_refused_and_outside_content_never_travels():
    (WORK / "ok.txt").write_text("루트 안 정상 파일", encoding="utf-8")
    link = WORK / "link"
    assert _junction(link, OUTSIDE) is True
    try:
        answer = _chunk(WORK, "link/밖비밀문서.txt")
        assert answer.get("ok") is False
        assert answer.get("error") == "link_refused"
        assert "바로가기 폴더" in answer.get("message", "")
        assert "허용 폴더 밖의 내용" not in json.dumps(answer, ensure_ascii=False)
    finally:
        subprocess.run(["cmd", "/c", "rmdir", str(link)], capture_output=True)


def test_mid_folder_junction_deep_read_is_refused():
    mid = WORK / "mid"
    assert _junction(mid, OUTSIDE) is True
    (OUTSIDE / "deep").mkdir(exist_ok=True)
    (OUTSIDE / "deep" / "밖비밀문서.txt").write_text(
        "정션 깊숙이 있는 밖 문서", encoding="utf-8")
    try:
        answer = _chunk(WORK, "mid/deep/밖비밀문서.txt")
        assert answer.get("ok") is False
        assert answer.get("error") == "link_refused"
    finally:
        subprocess.run(["cmd", "/c", "rmdir", str(mid)], capture_output=True)


def test_normal_read_inside_the_root_still_works():
    (WORK / "정상문서.txt").write_text("루트 안 정상 문서 내용", encoding="utf-8")
    answer = _chunk(WORK, "정상문서.txt")
    assert answer.get("ok") is True
    assert answer["text"] == "루트 안 정상 문서 내용"


def test_missing_file_error_unchanged():
    answer = _chunk(WORK, "없는파일.txt")
    assert answer.get("ok") is False
    assert answer.get("error") == "not_a_file"


def test_symbolic_link_read_is_refused_when_creatable():
    sym = WORK / "symlink"
    result = subprocess.run(["cmd", "/c", "mklink", "/D", str(sym), str(OUTSIDE)],
                            capture_output=True)
    if result.returncode != 0:
        pytest.skip("symbolic link creation requires admin or developer mode")
    try:
        answer = _chunk(WORK, "symlink/밖비밀문서.txt")
        assert answer.get("ok") is False
        assert answer.get("error") == "link_refused"
    finally:
        subprocess.run(["cmd", "/c", "rmdir", str(sym)], capture_output=True)
