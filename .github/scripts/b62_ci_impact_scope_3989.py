#!/usr/bin/env python3
"""Fail-closed B62 change-impact classification for CI lanes.

Exact static-only edits select static JavaScript parse and DOM/origin/privacy
audits, with separate path-scoped browser QA; unchanged Python/Worker/Core
regression and vendoring jobs are skipped. Test-only/B14-only edits retain Chat
pytest and Worker packaging but skip unchanged real Worker boots; source/runtime
changes retain their full applicable gates. Unknown event/API/changes => full.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import urllib.request

MAX_FILES = 100
FULL = "full"
CHAT_ONLY = "chat_only"
STATIC_ONLY = "static_only"
UI_MIXED = "ui_mixed"
TESTS_ONLY = "tests_only"
B14_ONLY = "b14_only"
B14_TESTS_ONLY = "b14_tests_only"

# #4459: source-invariant static UI and changed pytest modules. Run every
# changed test in the UI-mixed job; no deploy/auth/Worker/CI script ever qualifies.
UI_MIXED_MAX_FILES = 25
_UI_MIXED_STATIC = re.compile(
    r"apps/padiem-chat/static/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.(?:css|html|js)"
)
_UI_MIXED_TEST = re.compile(r"apps/padiem-chat/tests/test_[A-Za-z0-9_]+\.py")


def ui_mixed_test_modules(files: object) -> tuple[str, ...]:
    """Safe relative pytest arguments, only for strictly proven static+tests."""
    if not isinstance(files,list) or not 2 <= len(files) <= UI_MIXED_MAX_FILES:
        return ()
    static_count = 0
    modules: list[str] = []
    seen: set[str] = set()
    for row in files:
        if not isinstance(row,dict) or row.get("status") not in {"added","modified"}:
            return ()
        path = row.get("filename")
        if not isinstance(path,str) or path in seen or "\\" in path or ".." in Path(path).parts:
            return ()
        seen.add(path)
        if _UI_MIXED_STATIC.fullmatch(path):
            static_count += 1
        elif _UI_MIXED_TEST.fullmatch(path):
            modules.append(path.removeprefix("apps/padiem-chat/"))
        else:
            return ()
    return tuple(sorted(modules)) if static_count and modules else ()




def impact_scope(files: object) -> str:
    if not isinstance(files, list) or not 0 < len(files) <= MAX_FILES:
        return FULL
    paths = []
    for row in files:
        if not isinstance(row, dict) or row.get("status") not in {"added", "modified"}:
            return FULL
        path = row.get("filename")
        if not isinstance(path, str) or not (
            path.startswith("apps/padiem-chat/")
            or path.startswith("apps/korean-ai-platform/")
        ):
            return FULL
        # Do not accept malformed paths, explicit traversal or duplicates.
        if not path or "\\" in path or ".." in Path(path).parts or path in paths:
            return FULL
        paths.append(path)
    # B14 unit-test-only changes never alter either product's shipped sources,
    # pinned dependencies or runtime probes. B14's independent validate-b14-alpha
    # workflow runs the *complete* B14 test suite on every such PR and main push.
    # Keep the B14 pilot contract check here and the stable b62-test check context,
    # but omit unchanged B62 host/Worker jobs only for this exact narrow case.
    if all(re.fullmatch(r"apps/korean-ai-platform/tests/test_[^/]+\.py", p) for p in paths):
        return B14_TESTS_ONLY

    # B14 pilot source/tests are a separate deployed application: they cannot
    # change B62 Worker/Pyodide probe entrypoints, pinned vendor locks or
    # B62 Core source. Keep full B62 Chat integration + B14 tests + bundle,
    # but do not launch four source-identical B62 local Workerd runtimes.
    # Deliberately EXCLUDE B14 pyproject/locks/scripts and mixed changes.
    if all(
        re.fullmatch(r"apps/korean-ai-platform/app/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.(?:py|json)", p)
        or re.fullmatch(r"apps/korean-ai-platform/tests/test_[^/]+\.py", p)
        for p in paths
    ):
        return B14_ONLY
    if all(p.startswith("apps/padiem-chat/static/") for p in paths):
        return STATIC_ONLY
    if ui_mixed_test_modules(files):
        return UI_MIXED
    # #3989: strict test-module-only modifications cannot change the bundled
    # Worker code or its locked Pyodide dependencies. Run every B62 Chat test,
    # keep Worker bundling/lock checks, but omit four unchanged live runtimes.
    # Do NOT classify conftest/helpers, Worker probe entrypoints, or mixed changes.
    if all(re.fullmatch(r"apps/padiem-chat/tests/test_[^/]+\.py", p) for p in paths):
        return TESTS_ONLY
    # A B62-only dependency/Worker configuration change can alter the Core
    # execution environment without editing Core sources. Never fast-route it.
    source_roots = ("apps/padiem-chat/app/", "apps/padiem-chat/tests/")
    if all(
        p.startswith("apps/padiem-chat/static/")
        or (p.startswith(source_roots) and p.endswith(".py"))
        or p == "apps/padiem-chat/worker.py"
        for p in paths
    ):
        return CHAT_ONLY
    return FULL


def changed_files(event: dict, event_name: str, repository: str, token: str):
    if not token or not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
        return None
    if not isinstance(event, dict) or event.get("repository", {}).get("full_name") != repository:
        return None
    if event_name == "pull_request":
        pr = event.get("pull_request") or {}
        base = (pr.get("base") or {}).get("sha")
        head = (pr.get("head") or {}).get("sha")
    elif event_name == "push":
        base, head = event.get("before"), event.get("after")
    else:
        return None
    if not all(isinstance(s, str) and re.fullmatch("[0-9a-f]{40}", s) and set(s) != {"0"} for s in (base, head)):
        return None

    url = f"https://api.github.com/repos/{repository}/compare/{base}...{head}"
    request = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "padiem-b62-ci-impact/1.0",
    })
    with urllib.request.urlopen(request, timeout=15) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        return None
    status = result.get("status")
    if status not in {"ahead", "identical", "diverged"}:
        return None
    files = result.get("files")
    if not isinstance(files, list) or len(files) > MAX_FILES:
        return None
    # A PR branch can legitimately be behind main: GitHub compare returns
    # 'diverged' even when its merge-base..head diff touches only one CSS file.
    # Accept this PR-only case only with an exact changed-file count, so
    # truncated/uncertain API responses never turn into a reduced CI lane.
    if status == "diverged":
        if event_name != "pull_request":
            return None
        count = pr.get("changed_files")
        ahead = result.get("ahead_by")
        if (type(count) is not int or not 0 < count <= MAX_FILES
                or type(ahead) is not int or ahead < 1
                or len(files) != count):
            return None
    elif event_name == "pull_request":
        count = pr.get("changed_files")
        if type(count) is int and count != len(files):
            return None
    return files


def main() -> None:
    scope = FULL
    ui_tests: tuple[str, ...] = ()
    try:
        with Path(os.environ["GITHUB_EVENT_PATH"]).open(encoding="utf-8") as f:
            event = json.load(f)
        event_name = os.getenv("GITHUB_EVENT_NAME", "")
        files = changed_files(event, event_name,
                              os.getenv("GITHUB_REPOSITORY", ""),
                              os.getenv("GITHUB_TOKEN", ""))
        scope = impact_scope(files)
        if scope == UI_MIXED:
            # Require complete PR metadata, not just a possibly truncated
            # compare listing. Main pushes deliberately rerun full Chat suites.
            pr = event.get("pull_request") if isinstance(event,dict) else None
            count = pr.get("changed_files") if isinstance(pr,dict) else None
            if event_name != "pull_request" or type(count) is not int or count != len(files):
                scope = CHAT_ONLY
        ui_tests = ui_mixed_test_modules(files) if scope == UI_MIXED else ()
    except (OSError, ValueError, KeyError, TypeError, TimeoutError):
        scope = FULL
    except Exception:
        # Network/API ambiguity must never silently shrink a CI test lane.
        scope = FULL
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as out:
        out.write(f"scope={scope}\n")
        out.write(f"ui_tests={' '.join(ui_tests)}\n")
    print(f"B62_CI_IMPACT_SCOPE={scope}")


if __name__ == "__main__":
    main()
