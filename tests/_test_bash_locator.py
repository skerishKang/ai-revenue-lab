"""One shared bash locator for tests that execute a bash binary (#7630).

A bare ``bash`` is unsafe on Windows: CreateProcess resolves it to
``C:\\Windows\\System32\\bash.exe`` — the WSL entry point — before any Git
Bash on PATH, and the GitForWindows registry InstallPath can name an install
whose binaries do not run. Tests must drive their scripts with a working
POSIX shell and must never boot WSL as a side effect.

Windows resolution order (the registry is deliberately ignored):

1. ``PADIEM_TEST_BASH`` — an explicit pin, probed like every other candidate;
2. ``git.exe`` entries on PATH, in PATH order — each Git install offers its
   ``..\\bin\\bash.exe``, ``..\\usr\\bin\\bash.exe`` and
   ``..\\..\\bin\\bash.exe`` siblings.

A candidate counts only when it (a) exists, (b) is not a WSL entry point or a
Microsoft Store shim — nothing under the System32 directory, nothing under
``WindowsApps``, no ``wsl.exe`` leaf — and (c) passes an ``echo`` probe. When
nothing passes, callers skip their tests with the returned reason. On POSIX
the answer stays ``shutil.which("bash")`` exactly as these tests behaved
before.

Load from a test module that knows the repository root::

    _spec = importlib.util.spec_from_file_location(
        "_padiem_test_bash_locator", REPO / "tests" / "_test_bash_locator.py")
    _test_bash = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_test_bash)
    BASH, BASH_SKIP_REASON = _test_bash.locate_test_bash()
"""
from __future__ import annotations

import os
import shutil
import subprocess

#: The probe is one cheap ``echo`` process spawn, but it is still a process
#: spawn; bound it so a hanging binary cannot stall a whole test run.
PROBE_TIMEOUT_SECONDS = 15


def default_probe(bash: str) -> "tuple[bool, str]":
    """``bash -c 'echo <token>'`` must run and print exactly the token back."""
    token = "padiem_bash_probe_ok_%d" % os.getpid()
    try:
        done = subprocess.run(
            [bash, "-c", "echo " + token],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=PROBE_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, "probe did not run (%s)" % type(error).__name__
    if done.returncode != 0:
        return False, "probe exited %d" % done.returncode
    if done.stdout.strip() != token:
        return False, "probe printed something other than its token"
    return True, ""


def _windows_refusal(candidate: str, environ) -> str:
    """Why a path is a WSL entry point or a Store shim on Windows, else ``''``."""
    lowered = os.path.normpath(candidate).lower()
    parts = lowered.split(os.sep)
    if parts and parts[-1] == "wsl.exe":
        return "wsl.exe is not a POSIX shell"
    if "windowsapps" in parts:
        return "a Microsoft Store shim under WindowsApps"
    system_root = os.path.normpath(environ.get("SystemRoot") or "C:\\Windows").lower()
    system32 = system_root + os.sep + "system32"
    if lowered.startswith(system32 + os.sep):
        return "System32 bash.exe is the WSL entry point"
    return ""


def candidate_paths(*, environ=None, isfile=None, windows=None):
    """Ordered Windows bash candidates plus outright refusals, injectable.

    Returns ``(candidates, refusals)``: candidate paths in probe order and
    human-readable reasons for sources that were excluded without a probe.
    On POSIX (``windows`` unset means follow ``os.name``) both lists are empty.
    """
    environ = os.environ if environ is None else environ
    isfile = os.path.isfile if isfile is None else isfile
    if windows is None:
        windows = os.name == "nt"
    if not windows:
        return [], []

    def _absolute(path):
        return os.path.normpath(os.path.abspath(os.path.expandvars(path)))

    candidates, refusals = [], []
    pin = (environ.get("PADIEM_TEST_BASH") or "").strip()
    if pin:
        refusal = _windows_refusal(pin, environ)
        if refusal:
            refusals.append("PADIEM_TEST_BASH refused: " + refusal)
        else:
            candidates.append(_absolute(pin))

    seen_git_dirs = set()
    for entry in (environ.get("PATH") or "").split(os.pathsep):
        entry = entry.strip()
        if not entry:
            continue
        git_exe = _absolute(os.path.join(entry, "git.exe"))
        if not isfile(git_exe):
            continue
        refusal = _windows_refusal(git_exe, environ)
        if refusal:
            refusals.append("PATH git.exe refused: " + refusal)
            continue
        git_dir = os.path.dirname(git_exe)
        if git_dir.lower() in seen_git_dirs:
            continue
        seen_git_dirs.add(git_dir.lower())
        for relative in (os.path.join("..", "bin", "bash.exe"),
                         os.path.join("..", "usr", "bin", "bash.exe"),
                         os.path.join("..", "..", "bin", "bash.exe")):
            sibling = _absolute(os.path.join(git_dir, relative))
            if isfile(sibling) and sibling.lower() not in {
                    existing.lower() for existing in candidates}:
                candidates.append(sibling)
    return candidates, refusals


def locate_test_bash(*, environ=None, isfile=None, probe=None, which=None,
                     windows=None):
    """Return ``(bash, skip_reason)`` — exactly one of the two is non-empty.

    On POSIX this is ``shutil.which("bash")`` with no probe, matching what
    these tests did before the locator existed. On Windows the candidates
    from :func:`candidate_paths` are probed in order and the first working
    one wins; with none the reason names every refusal and probe failure.
    """
    which = shutil.which if which is None else which
    if windows is None:
        windows = os.name == "nt"
    if not windows:
        bash = which("bash")
        if not bash:
            return None, "no bash on PATH"
        return bash, ""
    probe = default_probe if probe is None else probe
    candidates, refusals = candidate_paths(environ=environ, isfile=isfile,
                                           windows=True)
    details = list(refusals)
    for candidate in candidates:
        ok, detail = probe(candidate)
        if ok:
            return candidate, ""
        details.append(candidate + ": " + detail)
    if not details:
        details.append("PATH offers no git.exe with an existing bash.exe sibling")
    return None, "no working bash for tests (" + "; ".join(details) + ")"
