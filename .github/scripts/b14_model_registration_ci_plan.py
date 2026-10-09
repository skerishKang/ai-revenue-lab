#!/usr/bin/env python3
"""Fail-closed B14 model-registration-only CI classifier. No provider calls.

Run by *both* B14 and B62 workflows. Github API is used only for exact changed
file metadata and the prior canonical registry, never for credentials.
If the event, pagination, patch, registry, or API is ambiguous => full suite.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import urllib.parse
import urllib.error
import urllib.request

REGISTRY = "apps/korean-ai-platform/app/pilot/b14_models.json"
WRANGLER = "apps/korean-ai-platform/wrangler.toml"
WORKER = "apps/korean-ai-platform/worker.py"
CODE_PATHS = {REGISTRY, WRANGLER, WORKER}
SECRET_LINE = re.compile(r'^\s*"PADIEM_[A-Z0-9_]+_API_KEY",\s*$')
BINDING_LINE = re.compile(r'^\s*(binding|secret_name)\s*=\s*"PADIEM_[A-Z0-9_]+_API_KEY"\s*$')
STORE_LINE = re.compile(r'^\s*store_id\s*=\s*"[0-9a-f]{32}"\s*$')


def allowed_file(path: str) -> bool:
    if path in CODE_PATHS:
        return True
    if path.startswith("apps/korean-ai-platform/tests/") and path.endswith(".py"):
        return True
    if path.startswith("docs/models/final-evaluation/") and path.endswith(".md"):
        return True
    if path == "docs/operations/tests/test_b14_owner_model_docs_consistency.py":
        return True
    if path.startswith(".github/tests/test_b14_") and path.endswith(".py"):
        return True
    if path in {
        ".github/tests/test_b66_quote_model_benchmark.py",
        ".github/tests/test_b67_space_bunny_primary_parity.py",
        ".github/scripts/b14_owner_evaluation_registry.py",
        "apps/korean-ai-platform/scripts/check_b14_worker_bundle.py",
    }:
        return True
    return False


def additions_only(patch: str | None, filename: str) -> bool:
    if not isinstance(patch, str) or not patch.startswith("@@"):
        return False
    added = []
    for line in patch.splitlines():
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("-"):
            return False
        if line.startswith("+"):
            added.append(line[1:])
    if not added:
        return False
    if filename == WORKER:
        return all(SECRET_LINE.fullmatch(line) for line in added)
    if filename == WRANGLER:
        return all(
            not line.strip()
            or line.lstrip().startswith("#")
            or line.strip() == "[[secrets_store_secrets]]"
            or BINDING_LINE.fullmatch(line)
            or STORE_LINE.fullmatch(line)
            for line in added
        )
    return False


def exact_append_only(old: dict, new: dict) -> bool:
    """Only add exact model/provider entries; never change existing privileges."""
    try:
        if not isinstance(old, dict) or not isinstance(new, dict):
            return False
        if set(old) != set(new):
            return False
        for name in old:
            if name not in ("models", "providers") and old[name] != new[name]:
                return False
        previous, current = old["models"], new["models"]
        if not isinstance(previous, list) or not isinstance(current, list):
            return False
        if len(current) <= len(previous) or current[:len(previous)] != previous:
            return False
        providers_old, providers_new = old["providers"], new["providers"]
        if not isinstance(providers_old, dict) or not isinstance(providers_new, dict):
            return False
        if any(providers_new.get(pid) != spec for pid, spec in providers_old.items()):
            return False
        existing_ids = {m["id"] for m in previous}
        all_ids = [m["id"] for m in current]
        if len(all_ids) != len(set(all_ids)) or len(existing_ids) != len(previous):
            return False
        if any(pid not in providers_new for pid in providers_old):
            return False
        for model in current[len(previous):]:
            mid = model["id"]
            pid = model["provider_id"]
            if mid in existing_ids or not mid.startswith(pid + "/"):
                return False
            if pid not in providers_new or model.get("enabled") is not True:
                return False
        for pid, spec in providers_new.items():
            if pid in providers_old:
                continue
            if spec.get("enabled") is not True or spec.get("credential_source") != "platform_secret":
                return False
            if not spec.get("credential_binding_name", "").startswith("PADIEM_"):
                return False
            if not spec.get("allowed_hosts") or not spec.get("base_origin"):
                return False
        return True
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def model_registration_only(changed_files: list[dict], base: dict, head: dict) -> bool:
    if not changed_files or len(changed_files) > 100:
        return False
    if any(row.get("status") not in ("modified", "added") for row in changed_files):
        return False
    paths = [row.get("filename", "") for row in changed_files]
    if len(set(paths)) != len(paths) or REGISTRY not in paths:
        return False
    if not all(allowed_file(p) for p in paths):
        return False
    if not exact_append_only(base, head):
        return False
    for row in changed_files:
        if row["filename"] in (WRANGLER, WORKER):
            if not additions_only(row.get("patch"), row["filename"]):
                return False
    # Metadata of newly added provider must be wired to the same exact name.
    new_provider_ids = set(head["providers"]) - set(base["providers"])
    if new_provider_ids:
        if WORKER not in paths or WRANGLER not in paths:
            return False
        added_worker = changed_files[paths.index(WORKER)]["patch"]
        added_wrangler = changed_files[paths.index(WRANGLER)]["patch"]
        for pid in new_provider_ids:
            binding = head["providers"][pid].get("credential_binding_name")
            if not isinstance(binding, str) or not SECRET_LINE.fullmatch(f'    "{binding}",'):
                return False
            if f'+    "{binding}",' not in added_worker:
                return False
            if f'+binding = "{binding}"' not in added_wrangler:
                return False
            if f'+secret_name = "{binding}"' not in added_wrangler:
                return False
    return True


def api_json(url: str, token: str):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "padiem-b14-model-ci-classifier/1.0",
    })
    with urllib.request.urlopen(req, timeout=15) as result:
        return json.load(result)


def classify_github(event: dict, event_name: str, repo: str, token: str, head_root: Path) -> str:
    if not token or not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        return "full"
    api = f"https://api.github.com/repos/{repo}"
    if event_name == "pull_request":
        pr = event.get("pull_request") or {}
        n = pr.get("number")
        base_sha = (pr.get("base") or {}).get("sha")
        if not isinstance(n, int) or not re.fullmatch(r"[a-f0-9]{40}", str(base_sha)):
            return "full"
        files = []
        for page in range(1, 4):
            chunk = api_json(f"{api}/pulls/{n}/files?per_page=100&page={page}", token)
            if not isinstance(chunk, list):
                return "full"
            files.extend(chunk)
            if len(chunk) < 100:
                break
        if len(files) > 100:
            return "full"
    elif event_name == "push":
        base_sha, head_sha = event.get("before"), event.get("after")
        if not all(re.fullmatch(r"[a-f0-9]{40}", str(v)) and set(v) != {"0"} for v in (base_sha, head_sha)):
            return "full"
        comparison = api_json(f"{api}/compare/{base_sha}...{head_sha}", token)
        files = comparison.get("files") or []
        if comparison.get("status") not in ("ahead", "identical") or len(files) > 100:
            return "full"
    else:
        return "full"
    # Most changes (including test-only and CI source) must use full regression.
    paths = [f.get("filename") for f in files]
    if REGISTRY not in paths or not paths or not all(allowed_file(p or "") for p in paths):
        return "full"
    qpath = urllib.parse.quote(REGISTRY, safe="/")
    raw = api_json(f"{api}/contents/{qpath}?ref={base_sha}", token)
    if raw.get("encoding") != "base64":
        return "full"
    base = json.loads(base64.b64decode(raw["content"]))
    head = json.loads((head_root / REGISTRY).read_text(encoding="utf-8"))
    return "model_registration_only" if model_registration_only(files, base, head) else "full"


def main():
    mode = "full"
    reason = "fail-closed"
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        mode = classify_github(
            event,
            os.environ.get("GITHUB_EVENT_NAME", ""),
            os.environ.get("GITHUB_REPOSITORY", ""),
            os.environ.get("GITHUB_TOKEN", ""),
            Path.cwd(),
        )
        reason = "exact-source-and-change-set-matched" if mode == "model_registration_only" else "full-or-unsupported-scope"
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError) as error:
        # Never print token, HTTP response body, or remote diff.
        reason = f"safe-full-fallback:{type(error).__name__}"
        mode = "full"
    print(f"B14_CI_LANE={mode}")
    print(f"B14_CI_CLASSIFIER={reason}")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"lane={mode}\n")


if __name__ == "__main__":
    main()
