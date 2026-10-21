"""#5224: the B62 production deploy gate must be able to attach the one
deployment-owned B14 caller-proof Secrets Store reference.

B62 signs its B14 dispatch with this reference. The B62 deploy config is
generated from the LIVE binding set, so a new repository-declared Secrets
Store reference reaches Production only through an explicit, owner-authorized
attach mode with its own confirmation phrase. These tests are network-free.
"""
from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".github" / "scripts"
sys.path.insert(0, str(SCRIPTS))
from b62_web_secrets_store_contract import expected_b14_service_proof_bindings

WORKFLOW = ROOT / ".github" / "workflows" / "b62-production-code-deploy-gate.yml"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def repo_config(tmp_path):
    path = tmp_path / "wrangler.toml"
    path.write_text(
        'name = "padiem-chat"\nmain = "worker.py"\ncompatibility_date = "2026-08-25"\n'
        'compatibility_flags = ["python_workers"]\n'
        '[assets]\ndirectory = "static"\nbinding = "ASSETS"\n'
        '[vars]\nPADIEM_CHAT_RUNTIME_MODE = "mock"\nPADIEM_CHAT_LIVE_ENABLED = "false"\n'
        '[[secrets_store_secrets]]\nbinding = "PADIEM_B14_SERVICE_PROOF_SECRET"\n'
        'store_id = "f0b09ca04a7b43248154c773704a5616"\n'
        'secret_name = "PADIEM_B14_SERVICE_PROOF_SECRET"\n',
        encoding="utf-8",
    )
    return path


def baseline():
    return [
        {"type": "assets", "name": "ASSETS"},
        {"type": "d1", "name": "PADIEM_CHAT_DB", "id": "test-d1"},
        {"type": "secret_text", "name": "PADIEM_CHAT_QUOTA_SALT"},
        {"type": "secret_text", "name": "P01_ENGINE_CREDENTIAL"},
        {"type": "plain_text", "name": "PADIEM_CHAT_RUNTIME_MODE", "text": "b14"},
        {"type": "plain_text", "name": "PADIEM_CHAT_LIVE_ENABLED", "text": "true"},
        {
            "type": "plain_text",
            "name": "PADIEM_CHAT_PUBLIC_BASE_URL",
            "text": "https://chat.padiem.net",
        },
    ]


def envelope(bindings):
    return {"success": True, "result": {"bindings": bindings}}


def proof_binding():
    return dict(expected_b14_service_proof_bindings()["PADIEM_B14_SERVICE_PROOF_SECRET"])


def test_generated_config_adds_only_the_exact_proof_reference(tmp_path):
    mod = load("b62_cloudflare_production_deploy_config")
    live = mod.parse_live_bindings(envelope(baseline()))
    output = mod.build_production_config(
        live,
        repo_config(tmp_path),
        "https://chat.padiem.net",
        attach_b14_service_proof_secret=True,
    )
    parsed = tomllib.loads(output)
    assert parsed["secrets_store_secrets"] == [
        {
            "binding": "PADIEM_B14_SERVICE_PROOF_SECRET",
            "store_id": "f0b09ca04a7b43248154c773704a5616",
            "secret_name": "PADIEM_B14_SERVICE_PROOF_SECRET",
        }
    ]
    assert mod.verify_mutation_zero(output, live) is None


def test_code_only_deploy_does_not_silently_add_the_proof_reference(tmp_path):
    """A code-only deploy must not mutate the live binding authority."""
    mod = load("b62_cloudflare_production_deploy_config")
    live = mod.parse_live_bindings(envelope(baseline()))
    output = mod.build_production_config(
        live, repo_config(tmp_path), "https://chat.padiem.net"
    )
    assert "secrets_store_secrets" not in tomllib.loads(output)


def test_attach_is_idempotent_when_the_reference_is_already_served(tmp_path):
    mod = load("b62_cloudflare_production_deploy_config")
    live = mod.parse_live_bindings(envelope(baseline() + [proof_binding()]))
    output = mod.build_production_config(
        live,
        repo_config(tmp_path),
        "https://chat.padiem.net",
        attach_b14_service_proof_secret=True,
    )
    assert len(tomllib.loads(output)["secrets_store_secrets"]) == 1


