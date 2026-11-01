"""The signed root mapping reaches the guard, never the model's prompt."""
import asyncio
import json
from unittest.mock import patch

from tests.test_6460_pc_action_driver import (
    DELETE, DEVICE_ID, DONE, _WritePcEndpoint, _ScriptedModel, _payload, _service,
)
from tests.test_5574_pc_read_boundary_end_to_end import _Response, _instant_sleep


def test_signed_folder_roots_resolve_delegation_without_entering_model_input():
    actual_root = "C:/Users/owner/private-work"

    class WithGuardRoots(_WritePcEndpoint):
        async def fetch(self, request):
            response = await super().fetch(request)
            if json.loads(request.body)["mode"] != "context":
                return response
            context = json.loads(await response.text())
            # Like the real Chat callback, identify the owner-selected PC even
            # when the request let the server choose its sole connected PC.
            context["device"]["device_id"] = DEVICE_ID
            context["delegation_roots"] = [{"label": "작업", "path": actual_root}]
            return _Response(context)

    model = _ScriptedModel([json.dumps(DELETE), json.dumps({"action": "complete", "answer": DONE})])
    pc = WithGuardRoots()
    payload = _payload([{"role": "user", "content": "notes.txt 파일을 지워줘"}])
    payload["pc_delegation"] = {"version": 1, "rules": [{
        "id": "delegated-folder", "device_id": DEVICE_ID, "folder": actual_root,
        "actions": ["delete"], "mode": "allow", "enabled": True,
    }]}
    with patch.object(asyncio, "sleep", _instant_sleep):
        response = asyncio.run(_service(model, pc).orchestrate_payload(payload))
    assert response.status_code == 200, response.body
    assert response.body["orchestration"]["execution"]["answer"] == DONE
    assert pc.ops == ["delete"]  # Relative target matched the signed absolute root.
    assert len(model.prompts) == 2
    assert all(actual_root not in prompt and "delegation_roots" not in prompt for prompt in model.prompts)
