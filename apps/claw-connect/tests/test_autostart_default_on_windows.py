"""Logon autostart contract for Claw Connect (#4139 item 6, Windows-only).

The 2026-10-13 founder-led AX pilot contract replaced the old opt-in /
default-OFF behaviour: owner-assisted installation must register logon
autostart **by default** once the canonical credential is durably committed,
and the owner can turn it off in a way that survives restart and logon.

These are the bounded acceptance tests for that change. Every one of them uses
the memory seams, so no test ever reads or writes a real registry — the real
HKCU stores are exercised separately by an operator-run check, never by CI.

Nothing here claims a live gateway, a signed install or a real PC E2E.
"""

from __future__ import annotations

import inspect
import json
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from claw_connect import __main__ as cli  # noqa: E402
from claw_connect.autostart import (  # noqa: E402
    ACTION_KEEP,
    ACTION_SUSPEND,
    EVENT_REVOKE,
    EVENT_TRANSIENT_OFFLINE,
    EVENT_UNPAIR,
    EVENT_USER_PAUSE,
    PREFERENCE_OFF,
    PREFERENCE_ON,
    PREFERENCE_KEY,
    REGISTRATION_CORRUPT,
    REGISTRATION_REGISTERED,
    RUN_KEY,
    Autostart,
    AutostartOutcome,
    AutostartRefused,
    MemoryPreferenceStore,
    MemoryRunKeyStore,
    WindowsPreferenceStore,
    WindowsRunKeyStore,
)
from claw_connect.connection import ConnectionController, ConnectionState  # noqa: E402
from claw_connect.enrollment import (  # noqa: E402
    LIFECYCLE_CREDENTIAL_EXPIRED,
    LIFECYCLE_PAIRED_OFFLINE,
    ConnectorEnrollment,
    EnrollmentRecord,
)

NAME = "PadiemClawConnect"
COMMAND = r'"C:\Python311\python.exe" -m claw_connect start'


def _autostart() -> tuple[Autostart, MemoryRunKeyStore, MemoryPreferenceStore]:
    store = MemoryRunKeyStore()
    preferences = MemoryPreferenceStore()
    return (
        Autostart(NAME, store, preference_store=preferences),
        store,
        preferences,
    )


def _enrolled_record(**overrides: object) -> EnrollmentRecord:
    """The exact object the stage-then-publish commit publishes."""
    fields: dict[str, object] = {
        "device_id": "pc_abc123",
        "binding_ref": "binding-1",
        "account_ref": "acct-1",
        "workspace_ref": "ws-1",
        "credential_generation": 2,
        "device_lifecycle": LIFECYCLE_PAIRED_OFFLINE,
    }
    fields.update(overrides)
    return EnrollmentRecord(**fields)  # type: ignore[arg-type]


# -- 1. first successful enrolled install ----------------------------------
def test_first_successful_enrolled_install_writes_the_run_entry_once():
    autostart, store, preferences = _autostart()

    outcome = autostart.register_after_install(COMMAND, _enrolled_record())

    assert outcome is AutostartOutcome.REGISTERED
    assert autostart.classify() == REGISTRATION_REGISTERED
    assert store.values == {NAME: COMMAND}
    assert store.writes == [(NAME, COMMAND)]
    # A default-on install is not an owner opt-in, so no choice is fabricated.
    assert preferences.values == {}
    assert autostart.preference() is None

    # Idempotent: a second install/reconcile writes nothing more.
    assert (
        autostart.register_after_install(COMMAND, _enrolled_record())
        is AutostartOutcome.ALREADY_REGISTERED
    )
    assert store.writes == [(NAME, COMMAND)]


# -- 2. the owner's opt-out is durable -------------------------------------
def test_the_owners_opt_out_survives_a_simulated_restart_and_logon():
    autostart, store, preferences = _autostart()
    autostart.register_after_install(COMMAND, _enrolled_record())
    autostart.disable()
    assert store.values == {}

    # Simulated restart/logon: a brand-new instance over the *same* durable
    # per-user stores, exactly as the registry persists them across a reboot.
    restarted = Autostart(NAME, store, preference_store=preferences)
    assert restarted.preference() == PREFERENCE_OFF
    assert (
        restarted.register_after_install(COMMAND, _enrolled_record())
        is AutostartOutcome.SUPPRESSED_BY_OWNER
    )
    assert store.values == {}
    # Only the first install ever wrote; the opt-out was never overridden.
    assert store.writes == [(NAME, COMMAND)]

    # An explicit re-enable is still allowed — the opt-out is a preference, not
    # a lock.
    restarted.enable(COMMAND, _enrolled_record())
    assert restarted.is_enabled() is True


