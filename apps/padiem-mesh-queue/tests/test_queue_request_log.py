"""The store door can say it was knocked on - in five fields and nothing else.

Measured on the 2026-10-30 cutover attempt: the Chat Worker answered its own calls with
503 while the queue wrote no row, logged nothing (uvicorn is quiet by design) and the
tunnel runs at `warn`, so "blocked before it got here", "refused here" and "answered 200
and disliked" left exactly the same trace - none. These tests pin the one instrument that
separates them, and the shape that keeps it from becoming a leak.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import pathlib
import re
import sqlite3
import sys
from types import SimpleNamespace

QUEUE = pathlib.Path(__file__).resolve().parents[1]
CHAT = QUEUE.parents[1] / "apps" / "padiem-chat"
sys.path.insert(0, str(CHAT))
sys.path.insert(0, str(QUEUE))

from internal_store import (  # noqa: E402
    INTERNAL_STORE_PATH, QUEUE_SERVICE_SECRET_HEADER, log_line, log_mode,
)
from schema import apply  # noqa: E402
from service import create_app  # noqa: E402

SECRET = "queue-channel-secret-value-261029"
SERVICE_SECRET = "queue-service-secret-value-261029"
OWNERSHIP = [{"account_ref": "acct-1", "device_id": "device-1", "node_ref": "node-ABC",
              "root_ref": "C:", "path_relative": "p.txt", "file_path": "C:/p.txt",
              "command_exec": True}]
LINE = re.compile(
    r"\AMESH_QUEUE_REQUEST path=/internal/store rpc=[a-z_]{1,64} status=[0-9]{3} "
    r"ms=[0-9]{1,7} proof=(ok|bad|absent) run_hash=(none|[0-9a-f]{16}) dispatch_id=(none|dsp_[0-9a-f]{32})\Z")

#: The door's other two shapes (#5881, after the 2026-10-30 attempt). Fixed forms, a class
#: name from a list and a status word - nothing a caller can put words into.
FAILURE_LINE = re.compile(
    r"\AMESH_QUEUE_STORE_FAILURE path=/internal/store rpc=[a-z_]{1,64} "
    r"fail=[A-Za-z_]{1,40} run_hash=(none|[0-9a-f]{16}) dispatch_id=(none|dsp_[0-9a-f]{32})\Z")
RECOVERY_LINE = re.compile(
    r"\AMESH_QUEUE_TXN_RECOVERED path=/internal/store rpc=[a-z_]{1,64} run_hash=(none|[0-9a-f]{16}) dispatch_id=(none|dsp_[0-9a-f]{32})\Z")


class _Headers(dict):
    def get(self, key, default=None):
        return super().get(str(key).lower(), default)


class _Request:
    def __init__(self, state, wire, *, secret=SERVICE_SECRET):
        self.app = SimpleNamespace(state=state)
        body = b"{}" if wire is None else json.dumps(wire).encode("utf-8")
        self.headers = _Headers({"content-type": "application/json",
                                 "content-length": str(len(body))})
        if secret is not None:
            self.headers[QUEUE_SERVICE_SECRET_HEADER.lower()] = secret
        self._body = body

    async def body(self):
        return self._body


def _app(**kwargs):
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    apply(connection)
    kwargs.setdefault("service_secret", SERVICE_SECRET)
    return create_app(connection=connection, channel_secret=SECRET,
                      ownership_map=json.dumps(OWNERSHIP), mode="mesh", **kwargs)


def _handler(app):
    return next(route.endpoint for route in app.routes if route.path == INTERNAL_STORE_PATH)


def _say(app, wire, **kwargs):
    """One call, and whatever the door printed while answering it."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        response = asyncio.run(_handler(app)(_Request(app.state, wire, **kwargs)))
    return response, out.getvalue()


LIST_LINKS = {"method": "list_links", "arguments": {"user_id": "usr_" + "a" * 32}}


def test_off_is_silent_even_when_a_caller_is_refused():
    app = _app()
    response, shouted = _say(app, LIST_LINKS, secret="wrong-service-secret-value-0000")
    assert response.status_code == 403
    assert shouted == "", "the shipped default changes nothing about this door"


