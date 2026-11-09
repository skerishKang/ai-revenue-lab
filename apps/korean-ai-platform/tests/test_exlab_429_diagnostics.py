"""Offline HTTPX-MockTransport verification for ExLab's 429 evidence.

#7241 3단계: the route, its host and its Provider id are read from the app's
own declaration rather than written here. The classifier cases take the
provider id as an argument, so no provider identity appears in this file.
"""
from __future__ import annotations

import logging

import httpx
import pytest

from app.pilot import platform as plt
from app.pilot.errors import UpstreamRateLimited
from app.pilot.exlab_429_diagnostics import classify_exlab_429, log_exlab_429

from _registry_values import adapter_declaring_retired, model_rows

def _adapter_declaring(attribute: str):
    """The one pilot adapter module that declares ``attribute``.

    The adapter is selected by the metadata it owns, not by its module name,
    so no Provider identity is restated here.
    """
    from _registry_values import adapter_modules

    matches = [module for module in adapter_modules().values()
               if hasattr(module, attribute)]
    assert len(matches) == 1, f"no unique adapter declares {attribute}"
    return matches[0]


#: The adapter that owns the 429 diagnostic contract this suite verifies.
EXLAB_ADAPTER = _adapter_declaring("EXPERIENTIAL_ALLOWED_HOST")
#: The Provider id as the adapter declares it (a module constant, not a value
#: written here).
EXLAB_PLATFORM_PROVIDER = EXLAB_ADAPTER.EXPERIENTIAL_PROVIDER_ID
EXLAB_PROVIDER_ID = EXLAB_PLATFORM_PROVIDER


def _served_row() -> dict:
    """The registered row this Provider serves, or ``None``.

    A document that registers no row for this Provider (e.g. the placeholder
    fixture) answers ``None``: the adapter cases below need a real route, so
    they report themselves skipped rather than pass on a route they never
    selected.
    """
    rows = [row for row in model_rows()
            if row["provider_id"] == EXLAB_PROVIDER_ID and row.get("enabled", True)]
    assert len(rows) <= 1, "the Provider serves more than one registered route"
    return rows[0] if rows else None


_EXLAB_ROW = _served_row()
#: The route this suite drives: the model id and upstream identity of the
#: registered row, read back rather than written here.
EXLAB_MODEL_ID = _EXLAB_ROW["id"] if _EXLAB_ROW else ""
EXLAB_UPSTREAM = _EXLAB_ROW["upstream_model"] if _EXLAB_ROW else ""
#: The display name the call surfaces label this Provider with.
EXLAB_ROW_PROVIDER_NAME = _EXLAB_ROW["provider_name"] if _EXLAB_ROW else ""
def _served_host() -> str:
    """The registered host the driven route is dialed at."""
    from urllib.parse import urlparse

    from _registry_values import provider_row

    return urlparse(provider_row(EXLAB_PROVIDER_ID)["base_origin"]).hostname or ""
#: Adapter cases need a registered route to drive.
requires_served_route = pytest.mark.skipif(
    _EXLAB_ROW is None,
    reason="the effective registry document registers no route for this Provider",
)


@pytest.mark.parametrize(("body","group","subtype"), [
    ('{"error":{"code":"insufficient_quota","message":"free_limit_reached: window"}}',
     "quota", "free_limit_reached"),
    ('{"error":{"code":"insufficient_quota","message":"org_rate_limit reached"}}',
     "quota", "org_rate_limit"),
    ('{"error":{"code":"insufficient_quota","message":"org_token_rate_limit_hour: some"}}',
     "quota", "org_token_rate_limit_hour"),
    ('{"error":{"code":"insufficient_quota","message":"key_daily_cap: capped"}}',
     "quota", "key_daily_cap"),
    ('{"error":{"code":"insufficient_quota","message":"private arbitrary text"}}',
     "quota", "none"),
    ('{"error":{"code":"org_under_review","message":"private"}}',
     "org_review", "none"),
    ('{"error":{"code":"unavailable_route"}}',
     "route_unavailable", "none"),
    ('{"error":{"code":"gateway_overloaded"}}',
     "capacity", "none"),
    ('{"error":{"code":"random-key-private-token"}}',
     "unclassified", "none"),
    ('{"error":{"message":"free_limit_reached private"}}',
     "unclassified", "none"),
    ('{"error":{"code":"insufficient_quota","message":"free_limit_reachedEVIL"}}',
     "quota", "none"),
])
def test_exlab_only_documented_error_codes(body, group, subtype):
    classification = classify_exlab_429(
        EXLAB_PLATFORM_PROVIDER, 429,
        httpx.Headers({"content-type":"application/json",
                       "retry-after":"PRIVATE_RETRY",
                       "cf-ray":"PRIVATE_RAY"}),
        body,
    )
    assert classification == {
        "media": "json", "reason_group": group, "quota_subtype": subtype,
        "retry_after_present": True, "cf_ray_present": True,
    }


