"""Trusted default-branch watchdog for B62 self-hosted job queue expiry."""
import datetime as dt
import os
import time

from com2_policy_failover_watch import api, parse_time

WAIT = dt.timedelta(minutes=5)
TARGET = "B62 tests-only changed pytest"


def eligible(run, pr, jobs, repo, now):
    """Only the original exact-head same-repo PR and its queued target."""
    head = pr.get("head") or {}
    if (run.get("event") != "pull_request"
            or run.get("run_attempt") != 1
            or run.get("status") not in ("queued", "in_progress")
            or (run.get("head_repository") or {}).get("full_name") != repo
            or pr.get("state") != "open"
            or (head.get("repo") or {}).get("full_name") != repo
            or not head.get("sha") or head.get("sha") != run.get("head_sha")):
        return False
    if any(j.get("conclusion") in ("failure", "timed_out", "action_required") for j in jobs):
        return False
    for job in jobs:
        if (job.get("name") != TARGET or job.get("status") != "queued"
                or not {"self-hosted", "padiem-com2-ci"} <= set(job.get("labels") or [])):
            continue
        try:
            queued_at = parse_time(job.get("created_at") or job["started_at"])
        except (KeyError, TypeError, ValueError, AttributeError):
            return False
        return now - queued_at >= WAIT
    return False


def recover(repo, run, now, request=api, pause=time.sleep):
    refs = run.get("pull_requests") or []
    if len(refs) != 1 or not refs[0].get("number"):
        return False
    base = f"/repos/{repo}"
    path = f"{base}/actions/runs/{run['id']}"
    pr_path = f"{base}/pulls/{refs[0]['number']}"
    pr = request(pr_path)
    jobs = request(path + "/attempts/1/jobs?per_page=100")["jobs"]
    if not eligible(run, pr, jobs, repo, now):
        return False
    # Re-read just before cancellation to avoid cancelling a started job.
    run = request(path)
    jobs = request(path + "/attempts/1/jobs?per_page=100")["jobs"]
    if not eligible(run, request(pr_path), jobs, repo, now):
        return False
    request(path + "/cancel", "POST")
    for _ in range(10):
        pause(3)
        status = request(path)
        if status.get("status") == "completed":
            head = request(pr_path)
            if (status.get("conclusion") == "cancelled"
                    and status.get("run_attempt") == 1
                    and head.get("state") == "open"
                    and (head.get("head") or {}).get("sha") == run["head_sha"]):
                request(path + "/rerun", "POST")
                print(f"B62 queue fallback: run {run['id']}")
                return True
            return False
    print(f"B62 queue fallback: cancellation not confirmed for {run['id']}; rerun manually")
    return False


def main():
    repo = os.environ["GH_REPO"]
    now = dt.datetime.now(dt.timezone.utc)
    path = f"/repos/{repo}/actions/workflows/b62-padiem-chat-ci.yml/runs"
    runs = []
    for status in ("queued", "in_progress"):
        runs.extend(api(path + f"?event=pull_request&status={status}&per_page=100")["workflow_runs"])
    for run in runs[:20]:
        recover(repo, run, now)


if __name__ == "__main__":
    main()
