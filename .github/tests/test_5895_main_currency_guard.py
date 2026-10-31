"""#5895: the main-currency rule, in the three cases that decide a deploy.

The gates used to compare the target with `origin/main` character for character
the moment they started, so a pull request merged during those seconds broke a
run that was still current for the app it ships. These three cases are the
replacement rule: an ancestor whose app path is unchanged goes, an ancestor
whose app path moved stops, and anything that is not on main stops.

Nothing here touches the network: the repository read and the path read are both
injected, so the verdict comes from the same function the gates call.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/main_currency_guard.py"

spec = importlib.util.spec_from_file_location("main_currency_guard", SCRIPT)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

TARGET = "a" * 40
MAIN = "b" * 40
ELSEWHERE = "c" * 40
SHORT_MAIN = "0ed486b7"
APP_PATH = "apps/padiem-chat"


def _verdict(capsys, *, merge_base: str, path_changed: bool, target: str = TARGET,
             main: str = MAIN) -> tuple[int, str, int]:
    diff_reads = {"count": 0}

    def transport(_target, _main, *, repo, token, api):
        return merge_base

    def diff(_target, _main, _paths):
        diff_reads["count"] += 1
        return path_changed

    rc = guard.evaluate(target, main, [APP_PATH], repo="owner/repo", token="synthetic-token",
                        api="https://api.example.invalid", transport=transport, diff=diff)
    return rc, capsys.readouterr().out, diff_reads["count"]


def test_an_ancestor_with_an_unchanged_app_path_passes(capsys) -> None:
    rc, out, diff_reads = _verdict(capsys, merge_base=TARGET, path_changed=False)
    assert rc == 0
    assert "MAIN_CURRENCY=PASS basis=ancestor" in out
    assert f"app_path={APP_PATH} path_changed=NO" in out
    assert diff_reads == 1
    # The target being main itself is the trivial case of current, and it needs
    # no history read at all.
    rc, out, _ = _verdict(capsys, merge_base=MAIN, path_changed=False, target=MAIN)
    assert rc == 0
    assert "MAIN_CURRENCY=PASS basis=identical" in out


def test_an_ancestor_whose_app_path_moved_since_stops_the_gate(capsys) -> None:
    rc, out, _ = _verdict(capsys, merge_base=TARGET, path_changed=True)
    assert rc == 1
    assert "MAIN_CURRENCY=FAIL basis=app_path_changed_since_target" in out
    assert "path_changed=YES" in out


def test_a_change_under_packages_alone_stops_the_gate(capsys) -> None:
    # Each of these bundles ships packages/ beside its app directory, so a merge
    # that moved only packages changed the thing being released.
    def diff(_target, _main, paths):
        return "packages" in paths

    rc = guard.evaluate(TARGET, MAIN, [APP_PATH, "packages"], repo="owner/repo",
                        token="synthetic-token", api="https://api.example.invalid",
                        transport=lambda *_a, **_k: TARGET, diff=diff)
    assert rc == 1
    out = capsys.readouterr().out
    assert "MAIN_CURRENCY=FAIL basis=app_path_changed_since_target" in out
    assert f"app_path={APP_PATH},packages path_changed=YES" in out


def test_a_target_that_is_not_on_main_stops_without_reading_paths(capsys) -> None:
    rc, out, diff_reads = _verdict(capsys, merge_base=ELSEWHERE, path_changed=False)
    assert rc == 1
    assert "MAIN_CURRENCY=FAIL basis=target_not_current_on_main:not_on_main" in out
    # Not on main is already a stop; the app path is never consulted, so a
    # branch head cannot talk its way into a deploy by claiming a clean diff.
    assert diff_reads == 0
    # Only full commit ids are printed: a short SHA on either side cannot read as
    # "main moved past me", which is why main() resolves both before comparing.
    assert f"target={SHORT_MAIN}" not in out
