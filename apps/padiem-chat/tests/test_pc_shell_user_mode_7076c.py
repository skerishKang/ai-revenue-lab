"""#7076c chat: pc_shell user-mode switch and MCP argument rejection."""
from __future__ import annotations
import os

from app.config import Settings, ConfigError


def test_user_mode_switch_defaults_off_and_parses_true_false():
    os.environ.pop("PADIEM_MCP_PC_SHELL_ENABLED", None)
    os.environ.pop("PADIEM_MCP_PC_SHELL_USER_MODE", None)
    s = Settings.from_env()
    assert s.mcp_pc_shell_user_mode_enabled is False
    os.environ["PADIEM_MCP_PC_SHELL_USER_MODE"] = "true"
    s = Settings.from_env()
    assert s.mcp_pc_shell_user_mode_enabled is True
    os.environ["PADIEM_MCP_PC_SHELL_USER_MODE"] = "false"
    s = Settings.from_env()
    assert s.mcp_pc_shell_user_mode_enabled is False
    os.environ["PADIEM_MCP_PC_SHELL_USER_MODE"] = "nope"
    try:
        Settings.from_env(); ok=False
    except ConfigError:
        ok=True
    assert ok
    os.environ.pop("PADIEM_MCP_PC_SHELL_USER_MODE", None)


def test_mode_user_rejected_when_switch_off_execution_layer():
    import asyncio
    from types import SimpleNamespace
    from app import mcp_gateway_execution as ex
    req = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(mcp_pc_shell_enabled=True, mcp_pc_shell_user_mode_enabled=False), history_store=None, mcp_gateway_store=None)))
    out = asyncio.run(ex.execute_mcp_pc_tool(req, {"owner_id":"usr_"+"a"*32,"device_id":"dev_"+"b"*32,"token_id":"tok"}, "pc_shell", {"command":"whoami","mode":"user"}))
    assert out["status"] == "tool_not_enabled"
    assert out.get("deny_reason") == "pc_shell_user_mode_disabled"


def test_system_mode_path_unchanged_when_user_switch_off():
    # schema/normalization still accepts explicit system
    from app.mcp_gateway_shell import normalize_pc_shell_arguments
    n = normalize_pc_shell_arguments({"command":"whoami","mode":"system"})
    assert n["mode"] == "system"
