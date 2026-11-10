"""The tool serialization check runs in the service's own runtime environment.

COM2 실측(#7088 후속, main 4b5676b4): the check ran against the staged tree
without the service's EnvironmentFile, so the app import chain failed and the
verdict was tool_declarations_import_failed — a harness mismatch reported as
a product FAIL. These tests drive the check script the way the deploy does:
a tmp installed root (app/ + .env) + the service's own interpreter, via
subprocess with the exact --app-root/--env-file arguments.

Verdict contract (CTO 2026-11-08):
  PASS  the payload serializes (exit 0)
  FAIL  the payload does not serialize (exit 1 — deploy stops)
  ERROR the check's own harness could not run (exit 2 — deploy continues,
        summary warning)
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".github" / "scripts" / "post_deploy_tool_serialization_check.py"
SPEC = importlib.util.spec_from_file_location("post_deploy_tool_serialization_check", SCRIPT)
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)

CHAT_APP_ROOT = ROOT / "apps" / "padiem-chat"

# The check script runs a real interpreter against an installed app root whose
# tool declarations import the repo's canonical packages, so pass this
# checkout's package sources explicitly (same set as #7322).
_SUBPROCESS_SOURCE_PATHS = (
    ROOT / "apps" / "padiem-chat",
    ROOT / "apps" / "korean-ai-code-agent" / "src",
    ROOT / "packages" / "padiem-ai-core",
    ROOT / "packages" / "padiem-control-plane",
    ROOT / "apps" / "padiem-ai-engine" / "clients" / "python",
)

NL = chr(10)

PLAIN_TOOLS = (
    "from padiem_ai_core.tool_channel import ToolDefinition" + NL
    + "CONNECTOR_TOOL_DECLARATIONS = (ToolDefinition(name='demo_tool'),)" + NL
)
FROZEN_TOOLS = (
    "from types import MappingProxyType" + NL
    + "from padiem_ai_core.tool_channel import ToolDefinition" + NL
    + "_inner = MappingProxyType({'type': 'string', 'format': MappingProxyType({'enum': ['a']})})" + NL
    + "_schema = MappingProxyType({'type': 'object', 'properties': MappingProxyType({"
    + "'query': _inner})})" + NL
    + "CONNECTOR_TOOL_DECLARATIONS = (ToolDefinition(name='demo_tool', parameters=_schema))" + NL
)
ENV_DEPENDING_TOOLS = (
    "import os" + NL
    + "_required = os.environ['PADIEM_TEST_REQUIRED_VAR']" + NL
    + "from padiem_ai_core.tool_channel import ToolDefinition" + NL
    + "CONNECTOR_TOOL_DECLARATIONS = (ToolDefinition(name='demo_tool'),)" + NL
)
EMPTY_TOOLS = "CONNECTOR_TOOL_DECLARATIONS = ()" + NL
BROKEN_IMPORT = "raise RuntimeError('broken installed tree')" + NL


def _build_root(tmp_path: Path, tools_body: str, env_lines: list[str]) -> tuple[Path, Path]:
    root = tmp_path / "chat-root"
    (root / "app").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "app" / "chat_connector_tools.py").write_text(tools_body, encoding="utf-8")
    (root / ".env").write_text(NL.join(env_lines) + NL, encoding="utf-8")
    return root, root / ".env"


def _run(script_args: list[str]) -> tuple[int, str, str]:
    env = os.environ.copy()
    existing_path = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join(str(p) for p in _SUBPROCESS_SOURCE_PATHS) + (
        os.pathsep + existing_path if existing_path else "")
    process = subprocess.run(
        [sys.executable, str(SCRIPT), *script_args],
        env=env,
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    lines = [l for l in process.stdout.splitlines() if l.startswith("TOOLS_SERIALIZATION=")]
    return process.returncode, (lines[-1] if lines else ""), process.stdout


def test_a_connected_environment_passes(tmp_path):
    root, env_file = _build_root(tmp_path, PLAIN_TOOLS, ["PADIEM_TEST_REQUIRED_VAR=ok"])
    code, line, _out = _run(["--app-root", str(root), "--env-file", str(env_file)])
    assert code == 0
    assert line == "TOOLS_SERIALIZATION=PASS"


def test_a_frozen_schema_fails_the_deploy(tmp_path):
    root, env_file = _build_root(tmp_path, FROZEN_TOOLS, ["PADIEM_TEST_REQUIRED_VAR=ok"])
    code, line, _out = _run(["--app-root", str(root), "--env-file", str(env_file)])
    assert code == 1
    assert "TOOLS_SERIALIZATION=FAIL code=tool_payload_serialization_failed" in line


def test_a_missing_service_env_reports_error_not_fail(tmp_path):
    root, _env = _build_root(tmp_path, ENV_DEPENDING_TOOLS, [])
    code, line, _out = _run(["--app-root", str(root)])
    assert code == 2
    assert "TOOLS_SERIALIZATION=ERROR code=import_failed:" in line
    assert "KeyError" in line


def test_the_env_file_restores_the_import(tmp_path):
    root, env_file = _build_root(tmp_path, ENV_DEPENDING_TOOLS, ["PADIEM_TEST_REQUIRED_VAR=ok"])
    code, line, out = _run(["--app-root", str(root), "--env-file", str(env_file)])
    assert code == 0
    assert "TOOLS_SERIALIZATION=PASS" in line
    assert "TOOLS_SERIALIZATION_ENV_FILE=applied_vars=" in out


def test_an_empty_declaration_list_is_a_harness_error(tmp_path):
    verdict_, code = check.verdict(_build_root(tmp_path, EMPTY_TOOLS, [])[0])
    assert verdict_ == "ERROR" and code == "no_connector_tools_declared"


def test_an_import_failure_in_process_is_an_error(tmp_path):
    verdict_, code = check.verdict(_build_root(tmp_path, BROKEN_IMPORT, [])[0])
    assert verdict_ == "ERROR" and code.startswith("import_failed:")


CWD_TOOLS = (
    "from pathlib import Path" + NL
    + "Path('cwd_marker.txt').read_text(encoding='utf-8')" + NL
    + "from padiem_ai_core.tool_channel import ToolDefinition" + NL
    + "CONNECTOR_TOOL_DECLARATIONS = (ToolDefinition(name='demo_tool'),)" + NL
)


def test_the_import_runs_from_the_service_working_directory(tmp_path):
    """padiem-chat-com2.service runs with WorkingDirectory=<installed root>; an
    import that reads a relative path must see that directory, not the
    operator's current one."""
    root, _env = _build_root(tmp_path, CWD_TOOLS, [])
    (root / "cwd_marker.txt").write_text("ok", encoding="utf-8")
    code, line, _out = _run(["--app-root", str(root)])
    assert code == 0
    assert line == "TOOLS_SERIALIZATION=PASS"
