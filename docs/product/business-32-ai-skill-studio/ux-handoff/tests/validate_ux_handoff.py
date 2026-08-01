#!/usr/bin/env python3
"""Validate the Business 32 pilot UX handoff package.

Checks required files, the 24-state matrix, role separation, trust labels,
browser head match, anti-optimistic-approval wording, PII forbidden fields,
absence of real customer/supplier identifiers, absence of backend files, and
that the validated product workspace is unchanged.
"""
import os
import re
import subprocess
import sys

VALIDATED_HEAD = "73ec4718d0835248ab20d56bc68f3956536112b4"
WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(WORKSPACE))))
PRODUCT_WORKSPACE = os.path.join(REPO_ROOT, "reference", "business-32-ai-skill-studio-ux")

REQUIRED_FILES = [
    "README.md",
    "01-demo-facilitator-script.md",
    "02-usability-test-plan.md",
    "03-state-role-action-matrix.md",
    "04-copy-and-trust-label-inventory.md",
    "05-backend-integration-ux-contract.md",
    "06-analytics-event-spec.md",
    "07-pilot-acceptance-checklist.md",
    "08-accessibility-responsive-evidence-index.md",
    "09-known-limitations-and-non-goals.md",
    "tests/validate_ux_handoff.py",
]

DOMAIN_STATES = [
    "initial", "task-selected", "input-incomplete", "ready", "running",
    "step-complete", "missing-evidence", "conflicting-evidence", "stopped",
    "draft-result", "review-requested", "correction-required", "revised",
    "approval-pending", "approved", "skill-saved",
]

GENERAL_STATES = [
    "loading", "empty", "validation-error", "system-error", "retry",
    "cancelled", "resume", "completed",
]

ALL_STATES = DOMAIN_STATES + GENERAL_STATES

TRUST_LABELS = [
    "AI-ASSISTED STEP",
    "HUMAN ACTION",
    "SOURCE EVIDENCE",
    "MISSING EVIDENCE",
    "CONFLICTING EVIDENCE",
    "DRAFT RESULT",
    "NOT YET APPROVED",
    "HUMAN-APPROVED",
    "VERIFIED ORGANIZATIONAL AI SKILL",
]

failures = []


def read(rel):
    with open(os.path.join(WORKSPACE, rel), "r", encoding="utf-8") as fh:
        return fh.read()


def check(name, fn):
    try:
        fn()
        print("PASS " + name)
    except AssertionError as error:
        failures.append(name)
        print("FAIL " + name + ": " + str(error))


def require_present(text, needle, what):
    assert needle in text, "missing %s: %s" % (what, needle)


def main():
    matrix = read("03-state-role-action-matrix.md")

    for rel in REQUIRED_FILES:
        check("required file exists: " + rel, lambda r=rel: assert_exists(r))

    check("24 states present in matrix", lambda: assert_states(matrix))

    matrix_text = matrix
    check("operator and reviewer roles present in matrix", lambda: (
        require_present(matrix_text, "operator", "operator role"),
        require_present(matrix_text, "reviewer", "reviewer role"),
    ))

    copy = read("04-copy-and-trust-label-inventory.md")
    for label in TRUST_LABELS:
        check("trust label present: " + label, lambda l=label: require_present(copy, l, "trust label"))

    ev = read("08-accessibility-responsive-evidence-index.md")
    check("browser exact head matches", lambda: (
        require_present(ev, VALIDATED_HEAD, "validated head"),
        require_present(ev, "BUSINESS_32_BROWSER_VALIDATION_PASS", "browser pass marker"),
        require_present(ev, "Screenshots retained by browser-validation environment.", "screenshot note"),
    ))

    contract = read("05-backend-integration-ux-contract.md")
    check("optimistic approval prohibition present", lambda: (
        require_present(contract, "optimistic approval", "optimistic approval clause"),
        require_present(contract, "optimistic skill save", "optimistic skill save clause"),
        require_present(contract, "server response", "server-authority clause"),
    ))

    spec = read("06-analytics-event-spec.md")
    check("PII forbidden fields present", lambda: (
        require_present(spec, "이메일", "email forbidden field"),
        require_present(spec, "전화번호", "phone forbidden field"),
        require_present(spec, "자유입력 전체 text", "free-text forbidden field"),
        require_present(spec, "견적 원문", "quotation forbidden field"),
    ))

    combined = "\n".join(read(rel) for rel in REQUIRED_FILES if rel.endswith(".md"))
    check("no real customer/supplier identifiers", lambda: (
        assert_no_email(combined),
        assert_no_phone(combined),
        assert_no_business_number(combined),
    ))

    check("no backend implementation files in workspace", lambda: assert_no_backend_files())

    check("validated product workspace unchanged", lambda: assert_product_unchanged())

    print()
    if failures:
        print("%d validation failure(s)" % len(failures))
        return 1
    print("ux handoff validation ok")
    return 0


def assert_exists(rel):
    assert os.path.isfile(os.path.join(WORKSPACE, rel)), "missing file: " + rel


def assert_states(matrix):
    for state in ALL_STATES:
        assert re.search(r"(^|\|)\s*" + re.escape(state) + r"\s*(\||$)", matrix), "state missing from matrix: " + state


def assert_no_email(text):
    assert not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text), "email-like pattern found"


def assert_no_phone(text):
    assert not re.search(r"010[- ]?\d{3,4}[- ]?\d{4}", text), "phone pattern found"


def assert_no_business_number(text):
    assert not re.search(r"\d{3}-\d{2}-\d{5}", text), "business registration pattern found"


def assert_no_backend_files():
    backend_markers = [".sql", "schema.py", "drizzle", "migration", "api/", "worker.py", "server.py"]
    for root, _dirs, files in os.walk(WORKSPACE):
        for name in files:
            full = os.path.join(root, name)
            rel = os.path.relpath(full, WORKSPACE)
            if rel.startswith("tests") and name == "validate_ux_handoff.py":
                continue
            for marker in backend_markers:
                assert marker not in rel.lower(), "backend file marker in workspace: " + rel


def assert_product_unchanged():
    out = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", PRODUCT_WORKSPACE],
        capture_output=True, text=True, cwd=REPO_ROOT,
    ).stdout.strip()
    assert not out, "validated product workspace has changes:\n" + out


if __name__ == "__main__":
    sys.exit(main())
