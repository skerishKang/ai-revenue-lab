"""Connector version compatibility judgment — comparison, env and display rules.

Covers the four required behaviour groups for the connector 0.3.0-rc1 rollout:
(1) semver/rc comparison including ``0.2.0 < 0.3.0`` and ``0.3.0-rc1 < 0.3.0``;
(2) an unknown version never blocks anyone and keeps today's behaviour;
(3) the default env keeps every device out of ``UPDATE_REQUIRED``;
(4) an explicit minimum turns on the ``UPDATE_REQUIRED`` lane only below it.
"""

from __future__ import annotations

import os

import pytest

from kagent.connections_center import DeviceCompatibility
from kagent.connector_version_compat import (
    CONNECTOR_LATEST_VERSION_ENV,
    CONNECTOR_MINIMUM_VERSION_ENV,
    DEFAULT_CONNECTOR_LATEST_VERSION,
    compare_connector_versions,
    connector_version_thresholds,
    derive_device_compatibility,
    parse_connector_version,
)

LATEST = DEFAULT_CONNECTOR_LATEST_VERSION


# ---------------------------------------------------------------------------
# 1. Parsing and comparison rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("0.2.0", "0.3.0"),
        ("0.2.0", "0.3.0-rc1"),
        ("0.3.0-rc1", "0.3.0"),
        ("0.3.0-rc1", "0.3.0-rc2"),
        ("0.3.0-rc2", "0.3.0-rc11"),
        ("0.3.0-rc1", "0.4.0"),
        ("1.0.0", "1.0.1"),
        ("0.3.0-rc1", "1.0.0"),
    ],
)
def test_left_below_right(left: str, right: str) -> None:
    assert compare_connector_versions(left, right) == -1


@pytest.mark.parametrize("version", ["0.3.0", "0.3.0-rc1", "1.0.0"])
def test_equal_versions_compare_zero(version: str) -> None:
    assert compare_connector_versions(version, version) == 0


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("0.3.0", "0.2.0"),
        ("0.3.0", "0.3.0-rc1"),
        ("0.3.0-rc2", "0.3.0-rc1"),
        ("1.0.0", "0.3.0-rc1"),
    ],
)
def test_left_above_right(left: str, right: str) -> None:
    assert compare_connector_versions(left, right) == 1


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   ",
        "unknown",
        "dev",
        "v0.3.0",
        "0.3",
        "0.3.0.1",
        "0.3.0-rc",
        "0.3.0-beta1",
        "0.3.0-rc1x",
        "x" * 65,
        3,
        b"0.3.0",
    ],
)
def test_unparseable_versions_are_unknown(value: object) -> None:
    assert parse_connector_version(value) is None
    assert compare_connector_versions(value, "0.3.0") is None
    assert compare_connector_versions("0.3.0", value) is None


def test_parse_key_orders_release_above_pre_release() -> None:
    assert parse_connector_version("0.3.0-rc1") < parse_connector_version("0.3.0")
    assert parse_connector_version("0.3.0-rc1") < parse_connector_version("0.3.0-rc2")


def test_surrounding_whitespace_is_tolerated() -> None:
    assert parse_connector_version("  0.3.0-rc1  ") == parse_connector_version("0.3.0-rc1")


# ---------------------------------------------------------------------------
# 2. Judgement
# ---------------------------------------------------------------------------


def test_unknown_reported_version_is_unknown_and_never_update() -> None:
    for value in (None, "", "unknown", "dev", "v0.3.0"):
        assert derive_device_compatibility(value, latest_version=LATEST) is DeviceCompatibility.UNKNOWN


def test_old_version_below_latest_is_update_available() -> None:
    assert derive_device_compatibility("0.2.0", latest_version=LATEST) is DeviceCompatibility.UPDATE_AVAILABLE
    assert derive_device_compatibility("0.1.1-rc2", latest_version=LATEST) is DeviceCompatibility.UPDATE_AVAILABLE
    assert derive_device_compatibility("0.3.0-rc1-ignored", latest_version=LATEST) is DeviceCompatibility.UNKNOWN


def test_version_below_release_candidate_counts_as_old() -> None:
    # 0.3.0-rc1 is this release; 0.2.9 sits below even the pre-release.
    assert derive_device_compatibility("0.2.9", latest_version="0.3.0-rc1") is DeviceCompatibility.UPDATE_AVAILABLE


def test_current_version_is_not_update_available() -> None:
    assert derive_device_compatibility("0.3.0-rc1", latest_version=LATEST) is DeviceCompatibility.CURRENT
    assert derive_device_compatibility("0.3.0", latest_version=LATEST) is DeviceCompatibility.CURRENT
    assert derive_device_compatibility("0.4.0", latest_version=LATEST) is DeviceCompatibility.CURRENT


