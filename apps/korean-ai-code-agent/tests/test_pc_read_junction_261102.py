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

# The junction/symlink fixtures are real Windows reparse points: cmd /c mklink
# does not exist on the Linux runner, so the machine-level tests run on Windows
# only. The source-contract tests below stay on every platform. A unittest
# marker is used because pytest marks are not applied to TestCase subclasses
# on every runner, and an attempted Linux junction fixture must not ERROR.
WIN_REAL = unittest.skipUnless(
    sys.platform == "win32", "real Windows junction fixtures")

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


class PcReparseCheckUnitTests(unittest.TestCase):
    """The executor's PC-side reparse walk through a fake command port.

    All machine behavior is mocked at the command-channel seam the executor
    already owns; no PowerShell runs here. The contract: a reported hit (or a
    check that cannot complete) refuses the read before the download, a clear
    walk lets the read proceed, and the verdict does not depend on which read
    bound the dispatch carries.
    """

    def _executor(self, *, marker_hit=None, no_marker=False, raises=False):
        from kagent.local_agent_oracle_mesh_executor import (
            OracleMeshExecutor, PC_FILE_LINK_REFUSED_MARKER,
        )
        import base64 as _b64

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

        executor = OracleMeshExecutor.__new__(OracleMeshExecutor)
        executor._command_port = _Port()
        executor._read_port = None  # must never be reached on a refusal
        executor._timeout = 30  # production always runs with a step deadline
        return executor

    def _dispatch(self):
        from kagent.local_agent_oracle_mesh_executor import OracleMeshDispatch
        return OracleMeshDispatch(
            dispatch_id="dsp-junction", nonce="n" * 32, kind="read",
            node_ref="node-pc", file_path="C:/granted/보고서.docx",
            command_id="cmd-junction", run_id="run-junction",
            granted_root="C:/granted", max_bytes=20_000_000,
        )

    def test_a_reported_junction_refuses_the_download(self):
        executor = self._executor(marker_hit=True)
        outcome = executor._execute_read(self._dispatch())
        assert outcome.body == (
            __import__("kagent.local_agent_oracle_mesh_executor",
                       fromlist=["PC_FILE_LINK_REFUSED_MARKER"])
            .PC_FILE_LINK_REFUSED_MARKER.encode("utf-8"))
        assert outcome.exit_code == 1

    def test_a_clear_walk_lets_the_read_proceed(self):
        executor = self._executor(marker_hit=False)
        reached = {}

        class _ReadPort:
            # The fake names the real port's parameters exactly, so a protocol
            # drift fails here instead of being swallowed by **kwargs.
            def read_bytes(self, *, node_ref: str, file_path: str,
                           timeout_seconds: int, max_bytes: int = 1) -> bytes:
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
        from kagent.local_agent_oracle_mesh_executor import (
            PC_FILE_LINK_REFUSED_MARKER,
        )
        assert outcome.body == PC_FILE_LINK_REFUSED_MARKER.encode("utf-8")

    def test_a_command_channel_failure_refuses_closed(self):
        executor = self._executor(raises=True)
        outcome = executor._execute_read(self._dispatch())
        from kagent.local_agent_oracle_mesh_executor import (
            PC_FILE_LINK_REFUSED_MARKER,
        )
        assert outcome.body == PC_FILE_LINK_REFUSED_MARKER.encode("utf-8")
