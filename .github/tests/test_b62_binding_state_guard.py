from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "b62_binding_state_guard.py"
spec = importlib.util.spec_from_file_location("b62_binding_state_guard", SCRIPT)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def settings(*bindings):
    return {"success": True, "result": {"bindings": list(bindings)}}


def base_bindings():
    return [
        {"type": "assets", "name": "ASSETS"},
        {"type": "service", "name": "IDENTITY_AUTHORITY_SERVICE", "service": "padiem-control-plane-identity"},
        {"type": "service", "name": "B14_SERVICE", "service": "ai-revenue-korean-ai-platform", "environment": "production"},
        {"type": "d1", "name": "PADIEM_CHAT_DB", "id": "db-id"},
        {"type": "r2_bucket", "name": "PADIEM_WORKSPACE_FILES", "bucket_name": "private-claw", "jurisdiction": "us"},
        {"type": "plain_text", "name": "PADIEM_CHAT_RUNTIME_MODE", "text": "b14"},
        {"type": "secret_text", "name": "PADIEM_CHAT_QUOTA_SALT"},
    ]


def test_exact_binding_authority_preservation_passes():
    before = settings(*base_bindings())
    after = settings(*reversed(base_bindings()))
    mod.assert_preserved(before, after)


def test_r2_bucket_name_drift_is_rejected():
    before = settings(*base_bindings())
    changed = base_bindings()
    changed[4] = {**changed[4], "bucket_name": "wrong-bucket"}
    with pytest.raises(mod.BindingStateError):
        mod.assert_preserved(before, settings(*changed))


def test_r2_jurisdiction_drift_is_rejected():
    before = settings(*base_bindings())
    changed = base_bindings()
    changed[4] = {**changed[4], "jurisdiction": "eu"}
    with pytest.raises(mod.BindingStateError):
        mod.assert_preserved(before, settings(*changed))


def test_service_environment_drift_is_rejected():
    before = settings(*base_bindings())
    changed = base_bindings()
    changed[2] = {**changed[2], "environment": "staging"}
    with pytest.raises(mod.BindingStateError):
        mod.assert_preserved(before, settings(*changed))


def test_service_entrypoint_drift_is_rejected():
    before = settings({"type": "service", "name": "ENGINE_SERVICE",
                       "service": "padiem-ai-engine", "entrypoint": "First"})
    after = settings({"type": "service", "name": "ENGINE_SERVICE",
                      "service": "padiem-ai-engine", "entrypoint": "Second"})
    with pytest.raises(mod.BindingStateError, match="binding authority drift"):
        mod.assert_preserved(before, after)


def test_d1_id_drift_is_rejected():
    before = settings(*base_bindings())
    changed = base_bindings()
    changed[3] = {**changed[3], "id": "other-db"}
    with pytest.raises(mod.BindingStateError):
        mod.assert_preserved(before, settings(*changed))


def test_plain_text_drift_is_rejected():
    before = settings(*base_bindings())
    changed = base_bindings()
    changed[5] = {**changed[5], "text": "mock"}
    with pytest.raises(mod.BindingStateError):
        mod.assert_preserved(before, settings(*changed))


def test_secret_name_presence_only_is_compared():
    before = settings(*base_bindings())
    changed = base_bindings()
    changed[6] = {"type": "secret_text", "name": "OTHER_SECRET"}
    with pytest.raises(mod.BindingStateError):
        mod.assert_preserved(before, settings(*changed))


def test_unknown_type_and_duplicate_names_fail_closed():
    with pytest.raises(mod.BindingStateError):
        mod.canonical_state(settings({"type": "kv_namespace", "name": "X"}))
    with pytest.raises(mod.BindingStateError):
        mod.canonical_state(settings(
            {"type": "secret_text", "name": "X"},
            {"type": "plain_text", "name": "X", "text": "x"},
        ))


def _version(*bindings, version_id="v123"):
    return {"success": True, "result": {
        "id": version_id, "resources": {"bindings": list(bindings)},
    }}


def _engine_bindings(database_id="engine-db", service="padiem-control-plane-identity"):
    return [
        {"type": "d1", "name": "ENGINE_CONTINUATION", "database_id": database_id},
        {"type": "service", "name": "CONTROL_PLANE_IDENTITY", "service": service},
        {"type": "secret_text", "name": "PADIEM_ENGINE_CALLER_SECRET"},
    ]


