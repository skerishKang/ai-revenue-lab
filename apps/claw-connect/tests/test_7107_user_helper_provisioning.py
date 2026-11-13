"""#7107 PR-B — the Connector self-provisions the helper after enrollment.

#7564 adds what the provisioning does to the secret's folder: it works only in
a folder this user owns (or creates), writes a new secret every time, and reads
the descriptors back before it registers the task. The Windows calls sit
behind one small object, so the walk is exercised here with an in-memory
stand-in on any machine; ``test_7564_install_lockdown_windows.py`` runs the
real calls against a sandbox folder.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from claw_connect import user_helper_provisioning as provisioning
from claw_connect import user_helper_registration as registration

DEVICE = "abcdefghijklmnopqrstuvwx1234567890ABCDEFGHIJKLMNOPQRSTfi$D62t1"
USER = r"PC\padiem"
USER_SID = "S-1-5-21-1111111111-2222222222-3333333333-1001"
OTHER_SID = "S-1-5-21-1111111111-2222222222-3333333333-1002"
POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
#: What a folder made the old way carries: whatever its parent hands down.
INHERITED = "D:AI(A;OICIID;FA;;;SY)(A;OICIID;FA;;;BA)(A;OICIID;0x1200a9;;;BU)"


class FakeSecurity:
    """An in-memory stand-in for the Windows calls the provisioning locks with.

    Objects are tracked by file identity, so a descriptor follows its file
    through a rename exactly as it does on disk. An object this stand-in did
    not create answers with ``existing_owner`` and the inherited access list.
    """

    def __init__(self, *, user: str = USER_SID, existing_owner: str | None = None) -> None:
        self.user = user
        self.existing_owner = existing_owner or user
        self.described: dict[tuple[int, int], str] = {}
        self.loosen: set[str] = set()

    @staticmethod
    def _key(path: str) -> tuple[int, int]:
        found = os.stat(path, follow_symlinks=False)
        return (found.st_dev, found.st_ino)

    def current_user_sid(self) -> str:
        return self.user

    def is_link(self, path: str) -> bool:
        return os.path.islink(path)

    def describe(self, path: str) -> str:
        if os.path.basename(path) in self.loosen:
            return "O:" + self.user + INHERITED
        return self.described.get(self._key(path), "O:" + self.existing_owner + INHERITED)

    def owner_sid(self, path: str) -> str:
        return self.describe(path).split("D:", 1)[0][2:]

    def canonical(self, sddl: str) -> str:
        return sddl

    def create_folder(self, path: str, sddl: str) -> None:
        os.mkdir(path)
        self.described[self._key(path)] = sddl

    def set_access(self, path: str, sddl: str) -> None:
        self.described[self._key(path)] = "O:" + self.owner_sid(path) + sddl[sddl.index("D:"):]

    def create_file(self, path: str, sddl: str, payload: bytes) -> None:
        with open(path, "xb") as handle:
            handle.write(payload)
        self.described[self._key(path)] = sddl


def _provision(tmp_path: Path, root: Path, **overrides):
    values = dict(
        device_id=DEVICE, state_dir=root, secret_dir=tmp_path / "ProgramData",
        user=USER, platform="win32", python_executable=sys.executable,
        security=FakeSecurity(), powershell=POWERSHELL,
    )
    values.update(overrides)
    return provisioning.provision_user_helper(**values)


def _scripts(calls: list[list[str]]) -> list[str]:
    assert all(call[0] == POWERSHELL for call in calls), calls
    return [call[-1] for call in calls]


def _state(tmp_path: Path) -> Path:
    root = tmp_path / "ClawConnect"
    (root / "claw_connect").mkdir(parents=True)
    return root


def _runner(calls: list[list[str]], fail=None):
    def run(argv, **kwargs):
        calls.append(list(argv))
        if fail is not None and fail(argv):
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    return run


def _runtime_class(runtime):
    return next(
        obj for obj in vars(runtime).values()
        if isinstance(obj, type) and hasattr(obj, "_provision_user_helper")
    )


def test_enrollment_provisioning_creates_secret_and_registers_a_started_task(tmp_path):
    root = _state(tmp_path)
    secret_dir = tmp_path / "ProgramData"
    calls: list[list[str]] = []
    result = _provision(tmp_path, root, run=_runner(calls))
    assert result["status"] == "installed"
    secret = (secret_dir / "helper.secret").read_text(encoding="ascii").strip()
    assert len(secret) == 64
    assert len(bytes.fromhex(secret)) == 32
    status = (root / "helper-status.json").read_text(encoding="utf-8")
    assert secret not in status
    # Windows PowerShell is called by its full path, twice: the running helper
    # is ended first, and the task is registered only after the secret exists.
    stop, script = _scripts(calls)
    assert "Stop-ScheduledTask" in stop and "Register-ScheduledTask" not in stop
    assert DEVICE in script
    assert "-WorkingDirectory" in script
    assert "Start-ScheduledTask" in script
    assert secret not in script and secret not in stop


def test_the_task_definition_carries_the_install_root_and_raw_id(tmp_path):
    root = _state(tmp_path)
    launch = registration.build_launch(
        python_executable=sys.executable, device_id=DEVICE,
        secret_file=r"C:\ProgramData\Padiem\helper.secret",
        working_directory=str(root),
    )
    definition = registration.task_definition(launch=launch, user=USER)
    assert definition["Action"]["WorkingDirectory"] == str(root)
    assert DEVICE in definition["Action"]["Argument"]
    script = registration.register_script(definition)
    assert "-WorkingDirectory" in script
    assert "Start-ScheduledTask" in script
    assert DEVICE in script


def test_a_task_registration_failure_is_reported_not_raised(tmp_path):
    root = _state(tmp_path)
    result = _provision(
        tmp_path, root,
        run=_runner([], fail=lambda argv: "Register-ScheduledTask" in argv[-1]),
    )
    assert result["status"] == "not_installed"
    assert result["reason"] == "task_registration_failed"
    assert (root / "helper-status.json").is_file()


def test_missing_claw_connect_skips_without_creating_a_secret(tmp_path):
    root = tmp_path / "ClawConnect"
    root.mkdir()
    secret_dir = tmp_path / "ProgramData"
    result = _provision(tmp_path, root, run=_runner([]))
    assert result["status"] == "skipped"
    assert result["reason"] == "claw_connect_missing"
    assert not (secret_dir / "helper.secret").exists()


# -- #7564: the folder and the secret are locked, and nothing old is kept -----

def test_the_folder_and_the_secret_get_their_own_descriptors(tmp_path):
    root = _state(tmp_path)
    security = FakeSecurity()
    result = _provision(tmp_path, root, run=_runner([]), security=security)
    assert result["status"] == "installed"
    folder = tmp_path / "ProgramData"
    # Inheritance is cut and exactly three accounts are named, by SID: SYSTEM,
    # the Administrators group and this user.
    owner, protected, entries = provisioning.descriptor_facts(security.describe(str(folder)))
    assert owner == USER_SID and protected
    assert entries == frozenset({
        ("S-1-5-18", 0x1F01FF, frozenset({"OI", "CI"})),
        ("S-1-5-32-544", 0x1F01FF, frozenset({"OI", "CI"})),
        (USER_SID, 0x1F01FF, frozenset({"OI", "CI"})),
    })
    owner, protected, entries = provisioning.descriptor_facts(
        security.describe(str(folder / "helper.secret")))
    assert owner == USER_SID and protected
    assert entries == frozenset({
        ("S-1-5-18", 0x1F01FF, frozenset()),
        ("S-1-5-32-544", 0x1F01FF, frozenset()),
        (USER_SID, 0x120089, frozenset()),
    })
    assert provisioning.folder_sddl(USER_SID).startswith("O:" + USER_SID + "D:PAI(")
    assert provisioning.secret_sddl(USER_SID).startswith("O:" + USER_SID + "D:PAI(")
    for bad in ("", "Everyone", "S-1-5-18)(A;;FA;;;WD", None):
        with pytest.raises(ValueError):
            provisioning.folder_sddl(bad)
        with pytest.raises(ValueError):
            provisioning.secret_sddl(bad)


def test_an_account_windows_spells_with_an_alias_is_still_this_user(tmp_path):
    """The built-in administrator account comes back from Windows as ``LA``.

    Found on the CI runner, whose account is that one: the folder this lane had
    just made was read back as owned by ``LA`` and refused as not its own. The
    owner is compared as an exact SID, and the entries only after both strings
    were spelled by Windows.
    """
    builtin = "S-1-5-21-1111111111-2222222222-3333333333-500"

    class Aliasing(FakeSecurity):
        def owner_sid(self, path: str) -> str:
            return super().owner_sid(path).replace("LA", builtin)

        def describe(self, path: str) -> str:
            return super().describe(path).replace(builtin, "LA")

        def canonical(self, sddl: str) -> str:
            return sddl.replace(builtin, "LA")

    root = _state(tmp_path)
    security = Aliasing(user=builtin)
    result = _provision(tmp_path, root, run=_runner([]), security=security)
    assert result["status"] == "installed", result
    assert "LA" in security.describe(str(tmp_path / "ProgramData"))
    # ... and an alias never makes another owner pass for this user.
    other = Aliasing(user=builtin, existing_owner=OTHER_SID)
    (tmp_path / "Other").mkdir()
    refused = _provision(
        tmp_path, root, run=_runner([]), security=other, secret_dir=tmp_path / "Other")
    assert refused["reason"] == "state_dir_owner_untrusted", refused


def test_an_existing_secret_is_replaced_and_never_kept(tmp_path):
    root = _state(tmp_path)
    folder = tmp_path / "ProgramData"
    folder.mkdir()
    planted = "5" * 64
    (folder / "helper.secret").write_text(planted + "\n", encoding="ascii")
    security = FakeSecurity()
    calls: list[list[str]] = []

    first = _provision(tmp_path, root, run=_runner(calls), security=security)
    assert first["status"] == "installed" and first["secret_created"] is True
    one = (folder / "helper.secret").read_text(encoding="ascii")
    assert one.strip() != planted and len(bytes.fromhex(one.strip())) == 32
    # The loose folder this user already owned was locked, not left as it was.
    assert provisioning.descriptor_facts(security.describe(str(folder)))[1] is True

    second = _provision(tmp_path, root, run=_runner(calls), security=security)
    assert second["status"] == "installed"
    two = (folder / "helper.secret").read_text(encoding="ascii")
    assert two not in (one, planted + "\n")
    assert [child.name for child in folder.iterdir()] == ["helper.secret"]
    for script in _scripts(calls):
        assert one.strip() not in script and two.strip() not in script


def test_the_order_is_lock_stop_secret_register(tmp_path):
    root = _state(tmp_path)
    folder = tmp_path / "ProgramData"
    seen: list[tuple[str, bool, bool]] = []
    security = FakeSecurity()

    def run(argv, **kwargs):
        kind = "stop" if "Stop-ScheduledTask" in argv[-1] else "register"
        locked = folder.is_dir() and provisioning.descriptor_facts(
            security.describe(str(folder)))[1]
        seen.append((kind, locked, (folder / "helper.secret").exists()))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    assert _provision(tmp_path, root, run=run, security=security)["status"] == "installed"
    # The helper is ended once the folder is locked and before the secret is
    # written; the task is registered only when the secret is in place.
    assert seen == [("stop", True, False), ("register", True, True)]


@pytest.mark.parametrize(("owner", "reason"), [
    (OTHER_SID, "state_dir_owner_untrusted"),
    ("S-1-5-32-544", "state_dir_managed_by_administrator"),
    ("S-1-5-18", "state_dir_managed_by_administrator"),
])
def test_a_folder_this_user_does_not_own_is_left_exactly_as_it_is(tmp_path, owner, reason):
    root = _state(tmp_path)
    folder = tmp_path / "ProgramData"
    folder.mkdir()
    (folder / "helper.secret").write_text("5" * 64 + "\n", encoding="ascii")
    security = FakeSecurity(existing_owner=owner)
    before = security.describe(str(folder))
    calls: list[list[str]] = []

    result = _provision(tmp_path, root, run=_runner(calls), security=security)

    assert result["status"] == "not_installed" and result["reason"] == reason
    # Nothing was stopped, written or registered, and the folder was not touched.
    assert calls == []
    assert security.describe(str(folder)) == before
    assert (folder / "helper.secret").read_text(encoding="ascii") == "5" * 64 + "\n"
    assert [child.name for child in folder.iterdir()] == ["helper.secret"]


def test_a_running_helper_that_does_not_end_stops_the_provisioning(tmp_path):
    root = _state(tmp_path)
    folder = tmp_path / "ProgramData"
    calls: list[list[str]] = []
    result = _provision(
        tmp_path, root,
        run=_runner(calls, fail=lambda argv: "Stop-ScheduledTask" in argv[-1]),
    )
    assert result["status"] == "not_installed"
    assert result["reason"] == "helper_still_running"
    assert len(calls) == 1 and not (folder / "helper.secret").exists()


def test_a_secret_whose_descriptor_cannot_be_confirmed_is_removed_not_served(tmp_path):
    root = _state(tmp_path)
    folder = tmp_path / "ProgramData"
    security = FakeSecurity()
    security.loosen.add("helper.secret")  # the disk answers with the inherited list
    calls: list[list[str]] = []
    result = _provision(tmp_path, root, run=_runner(calls), security=security)
    assert result["status"] == "not_installed"
    assert result["reason"] == "secret_acl_failed"
    assert not (folder / "helper.secret").exists()
    assert all("Register-ScheduledTask" not in script for script in _scripts(calls))


def test_no_windows_powershell_means_no_provisioning(tmp_path, monkeypatch):
    root = _state(tmp_path)
    monkeypatch.setattr(provisioning, "windows_powershell_executable", lambda: None)
    calls: list[list[str]] = []
    result = _provision(tmp_path, root, run=_runner(calls), powershell=None)
    assert result["status"] == "not_installed"
    assert result["reason"] == "powershell_missing"
    assert calls == [] and not (tmp_path / "ProgramData").exists()


def test_the_provisioning_source_names_no_bare_executable_and_no_account_by_name():
    source = Path(provisioning.__file__).read_text(encoding="utf-8")
    # #7637 left this file's own calls out of its scope; they are closed here.
    for pattern in ('"powershell.exe"', '"icacls"', "icacls", '"SYSTEM:(R)"', ":(M)"):
        assert pattern not in source, pattern
    assert "windows_powershell_executable()" in source
    # The reuse condition is gone: nothing reads an existing secret back.
    assert "read_bytes().strip()" not in source
    assert "secret_path.is_file()" not in source


def test_the_stop_script_ends_only_this_task_and_waits_for_it():
    script = registration.stop_script()
    assert script.count("-TaskPath '\\Padiem\\' -TaskName 'PadiemUserSessionHelper'") == 3
    assert "Stop-ScheduledTask" in script
    assert "$task.State -ne 'Running'" in script
    assert "exit 3" in script
    assert "Unregister-ScheduledTask" not in script and "Register-ScheduledTask" not in script


def test_the_runtime_provisions_after_enrollment(monkeypatch, tmp_path):
    runtime = pytest.importorskip("claw_connect.runtime")
    called: dict = {}

    def fake_provision(**kwargs):
        called.update(kwargs)
        return {"status": "installed"}

    monkeypatch.setattr(provisioning, "provision_user_helper", fake_provision)

    class Enrollment:
        def committed_record(self):
            return SimpleNamespace(device_id=DEVICE, is_enrolled=lambda: True)

    fake = SimpleNamespace(_enrollment=Enrollment(), _state_dir=tmp_path)
    _runtime_class(runtime)._provision_user_helper(fake)
    assert called == {"device_id": DEVICE, "state_dir": tmp_path}


def test_a_missing_record_does_not_provision(monkeypatch, tmp_path):
    runtime = pytest.importorskip("claw_connect.runtime")
    called = []
    monkeypatch.setattr(provisioning, "provision_user_helper",
                        lambda **kwargs: called.append(kwargs) or {"status": "installed"})

    class Enrollment:
        def committed_record(self):
            return None

    fake = SimpleNamespace(_enrollment=Enrollment(), _state_dir=tmp_path)
    _runtime_class(runtime)._provision_user_helper(fake)
    assert called == []
