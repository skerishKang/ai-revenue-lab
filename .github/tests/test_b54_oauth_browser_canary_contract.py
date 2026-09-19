"""Provider-free tests for the bounded readonly OAuth canary contract."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from b54_oauth_browser_canary_contract import (  # noqa: E402
    EXTERNAL_RUNTIME_METADATA_REDACTION,
    DURABLE_REPLAY_AUTHORITY,
    CanaryContractError,
    ConsentPollStatus,
    ConnectRequestPolicy,
    OAuthCanaryAttempt,
    poll_consent_target,
    project_transition_location,
)


def test_second_begin_fails_before_action() -> None:
    attempt = OAuthCanaryAttempt()
    attempt.start()
    called = []
    with pytest.raises(CanaryContractError):
        attempt.start()
    assert called == []


@pytest.mark.parametrize("action_name, prior_actions", [
    ("ticket_post", ("ticket_post",)),
    ("connect_post", ("ticket_post", "connect_post")),
    ("consent", ("ticket_post", "connect_post", "consent")),
    ("callback", ("ticket_post", "connect_post", "consent", "callback")),
])
def test_each_action_duplicate_is_blocked_immediately(action_name: str, prior_actions: tuple[str, ...]) -> None:
    attempt = OAuthCanaryAttempt()
    attempt.start()
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
    attempt.start()
    called = []
    with pytest.raises(CanaryContractError):
        attempt.connect_post(lambda: called.append("connect"))
    assert called == []


def test_failed_action_consumes_budget_and_cannot_retry() -> None:
    attempt = OAuthCanaryAttempt()
    attempt.start()
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
    attempt.start()
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
    attempt.start()
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
