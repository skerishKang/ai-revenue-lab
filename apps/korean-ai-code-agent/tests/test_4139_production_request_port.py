from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from kagent.contracts import ContractError
from kagent.local_agent_broker_pairing_client import (
    BrokerPairingHttpsOperation,
    StdlibPinnedHttpsBrokerPairingJsonRequestPort,
)
from kagent.local_agent_broker_production_entry import (
    BROKER_URL_ENV,
    PRODUCTION_REQUEST_PORT_FACTORY,
    PinnedBrokerOriginJsonRequestPort,
    make_production_request_port,
)
from kagent.local_agent_resident_process import (
    BrokerEntry,
    default_transport_config,
    main as resident_main,
)
from kagent.local_agent_secure_transport import (
    OutboundBrokerEndpoint,
    OutboundTransportConfig,
    OutboundTransportMode,
)

ORIGIN = "https://local-agent.padiem.net"
OTHER_ORIGIN = "https://other.padiem.net"

#: Every value here is refused by the strict pin. Each one is a *boundary* an
#: operator could plausibly type and that would otherwise carry the device
#: credential somewhere no deployment selected: cleartext, a non-443 port, URL
#: credentials, data in the authority, or a non-HTTP scheme.
REFUSED_URLS = (
    "http://local-agent.padiem.net",
    f"{ORIGIN}:8443",
    "https://user:pass@local-agent.padiem.net",
    f"{ORIGIN}/?a=1",
    f"{ORIGIN}/#fragment",
    "wss://local-agent.padiem.net",
    "local-agent.padiem.net",
    "https://",
    "",
    "   ",
)


class _Config:
    """A transport configuration shaped like ``OutboundTransportConfig``.

    Used only where ``OutboundBrokerEndpoint`` itself cannot express the value
    under test — it refuses a non-443 port outright — so the port's own check can
    be exercised independently of the dataclass that normally enforces it.
    """

    def __init__(self, url: str | None) -> None:
        self.endpoint = type("Endpoint", (), {"url": url})()


def _config(url: str = f"{ORIGIN}:443/broker") -> OutboundTransportConfig:
    return OutboundTransportConfig(
        endpoint=OutboundBrokerEndpoint(
            endpoint_ref="broker_endpoint_production_port_test",
            url=url,
            mode=OutboundTransportMode.HTTPS_LONG_POLL,
        ),
        heartbeat_seconds=30,
        poll_timeout_seconds=15,
        max_response_bytes=65_536,
    )


class _RecordingTransport:
    """Records every forwarded call, so "no bytes left the process" is provable."""

    def __init__(self, *, result: dict | None = None, error: Exception | None = None) -> None:
        self.calls: list[tuple] = []
        self._result = {"ok": True} if result is None else result
        self._error = error

    def post(self, *, config, operation, payload, timeout_seconds):
        self.calls.append((config, operation, payload, timeout_seconds))
        if self._error is not None:
            raise self._error
        return self._result


class DeclaredOriginTests(unittest.TestCase):
    def test_a_missing_declared_origin_refuses_by_name(self) -> None:
        with self.assertRaises(ContractError) as raised:
            make_production_request_port({})
        self.assertIn(BROKER_URL_ENV, str(raised.exception))

    def test_no_transport_exists_when_the_factory_refuses(self) -> None:
        # The refusal must happen before a transport is constructed, so nothing
        # is ever dialled for a boundary that was never accepted.
        with mock.patch.object(
            StdlibPinnedHttpsBrokerPairingJsonRequestPort,
            "__init__",
            side_effect=AssertionError("a transport was constructed for a refused origin"),
        ):
            for url in REFUSED_URLS:
                with self.subTest(url=url):
                    with self.assertRaises(ContractError):
                        make_production_request_port({BROKER_URL_ENV: url})

    def test_the_declared_origin_is_accepted_only_when_it_is_pinned(self) -> None:
        for url in (ORIGIN, f"{ORIGIN}:443", f"{ORIGIN}/broker"):
            with self.subTest(url=url):
                port = make_production_request_port({BROKER_URL_ENV: url})
                self.assertIsInstance(port, PinnedBrokerOriginJsonRequestPort)