def test_refusals_names_the_refusal_and_stays_quiet_about_a_good_call():
    app = _app(request_log="refusals")
    refused, shouted = _say(app, LIST_LINKS, secret="wrong-service-secret-value-0000")
    assert refused.status_code == 403
    assert LINE.fullmatch(shouted.strip()), shouted
    assert "proof=bad" in shouted and "status=403" in shouted and "rpc=none" in shouted
    _good, quiet = _say(app, LIST_LINKS)
    assert quiet == "", "a healthy lane must not print, or the window is unreadable"


def test_all_prints_the_method_name_only_from_the_allowlist():
    app = _app(request_log="all")
    good, shouted = _say(app, LIST_LINKS)
    assert good.status_code == 200
    assert LINE.fullmatch(shouted.strip()), shouted
    assert "rpc=list_links" in shouted and "status=200" in shouted and "proof=ok" in shouted
    denied, shouted2 = _say(app, {"method": "delete_everything", "arguments": {}})
    assert denied.status_code == 400
    assert "rpc=none" in shouted2 and "delete_everything" not in shouted2, shouted2


def test_the_line_carries_no_secret_no_argument_and_no_customer_path():
    app = _app(request_log="all")
    marker = "C:/Users/customer/private-file.txt"
    response, shouted = _say(app, {"method": "device_scope",
                                   "arguments": {"device_id": marker, "unexpected": 1}})
    assert response.status_code == 502
    # Two lines now: the five-field request line, and the store-failure line that names
    # only a class. Each still has exactly one fixed shape.
    lines = [line for line in shouted.splitlines() if line.strip()]
    assert len(lines) == 2, shouted
    assert LINE.fullmatch(lines[0]), lines[0]
    assert FAILURE_LINE.fullmatch(lines[1]), lines[1]
    for forbidden in (SERVICE_SECRET, marker, "unexpected", "device_id", "usr_"):
        assert forbidden not in shouted, forbidden


def test_a_caller_with_no_header_at_all_is_absent_and_not_ok():
    # `absent` vs `bad` is the difference between "never got our credential" and
    # "got a different one" - the two causes the last attempt could not separate.
    app = _app(request_log="refusals")
    response, shouted = _say(app, LIST_LINKS, secret=None)
    assert response.status_code == 403
    assert "proof=absent" in shouted, shouted


def test_an_unreadable_switch_value_is_off_and_the_shape_is_bounded():
    assert log_mode(None) == "off"
    assert log_mode("") == "off"
    assert log_mode("REFUSALS ") == "refusals"
    assert log_mode("everything") == "off"
    app = _app(request_log="everything")
    _say(app, LIST_LINKS)
    refused, shouted = _say(app, LIST_LINKS, secret="x")
    assert shouted == ""
    line = log_line(INTERNAL_STORE_PATH, "list_links", 200, 12, "ok")
    assert line == ("MESH_QUEUE_REQUEST path=/internal/store rpc=list_links status=200"
                    " ms=12 proof=ok run_hash=none dispatch_id=none")


def test_authenticated_correlation_headers_are_bounded_and_logged():
    app = _app(request_log="all")
    request = _Request(app.state, LIST_LINKS)
    request.headers["x-padiem-pc-run-hash"] = "a" * 16
    request.headers["x-padiem-pc-dispatch-id"] = "dsp_" + "b" * 32
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        response = asyncio.run(_handler(app)(request))
    assert response.status_code == 200
    assert "run_hash=" + "a" * 16 in out.getvalue()
    assert "dispatch_id=dsp_" + "b" * 32 in out.getvalue()
    request.headers["x-padiem-pc-run-hash"] = "chat_pcq_" + "a" * 32
    request.headers["x-padiem-pc-dispatch-id"] = "dsp_bogus\nsecret"
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        asyncio.run(_handler(app)(request))
    assert "run_hash=none dispatch_id=none" in out.getvalue()
    assert "chat_pcq_" not in out.getvalue() and "secret" not in out.getvalue()
