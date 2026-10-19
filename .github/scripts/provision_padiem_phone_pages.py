"""Provision *only* the Git-connected Cloudflare Pages project for public phone demo.

No deployments, retries, preview promotion, DNS or credential mutations.
Called once from GitHub Actions after reviewed main merge. Never print tokens.
"""
from __future__ import annotations
from pathlib import Path
import json
import os
import sys
import time
import urllib.error
import urllib.request

PROJECT = "padiem-phone-demo"
ROOT = "apps/padiem-phone/public-demo"
OWNER = "skerishKang"
OWNER_ID = "36503867"
REPO = "ai-revenue-lab"
REPO_ID = "1306003434"
BRANCH = "main"


def project_body() -> dict:
    return {
        "name": PROJECT,
        "production_branch": BRANCH,
        "build_config": {
            "build_command": "",
            "destination_dir": ".",
            "root_dir": ROOT,
        },
        "source": {
            "type": "github",
            "config": {
                "owner": OWNER,
                "owner_id": OWNER_ID,
                "repo_name": REPO,
                "repo_id": REPO_ID,
                "production_branch": BRANCH,
                "production_deployments_enabled": True,
                "preview_deployment_setting": "none",
                "pr_comments_enabled": False,
                "path_includes": [ROOT + "/*"],
            },
        },
    }


def validate_existing(project: dict) -> None:
    source = project.get("source") or {}
    cfg = source.get("config") or {}
    build = project.get("build_config") or {}
    expected = {
        "name": PROJECT, "production_branch": BRANCH,
    }
    for key, value in expected.items():
        if project.get(key) != value:
            raise RuntimeError("existing_project_contract_mismatch:" + key)
    if source.get("type") != "github":
        raise RuntimeError("existing_project_not_git_connected")
    for key, value in {
        "owner": OWNER, "repo_name": REPO,
        "production_branch": BRANCH
    }.items():
        if cfg.get(key) != value:
            raise RuntimeError("existing_project_git_source_mismatch:" + key)
    if str(cfg.get("repo_id")) != REPO_ID:
        raise RuntimeError("existing_project_repo_id_mismatch")
    if build.get("root_dir", "").strip("/") != ROOT:
        raise RuntimeError("existing_project_root_mismatch")
    if build.get("destination_dir") not in (".", ""):
        raise RuntimeError("existing_project_output_mismatch")
    if cfg.get("production_deployments_enabled") is False:
        raise RuntimeError("automatic_production_deployment_disabled")


def repair_deprecated_watch_path(account: str, token: str, project: dict) -> dict:
    """Narrowly repair the invalid path watch pattern created by this workflow.

    This PATCH changes only an approved Pages project setting. It does not
    create, retry, promote or trigger a deployment. The next meaningful source
    commit to the watched folder must still be automatically deployed.
    """
    validate_existing(project)
    cfg = (project.get("source") or {}).get("config") or {}
    current = cfg.get("path_includes")
    expected = [ROOT + "/*"]
    if current == expected:
        print("WATCH_PATH=VALID", flush=True)
        return project
    if current != [ROOT + "/**"]:
        raise RuntimeError("unexpected_pages_watch_path_configuration")
    status, changed = api_request(
        account, token, "PATCH", "/" + PROJECT,
        {"source": {"type": "github", "config": {"path_includes": expected}}},
    )
    if status != 200 or changed.get("success") is not True:
        raise RuntimeError("watch_path_configuration_repair_failed")
    status, readback = api_request(account, token, "GET", "/" + PROJECT)
    if status != 200 or readback.get("success") is not True:
        raise RuntimeError("watch_path_readback_failed")
    verified = readback.get("result") or {}
    validate_existing(verified)
    new_paths = ((verified.get("source") or {}).get("config") or {}).get("path_includes")
    if new_paths != expected:
        raise RuntimeError("watch_path_readback_mismatch")
    print("WATCH_PATH=REPAIRED_AND_VERIFIED", flush=True)
    print("DEPLOYMENT_API_USED=NO", flush=True)
    return verified


def api_request(account: str, token: str, method: str, suffix: str,
                payload: dict | None = None) -> tuple[int, dict]:
    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/pages/projects{suffix}"
    raw = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=raw, method=method,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        response = {}
        try:
            response = json.loads(exc.read().decode())
        except Exception:
            pass
        safe_errors = [(item.get("code"), item.get("message", "")[:150])
                       for item in response.get("errors", []) if isinstance(item, dict)]
        print(f"CLOUDFLARE_HTTP_ERROR={exc.code} ERRORS={safe_errors}", flush=True)
        return exc.code, response


