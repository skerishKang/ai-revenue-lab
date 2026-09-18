from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "apps" / "padiem-ai-engine" / "scripts" / "a14_gmail_read_production_canary.py"

spec = importlib.util.spec_from_file_location("a14_gmail_read_production_canary", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
canary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(canary)


class GmailReadProductionCanaryTests(unittest.TestCase):
    def _success_body(self) -> bytes:
        return json.dumps(
            {
                "ok": True,
                "tool": {
                    "canonical_tool_id": canary.TOOL_ID,
                    "status": "completed",
                    "output_truncated": False,
                    "output": {
                        "provider": "gmail",
                        "operation": "messages.list",
                        "query": canary.CANARY_QUERY,
                        "result_status": "OK",
                        "messages": [
                            {
                                "message_id": "sensitive-message-id",
                                "thread_id": "sensitive-thread-id",
                            }
                        ],
                        "result_count": 1,
                        "more_results_available": False,
                        "page_followed": False,
                        "mail_content_trusted": False,
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
                "app_id": "b54-padiem-claw",
                "agent_id": "agent:padiem:claw_mail_reader@1",
                "tool_id": "tool:google:gmail.search_messages@1",
                "arguments": {
                    "query": 'subject:"__PADIEM_GMAIL_READ_CANARY_NONMATCH_20260919__"'
                },
            },
        )
        self.assertEqual(canary.PROVIDER_READ_BUDGET_MAX, 2)

    def test_success_uses_one_engine_post_and_emits_only_aggregate_evidence(self) -> None:
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
        self.assertIn("GMAIL_READ_CANARY=PASS", output)
        self.assertIn("GMAIL_RESULT_ITEM_COUNT=1", output)
        self.assertIn("ENGINE_TOOL_EXECUTE_POST_COUNT=1", output)
        self.assertIn("NETWORK_RETRY_COUNT=0", output)
        self.assertIn("GMAIL_PROVIDER_READ_BUDGET_MAX=2", output)
        self.assertIn("RAW_MESSAGE_ID_OUTPUT=0", output)
        self.assertIn("RAW_THREAD_ID_OUTPUT=0", output)
        for forbidden in (
            credential,
            "sensitive-message-id",
            "sensitive-thread-id",
        ):
            self.assertNotIn(forbidden, output)

    def test_empty_search_is_valid_provider_read(self) -> None:
        payload = json.loads(self._success_body().decode("utf-8"))
        payload["tool"]["output"]["result_status"] = "UNKNOWN"
        payload["tool"]["output"]["messages"] = []
        payload["tool"]["output"]["result_count"] = 0
        count, pagination, truncated = canary.classify_success(payload)
        self.assertEqual(count, 0)
        self.assertEqual(pagination, "NO")
        self.assertFalse(truncated)

    def test_result_list_is_bounded_and_contains_refs_only(self) -> None:
        payload = json.loads(self._success_body().decode("utf-8"))
        payload["tool"]["output"]["messages"] = [
            {"message_id": f"m{i}", "thread_id": f"t{i}"}
            for i in range(canary.MAX_RESULT_ITEMS + 1)
        ]
        payload["tool"]["output"]["result_count"] = len(payload["tool"]["output"]["messages"])
        with self.assertRaises(ValueError):
            canary.classify_success(payload)

        payload = json.loads(self._success_body().decode("utf-8"))
        payload["tool"]["output"]["messages"][0]["subject"] = "private subject"
        with self.assertRaises(ValueError):
            canary.classify_success(payload)

    def test_no_message_content_surface_is_accepted(self) -> None:
        for forbidden_key in (
            "projection",
            "body",
            "body_segments",
            "subject",
            "from_address",
            "to_addresses",
            "attachments",
            "filename",
            "raw_attachment_bytes_present",
        ):
            payload = json.loads(self._success_body().decode("utf-8"))
            payload["tool"]["output"][forbidden_key] = "private"
            with self.assertRaises(ValueError):
                canary.classify_success(payload)

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
                    b'{"error":{"code":"google_oauth_access_lease_unavailable","message":"private detail"}}',
                ),
            )
        output = stdout.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn("GMAIL_READ_CANARY=FAIL_ENGINE_RESPONSE", output)
        self.assertIn("ENGINE_ERROR_CODE=google_oauth_access_lease_unavailable", output)
        self.assertNotIn("private detail", output)
        self.assertIn("ENGINE_TOOL_EXECUTE_POST_COUNT=1", output)
        self.assertIn("NETWORK_RETRY_COUNT=0", output)

    def test_malformed_success_fails_closed_without_raw_output(self) -> None:
        raw = b'{"ok":true,"tool":{"status":"completed","output":{"subject":"private-subject"}}}'
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = canary.run("credential", transport=lambda body, credential: (200, raw))
        output = stdout.getvalue()
        self.assertEqual(rc, 1)
        self.assertIn("GMAIL_READ_CANARY=FAIL_NONCANONICAL_SUCCESS", output)
        self.assertNotIn("private-subject", output)

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
        self.assertIn("GMAIL_READ_CANARY=FAIL_NETWORK", output)
        self.assertNotIn("sensitive transport failure", output)
        self.assertIn("NETWORK_RETRY_COUNT=0", output)


if __name__ == "__main__":
    unittest.main()
