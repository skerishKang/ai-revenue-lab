"""#7810 [리팩터링 v2 · T0] 구조 수치 래칫 시험.

tools/chat_structure_audit.py 가 잰 구조 수치를 tests/structure_baseline.json
기준선과 비교한다(#7809 · #7810).

- 어떤 수치든 기준선보다 크면 실패한다. 덮어쓰기가 다시 얹히는 순간 이 시험이
  막는다. 안내: 덮지 말고 이기고 있는 규칙을 고친다 / 새 기능은 새 모듈에.
- 기준선보다 작으면 실패한다. 수치를 줄인 트랙은 그 PR에서 기준선을 실측으로
  내려야 한다(#7809 공통 규칙 5: 가드 숫자는 내리기만 한다).
- 기준선 파일은 한 줄에 키 하나를 둔다(트랙끼리 병합 충돌 방지).
  ``css_important_by_file`` 은 ``css_important_by_file/<시트 이름>`` 키로
  한 줄씩 펼쳐 둔다.
- 기존 가드(test_r5_file_size_guard_7216.py, test_r6_history_file_size_guard_7790.py)
  는 그대로 둔다. 이 시험은 구조 수치 전체를 더한다.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
CHAT_DIR = TESTS_DIR.parent
ROOT = CHAT_DIR.parent.parent
BASELINE_PATH = TESTS_DIR / "structure_baseline.json"
TOOL_PATH = ROOT / "tools" / "chat_structure_audit.py"
STATIC_DIR = CHAT_DIR / "static"

GROW_GUIDE = (
    "구조 수치가 늘었다. 되돌린다: 덮지 말고 이기고 있는 규칙을 고친다 / "
    "새 기능은 새 모듈에(!important·새 덮어쓰기 시트·app.js 선언·"
    "D1HistoryStore 메서드 추가 금지 — #7809 기능·수리 PR 규칙)."
)
SHRINK_GUIDE = (
    "구조 수치가 줄었다. 기준선을 내려라: 이 PR에서 "
    "apps/padiem-chat/tests/structure_baseline.json 을 실측 값으로 갱신한다."
)


def _load_tool():
    spec = importlib.util.spec_from_file_location("chat_structure_audit", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def current_metrics() -> dict:
    tool = _load_tool()
    css, _rules = tool.css_metrics()
    metrics = {**css, **tool.js_metrics(), **tool.server_metrics()}
    flat: dict = {}
    for key, value in metrics.items():
        if key == "css_important_by_file":
            for name, count in value.items():
                flat[f"css_important_by_file/{name}"] = count
        elif key == "py_functions_over_300_names":
            continue  # 목록은 가드 대상이 아니다. 개수(py_functions_over_300)만 본다.
        else:
            flat[key] = value
    return flat


def baseline_metrics() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def test_baseline_and_tool_are_present() -> None:
    assert BASELINE_PATH.is_file(), "structure_baseline.json 이 없다"
    assert TOOL_PATH.is_file(), "tools/chat_structure_audit.py 가 없다"
    assert STATIC_DIR.is_dir(), "static 시트 디렉터리가 없다"


def test_no_structure_metric_grew() -> None:
    baseline = baseline_metrics()
    current = current_metrics()
    grew = [
        (key, baseline[key], current.get(key, 0))
        for key in baseline
        if current.get(key, 0) > baseline[key]
    ]
    assert not grew, (
        "늘어난 구조 수치:\n"
        + "\n".join(f"  {key}: {before} → {after} (+{after - before})" for key, before, after in grew)
        + "\n" + GROW_GUIDE
    )


def test_no_structure_metric_shrunk() -> None:
    baseline = baseline_metrics()
    current = current_metrics()
    shrunk = [
        (key, baseline[key], current.get(key, 0))
        for key in baseline
        if current.get(key, 0) < baseline[key]
    ]
    assert not shrunk, (
        "줄어든 구조 수치:\n"
        + "\n".join(f"  {key}: {before} → {after} (-{before - after})" for key, before, after in shrunk)
        + "\n" + SHRINK_GUIDE
    )
