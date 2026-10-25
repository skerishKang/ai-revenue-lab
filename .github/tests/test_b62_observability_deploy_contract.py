"""#5700: pure B62 deploy metadata/read-only contracts; no app conftest or live API."""
from pathlib import Path
import json
import runpy

import pytest

# Reuse the existing pure generator regression fixtures without collecting
# the Chat application test tree and its HTTP/runtime conftest dependencies.
_FIXTURES = runpy.run_path(str(Path(__file__).resolve().parents[2]
                             / "apps/padiem-chat/tests/test_b62_production_deploy_config.py"))
_load_module = _FIXTURES["_load_module"]
_settings_payload = _FIXTURES["_settings_payload"]
_production_bindings = _FIXTURES["_production_bindings"]
_write_repo_config = _FIXTURES["_write_repo_config"]
_read_workflow = _FIXTURES["_read_workflow"]
PUBLIC_URL = _FIXTURES["PUBLIC_URL"]


@pytest.mark.parametrize("enabled,rate,logs_enabled,invocation_logs", [
    (True, 1, True, True),
    (True, 0.25, True, False),
    (False, 0, False, False),
])
def test_observability_reaches_pywrangler_config_without_changing_bindings(
    tmp_path, enabled, rate, logs_enabled, invocation_logs,
):
    import tomllib
    module = _load_module()
    path = _write_repo_config(tmp_path)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"\n[observability]\nenabled = {str(enabled).lower()}\nhead_sampling_rate = {rate}\n"
                     f"[observability.logs]\nenabled = {str(logs_enabled).lower()}\n"
                     f"invocation_logs = {str(invocation_logs).lower()}\n")
    settings = _settings_payload(_production_bindings())
    settings["result"]["observability"] = {"enabled": not enabled, "head_sampling_rate": 0.75}
    live = module.parse_live_bindings(settings)
    generated = module.build_production_config(live, path, PUBLIC_URL)
    parsed = tomllib.loads(generated)
    assert parsed["observability"] == tomllib.loads(path.read_text())["observability"]
    module.verify_mutation_zero(generated, live)
    assert "secret_text" not in generated


def test_observability_real_repository_settings_survive_production_generation():
    import tomllib
    module = _load_module()
    repo = Path(__file__).resolve().parents[2] / "apps/padiem-chat/wrangler.toml"
    live = module.parse_live_bindings(_settings_payload(_production_bindings()))
    generated = module.build_production_config(live, repo, PUBLIC_URL)
    assert tomllib.loads(generated)["observability"] == tomllib.loads(repo.read_text())["observability"]
    module.verify_mutation_zero(generated, live)


@pytest.mark.parametrize("declaration", [
    "enabled = 'true'", "enabled = true\nhead_sampling_rate = true",
    "enabled = true\nhead_sampling_rate = 1.1", "enabled = true\nhead_sampling_rate = nan",
    "enabled = true\n[observability.logs]\nenabled = 'true'",
])
def test_observability_invalid_config_is_not_silently_dropped(tmp_path, declaration):
    module = _load_module()
    path = _write_repo_config(tmp_path)
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\n[observability]\n" + declaration + "\n")
    live = module.parse_live_bindings(_settings_payload(_production_bindings()))
    with pytest.raises(module.ProductionConfigError, match="observability"):
        module.build_production_config(live, path, PUBLIC_URL)


@pytest.mark.parametrize("observability", [None, {"enabled": False, "head_sampling_rate": 0},
    {"enabled": True, "head_sampling_rate": 1, "logs": {"enabled": True, "invocation_logs": True}},
])
def test_observability_readonly_reports_live_state_without_mutation_or_secret_values(tmp_path, observability):
    import subprocess
    workflow = _read_workflow()
    readonly = workflow.split("\n  cloudflare-readonly:", 1)[1].split("\n  deploy-production-code:", 1)[0]
    command, = [line.strip() for line in readonly.splitlines() if "B62_LIVE_OBSERVABILITY=" in line]
    settings = _settings_payload(_production_bindings())
    settings["result"]["observability"] = observability
    settings["result"]["bindings"].append({"type": "secret_text", "name": "SYNTHETIC", "text": "never-print-me"})
    snapshot = tmp_path / "settings.json"
    snapshot.write_text(json.dumps(settings))
    before = snapshot.read_bytes()
    result = subprocess.run(["bash", "-eu", "-o", "pipefail", "-c", 'settings="$1"; ' + command, "audit", str(snapshot)],
                            capture_output=True, text=True, check=True)
    label, value = result.stdout.strip().split("=", 1)
    assert label == "B62_LIVE_OBSERVABILITY"
    reported = json.loads(value)
    assert reported["enabled"] == (observability or {}).get("enabled")
    assert reported["head_sampling_rate"] == (observability or {}).get("head_sampling_rate")
    assert reported["logs"]["invocation_logs"] == ((observability or {}).get("logs") or {}).get("invocation_logs")
    assert "never-print-me" not in result.stdout
    assert snapshot.read_bytes() == before


def test_observability_gate_tests_and_all_deploy_attempts_use_the_generated_config():
    workflow = _read_workflow()
    source = workflow.split("\n  source-contract:", 1)[1].split("\n  cloudflare-readonly:", 1)[0]
    assert "python -m pytest .github/tests/test_b62_observability_deploy_contract.py -q" in source
    package = workflow.split("\n      - name: Package production bundle without deploying", 1)[1].split("\n      - name: Deploy production code preserving the full binding set", 1)[0]
    assert "--config wrangler.production.generated.toml" in package
    deploy = workflow.split("\n      - name: Deploy production code preserving the full binding set", 1)[1].split("\n      - name: Read back exact post-deploy binding and variable state", 1)[0]
    assert 'generated="wrangler.production.generated.toml"' in deploy
    assert deploy.count('--config "${generated}"') == deploy.count("pywrangler deploy") == 3
