"""PADIEM Claw -> Phone task *interface*, mock-only, not a registered tool.

A future canonical Claw/P01 adapter must inject the existing server-resolved
principal and a checked authorization callback. No browser-supplied 'claw'
source, model-generated grant or explicit user-id JSON becomes authority here.
No SIP/PSTN/LLM execution is available in this implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from hashlib import sha256
from threading import RLock

from phone_mock import MockPhoneTasks, TaskError
from phone_scripts import ScriptStore


@dataclass(frozen=True)
class CanonicalPhoneCaller:
    """Opaque server-derived identity projection, not an authentication mechanism."""

    subject_ref: str
    workspace_ref: str
    product_id: str = "padiem_claw"


class ClawPhoneTaskBridge:
    """Minimal tool port with default DENY before any mock task mutation."""

    def __init__(
        self,
        *,
        tasks: MockPhoneTasks,
        scripts: ScriptStore,
        authorize: Callable[[CanonicalPhoneCaller, str], bool] | None = None,
    ):
        self.tasks = tasks
        self.scripts = scripts
        self.authorize = authorize
        # Scoped only to this mock process. Unknown/restarted ownership fails
        # closed; production ownership belongs in the existing authority store.
        self.owner_by_task: dict[str, tuple[str, str]] = {}
        self.lock = RLock()

    def _admit(self, caller: CanonicalPhoneCaller, action: str) -> None:
        # No source string, request JSON or tool arguments can mint an identity.
        if (
            type(caller) is not CanonicalPhoneCaller
            or not isinstance(caller.subject_ref, str)
            or not caller.subject_ref.strip()
            or not isinstance(caller.workspace_ref, str)
            or not caller.workspace_ref.strip()
            or caller.product_id != "padiem_claw"
            or not callable(self.authorize)
        ):
            raise TaskError("phone_authorization_unavailable", 403)
        try:
            decision = self.authorize(caller, action)
        except Exception as exc:
            raise TaskError("phone_authorization_unavailable", 403) from None
        if decision is not True:
            raise TaskError("phone_not_authorized", 403)

    def execute(self, caller: CanonicalPhoneCaller, action: str, args: object) -> dict:
        """Tool actions start_mock/status/cancel. Only the registered Claw host
        may supply the server-derived caller + authorization callback.

        Production tool registration MUST bind this to existing Core tool
        grants, canonical user/workspace & auditable approvals. It is not bound
        in this preview and therefore fails closed by default.
        """
        if action not in ("start_mock", "status", "cancel"):
            raise TaskError("unknown_phone_tool_action")
        self._admit(caller, action)
        if not isinstance(args, dict):
            raise TaskError("invalid_tool_arguments")
        allowed_fields = {
            "start_mock": {"request_id", "goal", "destination", "script_id", "scenario"},
            "status": {"task_id"},
            "cancel": {"task_id"},
        }[action]
        if set(args) - allowed_fields:
            raise TaskError("invalid_tool_arguments")
        if action == "status" or action == "cancel":
            task_id = args.get("task_id")
            if not isinstance(task_id, str) or not 1 <= len(task_id) <= 80:
                raise TaskError("invalid_task_id")
            with self.lock:
                if self.owner_by_task.get(task_id) != (caller.subject_ref, caller.workspace_ref):
                    raise TaskError("phone_task_not_found", 404)
                task = self.tasks.get(task_id)
                if task["source"] != "claw":
                    raise TaskError("phone_task_not_found", 404)
                return self.tasks.get(task_id) if action == "status" else self.tasks.cancel(task_id)
        request = dict(args)
        request["source"] = "claw"  # server-controlled field
        user_request_id = request.get("request_id")
        if not isinstance(user_request_id, str) or not user_request_id:
            raise TaskError("invalid_request_id")
        # Namespace idempotency within one trusted subject/workspace. The
        # browser cannot set either canonical identity via request JSON.
        identity = f"{caller.subject_ref}\x00{caller.workspace_ref}\x00{user_request_id}"
        request["request_id"] = "claw_" + sha256(identity.encode("utf-8")).hexdigest()[:48]
        script_id = request.get("script_id")
        if script_id is not None:
            if not isinstance(script_id, str):
                raise TaskError("invalid_script_id")
            script = self.scripts.resolve(script_id)
            if request.get("goal") != script["goal"] or request.get("destination") != script["destination"]:
                raise TaskError("script_payload_mismatch", 409)
            request["questions"] = script["questions"]
            request["notes"] = script["notes"]
        with self.lock:
            result = self.tasks.create(request)
            existing_owner = self.owner_by_task.get(result["task_id"])
            if existing_owner is not None and existing_owner != (caller.subject_ref, caller.workspace_ref):
                raise TaskError("phone_task_not_found", 404)
            self.owner_by_task[result["task_id"]] = (caller.subject_ref, caller.workspace_ref)
            return result
