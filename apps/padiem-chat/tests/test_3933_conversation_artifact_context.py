"""#3933 previous-work context: owner-scoped GET index only, no grant, no guess."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
TEST_DIR = ROOT / "tests"
sys.path.insert(0, str(TEST_DIR))

from test_3929_claw_conversation_artifact_d1 import (  # noqa: E402
    CHAT, OWNER, RUN, RUN2, WORKSPACE, call, canonical, setup_database,
    D1HistoryStore, D1Sqlite,
)

CONTRACT = "claw-conversation-artifact-followup.v1"


def _module() -> str:
    return (STATIC / "claw-conversation-artifact-context.js").read_text(
        encoding="utf-8")


def test_completed_file_context_runs_the_shipped_module_network_free():
    if shutil.which("node") is None:
        pytest.skip("Node unavailable locally; required B62 Linux CI harness")
    result = subprocess.run(
        ["node", str(TEST_DIR / "conversation_artifact_context_node.js")],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for marker in (
        "CONVERSATION_ARTIFACT_CONTEXT_OWNER_ONLY_GET=PASS",
        "CONVERSATION_ARTIFACT_CONTEXT_NO_GUESS_AMBIGUOUS=PASS",
        "CONVERSATION_ARTIFACT_CONTEXT_REFERENCE_NOT_GRANT=PASS",
        "CONVERSATION_ARTIFACT_CONTEXT_NEW_APPROVAL_REQUIRED=PASS",
        "CONVERSATION_ARTIFACT_CONTEXT_STALE_SWITCH_SAFE=PASS",
        "CONVERSATION_ARTIFACT_CONTEXT_DELEGATED_ADOPT_NO_SINK=PASS",
    ):
        assert marker in result.stdout


def test_context_module_is_get_only_and_uses_no_dom_sink():
    module = _module()
    assert '"/artifact-followup?"' in module
    assert "selector: params.selector" in module
    assert 'method: "GET"' in module
    assert "POST" not in module
    assert "innerHTML" not in module
    assert "insertAdjacentHTML" not in module
    # A reference is never presented as a download/byte operation.
    assert 'createElement("a")' not in module
    assert "read_grant_issued !== false" in module
    assert "source_material_loaded !== false" in module
    # #3933: continuing from a completed result is delegated to the shipped
    # panel module. This read-only module never owns the adopt route, the
    # adopted document identity or a transport of its own.
    assert "adoptFromArtifact" in module
    assert "artifact-followup/adopt" not in module
    assert "adopted_from_artifact_id" not in module
    assert "base64" not in module
    assert "arrayBuffer" not in module


def test_app_shell_mounts_and_clears_the_context_for_the_open_conversation():
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "PadiemClawConversationArtifactContext?.init?." in app
    assert "conversationArtifactContext?.show?.(data.conversation.id)" in app
    assert "conversationArtifactContext?.clear?.()" in app
    assert html.count('src="./claw-conversation-artifact-context.js"') == 1
    # The module registers before app.js executes so init() can bind the host.
    assert (html.index('src="./claw-conversation-artifact-context.js"')
            < html.index('src="./app.js"'))
    # The conversation-only handoff shape stays a separate, validated case.
    assert '"claw-web-work-conversation-opened-read"' in (STATIC / "locale.js").read_text(
        encoding="utf-8")
    assert "claw-web-work-conversation-opened-read" in app


def test_web_panel_exposes_only_server_verified_read_handoff():
    panel = (STATIC / "claw-web-xlsx-sources.js").read_text(encoding="utf-8")
    assert "function validateWorkConversation" in panel
    assert "validateWorkConversation(" in panel
    assert "detail: { conversationId: handle.conversationId }" in panel
    assert "workConversationReady: workConversationHandle !== null" in panel
    # The READ handoff never re-checks the revision artifact index or posts.
    assert "openReadWorkConversation" in panel


class TestFollowupProjectionContext:
    """Resolved references carry the display name from the SAME trusted rows."""

    def setup_method(self):
        self.db = setup_database()
        self.store = D1HistoryStore(D1Sqlite(self.db))

    def teardown_method(self):
        self.db.close()

    @pytest.mark.asyncio
    async def test_single_completed_file_is_named_without_private_location(self):
        record = canonical()
        assert await self.store.register_owner_conversation_artifact(
            user_id=OWNER, conversation_id=CHAT, workspace_ref=WORKSPACE,
            artifact=record)
        code, body, _ = await call(self.store)
        assert code == 200, body
        assert body["followup"]["contract_version"] == CONTRACT
        assert body["followup"]["status"] == "resolved"
        assert body["followup"]["source_artifact_id"] == record.artifact_id
        assert body["followup"]["source_filename"] == "quote.xlsx"
        assert "private_file_provider_ref" not in json.dumps(body)
        assert body["followup"]["read_grant_issued"] is False

    @pytest.mark.asyncio
    async def test_same_name_versions_require_user_choice_without_name_claim(self):
        first = canonical(artifact_id="artifact_3933_dup_a")
        self.db.execute(
            "UPDATE claw_run_history SET status='completed' WHERE run_id=?", (RUN2,))
        second = canonical(artifact_id="artifact_3933_dup_b", source_run=RUN2)
        assert await self.store.register_owner_conversation_artifact(
            user_id=OWNER, conversation_id=CHAT, workspace_ref=WORKSPACE,
            artifact=first)
        assert await self.store.register_owner_conversation_artifact(
            user_id=OWNER, conversation_id=CHAT, workspace_ref=WORKSPACE,
            artifact=second)
        code, body, _ = await call(self.store)
        assert code == 200, body
        followup = body["followup"]
        assert followup["status"] == "confirmation_required"
        assert len(followup["choices"]) == 2
        assert {choice["filename"] for choice in followup["choices"]} == {"quote.xlsx"}
        # No single "the previous file" claim is made for an ambiguous latest.
        assert "source_filename" not in followup
        assert followup["source_artifact_id"] is None
        exact_code, exact, _ = await call(
            self.store, selector="exact",
            artifact_id=second.artifact_id, integrity_ref=second.integrity_ref)
        assert exact_code == 200
        assert exact["followup"]["status"] == "resolved"
        assert exact["followup"]["source_filename"] == "quote.xlsx"

    @pytest.mark.asyncio
    async def test_tampered_path_name_cannot_be_projected(self):
        record = canonical(artifact_id="artifact_3933_path_name")
        assert await self.store.register_owner_conversation_artifact(
            user_id=OWNER, conversation_id=CHAT, workspace_ref=WORKSPACE,
            artifact=record)
        self.db.execute(
            "UPDATE claw_conversation_artifact_index SET filename=? "
            "WHERE artifact_id=?", ("../../secret.xlsx", record.artifact_id))
        self.db.commit()
        code, body, _ = await call(self.store)
        # The tampered durable row fails closed instead of leaking a path.
        assert code == 503
        assert "../../secret.xlsx" not in json.dumps(body)