# -- 3. transient disconnect keeps the default-on registration -------------
def test_default_on_reconnect_after_a_transient_disconnect():
    autostart, store, _ = _autostart()
    autostart.register_after_install(COMMAND, _enrolled_record())

    reachable = {"value": True}
    controller = ConnectionController(lambda: reachable["value"])
    controller.connect()
    controller.poll()
    assert controller.state is ConnectionState.CONNECTED

    reachable["value"] = False
    controller.poll()
    assert controller.state is ConnectionState.DISCONNECTED

    # A flaky network is not a logon-startup decision.
    assert autostart.apply_lifecycle(EVENT_TRANSIENT_OFFLINE) == ACTION_KEEP
    assert autostart.is_enabled() is True
    assert autostart.preference() is None
    assert store.values == {NAME: COMMAND}


# -- 4. no durable credential, no autostart --------------------------------
def test_no_durable_credential_means_no_autostart(tmp_path):
    autostart, store, _ = _autostart()

    # A first-launch record: an identity exists, but no Broker binding does.
    fresh = ConnectorEnrollment(state_dir=tmp_path / "state")
    assert fresh.record().is_enrolled() is False

    with pytest.raises(AutostartRefused):
        autostart.register_after_install(COMMAND, fresh.record())

    # A record-shaped claim that is not a record is refused too.
    with pytest.raises(AutostartRefused):
        autostart.register_after_install(COMMAND, object())  # type: ignore[arg-type]

    assert store.values == {}
    assert store.writes == []
    assert autostart.is_enabled() is False


# -- 5. a dead binding is not a live credential ----------------------------
def test_a_revoked_or_expired_credential_is_never_registered():
    autostart, store, _ = _autostart()
    revoked = _enrolled_record(revoked=True)
    expired = _enrolled_record(device_lifecycle=LIFECYCLE_CREDENTIAL_EXPIRED)

    for record in (revoked, expired):
        with pytest.raises(AutostartRefused):
            autostart.register_after_install(COMMAND, record)
    assert store.values == {}


# -- 6. a failed persist never leaves a premature autostart ---------------
def test_a_failed_persist_leaves_no_premature_autostart(tmp_path, monkeypatch):
    autostart, store, _ = _autostart()
    connector = ConnectorEnrollment(state_dir=tmp_path / "state")
    connector.record()  # first launch materialises the un-enrolled record

    def _boom(record):  # noqa: ANN001
        raise OSError("state directory is unwritable")

    monkeypatch.setattr(connector, "_write", _boom)
    with pytest.raises(OSError):
        connector._write(connector.record())

    # Stage-then-publish (LOCAL2 D1) means a failed write publishes nothing, so
    # the record the connector exposes is still un-enrolled and the default-on
    # path refuses. No Run value is written before the credential is durable.
    assert connector.record().is_enrolled() is False
    with pytest.raises(AutostartRefused):
        autostart.register_after_install(COMMAND, connector.record())
    assert store.values == {}


# -- 7. a corrupt registration is refused, not adopted --------------------
def test_a_corrupt_run_command_refuses_and_is_left_untouched():
    autostart, store, _ = _autostart()
    store.values[NAME] = "   "
    assert autostart.classify() == REGISTRATION_CORRUPT
    assert autostart.is_enabled() is False

    with pytest.raises(AutostartRefused):
        autostart.register_after_install(COMMAND, _enrolled_record())

    # Evidence preserved: the default-on path never silently overwrites a value
    # it does not recognise, and never reports it as enabled.
    assert store.values == {NAME: "   "}
    assert store.writes == []


# -- 8. no credential material in the registry command --------------------
def test_a_registry_command_never_carries_credential_material():
    autostart, store, _ = _autostart()
    for command in (
        'python -m claw_connect start --token=abc',
        'python -m claw_connect start pairing_code=123456',
        'python -m claw_connect start --api_key:zzz',
    ):
        with pytest.raises(AutostartRefused):
            autostart.enable(command, _enrolled_record())
        with pytest.raises(AutostartRefused):
            autostart.register_after_install(command, _enrolled_record())
    assert store.values == {}

    # The command the connector actually registers is secret-free.
    real = cli._autostart_command()  # noqa: SLF001
    autostart.register_after_install(real, _enrolled_record())
    assert autostart.is_enabled() is True


# -- 9. no elevation, no machine-wide hive --------------------------------
def _code_only(path: Path) -> str:
    """The module's executable text: comments and docstrings removed.

    A prose mention of HKLM (this module documents what it deliberately does
    *not* do) must not satisfy the guard, and neither must a comment.
    """
    kept: list[str] = []
    with path.open("rb") as handle:
        for token in tokenize.tokenize(handle.readline):
            if token.type == tokenize.COMMENT:
                continue
            if token.type == tokenize.STRING and token.string[:3] in ('"""', "'''"):
                continue
            kept.append(token.string)
    return " ".join(kept)


