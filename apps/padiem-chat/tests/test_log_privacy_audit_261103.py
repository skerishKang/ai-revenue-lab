from app.claw_live_events import _adapter_failure_log_line
from app.oracle_mesh_read_return_routes import _identity_bridge_failure_log_line


def test_pc_failure_logs_emit_only_closed_stage_metadata(capsys):
    print(_adapter_failure_log_line("private@example.invalid-token"))
    print(_identity_bridge_failure_log_line("private@example.invalid-token"))
    output = capsys.readouterr().out

    assert "claw_live_adapter_failure terminal=unknown" in output
    assert "claw_engine_bridge_stage stage=unknown result=failed" in output
    for marker in ("private@example.invalid", "token", "cookie", "authorization"):
        assert marker not in output