class OneBoundaryTests(unittest.TestCase):
    def test_the_declared_origin_and_the_transport_configuration_must_agree(self) -> None:
        transport = _RecordingTransport()
        port = PinnedBrokerOriginJsonRequestPort(declared_origin=ORIGIN, transport=transport)
        with self.assertRaises(ContractError):
            port.post(
                config=_config(f"{OTHER_ORIGIN}:443/broker"),
                operation=BrokerPairingHttpsOperation.REDEEM,
                payload={"pairing_code": "0" * 32},
                timeout_seconds=10,
            )
        # The credential-bearing payload never reached the transport.
        self.assertEqual(transport.calls, [])

    def test_a_port_difference_is_a_different_boundary(self) -> None:
        transport = _RecordingTransport()
        port = PinnedBrokerOriginJsonRequestPort(declared_origin=ORIGIN, transport=transport)
        with self.assertRaises(ContractError):
            port.post(
                config=_Config("https://local-agent.padiem.net:8443/broker"),
                operation=BrokerPairingHttpsOperation.REDEEM,
                payload={"pairing_code": "0" * 32},
                timeout_seconds=10,
            )
        self.assertEqual(transport.calls, [])

    def test_a_declared_base_path_must_match_the_transport_configuration(self) -> None:
        transport = _RecordingTransport()
        port = PinnedBrokerOriginJsonRequestPort(
            declared_origin=f"{ORIGIN}/other", transport=transport
        )
        with self.assertRaises(ContractError):
            port.post(
                config=_config(f"{ORIGIN}:443/broker"),
                operation=BrokerPairingHttpsOperation.REDEEM,
                payload={},
                timeout_seconds=10,
            )
        self.assertEqual(transport.calls, [])

    def test_a_path_less_declared_origin_lets_the_configuration_own_the_mount_point(self) -> None:
        transport = _RecordingTransport(result={"ok": True, "sentinel": "forwarded"})
        port = PinnedBrokerOriginJsonRequestPort(declared_origin=ORIGIN, transport=transport)
        config = _config(f"{ORIGIN}:443/broker")
        payload = {"pairing_code": "0" * 32}
        result = port.post(
            config=config,
            operation=BrokerPairingHttpsOperation.REDEEM,
            payload=payload,
            timeout_seconds=10,
        )
        # Exactly one call, forwarded unchanged: the port rewrites nothing it
        # was handed, so the transport contract stays the transport's.
        self.assertEqual(transport.calls, [(config, BrokerPairingHttpsOperation.REDEEM, payload, 10)])
        self.assertEqual(result, {"ok": True, "sentinel": "forwarded"})

    def test_a_configuration_without_a_canonical_endpoint_is_refused(self) -> None:
        transport = _RecordingTransport()
        port = PinnedBrokerOriginJsonRequestPort(declared_origin=ORIGIN, transport=transport)
        for config in (object(), _Config(None), _Config("")):
            with self.subTest(config=repr(config)):
                with self.assertRaises(ContractError):
                    port.post(
                        config=config,
                        operation=BrokerPairingHttpsOperation.REDEEM,
                        payload={},
                        timeout_seconds=10,
                    )
        self.assertEqual(transport.calls, [])

    def test_a_refusal_from_the_transport_is_never_swallowed(self) -> None:
        transport = _RecordingTransport(
            error=ContractError("physical broker returned HTTP status 403")
        )
        port = PinnedBrokerOriginJsonRequestPort(declared_origin=ORIGIN, transport=transport)
        with self.assertRaises(ContractError):
            port.post(
                config=_config(),
                operation=BrokerPairingHttpsOperation.REDEEM,
                payload={},
                timeout_seconds=10,
            )
        self.assertEqual(len(transport.calls), 1)


class CompositionTests(unittest.TestCase):
    def test_the_default_transport_is_the_existing_canonical_pinned_port(self) -> None:
        port = make_production_request_port({BROKER_URL_ENV: ORIGIN})
        self.assertIsInstance(port._transport, StdlibPinnedHttpsBrokerPairingJsonRequestPort)

    def test_the_documented_factory_path_resolves_to_this_factory(self) -> None:
        module_name, _, attribute = PRODUCTION_REQUEST_PORT_FACTORY.partition(":")
        module = importlib.import_module(module_name)
        self.assertIs(getattr(module, attribute), make_production_request_port)

    def test_the_declared_origin_agrees_with_the_resident_default_configuration(self) -> None:
        # Load-bearing cross-check: the documented deployment value and the
        # Resident's own default endpoint must name one authority. If either side
        # moves scheme, host or port, this composition stops accepting.
        port = make_production_request_port({BROKER_URL_ENV: ORIGIN})
        config = default_transport_config()
        port._assert_one_boundary(config)
        with self.assertRaises(ContractError):
            port._assert_one_boundary(_Config(f"{OTHER_ORIGIN}:443/broker"))

    def test_safe_dict_never_exposes_the_origin_or_host(self) -> None:
        port = make_production_request_port({BROKER_URL_ENV: ORIGIN})
        rendered = json.dumps(port.safe_dict(), sort_keys=True)
        self.assertNotIn("padiem.net", rendered)
        self.assertNotIn("https", rendered)
        self.assertIs(port.safe_dict()["second_broker_origin"], False)


class ResidentBoundaryTests(unittest.TestCase):
    def _environment(self, *, url: str, credential_dir: str) -> dict[str, str]:
        return {
            "PADIEM_AGENT_DEVICE_ID": "device.4139.production-port",
            "PADIEM_AGENT_AUTHORITY_REF": "authority.4139.production-port",
            "PADIEM_AGENT_REQUEST_PORT": PRODUCTION_REQUEST_PORT_FACTORY,
            "PADIEM_AGENT_CREDENTIAL_DIR": credential_dir,
            BROKER_URL_ENV: url,
        }

    def test_the_resident_entry_composes_the_production_port(self) -> None:
        with tempfile.TemporaryDirectory() as credential_dir:
            with mock.patch.dict(
                os.environ,
                self._environment(url=ORIGIN, credential_dir=credential_dir),
                clear=True,
            ):
                entry = BrokerEntry.from_environment()
        self.assertIsInstance(entry, BrokerEntry)
        self.assertIsInstance(entry.request_port, PinnedBrokerOriginJsonRequestPort)

    def test_a_rejected_origin_refuses_instead_of_crashing_the_resident(self) -> None:
        # Without the bounded refusal in ``main``, the factory's ContractError
        # escapes the process as an unhandled traceback.
        with tempfile.TemporaryDirectory() as credential_dir:
            with mock.patch.dict(
                os.environ,
                self._environment(
                    url="http://local-agent.padiem.net", credential_dir=credential_dir
                ),
                clear=True,
            ):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = resident_main([])
        self.assertEqual(code, 2)
        payload = json.loads(out.getvalue().strip().splitlines()[-1])
        self.assertEqual(payload["status"], "refused")
        self.assertEqual(payload["reason"], "configured_broker_boundary_rejected")


if __name__ == "__main__":
    unittest.main()
