#!/usr/bin/env python3
"""Read-only Cloudflare Pages credential health audit for ai-revenue-lab.

Checks:
- CLOUDFLARE_API_TOKEN exists
- CLOUDFLARE_ACCOUNT_ID exists
- Cloudflare token verification endpoint
- Pages projects API responds
- Business 37 project exists with correct name and source type
- Production URL is reachable

Exit codes:
    0 — all checks pass
    1 — any check failed

No secret values are ever printed.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request


API_URL = "https://api.cloudflare.com/client/v4"
EXPECTED_ACCOUNT_ID = "9be14bb7b8974e65d0afba647ab16932"
B37_PROJECT = "ai-revenue-business-37-ai-safe-route"
EXPECTED_REPOSITORY = "skerishKang/ai-revenue-lab"
EXPECTED_BRANCH = "main"
B37_URL = "https://ai-revenue-business-37-ai-safe-route.pages.dev/"


def _request(path: str, token: str) -> tuple[int, dict | list]:
    req = urllib.request.Request(f"{API_URL}{path}", method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.load(exc.read())
        except json.JSONDecodeError:
            return exc.code, {}
    except urllib.error.URLError as exc:
        print(f"error: HTTP request failed: {exc.reason}", file=sys.stderr)
        return 0, {}


def _check_production_url() -> bool:
    req = urllib.request.Request(B37_URL, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except urllib.error.HTTPError:
        return False
    except urllib.error.URLError:
        return False


def main() -> int:
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    failures: list[str] = []

    # 1. Token exists
    if not token:
        failures.append("CLOUDFLARE_API_TOKEN secret is not set")
    else:
        fp = hashlib.sha256(token.encode()).hexdigest()[:12]
        print(f"[PASS] CLOUDFLARE_API_TOKEN exists (fingerprint: {fp}...)")

    # 2. Account ID exists
    if not account_id:
        failures.append("CLOUDFLARE_ACCOUNT_ID secret is not set")
    else:
        print(f"[PASS] CLOUDFLARE_ACCOUNT_ID exists")

    if failures:
        for f in failures:
            print(f"[FAIL] {f}", file=sys.stderr)
        return 1

    # 3. Cloudflare token verification
    status, data = _request("/user/tokens/verify", token)
    if status == 200 and data.get("success"):
        print("[PASS] Cloudflare token verification: HTTP 200")
    else:
        print(f"[FAIL] Cloudflare token verification: HTTP {status}", file=sys.stderr)
        failures.append("token_verify")

    # 4. Account ID matches expected
    if account_id != EXPECTED_ACCOUNT_ID:
        print(f"[FAIL] CLOUDFLARE_ACCOUNT_ID mismatch: expected ...{EXPECTED_ACCOUNT_ID[-8:]}, got ...{account_id[-8:]}")
        failures.append("account_id_mismatch")

    # 5. Pages projects API
    status, data = _request(f"/accounts/{account_id}/pages/projects?per_page=10", token)
    if status == 200 and data.get("success"):
        projects = data.get("result", []) or []
        print(f"[PASS] Pages projects API: HTTP 200 ({len(projects)} project(s) found)")
    else:
        print(f"[FAIL] Pages projects API: HTTP {status}", file=sys.stderr)
        failures.append("pages_api")

    # 6. Business 37 project exists
    status, data = _request(f"/accounts/{account_id}/pages/projects/{B37_PROJECT}", token)
    if status == 200 and data.get("success"):
        project = data.get("result", {})
        print(f"[PASS] Business 37 project '{B37_PROJECT}' found")
        source = project.get("source") or {}
        if source.get("type") == "github":
            print("[PASS]   source type: Git-connected")
        else:
            print(f"[FAIL]   source type: {source.get('type', 'direct_upload')} (expected: github)", file=sys.stderr)
            failures.append("b37_source_type")
        build = project.get("build_config") or {}
        if build.get("root_dir"):
            print(f"[PASS]   root directory: {build['root_dir']}")
    else:
        print(f"[FAIL] Business 37 project '{B37_PROJECT}' not found (HTTP {status})", file=sys.stderr)
        failures.append("b37_project_missing")

    # 7. Production URL reachable
    if _check_production_url():
        print(f"[PASS] Production URL {B37_URL} is reachable (HTTP 200)")
    else:
        print(f"[FAIL] Production URL {B37_URL} is not reachable", file=sys.stderr)
        failures.append("b37_url")

    if failures:
        print(f"\n{len(failures)} check(s) failed.", file=sys.stderr)
        return 1

    print("\nAll Cloudflare Pages credential health checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
