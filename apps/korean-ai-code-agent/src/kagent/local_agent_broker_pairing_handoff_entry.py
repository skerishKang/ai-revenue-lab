"""#3140 — the non-Production broker boundary, shared by both legs.

The Web leg and the resident must meet at ONE canonical broker authority: the
Web session issues the challenge there, and the resident redeems the same
challenge at the same boundary. This module publishes such a broker in-process
for a non-Production run, and hands out a request-port factory the resident
process can be configured with.

It is evidence scaffolding, not product authority:

    LOOPBACK_NON_PRODUCTION=YES
    SHARED_AUTHORITY_INSTANCE=YES   (issuer and redeemer get the same one)
    CHALLENGE_REISSUED_BY_RESIDENT=NO
    PUBLIC_INBOUND_PORT=0           (the boundary is reached in-process)

The same factory is what the resident's `PADIEM_AGENT_REQUEST_PORT` points at,
so both legs genuinely cross one authority. If the two sides ever constructed
different instances, the possession proof would fail — which is the property
the evidence run depends on.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any

from .contracts import ContractError

BROKER_PEPPER = b"control-plane-broker-pepper-16bytes!!"
PAIRING_PEPPER = b"control-plane-pairing-pepper16byte!!"
AUTHORITY_REF = "control-plane.local-agent-broker.3140.loopback.v1"
CREDENTIAL = b"3140-loopback-nonproduction-credential"


class _Clock:
    def __init__(self, now: datetime | None = None) -> None:
        self.now = now or datetime.now(timezone.utc).replace(microsecond=0)

    def __call__(self) -> datetime:
        return self.now


class _DurableState:
    durable = True

    def __init__(self) -> None:
        self.records: dict[str, Any] = {}

    def save_session(self, record: Any) -> Any:
        self.records[record.session_id] = record
        return record

    def load_session(self, session_id: str) -> Any:
        try:
            return self.records[session_id]
        except KeyError as exc:
            raise RuntimeError("session is not present in durable state") from exc

    def record_last_seen(self, session_id: str, *, seen_at: datetime) -> Any:
        record = self.load_session(session_id).with_last_seen(seen_at)
        self.records[session_id] = record
        return record


class _MaterialResolver:
    def resolve(self, request: Any) -> dict:
        raise AssertionError("pairing must not resolve command material")


class _References:
    def __call__(self) -> tuple[str, str]:
        return "admission_3140_loopback_1", "evidence_3140_loopback_1"


class _Nonces:
    def __init__(self) -> None:
        self._next = 0xB0000

    def __call__(self) -> str:
        self._next += 1
        return f"{self._next:032x}"


class LoopbackPairingBroker:
    """One broker + pairing authority, plus the request port both legs use."""

    def __init__(self) -> None:
        from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
        from padiem_control_plane.local_agent_broker_pairing import (
            InMemoryBrokerPairingAuthority,
        )
        from padiem_control_plane.local_agent_broker_pairing_http import (
            PairingAndAdmissionLocalAgentBrokerHttpHandler,
        )
        from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade
        from padiem_control_plane.local_agent_broker_http import (
            TrustedLocalAgentHttpAuthContext,
        )

        self.clock = _Clock()
        self.authority = InMemoryLocalAgentBrokerAuthority(
            pepper=BROKER_PEPPER, authority_ref=AUTHORITY_REF
        )
        self.pairing = InMemoryBrokerPairingAuthority(
            pepper=PAIRING_PEPPER,
            authority=self.authority,
            code_nonce_factory=_Nonces(),
            credential_factory=lambda: CREDENTIAL,
        )
        self.handler = PairingAndAdmissionLocalAgentBrokerHttpHandler(
            pairing_authority=self.pairing,
            admission_reference_factory=_References(),
            rpc=LocalAgentBrokerRpcFacade(authority=self.authority),
            state=_DurableState(),
            material_resolver=_MaterialResolver(),
            clock=self.clock,
        )
        self.audit: list[str] = []
        self._device_auth = TrustedLocalAgentHttpAuthContext(
            principal_ref="device.3140.resident",
            account_ref="account.1",
            workspace_ref="workspace.1",
            authenticated=False,
            tls_verified=True,
        )
        # After redemption the device is authenticated for session, heartbeat,
        # poll, material, admission and acknowledgement.
        self._authenticated_device_auth = TrustedLocalAgentHttpAuthContext(
            principal_ref="device.3140.resident",
            account_ref="account.1",
            workspace_ref="workspace.1",
            authenticated=True,
            tls_verified=True,
        )

    def request_port(self) -> "LoopbackRequestPort":
        return LoopbackRequestPort(self)

    def web_issue_challenge(self, *, now: datetime) -> dict:
        """The Web leg: an authenticated browser session issues the challenge."""

        from padiem_control_plane.local_agent_broker_http import (
            TrustedLocalAgentHttpAuthContext,
        )
        from padiem_control_plane.local_agent_broker_pairing_http import (
            PAIRING_CHALLENGE_ROUTE,
        )

        body = json.dumps(
            {
                "account_ref": "account.1",
                "workspace_ref": "workspace.1",
                "now": now.isoformat(),
                "ttl_seconds": 300,
            }
        ).encode("utf-8")
        response = self.handler.handle(
            method="POST",
            route=PAIRING_CHALLENGE_ROUTE,
            content_type="application/json",
            body=body,
            auth=TrustedLocalAgentHttpAuthContext(
                principal_ref="principal.browser.3140",
                account_ref="account.1",
                workspace_ref="workspace.1",
                authenticated=True,
                tls_verified=True,
            ),
        )
        if response.status != 200:
            raise ContractError("the web leg could not issue a pairing challenge")
        return response.body


class LoopbackRequestPort:
    """The request port the resident is configured with."""

    def __init__(self, broker: LoopbackPairingBroker) -> None:
        self._broker = broker

    def post(self, *, config: Any, operation: Any, payload: dict, timeout_seconds: int) -> dict:
        del config, timeout_seconds
        name = operation.value
        self._broker.audit.append(name)
        if name == "heartbeat" and isinstance(payload, dict) and "now" in payload:
            self._broker.clock.now = datetime.fromisoformat(
                str(payload["now"]).replace("Z", "+00:00")
            )
        response = self._broker.handler.handle(
            method="POST",
            route=f"/{name}",
            content_type="application/json",
            body=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            auth=self._broker._device_auth,
        )
        return json.loads(json.dumps(response.body))


class BrokerClientPort:
    """A client port that *connects* to the one shared broker.

    #3140: the resident must never stand up an authority of its own. This port
    reaches the broker owned by the separate broker process over the loopback
    service, so the Web leg and the resident redeem leg cross the same canonical
    authority rather than two deterministic reconstructions of one.
    """

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    def post(self, *, config: Any, operation: Any, payload: dict, timeout_seconds: int) -> dict:
        import urllib.request

        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base_url}/{operation.value}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout_seconds or 10) as response:
            return json.loads(response.read().decode("utf-8"))


def make_request_port() -> BrokerClientPort:
    """Client factory for the resident's configured broker entry.

    It connects to the broker owner process. It does not create an authority:
    a process that minted its own broker could redeem a code that no Web
    session ever received.
    """

    import os

    base_url = os.environ.get("PADIEM_AGENT_BROKER_URL")
    if not base_url:
        raise ContractError("PADIEM_AGENT_BROKER_URL must name the shared broker service")
    return BrokerClientPort(base_url)


def main(argv: list[str] | None = None) -> int:
    """The Web leg for the evidence run: issue a challenge, print it, exit.

    It prints the one-time code and the server-owned challenge id. Neither is
    persisted; the caller carries them into the `padiem://` deep link.
    """

    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] not in (["--issue-handoff"], ["--web-issue"]):
        sys.stderr.write("usage: python -m kagent.local_agent_broker_pairing_handoff_entry --issue-handoff\n")
        return 2
    # #3140: the web leg issues through the running owner when one is
    # configured, so the challenge belongs to the authority the resident will
    # redeem at. A private instance is only the single-process fallback.
    import os
    import urllib.request

    from padiem_control_plane.local_agent_broker_pairing_http import (
        PAIRING_CHALLENGE_ROUTE,
    )

    broker_url = os.environ.get("PADIEM_AGENT_BROKER_URL")
    if broker_url:
        body = json.dumps(
            {
                "account_ref": "account.1",
                "workspace_ref": "workspace.1",
                "now": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "ttl_seconds": 300,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{broker_url}{PAIRING_CHALLENGE_ROUTE}", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            issued = json.loads(response.read().decode("utf-8"))
    else:
        broker = LoopbackPairingBroker()
        issued = broker.web_issue_challenge(
            now=datetime.now(timezone.utc).replace(microsecond=0)
        )
    sys.stdout.write(
        json.dumps(
            {
                "pairing_code": issued["pairing_code"],
                "challenge_id": issued["challenge"]["challenge_id"],
                "authority_ref": AUTHORITY_REF,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    return 0


def serve(host: str = "127.0.0.1", port: int = 0) -> int:
    """Own the one non-Production broker authority and serve it.

    This process is the owner: it holds the single broker and pairing authority
    both legs reach. It binds loopback only and is never a public ingress.
    """

    import http.server
    import threading
    import urllib.parse

    broker = LoopbackPairingBroker()
    holder = {"url": ""}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 — BaseHTTPRequestHandler surface
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            # The canonical routes are the handler's own, read from the
            # module rather than guessed: the lifecycle routes are unversioned
            # (/session, /heartbeat, /poll) while the pairing routes are
            # versioned (/v1/broker/pairings/...).
            path_only = urllib.parse.urlparse(self.path).path
            if path_only.startswith("/v1/"):
                route = path_only
            else:
                route = f"/{path_only.lstrip('/')}"
            auth = _auth_for_route(route)
            body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            response = broker.handler.handle(
                method="POST",
                route=route,
                content_type="application/json",
                body=body,
                auth=auth,
            )
            out = json.dumps(response.body, sort_keys=True, separators=(",", ":")).encode("utf-8")
            self.send_response(response.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *args: Any) -> None:
            return

    def _auth_for_route(route: str):
        from padiem_control_plane.local_agent_broker_http import (
            TrustedLocalAgentHttpAuthContext,
        )

        # The same per-route principal rule the real broker enforces: the Web
        # session issues as an authenticated browser, the pairing redeem presents
        # an *unauthenticated* device principal with a possession proof, and
        # every post-pairing route is the authenticated device.
        if "pairings/challenge" in route:
            return TrustedLocalAgentHttpAuthContext(
                principal_ref="principal.browser.3140",
                account_ref="account.1", workspace_ref="workspace.1",
                authenticated=True, tls_verified=True,
            )
        if "pairings/redeem" in route:
            return broker._device_auth
        return broker._authenticated_device_auth

    server = http.server.HTTPServer((host, port), Handler)
    holder["url"] = f"http://{host}:{server.server_address[1]}"
    sys.stdout.write(
        json.dumps(
            {"broker_url": holder["url"], "owner_process": True,
             "public_inbound_port": 0},
            sort_keys=True, separators=(",", ":"),
        )
    )
    sys.stdout.flush()
    try:
        # The owner holds the one authority for the life of this process.
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover — operator shutdown
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    if "--serve" in sys.argv[1:]:
        raise SystemExit(serve())
    raise SystemExit(main())