def test_minimum_lane_is_disabled_when_minimum_is_absent() -> None:
    for minimum in (None, "", "   "):
        assert derive_device_compatibility(
            "0.1.0", latest_version=LATEST, minimum_version=minimum
        ) is DeviceCompatibility.UPDATE_AVAILABLE


def test_minimum_lane_turns_on_only_below_the_minimum() -> None:
    assert derive_device_compatibility(
        "0.1.0", latest_version=LATEST, minimum_version="0.2.0"
    ) is DeviceCompatibility.UPDATE_REQUIRED
    assert derive_device_compatibility(
        "0.2.0", latest_version=LATEST, minimum_version="0.2.0"
    ) is DeviceCompatibility.UPDATE_AVAILABLE
    assert derive_device_compatibility(
        "0.3.0", latest_version=LATEST, minimum_version="0.2.0"
    ) is DeviceCompatibility.CURRENT


def test_minimum_wins_over_update_available() -> None:
    assert derive_device_compatibility(
        "0.1.0", latest_version=LATEST, minimum_version="0.2.0"
    ) is DeviceCompatibility.UPDATE_REQUIRED


def test_unparseable_latest_config_is_fail_silent() -> None:
    assert derive_device_compatibility("0.2.0", latest_version="garbage") is DeviceCompatibility.UNKNOWN


def test_unparseable_minimum_config_is_ignored_not_enforced() -> None:
    assert derive_device_compatibility(
        "0.1.0", latest_version=LATEST, minimum_version="garbage"
    ) is DeviceCompatibility.UPDATE_AVAILABLE


def test_judgment_reuses_the_connections_center_vocabulary() -> None:
    # Single vocabulary authority: the returned members ARE the contract enum.
    for reported in ("0.2.0", "0.3.0-rc1", None, "garbage"):
        result = derive_device_compatibility(reported, latest_version=LATEST)
        assert isinstance(result, DeviceCompatibility)
        assert result.value in {"current", "update_available", "update_required", "unknown"}


# ---------------------------------------------------------------------------
# 3. Environment defaults and overrides
# ---------------------------------------------------------------------------


def test_default_thresholds_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CONNECTOR_LATEST_VERSION_ENV, raising=False)
    monkeypatch.delenv(CONNECTOR_MINIMUM_VERSION_ENV, raising=False)
    assert connector_version_thresholds() == ("0.3.0-rc1", None)


def test_default_thresholds_ignore_blank_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CONNECTOR_LATEST_VERSION_ENV, "   ")
    monkeypatch.setenv(CONNECTOR_MINIMUM_VERSION_ENV, "  ")
    assert connector_version_thresholds() == ("0.3.0-rc1", None)


def test_env_overrides_are_passed_through_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CONNECTOR_LATEST_VERSION_ENV, "0.4.0")
    monkeypatch.setenv(CONNECTOR_MINIMUM_VERSION_ENV, "0.2.0")
    assert connector_version_thresholds() == ("0.4.0", "0.2.0")


def test_with_default_env_nobody_is_update_required() -> None:
    # Deployment safety: with the default configuration (minimum off) no
    # version — known or unknown — ever lands in UPDATE_REQUIRED.
    versions = ["0.0.1", "0.1.0", "0.1.1-rc1", "0.1.1-rc2", "0.2.0", "0.2.9",
                "0.3.0-rc1", "0.3.0", "1.0.0", None, "", "unknown", "garbage"]
    latest, minimum = connector_version_thresholds(env={})
    for value in versions:
        assert derive_device_compatibility(
            value, latest_version=latest, minimum_version=minimum
        ) is not DeviceCompatibility.UPDATE_REQUIRED


def test_with_default_env_old_versions_are_update_available_not_blocked() -> None:
    latest, minimum = connector_version_thresholds(env={})
    assert (latest, minimum) == ("0.3.0-rc1", None)
    for value in ("0.1.0", "0.1.1-rc2", "0.2.0"):
        assert derive_device_compatibility(
            value, latest_version=latest, minimum_version=minimum
        ) is DeviceCompatibility.UPDATE_AVAILABLE


def test_owner_decision_turns_on_the_minimum_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {
        CONNECTOR_LATEST_VERSION_ENV: "0.3.0-rc1",
        CONNECTOR_MINIMUM_VERSION_ENV: "0.2.0",
    }
    latest, minimum = connector_version_thresholds(env=env)
    assert derive_device_compatibility("0.1.0", latest_version=latest, minimum_version=minimum) is (
        DeviceCompatibility.UPDATE_REQUIRED
    )
    assert derive_device_compatibility("0.2.0", latest_version=latest, minimum_version=minimum) is (
        DeviceCompatibility.UPDATE_AVAILABLE
    )