@pytest.mark.parametrize(("provider","status"), [
    ("atria",429), ("experiential",400), ("experiential",200), ("google",429),
])
def test_never_log_unrelated_errors(provider,status,caplog):
    with caplog.at_level(logging.WARNING):
        log_exlab_429(plt.logger,provider,status,{},'{"error":{"code":"insufficient_quota"}}')
    assert "b14_exlab_429_safe_metadata" not in caplog.text


@pytest.mark.parametrize(("content_type","body","media"), [
    ("text/html", "<html>private</html>", "html"),
    ("application/json", "not json", "json"),
    ("text/plain", "private", "other"),
    ("application/json", "x"*4097, "json"),
])
def test_untrusted_payload_is_never_logged(caplog,content_type,body,media):
    with caplog.at_level(logging.WARNING):
        log_exlab_429(plt.logger,EXLAB_PLATFORM_PROVIDER,429,
                      httpx.Headers({"content-type":content_type}),body)
    assert "reason_group=unclassified" in caplog.text
    assert "media="+media in caplog.text
    assert body not in caplog.text


@requires_served_route
@pytest.mark.asyncio
@pytest.mark.parametrize("stream",[False,True])
async def test_httpx_adapter_keeps_429_and_emits_redacted_classification(
    monkeypatch,caplog,stream,
):
    monkeypatch.setenv("B14_PROVIDER_MODE","live")
    monkeypatch.setattr(
        plt,"_request_headers",
        lambda spec,model_id="": {"Content-Type":"application/json"},
    )
    secret="PRIVATE_SECRET_NEVER_REPORT_4220"
    async def reply(req):
        assert req.url.host == _served_host()
        return httpx.Response(
            429,
            headers={
                "content-type":"application/json",
                "retry-after":secret,
                "cf-ray":secret,
            },
            json={
                "error": {
                    "code":"insufficient_quota",
                    "message":"free_limit_reached: "+secret,
                    "details":{"customer_data":secret},
                },
            },
        )
    kwargs={
        "model_id":EXLAB_MODEL_ID,
        "upstream_model":EXLAB_UPSTREAM,
        "provider":EXLAB_ROW_PROVIDER_NAME,
        "platform_provider_id":EXLAB_PLATFORM_PROVIDER,
        "messages":[{"role":"user","content":"synthetic only"}],
        "transport":httpx.MockTransport(reply),
    }
    with caplog.at_level(logging.WARNING), pytest.raises(UpstreamRateLimited) as exc:
        if stream:
            async for _ in plt.stream_platform_chat_completions(**kwargs):
                pass
        else:
            await plt.call_platform_chat_completions(**kwargs)
    assert exc.value.status_code==429
    assert "b14_exlab_429_safe_metadata" in caplog.text
    assert "reason_group=quota" in caplog.text
    assert "quota_subtype=free_limit_reached" in caplog.text
    assert "retry_after_present=True" in caplog.text
    assert secret not in caplog.text
    assert "insufficient_quota" not in caplog.text
    assert "free_limit_reached:" not in caplog.text


@requires_served_route
@pytest.mark.asyncio
async def test_200_does_not_emit_429_log(monkeypatch,caplog):
    monkeypatch.setenv("B14_PROVIDER_MODE","live")
    monkeypatch.setattr(
        plt,"_request_headers",
        lambda spec,model_id="": {"Content-Type":"application/json"},
    )
    async def reply(req):
        return httpx.Response(200,json={
            "id":"synthetic","model":EXLAB_UPSTREAM,
            "choices":[{"message":{"role":"assistant","content":"synthetic OK"},
                        "finish_reason":"stop"}],
        })
    with caplog.at_level(logging.WARNING):
        got=await plt.call_platform_chat_completions(
            model_id=EXLAB_MODEL_ID,
            upstream_model=EXLAB_UPSTREAM,
            provider=EXLAB_ROW_PROVIDER_NAME,platform_provider_id=EXLAB_PLATFORM_PROVIDER,
            messages=[{"role":"user","content":"synthetic"}],
            transport=httpx.MockTransport(reply),
        )
    assert got["model"]==EXLAB_UPSTREAM
    assert "b14_exlab_429_safe_metadata" not in caplog.text
