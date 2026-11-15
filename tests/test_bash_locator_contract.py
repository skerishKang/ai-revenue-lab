"""#7630 — the shared test-bash locator's selection contract.

These tests pin the rules the locator applies without running any real shell:
the WSL entry point and Store shims are refused however they are offered,
``PADIEM_TEST_BASH`` wins when it works, broken candidates are filtered, a
machine with no working bash yields a skip reason, and POSIX keeps the old
``shutil.which("bash")`` behavior. Filesystem and probe answers are injected,
so the same assertions run on Linux CI and Windows unchanged.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "_padiem_test_bash_locator_under_contract",
    Path(__file__).resolve().parent / "_test_bash_locator.py")
locator = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = locator
_SPEC.loader.exec_module(locator)


def _absolute(path) -> str:
    return os.path.normpath(os.path.abspath(str(path)))


def _fake_isfile(existing):
    known = {_absolute(p) for p in existing}
    return lambda path: _absolute(path) in known


def _ok_probe():
    """A probe that answers OK and records every candidate it was asked."""
    probed = []

    def probe(bash):
        probed.append(bash)
        return True, ""

    return probe, probed


def _windows_environ(tmp_path, path_entries=(), **extra):
    return {
        "SystemRoot": str(tmp_path / "Windows"),
        "PATH": os.pathsep.join(str(entry) for entry in path_entries),
        **extra,
    }


def _git_install(tmp_path, name):
    """A Git for Windows layout: cmd\\git.exe with bin and usr\\bin bash.exe."""
    root = tmp_path / name
    for directory in (root / "cmd", root / "bin", root / "usr" / "bin"):
        directory.mkdir(parents=True)
    (root / "cmd" / "git.exe").write_bytes(b"git")
    (root / "bin" / "bash.exe").write_bytes(b"bash")
    (root / "usr" / "bin" / "bash.exe").write_bytes(b"bash")
    return root


def test_the_wsl_entry_point_is_refused_even_when_it_is_first_on_path(tmp_path):
    system32 = tmp_path / "Windows" / "System32"
    system32.mkdir(parents=True)
    (system32 / "git.exe").write_bytes(b"git")
    (system32 / "bash.exe").write_bytes(b"bash")
    good = _git_install(tmp_path, "Git")
    environ = _windows_environ(tmp_path, path_entries=[system32, good / "cmd"])
    probe, probed = _ok_probe()
    bash, reason = locator.locate_test_bash(
        environ=environ,
        isfile=_fake_isfile([system32 / "git.exe", system32 / "bash.exe",
                             good / "cmd" / "git.exe", good / "bin" / "bash.exe",
                             good / "usr" / "bin" / "bash.exe"]),
        probe=probe, windows=True)
    assert bash == _absolute(good / "bin" / "bash.exe")
    assert reason == ""
    # The System32 pair was refused outright: never probed, never returned.
    assert probed == [_absolute(good / "bin" / "bash.exe")]
    assert "system32" not in bash.lower().replace("/", os.sep)


def test_padiem_test_bash_wins_over_path_candidates(tmp_path):
    good = _git_install(tmp_path, "Git")
    pinned = tmp_path / "Pinned" / "bash.exe"
    pinned.parent.mkdir()
    pinned.write_bytes(b"bash")
    environ = _windows_environ(tmp_path, path_entries=[good / "cmd"],
                               PADIEM_TEST_BASH=str(pinned))
    probe, probed = _ok_probe()
    bash, reason = locator.locate_test_bash(
        environ=environ,
        isfile=_fake_isfile([pinned, good / "cmd" / "git.exe",
                             good / "bin" / "bash.exe",
                             good / "usr" / "bin" / "bash.exe"]),
        probe=probe, windows=True)
    assert bash == _absolute(pinned)
    assert reason == ""
    assert probed == [_absolute(pinned)]


def test_a_pinned_wsl_entry_point_is_refused_and_the_path_answer_is_used(tmp_path):
    system32 = tmp_path / "Windows" / "System32"
    system32.mkdir(parents=True)
    (system32 / "bash.exe").write_bytes(b"bash")
    good = _git_install(tmp_path, "Git")
    environ = _windows_environ(tmp_path, path_entries=[good / "cmd"],
                               PADIEM_TEST_BASH=str(system32 / "bash.exe"))
    probe, probed = _ok_probe()
    bash, reason = locator.locate_test_bash(
        environ=environ,
        isfile=_fake_isfile([system32 / "bash.exe", good / "cmd" / "git.exe",
                             good / "bin" / "bash.exe"]),
        probe=probe, windows=True)
    assert bash == _absolute(good / "bin" / "bash.exe")
    assert reason == ""
    assert all("system32" not in probed_path.lower().replace("/", os.sep)
               for probed_path in probed)


def test_a_pinned_wsl_exe_leaf_is_refused(tmp_path):
    good = _git_install(tmp_path, "Git")
    wsl = tmp_path / "Windows" / "System32" / "wsl.exe"
    wsl.parent.mkdir(parents=True)
    wsl.write_bytes(b"wsl")
    environ = _windows_environ(tmp_path, path_entries=[good / "cmd"],
                               PADIEM_TEST_BASH=str(wsl))
    probe, probed = _ok_probe()
    bash, reason = locator.locate_test_bash(
        environ=environ, isfile=_fake_isfile([wsl, good / "cmd" / "git.exe",
                                              good / "bin" / "bash.exe"]),
        probe=probe, windows=True)
    assert bash == _absolute(good / "bin" / "bash.exe")
    assert probed == [_absolute(good / "bin" / "bash.exe")]


def test_windowsapps_shims_are_refused_wherever_they_are_offered(tmp_path):
    shim = tmp_path / "Microsoft" / "WindowsApps" / "bash.exe"
    shim.parent.mkdir(parents=True)
    shim.write_bytes(b"bash")
    good = _git_install(tmp_path, "Git")
    pinned_environ = _windows_environ(tmp_path, path_entries=[good / "cmd"],
                                      PADIEM_TEST_BASH=str(shim))
    bash, _reason = locator.locate_test_bash(
        environ=pinned_environ, isfile=_fake_isfile([shim]),
        probe=_ok_probe()[0], windows=True)
    assert bash is None
    assert "WindowsApps" in _reason
    candidates, refusals = locator.candidate_paths(
        environ=_windows_environ(tmp_path, path_entries=[shim.parent]),
        isfile=_fake_isfile([shim.parent / "git.exe", shim]), windows=True)
    assert candidates == [] and refusals


def test_broken_candidates_are_filtered_and_the_reason_names_them(tmp_path):
    good = _git_install(tmp_path, "Git")
    pinned = tmp_path / "Pinned" / "bash.exe"
    pinned.parent.mkdir()
    pinned.write_bytes(b"bash")
    environ = _windows_environ(tmp_path, path_entries=[good / "cmd"],
                               PADIEM_TEST_BASH=str(pinned))

    def broken(_bash):
        return False, "probe exited 1"

    bash, reason = locator.locate_test_bash(
        environ=environ,
        isfile=_fake_isfile([pinned, good / "cmd" / "git.exe",
                             good / "bin" / "bash.exe"]),
        probe=broken, windows=True)
    assert bash is None
    assert reason.startswith("no working bash for tests (")
    assert _absolute(pinned) in reason and "probe exited 1" in reason


def test_a_system32_git_exe_offers_no_candidates(tmp_path):
    system32 = tmp_path / "Windows" / "System32"
    system32.mkdir(parents=True)
    (system32 / "git.exe").write_bytes(b"git")
    (system32 / "bin" / "bash.exe").parent.mkdir(parents=True)
    (system32 / "bin" / "bash.exe").write_bytes(b"bash")
    probe, probed = _ok_probe()
    bash, reason = locator.locate_test_bash(
        environ=_windows_environ(tmp_path, path_entries=[system32]),
        isfile=_fake_isfile([system32 / "git.exe",
                             system32 / "bin" / "bash.exe"]),
        probe=probe, windows=True)
    assert bash is None and probed == []
    assert "WSL" in reason or "System32" in reason


def test_without_any_candidate_the_skip_reason_still_explains_itself(tmp_path):
    bash, reason = locator.locate_test_bash(
        environ=_windows_environ(tmp_path, path_entries=[tmp_path / "empty"]),
        isfile=lambda _path: False, probe=_ok_probe()[0], windows=True)
    assert bash is None
    assert reason.startswith("no working bash for tests (")
    assert "git.exe" in reason


def test_candidates_follow_path_order_and_dedupe(tmp_path):
    first = _git_install(tmp_path, "FirstGit")
    second = _git_install(tmp_path, "SecondGit")
    candidates, refusals = locator.candidate_paths(
        environ=_windows_environ(tmp_path, path_entries=[
            first / "cmd", second / "cmd", first / "cmd"]),
        isfile=_fake_isfile([first / "cmd" / "git.exe",
                             second / "cmd" / "git.exe",
                             first / "bin" / "bash.exe",
                             first / "usr" / "bin" / "bash.exe",
                             second / "bin" / "bash.exe",
                             second / "usr" / "bin" / "bash.exe"]),
        windows=True)
    assert refusals == []
    assert candidates == [_absolute(first / "bin" / "bash.exe"),
                          _absolute(first / "usr" / "bin" / "bash.exe"),
                          _absolute(second / "bin" / "bash.exe"),
                          _absolute(second / "usr" / "bin" / "bash.exe")]


def test_posix_keeps_the_old_which_behavior_without_probing():
    def exploding_probe(_bash):
        raise AssertionError("the POSIX branch must not probe")

    bash, reason = locator.locate_test_bash(
        which=lambda name: "/usr/bin/bash", probe=exploding_probe,
        windows=False)
    assert bash == "/usr/bin/bash" and reason == ""


def test_posix_without_bash_yields_a_skip_reason():
    bash, reason = locator.locate_test_bash(which=lambda _name: None,
                                            windows=False)
    assert bash is None and reason == "no bash on PATH"


@pytest.mark.skipif(os.name != "nt",
                    reason="exercises the real Windows machine's resolution")
def test_on_a_real_windows_machine_the_answer_is_never_the_wsl_entry_point():
    bash, reason = locator.locate_test_bash()
    if bash is None:
        pytest.skip(reason)
    assert "system32" not in bash.lower()
    assert "windowsapps" not in bash.lower()
    ok, detail = locator.default_probe(bash)
    assert ok, detail
