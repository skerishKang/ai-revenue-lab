"""Trusted hosted watchdog for missing/stale COM2 mobile QA (issue #5210)."""
import datetime as dt
import os
import sys
from com2_policy_failover_watch import api, parse_time, latest_by_context, SHA, LOOKBACK, WAIT

CONTEXT = "COM2 B62 mobile touch"
FINAL = "B62 mobile QA final"
MARKER = "COM2 mobile hosted fallback dispatch"
MAX = 4

def selected(files):
    if len(files) >= 100:
        return True
    paths = {x.get("filename", "") for x in files} | {x.get("previous_filename", "") for x in files}
    return any((p.startswith("apps/padiem-chat/") and not p.startswith("apps/padiem-chat/tests/"))
               or p == ".github/scripts/b62_mobile_touch_target_qa.py" for p in paths)

def reconcile(statuses):
    """Terminal marker state when a mobile QA verdict already resolved this head.

    A fallback that ends before its publish step leaves MARKER pending, and a pending
    marker suppresses eligibility forever. The verdict context is written by the hosted
    fallback and by the COM2 touch canary, so a terminal verdict on this exact SHA is
    the evidence that the dispatched work is over.
    """
    marker = latest_by_context(statuses, MARKER)
    if not marker or marker.get("state") != "pending":
        return None
    verdict = latest_by_context(statuses, FINAL)
    if not verdict or verdict.get("state") not in ("success", "failure"):
        return None
    if parse_time(verdict["created_at"]) < parse_time(marker["created_at"]):
        return None
    return verdict["state"]

def eligible(pr, statuses, repo, now):
    head = pr.get("head") or {}
    sha = head.get("sha", "")
    if pr.get("state") != "open" or not SHA.fullmatch(sha) or (head.get("repo") or {}).get("full_name") != repo:
        return False
    age = now - parse_time(pr["updated_at"])
    if not WAIT <= age <= LOOKBACK:
        return False
    marker = latest_by_context(statuses, MARKER)
    if marker and marker.get("state") in ("pending", "success"):
        return False
    primary = latest_by_context(statuses, CONTEXT)
    if primary:
        if primary.get("state") in ("success", "failure"):
            return False
        if now - parse_time(primary["created_at"]) < WAIT:
            return False
    return True

def report(repo, sha, state, description):
    api(f"/repos/{repo}/statuses/{sha}", "POST",
        {"state": state, "context": MARKER, "description": description[:140]})

def main():
    repo = os.environ["GH_REPO"]
    now = dt.datetime.now(dt.timezone.utc)
    count = 0
    for page in range(1, 4):
        prs = api(f"/repos/{repo}/pulls?state=open&sort=updated&direction=desc&per_page=100&page={page}")
        if not prs:
            break
        for pr in prs:
            if count >= MAX:
                return
            if now - parse_time(pr["updated_at"]) > LOOKBACK:
                return
            sha = (pr.get("head") or {}).get("sha", "")
            if not SHA.fullmatch(sha):
                continue
            statuses = api(f"/repos/{repo}/commits/{sha}/statuses?per_page=100")
            recovered = reconcile(statuses)
            if recovered:
                report(repo, sha, recovered,
                       "Mobile fallback marker reconciled from the terminal B62 mobile QA verdict")
                continue
            if not eligible(pr, statuses, repo, now):
                continue
            number = pr["number"]
            files = api(f"/repos/{repo}/pulls/{number}/files?per_page=100")
            if not selected(files):
                continue
            current = api(f"/repos/{repo}/pulls/{number}")
            if current["state"] != "open" or current["head"]["sha"] != sha or current["head"]["repo"]["full_name"] != repo:
                continue
            report(repo, sha, "pending", "Hosted mobile QA backup requested for stale COM2 result")
            try:
                api(f"/repos/{repo}/actions/workflows/b62-mobile-touch-hosted-fallback.yml/dispatches", "POST",
                    {"ref": "main", "inputs": {"pr_number": str(number), "expected_sha": sha}})
            except Exception:
                report(repo, sha, "failure", "Hosted mobile QA backup dispatch failed; retry eligible")
                raise
            print(f"COM2_MOBILE_HOSTED_FALLBACK_DISPATCHED PR={number} SHA={sha}")
            count += 1
        if len(prs) < 100:
            break
    print(f"COM2_MOBILE_HOSTED_FALLBACK_COUNT={count}")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"COM2_MOBILE_WATCH_ERROR={exc}", file=sys.stderr)
        raise
