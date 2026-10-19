"""Hark WEB-FIRST follow-up navigation remains owner-index-gated, GET-only."""
from __future__ import annotations

from types import SimpleNamespace
import pytest

from app import claw_web_xlsx_quote_write_routes as routes

OWNER = "usr_owner"
WORKSPACE = "tenant_1"
RUN = "web_p01_run_1"
CHAT = "chat_" + "a" * 32
DOC = "doc_" + "b" * 32
SHA = "c" * 64


class History:
    def __init__(self):
        self.status = "completed"
        self.owner = OWNER
        self.sha = SHA
        self.raise_index = False
        self.calls = []

    async def get_claw_run(self, owner, run):
        self.calls.append(("run", owner, run))
        return {"run_id": RUN, "workspace_id": WORKSPACE,
                "conversation_id": CHAT, "status": self.status}

    async def get_owner_conversation_artifact(self, **kwargs):
        self.calls.append(("index", kwargs.copy()))
        if self.raise_index:
            raise RuntimeError("schema unavailable")
        return {
            "artifact_id": DOC, "integrity_ref": self.sha,
            "source_run_ref": RUN, "user_id": self.owner,
            "workspace_ref": WORKSPACE, "conversation_id": CHAT,
            "media_type": routes.XLSX_MEDIA_TYPE,
        }


async def status(monkeypatch, history, receipt=None):
    row = {
        "run_id": RUN, "state": "confirmed",
        "revision_document_id": DOC, "revision_sha256": SHA,
    } if receipt is None else receipt
    async def confirmed(_):
        return object(), row, OWNER, WORKSPACE, "sel_" + "d" * 32
    monkeypatch.setattr(routes, "_confirmed", confirmed)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        history_store=history, web_xlsx_quote_pdf_enabled=False,
    )))
    result = await routes.web_xlsx_quote_edit_status(request)
    return result


@pytest.mark.asyncio
async def test_confirmed_owner_exact_durable_index_returns_only_safe_reference(monkeypatch):
    history = History()
    result = await status(monkeypatch, history)
    import json
    payload = json.loads(result.body)
    assert result.status_code == 200
    assert "no-store" in result.headers["cache-control"]
    assert payload["followup"] == {
        "conversation_id": CHAT, "artifact_id": DOC, "integrity_ref": SHA,
    }
    assert payload["revision_document_id"] == DOC
    assert payload["revised_xlsx_created"] is True
    assert payload["pdf_exported"] is False
    assert history.calls[-1] == ("index", {
        "user_id": OWNER, "conversation_id": CHAT,
        "workspace_ref": WORKSPACE, "artifact_id": DOC,
    })
    assert "location_ref" not in payload
    assert "read_grant" not in payload
    assert "token" not in payload


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", [
    "running", "foreign_owner", "sha_drift", "schema_failed",
    "unconfirmed", "bad_document_id", "invalid_digest",
])
async def test_no_unverified_or_foreign_conversation_navigation(monkeypatch, defect):
    import json
    history = History()
    row = {"run_id": RUN, "state": "confirmed",
           "revision_document_id": DOC, "revision_sha256": SHA}
    if defect == "running":
        history.status = "running"
    elif defect == "foreign_owner":
        history.owner = "different_owner"
    elif defect == "sha_drift":
        history.sha = "f" * 64
    elif defect == "schema_failed":
        history.raise_index = True
    elif defect == "unconfirmed":
        row["state"] = "dispatching"
    elif defect == "bad_document_id":
        row["revision_document_id"] = "doc_bad"
    elif defect == "invalid_digest":
        row["revision_sha256"] = "bad"
    response = await status(monkeypatch, history, row)
    body = json.loads(response.body)
    assert response.status_code == 200
    assert body["followup"] is None
    assert "conversation_id" not in body
    if defect in ("running", "unconfirmed", "bad_document_id", "invalid_digest"):
        assert not any(k[0] == "index" for k in history.calls)
