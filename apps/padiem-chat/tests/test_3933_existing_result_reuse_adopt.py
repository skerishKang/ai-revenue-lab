"""#3933 existing-result reuse: a completed XLSX becomes a NEW web source.

The adopt POST is the ONLY connection between an already-completed owner
artifact and a new web Excel input. It must re-read the exact recorded bytes,
mint a NEW unauthorized document identity and never reuse the previous P01
READ decision, workcopy or WRITE receipt.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_3929_claw_conversation_artifact_d1 import (  # noqa: E402
    CHAT, FOREIGN_CHAT, OTHER_WORKSPACE, OWNER, RUN, WORKSPACE,
    D1HistoryStore, D1Sqlite, setup_database,
)

from app.claw_conversation_artifact_adopt_routes import (  # noqa: E402
    CONTRACT, claw_conversation_artifact_adopt,
)
from app.claw_web_xlsx_source_routes import _error  # noqa: E402
from kagent.artifact_registration import (  # noqa: E402
    ArtifactLifecycle, ArtifactLocation, register_canonical_artifact,
)

ROOT = Path(__file__).resolve().parents[1]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ARTIFACT_ID = "doc_" + "1" * 32
NEW_DOCUMENT_ID = "doc_" + "2" * 32
PAYLOAD = b"PK\x03\x04" + b"hark-revised-quote".ljust(400, b"\x00")
SHA = hashlib.sha256(PAYLOAD).hexdigest()
FILENAME = "hark-revised-quote.xlsx"
ADOPT_PATH = "/api/claw/conversations/{conversation_id}/artifact-followup/adopt"


def revision_record(*, artifact_id=ARTIFACT_ID, integrity_ref=SHA,
                    size_bytes=len(PAYLOAD), filename=FILENAME,
                    location_kind="r2_bucket", workspace=WORKSPACE,
                    source_run=RUN, media_type=XLSX):
    return register_canonical_artifact(
        artifact_id=artifact_id,
        artifact_kind="output.xlsx",
        filename=filename,
        media_type=media_type,
        size_bytes=size_bytes,
        integrity_ref=integrity_ref,
        lifecycle=ArtifactLifecycle.DURABLE,
        workspace_ref=workspace,
        run_ref=source_run,
        durable_location=ArtifactLocation(
            location_kind, f"workspaces/{workspace}/claw/web-office-revisions/x"),
    )


class FakeHeaders(dict):
    def get(self, key, default=None):  # noqa: D102
        return dict.get(self, str(key).lower(), default)


class FakeDocuments:
    """Only the two trusted workspace-storage calls the route may use."""

    def __init__(self, *, payload=PAYLOAD, metadata_id=ARTIFACT_ID,
                 tenant=WORKSPACE, missing=False):
        self.payload, self.metadata_id = payload, metadata_id
        self.tenant, self.missing = tenant, missing
        self.puts: list[dict[str, object]] = []
        self.reads: list[dict[str, object]] = []

    async def get_for_tenant(self, *, tenant_id, document_id, now=None):
        self.reads.append({"tenant_id": tenant_id, "document_id": document_id})
        if self.missing:
            return None
        if tenant_id != self.tenant:
            raise RuntimeError("workspace document access denied")
        if document_id != self.metadata_id:
            return None
        metadata = SimpleNamespace(
            document_id=document_id, tenant_id=tenant_id,
            object_key="workspaces/x", byte_length=len(self.payload),
        )
        return metadata, self.payload

    async def put_web_xlsx(self, *, tenant_id, owner_id, workspace_id,
                           filename, body, now=None):
        self.puts.append({
            "tenant_id": tenant_id, "owner_id": owner_id,
            "workspace_id": workspace_id, "filename": filename,
            "body": body,
        })
        return {
            "document_id": NEW_DOCUMENT_ID, "filename": filename,
            "size_bytes": len(body),
            "source_sha256": hashlib.sha256(body).hexdigest(),
            "expires_at": "2026-10-13T00:00:00+00:00",
            "original_immutable": True, "processing_authorized": False,
        }


def adopt_request(*, body=None, method="POST",
                  content_type="application/json", conversation_id=CHAT,
                  store=None, path_params=True):
    raw = body if isinstance(body, bytes) else json.dumps(
        {} if body is None else body).encode()

    async def read_body():
        return raw

    return SimpleNamespace(
        method=method,
        path=ADOPT_PATH.format(conversation_id=conversation_id),
        path_params=({"conversation_id": conversation_id} if path_params else {}),
        headers=FakeHeaders({
            "content-type": content_type,
            "content-length": str(len(raw)),
        }),
        body=read_body,
        app=SimpleNamespace(state=SimpleNamespace(history_store=store)),
    )


async def call(store, documents, *, owner=OWNER, workspace=WORKSPACE,
               authority=None, artifact_id=ARTIFACT_ID, integrity_ref=SHA,
               **kwargs):
    if "body" not in kwargs:
        kwargs["body"] = {
            "artifact_id": artifact_id, "integrity_ref": integrity_ref,
        }
    request = adopt_request(store=store, **kwargs)

    async def resolved(_request):
        if authority is not None:
            return authority
        return documents, owner, workspace

    with patch(
        "app.claw_conversation_artifact_adopt_routes._authority", resolved,
    ):
        response = await claw_conversation_artifact_adopt(request)
    return response.status_code, json.loads(response.body.decode()), response


class ExistingResultReuseAdoptTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = setup_database()
        self.history = D1HistoryStore(D1Sqlite(self.db))
        self.documents = FakeDocuments()

    def tearDown(self):
        self.db.close()

    async def register(self, record=None, **kwargs):
        record = record or revision_record()
        registered = await self.history.register_owner_conversation_artifact(
            user_id=kwargs.pop("user_id", OWNER),
            conversation_id=kwargs.pop("conversation_id", CHAT),
            workspace_ref=kwargs.pop("workspace_ref", WORKSPACE),
            artifact=record,
        )
        return record, registered

    async def test_completed_revision_becomes_a_new_unapproved_source(self):
        record, registered = await self.register()
        self.assertTrue(registered)
        code, body, response = await call(self.history, self.documents)
        self.assertEqual(code, 201, body)
        self.assertEqual(body["contract_version"], CONTRACT)
        self.assertEqual(body["source"], "previous_completed_result")
        self.assertEqual(body["adopted_from_artifact_id"], record.artifact_id)
        # A genuinely NEW identity: the previous decision cannot be replayed.
        self.assertNotEqual(body["file"]["document_id"], record.artifact_id)
        self.assertEqual(body["file"]["document_id"], NEW_DOCUMENT_ID)
        self.assertEqual(body["file"]["source_sha256"], SHA)
        self.assertEqual(body["file"]["size_bytes"], len(PAYLOAD))
        self.assertEqual(body["file"]["filename"], FILENAME)
        self.assertTrue(body["file"]["original_immutable"])
        self.assertFalse(body["file"]["processing_authorized"])
        for flag in (
            "p01_approval_started", "processing_started", "p01_approved",
            "drive_uploaded", "workcopy_created", "previous_approval_reused",
            "read_grant_issued", "source_material_loaded",
            "provider_write_authorized", "memory_restored",
        ):
            self.assertIs(body[flag], False, flag)
        # Exactly the recorded bytes were re-read and re-stored, unmodified.
        self.assertEqual(self.documents.reads, [{
            "tenant_id": WORKSPACE, "document_id": record.artifact_id,
        }])
        self.assertEqual(len(self.documents.puts), 1)
        self.assertEqual(self.documents.puts[0]["body"], PAYLOAD)
        self.assertEqual(self.documents.puts[0]["filename"], FILENAME)
        self.assertEqual(self.documents.puts[0]["owner_id"], OWNER)
        self.assertEqual(
            response.headers["cache-control"], "private, no-store, max-age=0")
        # No private object key, provider reference or path ever leaves here.
        serialized = json.dumps(body)
        self.assertNotIn("workspaces/", serialized)
        self.assertNotIn("r2_bucket", serialized)
        self.assertNotIn("location_ref", serialized)

    async def test_the_artifact_index_row_is_never_mutated_or_extended(self):
        await self.register()
        before = self.db.execute(
            "SELECT artifact_id, integrity_ref, location_ref "
            "FROM claw_conversation_artifact_index").fetchall()
        code, body, _ = await call(self.history, self.documents)
        self.assertEqual(code, 201, body)
        after = self.db.execute(
            "SELECT artifact_id, integrity_ref, location_ref "
            "FROM claw_conversation_artifact_index").fetchall()
        self.assertEqual([tuple(row) for row in before],
                         [tuple(row) for row in after])
        # The adopted document is a web source, never a second index entry.
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM claw_conversation_artifact_index"
        ).fetchone()[0], 1)

    async def test_unregistered_foreign_or_wrong_reference_is_refused(self):
        record, _ = await self.register()
        cases = [
            ("no durable row at all", dict(
                artifact_id="doc_" + "3" * 32, integrity_ref=SHA)),
            ("wrong integrity hash", dict(
                artifact_id=record.artifact_id, integrity_ref="f" * 64)),
            ("a foreign conversation", dict(
                artifact_id=record.artifact_id, integrity_ref=SHA,
                conversation_id=FOREIGN_CHAT)),
        ]
        for label, kwargs in cases:
            with self.subTest(label):
                code, body, _ = await call(self.history, self.documents, **kwargs)
                self.assertEqual(code, 404, body)
                self.assertEqual(body["error"]["code"], "artifact_not_available")
        # A malformed identity never even reaches the index lookup.
        for label, kwargs in [
            ("malformed artifact identity", dict(
                artifact_id="artifact_1", integrity_ref=SHA)),
            ("malformed integrity hash", dict(
                artifact_id=record.artifact_id, integrity_ref="not-a-hash")),
        ]:
            with self.subTest(label):
                code, body, _ = await call(self.history, self.documents, **kwargs)
                self.assertEqual(code, 400, body)
                self.assertEqual(body["error"]["code"],
                                 "invalid_artifact_reference")
        self.assertEqual(self.documents.puts, [])
        self.assertEqual(self.documents.reads, [])

    async def test_a_google_drive_only_row_is_not_a_readable_source(self):
        await self.register(revision_record(location_kind="google_drive"))
        code, body, _ = await call(self.history, self.documents)
        # The durable Drive reader is deliberately not composed; the adopt
        # boundary must not pretend the bytes are reachable.
        self.assertEqual(code, 404, body)
        self.assertEqual(body["error"]["code"], "artifact_not_available")
        self.assertEqual(self.documents.puts, [])

    async def test_a_workspace_mismatch_fails_closed(self):
        await self.register()
        code, body, _ = await call(
            self.history, self.documents, workspace=OTHER_WORKSPACE)
        self.assertEqual(code, 404, body)
        self.assertEqual(self.documents.puts, [])

    async def test_substituted_truncated_or_non_xlsx_bytes_are_refused(self):
        await self.register()
        cases = [
            ("sha256 mismatch", FakeDocuments(payload=b"PK\x03\x04" + b"x" * 400)),
            ("truncated object", FakeDocuments(payload=PAYLOAD[:10])),
            ("not an XLSX archive", FakeDocuments(
                payload=b"%PDF-1.7".ljust(len(PAYLOAD), b"\x00"))),
            ("expired or absent object", FakeDocuments(missing=True)),
        ]
        for label, documents in cases:
            with self.subTest(label):
                code, body, _ = await call(self.history, documents)
                self.assertIn(code, (404, 409), body)
                self.assertEqual(documents.puts, [])

    async def test_an_unusable_durable_row_never_becomes_a_source(self):
        # The canonical registration already refuses these names, so the
        # tampering is applied to the durable row itself: a corrupted or
        # oversized index row must still never become a web source.
        cases = [
            ("oversized record", "size_bytes", 2_000_000),
            ("path traversal name", "filename", "../../secret.xlsx"),
            ("non xlsx name", "filename", "secret.pdf"),
            ("empty name", "filename", ""),
        ]
        for label, column, value in cases:
            with self.subTest(label):
                record, registered = await self.register()
                self.assertTrue(registered)
                self.db.execute(
                    f"UPDATE claw_conversation_artifact_index SET {column}=? "
                    "WHERE artifact_id=?", (value, record.artifact_id))
                self.db.commit()
                code, body, _ = await call(self.history, self.documents)
                self.assertEqual(code, 409, body)
                self.assertEqual(body["error"]["code"], "artifact_source_unusable")
                self.assertEqual(self.documents.puts, [])
                self.db.execute("DELETE FROM claw_conversation_artifact_index")
                self.db.commit()

    async def test_request_shape_auth_and_method_are_closed(self):
        await self.register()
        cases = [
            ("GET", dict(method="GET"), 405),
            ("missing content type", dict(content_type="text/plain"), 415),
            ("malformed json", dict(body=b"{not json"), 400),
            ("missing integrity ref", dict(body={"artifact_id": ARTIFACT_ID}), 400),
            ("extra authority field", dict(body={
                "artifact_id": ARTIFACT_ID, "integrity_ref": SHA,
                "owner_id": "someone_else"}), 400),
            ("browser supplied grant", dict(body={
                "artifact_id": ARTIFACT_ID, "integrity_ref": SHA,
                "processing_authorized": True}), 400),
            ("wrong conversation path", dict(path_params=False), 400),
        ]
        for label, kwargs, expected in cases:
            with self.subTest(label):
                code, body, _ = await call(self.history, self.documents, **kwargs)
                self.assertEqual(code, expected, body)
        self.assertEqual(self.documents.puts, [])
        # An unauthenticated caller never reaches any storage call.
        code, body, _ = await call(
            self.history, self.documents, authority=_error(401, "unauthorized"))
        self.assertEqual(code, 401)
        self.assertEqual(self.documents.reads, [])
        self.assertEqual(self.documents.puts, [])

    async def test_an_oversized_body_is_rejected_before_any_storage_call(self):
        await self.register()
        code, body, _ = await call(
            self.history, self.documents,
            body=b"{" + b"a" * 4096 + b"}",
        )
        self.assertEqual(code, 413, body)
        self.assertEqual(body["error"]["code"], "artifact_adopt_request_too_large")
        self.assertEqual(self.documents.reads, [])
        self.assertEqual(self.documents.puts, [])

    async def test_a_missing_index_or_store_capability_is_unavailable(self):
        class NoLookup:
            pass

        code, body, _ = await call(NoLookup(), self.documents)
        self.assertEqual(code, 503, body)
        self.assertEqual(body["error"]["code"], "artifact_index_unavailable")

        class Exploding:
            async def get_owner_conversation_artifact(self, **_kwargs):
                raise RuntimeError("D1 unavailable")

        code, body, _ = await call(Exploding(), self.documents)
        self.assertEqual(code, 503, body)
        self.assertEqual(body["error"]["code"], "artifact_index_read_failed")

        await self.register()

        class ExplodingRead(FakeDocuments):
            async def get_for_tenant(self, **_kwargs):
                raise RuntimeError("R2 unavailable")

        documents = ExplodingRead()
        code, body, _ = await call(self.history, documents)
        self.assertEqual(code, 503, body)
        self.assertEqual(body["error"]["code"], "artifact_bytes_unavailable")

        class ExplodingWrite(FakeDocuments):
            async def put_web_xlsx(self, **_kwargs):
                raise RuntimeError("R2 unavailable")

        documents = ExplodingWrite()
        code, body, _ = await call(self.history, documents)
        self.assertEqual(code, 503, body)
        self.assertEqual(body["error"]["code"], "web_xlsx_adopt_write_unavailable")

    async def test_a_projection_without_a_new_identity_is_never_reported(self):
        await self.register()

        class SameIdentity(FakeDocuments):
            async def put_web_xlsx(self, **kwargs):
                projection = await super().put_web_xlsx(**kwargs)
                projection["document_id"] = ARTIFACT_ID
                return projection

        code, body, _ = await call(self.history, SameIdentity())
        self.assertEqual(code, 503, body)
        self.assertEqual(body["error"]["code"],
                         "web_xlsx_adopt_projection_invalid")

        class Authorized(FakeDocuments):
            async def put_web_xlsx(self, **kwargs):
                projection = await super().put_web_xlsx(**kwargs)
                projection["processing_authorized"] = True
                return projection

        code, body, _ = await call(self.history, Authorized())
        self.assertEqual(code, 503, body)
        self.assertEqual(body["error"]["code"],
                         "web_xlsx_adopt_projection_invalid")


class AdoptBoundarySourceTests(unittest.TestCase):
    """The route is a storage-only boundary: no model, provider or Engine."""
    def test_the_two_shipped_modules_are_connected_end_to_end(self):
        """The real connection: context card -> panel -> NEW source -> NEW READ."""
        if shutil.which("node") is None:
            pytest.skip("Node unavailable locally; required B62 Linux CI harness")
        result = subprocess.run(
            ["node", str(Path(__file__).resolve().parent
                        / "existing_result_reuse_node.js")],
            capture_output=True, text=True, timeout=30, check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        for marker in (
            "EXISTING_RESULT_REUSE_CONTEXT_TO_PANEL_CONNECTION=PASS",
            "EXISTING_RESULT_REUSE_ADOPT_MINTS_NEW_IDENTITY=PASS",
            "EXISTING_RESULT_REUSE_NEW_READ_APPROVAL_REQUIRED=PASS",
        ):
            assert marker in result.stdout

    def test_no_provider_engine_or_model_path_is_reachable(self):
        source = (
            ROOT / "app" / "claw_conversation_artifact_adopt_routes.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "engine_client", "WebQuoteWriteEngine", "openai", "anthropic",
            "httpx", "import requests", "create_authorized_web_quote_revision",
            "revise_single_sheet_quote", "b14",
        ):
            self.assertNotIn(forbidden, source)
        # Only the two already-trusted workspace-storage calls are used.
        self.assertIn("get_for_tenant", source)
        self.assertIn("put_web_xlsx", source)
        self.assertIn('row.get("location_kind") != "r2_bucket"', source)
        self.assertIn('"previous_approval_reused": False', source)
        self.assertIn('"p01_approval_started": False', source)

    def test_the_route_is_registered_once_as_post_only(self):
        factory = (ROOT / "app" / "app_factory.py").read_text(encoding="utf-8")
        self.assertEqual(factory.count("artifact-followup/adopt"), 1)
        line = next(
            item for item in factory.splitlines()
            if "artifact-followup/adopt" in item
        )
        self.assertIn('methods=["POST"]', line)
        self.assertIn("claw_conversation_artifact_adopt", line)
        # The read-only followup GET stays exactly as it was.
        followup = next(
            item for item in factory.splitlines()
            if "artifact-followup" in item and "adopt" not in item
        )
        self.assertIn('methods=["GET"]', followup)


if __name__ == "__main__":
    unittest.main()
