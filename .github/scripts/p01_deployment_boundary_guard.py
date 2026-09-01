#!/usr/bin/env python3
"""Repository-side guard for P01 source-integrity vs deployment boundaries.

This guard is intentionally conservative. It proves that repository-owned
GitHub Actions used for P01/Core/Engine/Control-Plane validation do not run
live Cloudflare/Pages deployment commands as a side effect of ordinary pull
requests.

It cannot mutate or certify external Cloudflare Pages project settings. External
Cloudflare bot preview comments, when they exist, must therefore be treated as a
separate platform integration state, not as a repository-owned Production
mutation.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"

P01_PATH_PREFIXES = (
    "packages/padiem-ai-core/**",
    "apps/padiem-ai-engine/**",
    "packages/padiem-control-plane/**",
    "docs/architecture/**",
)

DEPLOYMENT_PATTERNS = (
    re.compile(r"cloudflare/pages-action", re.IGNORECASE),
    re.compile(r"wrangler\s+pages\s+deploy", re.IGNORECASE),
    re.compile(r"wrangler\s+deploy", re.IGNORECASE),
    re.compile(r"pywrangler\s+deploy", re.IGNORECASE),
)

SAFE_DEPLOYMENT_CONTEXT = (
    "--dry-run",
    "deployment = none",
    "production_deployment=no",
    "production_deployment = no",
    "production_deploy=no",
    "production_deploy = no",
)

EXPLICIT_RELEASE_NAMES = (
    "production",
    "deploy",
    "pages",
    "release",
)


def _iter_workflows() -> Iterable[Path]:
    if not WORKFLOWS.exists():
        return ()
    return sorted(
        path
        for path in WORKFLOWS.iterdir()
        if path.is_file() and path.suffix in {".yml", ".yaml"}
    )


def _workflow_mentions_p01(text: str) -> bool:
    return any(prefix in text for prefix in P01_PATH_PREFIXES)


def _line_has_deployment_command(line: str) -> bool:
    return any(pattern.search(line) for pattern in DEPLOYMENT_PATTERNS)


def _line_is_safe(line: str) -> bool:
    lowered = line.lower()
    return any(marker in lowered for marker in SAFE_DEPLOYMENT_CONTEXT)


def _is_explicit_release_workflow(path: Path, text: str) -> bool:
    name = path.name.lower()
    header = "\n".join(text.lower().splitlines()[:12])
    return any(token in name or token in header for token in EXPLICIT_RELEASE_NAMES)


def audit() -> dict[str, object]:
    violations: list[dict[str, object]] = []
    audited: list[str] = []
    p01_workflows: list[str] = []

    for path in _iter_workflows():
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        audited.append(rel)
        if _workflow_mentions_p01(text):
            p01_workflows.append(rel)

        for lineno, line in enumerate(text.splitlines(), start=1):
            if not _line_has_deployment_command(line):
                continue
            if _line_is_safe(line):
                continue
            if _is_explicit_release_workflow(path, text):
                continue
            violations.append(
                {
                    "path": rel,
                    "line": lineno,
                    "reason": "deployment_command_in_non_release_workflow",
                }
            )

    return {
        "audited_workflow_count": len(audited),
        "p01_source_integrity_workflows": p01_workflows,
        "violations": violations,
        "source_integrity_validation": "preserved",
        "repository_owned_production_deployment": "not_performed",
        "external_cloudflare_pages_preview": "separate_platform_state_not_repo_owned_production",
    }


def main() -> int:
    result = audit()
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["violations"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
