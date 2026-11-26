"""#6645: a stale project cursor must say so on screen.

The desktop glass frame hides `.composer-note` with ``display: none !important``
(``static/shared-six-panel-frame.css``), so the old ``setNote`` report never
painted. The notice now belongs to the project list, next to the button it is
about. These checks pin that contract so the silent failure cannot come back.
"""
from __future__ import annotations

# #8060: shipped reads live in _support; assertions stay here.
from _support.projects_recovery_template_source import (
    app_js, event_js, index_html, lifecycle_js, quote_runtime_js, read as _source_read,
    recovery_js, stream_js,
)

from pathlib import Path

# R5 0단계(R-01): 함수 본문은 app.js든 분리 모듈이든 같은 도우미로 찾는다.
from _r5_function_source import function_body

CHAT = Path(__file__).resolve().parents[1]
STATIC = CHAT / "static"


def read(name: str) -> str:
    return _source_read(name)


def test_the_project_list_owns_a_status_note_next_to_the_more_button() -> None:
    html = read("index.html")
    section = html.split('id="projectsSection"', 1)[1].split("</section>", 1)[0]
    assert 'id="projectsListNote"' in section
    assert section.index('id="projectsList"') < section.index('id="projectsListNote"')
    # A polite live region, hidden until the server refuses the cursor.
    note = section.split('id="projectsListNote"', 1)[1].split(">", 1)[0]
    assert 'role="status"' in note
    assert 'aria-live="polite"' in note
    assert "hidden" in note


def test_a_rejected_cursor_reports_into_that_note() -> None:
    source = read("app.js")
    project_source = read("chat-project-module.js")
    # R5 0단계(R-01): 이동한 함수의 실제 정의를 같은 도우미로 잘라낸다.
    body = function_body("loadMoreProjects", end="\n      }")
    assert "response.status === 400" in body
    stale = body.split("response.status === 400", 1)[1]
    assert 'setProjectsListNote(deps.uiT("projects-more-stale"))' in stale
    # The composer note was the silent path; it must not carry this message again.
    assert "setNote(uiT(\"projects-more-stale\"))" not in source
    assert "setNote(uiT(\"projects-more-stale\"))" not in project_source
    # A successful page clears the notice so it never outlives the failure.
    assert 'setProjectsListNote("");' in body
    clear = function_body("clearProjectsUI", end="\n      }")
    assert 'setProjectsListNote("");' in clear


def test_the_note_is_painted_on_every_theme_frame() -> None:
    css = read("projects.css")
    block = css.split(".project-list-note {", 1)[1].split("}", 1)[0]
    assert "font-size: 14px" in block
    assert "display: none" not in block
    assert "visibility: hidden" not in block
    for name in ("shared-six-panel-frame.css", "claw-workspace.css", "padiem-glass-portrait.css"):
        assert ".project-list-note" not in read(name)
