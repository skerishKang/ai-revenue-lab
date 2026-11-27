"""#3933 previous-work context: owner-scoped GET index only, no grant, no guess."""
from __future__ import annotations

from _r5_function_source import definition_source

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

from _support.conversation_artifact_d1 import (  # noqa: E402
    CHAT, OWNER, RUN, RUN2, WORKSPACE, call, canonical, setup_database,
    D1HistoryStore, D1Sqlite,
)

# #8060: 원문 읽기는 _support(conversation_artifact_source)가 담당하고 시험은
# 토큰·파싱 값·동작으로 단언한다.
from _support.conversation_artifact_source import (  # noqa: E402
    has,
    lacks,
    locale_has_key,
    script_src_before,
    script_src_count,
    tokens,
)

CONTRACT = "claw-conversation-artifact-followup.v1"


def test_completed_file_context_runs_the_shipped_module_network_free():
    if shutil.which("node") is None:
        pytest.skip("Node unavailable locally; required B62 Linux CI harness")
    result = subprocess.run(
        ["node", str(TEST_DIR / "conversation_artifact_context_node.js")],
        capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
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
    module_tokens = tokens("context")
    assert "/artifact-followup?" in module_tokens
    assert has("context", "selector: params.selector")
    assert has("context", 'method: "GET"')
    for forbidden in (
        "POST", "innerHTML", "insertAdjacentHTML", "base64", "arrayBuffer",
        "artifact-followup/adopt", "adopted_from_artifact_id",
    ):
        assert lacks("context", forbidden)
    # A reference is never presented as a download/byte operation.
    assert lacks("context", 'createElement("a")')
    assert has("context", "read_grant_issued !== false")
    assert has("context", "source_material_loaded !== false")
    # #3933: continuing from a completed result is delegated to the shipped
    # panel module. This read-only module never owns the adopt route, the
    # adopted document identity or a transport of its own.
    assert "adoptFromArtifact" in module_tokens


def test_app_shell_mounts_and_clears_the_context_for_the_open_conversation():
    assert has("app", "PadiemClawConversationArtifactContext?.init?.")
    assert "deps.conversationArtifactContext?.show?.(data.conversation.id)" in definition_source("openSavedConversation")
    # R5 A10: the clear call moved to the nav module.
    assert has("nav", "deps.conversationArtifactContext?.clear?.()")
    assert script_src_count("./claw-conversation-artifact-context.js") == 1
    # The module registers before app.js executes so init() can bind the host.
    assert script_src_before("./claw-conversation-artifact-context.js", "./app.js")
    # The conversation-only handoff shape stays a separate, validated case.
    assert locale_has_key("claw-web-work-conversation-opened-read")
    assert "claw-web-work-conversation-opened-read" in tokens("app")


def test_web_panel_exposes_only_server_verified_read_handoff():
    assert has("panel", "function validateWorkConversation")
    assert has("panel", "validateWorkConversation(")
    assert has("panel", "detail: { conversationId: handle.conversationId }")
    assert has("panel", "workConversationReady: workConversationHandle !== null")
    # The READ handoff never re-checks the revision artifact index or posts.
    assert has("panel", "openReadWorkConversation")


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
