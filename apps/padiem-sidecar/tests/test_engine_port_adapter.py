"""B53 server-mediated EnginePort adapter tests (#2204 S8-ACT1).

Network-free: every transport is an injected in-test seam. Proves the
boundary locks — canonical EnginePort reuse, server-only caller identity,
fail-closed config, reviewed-capability-only mapping, and no Control Plane /
B14 / provider authority inside B53.
"""

import json
import sys
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _APP_ROOT.parents[1]
sys.path.insert(0, str(_APP_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "packages" / "padiem-embedded-runtime"))

from app.engine_port_adapter import (  # noqa: E402
    CALLER_CREDENTIAL_HEADER,
    CALLER_ID_HEADER,
    ENGINE_APP_ID_ENV,
    ENGINE_CALLER_CREDENTIAL_ENV,
    ENGINE_CALLER_ID_ENV,
    ENGINE_EXECUTE_PATH,
    ENGINE_MODEL_ROUTES_ENV,
    EngineCallerConfig,
    EngineIngressResponse,
    ServerMediatedEnginePort,
    build_server_engine_port,
    engine_caller_config_from_environ,
)
from app.product_adapter import ProductAdapter, SidecarProductConfig  # noqa: E402
from padiem_embedded_runtime.engine_port import (  # noqa: E402
    ALLOWED_FAKE_CAPABILITIES,
    DeterministicFakeEnginePort,
    EnginePort,
)
from padiem_embedded_runtime.errors import SidecarContractError  # noqa: E402

SERVER_CALLER_ID = "b53-sidecar-server"
SERVER_APP_ID = "padiem-sidecar-host"
SERVER_CREDENTIAL = "s" * 48
ROUTES = {"context.project": "route-alpha", "notice.render": "route-beta"}


def make_caller_config() -> EngineCallerConfig:
    return EngineCallerConfig(
        app_id=SERVER_APP_ID,
        caller_id=SERVER_CALLER_ID,
        credential=SERVER_CREDENTIAL,
        model_routes=dict(ROUTES),
    )


def make_port(transport=None, *, status=200, answer="projected", raw_body=None):
    body = raw_body
    if body is None:
        body = json.dumps({"ok": True, "answer": answer}).encode("utf-8")
    return ServerMediatedEnginePort(
        transport=transport if transport is not None else RecordingTransport(status=status, body=body),
        caller_config=make_caller_config(),
    )


class RecordingTransport:
    def __init__(self, *, status=200, body=b'{"ok": true, "answer": "projected"}', raises=None):
        self.calls = []
        self._status = status
        self._body = body
        self._raises = raises

    def request(self, *, method, path, headers, body):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "headers": dict(headers),
                "body": json.loads(body.decode("utf-8")),
            }
        )
        if self._raises is not None:
            raise self._raises
        return EngineIngressResponse(status=self._status, body=self._body)


class CanonicalContractTests(unittest.TestCase):
    def test_real_engine_port_implements_canonical_contract(self):
        self.assertTrue(issubclass(ServerMediatedEnginePort, EnginePort))
        port = make_port()
        self.assertIsInstance(port, EnginePort)
        response = port.invoke_capability("context.project", {"text": "hi"})
        self.assertIsInstance(response, dict)
        self.assertEqual(response, {"capability": "context.project", "ok": True, "answer": "projected"})

    def test_reviewed_capabilities_match_ip_sidecar_fake_review(self):
        from app.engine_port_adapter import REVIEWED_ENGINE_CAPABILITIES

        self.assertEqual(REVIEWED_ENGINE_CAPABILITIES, ALLOWED_FAKE_CAPABILITIES)

    def test_unreviewed_capability_fails_closed(self):
        transport = RecordingTransport()
        port = make_port(transport=transport)
        with self.assertRaises(SidecarContractError):
            port.invoke_capability("tool.execute", {"text": "hi"})
        with self.assertRaises(SidecarContractError):
            port.invoke_capability("notice.render.extra", {"text": "hi"})
        self.assertEqual(transport.calls, [])


