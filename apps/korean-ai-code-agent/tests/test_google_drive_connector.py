from __future__ import annotations

import unittest

from kagent.connector_platform import ConnectorConnection
from kagent.google_drive_connector import (
    DRIVE_TOOLS,
    EXPORTABLE_MIME,
    FILE_FIELDS,
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

    def test_metadata_fields_include_drive_version_and_shortcut_proof_fields(self):
        for expected in (
            "driveId",
            "parents",
            "trashed",
            "version",
            "md5Checksum",
            "sha256Checksum",
            "headRevisionId",
            "resourceKey",
            "shortcutDetails(targetId,targetMimeType,targetResourceKey)",
        ):
            self.assertIn(expected, FILE_FIELDS)

    def test_search_uses_pinned_base_shared_drive_awareness_and_no_credentials(self):
        self.http.json_responses.append(
            {
                "files": [
                    {
                        "id": "file_1",
                        "name": "Report",
                        "mimeType": "text/plain",
                        "modifiedTime": "2026-09-03T00:00:00Z",
                        "version": "9",
                        "driveId": "drive_1",
                        "webViewLink": "https://drive.google.com/file/d/file_1/view",
                    }
                ]
            }
        )
        result = self.transport.call_tool(self.connection, "search_files", {"query": "Report"})
        self.assertIn("Report", result.text)
        self.assertIn("version 9", result.text)
        self.assertIn("shared-drive: drive_1", result.text)
        kind, call = self.http.calls[0]
        self.assertEqual(kind, "json")
        self.assertEqual(call["base_url"], "https://www.googleapis.com/drive/v3")
        self.assertEqual(call["query"]["pageSize"], "25")
        self.assertEqual(call["query"]["supportsAllDrives"], "true")
        self.assertEqual(call["query"]["includeItemsFromAllDrives"], "true")
        self.assertIn("trashed = false", call["query"]["q"])
        self.assertNotIn("token", call)
        self.assertNotIn("authorization", call)

    def test_recent_files_excludes_trashed(self):
        self.http.json_responses.append({"files": []})
        self.transport.call_tool(self.connection, "list_recent_files", {})
        _, call = self.http.calls[0]
        self.assertEqual(call["query"]["q"], "trashed = false")
        self.assertEqual(call["query"]["orderBy"], "modifiedTime desc")

    def test_empty_search_result_is_explicit(self):
        self.http.json_responses.append({"files": []})
        result = self.transport.call_tool(self.connection, "search_files", {"query": "missing"})
        self.assertIn("Nothing was found", result.text)

    def test_metadata_keeps_link_owner_id_version_and_shortcut_target(self):
        self.http.json_responses.append(
            {
                "id": "file_1",
                "name": "Report",
                "mimeType": "text/plain",
                "size": "42",
                "version": "12",
                "driveId": "drive_1",
                "owners": [{"emailAddress": "owner@example.com"}],
                "shortcutDetails": {"targetId": "target_1"},
                "webViewLink": "https://drive.google.com/file/d/file_1/view",
            }
        )
        result = self.transport.call_tool(
            self.connection, "get_file_metadata", {"fileId": "file_1"}
        )
        self.assertIn("id: file_1", result.text)
        self.assertIn("version 12", result.text)
        self.assertIn("shared-drive: drive_1", result.text)
        self.assertIn("size: 42 bytes", result.text)
        self.assertIn("owner: owner@example.com", result.text)
        self.assertIn("shortcut-target-id: target_1", result.text)
        _, call = self.http.calls[0]
        self.assertEqual(call["query"]["supportsAllDrives"], "true")

    def test_google_doc_is_exported_as_plain_text(self):
        self.http.json_responses.append(
            {
                "id": "doc_1",
                "name": "Doc",
                "mimeType": "application/vnd.google-apps.document",
                "version": "1",
            }
        )
        self.http.text_responses.append("hello")
        result = self.transport.call_tool(
            self.connection, "read_file_content", {"fileId": "doc_1"}
        )
        self.assertEqual(result.text, "Doc\n\nhello")
        _, metadata_call = self.http.calls[0]
        self.assertEqual(metadata_call["query"]["supportsAllDrives"], "true")
        _, call = self.http.calls[1]
        self.assertTrue(call["path"].endswith("/export"))
        self.assertEqual(
            call["query"]["mimeType"],
            EXPORTABLE_MIME["application/vnd.google-apps.document"],
        )

    def test_trashed_file_is_refused_before_content_call(self):
        self.http.json_responses.append(
            {"id": "doc_1", "name": "Doc", "mimeType": "text/plain", "trashed": True}
        )
        result = self.transport.call_tool(
            self.connection, "read_file_content", {"fileId": "doc_1"}
        )
        self.assertTrue(result.is_error)
        self.assertIn("trashed", result.text)
        self.assertEqual(len(self.http.calls), 1)

    def test_shortcut_is_refused_until_target_is_independently_authorized(self):
        self.http.json_responses.append(
            {
                "id": "shortcut_1",
                "name": "Shortcut",
                "mimeType": "application/vnd.google-apps.shortcut",
                "shortcutDetails": {"targetId": "target_1", "targetMimeType": "text/plain"},
            }
        )
        result = self.transport.call_tool(
            self.connection, "read_file_content", {"fileId": "shortcut_1"}
        )
        self.assertTrue(result.is_error)
        self.assertIn("independently authorized", result.text)
        self.assertEqual(len(self.http.calls), 1)

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
