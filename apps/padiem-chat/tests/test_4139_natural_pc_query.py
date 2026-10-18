"""#4139 natural-language PC query lane — detection only.

No live Mesh: these tests pin the conservative detector so ordinary prose
never becomes remote execution while clear PC-state questions do.
"""
from app.claw_general_routes import _requested_natural_pc_query


def test_natural_pc_query_detects_database_question() -> None:
    ok, command = _requested_natural_pc_query("내 PC에 데이터베이스가 있나?")
    assert ok is True
    assert command is not None
    assert "db" in command.lower() or "*.db" in command


def test_natural_pc_query_detects_hostname_question() -> None:
    ok, command = _requested_natural_pc_query("내 PC hostname 알려줘")
    assert ok is True
    assert command == "hostname.exe"


def test_natural_pc_query_detects_drive_question() -> None:
    ok, command = _requested_natural_pc_query("내 PC에 어떤 드라이브가 있어?")
    assert ok is True
    assert command is not None
    assert "wmic" in command.lower() and "logicaldisk" in command.lower()


def test_natural_pc_query_rejects_backtick_command() -> None:
    ok, command = _requested_natural_pc_query("내 PC에서 `hostname.exe` 실행해줘")
    assert ok is False
    assert command is None


def test_natural_pc_query_rejects_ordinary_prose() -> None:
    ok, command = _requested_natural_pc_query("안녕하세요")
    assert ok is False
    assert command is None


def test_natural_pc_query_rejects_execution_plan_prose() -> None:
    ok, command = _requested_natural_pc_query("내 PC에서 실행 계획을 알려줘")
    assert ok is False
    assert command is None
