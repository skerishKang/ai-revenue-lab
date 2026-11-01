"""Execute the shipped settings module with DOM and account API fakes."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
STATIC = HERE.parent / "static"
NODE = shutil.which("node")


def test_settings_are_in_the_shared_chat_claw_dialog_with_accessible_localized_controls():
    html = (STATIC / "index.html").read_text()
    section = html[html.index('id="pcDelegationSettings"'):html.index('id="adminSettingsSection"')]
    assert 'aria-labelledby="pcDelegationTitle"' in section
    assert 'role="status" aria-live="polite"' in section
    assert '<form' not in section
    for control in ("Device", "Folder", "Mode"):
        assert f'for="pcDelegation{control}"' in section
    assert './pc-delegation-settings.js' in html
    assert './pc-delegation-settings.css' in html
    assert 'pc-delegation-send-note' in section


def test_every_delegation_copy_key_has_both_locales_and_send_is_not_an_action():
    locale = (STATIC / "locale.js").read_text()
    ko, en = locale.split('    en: {', 1)
    keys = set(re.findall(r'"(pc-delegation-[^"]+)":', ko))
    assert len(keys) >= 30
    assert keys <= set(re.findall(r'"(pc-delegation-[^"]+)":', en))
    source = (STATIC / "pc-delegation-settings.js").read_text()
    assert 'const ACTIONS = ["write", "move", "delete"]' in source
    assert set(re.findall(r'copy\("(pc-delegation-[^"]+)"\)', source)) <= keys


@pytest.mark.skipif(NODE is None, reason="node is required for the DOM harness")
def test_account_settings_flow():
    result = subprocess.run(
        [NODE, str(HERE / "pc_delegation_settings_harness.js"), str(STATIC / "pc-delegation-settings.js")],
        text=True, capture_output=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PC_DELEGATION_SETTINGS=PASS" in result.stdout
    assert result.stdout.count("PC_DELEGATION_CHECK") == 10
