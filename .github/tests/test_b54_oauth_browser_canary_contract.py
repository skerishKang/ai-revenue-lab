"""Provider-free tests for the bounded readonly OAuth canary contract."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from b54_oauth_browser_canary_contract import (  # noqa: E402
    CANARY_REVIEWED_READONLY_SCOPES,
    DURABLE_REPLAY_AUTHORITY,
    EXTERNAL_RUNTIME_METADATA_REDACTION,
    GMAIL_READONLY_SCOPE,
    GOOGLE_DRIVE_READONLY_SCOPE,
    READONLY_SCOPE_SUFFIX,
    CanaryConnectorScope,
    CanaryContractError,
    ConsentPollStatus,
    ConnectRequestPolicy,
    OAuthCanaryAttempt,
    poll_consent_target,
    project_transition_location,
    reviewed_canary_scope,
)

DRIVE_SCOPE = reviewed_canary_scope("google-drive")
GMAIL_SCOPE = reviewed_canary_scope("gmail")


def test_second_begin_fails_before_action() -> None:
    attempt = OAuthCanaryAttempt()
    attempt.start(DRIVE_SCOPE)
    called = []
    with pytest.raises(CanaryContractError):
        attempt.start(DRIVE_SCOPE)
    assert called == []


@pytest.mark.parametrize("action_name, prior_actions", [
    ("ticket_post", ("ticket_post",)),
    ("connect_post", ("ticket_post", "connect_post")),
    ("consent", ("ticket_post", "connect_post", "consent")),
    ("callback", ("ticket_post", "connect_post", "consent", "callback")),
])
def test_each_action_duplicate_is_blocked_immediately(action_name: str, prior_actions: tuple[str, ...]) -> None:
    attempt = OAuthCanaryAttempt()
    attempt.start(DRIVE_SCOPE)
    calls: list[str] = []
    callbacks = {
        "ticket_post": lambda: calls.append("ticket_post"),
        "connect_post": lambda policy: calls.append("connect_post"),
        "consent": lambda: calls.append("consent"),
        "callback": lambda: calls.append("callback"),
    }
    for prior in prior_actions:
        getattr(attempt, prior)(callbacks[prior])
    with pytest.raises(CanaryContractError):
        getattr(attempt, action_name)(callbacks[action_name])
    assert calls == list(prior_actions)


def test_invalid_order_fails_before_action() -> None:
    attempt = OAuthCanaryAttempt()
    attempt.start(DRIVE_SCOPE)
    called = []
    with pytest.raises(CanaryContractError):
        attempt.connect_post(lambda: called.append("connect"))
    assert called == []


def test_failed_action_consumes_budget_and_cannot_retry() -> None:
    attempt = OAuthCanaryAttempt()
    attempt.start(DRIVE_SCOPE)
    calls = []

    def fail_once() -> None:
        calls.append("ticket")
        raise RuntimeError("failed")

    with pytest.raises(RuntimeError):
        attempt.ticket_post(fail_once)
    with pytest.raises(CanaryContractError):
        attempt.ticket_post(lambda: calls.append("retry"))
    with pytest.raises(CanaryContractError):
        attempt.connect_post(lambda policy: calls.append("connect"))
    assert calls == ["ticket"]
    assert attempt.counts["ticket_post"] == 1
    assert attempt.status.value == "failed"


@pytest.mark.parametrize("failed_action, blocked_action", [
    ("connect_post", "consent"),
    ("consent", "callback"),
    ("callback", "callback"),
])
def test_failed_later_action_is_terminal_and_blocks_followup(failed_action: str, blocked_action: str) -> None:
    attempt = OAuthCanaryAttempt()
    attempt.start(DRIVE_SCOPE)
    attempt.ticket_post(lambda: None)

    if failed_action in {"consent", "callback"}:
        attempt.connect_post(lambda policy: None)
    if failed_action == "callback":
        attempt.consent(lambda: None)

    def fail(*_args: object) -> None:
        raise RuntimeError(failed_action)

    with pytest.raises(RuntimeError):
        getattr(attempt, failed_action)(fail)
    with pytest.raises(CanaryContractError):
        if blocked_action == "callback":
            attempt.callback(lambda: None)
        else:
            attempt.consent(lambda: None)
    assert attempt.status.value == "failed"


def test_connect_is_structurally_single_call_with_redirect_and_retry_zero() -> None:
    attempt = OAuthCanaryAttempt()
    attempt.start(DRIVE_SCOPE)
    calls = []
    attempt.ticket_post(lambda: calls.append("ticket"))
    received_policies = []

    def connect(policy: ConnectRequestPolicy) -> None:
        calls.append("connect")
        received_policies.append(policy)

    attempt.connect_post(connect)
    assert calls == ["ticket", "connect"]
    assert received_policies == [ConnectRequestPolicy(max_redirects=0, max_retries=0)]
    assert attempt.connect_policy == ConnectRequestPolicy(max_redirects=0, max_retries=0)
    with pytest.raises(CanaryContractError):
        ConnectRequestPolicy(max_redirects=1)
    with pytest.raises(CanaryContractError):
        ConnectRequestPolicy(max_retries=1)


def test_commit_is_not_ready_and_later_bounded_poll_finds_target() -> None:
    now = [0.0]
    seen = [False, False, True]
    result = poll_consent_target(
        lambda: seen.pop(0),
        timeout_seconds=2,
        interval_seconds=0.5,
        clock=lambda: now[0],
        wait=lambda seconds: now.__setitem__(0, now[0] + seconds),
    )
    assert result.status is ConsentPollStatus.READY
    assert result.polls == 3


def test_consent_poll_returns_explicit_timeout() -> None:
    now = [0.0]
    result = poll_consent_target(
        lambda: False,
        timeout_seconds=1,
        interval_seconds=0.5,
        clock=lambda: now[0],
        wait=lambda seconds: now.__setitem__(0, now[0] + seconds),
    )
    assert result.status is ConsentPollStatus.TIMEOUT
    assert result.polls == 3


def test_safe_projection_excludes_oauth_query_and_raw_material() -> None:
    attempt = OAuthCanaryAttempt()
    report = attempt.safe_report(
        status="connected",
        transition_url="https://oauth.example.test/callback?state=opaque&code=single-use#fragment",
        presence={"ticket": True, "binding_ref": True},
    ).as_dict()
    assert report["transition_location"] == "https://oauth.example.test/callback"
    rendered = repr(report)
    for forbidden in ("state=", "code=", "single-use", "ticket_value", "binding_value", "actor_value"):
        assert forbidden not in rendered
    assert all(report[key] is False for key in report if key.startswith("raw_"))


@pytest.mark.parametrize("kwargs", [
    {"status": "token=secret"},
    {"status": "connected", "error_code": "code=secret"},
    {"status": "connected", "presence": {"raw-ticket-value": True}},
    {"status": "connected", "presence": {"ticket": "raw"}},
])
def test_safe_projection_rejects_arbitrary_diagnostic_data(kwargs: dict[str, object]) -> None:
    with pytest.raises(CanaryContractError):
        OAuthCanaryAttempt().safe_report(**kwargs)


def test_safe_projection_rejects_non_location_transition_url() -> None:
    with pytest.raises(CanaryContractError):
        project_transition_location("https://oauth.example.test?state=only")
    with pytest.raises(CanaryContractError):
        project_transition_location("https://user:password@example.test/callback")


def test_runtime_and_durable_authority_boundaries_are_explicit() -> None:
    assert EXTERNAL_RUNTIME_METADATA_REDACTION == "UNRESOLVED"
    assert DURABLE_REPLAY_AUTHORITY == "SERVER_SIDE_EXISTING"


def test_reviewed_scope_table_is_readonly_and_limited_to_reviewed_connectors() -> None:
    assert set(CANARY_REVIEWED_READONLY_SCOPES) == {"google-drive", "gmail"}
    assert CANARY_REVIEWED_READONLY_SCOPES["google-drive"] == (GOOGLE_DRIVE_READONLY_SCOPE,)
    assert CANARY_REVIEWED_READONLY_SCOPES["gmail"] == (GMAIL_READONLY_SCOPE,)
    assert GOOGLE_DRIVE_READONLY_SCOPE == "https://www.googleapis.com/auth/drive.readonly"
    assert GMAIL_READONLY_SCOPE == "https://www.googleapis.com/auth/gmail.readonly"
    for scopes in CANARY_REVIEWED_READONLY_SCOPES.values():
        assert scopes
        assert all(scope.endswith(READONLY_SCOPE_SUFFIX) for scope in scopes)


def test_reviewed_table_guard_rejects_an_injected_write_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    import b54_oauth_browser_canary_contract as contract

    guard = contract._assert_reviewed_scopes_are_readonly  # noqa: SLF001
    guard()
    monkeypatch.setitem(
        contract.CANARY_REVIEWED_READONLY_SCOPES,
        "google-drive",
        ("https://www.googleapis.com/auth/drive",),
    )
    with pytest.raises(CanaryContractError):
        guard()


def test_reviewed_scope_factory_returns_exact_reviewed_sets() -> None:
    assert DRIVE_SCOPE.connector_id == "google-drive"
    assert DRIVE_SCOPE.scopes == (GOOGLE_DRIVE_READONLY_SCOPE,)
    assert GMAIL_SCOPE.connector_id == "gmail"
    assert GMAIL_SCOPE.scopes == (GMAIL_READONLY_SCOPE,)


@pytest.mark.parametrize("connector_id", ["google-calendar", "drive", "", "Google-Drive", "google-drive "])
def test_unreviewed_connector_is_rejected(connector_id: str) -> None:
    with pytest.raises(CanaryContractError):
        reviewed_canary_scope(connector_id)
    with pytest.raises(CanaryContractError):
        CanaryConnectorScope(connector_id=connector_id, scopes=(GOOGLE_DRIVE_READONLY_SCOPE,))


def test_non_string_connector_id_is_rejected() -> None:
    with pytest.raises(CanaryContractError):
        reviewed_canary_scope(["gmail"])  # type: ignore[arg-type]
    with pytest.raises(CanaryContractError):
        CanaryConnectorScope(connector_id=None, scopes=(GMAIL_READONLY_SCOPE,))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "scopes",
    [
        (),
        ["https://www.googleapis.com/auth/drive.readonly"],
        (GOOGLE_DRIVE_READONLY_SCOPE, GOOGLE_DRIVE_READONLY_SCOPE),
        (GOOGLE_DRIVE_READONLY_SCOPE, 1),
        None,
    ],
)
def test_scope_tuple_shape_fails_closed(scopes: object) -> None:
    with pytest.raises(CanaryContractError):
        CanaryConnectorScope(connector_id="google-drive", scopes=scopes)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "write_scope",
    [
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/drive.file",
        "https://www.googleapis.com/auth/drive.readonly.write",
        "https://www.googleapis.com/auth/drive.metadata",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/drive.readonly ",
    ],
)
def test_write_scope_parameterization_is_rejected(write_scope: str) -> None:
    with pytest.raises(CanaryContractError):
        CanaryConnectorScope(connector_id="google-drive", scopes=(write_scope,))


def test_extra_readonly_scope_beyond_the_reviewed_set_is_rejected() -> None:
    with pytest.raises(CanaryContractError):
        CanaryConnectorScope(
            connector_id="google-drive",
            scopes=(GOOGLE_DRIVE_READONLY_SCOPE, "https://www.googleapis.com/auth/drive.metadata.readonly"),
        )


def test_attempt_cannot_start_or_act_without_a_reviewed_readonly_scope() -> None:
    attempt = OAuthCanaryAttempt()
    with pytest.raises(CanaryContractError):
        attempt.scope
    with pytest.raises(CanaryContractError):
        attempt.start("https://www.googleapis.com/auth/drive.readonly")  # type: ignore[arg-type]
    with pytest.raises(CanaryContractError):
        attempt.start(None)  # type: ignore[arg-type]
    called: list[str] = []
    with pytest.raises(CanaryContractError):
        attempt.ticket_post(lambda: called.append("ticket"))
    assert called == []


def test_attempt_scope_is_bound_before_any_action() -> None:
    attempt = OAuthCanaryAttempt()
    attempt.start(GMAIL_SCOPE)
    assert attempt.scope == GMAIL_SCOPE
    assert attempt.counts == {"ticket_post": 0, "connect_post": 0, "consent": 0, "callback": 0}


@pytest.mark.parametrize(
    "error_code",
    ["unreviewed_connector_scope", "non_readonly_scope", "scope_required"],
)
def test_scope_rejection_is_reportable_as_a_safe_error_code(error_code: str) -> None:
    report = OAuthCanaryAttempt().safe_report(status="blocked", error_code=error_code).as_dict()
    assert report["error_code"] == error_code
    assert report["raw_oauth_query"] is False
    assert report["raw_ticket"] is False


def test_scope_rejection_reports_distinct_safe_failure_classes() -> None:
    with pytest.raises(CanaryContractError) as write_exc:
        CanaryConnectorScope(
            connector_id="google-drive",
            scopes=("https://www.googleapis.com/auth/drive",),
        )
    assert "non_readonly_scope" in str(write_exc.value)

    with pytest.raises(CanaryContractError) as unreviewed_exc:
        CanaryConnectorScope(
            connector_id="google-drive",
            scopes=("https://www.googleapis.com/auth/drive.metadata.readonly",),
        )
    assert "unreviewed_connector_scope" in str(unreviewed_exc.value)

    with pytest.raises(CanaryContractError) as factory_exc:
        reviewed_canary_scope("google-calendar")
    assert "unreviewed_connector_scope" in str(factory_exc.value)


def test_start_scope_requirement_reports_scope_required() -> None:
    with pytest.raises(CanaryContractError) as exc:
        OAuthCanaryAttempt().start(None)  # type: ignore[arg-type]
    assert "scope_required" in str(exc.value)


def test_contract_test_module_has_a_real_ci_host() -> None:
    """Repo contract workflows list files explicitly, so an unpointed module never runs."""

    workflow = (
        Path(__file__).resolve().parents[2]
        / ".github/workflows/b54-oauth-browser-canary-contract-tests.yml"
    )
    text = workflow.read_text(encoding="utf-8")
    assert "python -m pytest -q .github/tests/test_b54_oauth_browser_canary_contract.py" in text
    assert "pull_request:" in text
    assert "workflow_dispatch:" in text
    assert "contents: read" in text
    assert "secrets." not in text
