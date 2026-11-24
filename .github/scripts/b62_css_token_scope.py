#!/usr/bin/env python3
"""Fail-closed proof for a CSS + colour-token test + evidence PR.

Both the B62 browser QA planner and the B62 Chat CI impact classifier use this
predicate, so the two lanes cannot disagree about what counts as a proven
colour/token-only change. A window of source-invariant stylesheets, token
contract tests and padiem-reports evidence cannot change runtime Python,
Worker or auth behaviour. Anything outside that window keeps the full lanes.
"""

from __future__ import annotations

from pathlib import Path
import re

CSS_RE = re.compile(
    r"apps/padiem-chat/static/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.css"
)
EVIDENCE_RE = re.compile(
    r"padiem-reports/(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.[A-Za-z0-9]+"
)
# Owner-approved name patterns for the colour/token contract tests. The
# *_support helpers are read-only sheet parsers used by those tests.
TOKEN_TEST_RES = (
    re.compile(r"apps/padiem-chat/tests/test_[A-Za-z0-9_]+_tokens_[A-Za-z0-9_]+\.py"),
    re.compile(r"apps/padiem-chat/tests/test_[A-Za-z0-9_]+_7187\.py"),
    re.compile(r"apps/padiem-chat/tests/test_[A-Za-z0-9_]+_7811\.py"),
    re.compile(r"apps/padiem-chat/tests/_support/calendar_palette\.py"),
    re.compile(r"apps/padiem-chat/tests/_support/theme_sheets\.py"),
)
# Stylesheets with their own proven surface isolation keep their pinned lanes.
EXCLUDED_CSS = frozenset({
    "apps/padiem-chat/static/b66-quote-runtime.css",
    "apps/padiem-chat/static/claw-manual-intake.css",
    "apps/padiem-chat/static/claw-quote-compare.css",
})

MAX_CSS_FILES = 10
MAX_TOKEN_TEST_FILES = 24
MAX_EVIDENCE_FILES = 64
MAX_CHANGED_FILES = 100

# A token test or support helper that a browser QA script imports or executes
# is runtime coverage, not a passive contract. Verified by grep in
# .github/tests/test_b62_css_token_scope.py; keep this set in sync with that
# scan. Empty at introduction: no browser QA script references these files.
BROWSER_QA_REFERENCED_FILES = frozenset()


def is_token_test_file(path: str) -> bool:
    """True for an allow-listed colour/token test or read-only helper."""
    return any(pattern.fullmatch(path) for pattern in TOKEN_TEST_RES)


def is_evidence_file(path: str) -> bool:
    return bool(EVIDENCE_RE.fullmatch(path))


def _well_formed(path: str) -> bool:
    return bool(path) and "\\" not in path and ".." not in Path(path).parts


def css_token_proof(files: object):
    """Return (paths, statuses, count) only for an exact, well-formed listing."""
    if not isinstance(files, list) or not 0 < len(files) <= MAX_CHANGED_FILES:
        return None
    paths: set[str] = set()
    statuses: dict[str, str] = {}
    for row in files:
        if not isinstance(row, dict):
            return None
        status = row.get("status")
        path = row.get("filename")
        if status not in {"added", "modified"} or not isinstance(path, str):
            return None
        if not _well_formed(path) or path in paths:
            return None
        paths.add(path)
        statuses[path] = status
    if len(statuses) != len(files):
        return None
    return paths, statuses, len(files)


def is_css_token_evidence_change(
    changed_paths: set[str] | None,
    statuses: dict[str, str] | None,
    *,
    expected_files: int | None = None,
) -> bool:
    """Prove CSS + allow-listed token tests + reports evidence, nothing else.

    Missing statuses, a mismatched or unknown changed-file count, a truncated
    API response, added/modified proof failures and any stray JS/Python/app
    source path all fail closed to the full lanes.
    """
    if not changed_paths or statuses is None:
        return False
    if type(expected_files) is not int or expected_files != len(changed_paths):
        return False
    if set(statuses) != set(changed_paths):
        return False
    if not 0 < len(changed_paths) <= MAX_CHANGED_FILES:
        return False
    for path in changed_paths:
        if statuses.get(path) not in {"added", "modified"} or not _well_formed(path):
            return False

    css = {p for p in changed_paths if CSS_RE.fullmatch(p)}
    if not css or css & EXCLUDED_CSS:
        return False
    if len(css) > MAX_CSS_FILES:
        return False

    tests = {p for p in changed_paths if is_token_test_file(p)}
    if any(Path(p).name in BROWSER_QA_REFERENCED_FILES for p in tests):
        return False
    if len(tests) > MAX_TOKEN_TEST_FILES:
        return False

    evidence = {p for p in changed_paths if is_evidence_file(p)}
    if len(evidence) > MAX_EVIDENCE_FILES:
        return False

    # A CSS-only edit keeps its existing static_only contract; this reduced
    # lane exists for the colour/token tests and their reports evidence.
    if not tests and not evidence:
        return False

    return css | tests | evidence == changed_paths


def token_test_modules(changed_paths: set[str] | None) -> tuple[str, ...]:
    """Runnable pytest arguments for changed token tests (helpers excluded)."""
    if not changed_paths:
        return ()
    return tuple(sorted(
        p.removeprefix("apps/padiem-chat/")
        for p in changed_paths
        if is_token_test_file(p) and p.startswith("apps/padiem-chat/tests/test_")
    ))