def main() -> int:
    for name in ("index.html", "app.js", "demo-api.js", "styles.css",
                 "_headers", "assets/padiem-glass-female.jpg"):
        if not (Path(ROOT) / name).is_file():
            raise RuntimeError("missing_static_demo_asset:" + name)
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    if not token or len(account) != 32:
        raise RuntimeError("cloudflare_github_secret_unavailable")
    status, result = api_request(account, token, "GET", "/" + PROJECT)
    if status == 404:
        print("GIT_CONNECTED_PROJECT=NOT_FOUND; CREATING", flush=True)
        status, result = api_request(account, token, "POST", "", project_body())
        if status not in (200, 201) or result.get("success") is not True:
            raise RuntimeError("git_connected_pages_project_create_failed")
        print("GIT_CONNECTED_PROJECT=CREATED", flush=True)
    elif status == 200 and result.get("success") is True:
        print("GIT_CONNECTED_PROJECT=ALREADY_EXISTS", flush=True)
    else:
        raise RuntimeError("git_connected_project_lookup_failed")
    current_project = repair_deprecated_watch_path(
        account, token, result.get("result") or {}
    )
    validate_existing(current_project)
    print("GIT_CONNECTED_CONTRACT=VALID", flush=True)
    print("DIRECT_UPLOAD_USED=NO", flush=True)

    # Git-linked project may start initial Production build itself. Merely
    # observe it; never dispatch a source deployment or retry a failed build.
    last = None
    for attempt in range(6):
        _, lookup = api_request(account, token, "GET", "/" + PROJECT)
        if lookup.get("success") is not True:
            raise RuntimeError("git_connected_project_readback_failed")
        current = lookup.get("result") or {}
        validate_existing(current)
        if ((current.get("source") or {}).get("config") or {}).get("path_includes") != [ROOT + "/*"]:
            raise RuntimeError("watch_path_regressed")
        deploy = current.get("canonical_deployment") or current.get("latest_deployment") or {}
        state = (deploy.get("latest_stage") or {}).get("status") or deploy.get("status") or "NOT_YET_VISIBLE"
        deployment_id = deploy.get("id") or "UNKNOWN"
        url = deploy.get("url") or ""
        if state != last or attempt in (0, 5):
            print(f"AUTO_DEPLOY_STAGE={state} DEPLOY_ID={deployment_id}", flush=True)
            stage_trace = [
                (s.get("name"), s.get("status"))
                for s in (deploy.get("stages") or []) if isinstance(s, dict)
            ]
            print("AUTO_DEPLOY_STAGES=" + repr(stage_trace), flush=True)
            print("AUTO_DEPLOY_SKIP_REASON=" + str(deploy.get("skip_reason")), flush=True)
            http_status, deployments = api_request(
                account, token, "GET", "/" + PROJECT + "/deployments?per_page=5"
            )
            if http_status == 200 and deployments.get("success") is True:
                listing = deployments.get("result") or []
                if not isinstance(listing, list):
                    listing = []
                brief = []
                for item in listing[:3]:
                    source = item.get("deployment_trigger") or {}
                    brief.append({
                        "id": item.get("id"),
                        "env": item.get("environment"),
                        "source_type": source.get("type"),
                        "commit": (source.get("metadata") or {}).get("commit_hash"),
                        "state": (item.get("latest_stage") or {}).get("status"),
                        "stages": [(s.get("name"), s.get("status")) for s in item.get("stages", [])],
                    })
                print("LATEST_DEPLOYMENT_EVIDENCE=" + repr(brief), flush=True)
            last = state
        if state == "success" and url.startswith("https://"):
            print(f"AUTO_DEPLOY_RESULT=SUCCESS URL={url}", flush=True)
            print(f"PROJECT_SITE=https://{PROJECT}.pages.dev/", flush=True)
            return 0
        if state in ("failure", "canceled"):
            raise RuntimeError("git_connected_auto_deployment_failed")
        time.sleep(10)
    print("AUTO_DEPLOY_RESULT=PENDING_VERIFICATION", flush=True)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("PROVISION_ERROR=" + str(exc)[:180], file=sys.stderr)
        sys.exit(1)
