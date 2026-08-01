#!/usr/bin/env python3
"""validate-portfolio-governance.py

Repository-wide portfolio-governance consistency validator for PR #365.

Checks are deliberately limited to ACTIVE governance documents so historical
records (reference/** Phase 1 records, recorded verdicts, superseded defaults
sections) are not misreported as active conflicts.

Run from the repository root:
    python3 scripts/validate-portfolio-governance.py
Exit 0 on success, 1 on any violation.
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
errors = []
checks = []


def check(name, ok, detail=""):
    checks.append((name, bool(ok)))
    if not ok:
        errors.append(f"{name}: {detail}")


def read(rel):
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.is_file() else ""


# ---------------------------------------------------------------------------
# 1. Required policy files exist
# ---------------------------------------------------------------------------
REQUIRED_POLICIES = [
    "docs/operations/OWNER_EXPERTISE_AND_OPERATOR_BOUNDARY.md",
    "docs/operations/COMPETITIVE_REFERENCE_AND_VISUAL_QUALITY_POLICY.md",
    "docs/operations/BACKEND_MVP_OPERATING_POLICY.md",
    "docs/operations/PORTFOLIO_PRODUCT_QUALITY_AUDIT.md",
    "docs/operations/DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md",
    "docs/operations/UI_UX_BACKEND_PHASE_GATES.md",
    "docs/operations/README.md",
]
for rel in REQUIRED_POLICIES:
    check(f"required policy exists: {rel}", (ROOT / rel).is_file())

OPS_README = read("docs/operations/README.md")
TOP_README = read("README.md")
INTENT = read("docs/portfolio/AI_REVENUE_LAB_OPERATING_INTENT.md")
BACKLOG = read("docs/portfolio/BUSINESS_CANDIDATE_BACKLOG.md")
PHASE_GATES = read("docs/operations/UI_UX_BACKEND_PHASE_GATES.md")

# ---------------------------------------------------------------------------
# 2. Top-level docs link the required policies
# ---------------------------------------------------------------------------
for name, content, target in [
    ("ops README links owner-expertise policy", OPS_README, "OWNER_EXPERTISE_AND_OPERATOR_BOUNDARY.md"),
    ("ops README links competitive-visual policy", OPS_README, "COMPETITIVE_REFERENCE_AND_VISUAL_QUALITY_POLICY.md"),
    ("ops README links backend MVP policy", OPS_README, "BACKEND_MVP_OPERATING_POLICY.md"),
    ("ops README links portfolio audit policy", OPS_README, "PORTFOLIO_PRODUCT_QUALITY_AUDIT.md"),
    ("ops README links deployment policy", OPS_README, "DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md"),
    ("top README links deployment policy", TOP_README, "DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md"),
    ("operating intent links deployment policy", INTENT, "DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md"),
    ("backlog links phase gates", BACKLOG, "UI_UX_BACKEND_PHASE_GATES.md"),
]:
    check(name, target in content)

# ---------------------------------------------------------------------------
# 3. Current portfolio mode is MVP_AND_VISUAL_UPGRADE
# ---------------------------------------------------------------------------
check("ops README declares MVP_AND_VISUAL_UPGRADE", "MVP_AND_VISUAL_UPGRADE" in OPS_README)
check("backlog declares MVP_AND_VISUAL_UPGRADE", "MVP_AND_VISUAL_UPGRADE" in BACKLOG)
check("backlog no longer declares UI_ONLY as current mode",
      "Current portfolio mode: `UI_ONLY`" not in BACKLOG)

# ---------------------------------------------------------------------------
# 4. UI_ONLY is not an active portfolio default
#   (limited to the active hub doc; UI_ONLY words in historical/business records are ignored)
# ---------------------------------------------------------------------------
check("ops README marks former UI_ONLY default as superseded",
      "superseded" in OPS_README and "UI_ONLY" in OPS_README)
check("phase gates mark UI_ONLY as superseded", "superseded" in PHASE_GATES.lower())

# ---------------------------------------------------------------------------
# 5. backend frozen is not an active portfolio default
# ---------------------------------------------------------------------------
check("ops README declares backend no longer frozen by default",
      "no longer frozen by default" in OPS_README or "Backend work is no longer frozen" in OPS_README)
check("ops README does not declare backend frozen as current default",
      "backend frozen by default" not in OPS_README.lower() or "no longer frozen" in OPS_README.lower())

# ---------------------------------------------------------------------------
# 6. Two deployment lanes exist
# ---------------------------------------------------------------------------
check("ops README names approved exact-head demo lane",
      "APPROVED_EXACT_HEAD_DEMO" in OPS_README or "Approved exact-head demo" in OPS_README)
check("ops README names canonical production lane",
      "CANONICAL_PRODUCTION" in OPS_README or "Canonical Production" in OPS_README)
check("deployment policy defines both lanes",
      "APPROVED_EXACT_HEAD_DEMO" in read("docs/operations/DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md")
      and "CANONICAL_PRODUCTION" in read("docs/operations/DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md"))

# ---------------------------------------------------------------------------
# 7. Required status vocabulary exists in the active phase gates
# ---------------------------------------------------------------------------
STATUS_VOCAB = [
    "PRODUCT_FRAMED",
    "COMPETITIVE_DEMO",
    "INVESTOR_DEMO",
    "MVP_VERTICAL_SLICE",
    "SERVICE_LED_PILOT",
    "RUNTIME_PILOT",
    "COMMERCIAL_HARDENING",
    "OPERATING_PRODUCT",
]
for token in STATUS_VOCAB:
    check(f"phase gates status vocabulary: {token}", token in PHASE_GATES or token in OPS_README)

# ---------------------------------------------------------------------------
# 8. Owner-expertise policy present and linked from the hub
# ---------------------------------------------------------------------------
check("owner-expertise policy declares multidisciplinary expert",
      "multidisciplinary expert" in read("docs/operations/OWNER_EXPERTISE_AND_OPERATOR_BOUNDARY.md"))
check("ops README owner standard present", "multidisciplinary expert" in OPS_README)

# ---------------------------------------------------------------------------
# 9. Policy cross-link targets exist
# ---------------------------------------------------------------------------
LINK_CHECKS = [
    ("docs/operations/README.md", "../portfolio/AI_REVENUE_LAB_OPERATING_INTENT.md"),
    ("docs/operations/README.md", "../portfolio/BUSINESS_CANDIDATE_BACKLOG.md"),
    ("docs/operations/BACKEND_MVP_OPERATING_POLICY.md", "DIRECT_PRODUCTION_DEPLOYMENT_AND_ROLLBACK_POLICY.md"),
]
for src, target in LINK_CHECKS:
    target_abs = ((ROOT / src).resolve().parent / pathlib.PurePosixPath(target)).resolve()
    check(f"link target exists: {target} (from {src})", target_abs.is_file() or target_abs.exists())

# ---------------------------------------------------------------------------
result = {
    "status": "pass" if not errors else "fail",
    "checks_total": len(checks),
    "checks_passed": sum(1 for _, ok in checks if ok),
    "checks_failed": len(errors),
    "errors": errors,
}
print(json.dumps(result, ensure_ascii=False, indent=2))
raise SystemExit(1 if errors else 0)
