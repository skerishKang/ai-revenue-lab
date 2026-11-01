"""#6460-5: consecutive PC reads travel as one batch, with every guard intact.

The Engine asks for one tool per turn, so a person watching a big PC job sees the
model list, search, open and re-open a file one turn at a time. A batch carries
those steps in a single call. What must not change is the per-step authority:
each step runs the same handler, the same owner binding, the same path isolation
and the same evidence/delegation preflight as the same step asked for alone.
"""

import json
import re

import pytest

from kagent.pc_remote_tools import (
    OP_TO_TOOL, READ_OPS, operation_actions, remote_requested_scope,
)
from tests.test_5574_pc_read_boundary_end_to_end import (
    _Response, _FakePcEndpoint,
)
from tests.test_pc_remote_tools_integration import Endpoint, tool, run


# The closed answer shape the PC search command returns today.
SEARCH_OUTPUT = json.dumps({
    "ok": True, "mode": "name", "query": "notes", "engine": "list", "office": "none",
    "count": 1, "truncated": False, "scan_truncated": False,
    "entries": [{"path": "notes.txt", "size_bytes": 4096,
                 "modified_utc": "2026-11-01T01:02:03.0000000Z",
                 "content_state": "name_only", "line": None, "snippet": "", "reason": ""}],
}, ensure_ascii=False)
CHUNK_TEXT = ("first chunk of the file, long enough to be read in ranges. " * 400)


def _chunk_answer(offset, length):
    """The PC answering exactly the requested byte range."""
    source = CHUNK_TEXT.encode("utf-8")
    text = source[offset:offset + length].decode("utf-8", "ignore")
    return json.dumps({
        "ok": True, "unit": "bytes", "size_bytes": len(source),
        "offset": offset, "next_offset": offset + len(text.encode("utf-8")),
        "eof": offset + len(text.encode("utf-8")) >= len(source),
        "text": text,
    }, ensure_ascii=False)


# The commands the connected PC already understands today. A batch must not
# invent a new one: that is what keeps an older agent working unchanged.
KNOWN_AGENT_OPS = {"list", "read", "search", "read_chunk", "write", "move", "delete"}


