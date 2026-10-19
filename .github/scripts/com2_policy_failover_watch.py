"""Trusted default-branch COM2 policy watchdog; never checks out PR code."""
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE = "https://api.github.com"
WAIT = dt.timedelta(minutes=20)
LOOKBACK = dt.timedelta(hours=48)
MAX_FALLBACKS = 5
SHA = re.compile(r"^[0-9a-f]{40}$")


def api(path, method="GET", payload=None):
    token = os.environ["GH_TOKEN"]
    url = BASE + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=25) as response:
        data = response.read()
        return json.loads(data) if data else None


def parse_time(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def latest_by_context(statuses, context):
    return next((s for s in statuses if s.get("context") == context), None)


def should_fallback(pr, statuses, repo, now):
    head = pr.get("head", {})
    sha = head.get("sha", "")
    if (pr.get("state") != "open" or not SHA.fullmatch(sha)
            or (head.get("repo") or {}).get("full_name") != repo):
        return False
    updated = parse_time(pr["updated_at"])
    if not WAIT <= now - updated <= LOOKBACK:
        return False
    primary = latest_by_context(statuses, "COM2 full policy")
    marker = latest_by_context(statuses, "COM2 hosted failover dispatch")
    if primary and primary.get("state") != "pending":
        return False
    if primary and now - parse_time(primary["created_at"]) < WAIT:
        return False
    if marker and marker.get("state") in ("pending", "success"):
        return False
    return True


def report(repo, sha, state, description):
    api(f"/repos/{repo}/statuses/{sha}", "POST", {
        "state": state, "context": "COM2 hosted failover dispatch",
        "description": description[:140],
    })


def main():
    repo = os.environ["GH_REPO"]
    assert re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo)
    now = dt.datetime.now(dt.timezone.utc)
    count = 0
    for page in range(1, 4):
        prs = api(f"/repos/{repo}/pulls?state=open&sort=updated&direction=desc&per_page=100&page={page}")
        if not prs:
            break
        for pr in prs:
            if count >= MAX_FALLBACKS:
                return
            if now - parse_time(pr["updated_at"]) > LOOKBACK:
                return
            sha = pr.get("head", {}).get("sha", "")
            if not SHA.fullmatch(sha):
                continue
            if (pr["head"].get("repo") or {}).get("full_name") != repo:
                continue
            statuses = api(f"/repos/{repo}/commits/{sha}/statuses?per_page=100")
            if not should_fallback(pr, statuses, repo, now):
                continue
            number = pr["number"]
            # Re-read current PR to stop if the head changed during the scan.
            current = api(f"/repos/{repo}/pulls/{number}")
            if (current["state"] != "open" or current["head"]["sha"] != sha
                    or current["head"]["repo"]["full_name"] != repo):
                continue
            report(repo, sha, "pending", "Hosted policy backup queued for stale COM2 status")
            try:
                api(f"/repos/{repo}/actions/workflows/operations-policy-guard-hosted-backup.yml/dispatches",
                    "POST", {"ref": "main", "inputs": {
                        "pr_number": str(number), "expected_sha": sha}})
            except (urllib.error.HTTPError, urllib.error.URLError):
                report(repo, sha, "failure", "Hosted backup dispatch request failed; retry eligible")
                raise
            print(f"COM2_HOSTED_FAILOVER_DISPATCHED PR={number} SHA={sha}")
            count += 1
        if len(prs) < 100:
            break
    print(f"COM2_HOSTED_FAILOVER_COUNT={count}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("COM2_FAILOVER_WATCH_ERROR=" + str(exc), file=sys.stderr)
        sys.exit(1)
