"""공용 시험 준비 — Chat PC 드라이브 레인 더미·매핑.

test_chat_pc_drive가 들고 있던 더미(_B14·_Bridge·_History·_request)와
서명 매핑 상수를 여기 옮겨 시험끼리 import가 없게 한다(#8061).
"""
from __future__ import annotations

from types import SimpleNamespace

from app.orchestration_bridge import B62EngineOrchestrationBridge

_CHAT_OWNER = "usr_chat_9"
_CHAT_SUBJECT = "sub_" + "b" * 32
_CHAT_ACCOUNT = "account-chat-9"
_CHAT_WORKSPACE = "tenant-chat-9"
_CHAT_RUN = "chat_pcq_" + "r" * 24
_CHAT_CONVERSATION = "chat_" + "9" * 32
_CHAT_SECRET = "s" * 32
_CHAT_CHANNEL_SECRET = "deployment-channel-secret-value-chat"


class _B14:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    async def complete(self, messages, skill, additional_system_context=None):
        self.calls.append(additional_system_context)
        return {"answer": self.answers.pop(0)}


class _Bridge(B62EngineOrchestrationBridge):
    def __init__(self, answer):
        super().__init__(client=object(), store=object())
        self.answer = answer
        self.requests = []

    async def start(self, **fields):
        self.requests.append(fields)
        return SimpleNamespace(answer=self.answer, public={"answer": self.answer})


class _History:
    def __init__(self):
        self.pairs = []
        self.staged = None
        self.appended = []

    async def append_exchange(self, user_id, conversation_id, user_text, answer, *, product_scope):
        assert product_scope == "b62-chat"
        self.pairs.append((user_text, answer))
        return conversation_id or ("chat_" + "n" * 32)

    async def record_chat_pc_drive_run(self, *, user_id, run_id, workspace_id, user_text, conversation_id, **extra):
        assert run_id.startswith("chat_pcq_")
        self.staged = {"run_id": run_id, "workspace_id": workspace_id, **extra}
        return conversation_id or ("chat_" + "s" * 32)

    async def get_claw_run(self, user_id, run_id):
        return {"run_id": run_id, "conversation_id": "chat_" + "s" * 32,
                "result_summary": "no_exit_code", "workspace_id": "tenant-1"}

    async def append_local_task_result(self, **fields):
        assert fields["summary"] == "no_exit_code"
        assert fields["message_id"].endswith("_answer")
        self.appended.append(fields)
        return True


def _request(*, user="usr_chat_1", model_answers, engine_answer="C: 드라이브가 있습니다."):
    b14 = _B14(model_answers)
    bridge = _Bridge(engine_answer)
    history = _History()
    state = SimpleNamespace(
        b14_client=b14, orchestration_bridge=bridge, history_store=history,
        identity_shadow_store=object(), control_plane_identity_authority=object(),
        oracle_mesh_return_source=SimpleNamespace(execution_mode="mesh"),
        settings=SimpleNamespace(auth_mode="mock"),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=state),
        cookies={"padiem_session": "signed-" + user} if user else {},
    )
    return request, b14, bridge, history


def _chat_mapping():
    # Ownership rows are TXT grants; the command lane reuses the row carrying
    # the command_exec grant, mirroring the Claw lane's deployment shape.
    return [{
        "account_ref": _CHAT_ACCOUNT, "device_id": "chat-device-1",
        "node_ref": "chat-node-1",
        "root_ref": "meshcentral_private_trial",
        "path_relative": "meshcentral-padiem-trial.txt",
        "file_path": "C:\\padiem\\meshcentral-padiem-trial.txt",
        "command_exec": True,
    }]
