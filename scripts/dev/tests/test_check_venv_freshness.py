# -*- coding: utf-8 -*-
"""check_venv_freshness의 실제 임시 venv 엔드투엔드 테스트.

가짜 더블을 만들지 않는다: 실제 저장소 소스(packages/padiem-control-plane)를
임시 저장소 구조로 복사하고, 실제 uv가 그 소스를 임시 앱 venv에 복사 설치하게
한 뒤, 소스 한 파일을 바꿔 STALE 감지와 --fix 복구를 끝까지 검증한다.

이 테스트가 잡는 실제 실패(이번 주 반복): 설치본이 소스보다 오래됐는데 테스트가
통과하거나, 신선한데 테스트가 실패해 레인이 원인 규명에 시간을 쓰는 경우.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKER = REPO_ROOT / "scripts" / "dev" / "check_venv_freshness.py"
SHARED_PACKAGE = REPO_ROOT / "packages" / "padiem-control-plane"
# The marker file the test edits to age the installed copy behind the source.
MARKER_FILE = "padiem_control_plane/product_tier_routes.py"

pytestmark = pytest.mark.skipif(
    not SHARED_PACKAGE.is_dir(), reason="padiem-control-plane source not present"
)


def _run_uv(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "uv", *args], cwd=cwd,
        capture_output=True, text=True, timeout=600,
    )


def _run_checker(args: list[str], cwd: Path) -> dict:
    completed = subprocess.run(
        [sys.executable, str(CHECKER), "--repo-root", str(cwd), "--json", *args],
        capture_output=True, text=True, timeout=600,
    )
    assert completed.stdout.strip(), completed.stderr
    return {"exit": completed.returncode, "report": json.loads(completed.stdout)}


def _package_states(report: dict) -> list[dict]:
    return [pkg for app in report["apps"] for pkg in app.get("packages", [])]


@pytest.fixture(scope="module")
def temp_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real minimal repo: the real shared source + one app locked onto it."""
    repo = tmp_path_factory.mktemp("fresh-repo")
    shutil.copytree(
        SHARED_PACKAGE, repo / "packages" / "padiem-control-plane",
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.egg-info"),
    )
    app = repo / "apps" / "testapp"
    app.mkdir(parents=True)
    (app / "pyproject.toml").write_text(
        "[project]\n"
        'name = "testapp"\n'
        'version = "0.1.0"\n'
        'requires-python = ">=3.11"\n'
        'dependencies = ["padiem-control-plane"]\n'
        "\n"
        "[tool.uv.sources]\n"
        'padiem-control-plane = { path = "../../packages/padiem-control-plane" }\n',
        encoding="utf-8",
    )
    sync = _run_uv(["sync"], app)
    assert sync.returncode == 0, sync.stderr
    return repo


def test_real_install_starts_fresh_then_goes_stale_then_fix_restores(temp_repo: Path) -> None:
    # 1) 막 설치한 상태: 복사 설치본이 소스와 같으니 FRESH, 종료 코드 0.
    fresh = _run_checker([], temp_repo)
    assert fresh["exit"] == 0, fresh["report"]
    states = _package_states(fresh["report"])
    assert states, "the locked local package must be discovered"
    assert all(s["state"] == "FRESH" for s in states), states

    # 2) 소스 한 파일을 앞으로: 설치본이 뒤처져 STALE, 종료 코드 1,
    #    보고에는 바뀐 파일이 예시로 잡혀야 규명이 한 번에 끝난다.
    marker = temp_repo / "packages" / "padiem-control-plane" / Path(MARKER_FILE)
    original = marker.read_text(encoding="utf-8")
    marker.write_text(original + "\n# freshness marker\n", encoding="utf-8")
    try:
        stale = _run_checker([], temp_repo)
        assert stale["exit"] == 1
        stale_states = _package_states(stale["report"])
        assert [s["state"] for s in stale_states] == ["STALE"], stale_states
        assert MARKER_FILE in stale_states[0]["examples"], stale_states[0]
        assert stale_states[0]["differences"] >= 1

        # 3) --fix: STALE 패키지에 한해 uv sync --reinstall-package 실행 후
        #    재검증이 FRESH로 돌아오고, 종료 코드도 0이 된다.
        fixed = _run_checker(["--fix"], temp_repo)
        fixed_states = _package_states(fixed["report"])
        assert all(s["state"] == "FRESH" for s in fixed_states), fixed_states
        assert fixed["exit"] == 0
        assert all(pkg.get("fix", {}).get("ok") for pkg in fixed_states), fixed_states
    finally:
        marker.write_text(original, encoding="utf-8")
