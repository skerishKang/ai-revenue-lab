"""R6 0단계-B/2단계/3단계 — Chat history.py 크기 상한 시험 (#7790).

R5의 `test_r5_file_size_guard_7216.py` 방식을 따른다. 줄 수는 실제 줄 수
(`splitlines()`)로 센다. 상한 상향 금지.

history.py 상한: 4,607줄(+100=4,707) → 4,570줄(+100=4,670) → 4,532줄(+100=4,632) → 4,484줄(+100=4,584) → 4,322줄(+100=4,422) → 4,195줄(+100=4,295) → 3,779줄(+100=3,879) → 3,247줄(+100=3,347) → 2,960줄(+100=3,060) → 2,411줄(+100=2,511) → 1,625줄(+100=1,725) → 1,130줄(+100=1,230) → 661줄(+100=761)으로 하향.
새 모듈은 500줄을 목표로 하며, 1,000줄을 넘으면 파일 맨 위에 이유와 예외 목록을
적어야 한다. 예외 없는 파일은 500 초과 경고, 1,000 초과 실패다.
"""
from pathlib import Path
import warnings

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "apps" / "padiem-chat" / "app"
HISTORY = APP / "history.py"

# 이동 후 history.py 661줄 + 100. 직전 1130 + 100 = 1230에서 하향, 상향 금지.
HISTORY_CAP = 761

FAIL_MSG = ("상한은 커지는 것을 알리는 장치다. 억지로 쪼개지 말고 새 기능은 새 모듈 파일로 만든다. "
            "상한 상향 금지(#7790).")


def _lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_history_stays_under_its_cap() -> None:
    n = _lines(HISTORY)
    assert n <= HISTORY_CAP, f"history.py {n} > {HISTORY_CAP}. {FAIL_MSG}"


def _warn_if_over_500(name: str, n: int) -> None:
    if n > 500:
        warnings.warn(f"{name} {n} lines (>500). 새 기능은 새 모듈 파일로. {FAIL_MSG}")


def test_new_history_modules_warn_over_500_fail_over_1000() -> None:
    for name in (
        "history_project_cursor.py",
        "history_search.py",
        "history_run_summary.py",
        "history_mesh_original.py",
        "history_pinned.py",
        "history_errors.py",
        "history_types.py",
        "history_text.py",
        "history_constants.py",
        "history_ids.py",
        "history_rows.py",
        "history_store_core.py",
        "history_store_handoff.py",
        "history_store_accounts.py",
        "history_store_conversations.py",
        "history_store_runs.py",
        "history_store_run_events.py",
        "history_store_mesh.py",
    ):
        n = _lines(APP / name)
        assert n <= 1000, f"{name} {n} > 1000. {FAIL_MSG}"
        _warn_if_over_500(name, n)
