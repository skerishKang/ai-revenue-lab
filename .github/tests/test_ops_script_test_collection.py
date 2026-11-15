"""The ops script test collection must pick up new test files by itself.

The dedicated workflow (Ops script tests) collects scripts/ops/tests as a
whole directory, so a new test file in that directory joins CI without a
workflow edit. This contract pins the structural properties that guarantee
that behavior:

- the workflow triggers on pull requests that change scripts/ops/** and on
  edits to the workflow itself,
- the pytest invocation targets the directory, never an enumerated file list
  (a per-file reference is allowed only as an --ignore= exclusion),
- every --ignore= exclusion is pinned here with the tracking issue that
  records why the file is excluded, so exclusions cannot silently grow,
- the exclusion set stays consistent with the files that actually exist.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ops-script-tests.yml"
OPS_TESTS_DIR = REPO_ROOT / "scripts" / "ops" / "tests"

# Files excluded from the directory collection, each with the tracking issue
# that records the reason (code defect, environment dependency, ...). Keep in
# sync with the workflow's --ignore= flags; the assertions below enforce it.
EXCLUDED_WITH_ISSUES: dict[str, str] = {}

TEST_FILE_RE = re.compile(r"test_[A-Za-z0-9_]+\.py")


def _workflow_text() -> str:
    assert WORKFLOW.exists(), f"collection workflow missing: {WORKFLOW}"
    return WORKFLOW.read_text(encoding="utf-8")


def test_collection_workflow_triggers_on_ops_script_changes() -> None:
    text = _workflow_text()

    # The pull_request trigger must cover the whole ops script tree so a new
    # test file (or the script it exercises) runs the collection.
    trigger_block = re.search(
        r"pull_request:\s*\n\s*paths:\s*\n((?:\s*-\s*\"[^\"]+\"\s*\n)+)", text
    )
    assert trigger_block is not None, "workflow has no pull_request paths block"
    assert '"scripts/ops/**"' in trigger_block.group(1), (
        "pull_request trigger must include the whole scripts/ops/** tree"
    )
    assert f'"{WORKFLOW.relative_to(REPO_ROOT).as_posix()}"' in trigger_block.group(1), (
        "pull_request trigger must include the workflow file itself"
    )


def test_collection_runs_the_directory_not_an_enumerated_file_list() -> None:
    text = _workflow_text()

    pytest_lines = [line for line in text.splitlines() if "python -m pytest" in line]
    assert pytest_lines, "workflow must run pytest"

    collection_lines = [
        line for line in pytest_lines if "scripts/ops/tests" in line
    ]
    assert collection_lines, "workflow must run the scripts/ops/tests suite"
    for line in collection_lines:
        # The directory is the collection root: a directory path that stops
        # there, never a per-file positional argument.
        assert re.search(r"pytest.*\s-q scripts/ops/tests(?![/\w.-])", line), (
            f"collection must pass the directory, got: {line.strip()}"
        )

    # Any per-file path may appear only behind an --ignore= flag. A bare file
    # reference would turn collection into an enumeration and silently drop
    # files added later.
    for match in re.finditer(r"(?<![\w./-])scripts/ops/tests/test_[A-Za-z0-9_.]+", text):
        prefix = text[max(0, match.start() - len("--ignore=")) : match.start()]
        assert prefix.endswith("--ignore="), (
            f"per-file reference outside --ignore= would exclude new files: {match.group(0)}"
        )


def test_ignore_flags_match_the_exclusion_list_with_issue_numbers() -> None:
    text = _workflow_text()

    ignored = set(re.findall(r"--ignore=scripts/ops/tests/(test_[A-Za-z0-9_]+\.py)", text))
    assert ignored == set(EXCLUDED_WITH_ISSUES), (
        "workflow --ignore= flags and EXCLUDED_WITH_ISSUES must list exactly "
        f"the same files; workflow={sorted(ignored)} contract={sorted(EXCLUDED_WITH_ISSUES)}"
    )

    for name, issue in EXCLUDED_WITH_ISSUES.items():
        assert TEST_FILE_RE.fullmatch(name), f"exclusion entry is not a test file name: {name}"
        assert re.search(r"#\d+", issue), (
            f"exclusion of {name} must record its tracking issue number, got: {issue!r}"
        )
        assert (OPS_TESTS_DIR / name).exists(), (
            f"excluded file no longer exists, drop the entry: {name}"
        )


def test_every_current_test_file_is_covered_by_the_directory_collection() -> None:
    text = _workflow_text()
    files = {path.name for path in OPS_TESTS_DIR.glob("test_*.py")}
    assert files, "scripts/ops/tests must contain test files"

    ignored = set(re.findall(r"--ignore=scripts/ops/tests/(test_[A-Za-z0-9_]+\.py)", text))
    covered = files - ignored
    assert covered == files - set(EXCLUDED_WITH_ISSUES), (
        "coverage bookkeeping disagrees with the contract exclusion list"
    )
    assert covered, "every test file is excluded; the collection would run nothing"

    # The per-file contract workflows that keep their own slices must still
    # exist and keep their check names, so the required checks stay stable.
    for workflow_name, job_name in (
        ("com2-backup-contract-tests.yml", "COM2 backup tests (pytest)"),
        ("pc-session-measure-contract-tests.yml", "PC session measure tests (pytest)"),
    ):
        existing = REPO_ROOT / ".github" / "workflows" / workflow_name
        assert existing.exists(), f"required per-file workflow missing: {workflow_name}"
        assert job_name in existing.read_text(encoding="utf-8"), (
            f"check name must stay for {workflow_name}: {job_name}"
        )
