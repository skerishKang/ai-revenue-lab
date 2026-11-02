"""#5994 D3 후속 — 읽기 레인의 정션/링크 경계 가드(reparse_guard) 검증.

가드 모듈은 의존성이 없으므로 저장소 소스 파일을 고유 모듈 이름으로 직접
적재한다 — site-packages 구버전 kagent와 무관하게 정확히 이 소스를 검증한다.
실행기 소스 계약(가드가 읽기 포트보다 먼저)도 소스로 고정한다.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

# 저장소 src를 site-packages 구버전보다 먼저 읽도록 한다 — 이 시험은 이 소스의
# 가드와 실행기를 검증한다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "padiem-ai-core"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "padiem-control-plane"))

# The junction/symlink fixtures are real Windows reparse points: cmd /c mklink
# does not exist on the Linux runner, so the machine-level tests run on Windows
# only. The source-contract tests below stay on every platform.
WIN_REAL = pytest.mark.skipif(sys.platform != "win32",
                              reason="real Windows junction fixtures")

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


@WIN_REAL
class WalkHitTests(unittest.TestCase):
    def setUp(self):
        self._previous = tempfile.TemporaryDirectory()
        self.root = Path(self._previous.name) / "granted"
        self.root.mkdir(parents=True)
        self.outside = Path(self._previous.name) / "outside"
        self.outside.mkdir()

    def tearDown(self):
        # rglob은 self→부모 정션 루프를 끝없이 따라간다 — reparse 지점은
        # 내려가지 않고 링크 자체만 제거한 뒤 임시 폴더를 정리한다.
        stack = [self.root]
        while stack:
            try:
                entries = list(os.scandir(stack.pop()))
            except OSError:
                continue
            for entry in entries:
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if getattr(info, "st_file_attributes", 0) & 0x400:
                    _rmdir(Path(entry.path))
                elif stat.S_ISDIR(info.st_mode):
                    stack.append(entry.path)
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


_TIMEOUT_UNSET = object()  # #6327 계약: None 기본값 대신 생략을 관찰하는 센티널


class _RefusingReadPort:
    """A read port that must never be reached while a refusal is expected."""

    def read_bytes(self, *, node_ref, file_path, timeout_seconds=_TIMEOUT_UNSET,
                   max_bytes=None):
        raise AssertionError(
            "the MeshCentral download started although the reparse walk "
            "refused the read: " + repr(sorted({
                "node_ref": node_ref, "file_path": file_path,
                "timeout_seconds": timeout_seconds, "max_bytes": max_bytes,
            })))


class PcReparseCheckUnitTests(unittest.TestCase):
    """The executor's PC-side reparse walk through a fake command port.

    All machine behavior is mocked at the command-channel seam the executor
    already owns; no PowerShell runs here. The contract: a reported hit (or a
    check that cannot complete) refuses the read before the download, a clear
    walk lets the read proceed, and the verdict does not depend on which read
    bound the dispatch carries.
    """

    @classmethod
    def _load(cls):
        # venv는 이 저장소를 editable로 설치한다 — kagent는 곧장 src를 가리킨다.
        # sys.modules를 몰래 지워 강제 재적재하는 방식은 세션 전역 모듈
        # 정체성을 깨뜨려 뒤에 도는 시험 파일을 흔들므로 쓰지 않는다.
        from kagent.local_agent_oracle_mesh_executor import (
            OracleMeshExecutor, OracleMeshDispatch, PC_FILE_LINK_REFUSED_MARKER,
        )
        return OracleMeshExecutor, OracleMeshDispatch, PC_FILE_LINK_REFUSED_MARKER

    def _executor(self, *, marker_hit=None, no_marker=False, raises=False):
        import base64 as _b64
        OracleMeshExecutor, _OracleMeshDispatch, PC_FILE_LINK_REFUSED_MARKER = self._load()
        self._marker = PC_FILE_LINK_REFUSED_MARKER

        class _Outcome:
            def __init__(self, body: bytes):
                self.body = body
                self.termination = "exited"
                self.exit_code = 0

        if raises:
            class _Port:
                def run_command(self, **_):
                    raise RuntimeError("SECRET_COMMAND_PATH")
        else:
            class _Port:
                def run_command(self, **_):
                    if marker_hit is None and not no_marker:
                        payload = {"hit": True}
                    elif no_marker:
                        payload = {"unexpected": "shape"}
                    else:
                        payload = {"hit": bool(marker_hit)}
                    encoded = _b64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
                    return _Outcome(("PADIEM_PC_REPARSE=" + encoded).encode("utf-8"))

        return OracleMeshExecutor(
            chat_origin="https://chat.example.test",
            channel_secret="test-channel-secret-value-261102",
            read_port=_RefusingReadPort(),
            command_port=_Port(),
        )

    def _dispatch(self):
        _OracleMeshExecutor, OracleMeshDispatch, _marker = self._load()
        return OracleMeshDispatch(
            dispatch_id="dsp-junction", nonce="n", kind="read", node_ref="node-pc",
            file_path="C:/granted/보고서.docx", command_id="cmd-1", run_id="run-1",
            granted_root="C:/granted", max_bytes=20_000_000,
        )

    def test_a_reported_junction_refuses_the_download(self):
        executor = self._executor(marker_hit=True)
        outcome = executor._execute_read(self._dispatch())
        assert outcome.body == self._marker.encode("utf-8")
        assert outcome.exit_code == 1

    def test_a_clear_walk_lets_the_read_proceed(self):
        executor = self._executor(marker_hit=False)
        reached = {}

        class _ReadPort:
            def read_bytes(self, *, node_ref, file_path,
                           timeout_seconds=_TIMEOUT_UNSET, max_bytes=None):
                reached.update(node_ref=node_ref, file_path=file_path,
                               timeout_seconds=timeout_seconds,
                               max_bytes=max_bytes)
                return b"inside content"

        executor = self._executor(marker_hit=False)
        executor._read_port = _ReadPort()
        outcome = executor._execute_read(self._dispatch())
        assert outcome.body == b"inside content"
        assert reached["node_ref"] == "node-pc"

    def test_a_check_that_cannot_report_refuses_closed(self):
        executor = self._executor(no_marker=True)
        outcome = executor._execute_read(self._dispatch())
        assert outcome.body == self._marker.encode("utf-8")

    def test_a_command_channel_failure_refuses_closed(self):
        executor = self._executor(raises=True)
        outcome = executor._execute_read(self._dispatch())
        assert outcome.body == self._marker.encode("utf-8")
