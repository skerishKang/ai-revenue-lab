import time

import pytest

from claw_connect.batch_runner import bind_batch_services, run_batch


class Executor:
    def __init__(self, outputs=None):
        self.outputs = outputs or {}
        self.calls = []

    def execute_authorized(self, op, args, *, owner):
        self.calls.append((op, args, owner))
        if op == "stat" and args.get("slow"):
            time.sleep(0.15)
        if args.get("fail"):
            raise ValueError("invalid PC arguments")
        return {"ok": True, "value": self.outputs.get(op, args)}


class Store:
    def __init__(self):
        self.saved = []

    def store(self, output, *, owner, source):
        self.saved.append((output, owner, source))
        return {"handle": "handle-1", "head": output[:8], "tail": output[-8:],
                "size": len(output.encode()), "truncated": True}


def step(op, **args):
    return {"op": op, "args": args}


def test_read_batch_passes_owner_and_args_to_authorized_executor():
    executor, store = Executor(), Store()
    steps = [step("list", path="."), step("search", query="x"), step("read", path="a.txt")]
    with bind_batch_services(executor, store):
        result = run_batch(steps, owner="alice", total_timeout=1)
    assert result["completed"] == 3
    assert all(row["ok"] for row in result["results"])
    assert executor.calls == [(s["op"], s["args"], "alice") for s in steps]


@pytest.mark.parametrize("stop,completed,count", [(True, 1, 2), (False, 2, 3)])
def test_step_error_stop_or_continue(stop, completed, count):
    executor, store = Executor(), Store()
    steps = [step("list"), step("read", fail=True), step("stat")]
    with bind_batch_services(executor, store):
        result = run_batch(steps, owner="alice", stop_on_error=stop, total_timeout=1)
    assert result["completed"] == completed
    assert len(result["results"]) == count
    assert result["results"][1]["ok"] is False


@pytest.mark.parametrize("op", ["write", "move", "delete"])
def test_mutation_blocks_entire_batch_without_execution(op):
    executor, store = Executor(), Store()
    with bind_batch_services(executor, store):
        result = run_batch([step("read"), step(op)], owner="alice", total_timeout=1)
    assert result == {"results": [], "completed": 0, "requires_confirmation": True}
    assert not executor.calls and not store.saved


def test_total_timeout_stops_further_calls():
    executor, store = Executor(), Store()
    with bind_batch_services(executor, store):
        start = time.monotonic()
        result = run_batch([step("stat", slow=True), step("read")], owner="alice", total_timeout=0.02)
        elapsed = time.monotonic() - start
    assert elapsed < 0.12
    assert result["completed"] == 0
    assert result["results"][0]["summary"] == "batch timeout"
    assert len(executor.calls) == 1


def test_large_output_is_stored_for_owner_and_returns_handle():
    executor, store = Executor({"read": "가" * 5000}), Store()
    with bind_batch_services(executor, store):
        result = run_batch([step("read")], owner="alice", total_timeout=1)
    row = result["results"][0]
    assert row["ok"] and row["output_handle"] == "handle-1"
    assert "truncated" in row["summary"] and len(row["summary"]) < 200
    assert "가" * 5000 in store.saved[0][0]
    assert store.saved[0][1:] == ("alice", "pc_batch")


def test_unbound_executor_fails_closed():
    with pytest.raises(RuntimeError, match="not bound"):
        run_batch([step("read")], owner="alice", total_timeout=1)


def test_no_deadline_runs_existing_executor_and_shared_runner_identity():
    from padiem_ai_core.pc_batch import run_batch as shared_run_batch
    assert shared_run_batch is run_batch
    executor, store = Executor(), Store()
    with bind_batch_services(executor, store):
        result = run_batch([step("read")], owner="alice", total_timeout=None)
    assert result["completed"] == 1


def test_confirmed_batch_checks_whole_batch_before_first_pc_operation():
    events = []
    class ConfirmedExecutor(Executor):
        def confirm_batch(self, steps, *, owner):
            events.append(("confirm", [item["op"] for item in steps], owner))
            return True

        def execute_authorized(self, op, args, *, owner):
            events.append(("execute", op, owner))
            return super().execute_authorized(op, args, owner=owner)

    executor = ConfirmedExecutor()
    with bind_batch_services(executor, Store()):
        result = run_batch([step("read"), step("write")], owner="alice", total_timeout=None)
    assert result["completed"] == 2
    assert events == [("confirm", ["read", "write"], "alice"),
                      ("execute", "read", "alice"), ("execute", "write", "alice")]


@pytest.mark.parametrize("answer", [False, None, 1, "approved"])
def test_confirmation_must_be_trusted_exact_true_and_precedes_even_reads(answer):
    class UnconfirmedExecutor(Executor):
        def confirm_batch(self, steps, *, owner):
            return answer
    executor, store = UnconfirmedExecutor(), Store()
    with bind_batch_services(executor, store):
        result = run_batch([step("read"), step("delete")], owner="alice", total_timeout=None)
    assert result["requires_confirmation"] is True
    assert executor.calls == []
    assert store.saved == []
