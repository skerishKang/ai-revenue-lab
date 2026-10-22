"""Daily read-only audit of the repository instruction index.

Reports, and only then comments on the maintenance issue, when the navigation
index actually needs work. It never writes to the repository, never opens a PR
and never rewrites a document.

Exit codes: 0 = nothing needs action, 1 = findings were reported, 2 = the audit
itself could not run.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# The entry point must stay below the size at which agent runtimes stop loading
# it in full. TARGET is the owner's stated goal, not a blocking limit.
HARD_LIMIT_BYTES = 32_768
TARGET_BYTES = 12_288

HUBS = (
    "docs/common/README.md",
    "docs/lifecycle/README.md",
    "docs/businesses/README.md",
    "docs/models/README.md",
    "docs/history/README.md",
    "docs/evidence/README.md",
)

INDEXES = (
    "README.md",
    "AGENTS.md",
    "docs/README.md",
    "docs/operations/README.md",
    "docs/governance/DOCUMENTATION_AUTHORITY_MODEL.md",
) + HUBS

MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
INLINE_CODE_PATH = re.compile(r"`((?:docs|\.github|apps)/[A-Za-z0-9_.\-/]+\.md)`")
BULLET = re.compile(r"^- (.+)$")

FAIL = "FAIL"
WARN = "WARN"
INFO = "INFO"


def read(relative: str) -> str:
    return (REPO / relative).read_text(encoding="utf-8", errors="replace")


def record(findings: list, level: str, message: str) -> None:
    findings.append((level, message))


def check_entry_point_size(findings, texts) -> None:
    size = len(texts["AGENTS.md"].encode("utf-8"))
    if size > HARD_LIMIT_BYTES:
        record(
            findings,
            FAIL,
            f"AGENTS.md is {size} bytes, above the {HARD_LIMIT_BYTES} byte limit at which "
            "agent runtimes stop loading the entry point in full.",
        )
    elif size > TARGET_BYTES:
        record(
            findings,
            INFO,
            f"AGENTS.md is {size} bytes, above the {TARGET_BYTES} byte navigation goal. "
            "Non-negotiable safety and authority rules are kept inline on purpose.",
        )
    else:
        record(findings, INFO, f"AGENTS.md is {size} bytes, within the navigation goal.")


def check_links(findings, texts) -> None:
    broken = []
    for name, text in texts.items():
        base = REPO / name
        # A Markdown link is relative to its own file. A path written inside
        # backticks is normally a repository-root path, but some indexes write
        # it relative to the file, so either reading is accepted.
        for href in MARKDOWN_LINK.findall(text):
            check_destination(broken, name, href, (base.parent,))
        for href in INLINE_CODE_PATH.findall(text):
            check_destination(broken, name, href, (REPO, base.parent))
    if broken:
        record(
            findings,
            FAIL,
            "Index links point at files that are not in the repository:\n"
            + "\n".join(f"  - `{item}`" for item in sorted(set(broken))),
        )
    else:
        record(findings, INFO, "Every index link and referenced document path resolves.")


def check_destination(broken, name, href, origins) -> None:
    if href.startswith(("http://", "https://", "mailto:", "#")):
        return
    candidates = [(origin / href.split("#", 1)[0]).resolve() for origin in origins]
    if any(candidate.is_file() for candidate in candidates):
        return
    if not any(_inside_repo(candidate) for candidate in candidates):
        broken.append(f"{name} -> {href} (outside repository)")
        return
    broken.append(f"{name} -> {href}")


def _inside_repo(path) -> bool:
    try:
        path.relative_to(REPO.resolve())
    except ValueError:
        return False
    return True


def check_hubs(findings, texts) -> None:
    missing = []
    for name in HUBS:
        text = texts.get(name)
        if text is None:
            missing.append(f"{name} (file absent)")
            continue
        if "SCOPE = NAVIGATION_ONLY" not in text:
            missing.append(f"{name} (missing SCOPE = NAVIGATION_ONLY)")
        if "DOC_STATUS = CANONICAL" not in text:
            missing.append(f"{name} (missing DOC_STATUS = CANONICAL)")
    if missing:
        record(
            findings,
            FAIL,
            "Navigation hubs are missing or lost their navigation-only markers:\n"
            + "\n".join(f"  - {item}" for item in missing),
        )
    else:
        record(findings, INFO, f"All {len(HUBS)} navigation hubs are present and marked.")


def check_entry_point_points_at_canonical_policies(findings, texts) -> None:
    """The entry point must not silently drop a whole area of the index."""
    entry = texts["AGENTS.md"]
    for name in (
        "AI_DEVELOPMENT_OPERATING_POLICY.md",
        "TEST_SCOPE_AND_DELIVERY_POLICY.md",
        "TECHNOLOGY_ADOPTION_POLICY.md",
        "MODEL_CHANGE_OWNER_APPROVAL_POLICY.md",
        "GITHUB_REPORT_HANDOFF_POLICY.md",
        "MULTI_MACHINE_LOCAL_WORKTREE_POLICY.md",
        "docs/models/README.md",
    ):
        if name not in entry:
            record(
                findings,
                FAIL,
                f"AGENTS.md no longer points at the canonical document `{name}`.",
            )


def duplicated_entry_lines(texts) -> list:
    """Long entry-point bullets that also appear verbatim in a canonical document."""
    other_bullets = {}
    for name, text in texts.items():
        if name == "AGENTS.md":
            continue
        for match in BULLET.finditer(text):
            line = match.group(1).strip()
            if len(line) >= 240:
                other_bullets.setdefault(line, name)
    duplicates = []
    for match in BULLET.finditer(texts["AGENTS.md"]):
        line = match.group(1).strip()
        source = other_bullets.get(line)
        if source:
            duplicates.append(f"{line[:70]}...  (also in `{source}`)")
    return sorted(set(duplicates))


def check_subtree_instructions(findings) -> None:
    subtree = sorted(
        str(path.relative_to(REPO))
        for path in REPO.rglob("AGENTS.md")
        if path != REPO / "AGENTS.md" and "node_modules" not in path.parts
    )
    if subtree:
        record(
            findings,
            INFO,
            "Subtree instruction files present: " + ", ".join(f"`{name}`" for name in subtree),
        )
    else:
        record(
            findings,
            INFO,
            "No subtree AGENTS.md exists; the root entry point is the only instruction file.",
        )


def post_to_issue(body: str, issue: str) -> None:
    command = ["gh", "issue", "comment", issue, "--body", body]
    repository = os.environ.get("GH_REPO")
    if repository:
        command += ["--repo", repository]
    subprocess.run(command, check=True)


def main(argv: list) -> int:
    no_post = "--no-post" in argv
    issue_number = os.environ.get("DOCUMENTATION_AUDIT_ISSUE", "5002")

    missing_indexes = [name for name in INDEXES if not (REPO / name).is_file()]
    if missing_indexes:
        print("AUDIT=ERROR")
        print("Missing index files: " + ", ".join(missing_indexes))
        return 2

    texts = {name: read(name) for name in INDEXES}
    findings = []

    check_entry_point_size(findings, texts)
    check_links(findings, texts)
    check_hubs(findings, texts)
    check_entry_point_points_at_canonical_policies(findings, texts)
    check_subtree_instructions(findings)

    duplicates = duplicated_entry_lines(texts)
    if duplicates:
        record(
            findings,
            WARN,
            "The entry point repeats canonical bullet text. Confirm each one is still a "
            "rule every agent needs inline, otherwise replace it with a pointer:\n"
            + "\n".join(f"  - {item}" for item in duplicates),
        )

    actions = [message for level, message in findings if level in (FAIL, WARN)]
    print(f"AGENTS_BYTES={len(texts['AGENTS.md'].encode('utf-8'))}")
    print(f"AUDIT={'NEEDS_ACTION' if actions else 'OK'}")
    for level, message in findings:
        print(f"[{level}] {message}")

    if not actions:
        return 0

    if not no_post:
        body = (
            "## Daily documentation-navigation audit\n\n"
            f"Run: `{os.environ.get('GITHUB_SHA', 'local')}` on "
            f"`{os.environ.get('GITHUB_REF_NAME', 'local')}`. Read-only check; no branch, "
            "pull request or file was created or modified.\n\n"
            + "\n\n".join(actions)
            + "\n\nNext action: correct the index through the normal branch/pull-request "
            "path, or record why the finding is expected.\n"
        )
        post_to_issue(body, issue_number)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
