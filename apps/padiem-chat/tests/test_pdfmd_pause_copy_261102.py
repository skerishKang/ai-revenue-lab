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

# #8060: shipped-source reads live in _support; assertions stay here.
from _support.pdfmd_source_261102 import (
    council_app_js, document_convert_routes, index_html, local_cpython,
    pc_file_exchange_js, util_app_js, util_manifest_js, util_menu_css, util_pdfmd_js,
)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
PDFMD = util_pdfmd_js()
INDEX = index_html()
UTIL_APP = util_app_js()
ROUTES = document_convert_routes()
CPYTHON = local_cpython()


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
    # The panel states the absence and states what still works, in plain words —
    # painted only when the server actually answers that the work is paused.
    assert "지금은 새 바꾸기를 시작할 수 없습니다" in PDFMD
    assert "기존 작업 이력과 결과 다운로드는 그대로 이용할 수 있습니다" in PDFMD
    assert "곧 다시 이용할 수 있어요" in PDFMD
    # The static card no longer claims a pause on first paint: new work is
    # enabled, so the pause sentence belongs to the panel's server answer.
    assert "새 업로드는 잠시 멈춤" not in INDEX
    assert "일시 중단" not in INDEX
    # #7173 / #7460: the card copy lives in the unified util manifest.
    manifest = util_manifest_js()
    assert "PDF·ZIP을 Markdown으로 바꾸고, 비교하고, 내려받아요" in manifest


def test_the_owner_pause_contract_is_untouched() -> None:
    # #5711: the pause sentence and the drop-zone call stay. What moved is when
    # they may be painted — the harness in test_5568_pdfmd_ui_p1.py now asserts
    # them after a paused answer instead of on the first paint.
    # #7865: the notice lives on the head status line with the same promise.
    assert '"지금은 새 바꾸기를 시작할 수 없습니다. 기존 작업 이력과 결과 다운로드는 그대로 이용할 수 있습니다."' in PDFMD
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
    assert "const workBlocked = PDFMD_NEW_WORK_DISABLED || PDFMD_LOGIN_REQUIRED || PDFMD_CHECKING;" in PDFMD
    assert "modeSel.disabled = workBlocked;" in PDFMD
    assert "fileInput.disabled = workBlocked;" in PDFMD
    assert 'if (workBlocked || quotaExhausted) return false;' in PDFMD


def test_a_guest_401_asks_for_login_instead_of_claiming_a_pause() -> None:
    # A 401 says the session is missing, not that the work stopped. It has its
    # own state, its own sentence and the app's existing login entry.
    # #8812 D6·D7 대표 확인: the one 로그인 button is the drop box's own CTA —
    # the notice line keeps the sentence only, so the action is never offered
    # twice on one screen.
    assert 'const PDFMD_LOGIN_REQUIRED = workState === "login_required";' in PDFMD
    assert 'window.initPdfMdUtility(panel, "login_required");' in PDFMD
    assert "로그인하면 PDF를 바꿀 수 있어요." in PDFMD
    assert "로그인이 필요합니다" in PDFMD
    assert 'dropCta.textContent = "로그인";' in PDFMD
    assert 'if (PDFMD_LOGIN_REQUIRED) { openExistingLogin(); return; }' in PDFMD
    assert 'loginEntry.id = "pdfmdLoginEntry";' not in PDFMD
    assert 'document.getElementById("loginButton")' in PDFMD
    # The 401 branch is decided before the no-answer branch, so a guest never
    # falls through to the pause sentence.
    code = _code(PDFMD)
    catch_body = code[code.index("} catch (e) {"):]
    assert catch_body.index("if (e.status === 401) {") < catch_body.index("if (PDFMD_CHECKING) {")
    assert '"로그인하면 작업 이력을 볼 수 있습니다."' in PDFMD
