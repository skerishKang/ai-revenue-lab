"""#3396 readonly CGI live auth canary's fail-closed policy tests."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/b66_3396_cgi_two_browser_readonly.py"
WORKFLOW = ROOT / ".github/workflows/b66-3396-cgi-two-browser-readonly.yml"
spec = importlib.util.spec_from_file_location("b66_cgi_readonly", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_request_budget():
    assert mod.self_test() == 0
    for unsafe in (
        "/api/padiem/b66/quotes",
        "/api/padiem/b66/quote/interpret",
        "/api/padiem/b66/quote/pdf",
        "/api/padiem/b66/saved-skills",
        "/api/padiem/b66/guided-draft",
        "/api/padiem/b66/company-profile",
    ):
        assert not mod.allow_http("POST", mod.ORIGIN + unsafe)
        assert not mod.allow_http("PUT", mod.ORIGIN + unsafe)
        assert not mod.allow_http("DELETE", mod.ORIGIN + unsafe)
    assert mod.allow_http("GET", mod.ORIGIN + mod.GUIDED)
    assert mod.AUTHORIZED_POSTS == frozenset({
        "/api/padiem/auth/password/login",
        "/api/padiem/auth/logout",
    })
    print("B66_3396_READONLY_REQUEST_BUDGET=PASS")


def test_only_exact_main_can_have_credential():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    expected = (
        "pull_request:", "workflow_dispatch:", "environment: production",
        "RUN_B66_3396_CGI_TWO_BROWSER_READONLY",
        "test \"${GITHUB_REF}\" = \"refs/heads/main\"",
        'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"',
        "persist-credentials: false",
        "secrets.B66_CGI_ALPHA_PASSWORD",
        "vars.B66_CGI_ALPHA_USERNAME",
        "source-contract",
        "live-cgi-readonly",
        "--authorized-live-readonly",
        "CUSTOMER_QUOTE_MUTATION=0",
        "MODEL_POSTS=0",
    )
    for marker in expected:
        assert marker in workflow, marker
    assert workflow.count("environment: production") == 1
    assert "pull_request_target:" not in workflow
    assert "actions: write" not in workflow
    assert workflow.index("live-cgi-readonly:") < workflow.index(
        "secrets.B66_CGI_ALPHA_PASSWORD"
    )
    print("B66_3396_GH_ACTIONS_CREDENTIAL_BOUNDARY=PASS")


def test_no_model_or_customer_writes():
    script = SCRIPT.read_text(encoding="utf-8")
    for value in (
        "MAX_MODEL_POSTS = 0", "MAX_PDF_POSTS = 0",
        "PRODUCTION_ROW_MUTATIONS = 0", "MAX_LOGINS = 2",
        'browser.new_context(', "api_snapshot(logged_in[0])",
        "api_snapshot(logged_in[1])", "logout(page)", "service_workers=\"block\"",
    ):
        assert value in script, value
    assert 'page.screenshot' not in script
    assert 'print(password)' not in script
    assert 'print(username)' not in script
    print("B66_3396_CGI_NO_MODEL_NO_ROW_MUTATION=PASS")


if __name__ == "__main__":
    test_request_budget()
    test_only_exact_main_can_have_credential()
    test_no_model_or_customer_writes()
    print("B66_3396_CGI_READONLY_CONTRACT=PASS")
