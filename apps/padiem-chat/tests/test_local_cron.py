"""The COM2 timer entry for the Worker's scheduled lane reports honestly."""
from __future__ import annotations

import pytest

from app.config import ConfigError
from app.local_cron import run_once


def _env(**overrides) -> dict[str, str]:
    base = {
        "PADIEM_LOCAL_DEV": "1",
        "PADIEM_CHAT_AUTOMATION_SCHEDULER_ENABLED": "true",
    }
    base.update(overrides)
    return base


def test_disabled_gate_wins_before_anything_else():
    assert run_once({}).endswith("SKIPPED reason=automation_scheduler_disabled")


def test_the_local_flag_is_required_once_enabled():
    with pytest.raises(ConfigError):
        run_once(_env(PADIEM_LOCAL_DEV="0"))


def test_missing_identity_reports_not_configured_instead_of_pretending():
    assert run_once(_env()).endswith("NOT_CONFIGURED reason=identity_rpc_unbound")


def test_configured_identity_still_reports_the_missing_engine_lane():
    status = run_once(_env(
        PADIEM_CHAT_LOCAL_IDENTITY_RPC_ORIGIN="https://identity.example",
        PADIEM_CHAT_LOCAL_IDENTITY_RPC_SECRET="local-service-secret-0123456789abcdef",
    ))
    assert status.endswith("NOT_CONFIGURED reason=p01_engine_transport_unbound")
