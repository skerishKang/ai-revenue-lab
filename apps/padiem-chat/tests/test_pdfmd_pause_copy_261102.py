"""#6592 follow-up: the PDF→Markdown pause notice speaks to the owner, not to a
deployment diagram.

The pause itself is an owner decision (#5710/#5711) and stays. What must not
appear on the screen is the internal channel name: the COM2 move finished on
2026-10-31, so a sentence that names the host tells the user nothing and is
already out of date.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
PDFMD = (STATIC / "util-pdfmd.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
ROUTES = (ROOT / "app" / "document_convert_routes.py").read_text(encoding="utf-8")
CPYTHON = (ROOT / "app" / "local_cpython.py").read_text(encoding="utf-8")


def _code(source: str) -> str:
    """Line comments are developer-facing on purpose; strings are not."""
    return "\n".join(re.sub(r"//.*$", "", line) for line in source.splitlines())


def test_the_internal_channel_name_is_gone_from_the_screen() -> None:
    assert "COM2" not in _code(PDFMD), "util-pdfmd.js paints the host name on the screen again"
    assert "COM2" not in INDEX, "index.html paints the host name on the screen again"
    for retired in ("문서 처리 서버를 COM2로 이전 중입니다", "COM2 이전 완료 후 이용할 수 있습니다",
                    "신규 업로드는 COM2 이전 후"):
        assert retired not in PDFMD and retired not in INDEX


def test_the_pause_still_says_what_is_and_is_not_possible() -> None:
    # The screen states the absence and states what still works, in plain words.
    assert "지금은 새 변환을 시작할 수 없습니다" in PDFMD
    assert "기존 작업 이력과 결과 다운로드는 그대로 이용할 수 있습니다" in PDFMD
    assert "곧 다시 이용할 수 있어요" in PDFMD
    assert "새 업로드는 잠시 멈춤" in INDEX


def test_the_owner_pause_contract_is_untouched() -> None:
    # #5711: the pause sentence and the drop-zone call stay. What moved is when
    # they may be painted — the harness in test_5568_pdfmd_ui_p1.py now asserts
    # them after a paused answer instead of on the first paint.
    assert '"서비스 준비 중 · 신규 업로드 및 변환 일시 중단"' in PDFMD
    assert '"업로드 일시 중단"' in PDFMD
    assert 'workState = "checking"' in PDFMD, "the first paint must start as unknown, not as paused"


def test_the_real_gate_is_still_the_server_answer_not_the_copy() -> None:
    # The route answers from the app state that only the COM2 host with the
    # reviewed dependency sets, and the panel repaints once from that answer.
    assert '"new_work_enabled": not _new_work_disabled(request)' in ROUTES
    assert "app.state.pdfmd_com2_ready = host_flag and importlib.util.find_spec(\"pypdf\") is not None" in CPYTHON
    assert 'const answer = data.new_work_enabled === true ? "open" : "paused";' in PDFMD
    assert "if (answer !== workState) {" in PDFMD
    # No answer at all is the other case that may claim the pause.
    assert 'if (PDFMD_CHECKING) {' in PDFMD
    assert 'window.initPdfMdUtility(panel, "paused");' in PDFMD
    # An unconfirmed state never performs an action, but only a confirmed pause
    # says so on screen.
    assert "const workBlocked = PDFMD_NEW_WORK_DISABLED || PDFMD_CHECKING;" in PDFMD
    assert "modeSel.disabled = workBlocked;" in PDFMD
    assert "fileInput.disabled = workBlocked;" in PDFMD
    assert 'if (workBlocked) return false;' in PDFMD
