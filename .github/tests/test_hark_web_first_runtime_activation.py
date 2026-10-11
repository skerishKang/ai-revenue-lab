"""Hark five-stage activation fail-closed tests; entirely offline."""
from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "hark_stage", ROOT / "scripts/hark_web_first_runtime_activation.py",
)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def settings(*bindings):
    return {"success": True, "result": {"bindings": list(bindings)}}


def plain(name, value="true"):
    return {"name": name, "type": "plain_text", "text": value}


def fixture(stage, *, ready_peer=True):
    worker, flags, prereqs, needed = mod.STAGES[stage]
    base = []
    for name in needed:
        if name == "WEB_XLSX_PRIVATE_B62_D1":
            base.append({"name": name, "type": "d1", "id": mod.B62_D1_ID})
        elif name == "ENGINE_CONTINUATION":
            base.append({"name": name, "type": "d1",
                         "id": "6b77ad02-bc27-488f-bb97-6325f6750cba"})
        elif name == "PADIEM_CHAT_DB":
            base.append({"name": name, "type": "d1", "id": mod.B62_D1_ID})
        elif name == "PADIEM_WORKSPACE_FILES":
            base.append({"name": name, "type": "r2_bucket",
                         "bucket_name": "padiem-workspace-files"})
        elif name == "P01_ENGINE_SERVICE":
            base.append({"name": name, "type": "service",
                         "service": "padiem-ai-engine"})
        elif name == "BROWSER":
            base.append({"name": name, "type": "browser"})
    base += [{"name": "P01_ENGINE_CREDENTIAL", "type": "secret_text"}]
    if stage == "chat_pdf":
        base += [plain("PADIEM_WEB_XLSX_QUOTE_WRITE_ENABLED")]
    peer = [plain(name) for name in prereqs] if ready_peer else []
    return settings(*base), settings(*peer)


@pytest.mark.parametrize("stage", tuple(mod.STAGES))
def test_every_stage_adds_exactly_approved_true_flags_and_preserves_everything(stage):
    before, peer = fixture(stage)
    target = mod.plan(stage, before, peer)
    old = before["result"]["bindings"]
    inherited = [b for b in target["bindings"] if b["type"] == "inherit"]
    additions = [b for b in target["bindings"] if b["type"] == "plain_text"]
    assert len(inherited) == len(old)
    assert {b["name"] for b in inherited} == {b["name"] for b in old}
    assert all(b["version_id"] == "latest" for b in inherited)
    assert {b["name"] for b in additions} == set(mod.STAGES[stage][1])
    assert {b["text"] for b in additions} == {"true"}
    assert not any(b["type"] == "secret_text" for b in target["bindings"])
    after = settings(*old, *additions)
    mod.verify(stage, before, after)
    with pytest.raises(mod.ActivationError, match="drift"):
        mod.verify(stage, before, settings(*old, *additions,
                                         {"name": "SURPRISE", "type": "secret_text"}))
    with pytest.raises(mod.ActivationError, match="drift"):
        mod.verify(stage, before, settings(*additions))


@pytest.mark.parametrize("stage", tuple(mod.STAGES))
def test_every_stage_refuses_bad_preconditions_and_existing_values(stage):
    before, peer = fixture(stage, ready_peer=False)
    if mod.STAGES[stage][2]:
        with pytest.raises(mod.ActivationError, match="prerequisite"):
            mod.plan(stage, before, peer)
    before, peer = fixture(stage)
    first = mod.STAGES[stage][1][0]
    before["result"]["bindings"].append(plain(first, "false"))
    with pytest.raises(mod.ActivationError, match="rewrite"):
        mod.plan(stage, before, peer)
    before, peer = fixture(stage)
    before["result"]["bindings"] = [
        item for item in before["result"]["bindings"]
        if item["name"] != mod.STAGES[stage][3][0]
    ]
    with pytest.raises(mod.ActivationError, match="required live Worker"):
        mod.plan(stage, before, peer)


def test_private_db_alias_mismatch_and_browser_type_refused():
    engine, peer = fixture("engine_read")
    for item in engine["result"]["bindings"]:
        if item["name"] == "WEB_XLSX_PRIVATE_B62_D1":
            item["id"] = "00000000-0000-0000-0000-000000000001"
    with pytest.raises(mod.ActivationError, match="identity mismatch"):
        mod.plan("engine_read", engine, peer)
    chat, peer = fixture("chat_pdf")
    for item in chat["result"]["bindings"]:
        if item["name"] == "BROWSER":
            item["type"] = "plain_text"
            item["text"] = "fake"
    with pytest.raises(mod.ActivationError, match="Browser binding type"):
        mod.plan("chat_pdf", chat, peer)