class FailClosedConfigurationTests(unittest.TestCase):
    def test_missing_engine_transport_fails_closed(self):
        config = make_caller_config()
        with self.assertRaises(SidecarContractError):
            ServerMediatedEnginePort(transport=None, caller_config=config)
        with self.assertRaises(SidecarContractError):
            ServerMediatedEnginePort(transport=object(), caller_config=config)

    def test_missing_engine_caller_identity_fails_closed(self):
        with self.assertRaises(SidecarContractError):
            EngineCallerConfig(app_id=SERVER_APP_ID, caller_id=None, credential=SERVER_CREDENTIAL, model_routes=dict(ROUTES))
        with self.assertRaises(SidecarContractError):
            EngineCallerConfig(app_id=SERVER_APP_ID, caller_id="", credential=SERVER_CREDENTIAL, model_routes=dict(ROUTES))
        with self.assertRaises(SidecarContractError):
            EngineCallerConfig(app_id=None, caller_id=SERVER_CALLER_ID, credential=SERVER_CREDENTIAL, model_routes=dict(ROUTES))
        with self.assertRaises(SidecarContractError):
            EngineCallerConfig(app_id=SERVER_APP_ID, caller_id=SERVER_CALLER_ID, credential="short", model_routes=dict(ROUTES))
        with self.assertRaises(SidecarContractError):
            EngineCallerConfig(app_id=SERVER_APP_ID, caller_id=SERVER_CALLER_ID, credential=SERVER_CREDENTIAL, model_routes={"context.project": "route-alpha"})
        with self.assertRaises(SidecarContractError):
            EngineCallerConfig(
                app_id=SERVER_APP_ID,
                caller_id="evil caller;inject",
                credential=SERVER_CREDENTIAL,
                model_routes=dict(ROUTES),
            )

    def test_environment_composition_fails_closed_and_succeeds(self):
        with self.assertRaises(SidecarContractError):
            engine_caller_config_from_environ({})
        with self.assertRaises(SidecarContractError):
            engine_caller_config_from_environ({ENGINE_MODEL_ROUTES_ENV: "not-json"})
        partial = {
            ENGINE_APP_ID_ENV: SERVER_APP_ID,
            ENGINE_CALLER_ID_ENV: SERVER_CALLER_ID,
        }
        with self.assertRaises(SidecarContractError):
            engine_caller_config_from_environ(partial)
        full = dict(partial)
        full[ENGINE_CALLER_CREDENTIAL_ENV] = SERVER_CREDENTIAL
        full[ENGINE_MODEL_ROUTES_ENV] = json.dumps(ROUTES)
        port = build_server_engine_port(transport=RecordingTransport(), environ=full)
        response = port.invoke_capability("notice.render", {"text": "hello"})
        self.assertEqual(response["capability"], "notice.render")


class CredentialContainmentTests(unittest.TestCase):
    def test_engine_caller_credential_never_in_public_projection(self):
        port = make_port()
        public = json.dumps(port.describe(), ensure_ascii=False)
        self.assertNotIn(SERVER_CREDENTIAL, public)
        self.assertNotIn(SERVER_CALLER_ID, public)
        self.assertNotIn(SERVER_APP_ID, public)
        self.assertNotIn(ROUTES["context.project"], public)
        self.assertNotIn(SERVER_CREDENTIAL, repr(make_caller_config()))
        self.assertNotIn(SERVER_CREDENTIAL, json.dumps(make_caller_config().to_public_dict()))

    def test_credential_never_in_error_or_log_text(self):
        transport = RecordingTransport(
            body=json.dumps(
                {"ok": False, "error": {"code": "engine_unavailable", "message": f"downstream {SERVER_CREDENTIAL}"}}
            ).encode("utf-8")
        )
        port = make_port(transport=transport)
        with self.assertRaises(SidecarContractError) as ctx:
            port.invoke_capability("context.project", {"text": "hi"})
        self.assertNotIn(SERVER_CREDENTIAL, str(ctx.exception))
        self.assertIn("engine_unavailable", str(ctx.exception))

    def test_browser_payload_cannot_override_engine_caller_identity(self):
        transport = RecordingTransport()
        port = make_port(transport=transport)
        for payload in (
            {"text": "hi", "caller_id": "evil"},
            {"text": "hi", CALLER_ID_HEADER: "evil"},
            {"text": "hi", CALLER_CREDENTIAL_HEADER: "evil" * 12},
            {"text": "hi", "credential": "evil" * 12},
        ):
            with self.assertRaises(SidecarContractError):
                port.invoke_capability("context.project", payload)
        self.assertEqual(transport.calls, [])
        port.invoke_capability("context.project", {"text": "hi"})
        headers = transport.calls[0]["headers"]
        self.assertEqual(headers[CALLER_ID_HEADER], SERVER_CALLER_ID)
        self.assertEqual(headers[CALLER_CREDENTIAL_HEADER], SERVER_CREDENTIAL)

    def test_browser_payload_cannot_mint_tenant_or_subject_authority(self):
        transport = RecordingTransport()
        port = make_port(transport=transport)
        for payload in (
            {"text": "hi", "app_id": "evil-app"},
            {"text": "hi", "tenant_id": "evil-tenant"},
            {"text": "hi", "subject_id": "evil-subject"},
            {"text": "hi", "session_id": "evil-session"},
        ):
            with self.assertRaises(SidecarContractError):
                port.invoke_capability("context.project", payload)
        self.assertEqual(transport.calls, [])
        port.invoke_capability("context.project", {"text": "hi"})
        body = transport.calls[0]["body"]
        self.assertEqual(body["app_id"], SERVER_APP_ID)
        self.assertNotIn("tenant_id", body)
        self.assertNotIn("subject_id", body)


