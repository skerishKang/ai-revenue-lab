"""B14 health classification regressions for the B62 Cloudflare preflight (#3109).

The defect these tests pin: ``read_b14_health()`` used to wrap the whole B14
request in ``except Exception: pass``, so a DNS failure, a timeout, a malformed
body and an arbitrary programming error all produced the *same* projection as a
legitimately unavailable service. A broken probe was therefore indistinguishable
from a healthy one.

These tests are network-free: ``get_json`` is replaced, so nothing here can reach
Cloudflare, the B14 service, or any provider.
"""

from __future__ import annotations

import importlib.util
import json
import socket
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "b62_cloudflare_preflight.py"

spec = importlib.util.spec_from_file_location("b62_cloudflare_preflight", SCRIPT)
assert spec is not None and spec.loader is not None
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


def _patch_get_json(testcase, *, status, payload=None, raises=None):
    """Replace the module's transport with a deterministic double."""

    def fake_get_json(url, headers=None):
        if raises is not None:
            raise raises
        return status, payload

    testcase.addCleanup(setattr, preflight, "get_json", preflight.get_json)
    preflight.get_json = fake_get_json


def _healthy_payload(**overrides):
    payload = {
        "status": "ok",
        "business14": {
            "provider_mode": "live",
            "has_key": True,
            "catalog_models": "3",
        },
    }
    payload.update(overrides)
    return payload


class B14HealthOkTests(unittest.TestCase):
    def test_healthy_service_is_classified_ok(self) -> None:
        _patch_get_json(self, status=200, payload=_healthy_payload())
        state = preflight.read_b14_health()
        self.assertEqual(state["b14_health"], preflight.B14_HEALTH_OK)
        self.assertEqual(state["b14_reason"], preflight.B14_REASON_OK)
        self.assertEqual(state["b14_http"], "200")
        self.assertEqual(state["b14_status"], "ok")
        self.assertEqual(state["b14_provider_mode"], "live")
        self.assertEqual(state["b14_has_key"], "true")
        self.assertEqual(state["b14_catalog_models"], "3")

    def test_ok_reports_a_real_health_state_not_a_placeholder(self) -> None:
        _patch_get_json(self, status=200, payload=_healthy_payload())
        state = preflight.read_b14_health()
        self.assertNotEqual(state["b14_health"], "unavailable")
        self.assertNotEqual(state["b14_reason"], "unknown")

    def test_has_key_false_is_preserved_as_a_real_boolean_fact(self) -> None:
        payload = _healthy_payload()
        payload["business14"]["has_key"] = False
        _patch_get_json(self, status=200, payload=payload)
        self.assertEqual(preflight.read_b14_health()["b14_has_key"], "false")

    def test_absent_business14_block_degrades_fields_not_the_health_state(self) -> None:
        _patch_get_json(self, status=200, payload={"status": "ok"})
        state = preflight.read_b14_health()
        self.assertEqual(state["b14_health"], preflight.B14_HEALTH_OK)
        self.assertEqual(state["b14_provider_mode"], "unknown")
        self.assertEqual(state["b14_has_key"], "unknown")


class B14HealthUnavailableExpectedTests(unittest.TestCase):
    def test_documented_not_configured_state_is_degraded_not_an_error(self) -> None:
        # The B14 service answers HTTP 200 with status "not_configured" when it
        # is intentionally unready (see test_b14_health_truth.py). That is a
        # reachable, degraded service -- categorically different from a probe
        # that could not run at all.
        payload = _healthy_payload(status="not_configured")
        _patch_get_json(self, status=200, payload=payload)
        state = preflight.read_b14_health()
        self.assertEqual(state["b14_health"], preflight.B14_HEALTH_UNAVAILABLE_EXPECTED)
        self.assertEqual(state["b14_reason"], preflight.B14_REASON_SERVICE_UNAVAILABLE)
        self.assertEqual(state["b14_status"], "not_configured")
        self.assertEqual(state["b14_http"], "200")

    def test_non_200_http_is_unavailable_expected_with_the_safe_status(self) -> None:
        _patch_get_json(self, status=503, payload={})
        state = preflight.read_b14_health()
        self.assertEqual(state["b14_health"], preflight.B14_HEALTH_UNAVAILABLE_EXPECTED)
        self.assertEqual(state["b14_reason"], preflight.B14_REASON_HTTP_STATUS)
        self.assertEqual(state["b14_http"], "503")

    def test_unavailable_expected_is_never_confused_with_check_error(self) -> None:
        _patch_get_json(self, status=200, payload=_healthy_payload(status="not_configured"))
        degraded = preflight.read_b14_health()["b14_health"]
        _patch_get_json(self, status=200, payload=[])
        broken = preflight.read_b14_health()["b14_health"]
        self.assertNotEqual(degraded, broken)
        self.assertEqual(degraded, preflight.B14_HEALTH_UNAVAILABLE_EXPECTED)
        self.assertEqual(broken, preflight.B14_HEALTH_CHECK_ERROR)


