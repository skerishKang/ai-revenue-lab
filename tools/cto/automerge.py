"""CTO PR 자동 머지 도구 (squash 머지 + 브랜치 삭제).

흐름: 시작 지연(--delay) → PR 확인(드래프트면 ready) → CI 검사 폴링(40초 주기) →
실패 잡 1회 재실행 → 검사가 1개 이상 등록되고 전부 끝났으면 squash 머지.

2026-11-01 안정화 (#6556 / #6557 / #6560 사례 반영):
- 검사 미등록 방어: PR 직후에는 검사가 0개라 "pending=0 fail=0"으로 보여 바로 머지하다
  "base branch policy prohibits the merge"로 실패했다. → 검사가 1개 이상 등록되고 전부
  끝날 때까지 기다리고, 시작 후 CHECK_GRACE_SECONDS(기본 180초, --grace) 동안은
  검사가 0개여도(또는 일찍 통과해도) 머지하지 않는다.
- 뒤처짐 복구: 머지가 "Head branch is out of date"/"BEHIND"로 실패하면
  `gh pr update-branch`를 실행하고 새 CI를 다시 기다린다(최대 UPDATE_BRANCH_MAX회).
- 일시적 실패 재시도: 정책(POLICY)·네트워크(NETWORK) 오류는 재시도한다.
  충돌(CONFLICTING)과 재실행 1회 후에도 실패한 CI(CI_FAIL)만 즉시 종료하고
  이유를 한 줄로 출력한다. update-branch 직후의 허수 fail은 2폴링 동안 무시한다.

모든 종료 경로는 마지막 줄에 "RESULT: ..."를 출력한다(형식 유지).
gh 호출은 test_automerge.py에서 subprocess 모의로 검증한다(실제 GitHub 호출 금지).
"""
import argparse
import json
import subprocess
import sys
import time

REPO = "skerishKang/ai-revenue-lab"
POLL_INTERVAL = 40          # 초 — 기존 동작 유지: 검사 확인 주기
MAX_POLLS = 70              # 폴링 한도 (40초 × 70 ≈ 47분 → RESULT: TIMEOUT)
CHECK_GRACE_SECONDS = 180   # 시작 후 이 시간 동안은 0개·통과 여부와 무관하게 머지 금지
UPDATE_BRANCH_MAX = 3       # "out of date" → gh pr update-branch 최대 횟수
UPDATE_SETTLE_POLLS = 2     # update-branch 직후 남아 있는 허수 fail을 무시하는 폴링 수
MERGE_RETRY_MAX = 8         # 일시적 머지 실패를 포함한 총 머지 시도 상한

CONFLICT_MARKERS = ("conflict", "dirty")
OUT_OF_DATE_MARKERS = ("out of date", "out-of-date", "not up-to-date", "behind")
POLICY_MARKERS = ("policy", "required status", "required check",
                  "branch protection", "protected branch")
NETWORK_MARKERS = ("network", "timed out", "timeout", "connection", "refused",
                   "reset by peer", "rate limit", "server error", "http 5",
                   "deadline exceeded", "tls", "eof", "aborted", "curl",
                   "unexpected error")


def run(a):
    return subprocess.run(a, capture_output=True, text=True)


def _sleep(sec):
    time.sleep(sec)


def _now():
    return time.monotonic()


def _one_line(s):
    return " ".join((s or "").split())


def classify_merge_error(stderr):
    """gh 머지/갱신 오류를 (종류, 한 줄 사유)로 분류한다."""
    s = _one_line(stderr).lower()
    if any(m in s for m in CONFLICT_MARKERS):
        return "CONFLICT", s
    if any(m in s for m in OUT_OF_DATE_MARKERS):
        return "OUT_OF_DATE", s
    if any(m in s for m in POLICY_MARKERS):
        return "POLICY", s
    if any(m in s for m in NETWORK_MARKERS):
        return "NETWORK", s
    return "OTHER", s


