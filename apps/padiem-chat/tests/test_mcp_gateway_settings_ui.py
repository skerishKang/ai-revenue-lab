"""Exercise the shipped token/approval settings code without issuing real tokens."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
STATIC = HERE.parent / "static"
NODE = shutil.which("node")


def test_mcp_settings_use_the_shared_dialog_and_accessible_controls():
    html = (STATIC / "index.html").read_text()
    section = html[html.index('id="mcpGatewaySettings"'):html.index('id="adminSettingsSection"')]
    assert 'aria-labelledby="mcpGatewayTitle"' in section
    assert 'role="status" aria-live="polite"' in section
    assert '<form' not in section
    for name in ("Endpoint", "Name", "Device", "Token"):
        assert f'for="mcpGateway{name}"' in section
    assert './mcp-gateway-settings.js' in html
    assert './mcp-gateway-settings.css' in html
    assert 'aria-describedby="mcpGatewayTokenHelp"' in section
    assert 'mcp-settings-once' in section


def test_all_mcp_settings_copy_and_exact_operation_labels_are_localized():
    locale = (STATIC / "locale.js").read_text()
    ko, en = locale.split('    en: {', 1)
    keys = set(re.findall(r'"(mcp-settings-[^"]+)":', ko))
    assert keys == set(re.findall(r'"(mcp-settings-[^"]+)":', en))
    source = (STATIC / "mcp-gateway-settings.js").read_text()
    css = (STATIC / "mcp-gateway-settings.css").read_text()
    html = (STATIC / "index.html").read_text()
    used = set(re.findall(r'"(mcp-settings-[a-z-]+)"', source))
    used |= set(re.findall(r'data-locale-[\w-]+="(mcp-settings-[^"]+)"', html))
    classes = set(re.findall(r'\.(mcp-settings-[a-z-]+)', css))
    assert used - classes <= keys
    assert {"mcp-settings-content", "mcp-settings-source", "mcp-settings-destination", "mcp-settings-path"} <= keys


@pytest.mark.skipif(NODE is None, reason="node is required for the DOM harness")
def test_personal_tokens_and_exact_request_approvals_in_the_settings_module():
    result = subprocess.run(
        [NODE, str(HERE / "mcp_gateway_settings_harness.js"), str(STATIC / "mcp-gateway-settings.js")],
        text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "MCP_GATEWAY_SETTINGS=PASS" in result.stdout
    assert result.stdout.count("MCP_GATEWAY_CHECK") == 14
