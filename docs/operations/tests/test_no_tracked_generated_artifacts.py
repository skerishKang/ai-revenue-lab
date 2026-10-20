"""Fail closed when regenerable local artifacts re-enter Git tracking.

Issue #5231 removed the tracked copies of browser-QA output, local agent
memory, one-off operational scratch and local agent-tool state. These are
re-created by the scripts and tools that own them, so a tracked copy is never
the canonical evidence and must not come back.

The guard proves two separate things and keeps them separate:

1. the cleaned paths are not tracked any more, and the ignore rules still
   cover them, so a regenerated file does not reappear in ``git status``;
2. the evidence and canonical source that replaced those copies are still
   present, so the cleanup cannot be mistaken for data loss.

No network, Provider, credential or Production access.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

# Directories whose tracked content is regenerable output, not source.
CLEANED_PREFIXES = (
    ".tmp/",
    ".workbuddy-ai/",
    ".freebuff/",
    "_synccheck/",
)

# The ignore rule that must exist in the repository `.gitignore` for each
# cleaned directory. A machine-local `$GIT_DIR/info/exclude` rule does not
# count: it is not part of the repository and is absent on a fresh clone.
REQUIRED_IGNORE_RULES = (
    ".tmp/",
    ".workbuddy-ai/",
    ".freebuff/",
    "_synccheck/",
    "padiem-reports/2026-10-06/b66-pdf-preview-parity/",
    "padiem-reports/b66-shell-cgi-v2/",
)

# The one report that stays tracked because it is registered public evidence.
KEPT_EVIDENCE = "padiem-reports/2026-09-25/CLAW3/2825-hwpx-image-insertion-adoption.md"

# Canonical replacements for every copy removed from the cleaned directories.
# If one of these disappears, the cleanup removed real source or real
# evidence instead of a duplicate.
CANONICAL_REPLACEMENTS = (
    ".github/workflows/b62-claw-d1-migration-008-gate.yml",
    ".github/workflows/b62-claw-d1-migration-040-gate.yml",
    ".github/workflows/b62-current-main-production-deploy-trigger.yml",
    ".github/workflows/b62-production-code-deploy-gate.yml",
    ".github/workflows/b54-claw-502-retained-telemetry-readonly.yml",
    ".github/tests/test_b62_d1_migration_040_gate.py",
    "apps/padiem-chat/app/claw_web_xlsx_p01_owner_decision.py",
    ".github/scripts/b62_browser_visual_qa.py",
    KEPT_EVIDENCE,
)


def _tracked_paths() -> list[str]:
    raw = subprocess.check_output(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        text=False,
    ).decode("utf-8")
    return [path for path in raw.split("\0") if path]


def _ignore_source(relative: str) -> str | None:
    """Return the file that provides the ignore rule for `relative`.

    `git check-ignore -v` prints `<source>:<linenum>:<pattern>\t<path>`.
    A repository rule is reported with the repository-relative `.gitignore`
    path; a machine-local `$GIT_DIR/info/exclude` entry is reported with an
    absolute path. Only the repository rule travels with a clone.
    """
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-v", relative],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    line = result.stdout.splitlines()[0]
    return line.split(":", 1)[0]


def test_generated_artifacts_are_not_tracked() -> None:
    offenders = sorted(
        path for path in _tracked_paths() if path.startswith(CLEANED_PREFIXES)
    )
    assert offenders == [], (
        "Regenerable local artifacts must never be tracked. "
        f"Remove these files from Git: {offenders}"
    )


def test_cleaned_directories_stay_ignored() -> None:
    for prefix in CLEANED_PREFIXES:
        probe = f"{prefix}re-entry-probe.txt"
        source = _ignore_source(probe)
        assert source is not None, (
            f"{prefix} is not ignored at all, so regenerated output would "
            "re-enter Git tracking"
        )
        assert source.replace("\\", "/").endswith(".gitignore"), (
            f"{prefix} is only ignored by a machine-local exclude ({source}), "
            "not by the repository .gitignore; a fresh clone would re-track it"
        )


def test_repository_gitignore_declares_every_required_rule() -> None:
    rules = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    missing = [rule for rule in REQUIRED_IGNORE_RULES if rule not in rules]
    assert missing == [], f"missing .gitignore rules: {missing}"


def test_kept_evidence_and_canonical_source_are_present() -> None:
    tracked = set(_tracked_paths())
    assert KEPT_EVIDENCE in tracked, (
        "Registered public evidence must stay tracked: " + KEPT_EVIDENCE
    )
    for relative in CANONICAL_REPLACEMENTS:
        assert (ROOT / relative).is_file(), f"missing canonical file: {relative}"
    for relative in CANONICAL_REPLACEMENTS:
        if relative == KEPT_EVIDENCE:
            continue
        assert relative in tracked, f"canonical file is no longer tracked: {relative}"


def test_root_readme_does_not_describe_the_code_repository_as_private() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "private product and research repository" not in readme, (
        "The repository visibility is public; the root README must not describe "
        "the code repository as private"
    )
    assert "public development and engineering repository" in readme, (
        "The root README must state that the code repository is public"
    )
    assert "AGENTS.md" in readme, (
        "The root README must keep the pointer to the non-public Governance "
        "decision order"
    )
