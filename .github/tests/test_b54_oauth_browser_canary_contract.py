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


@pytest.mark.parametrize("action_name", ["ticket_post", "connect_post", "consent", "callback"])
def test_duplicate_budgeted_action_fails_before_second_action(action_name: str) -> None:
    attempt = OAuthCanaryAttempt()
    attempt.start()
    callbacks = {name: (lambda name=name: calls.append(name)) for name in ("ticket_post", "connect_post", "consent", "callback")}
    calls: list[str] = []
    attempt.ticket_post(callbacks["ticket_post"])
    attempt.connect_post(callbacks["connect_post"])
    attempt.consent(callbacks["consent"])
    attempt.callback(callbacks["callback"])
    assert attempt.counts == {name: 1 for name in ("ticket_post", "connect_post", "consent", "callback")}
    with pytest.raises(CanaryContractError):
        getattr(attempt, action_name)(callbacks[action_name])
    assert calls == ["ticket_post", "connect_post", "consent", "callback"]


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
    assert calls == ["ticket"]
    assert attempt.counts["ticket_post"] == 1


def test_connect_is_structurally_single_call_with_redirect_and_retry_zero() -> None:
    attempt = OAuthCanaryAttempt()
    attempt.start()
    calls = []
    attempt.ticket_post(lambda: calls.append("ticket"))
    attempt.connect_post(lambda: calls.append("connect"))
    assert calls == ["ticket", "connect"]
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


def test_safe_projection_rejects_non_location_transition_url() -> None:
    with pytest.raises(CanaryContractError):
        project_transition_location("https://oauth.example.test?state=only")


def test_runtime_and_durable_authority_boundaries_are_explicit() -> None:
    assert EXTERNAL_RUNTIME_METADATA_REDACTION == "UNRESOLVED"
    assert DURABLE_REPLAY_AUTHORITY == "SERVER_SIDE_EXISTING"
