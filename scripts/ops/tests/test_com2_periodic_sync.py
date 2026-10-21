from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "com2_periodic_sync.py"

REFRESH_STUB = """
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
behavior = json.loads((root / "behavior.json").read_text(encoding="utf-8"))
if behavior.get("d1_exit"):
    print("fixture d1 failure", file=sys.stderr)
    sys.exit(behavior["d1_exit"])
print("D1_PUBLISHED_GENERATION gen-d1 DATABASES 2")
"""

R2_STUB = """
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
call = "diff-only" if "--diff-only" in sys.argv else "full"
with (root / "r2_calls.txt").open("a", encoding="utf-8") as handle:
    handle.write(call + "\\n")
behavior = json.loads((root / "behavior.json").read_text(encoding="utf-8"))
if "--diff-only" in sys.argv:
    diff = behavior.get("diff", {"workspace": 0, "b66": 0, "media": 0})
    for bucket, new in diff.items():
        print(f"DIFF {bucket} BASE_GEN=gen REMOTE=1 BYTES=1 NEW={new} CHANGED=0 "
              "DELETED_REMOTE=0 UNCHANGED=1")
    sys.exit(0)
if behavior.get("r2_sync_exit"):
    print("fixture r2 failure", file=sys.stderr)
    sys.exit(behavior["r2_sync_exit"])
print("R2_PUBLISHED_GENERATION gen-r2 DELTA_OBJECTS 1")
"""

# #5484: the D1 stub that really publishes a generation, so the B62 runtime
# pointer can be published from it.
PUBLISHING_REFRESH_STUB = """
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
generation = "20261021T074313336936Z"
r2_generation = "20261021T074335749153Z"
snapshot = root / "snapshots" / "generations" / generation
snapshot.mkdir(parents=True, exist_ok=True)
database = snapshot / "chat.sqlite3"
connection = sqlite3.connect(database)
connection.execute("CREATE TABLE t0 (a INTEGER)")
connection.commit()
connection.close()
digest = hashlib.sha256(database.read_bytes()).hexdigest()
(root / "snapshots" / "current_generation.json").write_text(
    json.dumps({
        "generation": generation,
        "databases": {"chat": {"sha256": digest, "bytes": database.stat().st_size, "tables": 1}},
        "fresh_remote_export": True,
        "production_bound": False,
    }),
    encoding="utf-8",
)
r2 = root / "r2-staging" / "generations" / r2_generation
r2.mkdir(parents=True, exist_ok=True)
(r2 / "manifest.json").write_text("[]", encoding="utf-8")
(root / "r2-staging" / "current_generation.json").write_text(
    json.dumps({"generation": r2_generation, "production_bound": False}), encoding="utf-8"
)
print("D1_PUBLISHED_GENERATION", generation, "DATABASES", 2)
"""


