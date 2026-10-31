import hashlib
import importlib.util
import io
import time
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace

from kagent.local_agent_oracle_mesh_executor import OracleMeshExecutor

ROOT = Path(__file__).resolve().parents[3]
RUN = "chat_pcq_" + "a" * 32
DISPATCH = "dsp_" + "b" * 32


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_three_apps_use_the_same_bounded_hash():
    paths = [
        "apps/padiem-chat/app/pc_correlation.py",
        "apps/padiem-ai-engine/app/pc_correlation.py",
        "apps/korean-ai-code-agent/src/kagent/pc_correlation.py",
    ]
    expected = hashlib.sha256(RUN.encode("ascii")).hexdigest()[:16]
    for index, path in enumerate(paths):
        module = _load(path, f"contract_{index}")
        assert module.run_hash(RUN) == expected
        assert module.run_hash("chat_pcq_invalid") is None
        assert module.run_hash(RUN + "\n") is None


def test_executor_command_and_read_logs_do_not_emit_raw_run():
    dispatch = SimpleNamespace(dispatch_id=DISPATCH, run_id=RUN,
                               request_id="req", command_id="cmd")
    executor = object.__new__(OracleMeshExecutor)
    capture = io.StringIO()
    with redirect_stderr(capture):
        executor._trace_command(dispatch, "refused", time.monotonic(), reason="port")
        executor._trace_read(dispatch, "read_failed", time.monotonic(), error="not_utf8")
    lines = capture.getvalue().splitlines()
    assert len(lines) == 2
    for line in lines:
        assert f"run_hash={hashlib.sha256(RUN.encode()).hexdigest()[:16]}" in line
        assert f"dispatch_id={DISPATCH}" in line
        assert RUN not in line
