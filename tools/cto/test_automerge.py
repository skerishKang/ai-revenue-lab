"""tools/cto/automerge.py 모의 시험 — 실제 GitHub(gh) 호출 없음.

subprocess(gh)를 FakeGh로 완전히 대체하고, 시간(_sleep/_now)도 가상 시계로 돌린다.
케이스: (1) 검사 미등록 방어, (2) 뒤처짐(update-branch) 복구와 3회 상한,
(3) 일시적 실패 재시도 vs 진짜 실패 즉시 종료, 정상 머지, 충돌 종료, --delay.
"""
import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import automerge


class R:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def ok():
    return R(0)


def bad(msg):
    return R(1, "", msg)


def checks(*name_bucket):
    return [{"name": n, "bucket": b} for n, b in name_bucket]


PASS = checks(("ci", "pass"))
FAILRUN = [{"conclusion": "FAILURE",
            "detailsUrl": "https://github.com/skerishKang/ai-revenue-lab/actions/runs/111/job/9"}]
G0 = ["123", "--grace", "0"]


class ScriptExhausted(BaseException):
    """시나리오 밖의 gh 호출 — except Exception에 안 걸리도록 BaseException."""


class FakeGh:
    """gh CLI 흉내. 스크립트의 마지막 항목은 소진될 때까지 반복된다."""

    def __init__(self, view=None, checks=None, merges=None, updates=None,
                 rollup=None, view_result=None):
        self.view = view or {"isDraft": False, "state": "OPEN", "files": []}
        self.view_result = view_result
        self.checks = list(checks or [])
        self.merges = list(merges or [])
        self.updates = list(updates or [])
        self.rollup = list(rollup or [])
        self.calls = []
        self.reruns = []
        self.clock = 0.0

    def _pop(self, lst, what):
        if not lst:
            raise ScriptExhausted("script exhausted: " + what)
        return lst.pop(0) if len(lst) > 1 else lst[0]

    def __call__(self, argv):
        a = [str(x) for x in argv]
        self.calls.append((self.clock, a))
        if a[:3] == ["gh", "pr", "view"]:
            if "statusCheckRollup" in a:
                return R(0, json.dumps({"statusCheckRollup": self.rollup}))
            if self.view_result is not None:
                return self.view_result
            return R(0, json.dumps(self.view))
        if a[:3] == ["gh", "pr", "checks"]:
            v = self._pop(self.checks, "checks")
            return v if isinstance(v, R) else R(0, json.dumps(v))
        if a[:3] == ["gh", "pr", "merge"]:
            return self._pop(self.merges, "merge")
        if a[:3] == ["gh", "pr", "update-branch"]:
            return self._pop(self.updates, "update-branch")
        if a[:2] == ["gh", "run"] and "rerun" in a:
            self.reruns.append(a)
            return R(0)
        if a[:3] == ["gh", "pr", "ready"]:
            return R(0)
        raise ScriptExhausted("unexpected call: " + " ".join(a))


def calls_of(fake, *prefix):
    return [c for c in fake.calls if c[1][:len(prefix)] == list(prefix)]


def run_tool(monkeypatch, fake, argv=None):
    monkeypatch.setattr(automerge, "run", fake)
    monkeypatch.setattr(automerge, "_sleep", lambda s: setattr(fake, "clock", fake.clock + s))
    monkeypatch.setattr(automerge, "_now", lambda: fake.clock)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = automerge.main(argv if argv is not None else ["123"])
    return code, buf.getvalue()


def last_line(out):
    lines = [l for l in out.splitlines() if l.strip()]
    return lines[-1]


# ── (1) 검사 미등록: 0개 상태에서는 절대 머지하지 않는다 ─────────────────────

def test_zero_checks_never_reaches_merge(monkeypatch):
    fake = FakeGh(checks=[[]])   # 검사가 끝내 등록되지 않음
    code, out = run_tool(monkeypatch, fake)
    assert code == 3
    assert last_line(out) == "RESULT: TIMEOUT"
    assert calls_of(fake, "gh", "pr", "merge") == []