def _load():
    spec = importlib.util.spec_from_file_location("com2_periodic_sync_ops", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sync_ops = _load()


class FakeInventoryServer:
    def __init__(
        self,
        *,
        truncated: bool = False,
        fail_bucket: str | None = None,
        fail_times: int = 0,
        counts: dict[str, int] | None = None,
    ):
        self.state = {
            "truncated": truncated,
            "fail_bucket": fail_bucket,
            "fail_times": fail_times,
            "counts": counts or {"workspace": 2, "b66": 1, "media": 3},
            "requests": [],
        }
        state = self.state

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                return None

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                bucket = urllib.parse.parse_qs(parsed.query).get("bucket", [""])[0]
                state["requests"].append(bucket)
                if bucket == state["fail_bucket"] and state["fail_times"] > 0:
                    state["fail_times"] -= 1
                    body = b'{"error":"fixture"}'
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                count = state["counts"].get(bucket)
                if parsed.path != "/inventory" or count is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                objects = [{"key": f"fixture-{i}", "size": 1, "etag": "e"} for i in range(count)]
                body = json.dumps(
                    {
                        "objects": objects,
                        "count": len(objects),
                        "pages": 1,
                        "truncated": state["truncated"],
                        "captured_utc": "2026-10-19T00:00:00.000Z",
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def _factory(**options):
    def build(*_args, **_kwargs):
        return FakeInventoryServer(**options)
    return build


def _make_root(tmp_path: Path, behavior: dict | None = None) -> Path:
    root = tmp_path / "storage-migration"
    (root / "logs").mkdir(parents=True)
    (root / "r2-staging" / "incoming").mkdir(parents=True)
    (root / "refresh_d1.py").write_text(REFRESH_STUB, encoding="utf-8")
    (root / "r2_sync.py").write_text(R2_STUB, encoding="utf-8")
    (root / "inventory.mjs").write_text("export default {};\n", encoding="utf-8")
    (root / "wrangler.inventory.toml").write_text("name = \"fixture\"\n", encoding="utf-8")
    (root / "behavior.json").write_text(
        json.dumps(behavior or {}), encoding="utf-8"
    )
    return root


def _status(root: Path) -> dict:
    return json.loads((root / "scheduled-sync-status.json").read_text(encoding="utf-8"))


def _r2_calls(root: Path) -> list[str]:
    path = root / "r2_calls.txt"
    if not path.is_file():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_unchanged_r2_skips_the_full_sync(tmp_path):
    root = _make_root(tmp_path)

    code = sync_ops.run_once(root, inventory_factory=_factory(), retry_delay=0)

    assert code == 0
    assert _r2_calls(root) == ["diff-only"]
    status = _status(root)
    assert status["ok"] is True
    assert status["d1"]["generation"] == "gen-d1"
    assert status["r2"]["mode"] == "unchanged"
    assert status["r2"]["inventory"] == {"workspace": 2, "b66": 1, "media": 3}
    assert status["r2"]["new"] == 0
    assert not (root / sync_ops.LOCK_NAME).exists()


def test_delta_runs_the_full_sync_and_records_generation(tmp_path):
    root = _make_root(tmp_path, {"diff": {"workspace": 2, "b66": 1, "media": 0}})

    code = sync_ops.run_once(root, inventory_factory=_factory(), retry_delay=0)

    assert code == 0
    assert _r2_calls(root) == ["diff-only", "full"]
    status = _status(root)
    assert status["r2"]["mode"] == "synced"
    assert status["r2"]["new"] == 3
    assert status["r2"]["generation"] == "gen-r2"


def test_d1_failure_skips_r2_and_records_the_step(tmp_path):
    root = _make_root(tmp_path, {"d1_exit": 3})

    code = sync_ops.run_once(root, inventory_factory=_factory(), retry_delay=0)

    assert code == 1
    assert _r2_calls(root) == []
    status = _status(root)
    assert status["ok"] is False
    assert status["failed_step"] == "d1"
    assert status["error"] == "d1_refresh_failed"
    assert status["d1"]["exit"] == 3


def test_r2_sync_failure_is_not_reported_as_success(tmp_path):
    root = _make_root(
        tmp_path, {"diff": {"workspace": 1, "b66": 0, "media": 0}, "r2_sync_exit": 2}
    )

    code = sync_ops.run_once(root, inventory_factory=_factory(), retry_delay=0)

    assert code == 1
    status = _status(root)
    assert status["ok"] is False
    assert status["failed_step"] == "r2_sync"
    assert status["error"] == "r2_sync_failed"
    assert status["r2"]["exit"] == 2


def test_truncated_inventory_aborts_before_the_diff(tmp_path):
    root = _make_root(tmp_path)

    code = sync_ops.run_once(
        root, inventory_factory=_factory(truncated=True), retry_delay=0
    )

    assert code == 1
    assert _r2_calls(root) == []
    status = _status(root)
    assert status["failed_step"] == "inventory"
    assert status["error"] == "inventory_incomplete:workspace"


def test_persistent_inventory_failure_retries_then_aborts(tmp_path):
    root = _make_root(tmp_path)
    server_box = {}

    def factory(*_args, **_kwargs):
        server = FakeInventoryServer(fail_bucket="media", fail_times=99)
        server_box["server"] = server
        return server

    code = sync_ops.run_once(root, inventory_factory=factory, retry_delay=0)

    assert code == 1
    assert _r2_calls(root) == []
    assert server_box["server"].state["requests"].count("media") == 3
    status = _status(root)
    assert status["failed_step"] == "inventory"
    assert status["error"] == "inventory_request_failed:media"


def test_transient_inventory_failure_is_retried(tmp_path):
    root = _make_root(tmp_path)

    code = sync_ops.run_once(
        root,
        inventory_factory=_factory(fail_bucket="media", fail_times=2),
        retry_delay=0,
    )

    assert code == 0
    assert _status(root)["ok"] is True
    assert _r2_calls(root) == ["diff-only"]


def test_fresh_lock_prevents_overlap(tmp_path):
    root = _make_root(tmp_path)
    lock = root / sync_ops.LOCK_NAME
    lock.write_text(json.dumps({"pid": 999999}), encoding="utf-8")

    code = sync_ops.run(root, inventory_factory=_factory(), retry_delay=0)

    assert code == 1
    assert _r2_calls(root) == []
    assert lock.exists()


def test_stale_lock_is_replaced(tmp_path):
    root = _make_root(tmp_path)
    lock = root / sync_ops.LOCK_NAME
    lock.write_text(json.dumps({"pid": 999999}), encoding="utf-8")
    old = time.time() - 4 * 3600
    os.utime(lock, (old, old))

    code = sync_ops.run(
        root, stale_minutes=180, inventory_factory=_factory(), retry_delay=0
    )

    assert code == 0
    assert _status(root)["ok"] is True
    assert not lock.exists()


def test_rerun_with_no_delta_does_not_copy_twice(tmp_path):
    root = _make_root(tmp_path)

    assert sync_ops.run_once(root, inventory_factory=_factory(), retry_delay=0) == 0
    assert sync_ops.run_once(root, inventory_factory=_factory(), retry_delay=0) == 0

    assert _r2_calls(root) == ["diff-only", "diff-only"]


def test_status_contains_no_object_keys(tmp_path):
    root = _make_root(tmp_path)

    assert sync_ops.run_once(root, inventory_factory=_factory(), retry_delay=0) == 0

    serialized = json.dumps(_status(root))
    assert "fixture-0" not in serialized
    assert "objects" not in serialized


def test_install_task_dry_run_writes_nothing(tmp_path, capsys):
    root = _make_root(tmp_path)
    repo = tmp_path / "repo"

    code = sync_ops.main(
        [
            "install-task",
            "--root", str(root),
            "--repo", str(repo),
            "--dry-run",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"][:2] == ["schtasks", "/Create"]
    assert "PADIEM-COM2-D1-R2-Sync" in payload["command"]
    assert "04:20" in payload["command"]
    assert "run --root" in payload["content"]
    assert not (root / "run-scheduled-sync.ps1").exists()


def test_install_task_rejects_incomplete_layout(tmp_path, capsys):
    root = _make_root(tmp_path)
    (root / "r2_sync.py").unlink()

    code = sync_ops.main(
        ["install-task", "--root", str(root), "--repo", str(tmp_path), "--dry-run"]
    )

    assert code == 1
    assert "TASK_INSTALL_FAILED reason=ops_layout_incomplete:r2_sync.py" in capsys.readouterr().err


def test_status_missing_returns_two(tmp_path, capsys):
    root = tmp_path / "empty"
    root.mkdir()

    assert sync_ops.main(["status", "--root", str(root)]) == 2
    assert "STATUS_MISSING" in capsys.readouterr().err


# #5484: a remote R2 binding needs a Cloudflare credential. The inventory
# Worker must receive it from the same DPAPI secret store the D1 export uses,
# otherwise "wrangler dev" exits with "You must be logged in to use wrangler dev
# in remote mode" and the whole sync fails before the first inventory request.


def test_the_inventory_worker_is_started_through_the_secret_store(tmp_path):
    store = tmp_path / "store.py"
    store.write_text("# test double\n", encoding="utf-8")

    command = sync_ops.inventory_command(
        wrangler="wrangler.cmd", port=1234, secret_store=store
    )

    assert command[0] == sys.executable
    assert command[1] == str(store)
    assert command[2] == "run"
    assert command[3] == "wrangler.cmd"
    assert command[4:] == [
        "dev",
        "--config",
        "wrangler.inventory.toml",
        "--port",
        "1234",
    ]


def test_the_inventory_worker_stays_unchanged_without_a_store(tmp_path):
    command = sync_ops.inventory_command(
        wrangler="wrangler.cmd", port=1234, secret_store=tmp_path / "missing.py"
    )

    assert command == [
        "wrangler.cmd",
        "dev",
        "--config",
        "wrangler.inventory.toml",
        "--port",
        "1234",
    ]
    assert sync_ops.inventory_command(wrangler="wrangler.cmd", port=1234) == command


def test_the_run_command_passes_the_secret_store_to_the_inventory_worker(tmp_path):
    root = _make_root(tmp_path)
    store = tmp_path / "store.py"
    store.write_text("# test double\n", encoding="utf-8")
    seen = {}

    def factory(*_args, **kwargs):
        seen.update(kwargs)
        return FakeInventoryServer()

    code = sync_ops.run_once(
        root, inventory_factory=factory, retry_delay=0, secret_store=store
    )

    assert code == 0
    assert seen["secret_store"] == store


def test_the_default_secret_store_is_the_com2_dpapi_store():
    assert sync_ops.DEFAULT_SECRET_STORE.endswith("store.py")
    assert "secret-store" in sync_ops.DEFAULT_SECRET_STORE


# #5484: nothing published the B62 runtime pointer after a successful sync, so
# the COM2 B62 runtime kept serving an old generation while the sync published
# a new one every day.


def test_the_sync_publishes_the_b62_runtime_pointer(tmp_path):
    root = _make_root(tmp_path)
    (root / "refresh_d1.py").write_text(PUBLISHING_REFRESH_STUB, encoding="utf-8")
    store = tmp_path / "b62-runtime" / "generation-store"
    store.parent.mkdir(parents=True, exist_ok=True)

    code = sync_ops.run_once(
        root, inventory_factory=_factory(), retry_delay=0, b62_store=store
    )

    assert code == 0
    pointer = json.loads((store / "current_generation.json").read_text(encoding="utf-8"))
    assert pointer["d1_generation"] == "20261021T074313336936Z"
    assert pointer["r2_generation"] == "20261021T074335749153Z"
    assert pointer["production_bound"] is False
    assert (store / pointer["d1_seed"]).is_file()


def test_the_pointer_step_is_skipped_on_a_host_without_a_b62_runtime_store(tmp_path):
    root = _make_root(tmp_path)
    (root / "refresh_d1.py").write_text(PUBLISHING_REFRESH_STUB, encoding="utf-8")

    code = sync_ops.run_once(
        root, inventory_factory=_factory(), retry_delay=0, b62_store=None
    )

    assert code == 0
    status = json.loads((root / "scheduled-sync-status.json").read_text(encoding="utf-8"))
    assert status["b62_pointer"]["published"] is False
    assert status["b62_pointer"]["skipped"] is True
    assert status["b62_pointer"]["reason"] == "b62_runtime_store_absent"


def test_a_failed_pointer_publish_fails_the_sync(tmp_path):
    root = _make_root(tmp_path)
    # A stub that publishes no generation leaves the publisher without a source.
    (root / "refresh_d1.py").write_text(REFRESH_STUB, encoding="utf-8")
    store = tmp_path / "b62-runtime" / "generation-store"
    store.parent.mkdir(parents=True, exist_ok=True)

    code = sync_ops.run_once(
        root, inventory_factory=_factory(), retry_delay=0, b62_store=store
    )

    assert code == 1
    status = json.loads((root / "scheduled-sync-status.json").read_text(encoding="utf-8"))
    assert status["failed_step"] == "b62_pointer"
    assert status["error"] == "b62_pointer_publish_failed"
    assert not (store / "current_generation.json").exists()

