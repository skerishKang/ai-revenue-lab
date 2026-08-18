#!/usr/bin/env python3
"""Validate the Business 32 commercial pilot package.

Checks required files, offer ladder A/B/C, price hypotheses, B35->B32 funnel,
verified skill package wording, deliverable fields, backend absence, no real
customer/org data, no performance-guarantee or employee-replacement claims, and
human-review requirement.
"""
import os
import re
import subprocess
import sys

VALIDATED_UX_HEAD = "73ec4718d0835248ab20d56bc68f3956536112b4"
VALIDATED_HANDOFF_HEAD = "29068281998b7f1a59d76a95174807ffbf20cb38"
WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(WORKSPACE))))
PRODUCT_WORKSPACE = os.path.join(REPO_ROOT, "reference", "business-32-ai-skill-studio-ux")

REQUIRED_FILES = [
    "README.md",
    "01-commercial-positioning.md",
    "02-offer-ladder.md",
    "03-b35-to-b32-sales-funnel.md",
    "04-skill-conversion-sprint.md",
    "05-team-pilot-plan.md",
    "06-deliverable-spec.md",
    "07-pricing-hypotheses.md",
    "08-customer-qualification-scorecard.md",
    "09-sales-meeting-script.md",
    "10-risk-data-and-authority-boundary.md",
    "11-pilot-acceptance-checklist.md",
    "12-case-study-template.md",
    "tests/validate_commercial_package.py",
]

SKILL_FIELDS = [
    "skill name",
    "business purpose",
    "owner",
    "active operator",
    "reviewer",
    "allowed use",
    "prohibited use",
    "required inputs",
    "execution steps",
    "AI-assisted steps",
    "human actions",
    "evidence requirements",
    "missing-evidence behavior",
    "conflicting-evidence behavior",
    "review checks",
    "known exceptions",
    "approval record",
    "version",
    "next review date",
    "rollback condition",
]

ABSENT_FEATURES = [
    "account",
    "authentication",
    "persistent database",
    "live AI model",
    "file upload",
    "enterprise integration",
    "billing",
    "production automation",
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
    for rel in REQUIRED_FILES:
        check("required file exists: " + rel, lambda r=rel: assert_exists(r))

    offers = read("02-offer-ladder.md")
    check("Offer A/B/C ladder present", lambda: (
        require_present(offers, "Offer A", "Offer A"),
        require_present(offers, "Offer B", "Offer B"),
        require_present(offers, "Offer C", "Offer C"),
    ))

    check("every price is a hypothesis", lambda: (
        require_present(offers, "300만~500만원", "Offer A price"),
        require_present(offers, "500만~800만원", "Offer B price"),
        require_present(offers, "1,200만~2,000만원", "Offer C price"),
        require_present(offers, "가설", "hypothesis wording"),
        require_present(read("07-pricing-hypotheses.md"), "PRICE_HYPOTHESIS_ONLY", "price hypothesis status"),
    ))

    funnel = read("03-b35-to-b32-sales-funnel.md")
    check("B35 to B32 sales funnel present", lambda: (
        require_present(funnel, "Business 35", "B35 reference"),
        require_present(funnel, "Business 32", "B32 reference"),
        require_present(funnel, "스킬 전환 스프린트", "sprint step"),
        require_present(funnel, "분기별 검토·버전 갱신", "quarterly review step"),
    ))

    combined = "\n".join(read(rel) for rel in REQUIRED_FILES if rel.endswith(".md"))
    check("verified skill package wording present", lambda: (
        require_present(combined, "VERIFIED ORGANIZATIONAL AI SKILL PACKAGE", "verified skill package"),
        require_present(combined, "검증된 조직 AI 업무 스킬 패키지", "korean verified skill package"),
        require_present(combined, "SERVICE-LED FRONTEND PILOT", "service-led pilot form"),
    ))

    deliverable = read("06-deliverable-spec.md")
    for field in SKILL_FIELDS:
        check("deliverable field present: " + field, lambda f=field: require_present(deliverable, f, "deliverable field"))

    check("absent backend features are declared as not provided", lambda: tuple(
        require_present(combined, feature, "absent feature declaration: " + feature)
        for feature in ABSENT_FEATURES
    ))

    check("no real customer or organization data", lambda: (
        assert_no_email(combined),
        assert_no_phone(combined),
        assert_no_business_number(combined),
    ))

    check("no performance-guarantee claims", lambda: (
        assert_not_present(combined, "보장합니다"),
        assert_not_present(combined, "보장해 드립니다"),
        assert_not_present(combined, "보장한다"),
    ))

    check("no employee-replacement claims", lambda: (
        assert_not_present(combined, "대체합니다"),
        assert_not_present(combined, "대체해 드립니다"),
    ))

    check("human review is required", lambda: (
        require_present(combined, "사람 검토", "human review requirement"),
        require_present(combined, "사람 검토와 승인", "human review and approval"),
    ))

    check("do-not-send status present", lambda: (
        require_present(read("README.md"), "DO_NOT_SEND", "do-not-send status"),
        require_present(read("11-pilot-acceptance-checklist.md"), "DO_NOT_SEND", "checklist status"),
    ))

    check("validated heads referenced", lambda: (
        require_present(read("README.md"), VALIDATED_UX_HEAD, "validated UX head"),
        require_present(read("README.md"), VALIDATED_HANDOFF_HEAD, "validated handoff head"),
    ))

    check("no backend implementation files in workspace", lambda: assert_no_backend_files())

    check("validated product workspace unchanged", lambda: assert_product_unchanged())

    print()
    if failures:
        print("%d validation failure(s)" % len(failures))
        return 1
    print("commercial package validation ok")
    return 0


def assert_exists(rel):
    assert os.path.isfile(os.path.join(WORKSPACE, rel)), "missing file: " + rel


def assert_not_present(text, needle):
    assert needle not in text, "forbidden claim present: " + needle


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
            if rel.startswith("tests") and name == "validate_commercial_package.py":
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