def test_attach_rejects_a_repository_declaration_with_another_identity(tmp_path):
    mod = load("b62_cloudflare_production_deploy_config")
    path = tmp_path / "wrangler.toml"
    path.write_text(
        'name = "padiem-chat"\nmain = "worker.py"\ncompatibility_date = "2026-08-25"\n'
        'compatibility_flags = ["python_workers"]\n'
        '[assets]\ndirectory = "static"\nbinding = "ASSETS"\n'
        '[vars]\nPADIEM_CHAT_RUNTIME_MODE = "mock"\nPADIEM_CHAT_LIVE_ENABLED = "false"\n'
        '[[secrets_store_secrets]]\nbinding = "PADIEM_B14_SERVICE_PROOF_SECRET"\n'
        'store_id = "00000000000000000000000000000000"\n'
        'secret_name = "PADIEM_B14_SERVICE_PROOF_SECRET"\n',
        encoding="utf-8",
    )
    live = mod.parse_live_bindings(envelope(baseline()))
    with pytest.raises(mod.ProductionConfigError):
        mod.build_production_config(
            live,
            path,
            "https://chat.padiem.net",
            attach_b14_service_proof_secret=True,
        )


def test_attach_mode_is_exclusive_with_every_other_additive_mode():
    mod = load("b62_cloudflare_production_deploy_config")
    with pytest.raises(mod.ProductionConfigError):
        mod.build_production_config(
            {"assets": [], "services": [], "d1": [], "r2": [], "vars": {},
             "secret_names": [], "secrets_store": [], "version_metadata": None,
             "browser": None},
            Path("wrangler.toml"),
            "https://chat.padiem.net",
            attach_b14_service_proof_secret=True,
            attach_claw_desktop_secret=True,
        )


def test_binding_guard_allows_only_the_exact_proof_addition():
    mod = load("b62_binding_state_guard")
    base = baseline()
    proof = proof_binding()
    mod.assert_exact_b14_service_proof_added_only(envelope(base), envelope(base + [proof]))
    mod.assert_exact_b14_service_proof_added_only(
        envelope(base + [proof]), envelope(base + [proof])
    )
    for bad in (
        [{**proof, "store_id": "00000000000000000000000000000000"}],
        [{**proof, "secret_name": "OTHER_SECRET"}],
        [{"type": "secret_text", "name": "UNRELATED"}],
    ):
        with pytest.raises(mod.BindingStateError):
            mod.assert_exact_b14_service_proof_added_only(
                envelope(base), envelope(base + bad)
            )


def test_served_version_secret_guard_allows_only_the_exact_proof_addition():
    mod = load("b62_served_version_secret_guard")
    proof = proof_binding()
    before = (
        ("PADIEM_CHAT_QUOTA_SALT", "secret_text"),
        ("P01_ENGINE_CREDENTIAL", "secret_text"),
    )
    post = [
        {"type": "secret_text", "name": "PADIEM_CHAT_QUOTA_SALT"},
        {"type": "secret_text", "name": "P01_ENGINE_CREDENTIAL"},
        proof,
    ]
    mod.verify_secret_set(before, post, allow_b14_service_proof_secret=True)
    with pytest.raises(mod.ServedVersionGuardError):
        mod.verify_secret_set(before, post)
    with pytest.raises(mod.ServedVersionGuardError):
        mod.verify_secret_set(
            before,
            post + [{"type": "secret_text", "name": "UNRELATED"}],
            allow_b14_service_proof_secret=True,
        )


def test_workflow_wires_the_explicit_attach_mode_and_confirmation():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "attach_existing_b14_service_proof_secret:" in workflow
    assert (
        "ATTACH_B14_SERVICE_PROOF_SECRET: "
        "${{ inputs.attach_existing_b14_service_proof_secret }}" in workflow
    )
    assert "DEPLOY_B62_B14_SERVICE_PROOF_SECRET_ATTACH_FROM_EXACT_MAIN" in workflow
    assert "extra_args=(--attach-existing-b14-service-proof-secret)" in workflow
    assert "verify_args=(--expected-add-b14-service-proof-secret)" in workflow
    assert (
        "verify_args=(--allow-add-existing-b14-service-proof-secret)" in workflow
    )
    assert "B14_SERVICE_PROOF_SECRET_SERVED_IMMUTABLE_BINDING=PASS" in workflow
    # The proof reference is metadata only; no value may appear in the gate.
    assert "PADIEM_B14_SERVICE_PROOF_SECRET" in workflow
    assert "SECRET_VALUES_READ=0" in workflow