class CapabilityMappingTests(unittest.TestCase):
    def test_reviewed_capability_maps_to_engine_request(self):
        transport = RecordingTransport()
        port = make_port(transport=transport)
        response = port.invoke_capability("context.project", {"text":  "  spaced text  "})
        self.assertEqual(response["ok"], True)
        self.assertEqual(len(transport.calls), 1)
        call = transport.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["path"], ENGINE_EXECUTE_PATH)
        self.assertEqual(call["headers"][CALLER_ID_HEADER], SERVER_CALLER_ID)
        self.assertEqual(call["headers"][CALLER_CREDENTIAL_HEADER], SERVER_CREDENTIAL)
        body = call["body"]
        self.assertEqual(body["app_id"], SERVER_APP_ID)
        self.assertEqual(body["messages"], [{"role": "user", "content": "spaced text"}])
        agent = body["agent"]
        self.assertEqual(agent["id"], "padiem-sidecar-context-project")
        self.assertEqual(agent["model_policy"], {"model": ROUTES["context.project"]})
        for field in ("title", "description", "system_instruction", "task_type", "optimize_for", "max_tokens"):
            self.assertIn(field, agent)

    def test_payload_text_bounds_enforced(self):
        transport = RecordingTransport()
        port = make_port(transport=transport)
        with self.assertRaises(SidecarContractError):
            port.invoke_capability("context.project", {"text": "x" * 8_001})
        with self.assertRaises(SidecarContractError):
            port.invoke_capability("context.project", {"text": "   "})
        with self.assertRaises(SidecarContractError):
            port.invoke_capability("context.project", "not-a-mapping")
        self.assertEqual(transport.calls, [])


class TransportFailureProjectionTests(unittest.TestCase):
    def test_transport_error_projects_safe_failure(self):
        port = make_port(transport=RecordingTransport(raises=RuntimeError(f"socket {SERVER_CREDENTIAL}")))
        with self.assertRaises(SidecarContractError) as ctx:
            port.invoke_capability("context.project", {"text": "hi"})
        self.assertEqual(str(ctx.exception), "engine transport failure")

    def test_non_2xx_and_malformed_responses_fail_closed(self):
        port = make_port(transport=RecordingTransport(status=503, body=b'{"ok": true, "answer": "x"}'))
        with self.assertRaises(SidecarContractError):
            port.invoke_capability("context.project", {"text": "hi"})
        port = make_port(transport=RecordingTransport(body=b"not-json"))
        with self.assertRaises(SidecarContractError):
            port.invoke_capability("context.project", {"text": "hi"})
        port = make_port(transport=RecordingTransport(body=b'{"ok": true}'))
        with self.assertRaises(SidecarContractError):
            port.invoke_capability("context.project", {"text": "hi"})
        port = make_port(transport=RecordingTransport(body=b"[1, 2]"))
        with self.assertRaises(SidecarContractError):
            port.invoke_capability("context.project", {"text": "hi"})


class ProductAdapterInjectionTests(unittest.TestCase):
    def _config(self):
        return SidecarProductConfig(
            product_id="padiem-sidecar",
            product_name="Padiem Sidecar",
            install_mode="embed",
            theme="dark",
            brand="B53",
            locale="ko",
        )

    def test_fake_default_regression_passes(self):
        adapter = ProductAdapter(self._config())
        self.assertIsInstance(adapter.engine_port, DeterministicFakeEnginePort)
        response = adapter.engine_port.invoke_capability("notice.render", {"text": "hi"})
        self.assertEqual(response, {"ok": True})

    def test_real_port_injection_preserved_and_non_canonical_rejected(self):
        port = make_port()
        adapter = ProductAdapter(self._config(), engine_port=port)
        self.assertIs(adapter.engine_port, port)
        with self.assertRaises(SidecarContractError):
            ProductAdapter(self._config(), engine_port=object())


class SourceBoundaryScanTests(unittest.TestCase):
    FORBIDDEN_TOKENS = (
        "CONTROL_PLANE_IDENTITY",
        "B14_SERVICE",
        "GEMINI_API_KEY",
        "GOOGLE_MAPS_API_KEY",
        "OPENAI_API_KEY",
    )

    def _app_sources(self):
        return sorted((_APP_ROOT / "app").glob("*.py"))

    def test_no_control_plane_binding_in_b53(self):
        for path in self._app_sources():
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("CONTROL_PLANE_IDENTITY", source, str(path))

    def test_no_b14_binding_in_b53(self):
        for path in self._app_sources():
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("B14_SERVICE", source, str(path))
            self.assertNotIn("B14", path.read_text(encoding="utf-8"), str(path))

    def test_no_provider_credential_in_b53(self):
        for path in self._app_sources():
            source = path.read_text(encoding="utf-8")
            for token in self.FORBIDDEN_TOKENS[2:]:
                self.assertNotIn(token, source, str(path))


if __name__ == "__main__":
    unittest.main()
