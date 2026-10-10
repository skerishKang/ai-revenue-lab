"""#3929: canonical same-thread version reference selection, provider free."""
import unittest
from dataclasses import replace
from hashlib import sha256

from kagent.artifact_lineage import LineageArtifactRef
from kagent.artifact_registration import (
    ArtifactLifecycle, ArtifactLocation, register_canonical_artifact,
)
from kagent.contracts import ContractError
from kagent.conversation_artifact_followup import (
    AuthorizedConversationArtifact, FollowupSelection, FollowupStatus,
    MAX_CANDIDATES, PRODUCTION_CONVERSATION_INDEX_COMPOSED,
    PRODUCTION_DURABLE_FOLLOWUP_ENABLED, resolve_followup_artifact,
)

OWNER = "owner_3929"
THREAD = "chat_" + "a" * 32
WORKSPACE = "workspace_3929"
OTHER = "owner_foreign"
PDF_MIME = "application/pdf"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def row(name="quote.xlsx", *, kind="xlsx", seq=1, owner=OWNER, conversation=THREAD,
        workspace=WORKSPACE, run=None, artifact=None, durable=True):
    run = run or f"run_3929_{seq}"
    artifact = artifact or f"artifact_3929_{seq}"
    media = XLSX_MIME if kind == "xlsx" else PDF_MIME
    contents = (name + artifact).encode("utf-8")
    record = register_canonical_artifact(
        artifact_id=artifact,
        artifact_kind="working.xlsx" if kind == "xlsx" else "output.pdf",
        filename=name,
        media_type=media,
        size_bytes=len(contents), integrity_ref=sha256(contents).hexdigest(),
        workspace_ref=workspace, run_ref=run,
        lifecycle=ArtifactLifecycle.DURABLE if durable else ArtifactLifecycle.GENERATED,
        durable_location=ArtifactLocation("google_drive", "opaque_provider_id")
        if durable else None,
        source_ref="artifact/" + artifact,
    )
    return AuthorizedConversationArtifact(
        owner_id=owner, conversation_id=conversation,
        workspace_ref=workspace, source_run_ref=run,
        ordinal=seq, record=record,
    )


class Index:
    def __init__(self, rows=(), allowed=True):
        self.rows=tuple(rows)
        self.allowed=allowed
        self.verified=[]
        self.listed=[]

    def verify_conversation_access(self, **kwargs):
        self.verified.append(kwargs)
        return self.allowed

    def list_authorized_artifacts(self, *, limit, **kwargs):
        self.listed.append({**kwargs, "limit":limit})
        return self.rows


def select(*, kind="xlsx", selector="latest", filename=None, artifact_id=None,
           integrity_ref=None, owner=OWNER, conversation=THREAD, workspace=WORKSPACE):
    return FollowupSelection(
        owner_id=owner, conversation_id=conversation,
        workspace_ref=workspace, output_kind=kind,
        selector=selector, filename=filename,
        artifact_id=artifact_id, integrity_ref=integrity_ref,
    )


