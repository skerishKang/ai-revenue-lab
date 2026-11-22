"""Trusted default-branch watchdog for B62 self-hosted queue and browser readiness."""
import datetime as dt
import os
import time

from com2_policy_failover_watch import api, parse_time

WAIT = dt.timedelta(minutes=5)
TARGET = "B62 tests-only changed pytest"
CHROMIUM_PREP = "Prepare Chromium headless shell"
FAILURES = {"failure", "timed_out", "action_required"}
LOOKBACK = dt.timedelta(hours=48)


def same_head(run, pr, repo):
    head = pr.get("head") or {}
    return (run.get("event") == "pull_request"
            and run.get("run_attempt") == 1
            and (run.get("head_repository") or {}).get("full_name") == repo
            and pr.get("state") == "open"
            and (head.get("repo") or {}).get("full_name") == repo
            and bool(head.get("sha"))
            and head["sha"] == run.get("head_sha"))


def is_self_hosted_target(job):
    return (job.get("name") == TARGET
            and {"self-hosted", "padiem-com2-ci"} <= set(job.get("labels") or []))


def eligible(run, pr, jobs, repo, now):
    """Only the original exact-head same-repo PR and its queued target."""
    if (not same_head(run, pr, repo)
            or run.get("status") not in ("queued", "in_progress")
            or any(j.get("conclusion") in FAILURES for j in jobs)):
        return False
    for job in jobs:
        if not is_self_hosted_target(job) or job.get("status") != "queued":
            continue
        try:
            queued_at = parse_time(job.get("created_at") or job["started_at"])
        except (KeyError, TypeError, ValueError, AttributeError):
            return False
        return now - queued_at >= WAIT
    return False


def browser_failure(run, pr, jobs, repo):
    """Retry infrastructure preparation only, never a real pytest failure."""
    if (not same_head(run, pr, repo) or run.get("status") != "completed"
            or run.get("conclusion") != "failure"):
        return False
    failed = [j for j in jobs if j.get("conclusion") in FAILURES]
    if any(j.get("name") not in (TARGET, "b62-test") for j in failed):
        return False
    for job in failed:
        if not is_self_hosted_target(job) or job.get("conclusion") != "failure":
            continue
        steps = job.get("steps") or []
        prep = [step for step in steps if step.get("name") == CHROMIUM_PREP]
        if len(prep) != 1 or prep[0].get("conclusion") != "failure":
            continue
        # A failed pytest (or any other failed step) is not infrastructure failover.
        if any(step.get("name") != CHROMIUM_PREP
               and step.get("conclusion") in FAILURES for step in steps):
            continue
        return True
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
    if browser_failure(run, pr, jobs, repo):
        # No cancellation: preparation already failed. Recheck attempt and PR
        # head immediately before the failed-job rerun, which uses hosted Ubuntu.
        run = request(path)
        jobs = request(path + "/attempts/1/jobs?per_page=100")["jobs"]
        if not browser_failure(run, request(pr_path), jobs, repo):
            return False
        request(path + "/rerun-failed-jobs", "POST")
        print(f"B62 Chromium readiness fallback: run {run['id']}")
        return True
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
    for status in ("queued", "in_progress", "failure"):
        # Limit completed-failure scans to recent runs. Older workflow
        # definitions lacked the marker step and must not be retried.
        since = (now - LOOKBACK).strftime("%Y-%m-%d")
        runs.extend(api(path + f"?event=pull_request&status={status}&created=%3E%3D{since}&per_page=100")["workflow_runs"])
    candidates = [
        run for run in runs
        if run.get("run_attempt") == 1
        and (run.get("head_repository") or {}).get("full_name") == repo
    ]
    # Oldest assignments first; bound each scheduled sweep's cancellation wait.
    recovered = 0
    # Check active queues first, then newest completed failures rather than
    # repeatedly scanning an old unrelated failure before fresh candidates.
    active = sorted((r for r in candidates if r.get("status") != "completed"),
                    key=lambda item: item.get("created_at", ""))
    failed = sorted((r for r in candidates if r.get("status") == "completed"),
                    key=lambda item: item.get("created_at", ""), reverse=True)
    for run in active[:20] + failed[:20]:
        if recover(repo, run, now):
            recovered += 1
            if recovered >= 3:
                break


if __name__ == "__main__":
    main()