class B14HealthCheckErrorTests(unittest.TestCase):
    def test_connection_error_is_an_explicit_check_error(self) -> None:
        _patch_get_json(
            self,
            status=0,
            raises=URLError(socket.gaierror("Name or service not known")),
        )
        state = preflight.read_b14_health()
        self.assertEqual(state["b14_health"], preflight.B14_HEALTH_CHECK_ERROR)
        self.assertEqual(state["b14_reason"], preflight.B14_REASON_NETWORK_ERROR)
        self.assertEqual(state["b14_http"], "0")

    def test_transport_runtime_error_is_a_network_check_error(self) -> None:
        # get_json() reports a transport failure as RuntimeError.
        _patch_get_json(self, status=0, raises=RuntimeError("network error while requesting"))
        state = preflight.read_b14_health()
        self.assertEqual(state["b14_health"], preflight.B14_HEALTH_CHECK_ERROR)
        self.assertEqual(state["b14_reason"], preflight.B14_REASON_NETWORK_ERROR)

    def test_timeout_is_distinguished_from_a_generic_network_error(self) -> None:
        _patch_get_json(self, status=0, raises=TimeoutError("timed out"))
        state = preflight.read_b14_health()
        self.assertEqual(state["b14_health"], preflight.B14_HEALTH_CHECK_ERROR)
        self.assertEqual(state["b14_reason"], preflight.B14_REASON_TIMEOUT)

    def test_malformed_json_body_is_a_malformed_response_error(self) -> None:
        # A 200 whose payload is not an object cannot be judged.
        for bad in ([], "not-a-dict", 12, None):
            with self.subTest(payload=bad):
                _patch_get_json(self, status=200, payload=bad)
                state = preflight.read_b14_health()
                self.assertEqual(state["b14_health"], preflight.B14_HEALTH_CHECK_ERROR)
                self.assertEqual(state["b14_reason"], preflight.B14_REASON_MALFORMED_RESPONSE)

    def test_unexpected_exception_is_explicitly_classified(self) -> None:
        _patch_get_json(self, status=0, raises=ValueError("boom"))
        state = preflight.read_b14_health()
        self.assertEqual(state["b14_health"], preflight.B14_HEALTH_CHECK_ERROR)
        self.assertEqual(state["b14_reason"], preflight.B14_REASON_UNEXPECTED_ERROR)

    def test_check_error_is_never_indistinguishable_from_unavailable(self) -> None:
        _patch_get_json(self, status=0, raises=RuntimeError("x"))
        broken = preflight.read_b14_health()
        _patch_get_json(self, status=200, payload=_healthy_payload(status="not_configured"))
        degraded = preflight.read_b14_health()
        self.assertNotEqual(broken["b14_health"], degraded["b14_health"])
        self.assertNotEqual(broken["b14_reason"], degraded["b14_reason"])


