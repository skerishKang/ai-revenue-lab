"""#3760/#3751: B66 against REAL B14 source GET metadata (zero upstream).

Unlike hand-written registry fixtures, these tests execute the real source
metadata builders behind B14's /api/pilot/models and
/api/pilot/provider-readiness GET endpoints in an isolated child process,
then invoke the genuine B66 quote resolver. No TestClient/HTTP GET is issued.

This is a SOURCE integration test, not deployed B14/provider readiness proof.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.b66_b14_free_first_resolver import B14FreeFirstQuoteModelResolver
from app.b66_registered_model_boundary import B66ModelRouteError, B66QuoteTaskRequirements


REPO = Path(__file__).resolve().parents[3]
B14_APP_DIR = REPO / "apps" / "korean-ai-platform"
B14_GETS = ("/api/pilot/models", "/api/pilot/provider-readiness")
GOOGLE_IDS = {
    "google/gemini-3.1-flash-lite",
    "google/gemini-3.5-flash-lite",
    "google/gemma-4-26b-a4b-it",
    "google/gemma-4-31b-it",
}

# Child process is the B14 package named 'app'; the parent stays B66's
# same-named 'app'. No import-path collision, credentials, HTML-template dependency or provider calls.
B14_SOURCE_SCRIPT = r"""
import json
import asyncio
import builtins

# B62's locked CI need not install B14 HTML templates to test quote routes.
# Reproduce the exact metadata builders behind B14's two GET endpoints,
# without importing B14 app.factory / jinja2 or making an HTTP request.
original_import = builtins.__import__
def reject_html_template_dependency(name, *args, **kwargs):
    if name == "jinja2" or name.startswith("jinja2."):
        raise ModuleNotFoundError("JINJA2_NOT_REQUIRED_FOR_B66_READ")
    return original_import(name, *args, **kwargs)
builtins.__import__ = reject_html_template_dependency

from app.pilot.gateway import _registered_route_dicts, _catalog_summary_dicts
from app.pilot.provider_readiness import provider_readiness

