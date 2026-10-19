"""#4469: B66 public Search is a server-only deployment admission.

No real provider calls, secrets, browser impersonation or deployment mutation.
"""
from types import SimpleNamespace

import pytest

from app.b66_search_boundary import authorized_b66_fact_search_binding


def configured(**changes):
    params = dict(
        runtime_mode="b14",
        live_enabled=True,
        auth_mode="google",
        web_provider="tinyfish_daum",
        tinyfish_api_key="synthetic-only-tinyfish",
        daum_rest_api_key="synthetic-only-daum",
    )
    params.update(changes)
    return SimpleNamespace(**params)


@pytest.mark.parametrize("raw", [None, "", "true", "TRUE", "on", "ENABLED", "false", True, 1])
def test_only_exact_trusted_server_binding_enables_fact_search(raw):
    assert authorized_b66_fact_search_binding(configured(), raw) is False


@pytest.mark.parametrize("override", [
    {"runtime_mode": "mock"},
    {"live_enabled": False},
    {"auth_mode": "off"},
    {"web_provider": "off"},
    {"web_provider": "mock"},
    {"web_provider": "tinyfish"},
    {"web_provider": "daum"},
    {"web_provider": "firecrawl"},
    {"tinyfish_api_key": None},
    {"daum_rest_api_key": None},
])
def test_absent_core_live_prerequisite_refuses_egress(override):
    assert authorized_b66_fact_search_binding(configured(**override), "enabled") is False


def test_exact_activation_never_grants_browser_or_customer_authority():
    assert authorized_b66_fact_search_binding(configured(), "enabled") is True
    # The server fact flag is only a prerequisite. B66 role, B14 route,
    # query allowlist and quota are checked by the existing AI chat route.
