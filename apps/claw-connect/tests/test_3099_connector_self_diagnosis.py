"""#3099 Connector self-diagnosis and the secret-free support bundle.

The diagnosis is a pure function of observed local facts, so every branch is
verified offline without a tray, Broker, Agent, registry or Windows session.

What these tests prove that nothing else does:

* a first-run PC reports exactly one blocking reason and one next action, and
  the earliest broken link in the chain always wins;
* the reason and action vocabulary is closed, so an unexpected observation can
  never leak an arbitrary string into user-facing or support-facing output;
* the support bundle carries no secret, no identifier and no raw task
  payload, so a user can hand it to support unchanged.
"""
from __future__ import annotations

import json

import pytest

from claw_connect.self_diagnosis import (
    ACTIONS,
    ADVISORIES,
    REASONS,
    SUPPORT_BUNDLE_VERSION,
    device_fingerprint,
    diagnose,
    support_bundle,
)

AGENT_OK = {"agent_ready": True, "agent_status": "ok", "source_kind": "configured"}
AGENT_MISSING = {
    "agent_ready": False,
    "agent_status": "agent_source_not_configured",
    "source_kind": "unconfigured",
}
ENROLLED = {"enrolled": True, "device_lifecycle": "paired", "blocked": False}
NOT_ENROLLED = {"enrolled": False, "device_lifecycle": None, "blocked": False}
BLOCKED = {"enrolled": True, "device_lifecycle": "paired", "blocked": True}
REVOKED = {"enrolled": True, "device_lifecycle": "revoked", "blocked": True}


def test_a_ready_pc_reports_no_blocking_reason():
    result = diagnose(
        agent=AGENT_OK, enrollment=ENROLLED, connection_state="connected",
        resident_running=True, autostart_enabled=True, single_instance=True,
    )
    assert result["ready"] is True
    assert result["reason"] == "ok"
    assert result["action"] == "none"
    assert result["advisories"] == []


def test_the_earliest_broken_link_wins():
    """A missing Agent source masks the later, less fundamental facts."""
    result = diagnose(
        agent=AGENT_MISSING, enrollment=NOT_ENROLLED, connection_state="disconnected",
    )
    assert result["reason"] == "agent_source_not_configured"
    assert result["action"] == "install_agent"


@pytest.mark.parametrize(
    "agent,reason,action",
    [
        (AGENT_MISSING, "agent_source_not_configured", "install_agent"),
        (
            {"agent_ready": False, "agent_status": "agent_source_invalid",
             "source_kind": "configured"},
            "agent_source_invalid",
            "review_agent_source",
        ),
        (
            {"agent_ready": False, "agent_status": "agent_source_conflict",
             "source_kind": "conflicting_environment"},
            "agent_source_conflict",
            "review_agent_source",
        ),
    ],
)
def test_agent_source_failures_have_their_own_reason(agent, reason, action):
    result = diagnose(agent=agent, enrollment=ENROLLED, connection_state="connected")
    assert result["reason"] == reason
    assert result["action"] == action


@pytest.mark.parametrize(
    "enrollment,reason,action",
    [
        (NOT_ENROLLED, "not_enrolled", "login_and_pair"),
        (BLOCKED, "enrollment_blocked", "review_enrollment"),
        (REVOKED, "enrollment_revoked", "review_enrollment"),
    ],
)
def test_enrollment_failures_have_their_own_reason(enrollment, reason, action):
    result = diagnose(
        agent=AGENT_OK, enrollment=enrollment, connection_state="connected",
    )
    assert result["reason"] == reason
    assert result["action"] == action


def test_a_paused_pc_is_reported_as_paused_not_as_offline():
    result = diagnose(
        agent=AGENT_OK, enrollment=ENROLLED, connection_state="paused",
        resident_running=True,
    )
    assert result["reason"] == "paused"
    assert result["action"] == "resume_connector"


def test_a_pc_that_never_connected_reports_start_connector():
    result = diagnose(
        agent=AGENT_OK, enrollment=ENROLLED, connection_state="offline",
    )
    assert result["reason"] == "not_connected"
    assert result["action"] == "start_connector"


def test_a_connected_pc_without_a_resident_reports_the_resident():
    result = diagnose(
        agent=AGENT_OK, enrollment=ENROLLED, connection_state="connected",
        resident_running=False,
    )
    assert result["reason"] == "resident_not_running"
    assert result["action"] == "start_connector"


def test_autostart_off_is_an_advisory_and_never_blocks():
    result = diagnose(
        agent=AGENT_OK, enrollment=ENROLLED, connection_state="connected",
        resident_running=True, autostart_enabled=False, single_instance=True,
    )
    assert result["ready"] is True
    assert result["reason"] == "ok"
    assert result["advisories"] == ["autostart_off"]