def test_no_elevation_is_required_and_hklm_is_never_referenced():
    code = _code_only(ROOT / "claw_connect" / "autostart.py")
    for forbidden in (
        "HKEY_LOCAL_MACHINE",
        "HKLM",
        "RunAs",
        "New-Service",
        "shell=True",
        "win32com",
    ):
        assert forbidden not in code, f"autostart.py must not use {forbidden}"
    # The only hive this module may touch is the current user's.
    assert "HKEY_CURRENT_USER" in code


# -- 10. pause vs revoke --------------------------------------------------
def test_pause_keeps_the_registration_while_revoke_suspends_it():
    autostart, store, _ = _autostart()
    autostart.register_after_install(COMMAND, _enrolled_record())

    # Pause is connection-scoped and non-durable: the PC still starts at logon.
    assert autostart.apply_lifecycle(EVENT_USER_PAUSE) == ACTION_KEEP
    assert autostart.is_enabled() is True

    # Revoke/unpair suspends the registration but keeps the owner's choice, so
    # a later re-enrollment falls back to the contract default.
    for event in (EVENT_UNPAIR, EVENT_REVOKE):
        autostart.enable(COMMAND, _enrolled_record())
        assert autostart.apply_lifecycle(event) == ACTION_SUSPEND
        assert store.values == {}
        assert autostart.preference() == PREFERENCE_ON
        assert (
            autostart.register_after_install(COMMAND, _enrolled_record())
            is AutostartOutcome.REGISTERED
        )

    # An unknown event is a programming error, never a silent no-op.
    with pytest.raises(ValueError):
        autostart.apply_lifecycle("something_new")


# -- 11. no per-task approval machinery was invented ----------------------
def test_no_per_task_approval_is_invented():
    parameters = list(
        inspect.signature(Autostart.register_after_install).parameters
    )
    # Exactly the command and the committed credential — no approval, consent or
    # confirmation step beyond the owner's own on/off choice.
    assert parameters == ["self", "command", "enrollment"]
    assert {outcome.value for outcome in AutostartOutcome} == {
        "registered",
        "already_registered",
        "suppressed_by_owner",
        "opt_out_reconciled",
    }


# -- 12. a test run can never touch the real profile ----------------------
@pytest.mark.skipif(
    sys.platform != "win32", reason="the real HKCU stores are Windows-only"
)
def test_the_windows_stores_honour_the_scratch_key_overrides(monkeypatch):
    """The wrapper test drives the real stores; without this the round trip
    would leave a durable opt-out in the developer's own profile."""
    monkeypatch.setenv("CLAW_CONNECT_AUTOSTART_RUN_KEY", r"Software\Scratch\Run")
    monkeypatch.setenv("CLAW_CONNECT_AUTOSTART_PREF_KEY", r"Software\Scratch\Pref")
    # Constructing a store never touches the registry, so this assertion is
    # side-effect free.
    assert WindowsRunKeyStore()._key == r"Software\Scratch\Run"  # noqa: SLF001
    assert WindowsPreferenceStore()._key == r"Software\Scratch\Pref"  # noqa: SLF001

    monkeypatch.delenv("CLAW_CONNECT_AUTOSTART_RUN_KEY")
    monkeypatch.delenv("CLAW_CONNECT_AUTOSTART_PREF_KEY")
    assert WindowsRunKeyStore()._key == RUN_KEY  # noqa: SLF001
    assert WindowsPreferenceStore()._key == PREFERENCE_KEY  # noqa: SLF001


# -- 13. the owner CLI is not a credential bypass -------------------------
def test_the_owner_cli_route_is_not_a_credential_bypass():
    autostart, store, preferences = _autostart()

    for evidence in (None, object()):
        with pytest.raises(AutostartRefused):
            autostart.enable(COMMAND, evidence)  # type: ignore[arg-type]

    assert store.values == {}
    assert store.writes == []
    # A refused enable records no choice either: "on" is never written for a
    # registration that did not happen.
    assert preferences.values == {}
    assert autostart.preference() is None


# -- 14. crash between recording `off` and removing the value -------------
class _CrashingRunKeyStore(MemoryRunKeyStore):
    """Kills the process at the moment ``disable()`` removes the value."""

    def __init__(self) -> None:
        super().__init__()
        self.crash_on_delete = False

    def delete(self, name: str) -> None:
        if self.crash_on_delete:
            raise OSError("process terminated before the value was removed")
        super().delete(name)


