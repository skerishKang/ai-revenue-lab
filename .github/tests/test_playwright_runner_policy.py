"""Playwright browser installers must not float to an unsupported hosted image."""
from pathlib import Path
import re
import subprocess
import sys

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / "workflows"
BROWSER_INSTALL = re.compile(r'\bplaywright(?:@[\w.-]+)?["\']?\s+install(?:-deps)?\b', re.I)


def browser_jobs(document):
    for name, job in document.get("jobs", {}).items():
        if any(BROWSER_INSTALL.search(step.get("run", "")) for step in job.get("steps", [])):
            yield name, job


def hosted_image_is_pinned(job):
    runner = str(job.get("runs-on"))
    matrix = str(job.get("strategy", {}).get("matrix", {}))
    return "ubuntu-latest" not in runner + matrix and (
        "ubuntu-24.04" in runner + matrix or "self-hosted" in runner
    )


def test_all_playwright_install_jobs_pin_hosted_ubuntu():
    installers = []
    for file in sorted(WORKFLOWS.glob("*.y*ml")):
        for name, job in browser_jobs(yaml.safe_load(file.read_text(encoding="utf-8")) or {}):
            installers.append((file.name, name))
            assert hosted_image_is_pinned(job), (file.name, name, job["runs-on"])
            if "self-hosted" in str(job["runs-on"]):
                assert any("b62_playwright_host_platform.sh" in step.get("run", "")
                           for step in job["steps"]), (file.name, name)
    assert len(installers) >= 40
    assert ("b62-padiem-chat-ci.yml", "b62-tests-only-tests") in installers


@pytest.mark.parametrize("runner,matrix", [
    ("ubuntu-latest", {}),
    ("$\u007b\u007b matrix.os \u007d\u007d", {"os": ["ubuntu-latest", "windows-latest"]}),
    ("$\u007b\u007b condition && fromJSON('[\"self-hosted\"]') || 'ubuntu-latest' \u007d\u007d", {}),
])
def test_policy_rejects_floating_hosted_image(runner, matrix):
    job = {"runs-on": runner, "strategy": {"matrix": matrix},
           "steps": [{"run": "uv run playwright install --only-shell chromium"}]}
    assert list(browser_jobs({"jobs": {"browser": job}})) == [("browser", job)]
    assert not hosted_image_is_pinned(job)



@pytest.mark.skipif(sys.platform != "linux", reason="Linux runner platform setup")
@pytest.mark.parametrize("os_id,version,arch,expected", [
    ("ubuntu", "26.04", "x86_64", "PLAYWRIGHT_HOST_PLATFORM_OVERRIDE=ubuntu24.04-x64\n"),
    ("ubuntu", "24.04", "x86_64", ""),
    ("ubuntu", "26.04", "aarch64", ""),
    ("debian", "13", "x86_64", ""),
])
def test_self_hosted_platform_override(os_id, version, arch, expected, tmp_path):
    script = WORKFLOWS.parent / "scripts/b62_playwright_host_platform.sh"
    env_file = tmp_path / "github-env"
    env_file.touch()
    # Replace only OS/architecture probes; run the actual platform setup script.
    subprocess.run(["bash", "-c", """
      fixture_os=$1; fixture_version=$2; fixture_arch=$3
      source() { ID="$fixture_os"; VERSION_ID="$fixture_version"; }
      uname() { printf '%s\\n' "$fixture_arch"; }
      export GITHUB_ENV="$4"
      . "$5"
    """, "fixture", os_id, version, arch, str(env_file), str(script)], check=True)
    assert env_file.read_text(encoding="utf-8") == expected
