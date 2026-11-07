"""The deploy-time tool serialization check catches the frozen-schema class."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import MappingProxyType

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / ".github" / "scripts" / "post_deploy_tool_serialization_check.py"
SPEC = importlib.util.spec_from_file_location("post_deploy_tool_serialization_check", SCRIPT)
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)

CHAT_APP_ROOT = ROOT / "apps" / "padiem-chat"


def _staged_app(tmp_path: Path, body: str) -> Path:
    app = tmp_path / "app"
    app.mkdir()
    (app / "__init__.py").write_text("", encoding="utf-8")
    (app / "chat_connector_tools.py").write_text(body, encoding="utf-8")
    return tmp_path


REGISTRY_TOOLS_IMPORT = (
    "from padiem_ai_core.tool_channel import ToolDefinition\n"
    "CONNECTOR_TOOL_DECLARATIONS = (ToolDefinition(name='demo_tool'),)\n"
)
FROZEN_NESTED_IMPORT = (
    "from types import MappingProxyType\n"
    "from padiem_ai_core.tool_channel import ToolDefinition\n"
    "_inner = MappingProxyType({'type': 'string', 'format': MappingProxyType({'enum': ['a']})})\n"
    "_schema = MappingProxyType({'type': 'object', 'properties': MappingProxyType({\n"
    "    'query': _inner,\n"
    "})})\n"
    "CONNECTOR_TOOL_DECLARATIONS = (ToolDefinition(name='demo_tool', parameters=_schema),)\n"
)


@pytest.fixture(autouse=True)
def _app_importable():
    """The chat venv can import the staged app modules (same as the service)."""
    sys.path.insert(0, str(CHAT_APP_ROOT))
    yield
    sys.modules.pop("app.chat_connector_tools", None)
    sys.modules.pop("app", None)


def test_a_plain_tool_payload_serializes_pass(tmp_path):
    assert check.verdict(_staged_app(tmp_path, REGISTRY_TOOLS_IMPORT)) == ("PASS", "none")


def test_a_frozen_nested_schema_fails_with_the_bounded_code(tmp_path):
    """The measured #7088 후속 failure: a frozen nested schema is the bug."""
    verdict_, code = check.verdict(_staged_app(tmp_path, FROZEN_NESTED_IMPORT))
    assert verdict_ == "FAIL" and code == "tool_payload_serialization_failed"


def test_an_empty_declaration_list_fails_closed(tmp_path):
    assert check.verdict(_staged_app(tmp_path, "CONNECTOR_TOOL_DECLARATIONS = ()\n")) == (
        "FAIL", "no_connector_tools_declared")


def test_an_import_failure_fails_closed(tmp_path):
    assert check.verdict(_staged_app(tmp_path, "raise RuntimeError('broken staged tree')\n")) == (
        "FAIL", "tool_declarations_import_failed")
