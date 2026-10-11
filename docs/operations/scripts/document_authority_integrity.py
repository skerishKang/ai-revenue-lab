"""Fail-closed, bounded navigation/authority check for current documentation.

No network, provider, deployment, or GitHub mutation. This guard deliberately
checks live reader entrypoints, NOT immutable issue snapshots or full prose history.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[3]
HUBS = (
    "docs/common/README.md",
    "docs/lifecycle/README.md",
    "docs/businesses/README.md",
    "docs/models/README.md",
    "docs/history/README.md",
    "docs/evidence/README.md",
)
CONSUMERS = (
    "apps/korean-ai-code-agent/README.md",
    "docs/products/padiem-sidecar/README.md",
    "docs/products/b66/README.md",
)
SCOPED_DOCS = ("docs/README.md",) + HUBS + CONSUMERS
OWNER_POLICY = "docs/operations/MODEL_CHANGE_OWNER_APPROVAL_POLICY.md"
OPS_CI_WORKFLOW = ".github/workflows/operations-policy-guard.yml"
HISTORY_TEST = "docs/operations/tests/test_lifecycle_evidence_taxonomy.py"

# Match genuine catalog-style identifiers and copied authority declarations.
# General prose saying "Gemini" or "owner approval" is not a duplicate model roster.
MODEL_ID = re.compile(r"\b(?:gemini|gemma|nemotron)-[0-9][a-z0-9_.-]*\b", re.I)
COPIED_STATUS = re.compile(
    r"\b(?:OWNER_GOOGLE_FOUR|OWNER_EXCLUDED|MERGED_SOURCE_PLUS|"
    r"GOOGLE_MODEL_SOURCE_MERGED)\s*=", re.I
)
STALE_SOURCE = re.compile(
    r"LOCAL Google registration not merged|"
    r"Google four are in LOCAL unmerged source|"
    r"google_provider\.py absent", re.I
)
OWNER_ONLY = (
    "MODEL_DECISION_AUTHORITY=OWNER_ONLY",
    "DEFAULT_AGENT_ACTION=STOP_AND_ASK_OWNER",
    "IMPLICIT_MODEL_APPROVAL=NO",
)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def inspect_content(relative: str, content: str) -> list[str]:
    """Pure content inspector, including simulated intentionally malformed input."""
    errors: list[str] = []
    for kind, pattern in (
        ("copied-model-ID", MODEL_ID),
        ("copied-volatile-status", COPIED_STATUS),
        ("stale-source-claim", STALE_SOURCE),
    ):
        found = pattern.search(content)
        if found:
            errors.append(f"{relative}: {kind}: {found.group(0)}")
    for declaration in OWNER_ONLY:
        if declaration in content:
            errors.append(f"{relative}: duplicate-owner-policy: {declaration}")
    return errors


def inspect_links(root: Path, relative: str, content: str) -> list[str]:
    """Local Markdown paths only; do not fetch HTTP(S) resources."""
    errors: list[str] = []
    file = root / relative
    links = MARKDOWN_LINK.findall(content)
    if not links:
        return [f"{relative}: no-markdown-links-parsed"]
    for href in links:
        href = href.strip().strip("<>")
        if href.startswith(("https://", "http://", "mailto:", "#", "data:")):
            continue
        target = unquote(href.split("#", 1)[0])
        if not target:
            continue
        # A Markdown title is outside the path; selected entrypoints do not
        # use titles, but support normal quoted titles rather than false failing.
        target = target.split(' "', 1)[0]
        candidate = (file.parent / target).resolve()
        if not candidate.is_relative_to(root.resolve()):
            errors.append(f"{relative}: escaped-repository: {href}")
        elif not candidate.is_file():
            errors.append(f"{relative}: missing-link-target: {href}")
    return errors


def inspect_ci_contract(workflow: str) -> list[str]:
    errors: list[str] = []
    if not re.search(r"(?m)^\s{2}pull_request:\s*$", workflow):
        errors.append("ci: pull_request-trigger-missing")
    # Existing operations-policy guard intentionally runs on every PR and
    # collects the entire docs/operations/tests tree (including this checker).
    trigger = workflow.split("permissions:", 1)[0]
    if re.search(r"(?m)^\s+paths(?:-ignore)?:", trigger):
        errors.append("ci: document-guard-trigger-path-filtered")
    if "python -m pytest -q docs/operations/tests" not in workflow:
        errors.append("ci: document-tests-not-collected")
    if not re.search(r"(?m)^\s+contents:\s*read\s*$", workflow):
        errors.append("ci: read-only-contents-permission-missing")
    if "persist-credentials: false" not in workflow:
        errors.append("ci: checkout-credentials-must-not-persist")
    return errors


def scan_repository(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    for relative in SCOPED_DOCS:
        file = root / relative
        if not file.is_file():
            errors.append(f"{relative}: current-entrypoint-missing")
            continue
        content = file.read_text(encoding="utf-8")
        errors.extend(inspect_content(relative, content))
        errors.extend(inspect_links(root, relative, content))
    policy = root / OWNER_POLICY
    if not policy.is_file():
        errors.append(f"{OWNER_POLICY}: owner-policy-missing")
    else:
        text = policy.read_text(encoding="utf-8")
        for declaration in OWNER_ONLY:
            if declaration not in text:
                errors.append(f"{OWNER_POLICY}: canonical-owner-guard-absent: {declaration}")
    workflow = root / OPS_CI_WORKFLOW
    if not workflow.is_file():
        errors.append(f"{OPS_CI_WORKFLOW}: ci-workflow-missing")
    else:
        errors.extend(inspect_ci_contract(workflow.read_text(encoding="utf-8")))
    history_guard = root / HISTORY_TEST
    if not history_guard.is_file():
        errors.append(f"{HISTORY_TEST}: history-hash-guard-missing")
    else:
        guard = history_guard.read_text(encoding="utf-8")
        if "ARCHIVES_SHA256" not in guard or "test_history_snapshot_bytes_and_index_are_unchanged" not in guard:
            errors.append(f"{HISTORY_TEST}: history-hash-guard-not-asserted")
    return errors


def main() -> int:
    errors = scan_repository(ROOT)
    if errors:
        for item in errors:
            print("DOC_AUTHORITY_FAIL " + item, file=sys.stderr)
        return 1
    print(f"DOC_AUTHORITY_PASS entrypoints={len(SCOPED_DOCS)} "
          "owner_policy=1 workflow=1 history_guard=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
