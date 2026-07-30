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

No secret values or fingerprints are ever printed.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import socket


API_URL = "https://api.cloudflare.com/client/v4"
EXPECTED_ACCOUNT_ID = "9be14bb7b8974e65d0afba647ab16932"
B37_PROJECT = "ai-revenue-business-37-ai-safe-route"
EXPECTED_REPOSITORY = "skerishKang/ai-revenue-lab"
EXPECTED_BRANCH = "main"
B37_URL = "https://ai-revenue-business-37-ai-safe-route.pages.dev/"


def request_json(path: str, token: str) -> tuple[int, object]:
    req = urllib.request.Request(f"{API_URL}{path}", method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            try:
                body = resp.read()
                data = json.loads(body.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                data = {}
            return resp.status, data
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
            data = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = {}
        return exc.code, data
    except urllib.error.URLError:
        return 0, {}
    except (TimeoutError, socket.timeout):
        return 0, {}


def fetch_production_status(url: str) -> int:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except urllib.error.URLError:
        return 0
    except (TimeoutError, socket.timeout):
        return 0


def validate_project_contract(project: dict) -> list[str]:
    failures = []
    expected_owner, expected_repo = EXPECTED_REPOSITORY.split("/")

    if project.get("name") != B37_PROJECT:
        failures.append("contract: wrong project.name")
    if project.get("production_branch") != EXPECTED_BRANCH:
        failures.append("contract: wrong top-level production branch")

    source = project.get("source")
    if not isinstance(source, dict) or source.get("type") != "github":
        failures.append("contract: source.type null/direct-upload rejected")
    else:
        config = source.get("config", {})
        if config.get("owner") != expected_owner:
            failures.append("contract: wrong source owner rejected")
        if config.get("repo_name") != expected_repo:
            failures.append("contract: wrong repo_name rejected")
        if config.get("production_branch") != EXPECTED_BRANCH:
            failures.append("contract: wrong source production branch rejected")
        if config.get("production_deployments_enabled") is not True:
            failures.append("contract: production_deployments_enabled false rejected")
        if config.get("preview_deployment_setting") != "none":
            failures.append("contract: Preview enabled rejected")
        if config.get("pr_comments_enabled") is not False:
            failures.append("contract: PR comments enabled rejected")

    build_config = project.get("build_config") or {}
    if build_config.get("root_dir") != "reference/business-37-ai-safe-route-v1":
        failures.append("contract: wrong root directory rejected")
    if build_config.get("destination_dir") != ".":
        failures.append("contract: wrong destination directory rejected")
    if build_config.get("build_command") != "":
        failures.append("contract: non-empty build command rejected")

    return failures


def run_audit(token: str, account_id: str) -> list[str]:
    failures = []

    if not token:
        failures.append("CLOUDFLARE_API_TOKEN missing")
    else:
        print("[PASS] CLOUDFLARE_API_TOKEN is present")

    if not account_id:
        failures.append("CLOUDFLARE_ACCOUNT_ID missing")
    else:
        print("[PASS] CLOUDFLARE_ACCOUNT_ID is present")

    if failures:
        return failures

    if account_id != EXPECTED_ACCOUNT_ID:
        failures.append("CLOUDFLARE_ACCOUNT_ID mismatch")

    status, data = request_json("/user/tokens/verify", token)
    if status == 200 and isinstance(data, dict) and data.get("success"):
        print("[PASS] token verification PASS")
    else:
        failures.append("token verification FAIL")

    status, data = request_json(f"/accounts/{account_id}/pages/projects", token)
    if status == 200 and isinstance(data, dict) and data.get("success"):
        print("[PASS] Pages API PASS")
    else:
        failures.append("Pages API FAIL")

    status, data = request_json(f"/accounts/{account_id}/pages/projects/{B37_PROJECT}", token)
    if status == 200 and isinstance(data, dict) and data.get("success"):
        project = data.get("result", {})
        contract_failures = validate_project_contract(project)
        if contract_failures:
            print("[FAIL] project contract FAIL category")
            failures.extend(contract_failures)
        else:
            print("[PASS] project contract PASS category")
    else:
        failures.append("project missing")

    url_status = fetch_production_status(B37_URL)
    if url_status == 200:
        print("[PASS] Production URL HTTP status category")
    else:
        failures.append("Production URL failure")

    return failures


def main() -> int:
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")

    failures = run_audit(token, account_id)
    if failures:
        for f in failures:
            print(f"[FAIL] {f}", file=sys.stderr)
        print(f"\n{len(failures)} check(s) failed.", file=sys.stderr)
        return 1

    print("\nAll Cloudflare Pages credential health checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
