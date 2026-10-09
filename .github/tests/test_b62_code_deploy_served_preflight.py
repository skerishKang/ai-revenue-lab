"""#3523: new exact-main deployment allows pre-existing unactivated uploads.

All checks are offline and do not use Cloudflare credentials or modify a Worker.
"""
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".github" / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location(
    "b62_code_deploy_served_preflight", SCRIPTS / "b62_code_deploy_served_preflight.py"
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ACTIVE = "11111111-1111-1111-1111-111111111111"
UPLOADED = "22222222-2222-2222-2222-222222222222"


@pytest.mark.parametrize("active,latest", [(ACTIVE, ACTIVE), (ACTIVE, UPLOADED)])
def test_safe_ids_are_accepted_without_requiring_equality(active, latest, capsys):
    assert module.main(["--active-version", active, "--latest-version", latest]) == 0
    text = capsys.readouterr().out
    assert "NEW_MAIN_DEPLOY_VERSION_PREFLIGHT=PASS" in text
    assert "PRODUCTION_MUTATION=0" in text
    assert "UNDEPLOYED_UPLOAD_PRESENT=" in text


@pytest.mark.parametrize("active,latest", [
    ("", UPLOADED), (ACTIVE, ""), ("malformed version", UPLOADED),
    (ACTIVE, "bad;id"), ("x" * 70, ACTIVE),
])
def test_missing_or_unsafe_ids_fail_closed(active, latest, capsys):
    assert module.main(["--active-version", active, "--latest-version", latest]) != 0
    assert "FAIL_CLOSED" in capsys.readouterr().out


def test_workflow_allows_mismatch_only_for_new_code_and_pins_both_ids():
    text = (ROOT / ".github/workflows/b62-production-code-deploy-gate.yml").read_text(encoding="utf-8")
    readonly = text.split("\n  cloudflare-readonly:", 1)[1].split("\n  deploy-production-code:", 1)[0]
    deploy = text.split("\n  deploy-production-code:", 1)[1]
    assert 'if [ "${{ inputs.mode }}" = "deploy_production_code" ]; then' in readonly
    assert "b62_code_deploy_served_preflight.py" in readonly
    assert "cloudflare_served_version_lineage.py" in readonly
    assert readonly.index("b62_code_deploy_served_preflight.py") < readonly.index("cloudflare_served_version_lineage.py")
    assert 'echo "latest_version=${latest}" >> "${GITHUB_OUTPUT}"' in readonly
    assert "READONLY_LATEST_VERSION: ${{ needs.cloudflare-readonly.outputs.latest_version }}" in deploy
    assert 'test "${current_latest}" = "${READONLY_LATEST_VERSION}"' in deploy
    assert "PREMUTATION_LATEST_UPLOADED_VERSION_STABLE=PASS" in deploy
    assert 'test "${active}" = "${READONLY_ACTIVE_VERSION}"' in deploy
    assert "PREMUTATION_EXACT_MAIN_SHA=PASS" in deploy
    assert "NEW_VERSION_ACTIVE=PASS" in deploy
