"""#4194 Engine bind-only commissioning: strict 18->20 authority gate."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "b62_4194_guard", ROOT / "scripts" / "b62_binding_state_guard.py"
)
assert SPEC and SPEC.loader
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)

ADDITIONS = [
    {"type": "d1", "name": "WEB_XLSX_PRIVATE_B62_D1",
     "database_id": "702bb62b-36f5-41a0-973f-c4f663ee01e6"},
    {"type": "plain_text", "name": "PADIEM_ENGINE_AGENT_DURABLE_ENABLED",
     "text": "true"},
]


def version(*bindings, id="pre"):
    return {"success": True, "result": {"id": id, "resources": {"bindings": list(bindings)}}}


def original():
    return [
        {"type": "d1", "name": "ENGINE_CONTINUATION",
         "database_id": "6b77ad02-bc27-488f-bb97-6325f6750cba"},
        {"type": "service", "name": "CONTROL_PLANE_IDENTITY",
         "service": "padiem-control-plane-identity"},
        {"type": "secret_text", "name": "LEGACY_ENGINE_CREDENTIAL"},
    ]


def test_rollout_requires_both_exact_bindings_and_preserves_every_old_authority():
    old = version(*original())
    new = version(*original(), *ADDITIONS, id="post")
    guard.assert_engine_4194_exact_rollout(old, new)
    with pytest.raises(guard.BindingStateError):
        guard.assert_preserved(old, new)


def test_fully_deployed_and_partially_commissioned_no_drift_are_accepted():
    complete = version(*original(), *ADDITIONS)
    guard.assert_engine_4194_exact_rollout(complete, complete)
    guard.assert_engine_4194_exact_rollout(
        version(*original(), ADDITIONS[0]),
        complete,
    )
    guard.assert_engine_4194_exact_rollout(
        version(*original(), ADDITIONS[1]),
        complete,
    )


@pytest.mark.parametrize("change", [
    "missing_d1", "missing_var", "wrong_db", "wrong_var",
    "remove_secret", "modify_service", "unapproved_d1", "add_secret",
    "alias_collision", "duplicate_name",
])
def test_rollout_denies_missing_or_unapproved_binding_mutations(change):
    old = version(*original())
    bindings = [dict(x) for x in original() + ADDITIONS]
    if change == "missing_d1":
        bindings = [x for x in bindings if x["name"] != "WEB_XLSX_PRIVATE_B62_D1"]
    elif change == "missing_var":
        bindings = [x for x in bindings if x["name"] != "PADIEM_ENGINE_AGENT_DURABLE_ENABLED"]
    elif change == "wrong_db":
        bindings[-2]["database_id"] = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    elif change == "wrong_var":
        bindings[-1]["text"] = "false"
    elif change == "remove_secret":
        bindings = [x for x in bindings if x["type"] != "secret_text"]
    elif change == "modify_service":
        bindings[1]["service"] = "malicious-service"
    elif change == "unapproved_d1":
        bindings.append({"type": "d1", "name": "OTHER_DB", "database_id": "another"})
    elif change == "add_secret":
        bindings.append({"type": "secret_text", "name": "ADDED_SECRET"})
    elif change == "alias_collision":
        bindings[0]["database_id"] = ADDITIONS[0]["database_id"]
    elif change == "duplicate_name":
        bindings.append(dict(bindings[-1]))
    with pytest.raises(guard.BindingStateError):
        guard.assert_engine_4194_exact_rollout(old, version(*bindings, id="post"))


def test_explicit_cli_mode_and_standard_mode_stays_strict(tmp_path, capsys):
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text(json.dumps(version(*original())), encoding="utf-8")
    new.write_text(json.dumps(version(*original(), *ADDITIONS, id="post")), encoding="utf-8")
    args = ["--before", str(old), "--after", str(new)]
    assert guard.main(args) == 1
    capsys.readouterr()
    assert guard.main(args + ["--expected-engine-4194-rollout"]) == 0
    output = capsys.readouterr().out
    assert "ENGINE_4194_EXACT_ADDITIONS_AND_PREEXISTING_BINDINGS_PRESERVED=PASS" in output
    assert "SECRET_VALUES_READ=0" in output
    assert ADDITIONS[0]["database_id"] not in output
    assert guard.main(args + [
        "--expected-engine-4194-rollout", "--expected-add-owner-d1"
    ]) == 1


def test_deploy_workflow_wires_explicit_exact_rollout_without_disabling_smoke():
    text = (ROOT / "workflows" / "b54-engine-production-deploy-gate.yml").read_text(
        encoding="utf-8"
    )
    assert "--expected-engine-4139-desktop-rollout" in text
    assert "b62_binding_state_guard.py" in text
    assert "B54_ENGINE_FULL_BINDING_SET_PRESERVED=PASS" in text
    assert "Post-deploy smoke" in text
    assert "ROLLBACK_B54_ENGINE_TO_PREVIOUS_VERSION" in text


DESKTOP_ADDITIONS = [
    {"type": "service", "name": "PADIEM_CHAT_SERVICE",
     "service": "padiem-chat", "environment": "production"},
    {"type": "secrets_store_secret", "name": "CLAW_ENGINE_DESKTOP_SECRET",
     "store_id": "f0b09ca04a7b43248154c773704a5616",
     "secret_name": "CLAW_ENGINE_DESKTOP_SECRET"},
]


def test_4139_desktop_rollout_accepts_exact_additions_and_is_idempotent():
    old = version(*original(), *ADDITIONS)
    new = version(*original(), *ADDITIONS, *DESKTOP_ADDITIONS, id="post")
    guard.assert_engine_4194_exact_rollout(
        old, new, allow_4139_desktop_bindings=True
    )
    guard.assert_engine_4194_exact_rollout(
        new, new, allow_4139_desktop_bindings=True
    )
    with pytest.raises(guard.BindingStateError):
        guard.assert_engine_4194_exact_rollout(old, new)


@pytest.mark.parametrize("change", [
    "missing_service", "wrong_service", "wrong_store", "wrong_secret_name",
    "unrelated_add", "removed_binding",
])
def test_4139_desktop_rollout_rejects_unreviewed_mutations(change):
    old = version(*original(), *ADDITIONS)
    bindings = [dict(x) for x in original() + ADDITIONS + DESKTOP_ADDITIONS]
    if change == "missing_service":
        bindings = [x for x in bindings if x["name"] != "PADIEM_CHAT_SERVICE"]
    elif change == "wrong_service":
        bindings[-2]["service"] = "malicious-service"
    elif change == "wrong_store":
        bindings[-1]["store_id"] = "00000000000000000000000000000000"
    elif change == "wrong_secret_name":
        bindings[-1]["secret_name"] = "OTHER"
    elif change == "unrelated_add":
        bindings.append({"type": "secret_text", "name": "ADDED_SECRET"})
    elif change == "removed_binding":
        bindings = [x for x in bindings if x["name"] != "LEGACY_ENGINE_CREDENTIAL"]
    with pytest.raises(guard.BindingStateError):
        guard.assert_engine_4194_exact_rollout(
            old, version(*bindings, id="post"), allow_4139_desktop_bindings=True
        )


def test_4139_desktop_cli_mode_and_exclusivity(tmp_path, capsys):
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text(
        json.dumps(version(*original(), *ADDITIONS)), encoding="utf-8"
    )
    new.write_text(
        json.dumps(version(*original(), *ADDITIONS, *DESKTOP_ADDITIONS, id="post")),
        encoding="utf-8",
    )
    args = ["--before", str(old), "--after", str(new),
            "--expected-engine-4139-desktop-rollout"]
    assert guard.main(args) == 0
    output = capsys.readouterr().out
    assert "ENGINE_4139_DESKTOP_EXACT_ADDITIONS_AND_PREEXISTING_BINDINGS_PRESERVED=PASS" in output
    assert guard.main(args + ["--expected-add-oracle-mesh"]) == 1