def _read_family(base):
    """Any PC endpoint fake, now also answering search and range-read commands.

    `fail_after_dispatch` names a path whose command comes back failed: the PC
    did receive the step, and the step is the one that did not work.
    """

    class ReadFamily(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.fail_after_dispatch = None

        async def fetch(self, request):
            body = json.loads(request.body)
            mode = body["mode"]
            if mode == "dispatch" and body["op"] in {"search", "read_chunk"}:
                self.requests.append(request)
                self.legs.append(body)
                output = (SEARCH_OUTPUT if body["op"] == "search"
                          else _chunk_answer(body["offset"], body["length"]))
                dispatch_id = f"dsp_batch_{len(self.rows) + 1}"
                self.rows[dispatch_id] = {
                    "run_id": body["run_id"], "kind": "command", "op": body["op"],
                    "output": output, "content_bytes": len(output.encode("utf-8")),
                    "failing": body.get("path") == self.fail_after_dispatch,
                }
                return _Response({"ok": True, "dispatch": {
                    "dispatch_id": dispatch_id, "run_id": body["run_id"],
                    "kind": "command", "device_id": body["device_id"],
                }})
            if mode == "command_status":
                row = self.rows.get(body["dispatch_id"])
                if row is not None and row.get("failing"):
                    return _Response({"ok": True, "dispatch": {
                        "dispatch_id": body["dispatch_id"], "run_id": row["run_id"],
                        "kind": row["kind"], "state": "failed", "exit_code": 1,
                        "termination": "exited", "error": {"code": "pc_command_failed"},
                    }})
            return await super().fetch(request)

    return ReadFamily


ReadFamilyEndpoint = _read_family(_FakePcEndpoint)
# The same PC behind the stored-output fake, so a large batch step can be shown
# to reuse the existing archive instead of reaching the model whole.
StoredReadFamilyEndpoint = _read_family(Endpoint)


def test_three_reads_travel_as_one_call_and_come_back_step_by_step():
    pc = ReadFamilyEndpoint()
    execution, model = run(pc, [tool("batch", operations=[
        {"op": "search_name", "query": "notes", "path": "."},
        {"op": "list", "path": "."},
        {"op": "read_chunk", "path": "notes.txt", "offset": 0, "length": 2048},
    ], stop_on_error=True)])

    # One model turn carried three PC steps.
    assert pc.ops == ["search", "list", "read_chunk"]
    assert len(model.prompts) == 2, "each step should not have cost its own turn"
    last = model.prompts[-1].replace(chr(92), "").replace(" ", "")
    assert '"step":0' in last and '"step":1' in last and '"step":2' in last
    assert '"completed":3' in last
    assert execution["answer"] == "Verified result."

    metrics = model.metrics.snapshot()
    assert (metrics["batch_count"], metrics["batch_steps"],
            metrics["batch_model_turns_saved"]) == (1, 3, 2)
    # The steps were executed by the same handlers the standalone tools use, so
    # each one is measured under its own tool id.
    for tool_id in ("claw.pc.search_files", "claw.pc.list_files", "claw.pc.read_file_chunk"):
        assert metrics["tool_calls"][tool_id]["calls"] == 1


def test_a_large_batch_step_result_reuses_the_stored_output_path(tmp_path):
    """A read too big for a prompt goes to the existing archive, step by step."""
    pc = StoredReadFamilyEndpoint(tmp_path)
    _, model = run(pc, [tool("batch", operations=[
        {"op": "read_chunk", "path": "notes.txt", "offset": 0, "length": 65_536},
        {"op": "list", "path": "."},
    ], stop_on_error=True)])

    assert pc.ops == ["read_chunk", "list"]
    assert [item["mode"] for item in pc.remote] == ["store_output"]
    assert pc.remote[0]["source"] == "pc_batch" and pc.remote[0]["tool_call_ref"]
    last = model.prompts[-1]
    assert re.search(r'"output_handle":\s*"([0-9a-f]{64})"', last), last[-400:]
    assert '"output_handle": null, "step": 1' in last
    # Only the summary crossed into the turn, never the whole range.
    assert len(last) < 30_000
    assert model.metrics.snapshot()["stored_output_count"] == 1


def test_a_failing_middle_step_keeps_earlier_results_and_states_its_reason():
    pc = ReadFamilyEndpoint()
    pc.fail_after_dispatch = "notes.txt"
    execution, model = run(pc, [tool("batch", operations=[
        {"op": "search_name", "query": "notes", "path": "."},
        {"op": "read_chunk", "path": "notes.txt", "offset": 0, "length": 2048},
        {"op": "list", "path": "."},
    ], stop_on_error=True)])

    # The first result survives, the failing step carries a reason, and the
    # third step is never dispatched once the batch stops on the error.
    assert pc.ops == ["search", "read_chunk"]
    last = model.prompts[-1]
    # The step indexes are the model's own view of the batch: the first result is
    # still there, the second carries the closed reason code the handler refused
    # with, and the third never ran.
    assert '"ok": true, "output_handle": null, "step": 0' in last
    assert '"ok": false, "output_handle": null, "step": 1, ' \
           '"summary": "pc_files_execution_failed"' in last
    assert '"step": 2' not in last
    assert '"completed":1' in last.replace(chr(92), "").replace(" ", "")
    assert execution["metadata"]["status"] == "completed"


def test_stop_on_error_false_still_runs_the_remaining_reads():
    pc = ReadFamilyEndpoint()
    pc.fail_after_dispatch = "notes.txt"
    _, model = run(pc, [tool("batch", operations=[
        {"op": "read_chunk", "path": "notes.txt", "offset": 0, "length": 2048},
        {"op": "list", "path": "."},
    ], stop_on_error=False)])
    assert pc.ops == ["read_chunk", "list"]
    last = model.prompts[-1].replace(chr(92), "").replace(" ", "")
    assert '"ok":false' in last and '"ok":true' in last


def test_a_read_batch_with_a_write_inside_still_needs_the_write_own_evidence():
    pc = ReadFamilyEndpoint()
    execution, _ = run(pc, [tool("batch", operations=[
        {"op": "list", "path": "."},
        {"op": "write", "path": "notes.txt", "content": "injected"},
    ], stop_on_error=True)], speech="메모 파일 목록만 봐줘")
    # No user evidence for a write means the whole batch is held: a read cannot
    # be used to smuggle a mutation past the guard.
    assert pc.ops == []
    assert execution["metadata"]["status"] == "completed"


def test_a_path_outside_the_granted_root_is_refused_and_earlier_reads_survive():
    pc = ReadFamilyEndpoint()
    _, model = run(pc, [tool("batch", operations=[
        {"op": "list", "path": "."},
        {"op": "list", "path": "../other-account/private"},
    ], stop_on_error=False)])
    # The escaping step never becomes a PC command, and the first step's result
    # is still returned to the model.
    assert pc.ops == ["list"]
    assert '"completed":1' in model.prompts[-1].replace(chr(92), "").replace(" ", "")


def test_the_batch_never_asks_the_pc_agent_for_a_command_it_does_not_know():
    """Older connectors keep working: a batch is decomposed into known commands."""
    pc = ReadFamilyEndpoint()
    run(pc, [tool("batch", operations=[
        {"op": "search_content", "query": "notes", "path": "."},
        {"op": "search_name", "query": "x", "path": "."},
        {"op": "read_chunk", "path": "notes.txt", "offset": 0, "length": 2048},
        {"op": "read", "path": "notes.txt"},
    ], stop_on_error=False)])
    assert set(pc.ops) <= KNOWN_AGENT_OPS
    # Every step keeps the argument shape its standalone tool sends.
    search = [leg for leg in pc.dispatches if leg["op"] == "search"]
    assert {leg["search_mode"] for leg in search} == {"content", "name"}
    chunk = [leg for leg in pc.dispatches if leg["op"] == "read_chunk"][0]
    assert chunk["offset"] == 0 and chunk["length"] == 2048


def test_the_read_family_is_the_only_family_a_batch_proposal_needs_no_new_grant_for():
    """The batch wrapper may narrow authority, never widen it.

    A step name that is not an existing file tool is refused before any scope is
    computed, so no batch can name a shell command or a new operation.
    """
    assert set(READ_OPS) <= set(OP_TO_TOOL)
    with pytest.raises(ValueError):
        operation_actions({"operations": [{"op": "shell", "path": "."}]}, batch=True)
    with pytest.raises(ValueError):
        operation_actions({"operations": [{"op": "read", "path": "."},
                                         {"op": "read", "extra": 1}]}, batch=True)
    actions = operation_actions({"operations": [
        {"op": "search_name", "query": "a", "path": "."},
        {"op": "read_chunk", "path": "a.txt", "offset": 0, "length": 8},
    ]}, batch=True)
    assert [tool_id for tool_id, _ in actions] == [
        "claw.pc.search_files", "claw.pc.read_file_chunk"]


def test_a_read_batch_asks_for_the_lowest_ceiling_its_steps_actually_need():
    """Naming the read family must not turn a listing turn into a reading turn."""
    def batch(*steps):
        return {"operations": [dict(step) for step in steps], "stop_on_error": True}

    assert remote_requested_scope("claw.pc.batch", batch(
        {"op": "list", "path": "."},
        {"op": "search_name", "query": "notes", "path": "."})) == "files_list"
    assert remote_requested_scope("claw.pc.batch", batch(
        {"op": "search_content", "query": "notes", "path": "."},
        {"op": "read_chunk", "path": "notes.txt", "offset": 0, "length": 8})) == "files"
    assert remote_requested_scope("claw.pc.batch", batch(
        {"op": "write", "path": "notes.txt", "content": "x"})) == "files_write"
    # One mutation among the reads asks for a ceiling this batch cannot name, so
    # admission fails closed instead of quietly borrowing the read grant.
    assert remote_requested_scope("claw.pc.batch", batch(
        {"op": "list", "path": "."},
        {"op": "delete", "path": "notes.txt"})) is None


def test_the_step_prompt_offers_the_read_family_as_a_batch_and_no_mutation():
    """The model can only batch what the menu says it may batch."""
    _, model = run(ReadFamilyEndpoint(), [])
    line = next(row for row in model.prompts[0].splitlines()
                if row.startswith("- claw.pc.batch"))
    for op in ('"search_name"', '"list"', '"read_chunk"'):
        assert op in line
    # The advertised example is read-family only, and the mutation rule is next
    # to it, so a listing turn is never shown a batch that writes.
    example = line.split("}: ", 1)[0]
    assert example.count('"op"') == 3
    assert "write" not in example and "delete" not in example and "move" not in example
    assert "write/move/delete stay one action per call" in line