def test_checks_registered_late_then_merged(monkeypatch):
    fake = FakeGh(checks=[[], checks(("ci", "pending")), PASS], merges=[ok()])
    code, out = run_tool(monkeypatch, fake, G0)
    assert code == 0
    assert last_line(out) == "RESULT: MERGED"
    merges = calls_of(fake, "gh", "pr", "merge")
    assert len(merges) == 1
    assert merges[0][1][-2:] == ["--squash", "--delete-branch"]


def test_default_grace_is_three_minutes():
    assert automerge.CHECK_GRACE_SECONDS == 180


def test_grace_blocks_merge_until_elapsed(monkeypatch):
    fake = FakeGh(checks=[PASS], merges=[ok()])   # 검사가 즉시 통과해도
    code, out = run_tool(monkeypatch, fake, ["123", "--grace", "180"])
    assert code == 0
    assert last_line(out) == "RESULT: MERGED"
    merges = calls_of(fake, "gh", "pr", "merge")
    assert len(merges) == 1
    assert merges[0][0] >= 180   # 시작 후 3분(가상 시계)이 지나고 나서 머지


# ── (2) 뒤처짐: update-branch 후 새 CI를 다시 기다린다 ──────────────────────

def test_out_of_date_updates_branch_and_rewaits_ci(monkeypatch):
    fake = FakeGh(checks=[PASS, checks(("ci", "pending")), PASS],
                  merges=[bad("Head branch is out of date. Pull the base branch"), ok()],
                  updates=[ok()])
    code, out = run_tool(monkeypatch, fake, G0)
    assert code == 0
    assert last_line(out) == "RESULT: MERGED"
    assert len(calls_of(fake, "gh", "pr", "update-branch")) == 1
    assert len(calls_of(fake, "gh", "pr", "merge")) == 2


def test_stale_fail_right_after_update_is_ignored(monkeypatch):
    # update-branch 직전 커밋의 허수 fail로 재실행/종료하지 않는다
    fake = FakeGh(checks=[PASS, checks(("ci", "fail")), PASS],
                  merges=[bad("Head branch is out of date"), ok()],
                  updates=[ok()],
                  rollup=FAILRUN)
    code, out = run_tool(monkeypatch, fake, G0)
    assert code == 0
    assert last_line(out) == "RESULT: MERGED"
    assert fake.reruns == []
    assert len(calls_of(fake, "gh", "pr", "merge")) == 2


def test_out_of_date_stops_after_three_updates(monkeypatch):
    fake = FakeGh(checks=[PASS], merges=[bad("Head branch is out of date")],
                  updates=[ok(), ok(), ok()])
    code, out = run_tool(monkeypatch, fake, G0)
    assert code == 4
    assert last_line(out) == "RESULT: OUT_OF_DATE (still behind after 3 update-branch runs)"
    assert len(calls_of(fake, "gh", "pr", "update-branch")) == 3
    assert len(calls_of(fake, "gh", "pr", "merge")) == 4


# ── (3) 일시적 실패는 재시도, 진짜 실패만 즉시 종료 ─────────────────────────

def test_policy_error_is_transient(monkeypatch):
    fake = FakeGh(checks=[PASS],
                  merges=[bad("base branch policy prohibits the merge"), ok()])
    code, out = run_tool(monkeypatch, fake, G0)
    assert code == 0
    assert last_line(out) == "RESULT: MERGED"
    assert calls_of(fake, "gh", "pr", "update-branch") == []
    assert len(calls_of(fake, "gh", "pr", "merge")) == 2


def test_network_error_is_transient(monkeypatch):
    fake = FakeGh(checks=[PASS],
                  merges=[bad('Post "https://api.github.com/graphql": network connection reset by peer'),
                          ok()])
    code, out = run_tool(monkeypatch, fake, G0)
    assert code == 0
    assert last_line(out) == "RESULT: MERGED"


