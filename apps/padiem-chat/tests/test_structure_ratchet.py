"""#8054 — 구조 수치 래칫: PR head 실측 ≤ base(main) 실측.

기준선 JSON을 커밋하지 않는다. 매 실행마다 base 트리를 임시 체크아웃하고
head와 **같은 감사 도구 코드**로 둘 다 잰 뒤, 어떤 수치도 base보다 크면 실패한다.

- 늘어나면 실패한다(느슨해지지 않음). 덮지 말고 이기고 있는 규칙을 고치거나
  새 기능을 새 모듈에 둔다.
- 줄어들어도 이제 실패가 아니다. 기준선 갱신 커밋이 필요 없어서, 수치를 줄이는
  PR 두 개가 같은 파일에서 충돌하지 않는다.
- `index_script_tags`는 새 모듈 1개 = script 태그 +1이 정상이라 비교에서 뺀다
  (CTO 결정, #7816).
- 파일 줄 상한 같은 **절대 상한**은 여기서 다루지 않는다.
  `test_r5_file_size_guard_7216.py`·`test_r6_history_file_size_guard_7790.py`가
  계속 소유한다.

base 트리 선택 순서:

1. ``PADIEM_STRUCTURE_BASE_ROOT`` — 이미 준비된 체크아웃 디렉터리.
2. ``PADIEM_STRUCTURE_BASE_SHA`` — PR base 커밋(CI). 없으면 ``git fetch --depth=1``.
3. ``PADIEM_STRUCTURE_BASE_REF`` 또는 ``origin/main`` — 로컬 기본값.
"""

from __future__ import annotations

import functools
import importlib.util
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
CHAT_DIR = TESTS_DIR.parent
ROOT = CHAT_DIR.parent.parent
BASELINE_PATH = TESTS_DIR / "structure_baseline.json"
TOOL_PATH = ROOT / "tools" / "chat_structure_audit.py"
STATIC_DIR = CHAT_DIR / "static"

#: CTO 결정(#7816): 새 모듈 = script 태그 +1 이 정상이라 이 키만 비교에서 뺀다.
EXCLUDED_KEYS = {"index_script_tags"}
#: 목록은 가드 대상이 아니다. 개수(py_functions_over_300)만 본다.
LIST_KEY = "py_functions_over_300_names"

GROW_GUIDE = (
    "구조 수치가 base(main)보다 늘었다. 되돌린다: 덮지 말고 이기고 있는 규칙을 고친다 / "
    "새 기능은 새 모듈에(!important·새 덮어쓰기 시트·app.js 선언·"
    "D1HistoryStore 메서드 추가 금지 — #7809 기능·수리 PR 규칙)."
)


def _load_tool():
    spec = importlib.util.spec_from_file_location("chat_structure_audit", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _flat_metrics(root: Path | None) -> dict[str, int]:
    tool = _load_tool()
    css, _rules = tool.css_metrics(root=root)
    metrics = {**css, **tool.js_metrics(root=root), **tool.server_metrics(root=root)}
    flat: dict = {}
    for key, value in metrics.items():
        if key == "css_important_by_file":
            for name, count in value.items():
                flat[f"css_important_by_file/{name}"] = count
        elif key == LIST_KEY:
            continue
        else:
            flat[key] = value
    return flat


@functools.lru_cache(maxsize=1)
def _head_metrics() -> dict[str, int]:
    return _flat_metrics(None)


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True, text=True, capture_output=True, encoding="utf-8",
    )


def _base_revision() -> str:
    sha = os.environ.get("PADIEM_STRUCTURE_BASE_SHA", "").strip()
    if sha:
        probe = subprocess.run(
            ["git", "-C", str(ROOT), "cat-file", "-e", f"{sha}^{{commit}}"],
            text=True, capture_output=True,
        )
        if probe.returncode != 0:
            _git("fetch", "--no-tags", "--depth=1", "origin", sha)
        return sha
    return os.environ.get("PADIEM_STRUCTURE_BASE_REF", "").strip() or "origin/main"


@functools.lru_cache(maxsize=1)
def _base_metrics() -> dict[str, int]:
    provided = os.environ.get("PADIEM_STRUCTURE_BASE_ROOT", "").strip()
    if provided:
        return _flat_metrics(Path(provided))

    revision = _base_revision()
    worktree = Path(tempfile.mkdtemp(prefix="padiem-structure-base-")) / "tree"
    _git("worktree", "add", "--detach", str(worktree), revision)
    try:
        return _flat_metrics(worktree)
    finally:
        subprocess.run(
            ["git", "-C", str(ROOT), "worktree", "remove", "--force", str(worktree)],
            text=True, capture_output=True,
        )
        shutil.rmtree(worktree.parent, ignore_errors=True)


def test_tool_and_head_tree_are_present() -> None:
    assert TOOL_PATH.is_file(), "tools/chat_structure_audit.py 가 없다"
    assert STATIC_DIR.is_dir(), "static 시트 디렉터리가 없다"


def test_no_committed_baseline_file() -> None:
    """#8054: 기준선 파일을 다시 들이지 않는다(base 실측이 유일한 비교 기준)."""
    assert not BASELINE_PATH.exists(), (
        "structure_baseline.json 을 커밋하지 않는다 — base 실측과 비교한다(#8054)."
    )


def _grown_metrics(base: dict, head: dict) -> list[tuple[str, int, int]]:
    """base 키 기준으로 늘어난 지표만. head에 없는 키는 0으로 본다.

    시트를 지우거나 합치면 ``css_important_by_file/<시트>`` 키가 사라진다.
    정상적인 정리이므로 사라진 키는 0(=줄어듦)으로 보고 실패시키지 않는다.
    """
    return [
        (key, base[key], head.get(key, 0))
        for key in base
        if key not in EXCLUDED_KEYS and head.get(key, 0) > base[key]
    ]


def test_head_metrics_never_exceed_the_base_tree() -> None:
    base = _base_metrics()
    head = _head_metrics()
    grew = _grown_metrics(base, head)
    assert not grew, (
        "base보다 늘어난 구조 수치:\n"
        + "\n".join(f"  {key}: {before} → {after} (+{after - before})" for key, before, after in grew)
        + "\n" + GROW_GUIDE
    )


def test_base_and_head_measurements_are_populated() -> None:
    """비교가 성립하는지 확인한다. base에 없는 새 키는 0으로 비교된다."""
    base = _base_metrics()
    head = _head_metrics()
    assert base, "base 실측이 비었다"
    assert head, "head 실측이 비었다"


def test_vanished_by_sheet_key_reads_as_zero() -> None:
    """시트 삭제/병합으로 사라진 키는 실패가 아니라 0으로 비교된다."""
    base = {"css_rules": 10, "css_important_by_file/old-sheet.css": 3}
    assert _grown_metrics(base, {"css_rules": 10}) == []
    assert _grown_metrics(base, {"css_rules": 11}) == [("css_rules", 10, 11)]