def test_every_reported_reason_and_action_is_in_the_closed_vocabulary():
    facts = [
        {"agent": agent, "enrollment": enrollment, "connection_state": state}
        for agent in (AGENT_OK, AGENT_MISSING)
        for enrollment in (ENROLLED, NOT_ENROLLED, BLOCKED, REVOKED)
        for state in ("connected", "connecting", "disconnected", "offline", "paused")
    ]
    for case in facts:
        result = diagnose(**case)
        assert result["reason"] in REASONS
        assert result["action"] in ACTIONS
        for advisory in result["advisories"]:
            assert advisory in ADVISORIES


def test_the_diagnosis_carries_no_identifier_and_no_secret():
    result = diagnose(
        agent=AGENT_OK, enrollment={**ENROLLED, "device_id": "dev-secret-value"},
        connection_state="connected",
    )
    rendered = json.dumps(result, ensure_ascii=False)
    assert "dev-secret-value" not in rendered
    for forbidden in ("device_id", "binding_ref", "account_ref", "workspace_ref",
                      "credential", "pairing_code", "path"):
        assert forbidden not in rendered


def test_the_device_fingerprint_is_not_reversible():
    device_id = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
    fingerprint = device_fingerprint(device_id)
    assert fingerprint is not None
    assert fingerprint.startswith("sha256:")
    assert device_id not in fingerprint
    assert device_fingerprint(device_id) == fingerprint
    assert device_fingerprint("other-device") != fingerprint
    assert device_fingerprint(None) is None
    assert device_fingerprint("") is None


def test_the_support_bundle_is_secret_free_and_identifier_free():
    device_id = "wYx8HR9Ou4C96Ys63dY8lYktUiTPf7PwRM8lclcOvW3V4KTM1Auk@Dd2cdXxSOwp"
    diagnosis = diagnose(
        agent=AGENT_OK, enrollment=ENROLLED, connection_state="connected",
        resident_running=True, autostart_enabled=True, single_instance=True,
    )
    bundle = support_bundle(
        diagnosis, connector_version="1.0.0", device_id=device_id,
    )
    assert bundle["bundle_version"] == SUPPORT_BUNDLE_VERSION
    assert bundle["connector_version"] == "1.0.0"
    assert bundle["device_fingerprint"].startswith("sha256:")
    assert bundle["diagnosis"]["ready"] is True

    rendered = json.dumps(bundle, ensure_ascii=False)
    assert device_id not in rendered
    for forbidden in ("device_id", "binding_ref", "account_ref", "workspace_ref",
                      "credential", "pairing_code", "stdout", "task_payload"):
        assert forbidden not in rendered
    # A path shape is never carried either.
    assert "C:\\" not in rendered and "/home/" not in rendered


def test_a_broken_pc_still_produces_a_bundle():
    """A support bundle is produced even when nothing is configured."""
    diagnosis = diagnose(agent=AGENT_MISSING, enrollment=NOT_ENROLLED)
    bundle = support_bundle(diagnosis, connector_version="1.0.0", device_id=None)
    assert bundle["device_fingerprint"] is None
    assert bundle["diagnosis"]["reason"] == "agent_source_not_configured"
    assert bundle["diagnosis"]["ready"] is False
    json.dumps(bundle)


def test_the_support_bundle_command_mints_no_identity(tmp_path, monkeypatch, capsys):
    """The command is read-only: it never creates Connector state."""
    from claw_connect import __main__ as cli

    state_dir = tmp_path / "state"
    monkeypatch.setenv("CLAW_CONNECT_STATE_DIR", str(state_dir))
    assert cli.main(["support-bundle"]) == 1
    bundle = json.loads(capsys.readouterr().out)
    assert bundle["bundle_version"] == SUPPORT_BUNDLE_VERSION
    assert bundle["diagnosis"]["reason"] in REASONS
    # Nothing was written: a first-run PC still has no committed record, so
    # there is no device id and therefore no fingerprint.
    assert bundle["device_fingerprint"] is None
    assert not state_dir.exists() or not list(state_dir.glob("enrollment.json"))


def test_the_doctor_command_keeps_its_reviewed_contract(tmp_path, monkeypatch, capsys):
    """The Agent preflight command is unchanged; the diagnosis is additive."""
    from claw_connect import __main__ as cli

    monkeypatch.setenv("CLAW_CONNECT_STATE_DIR", str(tmp_path / "state"))
    cli.main(["doctor"])
    snapshot = json.loads(capsys.readouterr().out)
    assert snapshot["product"] == "PADIEM Agent"
    assert set(snapshot) == {
        "product", "agent_ready", "agent_status", "source_kind",
        "production_gateway_enabled", "agent_started",
        "device_enrollment_changed",
    }