def test_merge_retry_cap(monkeypatch):
    fake = FakeGh(checks=[PASS], merges=[bad("base branch policy prohibits the merge")])
    code, out = run_tool(monkeypatch, fake, G0)
    assert code == 5
    assert last_line(out).startswith("RESULT: MERGE_RETRY_EXHAUSTED")
    assert len(calls_of(fake, "gh", "pr", "merge")) == automerge.MERGE_RETRY_MAX


def test_ci_fail_reruns_once_then_stops(monkeypatch):
    fake = FakeGh(checks=[checks(("build", "fail")), checks(("build", "fail"))],
                  rollup=FAILRUN)
    code, out = run_tool(monkeypatch, fake, G0)
    assert code == 1
    assert last_line(out) == "RESULT: CI_FAIL (still failing after one rerun)"
    assert len(fake.reruns) == 1
    assert fake.reruns[0][-1] == "--failed"
    assert calls_of(fake, "gh", "pr", "merge") == []


def test_conflict_stops_immediately(monkeypatch):
    fake = FakeGh(checks=[PASS],
                  merges=[bad("Pull Request is not mergeable: the merge state is CONFLICTING")])
    code, out = run_tool(monkeypatch, fake, G0)
    assert code == 2
    assert last_line(out) == "RESULT: CONFLICTING (manual resolution needed)"
    assert len(calls_of(fake, "gh", "pr", "merge")) == 1
    assert calls_of(fake, "gh", "pr", "update-branch") == []


# ── 새 옵션과 시작 단계 ─────────────────────────────────────────────────────

def test_delay_sleeps_before_first_gh_call(monkeypatch):
    fake = FakeGh(checks=[PASS], merges=[ok()])
    code, out = run_tool(monkeypatch, fake, ["123", "--delay", "150", "--grace", "0"])
    assert code == 0
    assert last_line(out) == "RESULT: MERGED"
    assert fake.calls[0][0] == 150   # 첫 gh 호출 전에 150초(가상) 대기


def test_draft_becomes_ready(monkeypatch):
    fake = FakeGh(view={"isDraft": True, "state": "OPEN", "files": []},
                  checks=[PASS], merges=[ok()])
    code, out = run_tool(monkeypatch, fake, G0)
    assert code == 0
    assert len(calls_of(fake, "gh", "pr", "ready")) == 1


def test_already_merged_and_closed(monkeypatch):
    fake = FakeGh(view={"isDraft": False, "state": "MERGED", "files": []})
    code, out = run_tool(monkeypatch, fake, G0)
    assert code == 0
    assert last_line(out).startswith("RESULT: MERGED")
    assert calls_of(fake, "gh", "pr", "checks") == []

    fake2 = FakeGh(view={"isDraft": False, "state": "CLOSED", "files": []})
    code2, out2 = run_tool(monkeypatch, fake2, G0)
    assert code2 == 7
    assert last_line(out2) == "RESULT: PR_CLOSED"


def test_startup_error(monkeypatch):
    fake = FakeGh(view_result=R(1, "", "boom"))
    code, out = run_tool(monkeypatch, fake, G0)
    assert code == 6
    assert last_line(out) == "RESULT: STARTUP_ERROR"


def test_classify_merge_error():
    assert automerge.classify_merge_error("the merge state is CONFLICTING")[0] == "CONFLICT"
    assert automerge.classify_merge_error("Head branch is out of date")[0] == "OUT_OF_DATE"
    assert automerge.classify_merge_error("the merge state is BEHIND")[0] == "OUT_OF_DATE"
    assert automerge.classify_merge_error("base branch policy prohibits the merge")[0] == "POLICY"
    assert automerge.classify_merge_error("connection reset by peer")[0] == "NETWORK"
    assert automerge.classify_merge_error("weird unknown thing")[0] == "OTHER"
