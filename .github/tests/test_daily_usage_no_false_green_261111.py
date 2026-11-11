"""#7440 4번 계약: 실사용 점검은 아무 흐름도 검사하지 않고 success 로 끝나지
않는다(2026-11-11).

#7449 가 QA 계정을 용도별로 분리하면서 daily_real_usage_check.py 가 읽는 env
이름은 QA_SMOKE_USERNAME / QA_SMOKE_PASSWORD 가 됐다. 워크플로가 옛 이름
(B66_CGI_ALPHA_*)만 넘기면 8흐름이 전부 SKIPPED qa_credential_missing 으로
끝나는데 결론은 success 였다 — 매일 밤 아무 것도 검사하지 않는 거짓 녹색.
이 파일은 세 가지를 고정한다:

  1. 스크립트가 읽는 env 이름은 QA_SMOKE_* 다(이름이 바뀌면 이 시험이 깨진다).
  2. 실제로 검사한 흐름(PASS + FAIL)이 0개면 실행 결론은 FAIL 이고 0이 아닌
     종료 코드로 끝난다. 흐름 기록 자체는 #6720 대로 SKIPPED 로 남는다.
  3. 워크플로는 QA_SMOKE_* 시크릿을 스크립트가 읽는 이름으로 그대로 넘기고,
     자격 증명이 없는 단계도 success 로 끝나지 않는다.
  4. 브라우저 점검(daily_usage_browser_checks)도 QA_SMOKE_* 만 읽는다 —
     B66_CGI_ALPHA_* 를 직접 읽던 4곳(공통 로그인 흐름·레거시 세션 심기)이
     남아 browser_shared_login 이 매번 SKIPPED 됐다(#7440 후속).

실행:
    python -m pytest .github/tests/test_daily_usage_no_false_green_261111.py -q
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CHECK = HERE.parent / "scripts" / "daily_real_usage_check.py"
WORKFLOW = HERE.parent / "workflows" / "daily-real-usage-check.yml"


def _load_fresh_smoke():
    """smoke 모듈을 새로 load 한다.

    post_deploy_ai_answer_check.py 는 import 때 smoke 모듈 전역을 QA_DEPLOY_*
    로 바꾼다(.github/scripts/post_deploy_ai_answer_check.py:31-32). 세션에서
    그게 먼저 load 되면 캐시된 모듈의 상수가 이미 바뀌어 있으므로, 이 시험은
    매번 새로 load 한 사본으로 관찰한다.
    """
    spec = importlib.util.spec_from_file_location(
        "post_deploy_real_chat_smoke",
        HERE.parent / "scripts" / "post_deploy_real_chat_smoke.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_module():
    # daily 스크립트가 import 하는 smoke 모듈도 새 사본으로 고정한다(위 주석).
    sys.modules["post_deploy_real_chat_smoke"] = _load_fresh_smoke()
    spec = importlib.util.spec_from_file_location("daily_real_usage_check", CHECK)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_browser_module():
    spec = importlib.util.spec_from_file_location(
        "daily_usage_browser_checks", HERE.parent / "scripts" / "daily_usage_browser_checks.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_the_script_reads_the_qa_smoke_env_names(monkeypatch):
    """#7449 뒤 스크립트가 읽는 이름은 smoke 모듈의 QA_SMOKE_* 다."""
    for name in ("QA_SMOKE_USERNAME", "QA_SMOKE_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    mod = _load_module()
    fresh_smoke = _load_fresh_smoke()

    # 소스 계약: smoke 모듈이 QA_SMOKE_* 를 정의하고 daily 스크립트가 그 이름을
    # import 해 쓴다(모듈 전역은 다른 스크립트가 바꿀 수 있으니 소스로 고정).
    smoke_source = (HERE.parent / "scripts" / "post_deploy_real_chat_smoke.py").read_text(
        encoding="utf-8")
    assert 'QA_USERNAME_ENV = "QA_SMOKE_USERNAME"' in smoke_source
    assert 'QA_PASSWORD_ENV = "QA_SMOKE_PASSWORD"' in smoke_source
    assert (fresh_smoke.QA_USERNAME_ENV, fresh_smoke.QA_PASSWORD_ENV) == (
        "QA_SMOKE_USERNAME", "QA_SMOKE_PASSWORD")

    # 행동 계약: QA_SMOKE_* 가 없으면 자격 판정은 SKIPPED 다.
    assert mod._credential_verdict() == ("SKIPPED", "qa_credential_missing")


def test_run_verdict_fails_when_nothing_was_checked():
    """전부 SKIPPED 인 실행(checked=0)은 PASS 가 아니라 FAIL 이다."""
    mod = _load_module()
    assert mod.run_verdict(failed=0, checked=8) == "PASS"
    assert mod.run_verdict(failed=1, checked=7) == "FAIL"
    assert mod.run_verdict(failed=0, checked=0) == "FAIL"
    assert mod.run_verdict(failed=0, checked=-1) == "FAIL"


def test_main_returns_nonzero_when_every_flow_is_skipped(tmp_path, monkeypatch, capsys):
    """자격 증명이 없으면 8흐름이 전부 SKIPPED 고 결론은 실패다(#6720 + #7440)."""
    mod = _load_module()
    for name in ("QA_SMOKE_USERNAME", "QA_SMOKE_PASSWORD",
                 "B66_CGI_ALPHA_USERNAME", "B66_CGI_ALPHA_PASSWORD",
                 "PADIEM_QA_PC_TOKEN", "GITHUB_RUN_ID", "GITHUB_STEP_SUMMARY",
                 "GITHUB_REPOSITORY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PADIEM_USAGE_METRICS_PATH", str(tmp_path / "metrics.json"))

    exit_code = mod.main()

    assert exit_code == 1
    output = capsys.readouterr().out
    assert "USAGE_CHECK verdict=FAIL" in output
    assert "checked=0" in output
    assert "skipped=8" in output
    # 흐름 기록은 #6720 대로 SKIPPED 로 남는다(수집기가 코드를 읽는다).
    assert "USAGE_FLOW name=chat_turn verdict=SKIPPED" in output
    assert output.count("code=qa_credential_missing") >= 8


def test_workflow_passes_the_qa_smoke_pair_the_script_reads():
    """워크플로 env 는 스크립트가 읽는 QA_SMOKE_* 이고 옛 이름이 남지 않는다."""
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = document["jobs"]["real-usage"]
    env = job["env"]

    assert env["QA_SMOKE_USERNAME"] == "${{ secrets.QA_SMOKE_USERNAME }}"
    assert env["QA_SMOKE_PASSWORD"] == "${{ secrets.QA_SMOKE_PASSWORD }}"
    rendered = WORKFLOW.read_text(encoding="utf-8")
    assert "B66_CGI_ALPHA" not in rendered, (
        "the workflow must not pass env names the script never reads — that "
        "left every nightly run SKIPPED qa_credential_missing yet success")

    steps = {step.get("name"): step for step in job["steps"] if step.get("name")}
    absent = steps["Fail when the QA credential is absent"]
    assert "exit 1" in absent["run"], (
        "an absent credential must not end the workflow green")
    run_step = steps["Run the eight real-usage flows"]
    assert "env.QA_SMOKE_USERNAME != ''" in run_step["if"]
    assert "env.QA_SMOKE_PASSWORD != ''" in run_step["if"]


def test_browser_checks_read_only_the_qa_smoke_env_names():
    """브라우저 점검도 QA_SMOKE_* 만 읽는다(#7440 후속).

    daily_usage_browser_checks.py 가 B66_CGI_ALPHA_* 를 직접 읽던 4곳이 남아
    워크플로가 넘기지 않는 이름을 기다렸고, browser_shared_login 은 매번
    SKIPPED qa_credential_missing 이 됐다. 소스 계약으로 이름을 고정한다.
    """
    source = (HERE.parent / "scripts" / "daily_usage_browser_checks.py").read_text(
        encoding="utf-8")
    assert 'os.environ.get("B66_CGI_ALPHA_' not in source, (
        "the browser checks must not read env names the workflow never passes")
    assert 'QA_USERNAME_ENV = "QA_SMOKE_USERNAME"' in source
    assert 'QA_PASSWORD_ENV = "QA_SMOKE_PASSWORD"' in source


def test_shared_login_flow_skips_on_missing_qa_smoke_pair(monkeypatch):
    """QA_SMOKE_* 가 없으면 browser_shared_login 은 건너뛴다(#6720).

    browser=None 로 부른다. 자격 검사가 브라우저보다 먼저이므로 이 시험은
    브라우저를 만지지 않는다.
    """
    mod = _load_browser_module()
    for name in ("QA_SMOKE_USERNAME", "QA_SMOKE_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    flow = mod.BrowserFlowResult("browser_shared_login")

    mod._run_shared_login_flow(None, mod.CHAT_URL, Path("/tmp"), flow, "", [])

    assert (flow.verdict, flow.code) == ("SKIPPED", "qa_credential_missing")


def test_shared_login_flow_does_not_read_the_old_env_names(monkeypatch):
    """옛 이름(B66_CGI_ALPHA_*)만 있으면 흐름은 건너뛴다 — 더는 읽지 않는다.

    옛 이름을 읽는다면 자격이 '있는' 것으로 나아가 브라우저(None)를 만지려
    했을 것이다. qa_credential_missing 으로 건너뛰는 것이 이름을 안 읽는
    관찰 증거다.
    """
    mod = _load_browser_module()
    for name in ("QA_SMOKE_USERNAME", "QA_SMOKE_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("B66_CGI_ALPHA_USERNAME", "qa@example.com")
    monkeypatch.setenv("B66_CGI_ALPHA_PASSWORD", "dummy-not-a-secret")
    flow = mod.BrowserFlowResult("browser_shared_login")

    mod._run_shared_login_flow(None, mod.CHAT_URL, Path("/tmp"), flow, "", [])

    assert (flow.verdict, flow.code) == ("SKIPPED", "qa_credential_missing")
