"""The B62 gate must be able to undo a refused production deploy.

A deploy that uploads a version, serves it and is then refused by its own
post-deploy audit leaves the account with traffic restored to the recorded version
while the refused upload stays the newest one. Two merged guards turned that scar
into a lock: the rollback mode demanded ``latest == active``, and both the reviewed
binding baseline and the generated production config read bindings from
``GET /settings``, which follows that newest upload. The result was a refused
deploy that could never be confirmed, and a residue binding that the next release
would have inherited as live state.

These are the two contracts that keep it that way. Nothing here calls Cloudflare.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts" / "b62_rollback_recorded_version_guard.py"
CONFIG = ROOT / "scripts" / "b62_cloudflare_production_deploy_config.py"
WORKFLOW = ROOT / "workflows" / "b62-production-code-deploy-gate.yml"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load("b62_rollback_recorded_version_guard", GUARD)
config = _load("b62_cloudflare_production_deploy_config", CONFIG)

SERVED = "ce2490f9-4591-49d6-af04-30791ca75834"
REFUSED_UPLOAD = "facde481-4bcd-446c-adaf-48021fddd365"
OLDER_RECORDED = "11111111-2222-3333-4444-555555555555"


def deployments(*version_ids: str):
    """The canonical /deployments envelope: newest deployment first, 100% traffic."""

    return {
        "success": True,
        "result": {
            "deployments": [
                {
                    "id": f"deployment-{index}",
                    "versions": [{"version_id": vid, "percentage": 100}],
                }
                for index, vid in enumerate(version_ids)
            ]
        },
    }


def served_version(*bindings):
    """GET /versions/{id}: keyed resources plus the version identity."""

    return {
        "success": True,
        "result": {
            "id": SERVED,
            "resources": {
                "bindings": {
                    entry["name"]: {k: v for k, v in entry.items() if k != "name"}
                    for entry in bindings
                }
            },
        },
    }


def settings_plane(*bindings):
    return {"success": True, "result": {"bindings": list(bindings)}}


BASE = [
    {"type": "assets", "name": "ASSETS"},
    {"type": "service", "name": "B14_SERVICE", "service": "ai-revenue-korean-ai-platform"},
    {"type": "d1", "name": "PADIEM_CHAT_DB", "database_id": "db-id"},
    {"type": "plain_text", "name": "PADIEM_CHAT_PUBLIC_BASE_URL", "text": "https://chat.padiem.net"},
]
RESIDUE = {"type": "service", "name": "DOCUMENT_PARSER_SERVICE", "service": "padiem-document-parser"}


def write(tmp_path: Path, payload: object, name: str) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_rollback_can_recover_when_the_newest_upload_never_served(tmp_path, capsys):
    """latest != active is a warning; the record itself is what a rollback must match."""

    doc = write(tmp_path, deployments(SERVED, OLDER_RECORDED), "deployments.json")

    refused = guard.main([
        "--deployments", doc,
        "--newest-upload-version", REFUSED_UPLOAD,
        "--previous-version-id", SERVED,
    ])
    out = capsys.readouterr().out
    assert refused == 0, "the recorded version serving traffic is roll-backable"
    assert f"ACTIVE_VERSION={SERVED}" in out
    assert "LATEST_VERSION_EQUALS_ACTIVE_VERSION=WARN:unactivated_latest_upload" in out
    assert f"LATEST_UNSERVED_VERSION={REFUSED_UPLOAD}" in out
    assert "B62_ROLLBACK_RECORDED_VERSION=ACTIVE" in out
    assert "PRODUCTION_MUTATION=0" in out

    predecessor = guard.main([
        "--deployments", doc,
        "--newest-upload-version", REFUSED_UPLOAD,
        "--previous-version-id", OLDER_RECORDED,
    ])
    assert predecessor == 0
    assert "B62_ROLLBACK_RECORDED_VERSION=PREDECESSOR" in capsys.readouterr().out

    clean = guard.main([
        "--deployments", write(tmp_path, deployments(SERVED), "clean.json"),
        "--newest-upload-version", SERVED,
        "--previous-version-id", SERVED,
    ])
    assert clean == 0
    assert "LATEST_VERSION_EQUALS_ACTIVE_VERSION=PASS" in capsys.readouterr().out


def test_a_rollback_still_refuses_anything_the_history_never_served(tmp_path, capsys):
    """The warning is not an open door: only a recorded served version is accepted."""

    doc = write(tmp_path, deployments(SERVED, OLDER_RECORDED), "deployments.json")

    never_served = guard.main([
        "--deployments", doc,
        "--newest-upload-version", REFUSED_UPLOAD,
        "--previous-version-id", REFUSED_UPLOAD,
    ])
    assert never_served == 1
    assert "BLOCKED:recorded-id-not-served-history" in capsys.readouterr().err

    for bad in ("ce2490f9", SERVED.upper(), "not-a-uuid", ""):
        assert guard.main([
            "--deployments", doc,
            "--newest-upload-version", REFUSED_UPLOAD,
            "--previous-version-id", bad,
        ]) == 1
        assert "BLOCKED:recorded-id-shape" in capsys.readouterr().err

    single = write(tmp_path, deployments(SERVED), "single.json")
    assert guard.main([
        "--deployments", single,
        "--newest-upload-version", REFUSED_UPLOAD,
        "--previous-version-id", OLDER_RECORDED,
    ]) == 1
    assert "BLOCKED:no-predecessor-record" in capsys.readouterr().err


def test_preserved_bindings_are_taken_from_the_served_version(tmp_path):
    """The refused upload's plane is not allowed to become the next deploy's live state."""

    served = served_version(*BASE)
    residue = settings_plane(*[*BASE, RESIDUE])

    served_entries = config.live_binding_entries(served)
    assert [entry["name"] for entry in served_entries] == [b["name"] for b in BASE]
    assert all(entry.get("name") for entry in served_entries), "keyed form is normalized"
    assert [entry["name"] for entry in config.live_binding_entries(residue)] == [
        b["name"] for b in [*BASE, RESIDUE]
    ]
    assert "DOCUMENT_PARSER_SERVICE" not in {entry["name"] for entry in served_entries}

    live = config.parse_live_bindings(served)
    assert [service["name"] for service in live["services"]] == ["B14_SERVICE"]
    assert live["d1"][0]["database_id"] == "db-id"

    with pytest.raises(config.ProductionConfigError, match="identity or resources missing"):
        config.live_binding_entries({"success": True, "result": {"resources": {}}})
    with pytest.raises(config.ProductionConfigError, match="key/name disagreement"):
        broken = served_version(*BASE)
        broken["result"]["resources"]["bindings"]["ASSETS"]["name"] = "SOMETHING_ELSE"
        config.live_binding_entries(broken)


def test_the_merged_gate_wires_both_sources_to_the_served_version():
    """Pin the release path itself, not only the helper it now calls."""

    workflow = WORKFLOW.read_text(encoding="utf-8")

    rollback_branch = workflow.split('"rollback_production_code" ]; then', 1)[1].split(
        "\n          else\n", 1
    )[0]
    assert "b62_rollback_recorded_version_guard.py" in rollback_branch
    assert "cloudflare_served_version_lineage.py" not in rollback_branch, (
        "a refused deploy left latest != active; the rollback mode may not demand it"
    )
    strict_marker = "Preserve canonical strict lineage for all normal read-only modes."
    assert strict_marker in workflow
    assert "cloudflare_served_version_lineage.py" in workflow.split(strict_marker, 1)[1][:240], (
        "the read-only audit keeps the strict lineage guard"
    )

    assert 'config_settings="${RUNNER_TEMP}/b62-version-before.json"' in workflow
    assert 'before_comparison="${RUNNER_TEMP}/b62-version-before.json"' in workflow
    assert 'from b62_cloudflare_production_deploy_config import live_binding_entries' in workflow
    assert "b62_rollback_recorded_version_guard.py" in workflow
    assert "B62_ROLLBACK_ACTIVE_BINDING_PRESERVED=PASS" in workflow
    assert "B62_ROLLBACK_SERVED_BINDING_BASELINE=PASS" in workflow

    rollback_readback = workflow.split("Read back rollback exactness and health", 1)[1]
    guard_call = rollback_readback.split("B62_ROLLBACK_ACTIVE_BINDING_PRESERVED=PASS", 1)[0]
    assert '--before "${RUNNER_TEMP}/b62-rollback-target.json"' in guard_call
    assert '--after "${detail}"' in guard_call
    assert '"/settings"' not in guard_call, (
        "the settings plane must not decide what a rollback preserved"
    )
    assert "B62_SETTINGS_PLANE_BINDING_RESIDUE=PRESENT" in workflow
    assert "B62_BINDING_BASELINE_VALUES_EMITTED=0" in workflow
