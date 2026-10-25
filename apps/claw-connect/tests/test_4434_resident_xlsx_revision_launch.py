"""#4434 — the Connector can carry a deployment's XLSX revision plan source.

The Resident reads ``PADIEM_AGENT_XLSX_REVISION_PLAN_SOURCE`` itself and starts
the revision lane only when a trusted ``module:attribute`` factory resolves. The
gap this pins is the launch side: a supervised Resident spawned with an inherited
environment either picks up whatever the operator's shell happened to export, or
picks up nothing at all because the plan dropped the key. Both are wrong, so the
plan must forward a configured value, refuse a malformed one, and clear an
ambient one it never authorized.

Nothing here imports the Resident, resolves a factory, touches a file, or mints
an approval: the plan carries a *name*, and only the deployment can make that
name mean something.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from claw_connect.enrollment import (
    LIFECYCLE_PAIRED_OFFLINE,
    EnrollmentRecord,
)
from claw_connect.installed_runtime import installed_resident_environ
from claw_connect.resident_launch import (
    REASON_REQUEST_PORT_UNCONFIGURED,
    REASON_VERIFIED_TEXT_PLAN_SOURCE_INVALID,
    REASON_XLSX_REVISION_PLAN_SOURCE_INVALID,
    RESIDENT_ENV_AUTHORITY_REF,
    RESIDENT_ENV_BROKER_URL,
    RESIDENT_ENV_CREDENTIAL_DIR,
    RESIDENT_ENV_DEVICE_ID,
    RESIDENT_ENV_REQUEST_PORT,
    RESIDENT_ENV_VERIFIED_TEXT_PLAN_SOURCE,
    RESIDENT_ENV_XLSX_REVISION_PLAN_SOURCE,
    ResidentLaunchPlan,
    plan_resident_launch,
)

DEVICE_ID = "device.4434.resident.revision"
AUTHORITY_REF = "control-plane.local-agent-broker.4434.revision.v1"
REQUEST_PORT = "kagent.local_agent_broker_production_entry:make_production_request_port"
BROKER_URL = "https://local-agent.padiem.net"
REVISION_SOURCE = "kagent.reviewed_xlsx_revision_plan_source:make_reviewed_plan_source"

#: Names that can never import. Each one is a broken configuration, not a
#: lane the owner turned off, and must be refused before a child is spawned.
IMPOSSIBLE = [
    "no_colon",
    "a:b:c",
    "kagent.:missing_attribute",
    ":missing_module",
    "kagent..mod:factory",
    "kagent.mod:NotAnIdentifier!",
    r"C:\Users\me\xlsx_plan.py",
    "kagent.mod: make_factory",
]


def _record() -> EnrollmentRecord:
    return EnrollmentRecord(
        device_id=DEVICE_ID,
        binding_ref="binding.4434.1",
        account_ref="account.4434",
        workspace_ref="workspace.4434",
        credential_generation=1,
        credential_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        device_lifecycle=LIFECYCLE_PAIRED_OFFLINE,
        revoked=False,
    )


def _configured(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(RESIDENT_ENV_CREDENTIAL_DIR, str(tmp_path / "canonical-credential-store"))
    monkeypatch.setenv(RESIDENT_ENV_AUTHORITY_REF, AUTHORITY_REF)
    monkeypatch.setenv(RESIDENT_ENV_REQUEST_PORT, REQUEST_PORT)
    monkeypatch.setenv(RESIDENT_ENV_BROKER_URL, BROKER_URL)
    monkeypatch.delenv(RESIDENT_ENV_XLSX_REVISION_PLAN_SOURCE, raising=False)
    monkeypatch.delenv(RESIDENT_ENV_VERIFIED_TEXT_PLAN_SOURCE, raising=False)


# -- the key is the Resident's own contract ----------------------------------


def test_the_revision_key_is_pinned_as_the_text_the_resident_reads():
    """Pinned literally: a rename on either side silently disables the lane.

    ``kagent.local_agent_resident_process`` looks this name up in its own
    environment; the Connector never resolves the factory, so the only contract
    between the two is this string.
    """
    assert RESIDENT_ENV_XLSX_REVISION_PLAN_SOURCE == "PADIEM_AGENT_XLSX_REVISION_PLAN_SOURCE"


def test_the_resident_reads_the_same_key_the_plan_writes():
    """Cross-app check against the Resident's own source.

    The two apps share no import, so the binding is textual: if the Resident
    renames its lookup, this fails instead of the lane quietly never starting.
    """
    resident = (
        Path(__file__).resolve().parents[2]
        / "korean-ai-code-agent" / "src" / "kagent"
        / "local_agent_resident_process.py"
    )
    source = resident.read_text(encoding="utf-8")

    assert (
        'XLSX_REVISION_PLAN_SOURCE_ENV = "PADIEM_AGENT_XLSX_REVISION_PLAN_SOURCE"' in source
    )
    assert "xlsx_revision_plan_source_from_environment()" in source


def test_the_refusal_reason_carries_no_value():
    """Bounded, secret-free reasons an operator can act on."""
    assert REASON_XLSX_REVISION_PLAN_SOURCE_INVALID == "xlsx_revision_plan_source_invalid"


# -- plan behaviour ---------------------------------------------------------


def test_configured_revision_source_is_planned_and_forwarded(monkeypatch, tmp_path):
    _configured(monkeypatch, tmp_path)
    monkeypatch.setenv(RESIDENT_ENV_XLSX_REVISION_PLAN_SOURCE, REVISION_SOURCE)

    plan, reason = plan_resident_launch(record=_record())

    assert reason == "planned"
    assert plan is not None
    assert plan.xlsx_revision_plan_source == REVISION_SOURCE
    assert plan.environment(base={})[RESIDENT_ENV_XLSX_REVISION_PLAN_SOURCE] == REVISION_SOURCE


def test_absent_revision_source_leaves_the_lane_inactive(monkeypatch, tmp_path):
    """No value, no key: the Resident resolves None and the lane stays off."""
    _configured(monkeypatch, tmp_path)

    plan, reason = plan_resident_launch(record=_record())

    assert reason == "planned"
    assert plan.xlsx_revision_plan_source is None
    assert RESIDENT_ENV_XLSX_REVISION_PLAN_SOURCE not in plan.environment(base={})


def test_plan_clears_an_ambient_revision_source_it_never_authorized(
    monkeypatch, tmp_path
):
    """The environment the child receives is the plan's, not the shell's.

    A value the owner did not configure through the plan must not reach the
    Resident: forwarding it would start a revision lane no one approved.
    """
    _configured(monkeypatch, tmp_path)
    inherited = plan_resident_launch(record=_record())[0].environment(base={})
    inherited[RESIDENT_ENV_XLSX_REVISION_PLAN_SOURCE] = "unreviewed_module:make_source"

    plan, _ = plan_resident_launch(record=_record())
    emitted = plan.environment(base=inherited)

    assert plan.xlsx_revision_plan_source is None
    assert RESIDENT_ENV_XLSX_REVISION_PLAN_SOURCE not in emitted


@pytest.mark.parametrize("value", IMPOSSIBLE, ids=[
    "no-colon", "three-parts", "empty-last-segment", "empty-module",
    "empty-middle-segment", "illegal-identifier", "a-file-path", "embedded-space",
])
def test_malformed_revision_source_refuses_the_launch_instead_of_forwarding_it(
    monkeypatch, tmp_path, value
):
    """Refuse, do not pass a broken value down.

    The Resident would fail closed on its own, but by then the Connector has
    spawned a child the owner never configured — the short-lived-process failure
    this whole gate exists to prevent.
    """
    _configured(monkeypatch, tmp_path)
    monkeypatch.setenv(RESIDENT_ENV_XLSX_REVISION_PLAN_SOURCE, value)

    plan, reason = plan_resident_launch(record=_record())

    assert plan is None
    assert reason == REASON_XLSX_REVISION_PLAN_SOURCE_INVALID


@pytest.mark.parametrize("value", [
    "kagent.a:b", "kagent.pkg.mod:make_factory", "_private.mod:attr_1",
])
def test_a_real_dotted_module_name_still_plans(monkeypatch, tmp_path, value):
    """Tightening the shape must not reject anything that could import."""
    _configured(monkeypatch, tmp_path)
    monkeypatch.setenv(RESIDENT_ENV_XLSX_REVISION_PLAN_SOURCE, value)

    plan, reason = plan_resident_launch(record=_record())

    assert reason == "planned"
    assert plan.xlsx_revision_plan_source == value


def test_no_factory_named_key_is_looser_than_the_revision_key(monkeypatch, tmp_path):
    """One shape for every deployment-supplied factory, revision included.

    ``PADIEM_AGENT_REQUEST_PORT`` and the TXT source name a ``module:attribute``
    the same way, so the same impossible names are refused for them too rather
    than only being caught one process later.
    """
    _configured(monkeypatch, tmp_path)

    monkeypatch.setenv(RESIDENT_ENV_VERIFIED_TEXT_PLAN_SOURCE, "kagent.:missing_attribute")
    assert plan_resident_launch(record=_record())[1] == REASON_VERIFIED_TEXT_PLAN_SOURCE_INVALID
    monkeypatch.setenv(RESIDENT_ENV_VERIFIED_TEXT_PLAN_SOURCE, "")

    monkeypatch.setenv(RESIDENT_ENV_REQUEST_PORT, "kagent.:missing_attribute")
    assert plan_resident_launch(record=_record())[1] == REASON_REQUEST_PORT_UNCONFIGURED
    monkeypatch.setenv(RESIDENT_ENV_REQUEST_PORT, REQUEST_PORT)

    assert plan_resident_launch(record=_record())[1] == "planned"


def test_environment_carries_only_the_canonical_keys(monkeypatch, tmp_path):
    """The plan hands the Resident a *name*.

    Never a path, an approval, a credential or a seventh piece of material that
    would widen what the child may act on.
    """
    _configured(monkeypatch, tmp_path)
    monkeypatch.setenv(RESIDENT_ENV_XLSX_REVISION_PLAN_SOURCE, REVISION_SOURCE)
    monkeypatch.setenv(RESIDENT_ENV_VERIFIED_TEXT_PLAN_SOURCE, "kagent.mod:make_factory")

    plan, _ = plan_resident_launch(record=_record())
    emitted = plan.environment(base={})

    assert set(emitted) == {
        RESIDENT_ENV_DEVICE_ID,
        RESIDENT_ENV_AUTHORITY_REF,
        RESIDENT_ENV_CREDENTIAL_DIR,
        RESIDENT_ENV_REQUEST_PORT,
        RESIDENT_ENV_BROKER_URL,
        RESIDENT_ENV_VERIFIED_TEXT_PLAN_SOURCE,
        RESIDENT_ENV_XLSX_REVISION_PLAN_SOURCE,
    }
    assert isinstance(plan, ResidentLaunchPlan)


# -- the installed customer release -----------------------------------------


def test_installed_release_pins_the_reviewed_revision_source(tmp_path):
    """A customer machine gets the reviewed factory, never an ambient name.

    The installed release pins its own reviewed plan sources, so an exported
    value cannot substitute a test fixture or an unreviewed module, and the
    pinned name is the one #5835 implements.
    """
    from claw_connect.installed_runtime import (
        XLSX_REVISION_PLAN_SOURCE, installed_resident_environ,
    )

    ambient = {
        RESIDENT_ENV_XLSX_REVISION_PLAN_SOURCE: "kagent.test_fixture:make_fake_plan_source",
        RESIDENT_ENV_VERIFIED_TEXT_PLAN_SOURCE: "untrusted_module:factory",
    }
    installed = installed_resident_environ(state_dir=tmp_path, environ=ambient)

    assert installed[RESIDENT_ENV_XLSX_REVISION_PLAN_SOURCE] == XLSX_REVISION_PLAN_SOURCE
    plan, reason = plan_resident_launch(record=_record(), environ=installed)

    assert reason == "planned"
    assert plan.xlsx_revision_plan_source == XLSX_REVISION_PLAN_SOURCE
    assert plan.verified_text_plan_source is not None
    assert plan.environment(base={})[RESIDENT_ENV_XLSX_REVISION_PLAN_SOURCE] == (
        XLSX_REVISION_PLAN_SOURCE)
    # The caller's mapping is not mutated by planning.
    assert ambient[RESIDENT_ENV_XLSX_REVISION_PLAN_SOURCE] == (
        "kagent.test_fixture:make_fake_plan_source"
    )


def test_the_pinned_revision_source_is_a_module_the_resident_can_resolve():
    """The pin names a real importable factory, not a hoped-for one."""

    from claw_connect.installed_runtime import XLSX_REVISION_PLAN_SOURCE

    module_name, _, attribute = XLSX_REVISION_PLAN_SOURCE.partition(":")
    assert module_name == "kagent.verified_p01_xlsx_revision_plan_source"
    assert attribute == "make_p01_xlsx_revision_plan_source"


def test_installed_device_still_launches_with_the_canonical_boundary(tmp_path):
    """Pinning one optional lane must not disturb the boundary itself."""
    installed = installed_resident_environ(state_dir=tmp_path, environ={})

    plan, reason = plan_resident_launch(record=_record(), environ=installed)

    assert reason == "planned"
    assert plan.environment(base={})[RESIDENT_ENV_DEVICE_ID] == DEVICE_ID