def test_immutable_version_binding_comparison_preserves_all_old_engine_bindings():
    before = _version(*_engine_bindings(), version_id="before")
    after = _version(*reversed(_engine_bindings()), version_id="after")
    mod.assert_preserved(before, after)


@pytest.mark.parametrize("change", ["database", "service", "secret", "new_d1", "missing_d1"])
def test_immutable_version_comparison_refuses_any_unexpected_binding_change(change):
    before = _version(*_engine_bindings(), version_id="before")
    bindings = _engine_bindings()
    if change == "database":
        bindings[0]["database_id"] = "wrong-db"
    elif change == "service":
        bindings[1]["service"] = "wrong-service"
    elif change == "secret":
        bindings[2]["name"] = "OTHER_SECRET"
    elif change == "new_d1":
        bindings.append({"type": "d1", "name": "UNAPPROVED_D1", "database_id": "other"})
    elif change == "missing_d1":
        bindings.pop(0)
    with pytest.raises(mod.BindingStateError, match="binding authority drift"):
        mod.assert_preserved(before, _version(*bindings, version_id="after"))


def test_version_and_settings_d1_identity_fields_normalize_to_same_value():
    settings_payload = settings({"type": "d1", "name": "ENGINE_CONTINUATION", "id": "same-db"})
    version_payload = _version({
        "type": "d1", "name": "ENGINE_CONTINUATION", "database_id": "same-db",
    })
    mod.assert_preserved(settings_payload, version_payload)


def test_version_with_inconsistent_d1_aliases_fails_closed():
    with pytest.raises(mod.BindingStateError, match="conflicting D1"):
        mod.canonical_state(_version({
            "type": "d1", "name": "ENGINE_CONTINUATION",
            "id": "one-db", "database_id": "other-db",
        }))


def test_name_keyed_immutable_version_matches_array_form():
    canonical = _engine_bindings()
    keyed = {entry["name"]: {k: v for k, v in entry.items() if k != "name"}
             for entry in canonical}
    mod.assert_preserved(
        _version(*canonical, version_id="before"),
        {"success": True, "result": {
            "id": "after", "resources": {"bindings": keyed},
        }},
    )


def test_name_keyed_immutable_version_rejects_key_identity_mismatch():
    with pytest.raises(mod.BindingStateError, match="key/name disagreement"):
        mod.canonical_state({"success": True, "result": {
            "id": "version", "resources": {"bindings": {
                "EXPECTED": {"name": "MISMATCH", "type": "secret_text"},
            }},
        }})


def test_name_keyed_immutable_version_rejects_non_object_entry():
    with pytest.raises(mod.BindingStateError, match="malformed keyed"):
        mod.canonical_state({"success": True, "result": {
            "id": "version", "resources": {"bindings": {"BROKEN": None}},
        }})


def test_version_without_identity_or_bindings_fails_closed():
    with pytest.raises(mod.BindingStateError):
        mod.canonical_state({"success": True, "result": {"resources": {"bindings": []}}})
    with pytest.raises(mod.BindingStateError):
        mod.canonical_state({"success": True, "result": {"id": "v1", "resources": {}}})


# #3782: single approved D1 additive commissioning mode, never standard redeploy.
_OWNER_ID = "01d0560b-58f4-4052-991d-dc935f5ecca0"
_OTHER_ID = "6b77ad02-bc27-488f-bb97-6325f6750cba"


def _commission_before():
    return settings(
        {"type": "d1", "name": "ENGINE_CONTINUATION", "id": _OTHER_ID},
        {"type": "service", "name": "CONTROL_PLANE_IDENTITY",
         "service": "padiem-control-plane-identity"},
        {"type": "secret_text", "name": "P01_ENGINE_CREDENTIAL"},
    )


def _commission_added():
    return settings(
        *_commission_before()["result"]["bindings"],
        {"type": "d1", "name": "BROWSER_CONTROL_OWNER_P01_D1", "id": _OWNER_ID},
    )


def test_owner_addition_exactly_one_and_default_equality_unmodified():
    before, after = _commission_before(), _commission_added()
    mod.assert_one_owner_d1_added(before, after, _OWNER_ID)
    with pytest.raises(mod.BindingStateError, match="binding authority drift"):
        mod.assert_preserved(before, after)


@pytest.mark.parametrize("mutation", ["drop_secret", "rename_service", "extra_d1", "wrong_db",
                                       "wrong_type", "no_addition", "duplicate_owner"])