class B14SecretContainmentTests(unittest.TestCase):
    SECRET = "sk-live-DO-NOT-LEAK-0123456789abcdef"

    def _public_surface(self, state):
        rendered = json.dumps(state, sort_keys=True)
        summary = "\n".join(preflight.b14_summary_rows(state))
        emitted = "\n".join(
            f"{key}={state[key]}" for key in preflight.B14_STATE_KEYS
        )
        return rendered + summary + emitted

    def test_secret_in_an_exception_message_never_reaches_the_state(self) -> None:
        _patch_get_json(
            self,
            status=0,
            raises=RuntimeError(f"auth failed with Bearer {self.SECRET}"),
        )
        state = preflight.read_b14_health()
        self.assertNotIn(self.SECRET, self._public_surface(state))
        self.assertEqual(state["b14_reason"], preflight.B14_REASON_NETWORK_ERROR)

    def test_secret_in_a_hostile_payload_value_is_reduced_to_a_token(self) -> None:
        payload = _healthy_payload()
        payload["business14"]["provider_mode"] = f"live {self.SECRET}"
        _patch_get_json(self, status=200, payload=payload)
        state = preflight.read_b14_health()
        self.assertNotIn(self.SECRET, self._public_surface(state))
        self.assertEqual(state["b14_provider_mode"], "unknown")

    def test_secret_in_a_hostile_status_value_is_reduced(self) -> None:
        payload = _healthy_payload(status=f"ok\nAuthorization: Bearer {self.SECRET}")
        _patch_get_json(self, status=200, payload=payload)
        state = preflight.read_b14_health()
        self.assertNotIn(self.SECRET, self._public_surface(state))

    def test_raw_response_body_is_never_echoed(self) -> None:
        body = json.dumps(
            _healthy_payload(raw_body=f"-----BEGIN PRIVATE KEY-----\n{self.SECRET}")
        )
        _patch_get_json(self, status=200, payload=json.loads(body))
        state = preflight.read_b14_health()
        surface = self._public_surface(state)
        self.assertNotIn("PRIVATE KEY", surface)
        self.assertNotIn("raw_body", surface)

    def test_non_200_http_error_body_is_not_reflected(self) -> None:
        # get_json() may return a parsed error body; none of it may be emitted.
        _patch_get_json(
            self,
            status=500,
            payload={"error": self.SECRET, "trace": "stack", "detail": "raw"},
        )
        state = preflight.read_b14_health()
        surface = self._public_surface(state)
        self.assertNotIn(self.SECRET, surface)
        self.assertNotIn("stack", surface)
        self.assertEqual(state["b14_health"], preflight.B14_HEALTH_UNAVAILABLE_EXPECTED)

    def test_every_emitted_state_field_is_a_bounded_token(self) -> None:
        _patch_get_json(
            self,
            status=0,
            raises=RuntimeError(f"connection to host failed {self.SECRET}"),
        )
        state = preflight.read_b14_health()
        for key, value in state.items():
            with self.subTest(key=key):
                self.assertNotIn(" ", value)
                self.assertNotIn(self.SECRET, value)
                self.assertLessEqual(len(value), 64)

    def test_reason_codes_are_a_closed_set(self) -> None:
        # Only contract literals are ever emitted, which is what makes the
        # no-secret-output guarantee structural rather than incidental.
        for raiser in (
            lambda: (_ for _ in ()).throw(TimeoutError()),
            lambda: (_ for _ in ()).throw(URLError("x")),
            lambda: (_ for _ in ()).throw(RuntimeError("x")),
            lambda: (_ for _ in ()).throw(ValueError("x")),
        ):
            with self.subTest():
                _patch_get_json(self, status=0, raises=None)
                preflight.get_json = raiser
                state = preflight.read_b14_health()
                self.assertIn(state["b14_reason"], preflight.B14_REASON_CODES)
                self.assertIn(state["b14_health"], preflight.B14_HEALTH_STATES)


class B14StateContractTests(unittest.TestCase):
    def test_b14_state_rejects_an_out_of_contract_health_value(self) -> None:
        state = preflight.b14_state(http="200", health="bogus", reason="bogus")
        self.assertEqual(state["b14_health"], preflight.B14_HEALTH_CHECK_ERROR)
        self.assertEqual(state["b14_reason"], preflight.B14_REASON_UNEXPECTED_ERROR)

    def test_b14_state_emits_exactly_the_declared_keys(self) -> None:
        state = preflight.b14_state(
            http="200", health=preflight.B14_HEALTH_OK, reason=preflight.B14_REASON_OK
        )
        self.assertEqual(tuple(state), preflight.B14_STATE_KEYS)

    def test_safe_remote_token_allows_only_short_opaque_tokens(self) -> None:
        self.assertEqual(preflight.safe_remote_token("live"), "live")
        self.assertEqual(preflight.safe_remote_token("model-3.1"), "model-3.1")
        for bad in ("", "a b", "a\nb", "a=b", "a/b", "x" * 65, None, 5, ["a"]):
            with self.subTest(bad=bad):
                self.assertEqual(preflight.safe_remote_token(bad), "unknown")

    def test_no_silent_exception_swallow_remains_in_read_b14_health(self) -> None:
        # Load-bearing source assertion: the historical defect was a bare
        # `except Exception: pass`. It must not come back in any form.
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("except Exception:\n        pass", source)
        self.assertNotIn("except Exception:\n            pass", source)
        # Every terminal branch of read_b14_health must name a classification.
        body = source.split("def read_b14_health", 1)[1].split("def emit_b14", 1)[0]
        self.assertIn("B14_HEALTH_CHECK_ERROR", body)
        self.assertIn("B14_REASON_UNEXPECTED_ERROR", body)
        self.assertIn("B14_REASON_TIMEOUT", body)
        self.assertIn("B14_REASON_NETWORK_ERROR", body)
        self.assertIn("B14_REASON_MALFORMED_RESPONSE", body)
        self.assertIn("B14_REASON_HTTP_STATUS", body)
        self.assertIn("B14_REASON_SERVICE_UNAVAILABLE", body)
        self.assertIn("B14_REASON_OK", body)


