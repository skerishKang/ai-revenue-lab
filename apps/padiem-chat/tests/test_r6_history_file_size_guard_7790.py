"""R6 0단계-B — Chat history.py 크기 상한 시험 (#7790).

R5의 `test_r5_file_size_guard_7216.py` 방식을 따른다. `history.py`는 4,607줄에서
이동 후 4,570줄이 되어 상한을 4,670줄로 내린다(실측 + 100). 상한 상향 금지.
줄 수는 빈 마지막 줄을 제외한 실제 줄 수(`splitlines()`)로 센다.

새 모듈은 500줄을 목표로 하며, 1,000줄을 넘으면 파일 맨 위에 이유와 예외 목록을
적어야 한다. 예외 없는 파일은 500 초과 경고, 1,000 초과 실패다.
"""
from pathlib import Path
import warnings

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "apps" / "padiem-chat" / "app"
HISTORY = APP / "history.py"
CURSOR_MODULE = APP / "history_project_cursor.py"

# 이동 후 history.py 4570줄 + 100. 직전 4607줄 + 100 = 4707에서 하향, 상향 금지.
HISTORY_CAP = 4670

FAIL_MSG = ("상한은 커지는 것을 알리는 장치다. 억지로 쪼개지 말고 새 기능은 새 모듈 파일로 만든다. "
            "상한 상향 금지(#7790).")


def _lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_history_stays_under_its_cap() -> None:
    n = _lines(HISTORY)
    assert n <= HISTORY_CAP, f"history.py {n} > {HISTORY_CAP}. {FAIL_MSG}"


def test_new_cursor_module_warn_over_500_fail_over_1000() -> None:
    n = _lines(CURSOR_MODULE)
    assert n <= 1000, f"history_project_cursor.py {n} > 1000. {FAIL_MSG}"
    if n > 500:
        warnings.warn(f"history_project_cursor.py {n} lines (>500). 새 기능은 새 모듈 파일로. {FAIL_MSG}")