def test_owner_addition_rejects_any_other_binding_change(mutation):
    after = _commission_added()["result"]["bindings"]
    if mutation == "drop_secret":
        after = [b for b in after if b["type"] != "secret_text"]
    elif mutation == "rename_service":
        after[1]["service"] = "another-worker"
    elif mutation == "extra_d1":
        after.append({"type": "d1", "name": "UNAPPROVED", "id": "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"})
    elif mutation == "wrong_db":
        after[-1]["id"] = "aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa"
    elif mutation == "wrong_type":
        after[-1]["type"] = "secret_text"
    elif mutation == "no_addition":
        after.pop()
    elif mutation == "duplicate_owner":
        after.append(dict(after[-1]))
    with pytest.raises(mod.BindingStateError):
        mod.assert_one_owner_d1_added(_commission_before(), settings(*after), _OWNER_ID)


def test_owner_addition_refuses_alias_preexisting_and_invalid_identity():
    alias_before = settings({"type": "d1", "name": "ENGINE_CONTINUATION", "id": _OWNER_ID})
    with pytest.raises(mod.BindingStateError, match="aliases"):
        mod.assert_one_owner_d1_added(alias_before, _commission_added(), _OWNER_ID)
    with pytest.raises(mod.BindingStateError, match="already exists"):
        mod.assert_one_owner_d1_added(_commission_added(), _commission_added(), _OWNER_ID)
    for bad in ("", "not-a-uuid", "00000000-0000-0000-0000-000000000000",
                _OWNER_ID.upper(), _OTHER_ID + "x"):
        with pytest.raises(mod.BindingStateError):
            mod.assert_one_owner_d1_added(_commission_before(), _commission_added(), bad)


def test_owner_addition_cli_is_explicit_and_prints_no_identifiers(tmp_path, capsys):
    before, after = tmp_path / "before.json", tmp_path / "after.json"
    before.write_text(json.dumps(_commission_before()), encoding="utf-8")
    after.write_text(json.dumps(_commission_added()), encoding="utf-8")
    base = ["--before", str(before), "--after", str(after)]
    assert mod.main(base) == 1  # Standard code deploy still forbids additions.
    capsys.readouterr()
    assert mod.main(base + ["--owner-d1-database-id", _OWNER_ID]) == 1
    capsys.readouterr()
    assert mod.main(base + ["--expected-add-owner-d1"]) == 1
    capsys.readouterr()
    assert mod.main(base + ["--expected-add-owner-d1", "--owner-d1-database-id", _OWNER_ID]) == 0
    out = capsys.readouterr().out
    assert "OWNER_P01_D1_EXACTLY_ONE_ADDITION=PASS" in out
    assert "EXISTING_WORKER_BINDINGS_PRESERVED=PASS" in out
    assert _OWNER_ID not in out and _OTHER_ID not in out


@pytest.mark.parametrize("worker,types", [
    ("B54", {"assets": 1, "service": 5, "d1": 1, "r2_bucket": 1,
             "plain_text": 15, "secret_text": 4}),
    ("Engine", {"service": 4, "d1": 6, "secret_text": 8}),
])
def test_owner_addition_preserves_full_live_size_binding_matrix(worker, types):
    """Exercise actual observed 27->28 / 18->19 shape without remote secrets."""
    identifiers = {
        "assets": lambda n: {"type": "assets", "name": f"ASSETS_{n}"},
        "service": lambda n: {
            "type": "service", "name": f"SERVICE_{n}", "service": f"worker-{n}",
        },
        "d1": lambda n: {
            "type": "d1", "name": f"EXISTING_D1_{n}",
            "id": "6b77ad02-bc27-488f-bb97-6325f6750cba",
        },
        "r2_bucket": lambda n: {
            "type": "r2_bucket", "name": f"R2_{n}", "bucket_name": f"bucket-{n}",
        },
        "plain_text": lambda n: {
            "type": "plain_text", "name": f"VAR_{n}", "text": f"unchanged-{n}",
        },
        "secret_text": lambda n: {"type": "secret_text", "name": f"SECRET_{n}"},
    }
    before_bindings = [identifiers[t](i) for t, count in types.items() for i in range(count)]
    before = settings(*before_bindings)
    after = settings(
        *before_bindings,
        {"type": "d1", "name": "BROWSER_CONTROL_OWNER_P01_D1", "id": _OWNER_ID},
    )
    expected_before = 27 if worker == "B54" else 18
    assert len(mod.canonical_state(before)) == expected_before
    assert len(mod.canonical_state(after)) == expected_before + 1
    mod.assert_one_owner_d1_added(before, after, _OWNER_ID)
    corrupted = settings(*[b for b in after["result"]["bindings"] if b["name"] != "SECRET_0"])
    with pytest.raises(mod.BindingStateError):
        mod.assert_one_owner_d1_added(before, corrupted, _OWNER_ID)