class B14GateSemanticsTests(unittest.TestCase):
    """The fail-open/degrade decision must stay explicit and unchanged."""

    def test_b14_health_does_not_change_the_preflight_exit_code(self) -> None:
        # #3109 decision: DEGRADE_RECORDED_NOT_GATING. A B14 check error must
        # not fail the Cloudflare preflight, because the deploy gate is the
        # Cloudflare worker_state, not an optional downstream probe.
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("FAIL_OPEN_OR_DEGRADE_DECISION = DEGRADE_RECORDED_NOT_GATING", source)
        main_body = source.split("def main()", 1)[1]
        # main() must not raise or return non-zero because of b14.
        self.assertNotIn("read_b14_health()\n    emit_b14(b14)\n    raise", main_body)
        self.assertIn("b14 = read_b14_health()", main_body)
        self.assertIn("emit_b14(b14)", main_body)

    def test_workflow_exposes_the_new_explicit_outputs(self) -> None:
        workflow = (
            ROOT / ".github" / "workflows" / "b62-cloudflare-worker-deploy.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("b14_health: ${{ steps.preflight.outputs.b14_health }}", workflow)
        self.assertIn("b14_reason: ${{ steps.preflight.outputs.b14_reason }}", workflow)

    def test_deploy_gate_remains_the_cloudflare_worker_state(self) -> None:
        workflow = (
            ROOT / ".github" / "workflows" / "b62-cloudflare-worker-deploy.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("needs.preflight.outputs.worker_state == 'absent'", workflow)
        # B14 health must not have been promoted into a deploy gate.
        self.assertNotIn("needs.preflight.outputs.b14_health ==", workflow)

    def test_emit_b14_prints_the_explicit_state_and_reason(self) -> None:
        import contextlib
        import io

        buffer = io.StringIO()
        state = preflight.b14_state(
            http="503",
            health=preflight.B14_HEALTH_UNAVAILABLE_EXPECTED,
            reason=preflight.B14_REASON_HTTP_STATUS,
        )
        with contextlib.redirect_stdout(buffer):
            preflight.emit_b14(state)
        printed = buffer.getvalue()
        self.assertIn("B14_HEALTH_STATE=unavailable_expected", printed)
        self.assertIn("B14_HEALTH_REASON=http_status", printed)
        self.assertIn("REAL_PROVIDER_CALLS=0", printed)

    def test_no_real_provider_call_surface_was_added(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        for forbidden in ("openai", "anthropic", "requests.post", "genai"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source.lower())


class B14NoSilentDefaultMutationTests(unittest.TestCase):
    """Mutation proof: restoring the silent default must fail the suite."""

    def test_restoring_a_silent_default_breaks_the_contract(self) -> None:
        # This asserts the *shape* of the guarantee rather than re-running the
        # module: every reachable state must carry an explicit health+reason
        # pair drawn from the closed sets, so there is no default that can be
        # returned without classification.
        _patch_get_json(self, status=0, raises=RuntimeError("network down"))
        broken = preflight.read_b14_health()
        self.assertEqual(broken["b14_health"], preflight.B14_HEALTH_CHECK_ERROR)
        self.assertNotEqual(broken["b14_reason"], "unknown")
        self.assertNotIn("b14_health", ("", "unknown"))
        # A silent-default implementation would emit no b14_health key at all.
        self.assertIn("b14_health", broken)
        self.assertIn("b14_reason", broken)

    def test_historical_default_projection_is_no_longer_producible(self) -> None:
        # The old default was b14_status="unavailable" with every other field
        # "unknown" and no classification. It must not be reachable.
        _patch_get_json(self, status=0, raises=RuntimeError("network down"))
        state = preflight.read_b14_health()
        self.assertNotEqual(
            state["b14_status"], "unavailable", "historical silent default is back"
        )
        self.assertEqual(state["b14_health"], preflight.B14_HEALTH_CHECK_ERROR)

    def test_each_outcome_is_reachable_and_distinct(self) -> None:
        seen = set()
        cases = (
            (200, _healthy_payload(), None),
            (200, _healthy_payload(status="not_configured"), None),
            (503, {}, None),
            (0, None, URLError("dns")),
            (0, None, TimeoutError()),
            (200, [], None),
            (0, None, ValueError("boom")),
        )
        for status, payload, raises in cases:
            with self.subTest(status=status, raises=raises):
                _patch_get_json(self, status=status, payload=payload, raises=raises)
                state = preflight.read_b14_health()
                self.assertIn(state["b14_health"], preflight.B14_HEALTH_STATES)
                self.assertIn(state["b14_reason"], preflight.B14_REASON_CODES)
                seen.add((state["b14_health"], state["b14_reason"]))
        self.assertEqual(len(seen), 7, f"outcomes collapsed: {seen}")


if __name__ == "__main__":
    unittest.main()
