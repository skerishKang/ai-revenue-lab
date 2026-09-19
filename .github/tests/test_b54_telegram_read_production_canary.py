from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "apps" / "padiem-ai-engine" / "scripts" / "a15_telegram_read_production_canary.py"

spec = importlib.util.spec_from_file_location("a15_telegram_read_production_canary", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
canary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(canary)


class TelegramReadProductionCanaryTests(unittest.TestCase):
    def _success_body(self) -> bytes:
        return json.dumps(
            {
                "ok": True,
                "tool": {
                    "canonical_tool_id": canary.TOOL_ID,
                    "status": "completed",
                    "output_truncated": False,
                    "output": {
                        "provider": "telegram",
                        "operation": "telegram.get_bot_info",
                        "result_status": "OK",
                        "bot": {
                            "bot_id": "8657553095",
                            "username": "padiem_clawbot",
                            "first_name": "Padiem Claw",
                            "is_bot": True,
                            "personal_account": False,
                            "bot_token_present": False,
                        },
                        "telegram_content_trusted": False,
                        "bot_token_present": False,
                        "mints_approval_authority": False,
                        "write_capability_granted": False,
                        # Engine's generic redactor treats credential-shaped
                        # keys as secret-shaped even when their Core value is False.
                        "raw_credentials_present": "[redacted]",
                    },
                },
            },
            separators=(",", ":"),
        ).encode("utf-8")

    def test_fixed_canonical_request_contract(self) -> None:
        self.assertEqual(canary.ENGINE_BASE_URL, "https://engine.padiem.net")
        self.assertEqual(canary.TOOL_EXECUTE_PATH, "/internal/v1/tools/execute")
        self.assertEqual(canary.CALLER_ID, "b54-p01-overlay-20260914-a1")
        self.assertEqual(
            canary.canonical_request_body(),
            {
                "app_id": "b54-padiem-claw-telegram",
                "agent_id": "agent:padiem:claw_telegram_reader@1",
                "tool_id": "tool:telegram:bot.get_bot_info@1",
                "arguments": {},
            },
        )
        self.assertEqual(canary.PROVIDER_READ_BUDGET_MAX, 1)

    def test_success_uses_exactly_one_transport_call_and_emits_only_aggregate_evidence(self) -> None:
        calls: list[tuple[dict[str, object], str]] = []
        credential = "super-secret-caller-credential"

        def transport(body: dict[str, object], supplied_credential: str) -> tuple[int, bytes]:
            calls.append((body, supplied_credential))
            return 200, self._success_body()

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = canary.run(credential, transport=transport)

        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], canary.canonical_request_body())
        self.assertEqual(calls[0][1], credential)
        output = stdout.getvalue()
        self.assertIn("TELEGRAM_READ_CANARY=PASS", output)
        self.assertIn("TELEGRAM_BOT_IDENTITY_PRESENT=YES", output)
        self.assertIn("TELEGRAM_GETME_BOUNDED=YES", output)
        self.assertIn("ENGINE_TOOL_EXECUTE_POST_COUNT=1", output)
        self.assertIn("NETWORK_RETRY_COUNT=0", output)
        self.assertIn("RAW_BOT_ID_OUTPUT=0", output)
        self.assertIn("RAW_BOT_USERNAME_OUTPUT=0", output)
        self.assertIn("RAW_BOT_NAME_OUTPUT=0", output)
        self.assertIn("RAW_CHAT_ID_OUTPUT=0", output)
        self.assertIn("RAW_BINDING_REF_OUTPUT=0", output)
        self.assertIn("RAW_ACTOR_REF_OUTPUT=0", output)
        self.assertIn("TELEGRAM_SEND=0", output)
        self.assertIn("D1_MUTATION=0", output)
        self.assertIn("SECRET_MUTATION=0", output)
        self.assertNotIn("8657553095", output)
        self.assertNotIn("padiem_clawbot", output)
        self.assertNotIn("Padiem Claw", output)
        self.assertNotIn(credential, output)

    def test_success_marks_truncated_output(self) -> None:
        payload = json.loads(self._success_body().decode("utf-8"))
        payload["tool"]["output_truncated"] = True
        payload["tool"]["output"]["raw_credentials_present"] = None

        present, truncated = canary.classify_success(payload)
        self.assertTrue(present)
        self.assertTrue(truncated)

    def test_headers_keep_credential_private(self) -> None:
        credential = "private-value"
        headers = canary._headers(credential)
        self.assertEqual(headers["x-padiem-engine-caller"], canary.CALLER_ID)
        self.assertEqual(headers["x-padiem-engine-credential"], credential)
        self.assertNotIn(credential, repr(canary.canonical_request_body()))

    def test_non_200_emits_only_bounded_error_code(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = canary.run(
                "credential",
                transport=lambda body, credential: (
                    503,
                    b'{"error":{"code":"connector_grants_unavailable","message":"private detail"}}',
                ),
            )
        output = stdout.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn("ENGINE_ERROR_CODE=connector_grants_unavailable", output)
        self.assertNotIn("private detail", output)
        self.assertIn("ENGINE_TOOL_EXECUTE_POST_COUNT=1", output)
        self.assertIn("NETWORK_RETRY_COUNT=0", output)

    def test_malformed_success_fails_closed_without_raw_output(self) -> None:
        raw = b'{"ok":true,"tool":{"status":"completed","output":{"bot":{"first_name":"private-name"}}}}'
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = canary.run("credential", transport=lambda body, credential: (200, raw))
        output = stdout.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn("TELEGRAM_READ_CANARY=FAIL_NONCANONICAL_SUCCESS", output)
        self.assertNotIn("private-name", output)

    def test_bot_identity_shape_mismatch_fails_closed(self) -> None:
        payload = json.loads(self._success_body().decode("utf-8"))
        payload["tool"]["output"]["bot"]["username"] = "private-username"
        with self.assertRaises(ValueError):
            canary.classify_success(payload)

    def test_non_getme_material_fails_closed(self) -> None:
        payload = json.loads(self._success_body().decode("utf-8"))
        payload["tool"]["output"]["chat_id"] = 123
        with self.assertRaises(ValueError):
            canary.classify_success(payload)

    def test_write_capability_projection_fails_closed(self) -> None:
        payload = json.loads(self._success_body().decode("utf-8"))
        payload["tool"]["output"]["write_capability_granted"] = True
        with self.assertRaises(ValueError):
            canary.classify_success(payload)

    def test_transport_exception_is_not_retried(self) -> None:
        calls = 0

        def transport(body: dict[str, object], credential: str) -> tuple[int, bytes]:
            nonlocal calls
            calls += 1
            raise RuntimeError("sensitive transport failure")

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = canary.run("credential", transport=transport)
        self.assertEqual(rc, 1)
        self.assertEqual(calls, 1)
        output = stdout.getvalue()
        self.assertIn("TELEGRAM_READ_CANARY=FAIL_NETWORK", output)
        self.assertNotIn("sensitive transport failure", output)
        self.assertIn("NETWORK_RETRY_COUNT=0", output)


if __name__ == "__main__":
    unittest.main()