def test_cli_never_overwrites_existing_plan_and_denies_fake_secret_authority(tmp_path, capsys):
    before, peer = fixture("engine_read")
    old = tmp_path / "before.json"
    peer_file = tmp_path / "peer.json"
    output = tmp_path / "output.json"
    old.write_text(json.dumps(before), encoding="utf-8")
    peer_file.write_text(json.dumps(peer), encoding="utf-8")
    args = ["plan", "--stage", "engine_read", "--before", str(old),
            "--peer", str(peer_file), "--output", str(output)]
    assert mod.main(args) == 0
    assert output.exists()
    assert mod.main(args) == 2
    printed = capsys.readouterr()
    assert "SECRET_VALUES_READ=0" in printed.out
    assert "BROWSER_QUICK_ACTION_CALLS=0" in printed.out


def test_workflow_has_protected_manual_only_mutation_and_rollback():
    workflow = (ROOT / "workflows/hark-web-first-runtime-activation.yml").read_text(
        encoding="utf-8"
    )
    assert "environment: production" in workflow
    assert "workflow_dispatch:" in workflow
    assert "CONFIRM_HARK_WEB_FIRST_" in workflow
    assert "hark_web_first_runtime_activation.py plan" in workflow
    assert "hark_web_first_runtime_activation.py verify" in workflow
    assert "POST" in workflow and "/deployments" in workflow
    assert "HARK_ROLLBACK_VERSION_ID" in workflow
    assert "HARK_PRODUCTION_STAGE=PASS" in workflow
    assert "BROWSER_QUICK_ACTION_CALLS=0" in workflow
    # workers/scripts/.../versions GET only provides metadata. Source
    # modules must come from a version-ID-bound workers/workers endpoint.
    # An absent pre-mutation byte manifest must block BEFORE any PATCH.
    read_step = workflow.split(
        "- name: Read actual 100-percent served target and peer authority", 1
    )[1].split("- name: Build additive exact-only patch", 1)[0]
    verify_step = workflow.split(
        "- name: Verify newly served immutable Worker", 1
    )[1].split("- name: Auto rollback", 1)[0]
    assert "workers/workers/${worker}/versions/${active}" in read_step
    assert "HARK_PREMUTATION_VERSION_MODULES=PASS" in read_step
    assert "_version_module_manifest" in read_step
    assert "workers/workers/${WORKER}/versions/${active}" in verify_step
    assert "assert_exact_worker_code" in verify_step
    # Cloudflare's versioned Worker API defaults to metadata-only. Explicit
    # include=modules is required for the base64 source byte manifest.
    # Check both preflight (before PATCH) and postflight (before success).
    assert 'workers/workers/${worker}/versions/${active}?include=modules"' in read_step
    assert 'workers/workers/${WORKER}/versions/${active}?include=modules"' in verify_step
    assert (read_step + verify_step).count("?include=modules") == 2

    assert "PADIEM_WEB_XLSX_QUOTE_PDF_ENABLED" not in workflow  # flags owned by script
    # Previous production engine_read run 38118608721 failed at curl(2):
    # the PATCH omitted its target URL, then requested rollback even though
    # nothing reached Cloudflare. Guard the *actual* live PATCH command, not
    # only the offline planner.
    mutation = workflow.split(
        "- name: Apply only reviewed live-inherit and approved flag additions", 1
    )[1].split("- name: Verify newly served immutable Worker", 1)[0]
    assert 'api="https://api.cloudflare.com/client/v4/accounts/' in mutation
    assert '-X PATCH' in mutation
    assert """-w '%{http_code}' \\
            "${api}")""" in mutation


def test_prepatch_cloudflare_module_authority_step_parses_with_actual_bash():
    """Catch malformed nested shell here-docs before *any* production run."""
    bash = shutil.which("bash")
    if sys.platform == "win32":
        # Windows may resolve 'bash' to WSL, not a Bash shell capable of
        # parsing this workflow. Prefer Git-for-Windows installed with git.
        git = shutil.which("git")
        git_bash = Path(git).resolve().parent.parent / "bin" / "bash.exe" if git else None
        bash = str(git_bash) if git_bash and git_bash.is_file() else None
    if not bash:
        pytest.skip("Requires Bash for GitHub Actions ubuntu shell parsing")
    workflow = (ROOT / "workflows/hark-web-first-runtime-activation.yml").read_text(
        encoding="utf-8"
    )
    block = workflow.split(
        "- name: Read actual 100-percent served target and peer authority", 1
    )[1].split("- name: Build additive exact-only patch", 1)[0]
    assert "python -c '" in block
    assert "<<'PY'" not in block
    script = textwrap.dedent(block.split("        run: |", 1)[1]).strip()
    completed = subprocess.run(
        [bash, "-n"], input=script, text=True, encoding="utf-8",
        errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