def run_json(args, tries=3, gap=15):
    """gh 호출을 몇 번 시도해 JSON을 돌려준다. 시작 단계 네트워크 흔들림 방어용."""
    last = ""
    for t in range(tries):
        r = run(args)
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
        last = _one_line(getattr(r, "stderr", "") or getattr(r, "stdout", "")
                         or f"exit={getattr(r, 'returncode', '?')}")
        if t < tries - 1:
            _sleep(gap)
    raise RuntimeError(f"gh call failed ({' '.join(str(x) for x in args[:4])}): {last}")


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(
        description="CTO PR automerge: wait for CI, squash merge, delete branch")
    ap.add_argument("pr", help="PR number")
    ap.add_argument("--delay", type=int, default=0, metavar="SEC",
                    help="sleep SEC seconds before starting (replaces CTO's Start-Sleep)")
    ap.add_argument("--grace", type=int, default=CHECK_GRACE_SECONDS, metavar="SEC",
                    help="no-merge grace period after start (default 180)")
    a = ap.parse_args(argv)
    pr = str(a.pr)

    if a.delay > 0:
        print(f"start delay: {a.delay}s", flush=True)
        _sleep(a.delay)

    try:
        v = run_json(["gh", "pr", "view", pr, "--repo", REPO, "--json", "isDraft,files,state"])
    except Exception as e:
        print(f"PR view failed: {_one_line(str(e))}", flush=True)
        print("RESULT: STARTUP_ERROR", flush=True)
        return 6
    print("state", v.get("state"), "draft", v.get("isDraft"), flush=True)
    for f in v.get("files", []):
        print("  ", f.get("path"), f"+{f.get('additions', 0)}/-{f.get('deletions', 0)}", flush=True)
    st = v.get("state")
    if st == "MERGED":
        print("RESULT: MERGED (already merged)", flush=True)
        return 0
    if st == "CLOSED":
        print("RESULT: PR_CLOSED", flush=True)
        return 7
    if v.get("isDraft"):
        run(["gh", "pr", "ready", pr, "--repo", REPO])

    started = _now()
    rerun_done = False   # 현재 CI 라운드에서 실패 잽 재실행을 이미 했는가
    updates = 0          # update-branch 성공 횟수
    merge_attempts = 0   # 총 머지 시도 횟수
    settle = 0           # update-branch 직후 무시할 허수 fail 폴링 수

    for i in range(MAX_POLLS):
        try:
            data = json.loads(run(["gh", "pr", "checks", pr, "--repo", REPO,
                                   "--json", "name,bucket"]).stdout)
        except Exception:
            print(f"[{i}] checks query failed, retrying", flush=True)
            _sleep(POLL_INTERVAL)
            continue
        pend = [c for c in data if c.get("bucket") == "pending"]
        fail = [c for c in data if c.get("bucket") == "fail"]

        if not data:
            # 검사 미등록 방어: 1개 이상 등록될 때까지 절대 머지하지 않는다.
            left = max(0, int(a.grace - (_now() - started)))
            print(f"[{i}] checks=0 (waiting for CI registration, grace left {left}s)", flush=True)
            _sleep(POLL_INTERVAL)
            continue
        if pend:
            print(f"[{i}] pending={len(pend)} fail={len(fail)}", flush=True)
            _sleep(POLL_INTERVAL)
            continue
        if fail:
            if settle > 0:
                settle -= 1
                print(f"[{i}] fail shown just after update-branch, "
                      f"ignoring for {settle} more polls", flush=True)
                _sleep(POLL_INTERVAL)
                continue
            print("FAILED:", [c.get("name") for c in fail], flush=True)
            if not rerun_done:
                try:
                    roll = run_json(["gh", "pr", "view", pr, "--repo", REPO,
                                     "--json", "statusCheckRollup"], tries=2, gap=10).get(
                        "statusCheckRollup", [])
                    ids = {c["detailsUrl"].split("/actions/runs/")[1].split("/")[0]
                           for c in roll
                           if c.get("conclusion") == "FAILURE"
                           and "/actions/runs/" in (c.get("detailsUrl") or "")}
                    for r in ids:
                        print("rerun", r,
                              run(["gh", "run", "rerun", r, "--repo", REPO, "--failed"]).returncode,
                              flush=True)
                except Exception as e:
                    print("rerun lookup failed:", _one_line(str(e)), flush=True)
                rerun_done = True
                _sleep(60)
                continue
            print("RESULT: CI_FAIL (still failing after one rerun)", flush=True)
            return 1

        grace_left = int(a.grace - (_now() - started))
        if grace_left > 0:
            print(f"[{i}] all checks done but within start grace "
                  f"({grace_left}s left), merge postponed", flush=True)
            _sleep(POLL_INTERVAL)
            continue

        merge_attempts += 1
        m = run(["gh", "pr", "merge", pr, "--repo", REPO, "--squash", "--delete-branch"])
        if m.returncode == 0:
            print("RESULT: MERGED", flush=True)
            return 0
        kind, detail = classify_merge_error(m.stderr)
        print(f"merge attempt {merge_attempts} failed [{kind}]: {detail}", flush=True)

        if kind == "CONFLICT":
            print("RESULT: CONFLICTING (manual resolution needed)", flush=True)
            return 2
        if kind == "OUT_OF_DATE":
            if updates >= UPDATE_BRANCH_MAX:
                print(f"RESULT: OUT_OF_DATE (still behind after {updates} update-branch runs)",
                      flush=True)
                return 4
            u = run(["gh", "pr", "update-branch", pr, "--repo", REPO])
            if u.returncode == 0:
                updates += 1
                rerun_done = False          # 새 CI 라운드: 실패 잽 재실행 1회를 다시 쓴다
                settle = UPDATE_SETTLE_POLLS
                print(f"update-branch ok ({updates}/{UPDATE_BRANCH_MAX}), "
                      f"waiting for fresh CI", flush=True)
            else:
                ukind, udetail = classify_merge_error(u.stderr)
                if ukind == "CONFLICT":
                    print("RESULT: CONFLICTING (conflict while updating branch)", flush=True)
                    return 2
                print(f"update-branch failed, will retry: {udetail}", flush=True)

        if merge_attempts >= MERGE_RETRY_MAX:
            print(f"RESULT: MERGE_RETRY_EXHAUSTED "
                  f"(gave up after {merge_attempts} attempts, last={kind})", flush=True)
            return 5
        _sleep(POLL_INTERVAL)

    print("RESULT: TIMEOUT", flush=True)
    return 3


if __name__ == "__main__":
    sys.exit(main())
