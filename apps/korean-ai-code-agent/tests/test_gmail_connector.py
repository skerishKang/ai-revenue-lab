from __future__ import annotations

import base64
import json
import unittest

from kagent.connector_platform import ConnectorConnection, ConnectorEffect
from kagent.gmail_connector import (
    GMAIL_ENTRY,
    GMAIL_TOOLS,
    MESSAGE_BODY_CONTEXT_CHARS,
    SEARCH_RESULT_LIMIT,
    GmailReadTransport,
)
from kagent.gmail_contracts import GMAIL_READONLY_SCOPE


def encoded(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def message(
    number: int = 1,
    *,
    thread_id: str = "thread_1",
    body: str = "hello",
    payload_parts: list[dict] | None = None,
) -> dict:
    payload: dict = {
        "mimeType": "text/plain" if payload_parts is None else "multipart/mixed",
        "filename": "",
        "headers": [
            {"name": "From", "value": "Sender <sender@example.com>"},
            {"name": "To", "value": "Recipient <recipient@example.com>"},
            {"name": "Subject", "value": f"Subject {number}"},
            {"name": "Date", "value": "Fri, 4 Sep 2026 08:00:00 +0000"},
        ],
        "body": {"data": encoded(body), "size": len(body.encode("utf-8"))},
    }
    if payload_parts is not None:
        payload["body"] = {"size": 0}
        payload["parts"] = payload_parts
    return {
        "id": f"msg_{number}",
        "threadId": thread_id,
        "labelIds": ["INBOX"],
        "historyId": str(100 + number),
        "internalDate": str(1788508800000 + number),
        "payload": payload,
    }


class FakeAuthorizedGmailHttp:
    def __init__(self) -> None:
        self.responses: list[dict] = []
        self.calls: list[dict] = []

    def get_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class GmailConnectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.http = FakeAuthorizedGmailHttp()
        self.transport = GmailReadTransport(self.http)
        self.connection = ConnectorConnection(
            binding_ref="binding_gmail_1",
            actor_ref="actor_1",
            connector_id="gmail",
        )

    def result_json(self, result):
        return json.loads(result.text)

    def test_catalogue_and_tool_surface_are_readonly_and_fail_closed(self):
        self.assertEqual(
            tuple(tool.name for tool in GMAIL_TOOLS),
            ("search_messages", "get_message", "get_thread"),
        )
        self.assertEqual(GMAIL_ENTRY.classify("search_messages"), ConnectorEffect.READ)
        self.assertEqual(GMAIL_ENTRY.classify("get_message"), ConnectorEffect.READ)
        self.assertEqual(GMAIL_ENTRY.classify("get_thread"), ConnectorEffect.READ)
        self.assertEqual(GMAIL_ENTRY.classify("future_tool"), ConnectorEffect.WRITE)
        self.assertIn("send_existing_approved_draft", GMAIL_ENTRY.write_tools)
        self.assertFalse(self.transport.list_needs_credential)

    def test_search_is_bounded_readonly_and_never_follows_provider_page(self):
        self.http.responses.append(
            {
                "messages": [
                    {"id": f"msg_{index}", "threadId": f"thread_{index}"}
                    for index in range(SEARCH_RESULT_LIMIT)
                ],
                "nextPageToken": "opaque_next_page",
            }
        )
        result = self.transport.call_tool(
            self.connection,
            "search_messages",
            {"query": "newer_than:1d from:supplier@example.com"},
        )
        rendered = self.result_json(result)
        self.assertEqual(rendered["result_status"], "REVIEW_REQUIRED")
        self.assertEqual(rendered["result_count"], SEARCH_RESULT_LIMIT)
        self.assertTrue(rendered["more_results_available"])
        self.assertFalse(rendered["page_followed"])
        self.assertFalse(rendered["mail_content_trusted"])
        self.assertFalse(rendered["raw_credentials_present"])
        call = self.http.calls[0]
        self.assertEqual(call["base_url"], "https://gmail.googleapis.com/gmail/v1")
        self.assertEqual(call["path"], "/users/me/messages")
        self.assertEqual(call["query"]["maxResults"], str(SEARCH_RESULT_LIMIT))
        self.assertEqual(call["required_scopes"], (GMAIL_READONLY_SCOPE,))
        self.assertNotIn("token", call)
        self.assertNotIn("authorization", call)

    def test_empty_search_is_explicit_unknown(self):
        self.http.responses.append({})
        result = self.transport.call_tool(self.connection, "search_messages", {"query": "missing"})
        rendered = self.result_json(result)
        self.assertEqual(rendered["result_status"], "UNKNOWN")
        self.assertEqual(rendered["messages"], [])

    def test_selected_message_projects_headers_body_and_provenance(self):
        self.http.responses.append(message())
        result = self.transport.call_tool(
            self.connection,
            "get_message",
            {"messageId": "msg_1"},
        )
        rendered = self.result_json(result)
        projection = rendered["projection"]
        self.assertEqual(rendered["result_status"], "OK")
        self.assertEqual(rendered["operation"], "messages.get")
        self.assertEqual(rendered["binding_ref"], "binding_gmail_1")
        self.assertEqual(projection["message_id"], "msg_1")
        self.assertEqual(projection["thread_id"], "thread_1")
        self.assertEqual(projection["from_address"], "sender@example.com")
        self.assertEqual(projection["to_addresses"], ["recipient@example.com"])
        self.assertEqual(projection["body_segments"][0]["text"], "hello")
        self.assertFalse(projection["mail_content_trusted"])
        self.assertFalse(rendered["raw_attachment_bytes_present"])
        call = self.http.calls[0]
        self.assertEqual(call["query"], {"format": "full"})
        self.assertTrue(call["path"].endswith("/messages/msg_1"))

    def test_multipart_alternative_prefers_plain_text_instead_of_duplication(self):
        parts = [
            {
                "mimeType": "text/plain",
                "filename": "",
                "body": {"data": encoded("plain version"), "size": 13},
            },
            {
                "mimeType": "text/html",
                "filename": "",
                "body": {"data": encoded("<p>html version</p>"), "size": 19},
            },
        ]
        provider = message(payload_parts=[])
        provider["payload"]["mimeType"] = "multipart/alternative"
        provider["payload"]["parts"] = parts
        self.http.responses.append(provider)
        rendered = self.result_json(
            self.transport.call_tool(self.connection, "get_message", {"messageId": "msg_1"})
        )
        segments = rendered["projection"]["body_segments"]
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["text"], "plain version")

    def test_attachment_is_manifest_only_and_never_downloaded(self):
        parts = [
            {
                "mimeType": "text/plain",
                "filename": "",
                "body": {"data": encoded("invoice attached"), "size": 16},
            },
            {
                "mimeType": "application/pdf",
                "filename": "invoice.pdf",
                "body": {"attachmentId": "att_1", "size": 1024},
            },
        ]
        self.http.responses.append(message(payload_parts=parts))
        rendered = self.result_json(
            self.transport.call_tool(self.connection, "get_message", {"messageId": "msg_1"})
        )
        attachment = rendered["projection"]["attachments"][0]
        self.assertEqual(attachment["attachment_ref"], "att_1")
        self.assertEqual(attachment["quarantine_state"], "pending")
        self.assertFalse(attachment["raw_bytes_present"])
        self.assertFalse(attachment["model_usable"])
        self.assertEqual(len(self.http.calls), 1)

    def test_inline_attachment_without_provider_ref_is_not_treated_as_message_text(self):
        parts = [
            {
                "mimeType": "text/plain",
                "filename": "secret.txt",
                "body": {"data": encoded("attachment bytes"), "size": 16},
            }
        ]
        self.http.responses.append(message(payload_parts=parts))
        rendered = self.result_json(
            self.transport.call_tool(self.connection, "get_message", {"messageId": "msg_1"})
        )
        self.assertEqual(rendered["result_status"], "REVIEW_REQUIRED")
        self.assertTrue(rendered["attachment_manifest_truncated"])
        self.assertEqual(rendered["projection"]["body_segments"], [])

    def test_oversized_message_body_is_visibly_review_required(self):
        self.http.responses.append(message(body="x" * (MESSAGE_BODY_CONTEXT_CHARS + 500)))
        rendered = self.result_json(
            self.transport.call_tool(self.connection, "get_message", {"messageId": "msg_1"})
        )
        self.assertEqual(rendered["result_status"], "REVIEW_REQUIRED")
        self.assertTrue(rendered["body_truncated"])
        self.assertLessEqual(
            len(rendered["projection"]["body_segments"][0]["text"]),
            MESSAGE_BODY_CONTEXT_CHARS,
        )

    def test_thread_uses_latest_bounded_messages_and_marks_omissions(self):
        provider_messages = [message(index, thread_id="thread_1") for index in range(1, 11)]
        self.http.responses.append({"id": "thread_1", "messages": provider_messages})
        rendered = self.result_json(
            self.transport.call_tool(self.connection, "get_thread", {"threadId": "thread_1"})
        )
        self.assertEqual(rendered["result_status"], "REVIEW_REQUIRED")
        self.assertEqual(rendered["provider_message_count"], 10)
        self.assertEqual(rendered["projected_message_count"], 8)
        self.assertEqual(rendered["omitted_message_count"], 2)
        projected_ids = [item["message_id"] for item in rendered["projection"]["messages"]]
        self.assertEqual(projected_ids[0], "msg_3")
        self.assertEqual(projected_ids[-1], "msg_10")
        self.assertFalse(rendered["projection"]["bulk_mailbox_dump"])

    def test_malformed_provider_message_fails_closed_as_review_required(self):
        broken = message()
        broken["payload"]["headers"] = []
        self.http.responses.append(broken)
        result = self.transport.call_tool(
            self.connection,
            "get_message",
            {"messageId": "msg_1"},
        )
        rendered = self.result_json(result)
        self.assertTrue(result.is_error)
        self.assertEqual(rendered["result_status"], "REVIEW_REQUIRED")
        self.assertFalse(rendered["mail_content_trusted"])

    def test_unknown_tool_is_explicit_error(self):
        result = self.transport.call_tool(self.connection, "future_tool", {})
        self.assertTrue(result.is_error)
        self.assertIn("not a tool this connector implements", result.text)


if __name__ == "__main__":
    unittest.main()
