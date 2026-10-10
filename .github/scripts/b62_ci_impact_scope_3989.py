#!/usr/bin/env python3
"""Fail-closed impact classification for B62 CI expensive *unchanged* dependencies.

This is not a test-coverage deletion: full B62 pytest, locks, packaging and
product security checks always run. Only source-invariant shared-Core pytest is
skipped on B62-only file edits; Worker-native probes are additionally skipped
when only static assets change. Unknown event/API/changes => all tests.
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
TESTS_ONLY = "tests_only"


def impact_scope(files: object) -> str:
    if not isinstance(files, list) or not 0 < len(files) <= MAX_FILES:
        return FULL
    paths = []
    for row in files:
        if not isinstance(row, dict) or row.get("status") not in {"added", "modified"}:
            return FULL
        path = row.get("filename")
        if not isinstance(path, str) or not path.startswith("apps/padiem-chat/"):
            return FULL
        # Do not accept malformed paths, explicit traversal or duplicates.
        if not path or "\\" in path or ".." in Path(path).parts or path in paths:
            return FULL
        paths.append(path)
    if all(p.startswith("apps/padiem-chat/static/") for p in paths):
        return STATIC_ONLY
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
    if not isinstance(result, dict) or result.get("status") not in {"ahead", "identical"}:
        return None
    files = result.get("files")
    if not isinstance(files, list) or len(files) > MAX_FILES:
        return None
    return files


def main() -> None:
    scope = FULL
    try:
        with Path(os.environ["GITHUB_EVENT_PATH"]).open(encoding="utf-8") as f:
            event = json.load(f)
        files = changed_files(event, os.getenv("GITHUB_EVENT_NAME", ""),
                              os.getenv("GITHUB_REPOSITORY", ""),
                              os.getenv("GITHUB_TOKEN", ""))
        scope = impact_scope(files)
    except (OSError, ValueError, KeyError, TypeError, TimeoutError):
        scope = FULL
    except Exception:
        # Network/API ambiguity must never silently shrink a CI test lane.
        scope = FULL
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as out:
        out.write(f"scope={scope}\n")
    print(f"B62_CI_IMPACT_SCOPE={scope}")


if __name__ == "__main__":
    main()
