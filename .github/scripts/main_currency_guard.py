"""#5895: let a release proceed while its target is still current for its app.

Every deploy gate used to demand ``target_sha == origin/main`` the moment it
started. A pull request merged in the seconds between dispatch and that check
broke the run even though the target was a direct ancestor of main and nothing
in the app being released had moved. This guard replaces the equality test with
the rule the equality test was standing in for:

  * the target is an ancestor of main, or is main itself, and
  * the paths this release actually ships did not change between the target
    and main.

A changed app path still fails, because that is the case where the release
would drop code main already carries. Anything the guard cannot establish - no
token, an unanswered API, a git error - is a failure, never a pass.

The verdict line names the basis, both short SHAs and whether the app path
moved, so a run log explains itself:

    MAIN_CURRENCY=PASS basis=ancestor target=0db3b0dd main=73b05504 app_path=apps/padiem-chat path_changed=NO
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

API_TIMEOUT_SECONDS = 20
USER_AGENT = "padiem-main-currency-guard/1.0"
FAIL_MARKER = "MAIN_CURRENCY=FAIL"
PASS_BASES = frozenset({"identical", "ancestor"})


def classify(target: str, main: str, *, merge_base: str | None) -> str:
    """What the repository API says the target's place on main is."""
    if target == main:
        return "identical"
    if merge_base == target:
        return "ancestor"
    return "not_on_main"


def compare_merge_base(target: str, main: str, *, repo: str, token: str, api: str) -> str:
    """The merge base main and the target share, read once from the API.

    Only the identity of the merge base is needed, so the response body is not
    walked for files and a single request answers the question.
    """
    if not repo or not token:
        raise RuntimeError("no repository or token to ask about main history")
    request = urllib.request.Request(
        f"{api}/repos/{repo}/compare/{main}...{target}?per_page=1",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=API_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise RuntimeError(f"main history is unreadable: {type(exc).__name__}") from exc
    # The compare resource names the shared ancestor ``merge_base_commit``; its
    # ``status`` word is left unused because the sha answers the question exactly.
    anchor = payload.get("merge_base_commit") if isinstance(payload, dict) else None
    base = anchor.get("sha") if isinstance(anchor, dict) else None
    if not isinstance(base, str) or not base:
        raise RuntimeError("the compare response carried no merge base")
    return base


def app_paths_changed(target: str, main: str, paths: list[str], *, run=subprocess.run) -> bool:
    """True when the shipped paths differ between the target and main."""
    result = run(
        ["git", "diff", "--name-only", target, main, "--", *paths],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git diff between target and main failed ({result.returncode})")
    return bool(result.stdout.strip())


def decide(basis: str, path_changed: bool) -> tuple[str, str]:
    """The whole rule in one place: current for this app, or stop."""
    if basis not in PASS_BASES:
        return "FAIL", f"target_not_current_on_main:{basis}"
    if path_changed:
        return "FAIL", "app_path_changed_since_target"
    return "PASS", basis


def evaluate(target: str, main: str, paths: list[str], *, repo: str, token: str, api: str,
             transport=compare_merge_base,
             diff=app_paths_changed) -> int:
    try:
        basis = ("identical" if target == main
                 else classify(target, main, merge_base=transport(target, main, repo=repo, token=token, api=api)))
    except RuntimeError as exc:
        print(f"{FAIL_MARKER} reason=main_history_unreadable", file=sys.stderr)
        print(f"MAIN_CURRENCY_REASON={exc}", file=sys.stderr)
        return 1
    if basis in PASS_BASES:
        try:
            changed = diff(target, main, paths)
        except RuntimeError as exc:
            print(f"{FAIL_MARKER} reason=app_path_read_failed", file=sys.stderr)
            print(f"MAIN_CURRENCY_REASON={exc}", file=sys.stderr)
            return 1
    else:
        changed = False
    verdict, reason = decide(basis, changed)
    print(
        f"MAIN_CURRENCY={verdict} basis={reason} target={target[:8]} main={main[:8]}"
        f" app_path={','.join(paths)} path_changed={'YES' if changed else 'NO'}"
    )
    if verdict == "FAIL":
        print("MAIN_CURRENCY_STOP=1", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="the dispatched target_sha")
    parser.add_argument("--main-ref", default="origin/main", help="the ref naming current main")
    parser.add_argument("--path", action="append", required=True, dest="paths",
                        help="a path this release ships; repeatable")
    args = parser.parse_args(argv)
    target = args.target.strip()
    if not target:
        print(f"{FAIL_MARKER} reason=target_missing", file=sys.stderr)
        return 1
    # Both sides are resolved to full commit ids before anything is compared: a
    # dispatch that typed a short SHA must not read as "not on main".
    resolved_target = subprocess.run(["git", "rev-parse", "--verify", target + "^{commit}"],
                                     capture_output=True, text=True, check=False)
    if resolved_target.returncode != 0 or not resolved_target.stdout.strip():
        print(f"{FAIL_MARKER} reason=target_unreadable", file=sys.stderr)
        return 1
    resolved = subprocess.run(["git", "rev-parse", args.main_ref],
                              capture_output=True, text=True, check=False)
    if resolved.returncode != 0 or not resolved.stdout.strip():
        print(f"{FAIL_MARKER} reason=main_ref_unreadable", file=sys.stderr)
        return 1
    return evaluate(
        resolved_target.stdout.strip(), resolved.stdout.strip(), args.paths,
        repo=os.environ.get("GITHUB_REPOSITORY", ""),
        token=os.environ.get("GITHUB_TOKEN", ""),
        api=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
    )


if __name__ == "__main__":
    raise SystemExit(main())
