"""#8359 후속3 — 갱신 스크립트의 원자적 교체를 실제 PowerShell에서 확인한다.

``[IO.File]::Replace``는 대상 옆 백업 파일이 필요하고 대상이 잠기거나 읽기
전용이면 실패한다. 같은 폴더에 임시 파일을 쓰고 해시를 확인한 뒤 Move-Item으로
덮어쓰는 경로로 바꾼다. 등록·스케줄러는 건드리지 않고 임시 폴더에서만 실행한다.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys

import pytest

from app.pc_helper_update import _UPDATE_SCRIPT

_SHELL = shutil.which("powershell") or shutil.which("pwsh")
pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or not _SHELL,
    reason="Windows ACL and Move-Item semantics require Windows PowerShell")


def _functions() -> str:
    start = _UPDATE_SCRIPT.index("function Get-UpdateDigest")
    end = _UPDATE_SCRIPT.index("function Write-AtomicJson")
    return _UPDATE_SCRIPT[start:end]


def _run(script: str):
    # 로컬 PowerShell의 오류 문구가 Windows 코드페이지로 나올 수 있다.
    return subprocess.run([_SHELL, "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=60)


def _ps(path) -> str:
    return str(path).replace("'", "''")


def test_move_atomic_replaces_target_and_keeps_acl(tmp_path):
    target = tmp_path / "update.ps1"
    source = tmp_path / "candidate.exe"
    target.write_text("old", encoding="utf-8")
    source.write_text("new", encoding="utf-8")
    digest = hashlib.sha256(b"new").hexdigest()
    script = ("$ErrorActionPreference='Stop'\n" + _functions() + "\n"
              + "$before = Get-UpdateAcl '" + _ps(target) + "'\n"
              + "Move-Atomic -source '" + _ps(source) + "' -target '" + _ps(target)
              + "' -expectedHash '" + digest + "'\n"
              + "if (-not (Test-UpdateAcl '" + _ps(target) + "' $before)) { throw 'acl_changed' }\n"
              + "'acl-ok'\n")
    out = _run(script)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().endswith("acl-ok")
    assert target.read_text(encoding="utf-8") == "new"
    assert source.read_text(encoding="utf-8") == "new"
    assert not (tmp_path / "update.ps1.stage").exists()


def test_move_atomic_keeps_original_on_digest_mismatch(tmp_path):
    target = tmp_path / "update.ps1"
    source = tmp_path / "candidate.exe"
    target.write_text("old", encoding="utf-8")
    source.write_text("new", encoding="utf-8")
    wrong = hashlib.sha256(b"other").hexdigest()
    script = ("$ErrorActionPreference='Stop'\n" + _functions() + "\n"
              + "Move-Atomic -source '" + _ps(source) + "' -target '" + _ps(target)
              + "' -expectedHash '" + wrong + "'\n")
    out = _run(script)
    assert out.returncode != 0
    assert "staged_digest_mismatch" in out.stderr
    assert target.read_text(encoding="utf-8") == "old"
    assert not (tmp_path / "update.ps1.stage").exists()


def test_move_atomic_refuses_a_leftover_staging_file(tmp_path):
    target = tmp_path / "update.ps1"
    source = tmp_path / "candidate.exe"
    target.write_text("old", encoding="utf-8")
    source.write_text("new", encoding="utf-8")
    (tmp_path / "update.ps1.stage").write_text("stale", encoding="utf-8")
    digest = hashlib.sha256(b"new").hexdigest()
    script = ("$ErrorActionPreference='Stop'\n" + _functions() + "\n"
              + "Move-Atomic -source '" + _ps(source) + "' -target '" + _ps(target)
              + "' -expectedHash '" + digest + "'\n")
    out = _run(script)
    assert out.returncode != 0
    assert "unexpected_staging_file" in out.stderr
    assert target.read_text(encoding="utf-8") == "old"
