"""#5573: an undecodable PC reply is reported as an encoding failure.

The reply envelope is produced by the executor's command port; what Chat owns is
the words the conversation shows. A console that answered with an unreadable
envelope must not be reported as a silent console ("콘솔 응답 없음") and must not
be reported as a command that never ran ("실행되지 않음") either — both would send
the owner looking at the wrong thing.
"""
from __future__ import annotations

from app import oracle_mesh_read_return_routes as routes

COMMAND = "Get-ChildItem -LiteralPath 'C:/Users/me/견적' -Force"


def _header(termination: str, exit_code=None):
    return routes._command_header(
        {"command_text": COMMAND},
        {"termination": termination, "exit_code": exit_code},
    )


def test_an_undecodable_reply_says_what_failed_without_blaming_the_console():
    lines = _header("bad_reply")
    assert any("인코딩 오류" in line for line in lines), lines
    assert not any("응답 없음" in line for line in lines), lines
    assert not any("실행되지 않음" in line for line in lines), lines
    assert any(line == "종료 코드: 확인되지 않음" for line in lines), lines
    # An observed exit code is still reported as observed, envelope or not.
    coded = _header("bad_reply", 1)
    assert any(line == "종료 코드: 1" for line in coded), coded
