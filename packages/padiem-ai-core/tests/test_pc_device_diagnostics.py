"""#3099 the canonical PC device diagnostic hint vocabulary.

These tests pin the contract every layer relies on: the vocabulary is
closed, the absence of an observation is a first-class value, and nothing
that is not an actual observation can be reported as a confirmed negative.
"""

from __future__ import annotations

import pytest

from padiem_ai_core.pc_device_diagnostics import (
    DIAGNOSTIC_KEYS,
    diagnostic_fix,
    diagnostics_have_observation,
    is_stale,
    normalize_diagnostics,
    sanitize_diagnostics_text,
    unknown_diagnostics,
)


def test_a_fully_observed_hint_is_accepted():
    hints = normalize_diagnostics({
        "agent_source": "ready", "autostart": "enabled", "resident": "running",
    })
    assert hints == {
        "agent_source": "ready", "autostart": "enabled", "resident": "running",
    }
    assert diagnostics_have_observation(hints) is True


def test_an_unknown_value_is_a_valid_observation_of_nothing():
    hints = normalize_diagnostics({
        "agent_source": "unknown", "autostart": "unknown", "resident": "unknown",
    })
    assert hints is not None
    assert diagnostics_have_observation(hints) is False


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "ready",
        {},
        {"agent_source": "ready"},
        {"agent_source": "ready", "autostart": "enabled"},
        {"agent_source": "ready", "autostart": "enabled", "resident": "running", "extra": 1},
        {"agent_source": "deleted", "autostart": "enabled", "resident": "running"},
        {"agent_source": 1, "autostart": "enabled", "resident": "running"},
        {"agent_source": "C:\\Users\\me", "autostart": "enabled", "resident": "running"},
    ],
)
def test_an_unusable_hint_is_refused_rather_than_guessed(raw):
    assert normalize_diagnostics(raw) is None


def test_the_unknown_set_covers_every_key():
    unknown = unknown_diagnostics()
    assert set(unknown) == set(DIAGNOSTIC_KEYS)
    assert all(value == "unknown" for value in unknown.values())


def test_only_an_observed_problem_has_a_fix():
    checks = {"agent_source": "not_installed", "autostart": "enabled", "resident": "running"}
    assert diagnostic_fix(checks, "agent_source") == "install_agent"
    assert diagnostic_fix(checks, "autostart") is None
    assert diagnostic_fix(checks, "resident") is None
    assert diagnostic_fix({"agent_source": "unknown"}, "agent_source") is None


def test_staleness_is_decided_by_the_server_clock():
    now = 1_000_000.0
    assert is_stale(now - 10, now=now, max_age_seconds=300) is False
    assert is_stale(now - 400, now=now, max_age_seconds=300) is True
    # A report from the future is not a fresh report.
    assert is_stale(now + 10, now=now, max_age_seconds=300) is True
    assert is_stale(None, now=now, max_age_seconds=300) is True
    assert is_stale("now", now=now, max_age_seconds=300) is True
    assert is_stale(True, now=now, max_age_seconds=300) is True


def test_a_label_may_not_carry_a_path_a_secret_or_a_log_line():
    assert sanitize_diagnostics_text("ready") == "ready"
    assert sanitize_diagnostics_text("C:\\Users\\me\\agent") is None
    assert sanitize_diagnostics_text("ready\nleaked log") is None
    assert sanitize_diagnostics_text("a" * 65) is None
    assert sanitize_diagnostics_text("") is None
    assert sanitize_diagnostics_text(None) is None
    assert sanitize_diagnostics_text("ready; rm -rf /") is None