# #3782 live commissioning: immutable version resources protect code and assets.
def _owner_served_version(version_id="pre", *, with_owner=False):
    bindings = [
        {"type": "service", "name": "IDENTITY_AUTHORITY_SERVICE",
         "service": "padiem-control-plane-identity"},
        {"type": "secret_text", "name": "P01_ENGINE_CREDENTIAL"},
        {"type": "d1", "name": "PADIEM_CHAT_DB", "database_id": _OTHER_ID},
    ]
    if with_owner:
        bindings.append({"type": "d1", "name": "BROWSER_CONTROL_OWNER_P01_D1",
                         "database_id": _OWNER_ID})
    return {"success": True, "result": {"id": version_id, "resources": {
        "bindings": bindings,
        "script": {
            "etag": "unchanged-code-etag",
            "handlers": ["fetch"],
            "last_deployed_from": "wrangler",
        },
        "script_runtime": {
            "assets": {"jwt": "unchanged-assets-authority"},
            "compatibility_date": "2026-08-25",
            "compatibility_flags": ["python_workers"],
            "usage_model": "standard",
        },
    }}}


def test_owner_immutable_version_integrity_accepts_exact_one_d1_and_unchanged_worker():
    before = _owner_served_version()
    after = _owner_served_version("post", with_owner=True)
    mod.assert_owner_version_integrity(before, after, _OWNER_ID)


@pytest.mark.parametrize("change", [
    "script_etag", "script_handler", "assets", "compatibility_date",
    "compatibility_flags", "usage_model", "missing_script", "missing_runtime",
    "missing_etag", "missing_compatibility", "new_resource",
    "remove_resource", "same_version_id", "wrong_secret",
    "settings_instead_of_version",
])
def test_owner_immutable_version_integrity_rejects_unrelated_changes(change):
    before = _owner_served_version()
    after = _owner_served_version("post", with_owner=True)
    resources = after["result"]["resources"]
    if change == "script_etag":
        resources["script"]["etag"] = "DIFFERENT"
    elif change == "script_handler":
        resources["script"]["handlers"] = ["scheduled"]
    elif change == "assets":
        resources["script_runtime"]["assets"]["jwt"] = "DIFFERENT"
    elif change == "compatibility_date":
        resources["script_runtime"]["compatibility_date"] = "2026-08-26"
    elif change == "compatibility_flags":
        resources["script_runtime"]["compatibility_flags"] = []
    elif change == "usage_model":
        resources["script_runtime"]["usage_model"] = "bundled"
    elif change == "missing_script":
        del resources["script"]
    elif change == "missing_runtime":
        del resources["script_runtime"]
    elif change == "missing_etag":
        del resources["script"]["etag"]
    elif change == "missing_compatibility":
        del resources["script_runtime"]["compatibility_date"]
    elif change == "new_resource":
        resources["some_new_resource"] = "unexpected"
    elif change == "remove_resource":
        del resources["script_runtime"]["assets"]
    elif change == "same_version_id":
        after["result"]["id"] = before["result"]["id"]
    elif change == "wrong_secret":
        resources["bindings"][1]["name"] = "OTHER_SECRET"
    elif change == "settings_instead_of_version":
        after = settings(*resources["bindings"])
    with pytest.raises(mod.BindingStateError):
        mod.assert_owner_version_integrity(before, after, _OWNER_ID)


def test_owner_immutable_version_integrity_cli_requires_opt_in(tmp_path, capsys):
    before = tmp_path / "pre.json"
    after = tmp_path / "post.json"
    before.write_text(json.dumps(_owner_served_version()), encoding="utf-8")
    after.write_text(json.dumps(_owner_served_version("post", with_owner=True)), encoding="utf-8")
    base = ["--before", str(before), "--after", str(after)]
    args = base + ["--expected-add-owner-d1", "--owner-d1-database-id", _OWNER_ID]
    assert mod.main(args + ["--require-served-resource-integrity"]) == 0
    output = capsys.readouterr().out
    assert "OWNER_P01_D1_SERVED_RESOURCE_INTEGRITY=PASS" in output
    assert _OWNER_ID not in output
    assert mod.main(base + ["--require-served-resource-integrity"]) == 1
    assert "requires additive mode" in capsys.readouterr().err