class ConversationFollowupArtifactTests(unittest.TestCase):

    def test_cross_run_followup_selects_latest_authorized_xlsx(self):
        first=row("initial.xlsx",seq=1)
        second=row("revised.xlsx",seq=2)
        out=resolve_followup_artifact(selection=select(),index=Index((first,second)))
        self.assertEqual(out.status,FollowupStatus.RESOLVED)
        self.assertEqual(out.artifact_ref,LineageArtifactRef(
            second.record.artifact_id,second.record.integrity_ref))
        self.assertEqual(out.source_run_ref,second.source_run_ref)
        self.assertNotEqual(first.source_run_ref,second.source_run_ref)
        self.assertFalse(out.public_projection()["read_grant_issued"])
        self.assertFalse(out.public_projection()["memory_restored"])
        self.assertNotIn("opaque_provider_id",str(out.public_projection()))

    def test_latest_pdf_is_not_confused_with_xlsx(self):
        xlsx=row("revision.xlsx",seq=1)
        pdf=row("revision.pdf",kind="pdf",seq=2)
        out=resolve_followup_artifact(selection=select(kind="pdf"),index=Index((xlsx,pdf)))
        self.assertEqual(out.artifact_ref.artifact_id,pdf.record.artifact_id)
        self.assertEqual(resolve_followup_artifact(
            selection=select(kind="xlsx"),index=Index((xlsx,pdf))
        ).artifact_ref.artifact_id,xlsx.record.artifact_id)

    def test_duplicate_filename_prompts_confirmation_not_latest_guess(self):
        v1=row("quote.xlsx",seq=1)
        v2=row("quote.xlsx",seq=2)
        out=resolve_followup_artifact(selection=select(),index=Index((v1,v2)))
        self.assertEqual(out.status,FollowupStatus.CONFIRMATION_REQUIRED)
        self.assertIsNone(out.artifact_ref)
        self.assertEqual({x.artifact_id for x in out.choices},
                         {v1.record.artifact_id,v2.record.artifact_id})
        self.assertEqual([x.ordinal for x in out.choices],[2,1])
        explicit=resolve_followup_artifact(
            selection=select(selector="exact", artifact_id=v2.record.artifact_id,
                             integrity_ref=v2.record.integrity_ref),
            index=Index((v1,v2)))
        self.assertEqual(explicit.status,FollowupStatus.RESOLVED)
        self.assertEqual(explicit.artifact_ref.integrity_ref,v2.record.integrity_ref)

    def test_renamed_filename_requires_exact_new_name(self):
        a=row("before.xlsx",seq=1)
        b=row("renamed.xlsx",seq=2)
        self.assertEqual(resolve_followup_artifact(
            selection=select(selector="filename",filename="before.xlsx"),
            index=Index((b,))
        ).status,FollowupStatus.NOT_AVAILABLE)
        self.assertEqual(resolve_followup_artifact(
            selection=select(selector="filename",filename="renamed.xlsx"),
            index=Index((a,b))
        ).artifact_ref.artifact_id,b.record.artifact_id)

    def test_foreign_owner_workspace_thread_rejected_not_ignored(self):
        foreign=[
            row(owner=OTHER),
            row(conversation="chat_"+"b"*32),
            row(workspace="workspace_other"),
        ]
        for item in foreign:
            with self.subTest(item=item),self.assertRaises(ContractError):
                resolve_followup_artifact(selection=select(),index=Index((item,)))

    def test_logout_revoked_access_prevents_listing(self):
        index=Index((row(),),allowed=False)
        out=resolve_followup_artifact(selection=select(),index=index)
        self.assertEqual(out.status,FollowupStatus.NOT_AVAILABLE)
        self.assertEqual(index.listed,[])
        self.assertEqual(index.verified,[{
            "owner_id":OWNER,"conversation_id":THREAD,"workspace_ref":WORKSPACE
        }])

    def test_unregistered_or_non_durable_artifact_is_never_a_followup(self):
        with self.assertRaises(ContractError):
            row(durable=False)
        self.assertEqual(resolve_followup_artifact(
            selection=select(),index=Index(())
        ).status,FollowupStatus.NOT_AVAILABLE)

    def test_injected_row_schema_and_unbounded_index_fail_closed(self):
        for values in (None, [], ("untrusted",),
                       tuple(row(seq=i+1) for i in range(MAX_CANDIDATES+1))):
            with self.subTest(values=type(values)), self.assertRaises(ContractError):
                resolve_followup_artifact(
                    selection=select(), index=IndexRaw(values))

    def test_duplicate_canonical_id_or_tied_order_denied(self):
        a=row(seq=1)
        duplicate=replace(a,ordinal=2)
        with self.assertRaises(ContractError):
            resolve_followup_artifact(selection=select(),index=Index((a,duplicate)))
        tie=row("different.xlsx",seq=1,artifact="artifact_second")
        result=resolve_followup_artifact(selection=select(),index=Index((a,tie)))
        self.assertEqual(result.status,FollowupStatus.CONFIRMATION_REQUIRED)

    def test_confirmation_requires_exact_digest_not_filename_guess(self):
        a=row()
        bad="f"*64
        self.assertEqual(resolve_followup_artifact(
            selection=select(selector="exact",artifact_id=a.record.artifact_id,integrity_ref=bad),
            index=Index((a,))).status,FollowupStatus.NOT_AVAILABLE)
        with self.assertRaises(ContractError):
            select(selector="exact", artifact_id=a.record.artifact_id, integrity_ref="not-sha")
        with self.assertRaises(ContractError):
            select(selector="latest",artifact_id=a.record.artifact_id)
        with self.assertRaises(ContractError):
            select(selector="filename",filename="../secret.xlsx")

    def test_owner_and_conversation_request_validation(self):
        for kwargs in [
            {"owner":"owner:fake"},
            {"owner":"token_secret"},
            {"conversation":"file:///secret"},
            {"workspace":"workspace/foreign"},
            {"kind":"js"},
        ]:
            with self.subTest(kwargs=kwargs),self.assertRaises(ContractError):
                select(**kwargs)

    def test_non_downloadable_type_and_no_prod_truth(self):
        other=row("notes.txt",seq=1)
        # Canonical record has different MIME/suffix than the requested kind.
        result=resolve_followup_artifact(selection=select(kind="pdf"),index=Index((other,)))
        self.assertEqual(result.status,FollowupStatus.NOT_AVAILABLE)
        self.assertFalse(PRODUCTION_CONVERSATION_INDEX_COMPOSED)
        self.assertFalse(PRODUCTION_DURABLE_FOLLOWUP_ENABLED)


class IndexRaw(Index):
    def __init__(self, value):
        super().__init__(())
        self.value = value

    def list_authorized_artifacts(self, **kwargs):
        return self.value


if __name__=="__main__":
    unittest.main()
