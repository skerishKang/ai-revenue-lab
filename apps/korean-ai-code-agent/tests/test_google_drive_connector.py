from __future__ import annotations

import unittest

from kagent.connector_platform import ConnectorConnection
from kagent.google_drive_connector import (
    DRIVE_TOOLS,
    EXPORTABLE_MIME,
    GoogleDriveReadTransport,
    drive_query,
    is_textual_mime,
)


class FakeAuthorizedHttp:
    def __init__(self):
        self.json_responses = []
        self.text_responses = []
        self.calls = []

    def get_json(self, **kwargs):
        self.calls.append(("json", kwargs))
        return self.json_responses.pop(0)

    def get_text(self, **kwargs):
        self.calls.append(("text", kwargs))
        return self.text_responses.pop(0)


class GoogleDriveConnectorTests(unittest.TestCase):
    def setUp(self):
        self.http = FakeAuthorizedHttp()
        self.transport = GoogleDriveReadTransport(self.http)
        self.connection = ConnectorConnection(
            binding_ref="binding_drive_1",
            actor_ref="actor_1",
            connector_id="google-drive",
        )

    def test_tool_names_match_openbot_drive_transport(self):
        self.assertEqual(
            tuple(tool.name for tool in DRIVE_TOOLS),
            ("search_files", "list_recent_files", "get_file_metadata", "read_file_content"),
        )
        self.assertFalse(self.transport.list_needs_credential)

    def test_drive_query_escapes_apostrophe_and_backslash(self):
        query = drive_query(r"don't\stop")
        self.assertIn(r"don\'t\\stop", query)

    def test_search_uses_pinned_base_and_bounded_page_size_without_credentials(self):
        self.http.json_responses.append(
            {
                "files": [
                    {
                        "id": "file_1",
                        "name": "Report",
                        "mimeType": "text/plain",
                        "modifiedTime": "2026-09-03T00:00:00Z",
                        "webViewLink": "https://drive.google.com/file/d/file_1/view",
                    }
                ]
            }
        )
        result = self.transport.call_tool(self.connection, "search_files", {"query": "Report"})
        self.assertIn("Report", result.text)
        kind, call = self.http.calls[0]
        self.assertEqual(kind, "json")
        self.assertEqual(call["base_url"], "https://www.googleapis.com/drive/v3")
        self.assertEqual(call["query"]["pageSize"], "25")
        self.assertNotIn("token", call)
        self.assertNotIn("authorization", call)

    def test_empty_search_result_is_explicit(self):
        self.http.json_responses.append({"files": []})
        result = self.transport.call_tool(self.connection, "search_files", {"query": "missing"})
        self.assertIn("Nothing was found", result.text)

    def test_metadata_keeps_link_owner_and_id(self):
        self.http.json_responses.append(
            {
                "id": "file_1",
                "name": "Report",
                "mimeType": "text/plain",
                "size": "42",
                "owners": [{"emailAddress": "owner@example.com"}],
                "webViewLink": "https://drive.google.com/file/d/file_1/view",
            }
        )
        result = self.transport.call_tool(
            self.connection, "get_file_metadata", {"fileId": "file_1"}
        )
        self.assertIn("id: file_1", result.text)
        self.assertIn("size: 42 bytes", result.text)
        self.assertIn("owner: owner@example.com", result.text)

    def test_google_doc_is_exported_as_plain_text(self):
        self.http.json_responses.append(
            {
                "id": "doc_1",
                "name": "Doc",
                "mimeType": "application/vnd.google-apps.document",
            }
        )
        self.http.text_responses.append("hello")
        result = self.transport.call_tool(
            self.connection, "read_file_content", {"fileId": "doc_1"}
        )
        self.assertEqual(result.text, "Doc\n\nhello")
        _, call = self.http.calls[1]
        self.assertTrue(call["path"].endswith("/export"))
        self.assertEqual(
            call["query"]["mimeType"],
            EXPORTABLE_MIME["application/vnd.google-apps.document"],
        )

    def test_binary_file_is_refused_instead_of_decoded(self):
        self.http.json_responses.append(
            {"id": "pdf_1", "name": "paper.pdf", "mimeType": "application/pdf"}
        )
        result = self.transport.call_tool(
            self.connection, "read_file_content", {"fileId": "pdf_1"}
        )
        self.assertTrue(result.is_error)
        self.assertIn("cannot read as text", result.text)
        self.assertEqual(len(self.http.calls), 1)

    def test_textual_allowlist_is_positive_not_application_wildcard(self):
        self.assertTrue(is_textual_mime("text/markdown"))
        self.assertTrue(is_textual_mime("application/json"))
        self.assertFalse(is_textual_mime("application/pdf"))
        self.assertFalse(is_textual_mime("application/zip"))

    def test_unknown_tool_is_explicit_error(self):
        result = self.transport.call_tool(self.connection, "new_unknown_tool", {})
        self.assertTrue(result.is_error)
        self.assertIn("not a tool this connector implements", result.text)


if __name__ == "__main__":
    unittest.main()
