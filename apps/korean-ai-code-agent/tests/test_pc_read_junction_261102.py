"""#5994 D3 후속 — 읽기 레인의 정션/링크 경계 가드(reparse_guard) 검증.

가드 모듈은 의존성이 없으므로 저장소 소스 파일을 고유 모듈 이름으로 직접
적재한다 — site-packages 구버전 kagent와 무관하게 정확히 이 소스를 검증한다.
실행기 소스 계약(가드가 읽기 포트보다 먼저)도 소스로 고정한다.
"""
from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

import importlib.util as _ilu

_ROOT = Path(__file__).resolve().parents[3]
_GUARD_FILE = _ROOT / "apps" / "korean-ai-code-agent" / "src" / "kagent" / "reparse_guard.py"
_spec = _ilu.spec_from_file_location("reparse_guard_under_test", str(_GUARD_FILE))
_guard = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_guard)
walk_hits_reparse_point = _guard.walk_hits_reparse_point


def _junction(link: Path, target: Path) -> bool:
    import subprocess
    if link.exists() or link.is_symlink():
        subprocess.run(["cmd", "/c", "rmdir", str(link)], capture_output=True)
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                            capture_output=True)
    return result.returncode == 0


def _symlink(link: Path, target: Path) -> bool:
    import subprocess
    result = subprocess.run(["cmd", "/c", "mklink", "/D", str(link), str(target)],
                            capture_output=True)
    return result.returncode == 0


def _rmdir(link: Path) -> None:
    import subprocess
    subprocess.run(["cmd", "/c", "rmdir", str(link)], capture_output=True)


class WalkHitTests(unittest.TestCase):
    def setUp(self):
        self._previous = tempfile.TemporaryDirectory()
        self.root = Path(self._previous.name) / "granted"
        self.root.mkdir(parents=True)
        self.outside = Path(self._previous.name) / "outside"
        self.outside.mkdir()

    def tearDown(self):
        for link in list(self.root.rglob("*link*")) + [self.root / "self"]:
            if link.is_dir() and not link.is_symlink():
                continue
            _rmdir(link)
        self._previous.cleanup()

    def test_plain_file_below_root_has_no_hit(self):
        (self.root / "a.txt").write_text("ok", encoding="utf-8")
        assert walk_hits_reparse_point(str(self.root), str(self.root / "a.txt")) is False

    def test_junction_target_is_a_hit(self):
        link = self.root / "link"
        assert _junction(link, self.outside) is True
        assert walk_hits_reparse_point(str(self.root), str(link / "x.txt")) is True

    def test_mid_folder_junction_is_a_hit(self):
        (self.outside / "deep").mkdir(exist_ok=True)
        link = self.root / "mid"
        assert _junction(link, self.outside) is True
        assert walk_hits_reparse_point(str(self.root), str(link / "deep" / "x.txt")) is True

    def test_normalized_path_outside_the_root_is_a_hit(self):
        assert walk_hits_reparse_point(
            str(self.root), str(self.outside / "x.txt")) is True

    def test_the_root_itself_is_never_inspected(self):
        """루트 자체가 링크인 경우는 소유자의 허가 결정 — 기존 동작 유지."""
        link = self.root / "self"
        assert _junction(link, self.root) is True
        assert walk_hits_reparse_point(str(self.root), str(self.root / "a.txt")) is False

    def test_missing_file_below_root_has_no_hit(self):
        assert walk_hits_reparse_point(
            str(self.root), str(self.root / "없는파일.txt")) is False


class ExecutorSourceContractTests(unittest.TestCase):
    """실행기 소스가 가드를 읽기 포트보다 먼저 부르는지 소스로 고정한다."""

    def test_the_read_leg_sends_the_guard_through_the_command_channel(self):
        executor_file = _ROOT / "apps" / "korean-ai-code-agent" / "src" / "kagent"             / "local_agent_oracle_mesh_executor.py"
        source = executor_file.read_text(encoding="utf-8")
        assert "_pc_reparse_check(" in source, "명령 채널 검사 메서드"
        check_call = source.index("_pc_reparse_check(")
        port_call = source.index("self._read_port.read_bytes(")
        assert check_call < port_call, "가드가 다운로드보다 먼저여야 한다"
        assert "PADIEM_PC_REPARSE" in source, "PC 검사 결과 마커"
        assert "link_refused" in source, "거부 마커가 계약에 있어야 한다"
        assert "self._command_port.run_command(" in source, "명령 채널로 PC 검사"

    def test_the_guard_module_is_dependency_free(self):
        source = _GUARD_FILE.read_text(encoding="utf-8")
        for forbidden in ("import requests", "import httpx", "from kagent",
                          "from .", "import logging"):
            assert forbidden not in source, forbidden


if __name__ == "__main__":
    unittest.main()
