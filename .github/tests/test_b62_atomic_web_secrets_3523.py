"""#3523: network-free exact-key, additive-only production binding tests."""
import importlib.util
import json
import sys
import tomllib
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".github" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from b62_web_secrets_store_contract import (
    expected_web_secret_bindings, require_exact_web_secrets_store
)


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    m = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(m)
    return m


def config(tmp_path):
    p = tmp_path / "wrangler.toml"
    p.write_text(
        'name = "padiem-chat"\nmain = "worker.py"\ncompatibility_date = "2026-08-25"\n'
        'compatibility_flags = ["python_workers"]\n'
        '[assets]\ndirectory = "static"\nbinding = "ASSETS"\n'
        '[vars]\nPADIEM_CHAT_RUNTIME_MODE = "mock"\nPADIEM_CHAT_LIVE_ENABLED = "false"\n',
        encoding="utf-8",
    )
    return p


def baseline():
    return [
        {"type":"assets","name":"ASSETS"},
        {"type":"d1","name":"PADIEM_CHAT_DB","id":"test-d1"},
        {"type":"secret_text","name":"PADIEM_CHAT_QUOTA_SALT"},
        {"type":"secret_text","name":"P01_ENGINE_CREDENTIAL"},
        {"type":"plain_text","name":"PADIEM_CHAT_RUNTIME_MODE","text":"b14"},
        {"type":"plain_text","name":"PADIEM_CHAT_LIVE_ENABLED","text":"true"},
        {"type":"plain_text","name":"PADIEM_CHAT_PUBLIC_BASE_URL","text":"https://chat.padiem.net"},
    ]


def envelope(bindings):
    return {"success":True,"result":{"bindings":bindings}}


def test_new_production_config_adds_exact_two_without_changing_others(tmp_path):
    mod = load("b62_cloudflare_production_deploy_config")
    before = baseline()
    live = mod.parse_live_bindings(envelope(before))
    output = mod.build_production_config(
        live, config(tmp_path), "https://chat.padiem.net", attach_web_secrets_store=True
    )
    parsed = tomllib.loads(output)
    expected = expected_web_secret_bindings()
    assert parsed["secrets_store_secrets"] == [
        {"binding":v["name"],"store_id":v["store_id"],"secret_name":v["secret_name"]}
        for v in expected.values()
    ]
    assert mod.verify_mutation_zero(output, live) is None
    unchanged = mod.build_production_config(live, config(tmp_path), "https://chat.padiem.net")
    assert "secrets_store_secrets" not in unchanged
    assert len(live["secret_names"]) == 2


def test_existing_exact_bindings_remain_idempotent_and_wrong_collisions_fail(tmp_path):
    mod = load("b62_cloudflare_production_deploy_config")
    exact = list(expected_web_secret_bindings().values())
    live = mod.parse_live_bindings(envelope(baseline() + exact))
    result = mod.build_production_config(live, config(tmp_path), "https://chat.padiem.net",
                                         attach_web_secrets_store=True)
    assert len(tomllib.loads(result)["secrets_store_secrets"]) == 2
    corrupt = [{**exact[0], "store_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]
    bad = mod.parse_live_bindings(envelope(baseline() + corrupt))
    with pytest.raises(mod.ProductionConfigError):
        mod.build_production_config(bad, config(tmp_path), "https://chat.padiem.net",
                                    attach_web_secrets_store=True)
    for bad_kind in ("plain_text", "secret_text"):
        conflict = baseline() + [{"name":"TINYFISH_API_KEY","type":bad_kind,
                                 **({"text":"bad"} if bad_kind=="plain_text" else {})}]
        live = mod.parse_live_bindings(envelope(conflict))
        with pytest.raises(mod.ProductionConfigError):
            mod.build_production_config(live, config(tmp_path), "https://chat.padiem.net",
                                        attach_web_secrets_store=True)


def test_binding_guard_only_two_approved_additions():
    mod = load("b62_binding_state_guard")
    base = baseline()
    exact = list(expected_web_secret_bindings().values())
    mod.assert_web_secret_additions_only(envelope(base), envelope(base + exact))
    mod.assert_web_secret_additions_only(envelope(base + exact), envelope(base + exact))
    for bad in [
        base + exact[:1],
        base + exact + [{"type":"plain_text","name":"PADIEM_CHAT_EXTRA","text":"1"}],
        base + [{**base[0],"name":"ASSETS_MODIFIED"}] + exact,
        base + [{**exact[0],"store_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}, exact[1]],
    ]:
        with pytest.raises(mod.BindingStateError):
            mod.assert_web_secret_additions_only(envelope(base), envelope(bad))


def test_served_secret_guard_allows_only_exact_two_stored_ids():
    mod = load("b62_served_version_secret_guard")
    names = (("P01_ENGINE_CREDENTIAL","secret_text"), ("PADIEM_CHAT_QUOTA_SALT","secret_text"))
    base = [{"type":t,"name":n} for n,t in names]
    add = list(expected_web_secret_bindings().values())
    mod.verify_secret_set(names, base + add, allow_web_store_additions=True)
    with pytest.raises(mod.ServedVersionGuardError):
        mod.verify_secret_set(names, base + add)
    with pytest.raises(mod.ServedVersionGuardError):
        mod.verify_secret_set(names, base + add[:1], allow_web_store_additions=True)
    with pytest.raises(mod.ServedVersionGuardError):
        mod.verify_secret_set(names, base + add + [{"name":"NO","type":"secret_text"}],
                              allow_web_store_additions=True)
    with pytest.raises(mod.ServedVersionGuardError):
        mod.verify_secret_set(names, base + [{**add[0], "secret_name":"wrong"}, add[1]],
                              allow_web_store_additions=True)


def test_preexisting_other_secret_never_leaks_during_addition():
    expected = expected_web_secret_bindings()
    assert set(expected) == {"TINYFISH_API_KEY", "PADIEM_CHAT_DAUM_REST_API_KEY"}
    require_exact_web_secrets_store(list(expected.values()), allow_absent=False)
    with pytest.raises(ValueError):
        require_exact_web_secrets_store(list(expected.values())[:1], allow_absent=False)


def test_workflow_explicit_opt_in_pins_no_source_mode_and_checks_both_postconditions():
    text = (ROOT / ".github/workflows/b62-production-code-deploy-gate.yml").read_text(encoding="utf-8")
    assert "attach_existing_web_secrets_store:" in text
    assert "default: false" in text
    assert "--attach-existing-web-secrets-store" in text
    assert "--expected-add-web-secrets-store" in text
    assert "--allow-add-existing-web-secrets-store" in text
    assert 'if [ "${ATTACH_WEB_SECRETS_STORE}" = "true" ]; then' in text