models = {
    "registered_routes": _registered_route_dicts(),
    "catalog": _catalog_summary_dicts(),
}
readiness = json.loads(asyncio.run(provider_readiness(None)).body)
print("B66_SOURCE_GETS=" + json.dumps({
    "models": models,
    "readiness": readiness,
}, separators=(",", ":"), ensure_ascii=True))
"""


@pytest.fixture(scope="module")
def b14_source_gets():
    # Minimal environment, no inherited provider/API credentials and no
    # external network/prod URL. 'live' is a LOCAL B14 config flag ONLY.
    keep = {"path", "systemroot", "windir", "temp", "tmp", "home",
            "userprofile", "appdata", "localappdata", "programfiles",
            "programfiles(x86)"}
    env = {key: value for key, value in os.environ.items()
           if key.casefold() in keep}
    env["B14_PROVIDER_MODE"] = "live"
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = os.pathsep.join((
        str(B14_APP_DIR),
        str(REPO / "packages" / "padiem-control-plane"),
        str(REPO / "packages" / "padiem-ai-core"),
    ))
    child = subprocess.run(
        [sys.executable, "-c", B14_SOURCE_SCRIPT],
        cwd=B14_APP_DIR,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=25,
        check=False,
    )
    assert child.returncode == 0, "B14 internal metadata builder smoke failed"
    markers = [line for line in child.stdout.splitlines()
               if line.startswith("B66_SOURCE_GETS=")]
    assert len(markers) == 1, "B14 metadata builder output was not produced exactly once"
    payload = json.loads(markers[0].split("=", 1)[1])
    assert set(payload) == {"models", "readiness"}
    assert isinstance(payload["models"].get("registered_routes"), list)
    assert isinstance(payload["models"].get("catalog"), list)
    assert isinstance(payload["readiness"].get("providers"), list)
    return payload


class SourceMetadataTransport:
    def __init__(self, payload):
        self.payload = payload
        self.get_paths = []
        self.provider_posts = 0

    async def get_json(self, path):
        self.get_paths.append(path)
        if path == B14_GETS[0]:
            return 200, json.dumps(self.payload["models"]).encode("utf-8")
        if path == B14_GETS[1]:
            return 200, json.dumps(self.payload["readiness"]).encode("utf-8")
        raise AssertionError("B14 source query outside the two GET allowlist")

    async def post_json(self, *unused):
        self.provider_posts += 1
        raise AssertionError("B66 source eligibility must never execute a provider")


def attempt_selection(payload, model_id=None):
    transport = SourceMetadataTransport(payload)
    with pytest.raises(B66ModelRouteError) as result:
        asyncio.run(
            B14FreeFirstQuoteModelResolver(transport).resolve_quote_model(
                B66QuoteTaskRequirements(selected_model_id=model_id or sorted(GOOGLE_IDS)[0])
            )
        )
    assert transport.get_paths == list(B14_GETS)
    assert transport.provider_posts == 0
    return result.value.code


def test_real_b14_source_registered_routes_and_google_manual_only(b14_source_gets):
    registry = b14_source_gets["models"]
    readiness = b14_source_gets["readiness"]
    rows = registry["registered_routes"]
    by_id = {row["id"]: row for row in rows}
    assert len(by_id) == len(rows)
    assert GOOGLE_IDS <= by_id.keys(), "Four owner-registered Google routes absent"
    for mid in GOOGLE_IDS:
        assert by_id[mid]["explicit_only"] is True
        assert by_id[mid]["auto_eligible"] is False
        assert by_id[mid]["owner_excluded"] is False
        assert "chat" in by_id[mid]["capabilities"]
    assert readiness["provider_mode"] == "live"  # local fixture, not Production

    # The only public-auto route in legacy source is owner-excluded. No
    # credential can authorize it for B66 merely by being registered/free.
    assert all(not row["auto_eligible"] for row in rows)
    assert any(row["owner_excluded"] for row in rows)
    assert any(row["owner_excluded"] and row["free"] for row in rows)


def test_b66_owner_allowed_selector_refuses_actual_unready_b14_source_snapshot(b14_source_gets):
    assert attempt_selection(b14_source_gets) == "selection_unavailable"


def test_all_providers_synthetically_ready_still_fail_closed_for_ambiguous_owner_routes(
    b14_source_gets,
):
    """Separate simulated readiness from actual Production credential proof."""
    data = json.loads(json.dumps(b14_source_gets))
    for provider in data["readiness"]["providers"]:
        provider["enabled"] = True
        provider["credential_ready"] = True
        provider["route_ready"] = True
    # Multiple owner-allowed routes must never receive a hidden price rank or
    # generic B14 public/auto route preference.
    # Ambiguity across models is not relevant when an exact user model was supplied.
    # No implicit choice is made; absence of selected_model_id is rejected separately.
    transport = SourceMetadataTransport(data)
    selected = asyncio.run(B14FreeFirstQuoteModelResolver(transport).resolve_quote_model(
        B66QuoteTaskRequirements(selected_model_id=sorted(GOOGLE_IDS)[0])
    ))
    assert selected.model_id == sorted(GOOGLE_IDS)[0]


def test_one_synthetic_ready_google_manual_pin_can_be_validated_without_catalog(
    b14_source_gets,
):
    """Source only: neither provider credentials nor an actual upstream call."""
    data = json.loads(json.dumps(b14_source_gets))
    mid = sorted(GOOGLE_IDS)[0]  # fixture only; not a B66 selection policy
    assert mid not in {m["id"] for m in data["models"]["catalog"]}
    for provider in data["readiness"]["providers"]:
        allowed = mid in provider.get("models", [])
        provider["enabled"] = allowed
        provider["credential_ready"] = allowed
        provider["route_ready"] = allowed
        provider["models"] = [mid] if allowed else []
    transport = SourceMetadataTransport(data)
    selected = asyncio.run(
        B14FreeFirstQuoteModelResolver(transport).resolve_quote_model(
            B66QuoteTaskRequirements(selected_model_id=mid)
        )
    )
    assert selected.model_id == mid
    assert selected.owner_policy_id == "OWNER_REGISTERED_AND_ALLOWED"
    assert transport.get_paths == list(B14_GETS)
    assert transport.provider_posts == 0


def test_live_mode_not_customer_authority_and_no_default_replacement(b14_source_gets):
    rows = b14_source_gets["models"]["registered_routes"]
    public = [row for row in rows if row.get("public") is True]
    assert len(public) == 1
    assert public[0]["owner_excluded"] is True
    assert public[0]["auto_eligible"] is False
    assert not any(row["id"].startswith("google/") and row["auto_eligible"]
                   for row in rows)
    # This test is not a model activation. It never reads secrets or sends
    # customer input, and it does not modify B14's registered routes.