def test_a_crash_between_recording_off_and_removing_the_entry_is_reconciled():
    store = _CrashingRunKeyStore()
    preferences = MemoryPreferenceStore()
    autostart = Autostart(NAME, store, preference_store=preferences)
    autostart.register_after_install(COMMAND, _enrolled_record())

    # `disable()` records the durable choice first and removes the value second.
    # Terminate it at the removal.
    store.crash_on_delete = True
    with pytest.raises(OSError):
        autostart.disable()
    assert preferences.values == {"Autostart": PREFERENCE_OFF}
    # The orphan: Windows would still execute this at the next logon.
    assert store.values == {NAME: COMMAND}

    # A fresh process over the same durable stores reconciles it — and needs no
    # credential to finish an opt-out. The fault was the dying process, not the
    # store, so it is cleared here.
    store.crash_on_delete = False
    restarted = Autostart(NAME, store, preference_store=preferences)
    assert (
        restarted.register_after_install(COMMAND, _enrolled_record())
        is AutostartOutcome.OPT_OUT_RECONCILED
    )
    assert store.values == {}
    # Idempotent: there is nothing left to reconcile.
    assert (
        restarted.register_after_install(COMMAND, None)  # type: ignore[arg-type]
        is AutostartOutcome.SUPPRESSED_BY_OWNER
    )
    assert store.values == {}


def test_the_opt_out_recovery_never_touches_a_corrupt_or_foreign_entry():
    autostart, store, preferences = _autostart()
    preferences.values["Autostart"] = PREFERENCE_OFF
    store.values[NAME] = "   "

    with pytest.raises(AutostartRefused):
        autostart.register_after_install(COMMAND, _enrolled_record())

    assert store.values == {NAME: "   "}
    assert store.writes == []


# -- 15. the CLI route, driven for real ------------------------------------
def _seed_state_dir(tmp_path: Path, record: EnrollmentRecord) -> Path:
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "enrollment.json").write_text(
        json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return state


#: A test-owned registry root, so the CLI test never creates a product key.
SCRATCH_ROOT = r"Software\PadiemClawConnectSelftest"
SCRATCH_RUN_KEY = rf"{SCRATCH_ROOT}\Run"
SCRATCH_PREF_KEY = rf"{SCRATCH_ROOT}\Pref"


def _isolate_cli(monkeypatch, state_dir: Path) -> None:
    monkeypatch.setenv("CLAW_CONNECT_STATE_DIR", str(state_dir))
    monkeypatch.setenv("CLAW_CONNECT_AUTOSTART_RUN_KEY", SCRATCH_RUN_KEY)
    monkeypatch.setenv("CLAW_CONNECT_AUTOSTART_PREF_KEY", SCRATCH_PREF_KEY)


def _drop_scratch_keys() -> None:
    if sys.platform != "win32":
        return
    import winreg  # noqa: PLC0415

    for key in (SCRATCH_RUN_KEY, SCRATCH_PREF_KEY, SCRATCH_ROOT):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
        except FileNotFoundError:
            pass


def test_the_cli_autostart_on_is_fail_closed_without_a_durable_credential(
    tmp_path, monkeypatch, capsys
):
    _isolate_cli(monkeypatch, tmp_path / "state")
    try:
        code = cli.main(["autostart", "on"])
        payload = capsys.readouterr().out
        assert code == 1
        out = json.loads(payload)
        assert out["ok"] is False
        assert out["detail"] == "no durable, valid canonical credential for this PC"
        # The refusal is bounded and secret-free.
        assert "pairing" not in payload.lower()
        if sys.platform == "win32":
            import winreg  # noqa: PLC0415

            with pytest.raises(FileNotFoundError):
                winreg.OpenKey(winreg.HKEY_CURRENT_USER, SCRATCH_RUN_KEY)
    finally:
        _drop_scratch_keys()


def test_a_refused_cli_autostart_on_creates_no_state(tmp_path, monkeypatch, capsys):
    """The gate reads the committed record read-only: a refusal is not a mutation."""
    state = tmp_path / "state"
    _isolate_cli(monkeypatch, state)
    try:
        assert cli.main(["autostart", "on"]) == 1
        capsys.readouterr()
        # `record()` would mint a first-launch identity as a side effect; the
        # gate must not do that on a path that ends in a refusal.
        assert not (state / "enrollment.json").exists()
    finally:
        _drop_scratch_keys()


def test_the_cli_autostart_on_registers_once_a_durable_credential_exists(
    tmp_path, monkeypatch, capsys
):
    _isolate_cli(monkeypatch, _seed_state_dir(tmp_path, _enrolled_record()))
    try:
        code = cli.main(["autostart", "on"])
        out = json.loads(capsys.readouterr().out)
        assert code == 0
        assert out["ok"] is True
        assert out["enabled"] is True
        assert out["preference"] == "on"
        assert out["command"] == cli._autostart_command()  # noqa: SLF001
        if sys.platform == "win32":
            import winreg  # noqa: PLC0415

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, SCRATCH_RUN_KEY) as key:
                value, _ = winreg.QueryValueEx(key, NAME)
            assert value == out["command"]
    finally:
        _drop_scratch_keys()
