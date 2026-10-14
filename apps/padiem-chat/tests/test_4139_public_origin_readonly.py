"""#4139 public-route readiness probe is pinned, read-only and never auth proof."""
from __future__ import annotations

import json
import socket

import pytest

from scripts import connector_cloudflare_runtime_readiness as inventory
from scripts import connector_public_origin_readonly as probe


class FakeHTTPS:
    def __init__(self, status: int = 401, *, error: Exception | None = None):
        self.status = status
        self.error = error
        self.calls = []
        self.closed = False

    def request(self, method, target, *, headers):
        self.calls.append((method, target, headers.copy()))
        if self.error is not None:
            raise self.error

    def getresponse(self):
        return type("FakeResponse", (), {"status": self.status})()

    def close(self):
        self.closed = True


def _run(status=401, *, resolver=None, error=None):
    calls = []
    connection = FakeHTTPS(status, error=error)

    def dns(host, port, *, type):
        calls.append((host, port, type))
        return [(1, 2, 3, 4, 5)] if resolver is None else resolver(host, port, type)

    def https(host, *, port, timeout, context):
        calls.append(("connection", host, port, timeout, context))
        return connection

    result = probe.probe_isolated_owner_setup(
        resolver=dns, connection_factory=https,
        tls_context_factory=lambda: object(),
    )
    return result, calls, connection


@pytest.mark.parametrize("status", [200, 302, 401, 403, 404, 503])
def test_status_only_never_claims_login_or_pc(status):
    result, calls, conn = _run(status)
    assert result == {
        "dns_resolves": True,
        "https_responds": True,
        "owner_setup_http_status": status,
        "owner_authenticated": False,
        "wss_pairing_proven": False,
        "changed_cloudflare_or_pc": False,
    }
    assert calls[0] == (
        "connector-acceptance.padiem.net", 443, socket.SOCK_STREAM,
    )
    assert calls[1][0:4] == ("connection", "connector-acceptance.padiem.net", 443, 3.0)
    assert conn.calls == [(
        "GET", "/api/claw/connector/enrollments/setup",
        {"Accept": "text/html", "Cache-Control": "no-store"},
    )]
    assert conn.closed is True
    # Status cannot be used as proof of a routed owner-authenticated page.
    assert probe.blockers_for_probe(result) == (
        ("acceptance_owner_setup_http_404",) if status == 404 else ()
    )


def test_dns_unavailable_never_attempts_https():
    def bad_dns(*_):
        raise OSError("contains_secret_should_not_log")

    result, calls, conn = _run(resolver=bad_dns)
    assert result["dns_resolves"] is False
    assert result["https_responds"] is False
    assert result["owner_setup_http_status"] is None
    assert len(calls) == 1 and conn.calls == []
    assert probe.blockers_for_probe(result) == ("acceptance_public_dns_unavailable",)
    assert "contains_secret_should_not_log" not in json.dumps(result)


def test_tls_timeout_fails_closed_and_never_logs_remote_details():
    result, _, conn = _run(error=TimeoutError("private_session_string"))
    assert result["dns_resolves"] is True
    assert result["https_responds"] is False
    assert probe.blockers_for_probe(result) == (
        "acceptance_public_https_unavailable",
    )
    assert conn.closed is True
    assert "private_session_string" not in json.dumps(result)


def test_empty_dns_answer_is_not_a_route():
    result = probe.probe_isolated_owner_setup(
        resolver=lambda *_a, **_k: [],
        connection_factory=lambda *_a, **_k: pytest.fail("HTTPS contacted"),
    )
    assert result["dns_resolves"] is False
    assert result["owner_authenticated"] is False


def test_default_inventory_is_offline_and_cli_network_is_explicit(monkeypatch):
    monkeypatch.setattr(inventory.shutil, "which", lambda name: "wrangler")
    monkeypatch.setattr(inventory, "_run_readonly", lambda **_: None)
    monkeypatch.setattr(
        probe, "probe_isolated_owner_setup",
        lambda: pytest.fail("default inventory made a network request"),
    )
    default = inventory.inventory()
    assert "acceptance_owner_setup_public_probe" not in default


def test_explicit_inventory_includes_dns_blocker_without_auth_claim(monkeypatch):
    monkeypatch.setattr(inventory.shutil, "which", lambda name: "wrangler")
    monkeypatch.setattr(inventory, "_run_readonly", lambda **_: None)
    sample = {
        "dns_resolves": False, "https_responds": False,
        "owner_setup_http_status": None, "owner_authenticated": False,
        "wss_pairing_proven": False, "changed_cloudflare_or_pc": False,
    }
    monkeypatch.setattr(probe, "probe_isolated_owner_setup", lambda: sample)
    state = inventory.inventory(inspect_public_https=True)
    assert state["acceptance_owner_setup_public_probe"] == sample
    assert "acceptance_public_dns_unavailable" in state["blocking_facts"]
    assert state["actual_owner_windows_pairing_proven"] is False
    assert state["changes_made"] is False


def test_documented_direct_script_import_mode_handles_sibling_module(monkeypatch):
    # "python apps/padiem-chat/scripts/connector_cloudflare_runtime_readiness.py"
    # is an executable script with __package__ empty, unlike pytest imports.
    import importlib
    import importlib.util
    from pathlib import Path

    script_file = Path(inventory.__file__).resolve()
    spec = importlib.util.spec_from_file_location(
        "readiness_as_direct_script", script_file,
    )
    direct = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(direct)
    assert not direct.__package__

    monkeypatch.syspath_prepend(str(script_file.parent))
    sibling = importlib.import_module("connector_public_origin_readonly")
    monkeypatch.setattr(sibling, "probe_isolated_owner_setup", lambda: {
        "dns_resolves": False,
        "https_responds": False,
        "owner_setup_http_status": None,
        "owner_authenticated": False,
        "wss_pairing_proven": False,
        "changed_cloudflare_or_pc": False,
    })
    monkeypatch.setattr(direct.shutil, "which", lambda _: "wrangler")
    monkeypatch.setattr(direct, "_run_readonly", lambda **_: None)

    outcome = direct.inventory(inspect_public_https=True)
    assert outcome["readiness"] == "blocked"
    assert "acceptance_public_dns_unavailable" in outcome["blocking_facts"]
    assert outcome["actual_owner_windows_pairing_proven"] is False
